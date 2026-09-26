"""页位几何（PressGeometry / SlotGeometry）与四接口坐标一致性回归测试。

press-layout 生成页位、locate-defects 反查纸面点、ink-zones 与 trim-safety
映射页内矩形，共用同一套双向坐标变换；本文件针对短边背面非对称矩形、
长边背面左右互换与页位边界做跨接口回归，并对全部槽位做一致性扫描，
防止各处独立计算产生坐标分歧。
"""
import pytest

from app.imposition import (
    PressGeometry,
    SlotGeometry,
    impose,
    ink_zones,
    locate_defects,
    press_layout,
    trim_safety,
)

# 扫描用统一参数：页宽 × 页高 × 中缝，纸面 210 × 150，右槽原点 x=110
PW, PH, GUTTER = 100.0, 150.0, 10.0
PAPER_W = 2 * PW + GUTTER
RIGHT_SLOT_X = PW + GUTTER
# 非对称页内矩形（不贴边、宽高不等），任何方向性错误都会暴露
RECT = (13.0, 17.0, 29.0, 41.0)


def _expected_paper_rect(placement, rect, page_width_mm=PW, page_height_mm=PH):
    """按规格书公式独立计算页内矩形的纸面映射（用于交叉核对各接口）。

    0°：纸面左上角 = 槽位原点 + 页内左上角；
    180°：纸面左上角 = (槽位 x + 页宽 − x − w, 槽位 y + 页高 − y − h)。
    """
    x, y, w, h = rect
    if placement["rotation_deg"] == 180:
        return (
            placement["x_mm"] + page_width_mm - x - w,
            placement["y_mm"] + page_height_mm - y - h,
            w,
            h,
        )
    return (placement["x_mm"] + x, placement["y_mm"] + y, w, h)


# ---------------------------------------------------------------------------
# SlotGeometry：双向坐标变换单元行为
# ---------------------------------------------------------------------------


def test_slot_geometry_point_round_trip_both_rotations():
    # 0° 与 180° 下，纸面点 -> 页内 -> 纸面 均还原（双向变换互逆）
    for rotation in (0, 180):
        geo = SlotGeometry(RIGHT_SLOT_X, 0.0, rotation, PW, PH)
        for point in ((0.0, 0.0), (13.5, 27.25), (100.0, 150.0), (100.0, 0.0)):
            assert geo.point_to_page(*geo.point_to_paper(*point)) == point


def test_slot_geometry_rect_180_maps_bottom_right_corner():
    # 180°：页内右下角 (13+29, 17+41) = (42, 58) 映射为纸面左上角 (58, 92)
    geo = SlotGeometry(0.0, 0.0, 180, PW, PH)
    assert geo.rect_to_paper(*RECT) == (58.0, 92.0, 29.0, 41.0)
    assert geo.point_to_paper(42.0, 58.0) == (58.0, 92.0)
    # 页内左上角映射为纸面右下角
    assert geo.point_to_paper(13.0, 17.0) == (87.0, 133.0)


def test_slot_geometry_rect_0_maps_top_left_corner():
    geo = SlotGeometry(RIGHT_SLOT_X, 0.0, 0, PW, PH)
    assert geo.rect_to_paper(*RECT) == (123.0, 17.0, 29.0, 41.0)
    assert geo.point_to_paper(13.0, 17.0) == (123.0, 17.0)


# ---------------------------------------------------------------------------
# PressGeometry：槽位原点、旋转角、落点分区与页码归属
# ---------------------------------------------------------------------------


def test_press_geometry_slot_origins_and_rotation():
    geo = PressGeometry(PW, PH, GUTTER, "short")
    assert geo.paper_width_mm == PAPER_W
    assert geo.paper_height_mm == PH
    assert geo.slot_origin("left") == (0.0, 0.0)
    assert geo.slot_origin("right") == (RIGHT_SLOT_X, 0.0)
    assert geo.rotation_deg("front") == 0
    assert geo.rotation_deg("back") == 180
    long_geo = PressGeometry(PW, PH, GUTTER, "long")
    assert long_geo.rotation_deg("front") == 0
    assert long_geo.rotation_deg("back") == 0


