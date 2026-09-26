"""小册子拼版核心算法。

规则
----
1. 按原页顺序分帖，每帖最多容纳 ``max_sheets * 4`` 页；
2. 仅末帖在尾部补空白页至 4 的倍数，空白页用 ``None`` 表示；
3. 每帖内部按纸张“从外到内”给出正反面左右页码；
4. 左装订（left）：最外张正面 = 末页/首页，背面 = 次页/倒数第二页，
   逐张向内递推；右装订（right）将左右页位镜像交换。

章节分帖（``split_signatures_by_chapters`` / ``impose_chapters``）
----
- 章节不可跨帖，相邻章节可合帖；每帖实际页数不超过 ``max_sheets * 4``；
- 分帖边界依次最小化：各帖补至 4 的倍数所需空白总数 → 帖数；
  仍相同则优先最早的分帖边界；
- 每帖各自在尾部补空白至 4 的倍数，再按规则 3/4 拼版。
"""
from __future__ import annotations

import bisect
import math
from decimal import Decimal, localcontext
from typing import Collection, List, Literal, Optional, Tuple, TypeVar, Union

from .press_geometry import (
    PressGeometry,
    DuplexFlip,
    Side,
    placement_payload,
)

Binding = Literal["left", "right"]

# 页面标识类型：页码（int）或页面 ID（str）
P = TypeVar("P")

# 单张纸的一页描述：(全局页码或 None, 在帖内纸张上的位置)
# side: "front" 正面 / "back" 背面；position: "left" 左页 / "right" 右页


def split_signatures(total_pages: int, max_sheets: int) -> List[List[Optional[int]]]:
    """按原页顺序分帖，末帖补空白至 4 的倍数。

    返回二维列表：外层为帖（顺序），内层为该帖按原页顺序排列的页码，
    末帖补齐位置为 ``None``。
    """
    capacity = max_sheets * 4
    signatures: List[List[Optional[int]]] = []

    start = 1
    while start <= total_pages:
        end = min(start + capacity - 1, total_pages)
        pages: List[Optional[int]] = list(range(start, end + 1))
        # 仅末帖需要补齐（前面的帖都恰好装满，本身就是 4 的倍数）
        if len(pages) % 4 != 0:
            pages.extend([None] * (4 - len(pages) % 4))
        signatures.append(pages)
        start = end + 1

    return signatures


def impose_signature(
    pages: List[Optional[P]],
    binding: Binding,
) -> List[dict]:
    """对一个帖拼版，按纸张从外到内返回各张正反面的左右页码。

    ``pages`` 长度必须为 ``4s``（``s`` 为纸张数），其中保存的已是**全局页码**
    （重印接口中为页面 ID）；末帖补齐位置为 ``None``，对应页位返回 ``null``。
    """
    sheet_count = len(pages) // 4
    n = len(pages)  # 帖页数（含补齐的空白）
    sheets: List[dict] = []

    for k in range(sheet_count):
        # 左装订下，第 k 张（k=0 最外张）四个页位的帖内位置索引（0-based）：
        #   正面左 n-1-2k、正面右 2k
        #   背面左 2k+1、背面右 n-2-2k
        front_left = pages[n - 1 - 2 * k]
        front_right = pages[2 * k]
        back_left = pages[2 * k + 1]
        back_right = pages[n - 2 - 2 * k]

        if binding == "right":
            # 右装订：左右页位镜像交换
            front_left, front_right = front_right, front_left
            back_left, back_right = back_right, back_left

        sheets.append(
            {
                "sheet_index": k + 1,
                "front": {"left": front_left, "right": front_right},
                "back": {"left": back_left, "right": back_right},
            }
        )

    return sheets


def impose(total_pages: int, max_sheets: int, binding: Binding) -> List[dict]:
    """完整拼版：分帖并逐帖返回拼版结果。"""
    grouped = split_signatures(total_pages, max_sheets)
    result: List[dict] = []
    for index, pages in enumerate(grouped, start=1):
        result.append(
            {
                "signature_index": index,
                "sheet_count": len(pages) // 4,
                "page_count_padded": len(pages),
                "sheets": impose_signature(pages, binding),
            }
        )
    return result


# ---------------------------------------------------------------------------
# 机台版面（press-layout）：拼版结果叠加纸面尺寸、页位坐标与双面翻转
#
# 页位几何（实际槽位页码、槽位原点、0°/180° 旋转与双向坐标变换）统一由
# app.press_geometry 提供，press-layout / locate-defects / ink-zones /
# trim-safety 共用同一套规则。
# ---------------------------------------------------------------------------


def _build_press_layout(
    total_pages: int,
    max_sheets: int,
    binding: Binding,
    page_width_mm: float,
    page_height_mm: float,
    gutter_mm: float,
    duplex_flip: DuplexFlip,
) -> tuple[PressGeometry, dict]:
    """生成机台版面的内部结构（页位为 :class:`Placement` 对象）。

    返回 ``(geometry, layout)``：``layout`` 结构与 :func:`press_layout` 的返回值
    相同，仅页位尚未序列化为 dict；供 press-layout 序列化及 locate-defects /
    ink-zones / trim-safety 直接按页位对象做坐标换算。
    """
    geometry = PressGeometry(
        page_width_mm=page_width_mm,
        page_height_mm=page_height_mm,
        gutter_mm=gutter_mm,
        duplex_flip=duplex_flip,
    )
    paper_width = geometry.paper_width_mm
    paper_height = geometry.paper_height_mm

    result_signatures: List[dict] = []
    for signature in impose(total_pages, max_sheets, binding):
        layout_sheets: List[dict] = []
        for sheet in signature["sheets"]:
            layout_sheets.append(
                {
                    "sheet_index": sheet["sheet_index"],
                    **geometry.place_sheet(sheet),
                }
            )
        result_signatures.append(
            {
                "signature_index": signature["signature_index"],
                "sheet_count": signature["sheet_count"],
                "page_count_padded": signature["page_count_padded"],
                "paper_width_mm": paper_width,
                "paper_height_mm": paper_height,
                "sheets": layout_sheets,
            }
        )

    layout = {
        "total_pages": total_pages,
        "max_sheets_per_signature": max_sheets,
        "binding": binding,
        "page_width_mm": page_width_mm,
        "page_height_mm": page_height_mm,
        "gutter_mm": gutter_mm,
        "duplex_flip": duplex_flip,
        "paper_width_mm": paper_width,
        "paper_height_mm": paper_height,
        "signature_count": len(result_signatures),
        "signatures": result_signatures,
    }
    return geometry, layout


def press_layout(
    total_pages: int,
    max_sheets: int,
    binding: Binding,
    page_width_mm: float,
    page_height_mm: float,
    gutter_mm: float,
    duplex_flip: DuplexFlip,
) -> dict:
    """在 :func:`impose` 的拼版结果上补充纸面尺寸与各页位坐标、旋转角。

    沿用总页数 / 每帖最大张数 / 装订方向的分帖与正反面页序规则。纸面宽为
    ``2 × 页宽 + 中缝``，纸面高为页高。坐标以纸张左上角为原点：左槽 x=0、
    右槽 x=页宽+中缝，所有槽位 y=0。正面旋转角恒为 0；背面

    - ``long``（长边翻转）：交换左右槽（页位坐标随新槽位）、旋转 0°；
    - ``short``（短边翻转）：保持槽位、各页位绕自身中心旋转 180°。

    页位几何（实际槽位、原点、旋转角）由共享的 :class:`PressGeometry` 决定，
    与 locate-defects / ink-zones / trim-safety 完全同源。空白页位整体返回
    ``None``。非法翻转模式抛 ``ValueError``。
    """
    _geometry, layout = _build_press_layout(
        total_pages,
        max_sheets,
        binding,
        page_width_mm,
        page_height_mm,
        gutter_mm,
        duplex_flip,
    )
    for signature in layout["signatures"]:
        for sheet in signature["sheets"]:
            for side in ("front", "back"):
                sheet[side] = {
                    slot: placement_payload(placement)
                    for slot, placement in sheet[side].items()
                }
    return layout


# ---------------------------------------------------------------------------
# 瑕疵定位（locate-defects）：纸面坐标反查原稿页码与阅读方向页内坐标
# ---------------------------------------------------------------------------

# 单个瑕疵点：(帖号, 张号, 面, x_mm, y_mm)
# 帖号/张号从 1 开始；面为 "front" 正面 / "back" 背面；
# x/y 以纸面左上角为原点（x 向右、y 向下，单位 mm）
DefectPoint = Tuple[int, int, Side, float, float]


def locate_defects(
    total_pages: int,
    max_sheets: int,
    binding: Binding,
    page_width_mm: float,
    page_height_mm: float,
    gutter_mm: float,
    duplex_flip: DuplexFlip,
    defects: List[DefectPoint],
) -> dict:
    """把纸面上的瑕疵点反查为原稿页码与阅读方向的页内坐标。

    页序、槽位与旋转规则与 :func:`press_layout` 完全同源（统一由
    :class:`PressGeometry` 决定）：正面与 ``long`` 背面旋转 0°（``long`` 背面按
    交换后的槽位定位），``short`` 背面各页位绕自身中心旋转 180°，槽内坐标经
    :meth:`PressGeometry.paper_to_page_point` 逆转 180° 还原为阅读方向。

    逐点返回（按请求顺序，序号 ``defect_index`` 从 1 开始）：

    - 落在页内：``location="page"``，给出页码与页内坐标（从该页阅读方向的
      左上角起算，x 向右、y 向下）；
    - 落在中缝：``location="gutter"``；落在空白页位：``location="blank"``；
      两者均不返回页码与页内坐标（相应字段为 ``None``）。

    帖号/张号越界、面取值非法、坐标越出纸面（含负坐标与非有限值）时抛
    ``ValueError``。
    """
    geometry, layout = _build_press_layout(
        total_pages,
        max_sheets,
        binding,
        page_width_mm,
        page_height_mm,
        gutter_mm,
        duplex_flip,
    )
    paper_width = layout["paper_width_mm"]
    paper_height = layout["paper_height_mm"]
    signatures = layout["signatures"]

    results: List[dict] = []
    for index, (signature_index, sheet_index, side, x_mm, y_mm) in enumerate(
        defects, start=1
    ):
        if not 1 <= signature_index <= len(signatures):
            raise ValueError(
                f"第 {index} 个瑕疵点的帖号 {signature_index} 无效："
                f"共 {len(signatures)} 帖"
            )
        signature = signatures[signature_index - 1]
        sheets = signature["sheets"]
        if not 1 <= sheet_index <= len(sheets):
            raise ValueError(
                f"第 {index} 个瑕疵点的张号 {sheet_index} 无效："
                f"第 {signature_index} 帖共 {len(sheets)} 张"
            )
        if side not in ("front", "back"):
            raise ValueError(
                f"第 {index} 个瑕疵点的面 {side!r} 非法："
                "只支持 'front' / 'back'"
            )
        # 纸面边界含边缘；NaN/Infinity 比较恒为 False，同样落入越界分支
        if not geometry.contains_paper_point(x_mm, y_mm):
            raise ValueError(
                f"第 {index} 个瑕疵点越出纸面：({x_mm}, {y_mm}) 不在"
                f" 0..{paper_width} × 0..{paper_height}（mm）内"
            )

        sheet = sheets[sheet_index - 1]
        region = geometry.region_at_x(x_mm)
        if region == "gutter":
            # 中缝（gutter_mm = 0 时该区间为空，不会命中）
            item = {"location": "gutter", "page": None,
                    "page_x_mm": None, "page_y_mm": None}
        else:
            placement = sheet[side][region]
            if placement is None:
                # 空白页位（末帖补白）
                item = {"location": "blank", "page": None,
                        "page_x_mm": None, "page_y_mm": None}
            else:
                # 槽内坐标 -> 阅读方向页内坐标（共享的双向点变换）
                page_x, page_y = geometry.paper_to_page_point(
                    placement, x_mm, y_mm
                )
                item = {
                    "location": "page",
                    "page": placement.page,
                    "page_x_mm": page_x,
                    "page_y_mm": page_y,
                }
        results.append({"defect_index": index, **item})

    return {
        "total_pages": total_pages,
        "max_sheets_per_signature": max_sheets,
        "binding": binding,
        "page_width_mm": page_width_mm,
        "page_height_mm": page_height_mm,
        "gutter_mm": gutter_mm,
        "duplex_flip": duplex_flip,
        "paper_width_mm": paper_width,
        "paper_height_mm": paper_height,
        "defect_count": len(results),
        "defects": results,
    }


