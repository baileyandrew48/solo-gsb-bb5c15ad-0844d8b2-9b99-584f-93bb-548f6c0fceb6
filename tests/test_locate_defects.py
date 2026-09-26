"""瑕疵定位（locate-defects）算法单元测试。"""
import pytest

from app.imposition import locate_defects


def _locate(defects, **overrides):
    """默认 4 页 1 张、左装订、页宽 210、页高 297、中缝 10、long 翻转。"""
    params = {
        "total_pages": 4,
        "max_sheets": 1,
        "binding": "left",
        "page_width_mm": 210.0,
        "page_height_mm": 297.0,
        "gutter_mm": 10.0,
        "duplex_flip": "long",
    }
    params.update(overrides)
    defects_arg = params.pop("defects", defects)
    return locate_defects(defects=defects_arg, **params)


def test_front_point_maps_to_page_and_in_page_coords():
    # 左装订正面：左槽 = 第 4 页（x=0），右槽 = 第 1 页（x=220）
    result = _locate([(1, 1, "front", 100.0, 50.0)])
    assert result["defect_count"] == 1
    assert result["defects"][0] == {
        "defect_index": 1,
        "location": "page",
        "page": 4,
        "page_x_mm": 100.0,
        "page_y_mm": 50.0,
    }
    result = _locate([(1, 1, "front", 300.0, 10.0)])
    assert result["defects"][0]["page"] == 1
    assert (result["defects"][0]["page_x_mm"],
            result["defects"][0]["page_y_mm"]) == (80.0, 10.0)


def test_long_flip_back_uses_swapped_slots():
    # long 背面交换槽位：左槽 = 第 3 页，右槽 = 第 2 页，旋转 0
    result = _locate([
        (1, 1, "back", 30.0, 40.0),
        (1, 1, "back", 250.0, 40.0),
    ])
    left, right = result["defects"]
    assert (left["location"], left["page"]) == ("page", 3)
    assert (left["page_x_mm"], left["page_y_mm"]) == (30.0, 40.0)
    assert (right["location"], right["page"]) == ("page", 2)
    assert (right["page_x_mm"], right["page_y_mm"]) == (30.0, 40.0)


def test_short_flip_back_reverses_180():
    # short 背面保持槽位（背左 = 2、背右 = 3），页内坐标逆转 180°
    result = _locate(
        [(1, 1, "back", 100.0, 50.0)],
        gutter_mm=0.0,
        duplex_flip="short",
    )
    item = result["defects"][0]
    assert (item["location"], item["page"]) == ("page", 2)
    assert item["page_x_mm"] == pytest.approx(210.0 - 100.0)
    assert item["page_y_mm"] == pytest.approx(297.0 - 50.0)
    # 槽内左上角即阅读方向的右下角
    result = _locate(
        [(1, 1, "back", 0.0, 0.0)],
        gutter_mm=0.0,
        duplex_flip="short",
    )
    item = result["defects"][0]
    assert (item["page_x_mm"], item["page_y_mm"]) == (210.0, 297.0)


def test_gutter_point_marked_without_page():
    # 中缝区间 [210, 220)
    result = _locate([(1, 1, "front", 215.0, 100.0)])
    assert result["defects"][0] == {
        "defect_index": 1,
        "location": "gutter",
        "page": None,
        "page_x_mm": None,
        "page_y_mm": None,
    }
    # 中缝左右边界：x=210 进入中缝，x=220 落在右槽
    assert _locate([(1, 1, "front", 210.0, 0.0)])["defects"][0]["location"] == "gutter"
    right = _locate([(1, 1, "front", 220.0, 0.0)])["defects"][0]
    assert (right["location"], right["page"]) == ("page", 1)
    assert right["page_x_mm"] == 0.0


def test_zero_gutter_has_no_gutter_region():
    result = _locate([(1, 1, "front", 210.0, 5.0)], gutter_mm=0.0)
    item = result["defects"][0]
    assert (item["location"], item["page"]) == ("page", 1)
    assert item["page_x_mm"] == 0.0