def test_press_geometry_slot_at_boundaries():
    geo = PressGeometry(PW, PH, GUTTER, "long")
    # 左槽 [0, 100)，中缝 [100, 110)，右槽 [110, 210]
    assert geo.slot_at(0.0) == "left"
    assert geo.slot_at(99.999) == "left"
    assert geo.slot_at(100.0) == "gutter"
    assert geo.slot_at(109.999) == "gutter"
    assert geo.slot_at(110.0) == "right"
    assert geo.slot_at(210.0) == "right"
    # 中缝为 0 时无中缝区间：x = 页宽直接落右槽
    zero = PressGeometry(PW, PH, 0.0, "long")
    assert zero.slot_at(100.0) == "right"


def test_press_geometry_page_at_applies_long_swap_only():
    # 4 页左装订：正面 (4, 1)、背面 (2, 3)
    sheet = impose(4, 1, "left")[0]["sheets"][0]
    long_geo = PressGeometry(PW, PH, GUTTER, "long")
    # long 背面左右槽互换
    assert long_geo.page_at(sheet, "back", "left") == 3
    assert long_geo.page_at(sheet, "back", "right") == 2
    short_geo = PressGeometry(PW, PH, GUTTER, "short")
    # short 背面保持槽位
    assert short_geo.page_at(sheet, "back", "left") == 2
    assert short_geo.page_at(sheet, "back", "right") == 3
    # 正面不受翻转方式影响
    for geo in (long_geo, short_geo):
        assert geo.page_at(sheet, "front", "left") == 4
        assert geo.page_at(sheet, "front", "right") == 1


def test_press_geometry_invalid_duplex_flip_raises():
    with pytest.raises(ValueError):
        PressGeometry(PW, PH, GUTTER, "side")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 短边翻转背面的非对称矩形：三个接口与 press-layout 逐一核对
# ---------------------------------------------------------------------------


def test_short_flip_back_asymmetric_rect_consistent_across_interfaces():
    # 4 页左装订、short 翻转：页 2 在背面左槽（x=0，旋转 180°）
    layout = press_layout(4, 1, "left", PW, PH, GUTTER, "short")
    placement = layout["signatures"][0]["sheets"][0]["back"]["left"]
    assert (placement["page"], placement["rotation_deg"]) == (2, 180)
    # 非对称矩形整体镜像：纸面左上角 = (100-13-29, 150-17-41) = (58, 92)
    expected = (58.0, 92.0, 29.0, 41.0)
    assert _expected_paper_rect(placement, RECT) == expected

    # trim-safety：违规记录中的纸面矩形
    trim = trim_safety(
        4, 1, "left", PW, PH, GUTTER, "short",
        outer_trim_mm=1000.0, fold_safety_mm=1000.0,
        page_protected=[(2, [RECT])],
    )
    assert {v["page"] for v in trim["violations"]} == {2}
    for v in trim["violations"]:
        assert (v["side"], v["sheet_index"]) == ("back", 1)
        r = v["rectangle"]
        assert (r["x_mm"], r["y_mm"], r["width_mm"], r["height_mm"]) == expected

    # locate-defects：纸面矩形中心反查为页内中心；矩形两角逐点核对
    located = locate_defects(
        4, 1, "left", PW, PH, GUTTER, "short",
        [
            (1, 1, "back", 72.5, 112.5),   # 纸面矩形中心
            (1, 1, "back", 58.0, 92.0),    # 纸面左上角 = 页内右下角 (42, 58)
            (1, 1, "back", 87.0, 133.0),   # 纸面右下角 = 页内左上角 (13, 17)
        ],
    )
    center, top_left, bottom_right = located["defects"]
    assert (center["page"], center["page_x_mm"], center["page_y_mm"]) == (2, 27.5, 37.5)
    assert (top_left["page_x_mm"], top_left["page_y_mm"]) == (42.0, 58.0)
    assert (bottom_right["page_x_mm"], bottom_right["page_y_mm"]) == (13.0, 17.0)

    # ink-zones：纸面 x 区间 [58, 87]，8 墨区（区宽 210/8 = 26.25）
    ink = ink_zones(
        4, 1, "left", PW, PH, GUTTER, "short",
        zone_count=8, copies=1,
        page_inks=[(2, [RECT + (1.0, 0.0, 0.0, 0.0)])],
    )
    sheet = ink["signatures"][0]["sheets"][0]
    assert "front" not in sheet
    back = {z["zone_index"]: z for z in sheet["back"]}
    # 区 3 [52.5, 78.75) 交叠 20.75；区 4 [78.75, 105) 交叠 8.25
    assert set(back) == {3, 4}
    assert back[3]["cyan_mm2"] == pytest.approx(20.75 * 41.0)
    assert back[4]["cyan_mm2"] == pytest.approx(8.25 * 41.0)