# ---------------------------------------------------------------------------
# 墨区着墨面积（ink-zones）：页内矩形随页位映射到纸面，按等宽墨区汇总
# ---------------------------------------------------------------------------

# 墨区数量允许范围
INK_ZONE_MIN_COUNT = 1
INK_ZONE_MAX_COUNT = 16

# CMYK 四通道顺序
INK_CHANNELS: Tuple[str, str, str, str] = ("cyan", "magenta", "yellow", "black")

# 页内矩形：(左上角 x, 左上角 y, 宽, 高, 青, 品, 黄, 黑覆盖率)，
# 坐标以页面左上角为原点（x 向右、y 向下，单位 mm），覆盖率 ∈ [0, 1]
PageRect = Tuple[float, float, float, float, float, float, float, float]

# 单页墨稿：(页码, [页内矩形, ...])
PageInk = Tuple[int, List[PageRect]]


def _rects_overlap(
    a: PageRect, b: PageRect, eps: float = 1e-9
) -> bool:
    """两个页内矩形（左上原点、x/y/宽/高）是否有正面积交叠。

    边相切（交叠面积为 0）不算重叠；``eps`` 为相对尺度的容差，用于抵消浮点误差。
    """
    ax, ay, aw, ah = a[:4]
    bx, by, bw, bh = b[:4]
    tolerance = eps * max(1.0, ax + aw, ay + ah, bx + bw, by + bh)
    return (
        ax < bx + bw - tolerance
        and bx < ax + aw - tolerance
        and ay < by + bh - tolerance
        and by < ay + ah - tolerance
    )


def ink_zones(
    total_pages: int,
    max_sheets: int,
    binding: Binding,
    page_width_mm: float,
    page_height_mm: float,
    gutter_mm: float,
    duplex_flip: DuplexFlip,
    zone_count: int,
    copies: int,
    page_inks: List[PageInk],
) -> dict:
    """按等宽墨区统计各通道等效着墨面积（已乘印数）。

    页序、分帖、槽位与旋转规则与 :func:`press_layout` 完全同源（统一由
    :class:`PressGeometry` 决定）。每个页内矩形（以页面左上角为原点）先经
    :meth:`PressGeometry.page_rect_to_paper` 按所在页位的 ``rotation_deg``
    映射到纸面坐标：

    - 0°：纸面左上角 = 槽位左上角 + 矩形左上角，宽高不变；
    - 180°：绕页位中心旋转，纸面左上角 =
      ``(槽位 x + 页宽 − x − w, 槽位 y + 页高 − y − h)``，宽高不变。

    纸面按宽度等分为 ``zone_count`` 个墨区（1～16），矩形与墨区按交叠面积
    拆分；某通道在某墨区的等效着墨面积为
    ``Σ 交叠面积 × 该矩形该通道覆盖率``，再乘印数 ``copies``（正整数）。

    按帖、张、正反面与墨区返回结果；空白页位（末帖补白）不参与统计，
    任何通道均为 0 的墨区也不输出（矩形落在中缝内的部分同理为 0）。

    以下情况抛 ``ValueError``（API 层对应 422）：墨区数量不在 1～16、
    印数不是正整数、页码无效（非正或超过总页数）、同页出现两次、
    页内矩形坐标/宽高为非有限值或越出页面（允许贴边）、同页矩形正面积重叠、
    通道覆盖率不在 [0, 1]。
    """
    if not isinstance(zone_count, int) or isinstance(zone_count, bool) or not (
        INK_ZONE_MIN_COUNT <= zone_count <= INK_ZONE_MAX_COUNT
    ):
        raise ValueError(
            f"墨区数量必须为 {INK_ZONE_MIN_COUNT}～{INK_ZONE_MAX_COUNT} 的整数"
        )
    if (
        not isinstance(copies, int)
        or isinstance(copies, bool)
        or copies < 1
    ):
        raise ValueError("印数 copies 必须为正整数")

    inks_by_page: dict = {}
    for page_index, (page, rects) in enumerate(page_inks, start=1):
        if not isinstance(page, int) or isinstance(page, bool) or not (
            1 <= page <= total_pages
        ):
            raise ValueError(
                f"第 {page_index} 组页内矩形的页码 {page!r} 无效："
                f"总页数为 {total_pages}，页码须在 1～{total_pages} 之间"
            )
        if page in inks_by_page:
            raise ValueError(f"第 {page} 页的页内矩形重复给出，每页只能出现一次")
        if not rects:
            raise ValueError(f"第 {page} 页至少需要给出 1 个页内矩形")
        scale = max(1.0, page_width_mm, page_height_mm)
        tolerance = 1e-9 * scale
        validated: List[PageRect] = []
        for rect_index, rect in enumerate(rects, start=1):
            if len(rect) != 8:
                raise ValueError(f"第 {page} 页第 {rect_index} 个矩形字段不完整")
            rx, ry, rw, rh, c, m, y_value, k = rect
            values = (rx, ry, rw, rh, c, m, y_value, k)
            if not all(math.isfinite(v) for v in values):
                raise ValueError(
                    f"第 {page} 页第 {rect_index} 个矩形含非有限数值"
                    "（NaN / Infinity）"
                )
            if rx < -tolerance or ry < -tolerance:
                raise ValueError(
                    f"第 {page} 页第 {rect_index} 个矩形越出页面："
                    f"左上角 ({rx}, {ry}) 不能为负"
                )
            if rw <= 0 or rh <= 0:
                raise ValueError(
                    f"第 {page} 页第 {rect_index} 个矩形越界：宽、高必须为正数"
                )
            if rx + rw > page_width_mm + tolerance or (
                ry + rh > page_height_mm + tolerance
            ):
                raise ValueError(
                    f"第 {page} 页第 {rect_index} 个矩形越出页面："
                    f"矩形 ({rx}, {ry}, {rw}, {rh}) 须完整落在 "
                    f"{page_width_mm} × {page_height_mm}（mm）的页面内"
                )
            # 夹回边界，消除贴边时的浮点误差
            rx = max(0.0, min(rx, page_width_mm))
            ry = max(0.0, min(ry, page_height_mm))
            rw = min(rw, page_width_mm - rx)
            rh = min(rh, page_height_mm - ry)
            for channel, coverage in zip(INK_CHANNELS, (c, m, y_value, k)):
                if not 0.0 <= coverage <= 1.0:
                    raise ValueError(
                        f"第 {page} 页第 {rect_index} 个矩形的 {channel} 通道"
                        f"覆盖率 {coverage} 越界，须在 0～1 之间"
                    )
            for other in validated:
                if _rects_overlap(other, (rx, ry, rw, rh, c, m, y_value, k)):
                    raise ValueError(
                        f"第 {page} 页的页内矩形互不重叠：第 {rect_index} 个矩形"
                        f" ({rx}, {ry}, {rw}, {rh}) 与此前矩形正面积交叠"
                    )
            validated.append((rx, ry, rw, rh, c, m, y_value, k))
        inks_by_page[page] = validated

    geometry, layout = _build_press_layout(
        total_pages,
        max_sheets,
        binding,
        page_width_mm,
        page_height_mm,
        gutter_mm,
        duplex_flip,
    )
    paper_width = layout["paper_width_mm"]
    paper_height = layout["paper_height_mm"]
    zone_width = paper_width / zone_count

    result_signatures: List[dict] = []
    for signature in layout["signatures"]:
        result_sheets: List[dict] = []
        for sheet in signature["sheets"]:
            sides: dict = {}
            for side in ("front", "back"):
                # totals[墨区索引] = [青, 品, 黄, 黑] 累计等效面积（未乘印数）
                totals = [[0.0, 0.0, 0.0, 0.0] for _ in range(zone_count)]
                for slot in ("left", "right"):
                    placement = sheet[side][slot]
                    if placement is None:
                        continue  # 空白页位（末帖补白）不计
                    rects = inks_by_page.get(placement.page)
                    if not rects:
                        continue
                    for rx, ry, rw, rh, c, m, y_value, k in rects:
                        # 页内矩形 -> 纸面矩形（共享的双向矩形变换）
                        px, py, rw, rh = geometry.page_rect_to_paper(
                            placement, rx, ry, rw, rh
                        )
                        first = max(0, int(math.floor(px / zone_width)))
                        last = min(
                            zone_count - 1,
                            int(math.floor((px + rw) / zone_width)),
                        )
                        for zone_index in range(first, last + 1):
                            overlap_w = (
                                min(px + rw, (zone_index + 1) * zone_width)
                                - max(px, zone_index * zone_width)
                            )
                            if overlap_w <= 0.0:
                                continue
                            area = overlap_w * rh
                            totals[zone_index][0] += area * c
                            totals[zone_index][1] += area * m
                            totals[zone_index][2] += area * y_value
                            totals[zone_index][3] += area * k
                zones = []
                for zone_index, channel_totals in enumerate(totals):
                    if any(value > 0.0 for value in channel_totals):
                        zones.append(
                            {
                                "zone_index": zone_index + 1,
                                "cyan_mm2": channel_totals[0] * copies,
                                "magenta_mm2": channel_totals[1] * copies,
                                "yellow_mm2": channel_totals[2] * copies,
                                "black_mm2": channel_totals[3] * copies,
                            }
                        )
                if zones:
                    sides[side] = zones
            result_sheets.append(
                {"sheet_index": sheet["sheet_index"], **sides}
            )
        result_signatures.append(
            {
                "signature_index": signature["signature_index"],
                "sheet_count": signature["sheet_count"],
                "page_count_padded": signature["page_count_padded"],
                "sheets": result_sheets,
            }
        )

    return {
        "total_pages": total_pages,
        "max_sheets_per_signature": max_sheets,
        "binding": binding,
        "page_width_mm": page_width_mm,
        "page_height_mm": page_height_mm,
        "gutter_mm": gutter_mm,
        "duplex_flip": duplex_flip,
        "paper_width_mm": paper_width,
        "paper_height_mm": paper_height,
        "zone_count": zone_count,
        "zone_width_mm": zone_width,
        "copies": copies,
        "signature_count": len(result_signatures),
        "signatures": result_signatures,
    }


