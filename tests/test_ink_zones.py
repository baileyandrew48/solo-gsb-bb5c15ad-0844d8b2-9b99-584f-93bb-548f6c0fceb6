"""墨区着墨面积（ink-zones）算法单元测试。"""
import pytest

from app.imposition import ink_zones


def _ink(page_inks, *, zone_count=4, copies=1, **overrides):
    """默认 4 页 1 张、左装订、页宽/页高 100、无中缝、long 翻转、4 墨区。"""
    params = {
        "total_pages": 4,
        "max_sheets": 1,
        "binding": "left",
        "page_width_mm": 100.0,
        "page_height_mm": 100.0,
        "gutter_mm": 0.0,
        "duplex_flip": "long",
        "zone_count": zone_count,
        "copies": copies,
        "page_inks": page_inks,
    }
    params.update(overrides)
    return ink_zones(**params)


def _zones(result):
    """取唯一帖唯一张各面的 {面: {墨区序号: {通道: 面积}}}。"""
    sheet = result["signatures"][0]["sheets"][0]
    out = {}
    for side in ("front", "back"):
        side_zones = sheet.get(side)
        if side_zones:
            out[side] = {z["zone_index"]: z for z in side_zones}
    return out


def test_response_echoes_layout_and_zone_parameters():
    result = _ink([], zone_count=8, copies=12, gutter_mm=20.0)
    assert result["paper_width_mm"] == 220.0
    assert result["paper_height_mm"] == 100.0
    assert result["zone_count"] == 8
    assert result["zone_width_mm"] == pytest.approx(27.5)
    assert result["copies"] == 12
    assert result["signature_count"] == 1


def test_front_rect_maps_without_rotation():
    # 左装订正面：左槽 = 第 4 页（x=0），右槽 = 第 1 页（x=100）
    # 第 1 页页内 (50,10,25,40) C=0.5 -> 纸面 150..175，4 墨区（每区 50）落区 4
    # 面积 25×40=1000，等效 500，印数 1000 -> 500000
    result = _ink(
        [(1, [(50, 10, 25, 40, 0.5, 0.0, 0.0, 0.0)])],
        copies=1000,
    )
    zone = _zones(result)["front"][4]
    assert zone["cyan_mm2"] == 500000.0
    assert zone["magenta_mm2"] == 0.0
    assert zone["black_mm2"] == 0.0


def test_rect_split_across_zone_boundary():
    # 纸面 220（中缝 20）、4 墨区每区 55；第 4 页正面左槽 x=0
    # 页内 (40,0,40,100) -> 纸面 40..80 跨界 55：区1 交叠 15、区2 交叠 25
    # K=0.25，印数 4 -> 15*100*.25*4=1500，25*100*.25*4=2500
    result = _ink(
        [(4, [(40, 0, 40, 100, 0.0, 0.0, 0.0, 0.25)])],
        gutter_mm=20.0,
        copies=4,
    )
    front = _zones(result)["front"]
    assert front[1]["black_mm2"] == 1500.0
    assert front[2]["black_mm2"] == 2500.0
    assert set(front) == {1, 2}


def test_long_flip_back_uses_swapped_slots():
    # long 背面交换槽位：左 = 第 3 页、右 = 第 2 页（x=100），旋转 0
    # 第 2 页页内 (0,0,50,20) M=1 -> 纸面 100..150 跨 2 个墨区（每区 50），落区 3
    result = _ink([(2, [(0, 0, 50, 20, 0.0, 1.0, 0.0, 0.0)])])
    zone = _zones(result)["back"][3]
    assert zone["magenta_mm2"] == 1000.0
    assert zone["cyan_mm2"] == 0.0


def test_short_flip_back_rotates_180():
    # short 背面保持槽位：背左 = 第 2 页（x=0）、旋转 180
    # 页内 (40,10,20,20) -> 纸面 x: 100-40-20=40..60；y: 100-10-20=70
    # 2 墨区（每区 100）落区 1，面积 400，M=1，印数 2 -> 800
    result = _ink(
        [(2, [(40, 10, 20, 20, 0.0, 1.0, 0.0, 0.0)])],
        zone_count=2,
        copies=2,
        duplex_flip="short",
    )
    back = _zones(result)["back"]
    assert list(back) == [1]
    assert back[1]["magenta_mm2"] == 800.0