def test_short_flip_back_right_slot_asymmetric_rect():
    # 页 3 在背面右槽（x=110，旋转 180°）：纸面矩形 = (110+58, 92) = (168, 92)
    layout = press_layout(4, 1, "left", PW, PH, GUTTER, "short")
    placement = layout["signatures"][0]["sheets"][0]["back"]["right"]
    assert (placement["page"], placement["x_mm"]) == (3, RIGHT_SLOT_X)
    assert _expected_paper_rect(placement, RECT) == (168.0, 92.0, 29.0, 41.0)
    trim = trim_safety(
        4, 1, "left", PW, PH, GUTTER, "short",
        outer_trim_mm=1000.0, fold_safety_mm=1000.0,
        page_protected=[(3, [RECT])],
    )
    for v in trim["violations"]:
        r = v["rectangle"]
        assert (r["x_mm"], r["y_mm"], r["width_mm"], r["height_mm"]) == (
            168.0, 92.0, 29.0, 41.0,
        )
    located = locate_defects(
        4, 1, "left", PW, PH, GUTTER, "short",
        [(1, 1, "back", 182.5, 112.5)],
    )
    item = located["defects"][0]
    assert (item["page"], item["page_x_mm"], item["page_y_mm"]) == (3, 27.5, 37.5)


# ---------------------------------------------------------------------------
# 长边翻转背面左右互换：页码随新槽位，三个接口一致
# ---------------------------------------------------------------------------


def test_long_flip_back_swapped_slots_consistent_across_interfaces():
    # 8 页 2 张、左装订、long 翻转：impose 页序 张1 背(2,7)、张2 背(4,5)，
    # 背面左右槽互换后 张1 背左=7 背右=2、张2 背左=5 背右=4
    layout = press_layout(8, 2, "left", PW, PH, GUTTER, "long")
    sheets = layout["signatures"][0]["sheets"]
    assert sheets[0]["back"]["left"]["page"] == 7
    assert sheets[0]["back"]["right"]["page"] == 2
    assert sheets[1]["back"]["left"]["page"] == 5
    assert sheets[1]["back"]["right"]["page"] == 4
    # 坐标随新槽位、旋转 0
    left_slot = sheets[0]["back"]["left"]
    assert (left_slot["x_mm"], left_slot["y_mm"], left_slot["rotation_deg"]) == (0.0, 0.0, 0)
    right_slot = sheets[0]["back"]["right"]
    assert (right_slot["x_mm"], right_slot["y_mm"], right_slot["rotation_deg"]) == (
        RIGHT_SLOT_X, 0.0, 0,
    )

    # 页 7（张 1 背面左槽）：trim-safety 的纸面矩形即页内矩形平移到左槽
    trim = trim_safety(
        8, 2, "left", PW, PH, GUTTER, "long",
        outer_trim_mm=1000.0, fold_safety_mm=1000.0,
        page_protected=[(7, [RECT])],
    )
    assert {v["page"] for v in trim["violations"]} == {7}
    for v in trim["violations"]:
        assert (v["signature_index"], v["sheet_index"], v["side"]) == (1, 1, "back")
        r = v["rectangle"]
        assert (r["x_mm"], r["y_mm"], r["width_mm"], r["height_mm"]) == RECT

    # locate-defects：左槽内点反查为页 7，页内坐标即槽内坐标（0°）
    located = locate_defects(
        8, 2, "left", PW, PH, GUTTER, "long",
        [(1, 1, "back", 32.5, 50.0)],
    )
    item = located["defects"][0]
    assert (item["page"], item["page_x_mm"], item["page_y_mm"]) == (7, 32.5, 50.0)

    # ink-zones：页 7 矩形落在背面左槽 x 区间 [13, 42]，正面无着墨
    ink = ink_zones(
        8, 2, "left", PW, PH, GUTTER, "long",
        zone_count=7, copies=1,
        page_inks=[(7, [RECT + (0.0, 0.0, 0.0, 1.0)])],
    )
    sheet1 = ink["signatures"][0]["sheets"][0]
    assert "front" not in sheet1
    # 区宽 30：区 1 [0,30) 交叠 17、区 2 [30,60) 交叠 12
    back = {z["zone_index"]: z for z in sheet1["back"]}
    assert set(back) == {1, 2}
    assert back[1]["black_mm2"] == pytest.approx(17.0 * 41.0)
    assert back[2]["black_mm2"] == pytest.approx(12.0 * 41.0)


