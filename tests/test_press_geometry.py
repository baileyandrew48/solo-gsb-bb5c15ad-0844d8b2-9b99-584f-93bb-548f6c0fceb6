"""共享页位几何（press_geometry）与跨接口坐标一致性回归测试。

覆盖任务要求的三类回归点：

1. 短边背面（short + back）非对称矩形：180° 旋转宽高不交换、点/矩形往返一致；
2. 长边背面（long + back）左右互换：实际槽位页码来自拼版背面的对侧槽位；
3. 页位边界：槽位/中缝/右槽分界、纸面四角与整页贴边矩形。

另含 locate-defects / ink-zones / trim-safety 与 press-layout 的跨接口一致性，
确保四个接口不再各自独立计算坐标。
"""
from __future__ import annotations

import pytest

from app.imposition import (
    ink_zones,
    locate_defects,
    press_layout,
    trim_safety,
)
from app.press_geometry import Placement, PressGeometry, placement_payload


def _geometry(**overrides) -> PressGeometry:
    params = {
        "page_width_mm": 210.0,
        "page_height_mm": 297.0,
        "gutter_mm": 10.0,
        "duplex_flip": "long",
    }
    params.update(overrides)
    return PressGeometry(**params)


def _placement(page, side, slot, geometry, rotation=None) -> Placement:
    rot = rotation if rotation is not None else geometry.side_rotation_deg(side)
    return Placement(
        page=page,
        side=side,
        slot=slot,
        x_mm=geometry.slot_origin_x_mm(slot),
        y_mm=0.0,
        rotation_deg=rot,
    )


# 4 页左装订的最外张拼版结果：正面 (4, 1)、背面 (2, 3)
IMPOSED_SHEET = {
    "sheet_index": 1,
    "front": {"left": 4, "right": 1},
    "back": {"left": 2, "right": 3},
}


# ---------------------------------------------------------------------------
# 槽位原点与旋转角
# ---------------------------------------------------------------------------


def test_slot_origins_and_paper_size():
    g = _geometry()
    assert g.paper_width_mm == 430.0
    assert g.paper_height_mm == 297.0
    assert g.fold_x_mm == 215.0
    assert g.slot_origin_x_mm("left") == 0.0
    assert g.slot_origin_x_mm("right") == 220.0
    assert g.side_rotation_deg("front") == 0
    assert _geometry(duplex_flip="long").side_rotation_deg("back") == 0
    assert _geometry(duplex_flip="short").side_rotation_deg("back") == 180


def test_invalid_flip_rejected():
    with pytest.raises(ValueError):
        PressGeometry(210.0, 297.0, 0.0, "side")  # type: ignore[arg-type]


def test_placement_payload_null_for_blank():
    assert placement_payload(None) is None
    g = _geometry()
    p = _placement(7, "front", "right", g)
    assert placement_payload(p) == {
        "page": 7,
        "x_mm": 220.0,
        "y_mm": 0.0,
        "rotation_deg": 0,
    }


# ---------------------------------------------------------------------------
# 长边背面左右互换 / 短边背面保持槽位
# ---------------------------------------------------------------------------


def test_long_back_swaps_left_and_right_slots():
    g = _geometry(duplex_flip="long")
    placed = g.place_sheet(IMPOSED_SHEET)
    # 正面槽位不变
    assert placed["front"]["left"].page == 4
    assert placed["front"]["right"].page == 1
    # long 背面互换：拼版背面 (2, 3) -> 实际左槽 3、右槽 2，旋转均为 0
    assert placed["back"]["left"].page == 3
    assert placed["back"]["left"].slot == "left"
    assert placed["back"]["left"].x_mm == 0.0
    assert placed["back"]["left"].rotation_deg == 0
    assert placed["back"]["right"].page == 2
    assert placed["back"]["right"].slot == "right"
    assert placed["back"]["right"].x_mm == 220.0
    assert placed["back"]["right"].rotation_deg == 0


