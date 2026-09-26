"""双面拼版校样 PDF（proof.pdf）生成。

以 :func:`app.imposition.press_layout` 的机台版面结果为唯一数据源：每张印张
依次输出**正面、背面**两页，PDF 纸面尺寸（MediaBox）与机台版面计算的
``paper_width_mm`` / ``paper_height_mm`` 一致；页位的页码、左上角坐标与旋转角
完全沿用 press-layout 的结果，本模块只负责绘制，不再做任何拼版决策。

坐标系换算
----------
press-layout 以纸张**左上角为原点**（x 向右、y 向下，单位 mm）；PDF 以
**左下角为原点**（单位 pt，1 mm = 2.834645669 pt）。左上角原点的毫米坐标
``(x_mm, y_mm)`` 换算为 PDF 坐标：

    x_pt = x_mm × mm
    y_pt = (paper_height_mm - y_mm) × mm

页位旋转绕**页位中心**进行：先平移到页位中心、按 ``rotation_deg`` 旋转
（long 背面与正面为 0°，short 背面为 180°）、再平移还原。

绘制约定
--------
- 每个非空页位标注页码（大字）与“第 N 帖 · 第 M 张 · 正面/背面”（小字）；
- 空白页位（press-layout 中为 ``None``）标注“空白”，并同样标注帖号、张号；
- 中缝居中画一条竖向分隔线（``gutter_mm = 0`` 时即左右槽分界线）。

中文字体使用随包分发的子集化 Noto Sans SC（``app/fonts/NotoSansSC-Proof.ttf``，
仅含校样用到的几十个汉字与 ASCII），字形直接嵌入 PDF，任何阅读器均可显示；
字体文件缺失时回退到 reportlab 自带的 CID 字体 ``STSong-Light``（UniGB-UCS2-H）。
"""
from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Optional

from reportlab.lib.colors import Color
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas

# 单次校样最多生成的印张数（每张 2 页 PDF）；超限由 API 层返回 422
PROOF_MAX_SHEETS = 100

_PROOF_FONT = "ProofNoto"
_FONT_PATH = Path(__file__).with_name("fonts") / "NotoSansSC-Proof.ttf"
_font_registered = False

# 绘制配色
_COLOR_SLOT_BORDER = Color(0.72, 0.72, 0.72)
_COLOR_GUTTER = Color(0.15, 0.15, 0.15)
_COLOR_TEXT = Color(0, 0, 0)
_COLOR_BLANK = Color(0.45, 0.45, 0.45)
_COLOR_TAG = Color(0.3, 0.3, 0.3)


def _ensure_font() -> None:
    """注册校样字体（进程内仅需一次）：优先嵌入子集 TTF，缺失时回退 CID 字体。"""
    global _font_registered
    if not _font_registered:
        if _FONT_PATH.is_file():
            pdfmetrics.registerFont(TTFont(_PROOF_FONT, str(_FONT_PATH)))
        else:  # pragma: no cover - 字体随包分发，回退仅为兜底
            pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
        _font_registered = True


def total_sheet_count(total_pages: int) -> int:
    """按拼版规则计算总印张数：每张纸容纳 4 页（含末帖补白）。"""
    return (total_pages + 3) // 4


def validate_sheet_limit(total_pages: int) -> None:
    """校验单次印张数不超过 :data:`PROOF_MAX_SHEETS`，超限抛 ``ValueError``。"""
    sheet_count = total_sheet_count(total_pages)
    if sheet_count > PROOF_MAX_SHEETS:
        raise ValueError(
            f"单次最多生成 {PROOF_MAX_SHEETS} 张印张：本次共 {sheet_count} 张"
            f"（{total_pages} 页），总页数不能超过 {PROOF_MAX_SHEETS * 4} 页"
        )


def _slot_font_sizes(page_width_mm: float, page_height_mm: float) -> tuple[float, float]:
    """按页位尺寸缩放的（页码/空白大字字号, 帖号张号小字字号），单位 pt。"""
    main_pt = min(page_width_mm, page_height_mm) * 0.9
    main_pt = max(8.0, min(40.0, main_pt))
    small_pt = max(5.0, main_pt * 0.42)
    return main_pt, small_pt


def _draw_slot_label(
    canvas: Canvas,
    *,
    page: Optional[object],
    slot_x_mm: float,
    page_width_mm: float,
    page_height_mm: float,
    paper_height_mm: float,
    rotation_deg: int,
    signature_index: int,
    sheet_index: int,
    side_label: str,
) -> None:
    """在单个页位（槽）内绘制标注；``page is None`` 表示空白位。"""
    main_pt, small_pt = _slot_font_sizes(page_width_mm, page_height_mm)
    tag = f"第{signature_index}帖 · 第{sheet_index}张 · {side_label}"

    # 页位中心：左上角毫米坐标 -> PDF 坐标
    cx = (slot_x_mm + page_width_mm / 2.0) * mm
    cy = (paper_height_mm - page_height_mm / 2.0) * mm

    canvas.saveState()
    # 旋转绕页位中心（0°/180°）；180° 时文字与页码一并倒置，
    # 与机台版面 short 翻转“页位绕自身中心旋转 180°”一致。0° 不做变换。
    if rotation_deg:
        canvas.translate(cx, cy)
        canvas.rotate(rotation_deg)
        canvas.translate(-cx, -cy)

    main_text = "空白" if page is None else str(page)
    main_color = _COLOR_BLANK if page is None else _COLOR_TEXT

    # 大字居中于中线之上，小字标签居中于中线之下
    canvas.setFont(_PROOF_FONT, main_pt)
    canvas.setFillColor(main_color)
    canvas.drawCentredString(cx, cy + main_pt * 0.18, main_text)
    canvas.setFont(_PROOF_FONT, small_pt)
    canvas.setFillColor(_COLOR_TAG)
    canvas.drawCentredString(cx, cy - main_pt * 0.95, tag)

    canvas.restoreState()