def test_right_binding_page_order_reused():
    # 右装订正面：左 = 第 1 页（x=0）、右 = 第 4 页（x=100）
    result = _ink([(1, [(0, 0, 50, 10, 1.0, 0.0, 0.0, 0.0)])], binding="right")
    front = _zones(result)["front"]
    # 第 1 页在左槽 -> 纸面 0..50，落区 1
    assert list(front) == [1]
    assert front[1]["cyan_mm2"] == 500.0


def test_channels_accumulate_per_zone():
    # 同一墨区内两个矩形的同通道覆盖率按面积加权累加
    # 第 4 页左槽：(0,0,50,10) C=0.25 与 (0,20,50,10) C=0.75，均落区 1
    result = _ink([
        (4, [
            (0, 0, 50, 10, 0.25, 0.0, 0.0, 0.0),
            (0, 20, 50, 10, 0.75, 0.0, 0.0, 0.0),
        ]),
    ])
    zone = _zones(result)["front"][1]
    # (500*.25 + 500*.75) = 500
    assert zone["cyan_mm2"] == 500.0


def test_gutter_portion_is_excluded():
    # 中缝 20，纸面 220，4 墨区每区 55；右槽 x=120，中缝区间 [100,120)
    # 页内矩形必须完整落在页面（0..100）内，故永远不会伸进中缝：
    # 第 1 页页内 x=30..80 -> 纸面 150..200：区3 [110,165) 交叠 15、
    # 区4 [165,220) 交叠 35
    result = _ink(
        [(1, [(30, 0, 50, 100, 1.0, 0.0, 0.0, 0.0)])],
        gutter_mm=20.0,
    )
    front = _zones(result)["front"]
    assert set(front) == {3, 4}
    assert front[3]["cyan_mm2"] == 1500.0
    assert front[4]["cyan_mm2"] == 3500.0
    # 贴中缝一侧的页边（页内 x=90..100）-> 纸面 210..220，只落区 4
    result = _ink(
        [(1, [(90, 0, 10, 100, 1.0, 0.0, 0.0, 0.0)])],
        gutter_mm=20.0,
    )
    front = _zones(result)["front"]
    assert set(front) == {4}
    assert front[4]["cyan_mm2"] == 1000.0


def test_blank_pages_not_counted():
    # 1 页补 3 空白：正面 (null, 1)，背面 (null, null)
    # 仅第 1 页（右槽 x=100）出结果；背面整面无着墨而缺省
    result = _ink(
        [(1, [(0, 0, 50, 50, 0.5, 0.0, 0.0, 0.0)])],
        total_pages=1,
    )
    sheet = result["signatures"][0]["sheets"][0]
    assert "back" not in sheet
    front = {z["zone_index"]: z for z in sheet["front"]}
    # 页内 0..50 -> 纸面 100..150，落区 3；2500×.5=1250
    assert list(front) == [3]
    assert front[3]["cyan_mm2"] == 1250.0


def test_pages_without_ink_omitted_and_empty_request_ok():
    # page_inks 为空（整体无墨）时所有张均无正反面墨区
    result = _ink([], copies=5)
    sheet = result["signatures"][0]["sheets"][0]
    assert sheet == {"sheet_index": 1}


def test_zero_coverage_zones_omitted():
    # 覆盖率全 0 的矩形不产生任何墨区
    result = _ink([(4, [(0, 0, 50, 50, 0.0, 0.0, 0.0, 0.0)])])
    sheet = result["signatures"][0]["sheets"][0]
    assert "front" not in sheet


def test_touching_rectangles_are_not_overlapping():
    # 两个矩形边相切（交叠面积 0）允许；页 1 在右槽 x=100
    result = _ink([
        (1, [
            (0, 0, 50, 50, 0.0, 0.0, 0.0, 0.5),
            (50, 0, 50, 50, 0.0, 0.3, 0.0, 0.0),
        ]),
    ])
    front = _zones(result)["front"]
    # 纸面 100..150 落区 3（K 1250），150..200 落区 4（M 750）
    assert front[3]["black_mm2"] == 1250.0
    assert front[4]["magenta_mm2"] == 750.0


def test_rect_aligned_to_paper_edges_is_valid():
    # 矩形完整贴住页面四边允许；第 4 页在左槽 x=0，覆盖纸面 0..100，
    # 默认 4 墨区每区 50 -> 落区 1、2
    result = _ink([(4, [(0.0, 0.0, 100.0, 100.0, 1.0, 1.0, 1.0, 1.0)])])
    sheet = result["signatures"][0]["sheets"][0]
    assert [z["zone_index"] for z in sheet["front"]] == [1, 2]
    front = _zones(result)["front"]
    for index in (1, 2):
        assert front[index]["cyan_mm2"] == 5000.0
        assert front[index]["magenta_mm2"] == 5000.0
        assert front[index]["yellow_mm2"] == 5000.0
        assert front[index]["black_mm2"] == 5000.0


