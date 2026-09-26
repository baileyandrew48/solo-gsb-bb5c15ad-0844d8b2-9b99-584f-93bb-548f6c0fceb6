"""双面拼版校样 PDF（proof）生成单元测试。"""
import re
from io import BytesIO

import pytest
from reportlab.lib.units import mm
from pypdf import PdfReader

from app.imposition import press_layout
from app.proof import (
    PROOF_MAX_SHEETS,
    render_proof_pdf,
    total_sheet_count,
    validate_sheet_limit,
)


def _reader(layout: dict) -> PdfReader:
    return PdfReader(BytesIO(render_proof_pdf(layout)))


def _content(page) -> str:
    return page.get_contents().get_data().decode("latin-1")


# ---------------------------------------------------------------------------
# 印张数上限
# ---------------------------------------------------------------------------


def test_total_sheet_count_is_ceil_pages_over_four():
    assert total_sheet_count(1) == 1
    assert total_sheet_count(4) == 1
    assert total_sheet_count(5) == 2
    assert total_sheet_count(400) == 100
    assert total_sheet_count(401) == 101


def test_validate_sheet_limit_boundary():
    validate_sheet_limit(400)  # 恰好 100 张，不抛
    with pytest.raises(ValueError):
        validate_sheet_limit(401)
    assert PROOF_MAX_SHEETS == 100


# ---------------------------------------------------------------------------
# PDF 页数与纸面尺寸
# ---------------------------------------------------------------------------


def test_each_sheet_emits_front_then_back_page():
    # 6 页、每帖 1 张 -> 2 张印张 -> 4 页 PDF
    layout = press_layout(6, 1, "left", 100.0, 150.0, 0.0, "long")
    reader = _reader(layout)
    assert len(reader.pages) == 2 * total_sheet_count(6)
    # 页序：帖1 正面、帖1 背面、帖2 正面、帖2 背面
    assert "正面" in reader.pages[0].extract_text()
    assert "背面" in reader.pages[1].extract_text()
    assert "第2帖" in reader.pages[2].extract_text()
    assert "背面" in reader.pages[3].extract_text()


def test_mediabox_equals_press_layout_paper_size():
    layout = press_layout(4, 1, "left", 210.0, 297.0, 10.0, "long")
    reader = _reader(layout)
    for page in reader.pages:
        assert float(page.mediabox.width) == pytest.approx(430.0 * mm, rel=1e-6)
        assert float(page.mediabox.height) == pytest.approx(297.0 * mm, rel=1e-6)


def test_zero_gutter_paper_width_is_two_pages():
    layout = press_layout(4, 1, "left", 148.5, 210.0, 0.0, "long")
    reader = _reader(layout)
    assert float(reader.pages[0].mediabox.width) == pytest.approx(297.0 * mm, rel=1e-6)


# ---------------------------------------------------------------------------
# 页位标注：页码、帖号张号、空白
# ---------------------------------------------------------------------------


def test_slot_labels_show_page_and_signature_sheet():
    # 左装订 4 页正面：左 4、右 1
    layout = press_layout(4, 1, "left", 210.0, 297.0, 0.0, "long")
    text = _reader(layout).pages[0].extract_text()
    assert "4" in text and "1" in text
    assert "第1帖" in text
    assert "第1张" in text
    assert "正面" in text


def test_blank_slot_labelled_blank():
    # 1 页补 3 空白：正面 空白/1，背面 空白/空白
    layout = press_layout(1, 1, "left", 210.0, 297.0, 0.0, "short")
    reader = _reader(layout)
    front_text = reader.pages[0].extract_text()
    assert "空白" in front_text
    assert "1" in front_text
    # 背面两个槽均为空白
    back_text = reader.pages[1].extract_text()
    assert back_text.count("空白") == 2


def test_multi_signature_labels():
    # 每帖 1 张、8 页 -> 2 帖；每张均标注对应帖号
    layout = press_layout(8, 1, "left", 100.0, 150.0, 4.0, "long")
    reader = _reader(layout)
    assert len(reader.pages) == 4
    assert "第1帖" in reader.pages[0].extract_text()
    assert "第2帖" in reader.pages[2].extract_text()
    assert "第1张" in reader.pages[2].extract_text()


def test_long_flip_back_page_order_matches_layout():
    # 左装订 long：正面 (4,1)，背面交换槽位 -> (3,2)
    layout = press_layout(4, 1, "left", 210.0, 297.0, 0.0, "long")
    reader = _reader(layout)
    front = [line for line in reader.pages[0].extract_text().splitlines() if line.isdigit()]
    back = [line for line in reader.pages[1].extract_text().splitlines() if line.isdigit()]
    # pypdf 按内容流顺序取字（左槽先绘制、右槽后绘制）
    assert front == ["4", "1"]
    assert back == ["3", "2"]