def _draw_side_page(
    canvas: Canvas,
    *,
    pair: dict,
    paper_width_mm: float,
    paper_height_mm: float,
    page_width_mm: float,
    gutter_mm: float,
    signature_index: int,
    sheet_index: int,
    side_label: str,
    side_rotation_deg: int,
) -> None:
    """绘制一张印张的一个面（正面或背面）。

    ``side_rotation_deg`` 为该面的翻转旋转角（正面 / long 背面为 0，short 背面为
    180）：press-layout 对空白页位返回 ``None``（不带旋转），但实际整张背面都被
    翻转，故空白标注仍按该面的旋转角绘制，保证校样与实物朝向一致。
    """
    width_pt = paper_width_mm * mm
    height_pt = paper_height_mm * mm
    canvas.setPageSize((width_pt, height_pt))

    # 纸面外框
    canvas.setStrokeColor(_COLOR_GUTTER)
    canvas.setLineWidth(1.2)
    canvas.rect(0, 0, width_pt, height_pt, stroke=1, fill=0)

    # 左右槽外框（左槽 x=0，右槽 x=页宽+中缝），帮助识别空白位
    canvas.setStrokeColor(_COLOR_SLOT_BORDER)
    canvas.setLineWidth(0.6)
    left_slot_x, right_slot_x = 0.0, page_width_mm + gutter_mm
    for slot_x_mm in (left_slot_x, right_slot_x):
        canvas.rect(
            slot_x_mm * mm,
            0,
            page_width_mm * mm,
            paper_height_mm * mm,
            stroke=1,
            fill=0,
        )

    # 中缝分隔线：居中绘制于中缝（gutter=0 时即左右槽分界）
    gutter_x = (page_width_mm + gutter_mm / 2.0) * mm
    canvas.setStrokeColor(_COLOR_GUTTER)
    canvas.setLineWidth(0.9)
    canvas.setDash(3, 3)
    canvas.line(gutter_x, 0, gutter_x, height_pt)
    canvas.setDash()  # 复位

    placements = (
        ("left", left_slot_x, pair["left"]),
        ("right", right_slot_x, pair["right"]),
    )
    for _slot_name, fallback_x_mm, placement in placements:
        if placement is None:
            # 空白页位：press-layout 对空白返回 None（不带旋转），但整张背面
            # 实际被翻转，按该面的旋转角绘制“空白”与帖号张号标注
            slot_x_mm = fallback_x_mm
            rotation_deg = side_rotation_deg
            page: Optional[object] = None
        else:
            slot_x_mm = placement["x_mm"]
            rotation_deg = placement["rotation_deg"]
            page = placement["page"]
        _draw_slot_label(
            canvas,
            page=page,
            slot_x_mm=slot_x_mm,
            page_width_mm=page_width_mm,
            page_height_mm=paper_height_mm,
            paper_height_mm=paper_height_mm,
            rotation_deg=rotation_deg,
            signature_index=signature_index,
            sheet_index=sheet_index,
            side_label=side_label,
        )

    canvas.showPage()


def render_proof_pdf(layout: dict) -> bytes:
    """把 press-layout 结果渲染为双面拼版校样 PDF，返回文件字节。

    每张印张依次生成正面、背面两页，按帖号升序、帖内张号从外到内排列。
    """
    _ensure_font()

    paper_width_mm = layout["paper_width_mm"]
    paper_height_mm = layout["paper_height_mm"]
    page_width_mm = layout["page_width_mm"]
    gutter_mm = layout["gutter_mm"]
    # 正面恒为 0°；背面 long=0°、short=180°（与 press_layout 的 back_rotation 一致）
    back_side_rotation = 180 if layout.get("duplex_flip") == "short" else 0

    # reportlab 的 Canvas 需要首屏尺寸，后续每页以 setPageSize 重设；
    # 所有纸面尺寸一致，直接用计算结果初始化。
    buffer = BytesIO()
    canvas = Canvas(
        buffer,
        pagesize=(paper_width_mm * mm, paper_height_mm * mm),
        title="双面拼版校样",
        author="booklet-imposition-api",
    )

    for signature in layout["signatures"]:
        for sheet in signature["sheets"]:
            _draw_side_page(
                canvas,
                pair=sheet["front"],
                paper_width_mm=paper_width_mm,
                paper_height_mm=paper_height_mm,
                page_width_mm=page_width_mm,
                gutter_mm=gutter_mm,
                signature_index=signature["signature_index"],
                sheet_index=sheet["sheet_index"],
                side_label="正面",
                side_rotation_deg=0,
            )
            _draw_side_page(
                canvas,
                pair=sheet["back"],
                paper_width_mm=paper_width_mm,
                paper_height_mm=paper_height_mm,
                page_width_mm=page_width_mm,
                gutter_mm=gutter_mm,
                signature_index=signature["signature_index"],
                sheet_index=sheet["sheet_index"],
                side_label="背面",
                side_rotation_deg=back_side_rotation,
            )

    canvas.save()
    return buffer.getvalue()