def test_long_back_swap_with_right_binding():
    # 右装订拼版：正面 (1, 4)、背面 (3, 2)
    imposed = {
        "sheet_index": 1,
        "front": {"left": 1, "right": 4},
        "back": {"left": 3, "right": 2},
    }
    g = _geometry(duplex_flip="long", gutter_mm=0.0)
    placed = g.place_sheet(imposed)
    # long 互换：实际背面左槽 = 拼版背右 = 2，右槽 = 拼版背左 = 3
    assert placed["back"]["left"].page == 2
    assert placed["back"]["right"].page == 3
    assert placed["back"]["left"].x_mm == 0.0
    assert placed["back"]["right"].x_mm == 210.0


def test_short_back_keeps_slots_and_rotates_180():
    g = _geometry(duplex_flip="short", gutter_mm=0.0)
    placed = g.place_sheet(IMPOSED_SHEET)
    # short 背面保持槽位：背左 = 2、背右 = 3，旋转 180
    assert placed["back"]["left"].page == 2
    assert placed["back"]["left"].x_mm == 0.0
    assert placed["back"]["left"].rotation_deg == 180
    assert placed["back"]["right"].page == 3
    assert placed["back"]["right"].x_mm == 210.0
    assert placed["back"]["right"].rotation_deg == 180
    # 空白页位为 None
    imposed_with_blank = {
        "sheet_index": 1,
        "front": {"left": None, "right": 1},
        "back": {"left": None, "right": None},
    }
    blanks = g.place_sheet(imposed_with_blank)
    assert blanks["front"]["left"] is None
    assert blanks["back"]["left"] is None
    assert blanks["back"]["right"] is None


# ---------------------------------------------------------------------------
# 点的双向变换（往返一致）
# ---------------------------------------------------------------------------


def test_point_roundtrip_front_and_long_back():
    g = _geometry(duplex_flip="long")
    for slot in ("left", "right"):
        for side in ("front", "back"):
            p = _placement(1, side, slot, g)
            for px, py in [(0.0, 0.0), (33.3, 77.7), (210.0, 297.0)]:
                sx, sy = g.page_to_paper_point(p, px, py)
                back_x, back_y = g.paper_to_page_point(p, sx, sy)
                assert back_x == pytest.approx(px)
                assert back_y == pytest.approx(py)


def test_short_back_point_roundtrip_and_corner_flip():
    g = _geometry(duplex_flip="short", gutter_mm=0.0)
    p = _placement(2, "back", "left", g)
    # 阅读方向左上角 -> 纸面槽位右下角（180°）
    assert g.page_to_paper_point(p, 0.0, 0.0) == (210.0, 297.0)
    # 纸面槽位左上角 -> 阅读方向右下角
    assert g.paper_to_page_point(p, 0.0, 0.0) == (210.0, 297.0)
    # 任意点往返一致
    for px, py in [(1.5, 2.5), (100.0, 100.0), (209.9, 296.1)]:
        sx, sy = g.page_to_paper_point(p, px, py)
        bx, by = g.paper_to_page_point(p, sx, sy)
        assert bx == pytest.approx(px)
        assert by == pytest.approx(py)
    # 右槽 180°：槽位原点 x=210
    pr = _placement(3, "back", "right", g)
    sx, sy = g.page_to_paper_point(pr, 10.0, 20.0)
    assert sx == pytest.approx(210.0 + 210.0 - 10.0)
    assert sy == pytest.approx(297.0 - 20.0)


# ---------------------------------------------------------------------------
# 短边背面非对称矩形
# ---------------------------------------------------------------------------


def test_short_back_asymmetric_rect_keeps_width_height():
    g = _geometry(duplex_flip="short", gutter_mm=0.0)
    p = _placement(2, "back", "left", g)
    # 非对称矩形（宽 40、高 90）：180° 后宽高不得交换
    px, py, pw, ph = g.page_rect_to_paper(p, 10.0, 20.0, 40.0, 90.0)
    assert (pw, ph) == (40.0, 90.0)
    assert px == pytest.approx(210.0 - 10.0 - 40.0)   # 160
    assert py == pytest.approx(297.0 - 20.0 - 90.0)   # 187
    # 往返一致
    rx, ry, rw, rh = g.paper_rect_to_page(p, px, py, pw, ph)
    assert (rx, ry, rw, rh) == pytest.approx((10.0, 20.0, 40.0, 90.0))


