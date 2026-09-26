"""外裁/折缝安全检查（trim-safety）算法单元测试。"""
import pytest

from app.imposition import trim_safety


def _trim(page_protected, *, outer_trim_mm=10.0, fold_safety_mm=5.0, **overrides):
    """默认 4 页 1 张、左装订、页宽/页高 100、无中缝、long 翻转。"""
    params = {
        "total_pages": 4,
        "max_sheets": 1,
        "binding": "left",
        "page_width_mm": 100.0,
        "page_height_mm": 100.0,
        "gutter_mm": 0.0,
        "duplex_flip": "long",
        "outer_trim_mm": outer_trim_mm,
        "fold_safety_mm": fold_safety_mm,
        "page_protected": page_protected,
    }
    params.update(overrides)
    return trim_safety(**params)


def _edges(result):
    """取全部违规的 (帖, 张, 面, 页, 边) 列表。"""
    return [
        (
            v["signature_index"],
            v["sheet_index"],
            v["side"],
            v["page"],
            v["edge"],
        )
        for v in result["violations"]
    ]


def test_response_echoes_layout_and_safety_parameters():
    result = _trim([], outer_trim_mm=12.5, fold_safety_mm=7.5, gutter_mm=20.0)
    assert result["paper_width_mm"] == 220.0
    assert result["paper_height_mm"] == 100.0
    assert result["outer_trim_mm"] == 12.5
    assert result["fold_safety_mm"] == 7.5
    assert result["violation_count"] == 0
    assert result["violations"] == []


def test_front_right_slot_fold_violation():
    # 左装订正面：右槽 = 第 1 页（x=100）；折缝线 x=100
    # 页内 0..10 -> 纸面 100..110，左边 100 越过折缝安全线 105
    result = _trim([(1, [(0, 50, 10, 10)])])
    assert result["violation_count"] == 1
    v = result["violations"][0]
    assert _edges(result) == [(1, 1, "front", 1, "fold")]
    assert v["rectangle"] == {
        "x_mm": 100.0, "y_mm": 50.0, "width_mm": 10.0, "height_mm": 10.0
    }


def test_touching_safe_lines_passes():
    # 右槽第 1 页，折缝安全线 105：页内 5..15 -> 纸面 105..115，左边恰好 105，合格
    result = _trim([(1, [(5, 50, 10, 10)])])
    assert result["violations"] == []
    # 外侧竖边：右槽右缘安全线 = 200-10 = 190
    # 页内 (85,50,10,10) -> 纸面 185..195，右缘 195 > 190 越线（左缘 185 不越折缝）
    # 页内 (80,50,10,10) -> 纸面 180..190，右缘恰好 190 贴线，合格
    result = _trim([(1, [(85, 50, 10, 10)])])
    assert _edges(result) == [(1, 1, "front", 1, "outer")]
    result = _trim([(1, [(80, 50, 10, 10)])])
    assert result["violations"] == []
    # 顶边 / 底边恰好压线
    result = _trim([(1, [(50, 10, 10, 10)])])
    assert result["violations"] == []
    result = _trim([(1, [(50, 80, 10, 10)])])
    assert result["violations"] == []
    # 左槽第 4 页：外侧左缘恰好 10、折缝侧右缘恰好 95（100-5）
    result = _trim([
        (4, [(10, 10, 80, 80)]),
    ])
    assert result["violations"] == []


def test_zero_safety_distances_touches_paper_edges():
    # 安全距离全 0：矩形铺满整页（映射后铺满槽位、右缘压折缝线）仍合格
    result = _trim(
        [(1, [(0, 0, 100, 100)])],
        outer_trim_mm=0.0,
        fold_safety_mm=0.0,
    )
    assert result["violations"] == []


def test_each_outer_edge_violation():
    # 左槽第 4 页（x=0）：分别越过顶、底、外侧（左缘）
    result = _trim([(4, [(50, 5, 10, 10)])])  # 纸面 y 5..15，顶安全线 10
    assert _edges(result) == [(1, 1, "front", 4, "top")]
    result = _trim([(4, [(50, 90, 10, 10)])])  # 纸面 y 90..100，底安全线 90
    assert _edges(result) == [(1, 1, "front", 4, "bottom")]
    result = _trim([(4, [(5, 50, 10, 10)])])  # 纸面 x 5..15，外侧安全线 10
    assert _edges(result) == [(1, 1, "front", 4, "outer")]
    # 右槽第 1 页外侧在纸右缘：页内 90..100 -> 纸面 190..200，右缘越线
    result = _trim([(1, [(85, 50, 10, 10)])])
    assert _edges(result) == [(1, 1, "front", 1, "outer")]