def test_multi_signature_and_sheet_order():
    # 6 页、每帖 1 张：帖 1 页 1-4，帖 2 页 5、6（补 2 空白）
    result = _ink(
        [
            (4, [(0, 0, 10, 10, 1.0, 0.0, 0.0, 0.0)]),
            (5, [(0, 0, 10, 10, 0.0, 1.0, 0.0, 0.0)]),
        ],
        total_pages=6,
    )
    assert result["signature_count"] == 2
    sig1, sig2 = result["signatures"]
    assert (sig1["signature_index"], sig1["sheet_count"], sig1["page_count_padded"]) == (1, 1, 4)
    assert (sig2["signature_index"], sig2["sheet_count"], sig2["page_count_padded"]) == (2, 1, 4)
    # 帖 2：正面 (null, 5)，long 背面交换后右槽 = 第 6 页
    sheet2 = sig2["sheets"][0]
    # 第 5 页右槽 x=100，页内 0..10 -> 纸面 100..110 落区 3
    front2 = {z["zone_index"]: z for z in sheet2["front"]}
    assert front2[3]["magenta_mm2"] == 100.0
    # 未给第 6 页墨稿 -> 背面缺省
    assert "back" not in sheet2


def test_invalid_zone_count_raises():
    for zone_count in (0, 17, -1):
        with pytest.raises(ValueError):
            _ink([], zone_count=zone_count)


def test_invalid_copies_raises():
    for copies in (0, -3):
        with pytest.raises(ValueError):
            _ink([], copies=copies)


def test_invalid_page_number_raises():
    with pytest.raises(ValueError):
        _ink([(5, [(0, 0, 1, 1, 0.0, 0.0, 0.0, 0.0)])])
    with pytest.raises(ValueError):
        _ink([(0, [(0, 0, 1, 1, 0.0, 0.0, 0.0, 0.0)])])


def test_duplicate_page_raises():
    with pytest.raises(ValueError):
        _ink([
            (1, [(0, 0, 1, 1, 0.0, 0.0, 0.0, 0.0)]),
            (1, [(0, 0, 1, 1, 0.0, 0.0, 0.0, 0.0)]),
        ])


def test_rect_out_of_page_raises():
    for rect in (
        (-0.1, 0.0, 10.0, 10.0, 0.0, 0.0, 0.0, 0.0),
        (0.0, 0.0, 100.1, 10.0, 0.0, 0.0, 0.0, 0.0),
        (95.0, 0.0, 10.0, 10.0, 0.0, 0.0, 0.0, 0.0),
        (0.0, 95.0, 10.0, 10.0, 0.0, 0.0, 0.0, 0.0),
        (0.0, 0.0, 0.0, 10.0, 0.0, 0.0, 0.0, 0.0),
        (0.0, 0.0, 10.0, -1.0, 0.0, 0.0, 0.0, 0.0),
    ):
        with pytest.raises(ValueError):
            _ink([(1, [rect])])


def test_overlapping_rectangles_raise():
    with pytest.raises(ValueError):
        _ink([
            (1, [
                (0, 0, 50, 50, 0.0, 0.0, 0.0, 0.0),
                (40, 40, 20, 20, 0.0, 0.0, 0.0, 0.0),
            ]),
        ])


def test_coverage_out_of_range_raises():
    for channels in (
        (1.1, 0.0, 0.0, 0.0),
        (-0.1, 0.0, 0.0, 0.0),
        (0.0, 0.0, 0.0, 2.0),
    ):
        with pytest.raises(ValueError):
            _ink([(1, [(0, 0, 10, 10, *channels)])])


def test_non_finite_rect_values_raise():
    for rect in (
        (float("nan"), 0.0, 10.0, 10.0, 0.0, 0.0, 0.0, 0.0),
        (0.0, float("inf"), 10.0, 10.0, 0.0, 0.0, 0.0, 0.0),
    ):
        with pytest.raises(ValueError):
            _ink([(1, [rect])])


def test_invalid_duplex_flip_raises():
    with pytest.raises(ValueError):
        _ink([], duplex_flip="side")