def test_long_flip_back_swap_with_right_binding():
    # 右装订镜像页序 + long 背面互换：张 1 背(7,2) -> 背左=2、背右=7
    layout = press_layout(8, 2, "right", PW, PH, GUTTER, "long")
    sheet1 = layout["signatures"][0]["sheets"][0]
    assert sheet1["back"]["left"]["page"] == 2
    assert sheet1["back"]["right"]["page"] == 7
    # 左槽内的点反查为页 2
    located = locate_defects(
        8, 2, "right", PW, PH, GUTTER, "long",
        [(1, 1, "back", 50.0, 75.0)],
    )
    assert located["defects"][0]["page"] == 2


# ---------------------------------------------------------------------------
# 页位边界：槽位边缘的点分类、贴边矩形与墨区边界
# ---------------------------------------------------------------------------


def test_slot_boundary_points_classified_consistently():
    # 边界点：x=0 左槽左缘、x=100 中缝起点、x=110 右槽原点、x=210 纸面右缘
    defects = [
        (1, 1, "front", 0.0, 0.0),       # 左槽左上角 -> 页 4 页内 (0, 0)
        (1, 1, "front", 100.0, 0.0),     # 中缝起点 -> gutter
        (1, 1, "front", 109.999, 0.0),   # 中缝末 -> gutter
        (1, 1, "front", 110.0, 0.0),     # 右槽原点 -> 页 1 页内 (0, 0)
        (1, 1, "front", 210.0, 150.0),   # 纸面右下角 -> 页 1 页内 (100, 150)
    ]
    result = locate_defects(4, 1, "left", PW, PH, GUTTER, "long", defects)
    locations = [d["location"] for d in result["defects"]]
    assert locations == ["page", "gutter", "gutter", "page", "page"]
    assert (result["defects"][0]["page"],
            result["defects"][0]["page_x_mm"],
            result["defects"][0]["page_y_mm"]) == (4, 0.0, 0.0)
    assert (result["defects"][3]["page"],
            result["defects"][3]["page_x_mm"],
            result["defects"][3]["page_y_mm"]) == (1, 0.0, 0.0)
    assert (result["defects"][4]["page_x_mm"],
            result["defects"][4]["page_y_mm"]) == (100.0, 150.0)


def test_short_flip_back_corner_points_inverted():
    # 180° 页位的边界点：槽位角点与页内角点交叉对应（左槽右缘 x=100 已入中缝，
    # 故左槽取左缘两角、右槽取四角，均为可精确分类的边界点）
    result = locate_defects(
        4, 1, "left", PW, PH, GUTTER, "short",
        [
            (1, 1, "back", 0.0, 0.0),      # 左槽左上角 -> 页 2 页内右下角 (100, 150)
            (1, 1, "back", 0.0, 150.0),    # 左槽左下角 -> 页 2 页内右上角 (100, 0)
            (1, 1, "back", 110.0, 0.0),    # 右槽左上角 -> 页 3 页内 (100, 150)
            (1, 1, "back", 210.0, 0.0),    # 右槽右上角 -> 页 3 页内 (0, 150)
            (1, 1, "back", 110.0, 150.0),  # 右槽左下角 -> 页 3 页内 (100, 0)
            (1, 1, "back", 210.0, 150.0),  # 右槽右下角 -> 页 3 页内 (0, 0)
        ],
    )
    expected = [
        (2, 100.0, 150.0),
        (2, 100.0, 0.0),
        (3, 100.0, 150.0),
        (3, 0.0, 150.0),
        (3, 100.0, 0.0),
        (3, 0.0, 0.0),
    ]
    for item, (page, page_x, page_y) in zip(result["defects"], expected):
        assert (item["page"], item["page_x_mm"], item["page_y_mm"]) == (
            page, page_x, page_y,
        )