def test_rectangle_crossing_multiple_edges_reports_each():
    # 左槽第 4 页整页出血矩形 0..100：顶、底、外侧、折缝四线全越
    result = _trim(
        [(4, [(0, 0, 100, 100)])],
        outer_trim_mm=10.0,
        fold_safety_mm=5.0,
    )
    assert _edges(result) == [
        (1, 1, "front", 4, "top"),
        (1, 1, "front", 4, "bottom"),
        (1, 1, "front", 4, "outer"),
        (1, 1, "front", 4, "fold"),
    ]
    # 每边一条，纸面矩形相同
    rects = {v["edge"]: v["rectangle"] for v in result["violations"]}
    assert all(
        rect == {"x_mm": 0.0, "y_mm": 0.0, "width_mm": 100.0, "height_mm": 100.0}
        for rect in rects.values()
    )


def test_long_flip_back_uses_swapped_slots():
    # long 背面交换槽位：左槽 = 第 3 页（x=0），右槽 = 第 2 页（x=100）
    # 第 2 页页内 0..5 -> 纸面 100..105，左缘越折缝安全线 105 失败（100<105）
    result = _trim([(2, [(0, 50, 5, 10)])])
    assert _edges(result) == [(1, 1, "back", 2, "fold")]
    # 第 3 页在左槽，页内 0..5 -> 纸面 0..5，越外侧安全线
    result = _trim([(3, [(0, 50, 5, 10)])])
    assert _edges(result) == [(1, 1, "back", 3, "outer")]


def test_short_flip_back_rotates_180():
    # short 背面保持槽位：背左 = 第 2 页（x=0）、背右 = 第 3 页（x=100），均旋转 180
    # 第 2 页页内右下角 (90,90,10,10)（阅读方向外缘）-> 纸面 (0,0,10,10)：
    # 越顶边与外侧竖边
    result = _trim(
        [(2, [(90, 90, 10, 10)])],
        duplex_flip="short",
    )
    assert _edges(result) == [
        (1, 1, "back", 2, "top"),
        (1, 1, "back", 2, "outer"),
    ]
    top_rect = result["violations"][0]["rectangle"]
    assert top_rect == {"x_mm": 0.0, "y_mm": 0.0, "width_mm": 10.0, "height_mm": 10.0}
    # 第 2 页阅读方向装订边（页内左缘 0..10）-> 纸面 90..100，右缘压折缝线，
    # 折缝安全 5 时越线
    result = _trim(
        [(2, [(0, 50, 10, 10)])],
        duplex_flip="short",
    )
    assert _edges(result) == [(1, 1, "back", 2, "fold")]
    fold_rect = result["violations"][0]["rectangle"]
    assert fold_rect["x_mm"] == 90.0 and fold_rect["width_mm"] == 10.0
    # 第 3 页右槽旋转 180：页内 (10,40,5,20) -> 纸面 (185,40,5,20)，
    # 右缘 190 恰好贴外侧安全线（200-10），其余边也不越线，合格
    result = _trim(
        [(3, [(10, 40, 5, 20)])],
        duplex_flip="short",
    )
    assert result["violations"] == []


def test_right_binding_slot_order_mirrored():
    # 右装订正面：左槽 = 第 1 页（x=0）、右槽 = 第 4 页（x=100）
    # 第 1 页页内 0..5 -> 纸面 0..5，越左槽外侧
    result = _trim([(1, [(0, 50, 5, 10)])], binding="right")
    assert _edges(result) == [(1, 1, "front", 1, "outer")]
    # 第 4 页在右槽：页内 0..5 -> 纸面 100..105，越折缝安全线
    result = _trim([(4, [(0, 50, 5, 10)])], binding="right")
    assert _edges(result) == [(1, 1, "front", 4, "fold")]


def test_gutter_fold_line_is_paper_center():
    # 中缝 20：纸面 220，折缝线 110（= 页宽 + 中缝/2）；
    # 左槽 x=0（第 4 页），右槽 x=120（第 1 页）；outer=3、fold=10
    # 右槽折缝安全线（左缘）= 120；左槽折缝安全线（右缘）= 100
    result = _trim(
        [(1, [(0, 50, 5, 5)])],
        gutter_mm=20.0,
        outer_trim_mm=3.0,
        fold_safety_mm=10.0,
    )
    # 第 1 页页内 0..5 -> 纸面 120..125，左缘恰好 120，贴线合格
    assert result["violations"] == []
    result = _trim(
        [(4, [(0, 50, 100, 5)])],
        gutter_mm=20.0,
        outer_trim_mm=3.0,
        fold_safety_mm=10.0,
    )
    # 第 4 页满宽 -> 纸面 0..100：右缘恰好 100 贴折缝安全线合格，左缘 0 越过外裁线 3
    assert _edges(result) == [(1, 1, "front", 4, "outer")]
    # 折缝安全距离加大到 11（左槽右缘安全线 99）：满宽右缘 100 > 99 越线
    result = _trim(
        [(4, [(0, 50, 100, 5)])],
        gutter_mm=20.0,
        outer_trim_mm=3.0,
        fold_safety_mm=11.0,
    )
    assert (1, 1, "front", 4, "fold") in _edges(result)
    # 右槽同样：fold=11 时折缝安全线 121，纸面左缘 120 < 121 越线
    result = _trim(
        [(1, [(0, 50, 5, 5)])],
        gutter_mm=20.0,
        outer_trim_mm=3.0,
        fold_safety_mm=11.0,
    )
    assert _edges(result) == [(1, 1, "front", 1, "fold")]