def test_short_back_asymmetric_rect_all_corners_roundtrip():
    g = _geometry(duplex_flip="short", gutter_mm=5.0)
    p = _placement(3, "back", "right", g)
    origin_x = g.slot_origin_x_mm("right")
    # 非对称矩形四个角：页内 -> 纸面 -> 页内，角点集合不变
    rect = (12.5, 30.0, 70.0, 13.0)
    px, py, pw, ph = g.page_rect_to_paper(p, *rect)
    page_corners = {
        (rect[0], rect[1]),
        (rect[0] + rect[2], rect[1]),
        (rect[0], rect[1] + rect[3]),
        (rect[0] + rect[2], rect[1] + rect[3]),
    }
    paper_corners = set()
    for cx, cy in page_corners:
        paper_corners.add(g.page_to_paper_point(p, cx, cy))
    # 纸面矩形四角必须与角点变换结果一致
    rect_corners = {
        (px, py), (px + pw, py), (px, py + ph), (px + pw, py + ph)
    }
    assert sorted(rect_corners) == pytest.approx(sorted(paper_corners))
    # 全部落在该右槽范围内（不进中缝、不出纸面）
    for cx, cy in paper_corners:
        assert origin_x <= cx <= g.paper_width_mm
        assert 0.0 <= cy <= g.page_height_mm
    # 逆变换还原矩形
    assert g.paper_rect_to_page(p, px, py, pw, ph) == pytest.approx(rect)


def test_full_page_rect_maps_slot_to_slot_under_180():
    # 整页贴边矩形在 180° 下应铺满同一槽位（外接框不变）
    g = _geometry(duplex_flip="short", gutter_mm=8.0)
    for slot in ("left", "right"):
        p = _placement(1, "back", slot, g)
        px, py, pw, ph = g.page_rect_to_paper(
            p, 0.0, 0.0, g.page_width_mm, g.page_height_mm
        )
        assert (px, py, pw, ph) == (
            g.slot_origin_x_mm(slot), 0.0, g.page_width_mm, g.page_height_mm
        )


# ---------------------------------------------------------------------------
# 区域判定与纸面边界
# ---------------------------------------------------------------------------


def test_region_boundaries_with_and_without_gutter():
    g = _geometry(gutter_mm=10.0)  # 左槽 [0,210)、中缝 [210,220)、右槽 [220,430]
    assert g.region_at_x(0.0) == "left"
    assert g.region_at_x(209.999) == "left"
    assert g.region_at_x(210.0) == "gutter"
    assert g.region_at_x(215.0) == "gutter"
    assert g.region_at_x(219.999) == "gutter"
    assert g.region_at_x(220.0) == "right"
    assert g.region_at_x(430.0) == "right"
    # 无中缝：x=页宽直接进右槽
    g0 = _geometry(gutter_mm=0.0)
    assert g0.region_at_x(209.999) == "left"
    assert g0.region_at_x(210.0) == "right"
    assert g0.region_at_x(420.0) == "right"


def test_paper_edges_contained_but_not_outside_or_non_finite():
    g = _geometry()
    for x, y in [(0.0, 0.0), (430.0, 297.0), (430.0, 0.0), (0.0, 297.0)]:
        assert g.contains_paper_point(x, y)
    for x, y in [
        (-0.1, 10.0), (430.1, 10.0), (10.0, -0.1), (10.0, 297.1),
        (float("nan"), 10.0), (10.0, float("inf")),
    ]:
        assert not g.contains_paper_point(x, y)


# ---------------------------------------------------------------------------
# 页位边界回归：press-layout 与共享几何完全一致
# ---------------------------------------------------------------------------


def test_press_layout_placements_match_shared_geometry():
    for flip in ("long", "short"):
        for binding in ("left", "right"):
            g = _geometry(duplex_flip=flip, gutter_mm=10.0)
            layout = press_layout(4, 1, binding, 210.0, 297.0, 10.0, flip)
            sheet = layout["signatures"][0]["sheets"][0]
            # 右装订用其自身拼版结果重建预期页位
            imposed = {
                "front": {
                    "left": 4 if binding == "left" else 1,
                    "right": 1 if binding == "left" else 4,
                },
                "back": {
                    "left": 2 if binding == "left" else 3,
                    "right": 3 if binding == "left" else 2,
                },
            }
            expected = g.place_sheet(imposed)
            for side in ("front", "back"):
                for slot in ("left", "right"):
                    exp = expected[side][slot]
                    got = sheet[side][slot]
                    assert got == placement_payload(exp)