def test_full_page_rect_maps_exactly_onto_slot():
    # 贴边矩形（铺满整页）映射后恰好铺满槽位：安全距离为 0 时四边贴线合格
    trim = trim_safety(
        4, 1, "left", PW, PH, GUTTER, "short",
        outer_trim_mm=0.0, fold_safety_mm=0.0,
        page_protected=[(2, [(0.0, 0.0, PW, PH)])],
    )
    assert trim["violations"] == []
    # 安全距离为正：纸面矩形恰好是左槽外框 (0, 0, 100, 150)
    trim = trim_safety(
        4, 1, "left", PW, PH, GUTTER, "short",
        outer_trim_mm=1.0, fold_safety_mm=1.0,
        page_protected=[(2, [(0.0, 0.0, PW, PH)])],
    )
    assert [v["edge"] for v in trim["violations"]] == ["top", "bottom", "outer"]
    for v in trim["violations"]:
        r = v["rectangle"]
        assert (r["x_mm"], r["y_mm"], r["width_mm"], r["height_mm"]) == (
            0.0, 0.0, PW, PH,
        )


def test_zone_boundary_exact_no_spillover():
    # 无中缝：纸面 200，2 墨区各宽 100，槽位与墨区边界重合
    # 左槽满页矩形（页 4）只落区 1，右槽满页矩形（页 1）只落区 2，互不串区
    ink = ink_zones(
        4, 1, "left", PW, PH, 0.0, "long",
        zone_count=2, copies=1,
        page_inks=[
            (4, [(0.0, 0.0, PW, PH, 1.0, 0.0, 0.0, 0.0)]),
            (1, [(0.0, 0.0, PW, PH, 0.0, 1.0, 0.0, 0.0)]),
        ],
    )
    front = {z["zone_index"]: z for z in ink["signatures"][0]["sheets"][0]["front"]}
    assert set(front) == {1, 2}
    assert front[1]["cyan_mm2"] == pytest.approx(PW * PH)
    assert front[1]["magenta_mm2"] == 0.0
    assert front[2]["magenta_mm2"] == pytest.approx(PW * PH)
    assert front[2]["cyan_mm2"] == 0.0