def test_blank_pages_skipped():
    # 1 页补 3 空白：正面 (null, 1)，背面 (null, null)
    # 只检查第 1 页；背面无任何输出
    result = _trim(
        [(1, [(0, 0, 5, 5)])],
        total_pages=1,
    )
    # 第 1 页右槽：纸面 100..105（折缝越线）、y 0..5（顶边越线）
    assert _edges(result) == [
        (1, 1, "front", 1, "top"),
        (1, 1, "front", 1, "fold"),
    ]


def test_violations_ordered_signature_sheet_side_slot():
    # 6 页、每帖 1 张：帖 1（1-4）、帖 2（5、6 + 2 空白）
    # 各页均给整页出血（outer=10/fold=5 下四边全越）；
    # 顺序：帖1 正面左(p4)、正面右(p1)、背面左(p3)、背面右(p2)，
    #       帖2 正面右(p5)、背面右(p6)
    result = _trim(
        [(page, [(0, 0, 100, 100)]) for page in range(1, 7)],
        total_pages=6,
    )
    order = [(v["signature_index"], v["sheet_index"], v["side"], v["page"])
             for v in result["violations"]]
    expected_order = []
    for sig, pages in (
        (1, [("front", 4), ("front", 1), ("back", 3), ("back", 2)]),
        (2, [("front", 5), ("back", 6)]),
    ):
        for side, page in pages:
            # 每页矩形越 top, bottom, outer, fold 四边
            for edge in ("top", "bottom", "outer", "fold"):
                expected_order.append((sig, 1, side, page))
    assert len(order) == len(expected_order) == 6 * 4
    assert order == expected_order
    # 同一页四条边的顺序固定为 top, bottom, outer, fold
    assert [v["edge"] for v in result["violations"][:4]] == [
        "top", "bottom", "outer", "fold"
    ]
    assert result["violation_count"] == 24


def test_multiple_rectangles_same_page_all_checked():
    # 第 1 页两个矩形：一个越折缝、一个越顶边；同页矩形允许交叠
    result = _trim([
        (1, [
            (0, 50, 10, 10),    # 纸面 100..110：折缝
            (50, 0, 10, 5),     # 纸面 150.., y0..5：顶边
        ]),
    ])
    assert _edges(result) == [
        (1, 1, "front", 1, "fold"),
        (1, 1, "front", 1, "top"),
    ]


def test_rect_out_of_page_raises():
    for rect in (
        (-0.1, 0.0, 10.0, 10.0),
        (0.0, 0.0, 100.1, 10.0),
        (95.0, 0.0, 10.0, 10.0),
        (0.0, 95.0, 10.0, 10.0),
        (0.0, 0.0, 0.0, 10.0),
        (0.0, 0.0, 10.0, -1.0),
    ):
        with pytest.raises(ValueError):
            _trim([(1, [rect])])


def test_invalid_page_number_raises():
    with pytest.raises(ValueError):
        _trim([(5, [(0, 0, 1, 1)])])
    with pytest.raises(ValueError):
        _trim([(0, [(0, 0, 1, 1)])])


def test_duplicate_page_raises():
    with pytest.raises(ValueError):
        _trim([
            (1, [(0, 0, 1, 1)]),
            (1, [(0, 0, 1, 1)]),
        ])


def test_empty_rectangle_list_raises():
    with pytest.raises(ValueError):
        _trim([(1, [])])


def test_non_finite_rect_values_raise():
    for rect in (
        (float("nan"), 0.0, 10.0, 10.0),
        (0.0, float("inf"), 10.0, 10.0),
    ):
        with pytest.raises(ValueError):
            _trim([(1, [rect])])


def test_invalid_safety_distances_raise():
    for kwargs in (
        {"outer_trim_mm": -1.0},
        {"fold_safety_mm": -0.1},
        {"outer_trim_mm": float("nan")},
        {"fold_safety_mm": float("inf")},
    ):
        with pytest.raises(ValueError):
            _trim([], **kwargs)


def test_invalid_duplex_flip_raises():
    with pytest.raises(ValueError):
        _trim([], duplex_flip="side")
