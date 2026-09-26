"""机台版面（press-layout）算法单元测试。"""
import pytest

from app.imposition import press_layout


def _slot(slot):
    """非空槽位 -> (页码, x, y, 旋转角)；空槽位 -> None。"""
    if slot is None:
        return None
    return slot["page"], slot["x_mm"], slot["y_mm"], slot["rotation_deg"]


def test_paper_size_is_two_page_widths_plus_gutter():
    result = press_layout(4, 1, "left", 210.0, 297.0, 8.0, "long")
    assert result["paper_width_mm"] == 428.0
    assert result["paper_height_mm"] == 297.0
    assert result["signature_count"] == 1
    sig = result["signatures"][0]
    assert sig["paper_width_mm"] == 428.0
    assert sig["paper_height_mm"] == 297.0
    assert sig["sheet_count"] == 1
    assert sig["page_count_padded"] == 4


def test_long_flip_front_slots_and_back_swap():
    # 4 页左装订拼版：正面 (4, 1)、背面 (2, 3)
    result = press_layout(4, 1, "left", 210.0, 297.0, 10.0, "long")
    sheet = result["signatures"][0]["sheets"][0]
    # 正面：左槽 x=0、右槽 x=页宽+中缝，旋转均为 0
    assert _slot(sheet["front"]["left"]) == (4, 0.0, 0.0, 0)
    assert _slot(sheet["front"]["right"]) == (1, 220.0, 0.0, 0)
    # long：背面交换左右槽，旋转 0
    assert _slot(sheet["back"]["left"]) == (3, 0.0, 0.0, 0)
    assert _slot(sheet["back"]["right"]) == (2, 220.0, 0.0, 0)


def test_short_flip_keeps_slots_and_rotates_180():
    result = press_layout(4, 1, "left", 210.0, 297.0, 0.0, "short")
    sheet = result["signatures"][0]["sheets"][0]
    assert _slot(sheet["front"]["left"]) == (4, 0.0, 0.0, 0)
    assert _slot(sheet["front"]["right"]) == (1, 210.0, 0.0, 0)
    # short：槽位不变（x 坐标不变），各旋转 180°
    assert _slot(sheet["back"]["left"]) == (2, 0.0, 0.0, 180)
    assert _slot(sheet["back"]["right"]) == (3, 210.0, 0.0, 180)


def test_right_binding_page_order_reused():
    # 右装订镜像：正面 (1, 4)、背面 (3, 2)
    result = press_layout(4, 1, "right", 100.0, 200.0, 5.0, "long")
    sheet = result["signatures"][0]["sheets"][0]
    assert _slot(sheet["front"]["left"]) == (1, 0.0, 0.0, 0)
    assert _slot(sheet["front"]["right"]) == (4, 105.0, 0.0, 0)
    assert _slot(sheet["back"]["left"]) == (2, 0.0, 0.0, 0)
    assert _slot(sheet["back"]["right"]) == (3, 105.0, 0.0, 0)


def test_blank_slots_stay_null_with_coordinates_omitted():
    # 1 页补 3 空白：正面 (null, 1)、背面 (null, null)
    result = press_layout(1, 1, "left", 210.0, 297.0, 0.0, "short")
    sheet = result["signatures"][0]["sheets"][0]
    assert sheet["front"]["left"] is None
    assert _slot(sheet["front"]["right"]) == (1, 210.0, 0.0, 0)
    assert sheet["back"]["left"] is None
    assert sheet["back"]["right"] is None


def test_multi_signature_layout_reuses_split_rules():
    # 每帖 1 张（容量 4 页）：6 页 -> 4 + 2(补 2 空白)
    result = press_layout(6, 1, "left", 100.0, 150.0, 0.0, "long")
    assert result["signature_count"] == 2
    s1, s2 = result["signatures"]
    assert (s1["signature_index"], s1["sheet_count"], s1["page_count_padded"]) == (1, 1, 4)
    assert (s2["signature_index"], s2["sheet_count"], s2["page_count_padded"]) == (2, 1, 4)
    # 帖 2 页面 5、6：正面 (null, 5)、背面 (6, null)；long 背面交换槽位
    sheet2 = s2["sheets"][0]
    assert sheet2["front"]["left"] is None
    assert _slot(sheet2["front"]["right"]) == (5, 100.0, 0.0, 0)
    # long 交换后：左槽 = 原背右(null)，右槽 = 原背左(6)
    assert sheet2["back"]["left"] is None
    assert _slot(sheet2["back"]["right"]) == (6, 100.0, 0.0, 0)


def test_zero_gutter_right_slot_x_equals_page_width():
    result = press_layout(4, 1, "left", 148.5, 210.0, 0.0, "long")
    assert result["paper_width_mm"] == 297.0
    sheet = result["signatures"][0]["sheets"][0]
    assert sheet["front"]["right"]["x_mm"] == 148.5


def test_invalid_duplex_flip_raises():
    with pytest.raises(ValueError):
        press_layout(4, 1, "left", 210.0, 297.0, 0.0, "side")  # type: ignore[arg-type]