# ---------------------------------------------------------------------------
# 全槽位跨接口一致性扫描：装订方向 × 翻转方式 × 多帖多张
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("binding", ["left", "right"])
@pytest.mark.parametrize("duplex_flip", ["long", "short"])
def test_all_slots_consistent_across_interfaces(binding, duplex_flip):
    # 12 页、每帖最多 2 张：帖 1 共 8 页 2 张，帖 2 共 4 页 1 张
    total_pages, max_sheets = 12, 2
    zone_count = 8
    layout = press_layout(total_pages, max_sheets, binding, PW, PH, GUTTER, duplex_flip)
    zone_width = layout["paper_width_mm"] / zone_count

    # 收集每个非空槽位及其按规格书公式独立计算的纸面矩形
    slots_info = []
    for sig in layout["signatures"]:
        for sheet in sig["sheets"]:
            for side in ("front", "back"):
                for slot in ("left", "right"):
                    placement = sheet[side][slot]
                    if placement is None:
                        continue
                    expected = _expected_paper_rect(placement, RECT)
                    slots_info.append(
                        (sig["signature_index"], sheet["sheet_index"], side,
                         placement["page"], expected)
                    )
    assert slots_info  # 本用例无空白页位

    # trim-safety：超大安全距离使每个矩形都报违规，逐页读出纸面矩形
    trim = trim_safety(
        total_pages, max_sheets, binding, PW, PH, GUTTER, duplex_flip,
        outer_trim_mm=1000.0, fold_safety_mm=1000.0,
        page_protected=[(page, [RECT]) for page in range(1, total_pages + 1)],
    )
    trim_rects = {}
    for v in trim["violations"]:
        key = (v["signature_index"], v["sheet_index"], v["side"], v["page"])
        r = v["rectangle"]
        rect_tuple = (r["x_mm"], r["y_mm"], r["width_mm"], r["height_mm"])
        # 同一页各边违规的纸面矩形必须一致
        assert trim_rects.get(key, rect_tuple) == rect_tuple
        trim_rects[key] = rect_tuple

    # locate-defects：每个纸面矩形的中心点反查
    defects = [
        (sig_idx, sheet_idx, side, ex[0] + ex[2] / 2.0, ex[1] + ex[3] / 2.0)
        for sig_idx, sheet_idx, side, _page, ex in slots_info
    ]
    located = locate_defects(
        total_pages, max_sheets, binding, PW, PH, GUTTER, duplex_flip, defects
    )

    # ink-zones：按墨区交叠面积核对纸面 x 区间（同一面两个槽位的贡献累加）
    ink = ink_zones(
        total_pages, max_sheets, binding, PW, PH, GUTTER, duplex_flip,
        zone_count=zone_count, copies=1,
        page_inks=[
            (page, [RECT + (1.0, 0.0, 0.0, 0.0)])
            for page in range(1, total_pages + 1)
        ],
    )
    ink_zones_by_side = {}
    for sig in ink["signatures"]:
        for sheet in sig["sheets"]:
            for side in ("front", "back"):
                if side in sheet:
                    key = (sig["signature_index"], sheet["sheet_index"], side)
                    ink_zones_by_side[key] = {
                        z["zone_index"]: z["cyan_mm2"] for z in sheet[side]
                    }

    expected_side_zones = {}
    for sig_idx, sheet_idx, side, page, ex in slots_info:
        px, _py, w, h = ex
        # trim-safety 的纸面矩形与规格书公式一致
        assert trim_rects[(sig_idx, sheet_idx, side, page)] == pytest.approx(ex)
        # ink-zones 的期望交叠
        key = (sig_idx, sheet_idx, side)
        zones_for_side = expected_side_zones.setdefault(key, {})
        for z in range(zone_count):
            overlap = min(px + w, (z + 1) * zone_width) - max(px, z * zone_width)
            if overlap > 0:
                zones_for_side[z + 1] = zones_for_side.get(z + 1, 0.0) + overlap * h

    # locate-defects：中心点反查回原页、页内坐标为矩形中心
    assert located["defect_count"] == len(slots_info)
    for item, (_sig_idx, _sheet_idx, _side, page, _ex) in zip(
        located["defects"], slots_info
    ):
        assert item["location"] == "page"
        assert item["page"] == page
        assert item["page_x_mm"] == pytest.approx(RECT[0] + RECT[2] / 2.0)
        assert item["page_y_mm"] == pytest.approx(RECT[1] + RECT[3] / 2.0)

    # ink-zones：各面墨区集合与交叠面积一致
    for key, expected_zones in expected_side_zones.items():
        actual = ink_zones_by_side.get(key, {})
        assert actual.keys() == expected_zones.keys()
        for zone_index, cyan in expected_zones.items():
            assert actual[zone_index] == pytest.approx(cyan)


@pytest.mark.parametrize("duplex_flip", ["long", "short"])
def test_blank_slots_and_gutter_marked_consistently(duplex_flip):
    # 5 页补 3 空白（1 帖 2 张）：空白页位反查为 blank，中缝点为 gutter
    layout = press_layout(5, 2, "left", PW, PH, GUTTER, duplex_flip)
    defects = []
    expected_locations = []
    for sig in layout["signatures"]:
        for sheet in sig["sheets"]:
            for side in ("front", "back"):
                for slot, origin_x in (("left", 0.0), ("right", RIGHT_SLOT_X)):
                    if sheet[side][slot] is None:
                        defects.append(
                            (sig["signature_index"], sheet["sheet_index"], side,
                             origin_x + PW / 2.0, PH / 2.0)
                        )
                        expected_locations.append("blank")
    assert expected_locations  # 本用例确有空白页位
    # 中缝中心点
    defects.append((1, 1, "front", PW + GUTTER / 2.0, PH / 2.0))
    expected_locations.append("gutter")

    result = locate_defects(5, 2, "left", PW, PH, GUTTER, duplex_flip, defects)
    assert [d["location"] for d in result["defects"]] == expected_locations
    # 中缝与空白页位均不返回页码与页内坐标
    for item in result["defects"]:
        assert item["page"] is None
        assert item["page_x_mm"] is None
        assert item["page_y_mm"] is None