# ---------------------------------------------------------------------------
# 外裁/折缝安全检查（trim-safety）：受保护内容矩形映射纸面后核对安全距离
# ---------------------------------------------------------------------------

# 页内受保护内容矩形：(左上角 x, 左上角 y, 宽, 高)，
# 坐标以页面（阅读方向）左上角为原点（x 向右、y 向下，单位 mm）
ProtectedRect = Tuple[float, float, float, float]

# 单页受保护内容：(页码, [页内矩形, ...])
PageProtected = Tuple[int, List[ProtectedRect]]

# 违规边取值（按此顺序逐边上报同一矩形的多处越线）：
# top/bottom=纸面顶/底边（外裁），outer=纸面外侧竖边（左槽靠左缘、右槽靠右缘，
# 外裁），fold=中缝折缝侧
TRIM_EDGE_ORDER: Tuple[str, ...] = ("top", "bottom", "outer", "fold")


def trim_safety(
    total_pages: int,
    max_sheets: int,
    binding: Binding,
    page_width_mm: float,
    page_height_mm: float,
    gutter_mm: float,
    duplex_flip: DuplexFlip,
    outer_trim_mm: float,
    fold_safety_mm: float,
    page_protected: List[PageProtected],
) -> dict:
    """检查各页受保护内容矩形映射到纸面后是否越过裁切/折缝安全线。

    页序、分帖、槽位与旋转规则与 :func:`press_layout` 完全同源（统一由
    :class:`PressGeometry` 决定）。请求按**实际页码**给出**阅读方向**的页内受保护
    矩形（以页面左上角为原点），矩形先经 :meth:`PressGeometry.page_rect_to_paper`
    按所在页位的 ``rotation_deg`` 映射到纸面坐标（与 :func:`ink_zones` 共用同一
    0°/180° 矩形变换）：

    - 0°：纸面左上角 = 槽位左上角 + 矩形左上角，宽高不变；
    - 180°：绕页位中心旋转，纸面左上角 =
      ``(槽位 x + 页宽 − x − w, 槽位 y + 页高 − y − h)``，宽高不变。

    折缝线为纸面（中缝）中心线 ``paper_width / 2 = 页宽 + 中缝 / 2``
    （即 :attr:`PressGeometry.fold_x_mm`）。矩形四边
    按所在槽位核对（贴安全线视为合格，仅严格越线才记违规）：

    - **中缝侧**（左槽矩形右边、右槽矩形左边）：与折缝线保持 ``fold_safety_mm``；
    - **其余三边**（纸面顶边、底边与外侧竖边——左槽靠左纸边、右槽靠右纸边）：
      与纸面边缘保持 ``outer_trim_mm``。

    逐帖、逐张、逐面（front → back）、逐槽（left → right）、按请求矩形顺序返回
    每处越线，给出帖号、张号、正反面、页码、违规边（``top`` / ``bottom`` /
    ``outer`` / ``fold``）与**纸面矩形**；同一矩形同时越过多条安全线时逐边各记
    一条，顺序为 :data:`TRIM_EDGE_ORDER`。空白页位（末帖补白）整体跳过。

    以下情况抛 ``ValueError``（API 层对应 422）：外裁/折缝安全距离为负或非有限
    值、页码无效（非正或超过总页数）、同页出现两次、矩形列表为空、矩形坐标/宽高
    为非有限值或越出页面（允许贴边）、宽高非正。同页矩形允许相互交叠（不影响
    安全判定）。
    """
    for name, value in (
        ("外裁安全距离", outer_trim_mm),
        ("折缝安全距离", fold_safety_mm),
    ):
        if (
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not math.isfinite(value)
            or value < 0
        ):
            raise ValueError(f"{name}必须为非负有限数值（单位 mm）")

    protected_by_page: dict = {}
    for item_index, (page, rects) in enumerate(page_protected, start=1):
        if not isinstance(page, int) or isinstance(page, bool) or not (
            1 <= page <= total_pages
        ):
            raise ValueError(
                f"第 {item_index} 组受保护矩形的页码 {page!r} 无效："
                f"总页数为 {total_pages}，页码须在 1～{total_pages} 之间"
            )
        if page in protected_by_page:
            raise ValueError(f"第 {page} 页的受保护矩形重复给出，每页只能出现一次")
        if not rects:
            raise ValueError(f"第 {page} 页至少需要给出 1 个受保护矩形")
        scale = max(1.0, page_width_mm, page_height_mm)
        tolerance = 1e-9 * scale
        validated: List[ProtectedRect] = []
        for rect_index, rect in enumerate(rects, start=1):
            if len(rect) != 4:
                raise ValueError(f"第 {page} 页第 {rect_index} 个矩形字段不完整")
            rx, ry, rw, rh = rect
            if not all(math.isfinite(v) for v in (rx, ry, rw, rh)):
                raise ValueError(
                    f"第 {page} 页第 {rect_index} 个矩形含非有限数值"
                    "（NaN / Infinity）"
                )
            if rx < -tolerance or ry < -tolerance:
                raise ValueError(
                    f"第 {page} 页第 {rect_index} 个矩形越出页面："
                    f"左上角 ({rx}, {ry}) 不能为负"
                )
            if rw <= 0 or rh <= 0:
                raise ValueError(
                    f"第 {page} 页第 {rect_index} 个矩形越界：宽、高必须为正数"
                )
            if rx + rw > page_width_mm + tolerance or (
                ry + rh > page_height_mm + tolerance
            ):
                raise ValueError(
                    f"第 {page} 页第 {rect_index} 个矩形越出页面："
                    f"矩形 ({rx}, {ry}, {rw}, {rh}) 须完整落在 "
                    f"{page_width_mm} × {page_height_mm}（mm）的页面内"
                )
            # 夹回边界，消除贴边时的浮点误差
            rx = max(0.0, min(rx, page_width_mm))
            ry = max(0.0, min(ry, page_height_mm))
            rw = min(rw, page_width_mm - rx)
            rh = min(rh, page_height_mm - ry)
            validated.append((rx, ry, rw, rh))
        protected_by_page[page] = validated

    geometry, layout = _build_press_layout(
        total_pages,
        max_sheets,
        binding,
        page_width_mm,
        page_height_mm,
        gutter_mm,
        duplex_flip,
    )
    paper_width = layout["paper_width_mm"]
    paper_height = layout["paper_height_mm"]
    # 折缝线：纸面（中缝）中心线（共享几何）
    fold_x = geometry.fold_x_mm
    tolerance = 1e-9 * max(1.0, paper_width, paper_height)

    violations: List[dict] = []
    for signature in layout["signatures"]:
        for sheet in signature["sheets"]:
            for side in ("front", "back"):
                for slot in ("left", "right"):
                    placement = sheet[side][slot]
                    if placement is None:
                        continue  # 空白页位（末帖补白）跳过
                    rects = protected_by_page.get(placement.page)
                    if not rects:
                        continue
                    for rx, ry, rw, rh in rects:
                        # 页内矩形 -> 纸面矩形（共享的双向矩形变换）
                        px, py, rw, rh = geometry.page_rect_to_paper(
                            placement, rx, ry, rw, rh
                        )
                        # 追加顺序与 TRIM_EDGE_ORDER 一致（top,bottom,outer,fold）
                        crossed: List[str] = []
                        if py < outer_trim_mm - tolerance:
                            crossed.append("top")
                        if py + rh > paper_height - outer_trim_mm + tolerance:
                            crossed.append("bottom")
                        if slot == "left":
                            # 左槽：左缘为纸面外侧裁边，右边朝折缝
                            if px < outer_trim_mm - tolerance:
                                crossed.append("outer")
                            if px + rw > fold_x - fold_safety_mm + tolerance:
                                crossed.append("fold")
                        else:
                            # 右槽：右缘为纸面外侧裁边，左边朝折缝
                            if px + rw > paper_width - outer_trim_mm + tolerance:
                                crossed.append("outer")
                            if px < fold_x + fold_safety_mm - tolerance:
                                crossed.append("fold")
                        for edge in crossed:
                            violations.append(
                                {
                                    "signature_index": signature["signature_index"],
                                    "sheet_index": sheet["sheet_index"],
                                    "side": side,
                                    "page": placement.page,
                                    "edge": edge,
                                    "rectangle": {
                                        "x_mm": px,
                                        "y_mm": py,
                                        "width_mm": rw,
                                        "height_mm": rh,
                                    },
                                }
                            )

    return {
        "total_pages": total_pages,
        "max_sheets_per_signature": max_sheets,
        "binding": binding,
        "page_width_mm": page_width_mm,
        "page_height_mm": page_height_mm,
        "gutter_mm": gutter_mm,
        "duplex_flip": duplex_flip,
        "paper_width_mm": paper_width,
        "paper_height_mm": paper_height,
        "outer_trim_mm": outer_trim_mm,
        "fold_safety_mm": fold_safety_mm,
        "violation_count": len(violations),
        "violations": violations,
    }