# ---------------------------------------------------------------------------
# 跨接口一致性：locate / ink / trim 与共享几何同源
# ---------------------------------------------------------------------------


def test_locate_defects_uses_shared_point_transform():
    # short 背面左槽（第 2 页，180°）：纸面点 (40,60) -> 页内 (170,237)
    result = locate_defects(
        total_pages=4,
        max_sheets=1,
        binding="left",
        page_width_mm=210.0,
        page_height_mm=297.0,
        gutter_mm=0.0,
        duplex_flip="short",
        defects=[(1, 1, "back", 40.0, 60.0)],
    )
    item = result["defects"][0]
    assert item["location"] == "page"
    assert item["page"] == 2
    assert item["page_x_mm"] == pytest.approx(170.0)
    assert item["page_y_mm"] == pytest.approx(237.0)


def test_locate_paper_corners_short_back_boundaries():
    # short 背面四角（无中缝，纸面 420×297）均落在页内且坐标逆转正确
    result = locate_defects(
        total_pages=4,
        max_sheets=1,
        binding="left",
        page_width_mm=210.0,
        page_height_mm=297.0,
        gutter_mm=0.0,
        duplex_flip="short",
        defects=[
            (1, 1, "back", 0.0, 0.0),
            (1, 1, "back", 210.0, 0.0),
            (1, 1, "back", 420.0, 297.0),
        ],
    )
    d1, d2, d3 = result["defects"]
    # 纸面 (0,0) 在背左槽（第 2 页）-> 页内右下角
    assert (d1["page"], d1["page_x_mm"], d1["page_y_mm"]) == (2, 210.0, 297.0)
    # x=210 是右槽起点（无中缝）-> 背右槽第 3 页页内右下角
    assert (d2["page"], d2["page_x_mm"], d2["page_y_mm"]) == (3, 210.0, 297.0)
    # 纸面右下角 -> 背右槽第 3 页页内左上角
    assert (d3["page"], d3["page_x_mm"], d3["page_y_mm"]) == (3, 0.0, 0.0)


def test_locate_long_back_swapped_slot_boundary():
    # long 背面 + 中缝：右槽起点 x=220 落在交换后的右槽（第 2 页），页内 (0,0)
    result = locate_defects(
        total_pages=4,
        max_sheets=1,
        binding="left",
        page_width_mm=210.0,
        page_height_mm=297.0,
        gutter_mm=10.0,
        duplex_flip="long",
        defects=[
            (1, 1, "back", 0.0, 0.0),
            (1, 1, "back", 220.0, 0.0),
            (1, 1, "back", 210.0, 0.0),
            (1, 1, "back", 219.999, 0.0),
        ],
    )
    left, right, gutter_a, gutter_b = result["defects"]
    assert (left["location"], left["page"]) == ("page", 3)
    assert (right["location"], right["page"], right["page_x_mm"]) == ("page", 2, 0.0)
    assert gutter_a["location"] == "gutter"
    assert gutter_b["location"] == "gutter"