def test_right_binding_matches_layout():
    # 右装订：正面 (1,4)，long 背面 (2,3)
    layout = press_layout(4, 1, "right", 210.0, 297.0, 0.0, "long")
    reader = _reader(layout)
    front = [line for line in reader.pages[0].extract_text().splitlines() if line.isdigit()]
    back = [line for line in reader.pages[1].extract_text().splitlines() if line.isdigit()]
    assert front == ["1", "4"]
    assert back == ["2", "3"]


# ---------------------------------------------------------------------------
# 旋转角（沿用 press-layout 的 rotation_deg）
# ---------------------------------------------------------------------------


def _has_180_rotation(page) -> bool:
    # 180° 旋转的变换矩阵为 [-1 0 0 -1 tx ty]
    return "-1 0 0 -1" in _content(page)


def _find_nums(content: str) -> list[list[float]]:
    """提取内容流中所有四元数值序列 ``a b c d re`` 的数值（pt）。"""
    return [
        [float(v) for v in m]
        for m in re.findall(
            r"([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s+re", content
        )
    ]


def _has_rect(page, x_mm: float, y_mm: float, w_mm: float, h_mm: float) -> bool:
    """内容流中是否存在以左上角毫米坐标描述的描边矩形（x y w h re）。"""
    expected = [x_mm * mm, y_mm * mm, w_mm * mm, h_mm * mm]
    return any(
        all(abs(actual - want) < 0.01 for actual, want in zip(nums, expected))
        for nums in _find_nums(_content(page))
    )


def _has_vline(page, x_mm: float, height_mm: float) -> bool:
    """内容流中是否存在从底边 (x,0) 到顶边 (x,height) 的竖直线。"""
    x_pt = x_mm * mm
    match = re.search(
        rf"([-\d.]+)\s+0\s+m\s+\1\s+([-\d.]+)\s+l", _content(page)
    )
    return bool(
        match
        and abs(float(match.group(1)) - x_pt) < 0.01
        and abs(float(match.group(2)) - height_mm * mm) < 0.01
    )


def test_short_flip_back_rotated_180_front_not():
    layout = press_layout(4, 1, "left", 210.0, 297.0, 0.0, "short")
    reader = _reader(layout)
    assert _has_180_rotation(reader.pages[0]) is False  # 正面 0°
    assert _has_180_rotation(reader.pages[1]) is True   # short 背面 180°


def test_long_flip_back_not_rotated():
    layout = press_layout(4, 1, "left", 210.0, 297.0, 8.0, "long")
    reader = _reader(layout)
    assert _has_180_rotation(reader.pages[0]) is False
    assert _has_180_rotation(reader.pages[1]) is False


def test_short_flip_blank_slots_on_back_also_rotated():
    # 1 页 short：背面两个槽均为空白（press-layout 返回 None），
    # 但整张背面被短边翻转，两个“空白”标注仍应旋转 180°（两个变换矩阵）。
    layout = press_layout(1, 1, "left", 210.0, 297.0, 0.0, "short")
    back = _reader(layout).pages[1]
    assert _content(back).count("-1 0 0 -1") == 2


# ---------------------------------------------------------------------------
# 坐标换算与中缝
# ---------------------------------------------------------------------------


def test_left_top_origin_mm_converted_to_pdf_bottom_left():
    # 右槽 x=页宽+中缝=220mm，页宽 210mm；槽框矩形 x 起点应为 220mm。
    # 槽高=纸面高=297mm，y=0（左下角，y_mm=0 对应 PDF 底边）。
    layout = press_layout(4, 1, "left", 210.0, 297.0, 10.0, "long")
    page = _reader(layout).pages[0]
    assert _has_rect(page, 0.0, 0.0, 210.0, 297.0)      # 左槽
    assert _has_rect(page, 220.0, 0.0, 210.0, 297.0)    # 右槽
    assert _has_rect(page, 0.0, 0.0, 430.0, 297.0)      # 纸面外框


def test_gutter_separator_drawn_at_center():
    # 中缝中心 = 页宽 + 中缝/2 = 215mm，竖向贯穿纸面
    layout = press_layout(4, 1, "left", 210.0, 297.0, 10.0, "long")
    page = _reader(layout).pages[0]
    assert _has_vline(page, 215.0, 297.0)
    # 虚线线型
    assert "[3 3] 0 d" in _content(page)


def test_gutter_separator_drawn_at_zero_gutter():
    layout = press_layout(4, 1, "left", 210.0, 297.0, 0.0, "long")
    page = _reader(layout).pages[0]
    assert _has_vline(page, 210.0, 297.0)