def split_signatures_by_chapters(
    total_pages: int,
    max_sheets: int,
    chapter_starts: List[int],
) -> List[List[Optional[int]]]:
    """按章节边界分帖：章节不可跨帖，相邻章节可合帖。

    在满足“单帖实际页数 ≤ ``max_sheets * 4``”的分帖方案中，依次最小化：

    1. 各帖补至 4 的倍数所需空白页总数；
    2. 帖数；
    3. 仍相同则取最早的分帖边界（排在前面的帖尽量短）。

    每帖尾部补空白至 4 的倍数（``None``）。
    任一单章页数超过容量时抛 ``ValueError``。
    """
    capacity = max_sheets * 4
    starts = list(chapter_starts)
    ends = starts[1:] + [total_pages + 1]
    lengths = [end - start for start, end in zip(starts, ends)]
    for start, length in zip(starts, lengths):
        if length > capacity:
            raise ValueError(
                f"起始页为 {start} 的章节共 {length} 页，超过单帖容量 {capacity} 页"
            )

    m = len(lengths)
    # 章节页数前缀和，O(1) 求连续若干章的总页数
    prefix = [0] * (m + 1)
    for i, length in enumerate(lengths, 1):
        prefix[i] = prefix[i - 1] + length

    def blanks(count: int) -> int:
        # 补至 4 的倍数所需空白页数
        return (-count) % 4

    # 后缀 DP：best[i] = 章节 i..m（1-based）的最优 (空白总数, 帖数)。
    # 内层循环最多推进 capacity 章（每章至少 1 页），整体 O(m * capacity)。
    best: List[Tuple[int, int]] = [(0, 0)] * (m + 2)
    for i in range(m, 0, -1):
        best_cost: Optional[Tuple[int, int]] = None
        for j in range(i, m + 1):
            count = prefix[j] - prefix[i - 1]
            if count > capacity:
                break
            candidate = (blanks(count) + best[j + 1][0], 1 + best[j + 1][1])
            if best_cost is None or candidate < best_cost:
                best_cost = candidate
        # 单章必能成帖（前面已校验容量），best_cost 不会为 None
        assert best_cost is not None
        best[i] = best_cost

    # 重建：达到最优成本的边界中取最早者（每步选最小的 j）
    signatures: List[List[Optional[int]]] = []
    i = 1
    while i <= m:
        for j in range(i, m + 1):
            count = prefix[j] - prefix[i - 1]
            if count > capacity:
                break
            if (blanks(count) + best[j + 1][0], 1 + best[j + 1][1]) == best[i]:
                pages: List[Optional[int]] = list(
                    range(starts[i - 1], starts[i - 1] + count)
                )
                pages.extend([None] * blanks(count))
                signatures.append(pages)
                i = j + 1
                break
    return signatures


def impose_chapters(
    total_pages: int,
    max_sheets: int,
    binding: Binding,
    chapter_starts: List[int],
) -> List[dict]:
    """按章节分帖的完整拼版：每帖额外给出原页起止页码与空白数。"""
    grouped = split_signatures_by_chapters(total_pages, max_sheets, chapter_starts)
    result: List[dict] = []
    for index, pages in enumerate(grouped, start=1):
        real_pages = [p for p in pages if p is not None]
        result.append(
            {
                "signature_index": index,
                "sheet_count": len(pages) // 4,
                "page_count_padded": len(pages),
                "page_start": real_pages[0],
                "page_end": real_pages[-1],
                "blank_count": len(pages) - len(real_pages),
                "sheets": impose_signature(pages, binding),
            }
        )
    return result


# ---------------------------------------------------------------------------
# 重印（reprint）：基于页面 ID 的两版拼版复用
# ---------------------------------------------------------------------------

# 一张印张四个页位的键：(正面左, 正面右, 背面左, 背面右)，空白页位为 None
SheetKey = Tuple[Optional[P], Optional[P], Optional[P], Optional[P]]


def split_signatures_from_pages(
    page_ids: List[P],
    max_sheets: int,
) -> List[List[Optional[P]]]:
    """按阅读顺序把页面 ID 分帖，规则与 :func:`split_signatures` 相同。

    每帖最多容纳 ``max_sheets * 4`` 页，前面的帖装满；仅末帖在尾部补 ``None``
    至 4 的倍数。
    """
    capacity = max_sheets * 4
    signatures: List[List[Optional[P]]] = []

    start = 0
    total = len(page_ids)
    while start < total:
        end = min(start + capacity, total)
        pages: List[Optional[P]] = list(page_ids[start:end])
        if len(pages) % 4 != 0:
            pages.extend([None] * (4 - len(pages) % 4))
        signatures.append(pages)
        start = end

    return signatures


def impose_from_pages(
    page_ids: List[P],
    max_sheets: int,
    binding: Binding,
) -> List[dict]:
    """页面 ID 版本的完整拼版：分帖并逐帖返回四页位（ID 或 ``None``）。"""
    grouped = split_signatures_from_pages(page_ids, max_sheets)
    result: List[dict] = []
    for index, pages in enumerate(grouped, start=1):
        result.append(
            {
                "signature_index": index,
                "sheet_count": len(pages) // 4,
                "page_count_padded": len(pages),
                "sheets": impose_signature(pages, binding),
            }
        )
    return result


def _sheet_key(sheet: dict) -> SheetKey:
    """取一张拼版结果四个页位，构成可比较的键（正左、正右、背左、背右）。"""
    return (
        sheet["front"]["left"],
        sheet["front"]["right"],
        sheet["back"]["left"],
        sheet["back"]["right"],
    )


def plan_reprint(
    old_page_ids: List[P],
    new_page_ids: List[P],
    max_sheets: int,
    binding: Binding,
    changed_page_ids: Collection[P],
) -> dict:
    """计算新版各印张能否复用旧版印张，否则标记整张重印。

    复用条件（缺一不可）：

    1. 新版印张四个页位（``None`` 表示空白）与某张旧版印张**完全相同**，
       允许跨帖匹配；
    2. 四个页位中的非空页面 ID 均不在 ``changed_page_ids`` 内；
    3. 每张旧版印张最多被复用一次。

    含空白页位的多张印张键可能相同（全空白张），按旧版帖号、张号顺序取用，
    保证结果确定。按新版帖号、张号顺序依次匹配可最大化复用张数：一旦一张新
    张被标记重印，相应的旧张仍留给后续新张。

    返回新版逐帖的复用/重印计划与重印总张数。
    """
    old_imposed = impose_from_pages(old_page_ids, max_sheets, binding)
    new_imposed = impose_from_pages(new_page_ids, max_sheets, binding)
    changed = set(changed_page_ids)

    # 旧版各四页位组合对应的可用印张列表（旧帖号, 旧张号），按帖号、张号排序
    available: dict = {}
    for signature in old_imposed:
        for sheet in signature["sheets"]:
            available.setdefault(_sheet_key(sheet), []).append(
                (signature["signature_index"], sheet["sheet_index"])
            )

    reprint_count = 0
    result_signatures: List[dict] = []

    for signature in new_imposed:
        result_sheets: List[dict] = []
        for sheet in signature["sheets"]:
            key = _sheet_key(sheet)
            is_changed = any(
                page_id is not None and page_id in changed for page_id in key
            )
            reuse: Optional[Tuple[int, int]] = None
            if not is_changed:
                candidates = available.get(key)
                if candidates:
                    reuse = candidates.pop(0)

            if reuse is None:
                reused = False
                old_signature_index: Optional[int] = None
                old_sheet_index: Optional[int] = None
                reprint_count += 1
            else:
                reused = True
                old_signature_index, old_sheet_index = reuse

            result_sheets.append(
                {
                    "sheet_index": sheet["sheet_index"],
                    "front": sheet["front"],
                    "back": sheet["back"],
                    "reused": reused,
                    "old_signature_index": old_signature_index,
                    "old_sheet_index": old_sheet_index,
                }
            )

        result_signatures.append(
            {
                "signature_index": signature["signature_index"],
                "sheet_count": signature["sheet_count"],
                "page_count_padded": signature["page_count_padded"],
                "sheets": result_sheets,
            }
        )

    return {
        "max_sheets_per_signature": max_sheets,
        "binding": binding,
        "signature_count": len(result_signatures),
        "reprint_sheet_count": reprint_count,
        "signatures": result_signatures,
    }


# ---------------------------------------------------------------------------
# 印张抽检（inspect）：乱序实物印张与预期拼版的配对核对
# ---------------------------------------------------------------------------

# 四页位固定顺序：(正面左, 正面右, 背面左, 背面右)，索引 0..3
SLOT_ORDER: Tuple[str, str, str, str] = (
    "front_left",
    "front_right",
    "back_left",
    "back_right",
)

# 实物印张可被解释的四种变换（顺序即同分裁决时的变换顺序）：
# 原样、左右镜像、正反互换、两者组合。
# 每项给出“观测页位 i 应与预期页位 PERM[i] 比较”的位置置换。
TRANSFORMS: Tuple[Tuple[str, Tuple[int, int, int, int]], ...] = (
    ("none", (0, 1, 2, 3)),
    ("mirror_lr", (1, 0, 3, 2)),
    ("flip_fb", (2, 3, 0, 1)),
    ("mirror_lr_flip_fb", (3, 2, 1, 0)),
)


class _Unread:
    """页位标记：实物页位未读出（请求中的 ``"?"``）。单例 :data:`UNREAD`。"""

    _instance = None

    def __new__(cls) -> "_Unread":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:  # pragma: no cover - 仅便于调试
        return "UNREAD"

    def __bool__(self) -> bool:
        return True


UNREAD = _Unread()

# 单个页位的值：页面 ID / None（空白）/ UNREAD（未读出）
SlotValue = object