def test_blank_slot_marked_without_page():
    # 1 页补 3 空白：正面 (null, 1)、背面 (null, null)
    result = _locate(
        [(1, 1, "front", 100.0, 100.0), (1, 1, "back", 100.0, 100.0)],
        total_pages=1,
        gutter_mm=0.0,
    )
    front, back = result["defects"]
    assert front["location"] == "blank"
    assert front["page"] is None
    assert back["location"] == "blank"
    # 同一请求中非空页位照常定位：右槽 = 第 1 页（x=210 -> 页内 x=40）
    result = _locate([(1, 1, "front", 250.0, 20.0)], total_pages=1, gutter_mm=0.0)
    item = result["defects"][0]
    assert (item["location"], item["page"]) == ("page", 1)
    assert (item["page_x_mm"], item["page_y_mm"]) == (40.0, 20.0)


def test_right_binding_page_order_reused():
    # 右装订镜像：正面 (1, 4)、long 背面 (2, 3)
    result = _locate(
        [(1, 1, "front", 50.0, 5.0), (1, 1, "back", 50.0, 5.0)],
        binding="right",
        gutter_mm=0.0,
    )
    front, back = result["defects"]
    assert front["page"] == 1
    assert back["page"] == 2


def test_multi_signature_and_sheet_indices():
    # 6 页、每帖 1 张：帖 1 页 1-4，帖 2 页 5、6（补 2 空白）
    result = _locate(
        [(2, 1, "front", 320.0, 10.0), (2, 1, "back", 320.0, 10.0)],
        total_pages=6,
    )
    front, back = result["defects"]
    # 帖 2 正面右槽 = 第 5 页（x=220 -> 页内 x=100）
    assert (front["location"], front["page"]) == ("page", 5)
    assert front["page_x_mm"] == 100.0
    # long 背面交换后右槽 = 第 6 页
    assert (back["location"], back["page"]) == ("page", 6)


def test_paper_edges_are_valid():
    # 纸面 430 × 297：四角与边缘均在纸面内
    result = _locate([
        (1, 1, "front", 0.0, 0.0),
        (1, 1, "front", 430.0, 297.0),
    ])
    top_left, bottom_right = result["defects"]
    assert (top_left["page"], top_left["page_x_mm"], top_left["page_y_mm"]) == (4, 0.0, 0.0)
    # 右下角落在右槽（第 1 页）的页内右下角
    assert bottom_right["page"] == 1
    assert (bottom_right["page_x_mm"], bottom_right["page_y_mm"]) == (210.0, 297.0)


def test_out_of_paper_raises():
    for point in (
        (1, 1, "front", -0.1, 10.0),
        (1, 1, "front", 430.1, 10.0),
        (1, 1, "front", 10.0, -0.1),
        (1, 1, "front", 10.0, 297.1),
        (1, 1, "front", float("nan"), 10.0),
        (1, 1, "front", 10.0, float("inf")),
    ):
        with pytest.raises(ValueError):
            _locate([point])


def test_invalid_signature_or_sheet_raises():
    with pytest.raises(ValueError):
        _locate([(2, 1, "front", 10.0, 10.0)])  # 仅 1 帖
    with pytest.raises(ValueError):
        _locate([(1, 2, "front", 10.0, 10.0)])  # 帖内仅 1 张
    with pytest.raises(ValueError):
        _locate([(0, 1, "front", 10.0, 10.0)])
    with pytest.raises(ValueError):
        _locate([(1, 0, "front", 10.0, 10.0)])


def test_invalid_side_raises():
    with pytest.raises(ValueError):
        _locate([(1, 1, "top", 10.0, 10.0)])  # type: ignore[arg-type]


def test_defect_index_follows_request_order():
    result = _locate([
        (1, 1, "front", 215.0, 0.0),   # 中缝
        (1, 1, "front", 0.0, 0.0),     # 第 4 页左上角
        (1, 1, "back", 250.0, 40.0),   # long 背面右槽 = 第 2 页
    ])
    assert [d["defect_index"] for d in result["defects"]] == [1, 2, 3]
    assert [d["location"] for d in result["defects"]] == ["gutter", "page", "page"]
    assert result["defects"][1]["page"] == 4
    assert result["defects"][2]["page"] == 2
    assert result["defect_count"] == 3


def test_response_echoes_layout_parameters():
    result = _locate([(1, 1, "front", 10.0, 10.0)])
    assert result["paper_width_mm"] == 430.0
    assert result["paper_height_mm"] == 297.0
    assert result["page_width_mm"] == 210.0
    assert result["gutter_mm"] == 10.0
    assert result["duplex_flip"] == "long"
    assert result["binding"] == "left"
