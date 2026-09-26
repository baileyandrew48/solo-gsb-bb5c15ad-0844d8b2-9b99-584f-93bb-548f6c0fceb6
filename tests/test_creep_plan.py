"""骑马订爬移补偿（creep-plan）算法单元测试。"""
import pytest

from app.imposition import creep_plan


def _slot(slot):
    """槽位 -> (页码, 纸面水平位移, 阅读方向稿件位移)；空白页位页码为 None。"""
    return slot["page"], slot["paper_shift_x_mm"], slot["artwork_shift_x_mm"]


def test_outermost_sheet_has_zero_shift():
    result = creep_plan(8, 4, "left", 100.0, 200.0, 0.0, "long", 0.1)
    sheet = result["signatures"][0]["sheets"][0]
    assert sheet["creep_mm"] == 0.0
    for side in ("front", "back"):
        for slot in ("left", "right"):
            _, paper_shift, artwork_shift = _slot(sheet[side][slot])
            assert paper_shift == 0.0
            assert artwork_shift == 0.0
            # 位移为 0 时不得出现 -0.0
            assert str(paper_shift) != "-0.0"
            assert str(artwork_shift) != "-0.0"


def test_creep_formula_two_times_sheet_offset():
    # 16 页单帖 4 张，纸厚 0.1：爬移量 0 / 0.2 / 0.4 / 0.6
    result = creep_plan(16, 4, "left", 100.0, 200.0, 0.0, "long", 0.1)
    sheets = result["signatures"][0]["sheets"]
    assert [s["creep_mm"] for s in sheets] == [0.0, 0.2, 0.4, 0.6]


def test_long_flip_shifts_toward_fold_center():
    # 8 页单帖 2 张：内张爬移 0.2，左槽 +0.2、右槽 -0.2（均指向折缝中心）
    result = creep_plan(8, 4, "left", 100.0, 200.0, 0.0, "long", 0.1)
    sheet = result["signatures"][0]["sheets"][1]
    assert sheet["creep_mm"] == 0.2
    # 正面 (6, 3)，旋转 0：阅读方向位移与纸面位移相同
    assert _slot(sheet["front"]["left"]) == (6, 0.2, 0.2)
    assert _slot(sheet["front"]["right"]) == (3, -0.2, -0.2)
    # long 背面交换槽位后为 (5, 4)，旋转 0
    assert _slot(sheet["back"]["left"]) == (5, 0.2, 0.2)
    assert _slot(sheet["back"]["right"]) == (4, -0.2, -0.2)


def test_short_flip_back_artwork_shift_negated():
    # short 背面保持槽位 (4, 5) 且旋转 180°：阅读方向位移取反
    result = creep_plan(8, 4, "left", 100.0, 200.0, 0.0, "short", 0.1)
    sheet = result["signatures"][0]["sheets"][1]
    assert _slot(sheet["front"]["left"]) == (6, 0.2, 0.2)
    assert _slot(sheet["back"]["left"]) == (4, 0.2, -0.2)
    assert _slot(sheet["back"]["right"]) == (5, -0.2, 0.2)


def test_right_binding_shifts_follow_slots():
    # 右装订镜像页序：正面 (1, 8)；位移方向仍按槽位（左正右负）
    result = creep_plan(8, 4, "right", 100.0, 200.0, 0.0, "long", 0.1)
    sheet = result["signatures"][0]["sheets"][1]
    assert _slot(sheet["front"]["left"]) == (3, 0.2, 0.2)
    assert _slot(sheet["front"]["right"]) == (6, -0.2, -0.2)


def test_blank_slots_kept_with_zero_shift():
    # 1 页补 3 空白：空白页位保留，页码 None、位移为 0
    result = creep_plan(1, 1, "left", 100.0, 200.0, 0.0, "long", 0.1)
    sheet = result["signatures"][0]["sheets"][0]
    assert _slot(sheet["front"]["left"]) == (None, 0.0, 0.0)
    assert _slot(sheet["front"]["right"]) == (1, 0.0, 0.0)
    assert _slot(sheet["back"]["left"]) == (None, 0.0, 0.0)
    assert _slot(sheet["back"]["right"]) == (None, 0.0, 0.0)


def test_creep_computed_independently_per_signature():
    # 16 页每帖 2 张 -> 2 帖：各帖内张爬移都是 0.2，与帖号无关
    result = creep_plan(16, 2, "left", 100.0, 200.0, 0.0, "long", 0.1)
    assert result["signature_count"] == 2
    for signature in result["signatures"]:
        assert [s["creep_mm"] for s in signature["sheets"]] == [0.0, 0.2]


def test_shift_equal_to_page_width_raises_decimal_exact():
    # 第 4 张爬移量 2×3×0.15 = 0.9 恰等于页宽 0.9 -> 422；
    # 二进制浮点下 6×0.15 = 0.8999999999999999 < 0.9，必须按十进制判定
    with pytest.raises(ValueError, match="第 1 帖第 4 张"):
        creep_plan(16, 4, "left", 0.9, 200.0, 0.0, "long", 0.15)


def test_shift_exceeding_page_width_raises():
    # 第 2 张爬移量 2×1×0.6 = 1.2 > 页宽 1.0
    with pytest.raises(ValueError, match="达到单页宽度"):
        creep_plan(8, 4, "left", 1.0, 200.0, 0.0, "long", 0.6)


def test_shift_just_below_page_width_ok():
    # 第 2 张爬移量 0.98 < 页宽 1.0
    result = creep_plan(8, 4, "left", 1.0, 200.0, 0.0, "long", 0.49)
    sheet = result["signatures"][0]["sheets"][1]
    assert sheet["creep_mm"] == 0.98


def test_error_message_identifies_signature_and_sheet():
    # 12 页每帖 2 张 -> 2 帖（2 张 + 1 张）；第 1 帖第 2 张爬移 1.0 达到页宽 1.0，
    # 错误信息指出帖号与张号
    with pytest.raises(ValueError, match="第 1 帖第 2 张"):
        creep_plan(12, 2, "left", 1.0, 200.0, 0.0, "long", 0.5)


def test_invalid_thickness_raises():
    for thickness in (0, -0.1, float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValueError):
            creep_plan(8, 4, "left", 100.0, 200.0, 0.0, "long", thickness)


def test_response_echoes_layout_parameters():
    result = creep_plan(8, 4, "left", 100.0, 200.0, 10.0, "short", 0.1)
    assert result["paper_width_mm"] == 210.0
    assert result["paper_height_mm"] == 200.0
    assert result["thickness_mm"] == 0.1
    assert result["duplex_flip"] == "short"
    sig = result["signatures"][0]
    assert (sig["signature_index"], sig["sheet_count"], sig["page_count_padded"]) == (1, 2, 8)