def _hungarian_min(cost: List[List[int]]) -> List[int]:
    """方阵最小权完美匹配（O(n³) 匈牙利算法）。

    返回每个行号（0-based）匹配的列号（0-based）；输入方阵元素为整数
    （允许负权、数值较大），不可行的行/列以 0 权“哑边”填充，由调用方按
    真实边解码。
    """
    n = len(cost)
    # 比任意可行松弛量都大：任意真实边的缩减代价绝对值不超过全部边权绝对值之和
    inf = sum(abs(value) for row in cost for value in row) + 1
    u = [0] * (n + 1)
    v = [0] * (n + 1)
    p = [0] * (n + 1)
    way = [0] * (n + 1)

    for i in range(1, n + 1):
        p[0] = i
        j0 = 0
        minv = [inf] * (n + 1)
        used = [False] * (n + 1)
        while p[j0] != 0:
            used[j0] = True
            i0 = p[j0]
            delta = inf
            j1 = 0
            for j in range(1, n + 1):
                if not used[j]:
                    cur = cost[i0 - 1][j - 1] - u[i0] - v[j]
                    if cur < minv[j]:
                        minv[j] = cur
                        way[j] = j0
                    if minv[j] < delta:
                        delta = minv[j]
                        j1 = j
            for j in range(n + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
        while True:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1
            if j0 == 0:
                break

    assignment = [0] * n
    for j in range(1, n + 1):
        assignment[p[j] - 1] = j - 1
    return assignment


def inspect_observed_sheets(
    page_ids: List[P],
    max_sheets: int,
    binding: Binding,
    observed_sheets: List[Tuple[SlotValue, SlotValue, SlotValue, SlotValue]],
) -> dict:
    """将乱序实物印张与按 :func:`impose_from_pages` 生成的预期印张配对核对。

    每张观测四页位的取值为页面 ID、``None``（空白）或 :data:`UNREAD`（未读出）。
    观测可按 :data:`TRANSFORMS` 的四种变换（原样、左右镜像、正反互换、两者组合）
    解释；仅当观测至少有一个**非空已读页面 ID**出现在某张预期印张上时，二者才
    允许配对。在每张预期印张、每张观测至多使用一次的约束下：

    1. 先最大化配对数；
    2. 再最大化已读页位吻合数（``None`` 与 ``None`` 也算吻合，``UNREAD`` 不计）；
    3. 同分按观测序号升序、预期帖号/张号升序、变换顺序裁决。

    返回逐观测的配对结果（帖号/张号/变换/吻合数/已知页位错误明细），
    以及未见的预期印张与无法配对的观测。
    """
    imposed = impose_from_pages(page_ids, max_sheets, binding)
    expected: List[dict] = []
    for signature in imposed:
        for sheet in signature["sheets"]:
            expected.append(
                {
                    "signature_index": signature["signature_index"],
                    "sheet_index": sheet["sheet_index"],
                    "slots": (
                        sheet["front"]["left"],
                        sheet["front"]["right"],
                        sheet["back"]["left"],
                        sheet["back"]["right"],
                    ),
                }
            )

    m = len(observed_sheets)
    n = len(expected)

    # edges[i]：观测 i 可配对的预期列 -> 候选信息（列号按帖号/张号升序）
    edges: List[List[dict]] = []
    for obs in observed_sheets:
        known_ids = {v for v in obs if v is not None and v is not UNREAD}
        candidates: List[dict] = []
        for col, exp in enumerate(expected):
            if not any(page_id in exp["slots"] for page_id in known_ids):
                continue
            best: Optional[dict] = None
            for transform_index, (transform_name, perm) in enumerate(TRANSFORMS):
                matches = 0
                mismatches: List[dict] = []
                for slot_index, value in enumerate(obs):
                    if value is UNREAD:
                        continue
                    expected_value = exp["slots"][perm[slot_index]]
                    if value == expected_value:
                        matches += 1
                    else:
                        mismatches.append(
                            {
                                "position": SLOT_ORDER[slot_index],
                                "observed": value,
                                "expected": expected_value,
                            }
                        )
                candidate = {
                    "col": col,
                    "matches": matches,
                    "transform_index": transform_index,
                    "transform": transform_name,
                    "errors": mismatches,
                }
                # 变换顺序裁决：取吻合数最多、序号最小者
                if best is None or (
                    candidate["matches"],
                    -candidate["transform_index"],
                ) > (best["matches"], -best["transform_index"]):
                    best = candidate
            assert best is not None
            candidates.append(best)
        candidates.sort(key=lambda c: c["col"])
        edges.append(candidates)

    # 单次最大权匹配完成“配对数 → 吻合数 → 字典序”三级目标：
    #   权重 = (PAIR_BASE + 吻合数) * BASE**m + 字典序奖赏
    # PAIR_BASE 大于任一方案的吻合数与字典序奖赏上限，BASE 大于任一字典序数位
    # 上限，因此整数位级比较严格对应目标优先级。字典序数位按观测序号从高位到
    # 低位排列：配对（数位 (n-col)）恒优于不配对（0），同配对下列号越小越优。
    size = max(m, n)
    lex_base = size + 1
    pair_base = 4 * m + lex_base ** m + 1
    # lex_weight[i][col] 已按 BASE 定位到观测 i 的数位
    lex_weight: List[List[int]] = [[0] * n for _ in range(m)]
    lex_scale = 1
    for i in range(m - 1, -1, -1):
        for candidate in edges[i]:
            lex_weight[i][candidate["col"]] = (n - candidate["col"]) * lex_scale
        lex_scale *= lex_base

    weight: List[List[int]] = [[0] * n for _ in range(m)]
    for i in range(m):
        for candidate in edges[i]:
            col = candidate["col"]
            weight[i][col] = (
                (pair_base + candidate["matches"]) * lex_base ** m
                + lex_weight[i][col]
            )

    # 匈牙利算法求最小权完美匹配；目标为最大化权和，故代价取负。
    # 方阵补 0 权“哑边”（不可配对的观测/预期列），解码时只认真实边。
    cost = [[0] * size for _ in range(size)]
    for i in range(m):
        for j in range(n):
            cost[i][j] = -weight[i][j]
    assignment = _hungarian_min(cost)

    chosen: List[Optional[dict]] = [None] * m
    edge_lookup = [
        {candidate["col"]: candidate for candidate in candidates}
        for candidates in edges
    ]
    for i, j in enumerate(assignment):
        if i < m and j < n and j in edge_lookup[i]:
            chosen[i] = edge_lookup[i][j]

    fixed_pairs = sum(1 for candidate in chosen if candidate is not None)

    result_observations: List[dict] = []
    matched_cols = set()
    for index, (obs, candidate) in enumerate(
        zip(observed_sheets, chosen), start=1
    ):
        front_left, front_right, back_left, back_right = obs
        item = {
            "observation_index": index,
            "front": {"left": front_left, "right": front_right},
            "back": {"left": back_left, "right": back_right},
            "matched": candidate is not None,
            "signature_index": None,
            "sheet_index": None,
            "transform": None,
            "matched_slot_count": 0,
            "errors": [],
        }
        if candidate is not None:
            exp = expected[candidate["col"]]
            matched_cols.add(candidate["col"])
            item.update(
                {
                    "signature_index": exp["signature_index"],
                    "sheet_index": exp["sheet_index"],
                    "transform": candidate["transform"],
                    "matched_slot_count": candidate["matches"],
                    "errors": candidate["errors"],
                }
            )
        result_observations.append(item)

    unseen_signatures = [
        {
            "signature_index": exp["signature_index"],
            "sheet_index": exp["sheet_index"],
            "front": {
                "left": exp["slots"][0],
                "right": exp["slots"][1],
            },
            "back": {
                "left": exp["slots"][2],
                "right": exp["slots"][3],
            },
        }
        for col, exp in enumerate(expected)
        if col not in matched_cols
    ]

    unmatched_observations = [
        {
            "observation_index": item["observation_index"],
            "front": item["front"],
            "back": item["back"],
        }
        for item in result_observations
        if not item["matched"]
    ]

    return {
        "max_sheets_per_signature": max_sheets,
        "binding": binding,
        "matched_observation_count": fixed_pairs,
        "unmatched_observation_count": m - fixed_pairs,
        "unseen_sheet_count": n - fixed_pairs,
        "observations": result_observations,
        "unmatched_observations": unmatched_observations,
        "unseen_signatures": unseen_signatures,
    }


# ---------------------------------------------------------------------------
# 订针计划（staple-plan）：在既有分帖结果上逐帖规划订针整数毫米针位
# ---------------------------------------------------------------------------

# 页高允许范围、每帖订针数允许范围
STAPLE_PAGE_HEIGHT_MIN_MM = 50
STAPLE_PAGE_HEIGHT_MAX_MM = 1000
STAPLE_COUNT_MIN = 2
STAPLE_COUNT_MAX = 4

# 针位均为整数毫米刻度，最小离散误差即 0.5 mm；浮点比较取远小于该量级的
# 容差，仅用于抵消理想针位浮点运算引入的 ULP 级偏差（如并列偏差因舍入路径
# 不同相差 1 ULP 时仍按并列处理），不改变任何离散刻度上的真实优劣
STAPLE_EPS = 1e-9

# 某帖的禁针闭区间：(起点, 终点)，均以页顶为原点、向下为正，单位 mm
StapleForbiddenInterval = Tuple[float, float]


def _staple_allowed_ticks(
    page_height_mm: float,
    top_margin_mm: float,
    bottom_margin_mm: float,
    forbidden: List[StapleForbiddenInterval],
) -> List[int]:
    """页高内可下针的整数毫米刻度（避开上/下留边与全部禁针闭区间）。"""
    ticks: List[int] = []
    # range 上界含 page_height_mm 本身，再由严格不等式排除边界
    for tick in range(1, int(math.floor(page_height_mm)) + 1):
        if not (top_margin_mm < tick < page_height_mm - bottom_margin_mm):
            continue
        if any(lo <= tick <= hi for lo, hi in forbidden):
            continue
        ticks.append(tick)
    return ticks


def _plan_staple_signature(
    page_height_mm: float,
    top_margin_mm: float,
    bottom_margin_mm: float,
    min_spacing_mm: float,
    staple_count: int,
    forbidden: List[StapleForbiddenInterval],
) -> Tuple[List[int], float]:
    """为单个帖规划递增针位。

    第 i（1-based）个理想针位为
    ``上留边 + i × (页高 − 上留边 − 下留边) / (订针数 + 1)``；
    在所有可行的递增整数毫米针位序列（避开留边、禁针闭区间，相邻针距不小于
    下限）中，依次最小化：最大绝对偏差 → 偏差总和 → 针位序列字典序。

    返回 (针位列表, 最大绝对偏差 mm)。无可行排列时抛 ValueError。
    """
    ticks = _staple_allowed_ticks(
        page_height_mm, top_margin_mm, bottom_margin_mm, forbidden
    )
    usable = page_height_mm - top_margin_mm - bottom_margin_mm
    ideals = [
        top_margin_mm + i * usable / (staple_count + 1)
        for i in range(1, staple_count + 1)
    ]
    # 每个可用刻度相对各理想针位的偏差矩阵：deviation_matrix[i][j] 为第 i 根
    # 针（自顶向下，从 0 计）落在 ticks[j] 时的绝对偏差
    deviation_matrix = [
        [abs(tick - ideal) for tick in ticks] for ideal in ideals
    ]

    def feasible_common(max_dev: float) -> bool:
        """各针偏差均不超过 max_dev（容差 STAPLE_EPS）时，能否自顶向下放下
        staple_count 根针。

        针位按针序逐根匹配：只要上一根已落在当前刻度之前（满足最小针距），
        当前刻度即可服务于下一根针；全部针都能落下即可行。
        """
        chosen = 0
        last: Optional[int] = None
        for j, tick in enumerate(ticks):
            if last is not None and tick - last < min_spacing_mm:
                continue
            if deviation_matrix[chosen][j] <= max_dev + STAPLE_EPS:
                chosen += 1
                last = tick
                if chosen == staple_count:
                    return True
        return False

    if not feasible_common(math.inf):
        raise ValueError("无可行订针排列")

    # 第 1 级目标：最小化最大绝对偏差。候选上限取实际可达偏差值，二分贪心
    candidates = sorted(
        {
            deviation_matrix[i][j]
            for i in range(staple_count)
            for j in range(len(ticks))
        }
    )
    lo, hi = 0, len(candidates) - 1
    while lo < hi:
        mid = (lo + hi) // 2
        if feasible_common(candidates[mid]):
            hi = mid
        else:
            lo = mid + 1
    optimal_max_dev = candidates[lo]

    # 偏差按 STAPLE_EPS 量化成整数“档级”比较：仅抵消理想针位浮点运算的
    # ULP 级差异（数学上相等的并列偏差不因舍入路径不同被误判优劣），
    # 离散刻度间 ≥ 1 mm 的真实差异远大量化误差，不受影响
    def level(dev: float) -> int:
        return int(round(dev / STAPLE_EPS))

    # 第 2/3 级目标：在最大偏差不超过最优上限的前提下，DP 最小化
    # (偏差总和档级, 针位序列字典序)。dp[j] = 当前针落在 ticks[j] 的最优状态，
    # 元组 (偏差总和档级, 针位元组) 直接按目标顺序比较；针位元组随前缀增长，
    # 天然实现字典序裁决。
    INF_STATE: Optional[Tuple[int, Tuple[int, ...]]] = None
    dp: List[Optional[Tuple[int, Tuple[int, ...]]]] = [None] * len(ticks)
    for j, tick in enumerate(ticks):
        if deviation_matrix[0][j] <= optimal_max_dev + STAPLE_EPS:
            dp[j] = (level(deviation_matrix[0][j]), (tick,))
    for needle in range(1, staple_count):
        ndp: List[Optional[Tuple[int, Tuple[int, ...]]]] = [
            None
        ] * len(ticks)
        best: Optional[Tuple[int, Tuple[int, ...]]] = None
        p = 0
        for j, tick in enumerate(ticks):
            # 纳入所有 ticks[p] <= tick - min_spacing 的前驱，保留最优
            while p < j and ticks[p] <= tick - min_spacing_mm:
                if dp[p] is not None and (best is None or dp[p] < best):
                    best = dp[p]
                p += 1
            if (
                best is not None
                and deviation_matrix[needle][j] <= optimal_max_dev + STAPLE_EPS
            ):
                ndp[j] = (
                    best[0] + level(deviation_matrix[needle][j]),
                    best[1] + (tick,),
                )
        dp = ndp

    final_best: Optional[Tuple[int, Tuple[int, ...]]] = INF_STATE
    for state in dp:
        if state is not None and (final_best is None or state < final_best):
            final_best = state
    if final_best is None:  # pragma: no cover - 二分已保证可行
        raise ValueError("无可行订针排列")
    positions = list(final_best[1])
    # 返回的最大偏差取所选排列的真实值（可能与最优上限仅差 ULP 级舍入）
    actual_max_dev = max(
        abs(position - ideal) for position, ideal in zip(positions, ideals)
    )
    return positions, actual_max_dev


def staple_plan(
    total_pages: int,
    max_sheets: int,
    binding: Binding,
    page_height_mm: float,
    staple_count: int,
    top_margin_mm: float,
    bottom_margin_mm: float,
    min_spacing_mm: float,
    forbidden_by_signature: List[Tuple[int, List[StapleForbiddenInterval]]],
) -> dict:
    """沿用 :func:`impose` 的分帖结果，逐帖规划订针针位。

    订针位置限于页高 ``0..page_height_mm`` 内的**整数毫米刻度**，须严格避开
    上/下留边（``top_margin_mm < y < 页高 − bottom_margin_mm``）与按帖号给出
    的禁针闭区间；同一帖内针位严格递增，相邻针距不小于 ``min_spacing_mm``。

    每帖在可行排列中依次最小化：最大绝对偏差 → 偏差总和 → 针位序列字典序；
    理想针位见 :func:`_plan_staple_signature`。任一帖无可行排列时抛
    ``ValueError``，错误信息指出帖号。

    禁针区间按帖号（从 1 开始）给出；同一帖号只能出现一次，区间须为
    ``0 ≤ 起点 ≤ 终点 ≤ 页高`` 的有限数值，帖号超出实际帖数同样报错。
    """
    if binding not in ("left", "right"):
        raise ValueError(f"非法装订方向：{binding!r}，只支持 'left' / 'right'")
    if (
        not isinstance(page_height_mm, (int, float))
        or isinstance(page_height_mm, bool)
        or not math.isfinite(page_height_mm)
        or not (
            STAPLE_PAGE_HEIGHT_MIN_MM <= page_height_mm <= STAPLE_PAGE_HEIGHT_MAX_MM
        )
    ):
        raise ValueError(
            f"页高必须为 {STAPLE_PAGE_HEIGHT_MIN_MM}～"
            f"{STAPLE_PAGE_HEIGHT_MAX_MM} mm 的有限数值"
        )
    if (
        not isinstance(staple_count, int)
        or isinstance(staple_count, bool)
        or not (STAPLE_COUNT_MIN <= staple_count <= STAPLE_COUNT_MAX)
    ):
        raise ValueError(
            f"每帖订针数必须为 {STAPLE_COUNT_MIN}～{STAPLE_COUNT_MAX} 的整数"
        )
    for name, value in (
        ("上留边", top_margin_mm),
        ("下留边", bottom_margin_mm),
        ("最小针距", min_spacing_mm),
    ):
        if (
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not math.isfinite(value)
            or value < 0
        ):
            raise ValueError(f"{name}必须为非负有限数值（单位 mm）")
    if top_margin_mm + bottom_margin_mm >= page_height_mm:
        raise ValueError("上留边与下留边之和必须小于页高")

    signatures = impose(total_pages, max_sheets, binding)
    signature_total = len(signatures)
    forbidden_map: dict = {}
    for order, (signature_index, intervals) in enumerate(
        forbidden_by_signature, start=1
    ):
        if (
            not isinstance(signature_index, int)
            or isinstance(signature_index, bool)
            or not 1 <= signature_index <= signature_total
        ):
            raise ValueError(
                f"第 {order} 组禁针区间的帖号 {signature_index!r} 无效："
                f"共 {signature_total} 帖"
            )
        if signature_index in forbidden_map:
            raise ValueError(f"第 {signature_index} 帖的禁针区间重复给出，每帖只能出现一次")
        normalized: List[StapleForbiddenInterval] = []
        for interval_index, interval in enumerate(intervals, start=1):
            if len(interval) != 2:
                raise ValueError(
                    f"第 {signature_index} 帖第 {interval_index} 个禁针区间字段不完整"
                )
            lo, hi = interval
            if not all(
                isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
                for v in (lo, hi)
            ):
                raise ValueError(
                    f"第 {signature_index} 帖第 {interval_index} 个禁针区间"
                    "必须为有限数值（单位 mm）"
                )
            if not (0 <= lo <= hi <= page_height_mm):
                raise ValueError(
                    f"第 {signature_index} 帖第 {interval_index} 个禁针区间"
                    f" [{lo}, {hi}] 非法：须满足 0 ≤ 起点 ≤ 终点 ≤ 页高"
                    f"（{page_height_mm} mm）"
                )
            normalized.append((float(lo), float(hi)))
        forbidden_map[signature_index] = tuple(normalized)

    result_signatures: List[dict] = []
    # 禁针区间相同的帖（含均无禁区的多数帖）规划结果一致，缓存复用
    plan_cache: dict = {}
    for signature in signatures:
        index = signature["signature_index"]
        key = forbidden_map.get(index, ())
        if key not in plan_cache:
            try:
                plan_cache[key] = _plan_staple_signature(
                    page_height_mm=page_height_mm,
                    top_margin_mm=top_margin_mm,
                    bottom_margin_mm=bottom_margin_mm,
                    min_spacing_mm=min_spacing_mm,
                    staple_count=staple_count,
                    forbidden=list(key),
                )
            except ValueError:
                raise ValueError(f"第 {index} 帖无可行订针排列") from None
        positions, max_deviation = plan_cache[key]
        result_signatures.append(
            {
                "signature_index": index,
                "sheet_count": signature["sheet_count"],
                "page_count_padded": signature["page_count_padded"],
                "staple_positions_mm": positions,
                "max_deviation_mm": max_deviation,
            }
        )

    return {
        "total_pages": total_pages,
        "max_sheets_per_signature": max_sheets,
        "binding": binding,
        "page_height_mm": page_height_mm,
        "staple_count": staple_count,
        "top_margin_mm": top_margin_mm,
        "bottom_margin_mm": bottom_margin_mm,
        "min_spacing_mm": min_spacing_mm,
        "signature_count": signature_total,
        "signatures": result_signatures,
    }


# ---------------------------------------------------------------------------
# 原纸备料（stock-plan）：按纸纹朝向计算单张出数，并在库存内优选原纸组合
# ---------------------------------------------------------------------------

# 原纸规格数量、单规格库存张数允许范围
STOCK_SPEC_MIN_COUNT = 1
STOCK_SPEC_MAX_COUNT = 6
STOCK_INVENTORY_MAX = 30

# 纸纹方向：width=纸纹沿原纸宽度，height=纸纹沿原纸高度
GrainDirection = Literal["width", "height"]

# 单种原纸：(宽度 mm, 高度 mm, 库存张数, 纸纹方向)
StockPaper = Tuple[int, int, int, GrainDirection]

# 尺寸核算一律使用十进制（Decimal）：留边/间隔可能是 1e-8 量级的小数，
# 二进制浮点加全局容差会把“差一丝排不下”误判为“恰好排满”（或反之），
# 只有按十进制尺寸精确比较才能保证“n 个成品 + n−1 个间隔 ≤ 可用长度”
# 这一判定不多排也不少排。

# 十进制尺寸值：整数 / 浮点 / Decimal 均可
DecimalSize = Union[int, float, Decimal]


def _to_decimal(value: DecimalSize) -> Decimal:
    """把尺寸参数转换为十进制 ``Decimal``。

    整数精确转换；浮点按 ``str()`` 的最短往返表示取值（即请求中的十进制
    字面量，如 ``0.000000025`` → ``Decimal("2.5E-8")``），避免把二进制
    浮点的表示误差带入尺寸核算。
    """
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    return Decimal(str(value))


def _decimal_prec(*values: Decimal) -> int:
    """按各操作数的最高有效位与最小小数位，估算精确十进制运算所需精度。

    ``Decimal`` 的加减乘除在结果有效位数超出上下文精度时会舍入；取
    ``最高有效位 − 最小小数位 + 10`` 可覆盖这些尺寸加减与整除的结果位数，
    保证计算精确无舍入。
    """
    high = max(value.adjusted() for value in values)
    low = min(value.as_tuple().exponent for value in values)
    return max(28, high - low + 10)


def _fit_count(usable: DecimalSize, item: DecimalSize, spacing: DecimalSize) -> int:
    """整行/整列排布数量（按十进制尺寸精确核算）。

    ``n`` 个成品加 ``n-1`` 个间隔的实际占用为 ``n*item + (n-1)*spacing``，
    只有该占用不超过可用长度 ``usable`` 才计入 ``n``；恰好贴边（占用等于
    可用长度）仍可排入。等价于 ``n ≤ (usable + spacing) / (item + spacing)``
    的最大整数；可用长度小于单个成品、或成品尺寸非正时结果为 0。
    """
    usable_d = _to_decimal(usable)
    item_d = _to_decimal(item)
    spacing_d = _to_decimal(spacing)
    if item_d <= 0 or usable_d < item_d:
        return 0
    with localcontext() as ctx:
        ctx.prec = _decimal_prec(usable_d, item_d, spacing_d)
        step = item_d + spacing_d
        total = usable_d + spacing_d
        # n*item + (n-1)*spacing <= usable  ⇔  n <= total / step；
        # 十进制整除 // 精确无舍入，恰好整除（贴边）时同样计入
        count = int(total // step)
    return max(0, count)


def _pieces_per_sheet(
    stock_width_mm: int,
    stock_height_mm: int,
    grain: GrainDirection,
    sheet_width_mm: DecimalSize,
    sheet_height_mm: DecimalSize,
    margin_mm: float,
    spacing_mm: float,
) -> Tuple[int, int, int, float, float]:
    """计算单张原纸在唯一合法朝向下的整行整列出数。

    成品书脊沿页高，只能按**书脊与纸纹平行**落版（不允许旋转调换朝向）：

    - ``grain="height"``：成品高（书脊方向）沿原纸高，成品宽沿原纸宽；
    - ``grain="width"``：成品高（书脊方向）沿原纸宽，成品宽沿原纸高。

    扣除四周留边后的可用区域为
    ``(原纸宽 − 2 × 留边) × (原纸高 − 2 × 留边)``，成品之间留出统一裁切间隔，
    行列均按整行整列排满；可用长度与每行/每列实际占用均按**十进制尺寸**
    精确核算（``n`` 个成品加 ``n−1`` 个间隔不超过可用长度才计入 ``n``，
    恰好贴边仍可排入）。返回 ``(单张出数, 列数, 行数, 可用宽, 可用高)``。
    """
    if grain not in ("width", "height"):
        raise ValueError(f"非法纸纹方向：{grain!r}，只支持 'width' / 'height'")
    # 十进制可用区域：原纸整数毫米 − 2 × 留边，精确到留边的十进制位
    stock_w_d = _to_decimal(stock_width_mm)
    stock_h_d = _to_decimal(stock_height_mm)
    margin_d = _to_decimal(margin_mm)
    with localcontext() as ctx:
        ctx.prec = _decimal_prec(stock_w_d, stock_h_d, margin_d)
        usable_w_d = stock_w_d - 2 * margin_d
        usable_h_d = stock_h_d - 2 * margin_d
    if grain == "height":
        columns = _fit_count(usable_w_d, sheet_width_mm, spacing_mm)
        rows = _fit_count(usable_h_d, sheet_height_mm, spacing_mm)
    else:
        # 成品旋转 90° 落版（书脊与沿宽纸纹平行）：成品高沿原纸宽、成品宽沿原纸高
        columns = _fit_count(usable_w_d, sheet_height_mm, spacing_mm)
        rows = _fit_count(usable_h_d, sheet_width_mm, spacing_mm)
    return columns * rows, columns, rows, float(usable_w_d), float(usable_h_d)


def _choose_stock_usage(
    pieces: List[int],
    area_weights: List[int],
    inventories: List[int],
    demand: int,
) -> Optional[Tuple[int, ...]]:
    """库存内优选用量组合（折半枚举）。

    参数：单张出数 ``pieces``、单张面积 ``area_weights``（mm²，整数）、库存张数
    ``inventories``、总需求 ``demand``。在 ``0 ≤ u[i] ≤ inventories[i]`` 且
    ``Σ u[i]·pieces[i] ≥ demand`` 的组合中，依次最小化
    ``(Σ u[i]·area_weights[i], Σ u[i]·pieces[i], u 字典序)``；
    无可行组合返回 ``None``。
    """
    n = len(pieces)
    split = n // 2
    left_indices = list(range(split))
    right_indices = list(range(split, n))

    def enumerate_part(indices: List[int]) -> List[Tuple[int, int, Tuple[int, ...]]]:
        """枚举这一半规格的全部用量组合 (产量, 面积, 各规格用量)。"""
        combos: List[Tuple[int, int, Tuple[int, ...]]] = [(0, 0, ())]
        for idx in indices:
            extended: List[Tuple[int, int, Tuple[int, ...]]] = []
            for production, area, usage in combos:
                for used in range(inventories[idx] + 1):
                    extended.append(
                        (
                            production + used * pieces[idx],
                            area + used * area_weights[idx],
                            usage + (used,),
                        )
                    )
            combos = extended
        return combos

    left_combos = enumerate_part(left_indices)
    right_combos = enumerate_part(right_indices)

    # 同一半内安全剪枝：(产量, 面积) 完全相同的组合只保留用量字典序最小者
    # （面积、产量均相同，字典序最小者在任何搭档下都最优）。不能按面积或
    # 产量单独支配剪枝——更大面积的左半组合可能与更省的右半组合拼成全局最优。
    # enumerate_part 按用量字典序生成，稳定排序后同键组合天然保持字典序。
    def dedup(
        combos: List[Tuple[int, int, Tuple[int, ...]]],
    ) -> List[Tuple[int, int, Tuple[int, ...]]]:
        combos.sort(key=lambda item: (item[0], item[1]))
        unique: List[Tuple[int, int, Tuple[int, ...]]] = []
        for combo in combos:
            if unique and (combo[0], combo[1]) == (unique[-1][0], unique[-1][1]):
                continue
            unique.append(combo)
        return unique

    left_combos = dedup(left_combos)
    right_combos = dedup(right_combos)

    # suffix_best[k] = left_combos[k:]（产量不小于第 k 档）中使
    # (面积, 产量, 用量字典序) 最小的组合。对固定的右半组合，左半只需满足
    # 产量下界；面积为全局第一目标，故阈值之上该键最小者即最佳搭档。
    suffix_best: List[int] = [0] * len(left_combos)
    running = len(left_combos) - 1
    for k in range(len(left_combos) - 1, -1, -1):
        candidate = left_combos[k]
        if k == len(left_combos) - 1 or (
            candidate[1],
            candidate[0],
            candidate[2],
        ) < (
            left_combos[running][1],
            left_combos[running][0],
            left_combos[running][2],
        ):
            running = k
        suffix_best[k] = running
    left_productions = [combo[0] for combo in left_combos]

    best: Optional[Tuple[int, int, Tuple[int, ...]]] = None
    for r_production, r_area, r_usage in right_combos:
        required_left = demand - r_production
        # bisect_left：左半产量 ≥ required_left 的第一档；
        # required_left ≤ 0 时下界为 0（允许左半一张不用）
        k = bisect.bisect_left(left_productions, max(0, required_left))
        if k >= len(left_combos):
            continue
        l_production, l_area, l_usage = left_combos[suffix_best[k]]
        candidate = (
            r_production + l_production,
            r_area + l_area,
            l_usage + r_usage,
        )
        # 全局键：面积优先、总产量（超产）次之、用量字典序最后
        key = (candidate[1], candidate[0], candidate[2])
        if best is None or key < (best[1], best[0], best[2]):
            best = candidate

    if best is None:
        return None
    return best[2]


def plan_stock(
    total_pages: int,
    max_sheets: int,
    binding: Binding,
    page_width_mm: float,
    page_height_mm: float,
    gutter_mm: float,
    copies: int,
    papers: List[StockPaper],
    margin_mm: float,
    spacing_mm: float,
) -> dict:
    """原纸备料：计算每册印张需求并在库存原纸中优选组合。

    需求与成品尺寸沿用拼版/机台版面：

    - 每册印张数沿用 :func:`impose` 的分帖结果（含末帖补白张，每张 4 页），
      总需求 = 每册印张数 × 印数 ``copies``；
    - 成品印张尺寸沿用机台版面：宽 ``2 × 页宽 + 中缝``、高 = 页高，
      书脊沿页高方向。

    每种原纸给整数毫米宽高、库存张数（0～30）与纸纹方向（``width`` 沿宽 /
    ``height`` 沿高）。成品只能按**书脊与纸纹平行**的唯一朝向，在扣除四周
    统一留边 ``margin_mm`` 的可用区域内、按统一裁切间隔 ``spacing_mm``
    整行整列排满，得到该规格单张出数。出数按**十进制尺寸**精确核算：
    某方向排 ``n`` 个成品的实际占用为 ``n × 成品尺寸 + (n−1) × 间隔``，
    只有不超过扣边后的可用长度才计入 ``n``，恰好贴边仍可排入。

    在各规格库存张数内选择用量组合，使总产量满足总需求，并依次最小化：
    原纸总面积 → 超产张数（总产量 − 总需求）→ 按输入顺序的用量字典序。
    无可行组合（含全部规格单张出数均为 0）时抛 ``ValueError``。
    """
    if binding not in ("left", "right"):
        raise ValueError(f"非法装订方向：{binding!r}，只支持 'left' / 'right'")
    if (
        not isinstance(total_pages, int)
        or isinstance(total_pages, bool)
        or total_pages < 1
    ):
        raise ValueError("总页数 total_pages 必须为正整数")
    if not isinstance(max_sheets, int) or isinstance(max_sheets, bool) or max_sheets < 1:
        raise ValueError("每帖最多纸张数 max_sheets 必须为正整数")
    for name, value in (
        ("页宽", page_width_mm),
        ("页高", page_height_mm),
    ):
        if (
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not math.isfinite(value)
            or value <= 0
        ):
            raise ValueError(f"{name}必须为正数（有限数值，单位 mm）")
    if (
        not isinstance(gutter_mm, (int, float))
        or isinstance(gutter_mm, bool)
        or not math.isfinite(gutter_mm)
        or gutter_mm < 0
    ):
        raise ValueError("中缝宽度必须为非负数（有限数值，单位 mm）")
    if not isinstance(copies, int) or isinstance(copies, bool) or copies < 1:
        raise ValueError("印数 copies 必须为正整数")
    for name, value in (("四周留边", margin_mm), ("裁切间隔", spacing_mm)):
        if (
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not math.isfinite(value)
            or value < 0
        ):
            raise ValueError(f"{name}必须为非负有限数值（单位 mm）")
    if not (
        isinstance(papers, list)
        and STOCK_SPEC_MIN_COUNT <= len(papers) <= STOCK_SPEC_MAX_COUNT
    ):
        raise ValueError(
            f"原纸规格必须为 {STOCK_SPEC_MIN_COUNT}～{STOCK_SPEC_MAX_COUNT} 种"
        )

    signatures = impose(total_pages, max_sheets, binding)
    sheets_per_copy = sum(signature["sheet_count"] for signature in signatures)
    demand = sheets_per_copy * copies

    sheet_width = 2 * page_width_mm + gutter_mm
    sheet_height = page_height_mm
    # 十进制成品尺寸：与响应回显的浮点值同源，但按十进制合成
    # （避免 2 × 页宽 + 中缝 的二进制浮点组合误差进入出数核算）
    page_width_d = _to_decimal(page_width_mm)
    gutter_d = _to_decimal(gutter_mm)
    page_height_d = _to_decimal(page_height_mm)
    with localcontext() as ctx:
        ctx.prec = _decimal_prec(page_width_d, gutter_d, page_height_d)
        sheet_width_d = 2 * page_width_d + gutter_d
        sheet_height_d = page_height_d

    pieces: List[int] = []
    areas: List[int] = []
    inventories: List[int] = []
    paper_results: List[dict] = []
    for index, paper in enumerate(papers, start=1):
        if len(paper) != 4:
            raise ValueError(f"第 {index} 种原纸字段不完整")
        width, height, inventory, grain = paper
        for name, value in (("宽", width), ("高", height), ("库存", inventory)):
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError(f"第 {index} 种原纸的{name}必须为非负整数")
        if width < 1 or height < 1:
            raise ValueError(f"第 {index} 种原纸的宽、高必须为正整数（mm）")
        if inventory > STOCK_INVENTORY_MAX:
            raise ValueError(
                f"第 {index} 种原纸的库存不能超过 {STOCK_INVENTORY_MAX} 张"
            )
        per_sheet, columns, rows, usable_w, usable_h = _pieces_per_sheet(
            width,
            height,
            grain,
            sheet_width_d,
            sheet_height_d,
            margin_mm,
            spacing_mm,
        )
        pieces.append(per_sheet)
        areas.append(width * height)
        inventories.append(inventory)
        paper_results.append(
            {
                "paper_index": index,
                "width_mm": width,
                "height_mm": height,
                "grain": grain,
                "inventory": inventory,
                "pieces_per_sheet": per_sheet,
                "columns": columns,
                "rows": rows,
                "usable_width_mm": usable_w,
                "usable_height_mm": usable_h,
                "used": 0,
                "production": 0,
                "area_mm2": 0,
            }
        )

    capacity = sum(
        inventory * per_sheet
        for inventory, per_sheet in zip(inventories, pieces)
    )
    if capacity < demand:
        raise ValueError(
            f"库存原纸满负荷最多产出 {capacity} 张成品印张，"
            f"无法满足总需求 {demand} 张（每册 {sheets_per_copy} 张 × 印数 {copies}）"
        )

    usage = _choose_stock_usage(pieces, areas, inventories, demand)
    # 容量预判已保证可行；防御性处理避免 None 误下发
    if usage is None:  # pragma: no cover - 容量上界已保证存在可行组合
        raise ValueError("无可行原纸组合")

    total_production = 0
    total_area = 0
    for item, used in zip(paper_results, usage):
        per_sheet = pieces[item["paper_index"] - 1]
        item["used"] = used
        item["production"] = used * per_sheet
        item["area_mm2"] = used * areas[item["paper_index"] - 1]
        total_production += item["production"]
        total_area += item["area_mm2"]

    return {
        "total_pages": total_pages,
        "max_sheets_per_signature": max_sheets,
        "binding": binding,
        "page_width_mm": page_width_mm,
        "page_height_mm": page_height_mm,
        "gutter_mm": gutter_mm,
        "copies": copies,
        "margin_mm": margin_mm,
        "spacing_mm": spacing_mm,
        "signature_count": len(signatures),
        "sheets_per_copy": sheets_per_copy,
        "total_demand": demand,
        "sheet_width_mm": sheet_width,
        "sheet_height_mm": sheet_height,
        "papers": paper_results,
        "total_production": total_production,
        "surplus": total_production - demand,
        "total_area_mm2": total_area,
    }


# ---------------------------------------------------------------------------
# 骑马订爬移补偿（creep-plan）：按帖独立计算各页位图像向折缝中心的水平位移
# ---------------------------------------------------------------------------


def _creep_slot(placement: Optional[dict], slot: str, creep: float) -> dict:
    """单个页位的爬移补偿结果。

    左槽图像向纸面右侧平移（``+creep``）、右槽向纸面左侧平移（``−creep``），
    均指向纸面折缝中心；阅读方向稿件位移按页位旋转角换算：0° 与纸面位移
    相同，180° 取反。空白页位页码为 ``None``、两项位移均为 0。
    """
    if placement is None:
        return {"page": None, "paper_shift_x_mm": 0.0, "artwork_shift_x_mm": 0.0}
    if creep == 0:
        # 最外张位移为 0：直接取 0.0，避免右槽/180° 页位出现 -0.0
        paper_shift = 0.0
        artwork_shift = 0.0
    else:
        paper_shift = creep if slot == "left" else -creep
        artwork_shift = (
            paper_shift if placement["rotation_deg"] == 0 else -paper_shift
        )
    return {
        "page": placement["page"],
        "paper_shift_x_mm": paper_shift,
        "artwork_shift_x_mm": artwork_shift,
    }


def creep_plan(
    total_pages: int,
    max_sheets: int,
    binding: Binding,
    page_width_mm: float,
    page_height_mm: float,
    gutter_mm: float,
    duplex_flip: DuplexFlip,
    thickness_mm: float,
) -> dict:
    """骑马订爬移补偿：按帖独立计算各页位图像向折缝中心的水平位移。

    页序、槽位与旋转规则完全沿用 :func:`press_layout`（左右装订与长/短边
    翻转均以机台版面的实际槽位和旋转角为准）。爬移按帖独立计算：最外张
    （张号 1）位移为 0，向内第 ``n`` 张的爬移量为
    ``2 × (n−1) × thickness_mm``；该张正反面左右页位的图像均向纸面折缝
    中心（纸面竖直中线）平移该量：

    - 左槽（``x = 0``）：向纸面右侧平移，纸面水平位移为 ``+爬移量``；
    - 右槽（``x = 页宽 + 中缝``）：向纸面左侧平移，纸面水平位移为 ``−爬移量``。

    阅读方向稿件水平位移按页位 ``rotation_deg`` 换算：0° 与纸面位移相同，
    180° 取反。空白页位（末帖补白）保留在结果中，页码为 ``None``、
    两项位移均为 0。

    爬移量与“达到单页宽度”的判定按**十进制尺寸**精确核算（与
    :func:`plan_stock` 相同的十进制约定）：任一张的爬移量达到单页宽度
    （``≥ page_width_mm``）时抛 ``ValueError``（API 层对应 422），
    错误信息指出帖号与张号。``thickness_mm`` 必须为正有限数。
    """
    if (
        not isinstance(thickness_mm, (int, float))
        or isinstance(thickness_mm, bool)
        or not math.isfinite(thickness_mm)
        or thickness_mm <= 0
    ):
        raise ValueError("单张纸厚度 thickness_mm 必须为正数（有限数值，单位 mm）")

    layout = press_layout(
        total_pages,
        max_sheets,
        binding,
        page_width_mm,
        page_height_mm,
        gutter_mm,
        duplex_flip,
    )
    # 十进制精确核算：爬移量 = 2 × (张号 − 1) × 纸厚，
    # 边界“达到单页宽度”不能用二进制浮点比较（如 6 × 0.15 在浮点下 < 0.9）
    thickness_d = _to_decimal(thickness_mm)
    page_width_d = _to_decimal(page_width_mm)

    result_signatures: List[dict] = []
    for signature in layout["signatures"]:
        result_sheets: List[dict] = []
        for sheet in signature["sheets"]:
            sheet_index = sheet["sheet_index"]
            creep_d = Decimal(2 * (sheet_index - 1)) * thickness_d
            if creep_d >= page_width_d:
                raise ValueError(
                    f"第 {signature['signature_index']} 帖第 {sheet_index} 张"
                    f"爬移量 {float(creep_d)} mm 达到单页宽度 "
                    f"{page_width_mm} mm，无法完成爬移补偿"
                )
            creep = float(creep_d)
            result_sheets.append(
                {
                    "sheet_index": sheet_index,
                    "creep_mm": creep,
                    "front": {
                        "left": _creep_slot(sheet["front"]["left"], "left", creep),
                        "right": _creep_slot(sheet["front"]["right"], "right", creep),
                    },
                    "back": {
                        "left": _creep_slot(sheet["back"]["left"], "left", creep),
                        "right": _creep_slot(sheet["back"]["right"], "right", creep),
                    },
                }
            )
        result_signatures.append(
            {
                "signature_index": signature["signature_index"],
                "sheet_count": signature["sheet_count"],
                "page_count_padded": signature["page_count_padded"],
                "sheets": result_sheets,
            }
        )

    return {
        "total_pages": total_pages,
        "max_sheets_per_signature": max_sheets,
        "binding": binding,
        "page_width_mm": page_width_mm,
        "page_height_mm": page_height_mm,
        "gutter_mm": gutter_mm,
        "duplex_flip": duplex_flip,
        "thickness_mm": thickness_mm,
        "paper_width_mm": layout["paper_width_mm"],
        "paper_height_mm": layout["paper_height_mm"],
        "signature_count": len(result_signatures),
        "signatures": result_signatures,
    }