def test_ink_zones_short_back_asymmetric_rect_matches_trim_safety():
    # 同一非对称页内矩形（第 2 页，short 背面左槽 180°）：
    # ink-zones 的墨区拆分必须与 trim-safety 返回的纸面矩形、共享几何一致
    g = _geometry(page_width_mm=100.0, page_height_mm=100.0, gutter_mm=0.0,
                  duplex_flip="short")
    p = _placement(2, "back", "left", g)
    px, py, pw, ph = g.page_rect_to_paper(p, 10.0, 20.0, 30.0, 70.0)
    assert (px, py, pw, ph) == (60.0, 10.0, 30.0, 70.0)

    # ink-zones：纸面 200、4 墨区每区 50 -> 纸面 60..90 跨区 2（50..100），
    # 面积 30×70=2100，K=1，印数 1
    ink = ink_zones(
        total_pages=4,
        max_sheets=1,
        binding="left",
        page_width_mm=100.0,
        page_height_mm=100.0,
        gutter_mm=0.0,
        duplex_flip="short",
        zone_count=4,
        copies=1,
        page_inks=[(2, [(10.0, 20.0, 30.0, 70.0, 0.0, 0.0, 0.0, 1.0)])],
    )
    back = {z["zone_index"]: z for z in ink["signatures"][0]["sheets"][0]["back"]}
    assert list(back) == [2]
    assert back[2]["black_mm2"] == pytest.approx(2100.0)

    # trim-safety：同一矩形映射到同一纸面矩形（右缘 90 越过左槽折缝安全线）
    trim = trim_safety(
        total_pages=4,
        max_sheets=1,
        binding="left",
        page_width_mm=100.0,
        page_height_mm=100.0,
        gutter_mm=0.0,
        duplex_flip="short",
        outer_trim_mm=0.0,
        fold_safety_mm=20.0,
        page_protected=[(2, [(10.0, 20.0, 30.0, 70.0)])],
    )
    fold_violations = [v for v in trim["violations"] if v["edge"] == "fold"]
    assert len(fold_violations) == 1
    assert fold_violations[0]["side"] == "back"
    assert fold_violations[0]["page"] == 2
    assert fold_violations[0]["rectangle"] == {
        "x_mm": 60.0, "y_mm": 10.0, "width_mm": 30.0, "height_mm": 70.0,
    }


def test_long_back_page_agreement_across_three_apis():
    # long 背面第 2 页在实际右槽（x=100，页宽 100、无中缝）：
    # locate / ink / trim 三个接口对该页位置必须给出一致结果
    common = dict(
        total_pages=4,
        max_sheets=1,
        binding="left",
        page_width_mm=100.0,
        page_height_mm=100.0,
        gutter_mm=0.0,
        duplex_flip="long",
    )
    # locate：纸面 (100,0) -> 第 2 页页内 (0,0)
    located = locate_defects(
        **common, defects=[(1, 1, "back", 100.0, 0.0)]
    )["defects"][0]
    assert (located["page"], located["page_x_mm"], located["page_y_mm"]) == (
        2, 0.0, 0.0
    )
    # ink：第 2 页页内 (0,0,50,100) -> 纸面 100..150 落区 3（4 墨区）
    ink = ink_zones(
        **common,
        zone_count=4,
        copies=1,
        page_inks=[(2, [(0.0, 0.0, 50.0, 100.0, 1.0, 0.0, 0.0, 0.0)])],
    )
    back = {z["zone_index"]: z for z in ink["signatures"][0]["sheets"][0]["back"]}
    assert back[3]["cyan_mm2"] == pytest.approx(5000.0)
    # trim：同一矩形左缘在纸面 100（折缝线），fold 安全 1 时越线
    trim = trim_safety(
        **common,
        outer_trim_mm=0.0,
        fold_safety_mm=1.0,
        page_protected=[(2, [(0.0, 0.0, 50.0, 100.0)])],
    )
    edges = [(v["side"], v["page"], v["edge"], v["rectangle"]["x_mm"])
             for v in trim["violations"]]
    assert ("back", 2, "fold", 100.0) in edges


def test_right_binding_short_back_asymmetric_rect_roundtrip():
    # 右装订 + short 背面：背左 = 第 3 页（保持槽位、180°），非对称矩形往返
    g = _geometry(page_width_mm=100.0, page_height_mm=100.0, gutter_mm=0.0,
                  duplex_flip="short")
    imposed = {
        "sheet_index": 1,
        "front": {"left": 1, "right": 4},
        "back": {"left": 3, "right": 2},
    }
    placed = g.place_sheet(imposed)
    p = placed["back"]["left"]
    assert (p.page, p.x_mm, p.rotation_deg) == (3, 0.0, 180)
    rect = (5.0, 15.0, 80.0, 20.0)  # 宽 80、高 20 的非对称矩形
    paper_rect = g.page_rect_to_paper(p, *rect)
    assert paper_rect[2:] == (80.0, 20.0)
    assert g.paper_rect_to_page(p, *paper_rect) == pytest.approx(rect)
