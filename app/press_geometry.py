"""机台版面页位几何规则：可复用的双向坐标变换。

机台版面各接口（``press-layout`` 生成页位、``locate-defects`` 反查纸面点、
``ink-zones`` / ``trim-safety`` 映射页内矩形）共用本模块的同一套规则，避免各处
独立计算产生坐标分歧：

- 装订方向（``binding``）与双面翻转（``duplex_flip``）由 :func:`impose` 的页序与
  :class:`PressGeometry` 共同决定每个**实际槽位**上的页码；
- 槽位原点只取决于槽位本身：左槽 ``x = 0``、右槽 ``x = 页宽 + 中缝``，``y = 0``；
- 正面恒为 0°；``long``（长边翻转）背面交换左右槽、旋转 0°；``short``（短边翻转）
  背面保持槽位、各页位绕自身中心旋转 180°。

:class:`Placement` 同时承载页码、所在面/槽位、槽位原点与旋转角；点与矩形的
页内 ⇄ 纸面变换互为逆变换（0° 平移、180° 绕页位中心），中缝（gutter）与空白页位
（页码 ``None``）的语义不在本模块内，由各调用方按既有约定处理。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, Literal, Optional, TypeVar

Binding = Literal["left", "right"]
DuplexFlip = Literal["long", "short"]
Side = Literal["front", "back"]
Slot = Literal["left", "right"]

# 页面标识类型：页码（int）或页面 ID（str）
P = TypeVar("P")

_SIDES: tuple[Side, Side] = ("front", "back")
_SLOTS: tuple[Slot, Slot] = ("left", "right")


@dataclass(frozen=True)
class Placement(Generic[P]):
    """单个**实际页位**的完整几何描述。

    - ``page``：该槽位上的页码（或页面 ID）；``None`` 表示末帖补白的空白页位；
    - ``side`` / ``slot``：实际所在的面（正面/背面）与槽位（左/右）；
    - ``x_mm`` / ``y_mm``：页位（未旋转时）左上角在纸面上的坐标，
      以纸面左上角为原点（x 向右、y 向下，单位 mm）；0°/180° 不改变外接框，
      故即便是 180° 页位，原点也与槽位左上角一致；
    - ``rotation_deg``：绕页位中心的旋转角，只可能为 0 或 180。
    """

    page: Optional[P]
    side: Side
    slot: Slot
    x_mm: float
    y_mm: float
    rotation_deg: Literal[0, 180]


def placement_payload(placement: Optional[Placement]) -> Optional[dict]:
    """把页位序列化为 press-layout 响应字段；空白页位（``None``）原样返回 ``None``。"""
    if placement is None:
        return None
    return {
        "page": placement.page,
        "x_mm": placement.x_mm,
        "y_mm": placement.y_mm,
        "rotation_deg": placement.rotation_deg,
    }


@dataclass(frozen=True)
class PressGeometry:
    """纸面/槽位几何与页位双向坐标变换（与装订、页序无关的纯几何部分）。

    实际槽位上放哪个页码由 :meth:`place_sheet` 结合 :func:`impose` 的拼版结果决定；
    本类只负责槽位原点、旋转角与坐标换算。
    """

    page_width_mm: float
    page_height_mm: float
    gutter_mm: float
    duplex_flip: DuplexFlip

    def __post_init__(self) -> None:
        if self.duplex_flip not in ("long", "short"):
            raise ValueError(
                f"非法双面翻转模式：{self.duplex_flip!r}，只支持 'long' / 'short'"
            )

    # -- 纸面与槽位 ----------------------------------------------------------

    @property
    def paper_width_mm(self) -> float:
        """纸面宽 = 2 × 页宽 + 中缝。"""
        return 2 * self.page_width_mm + self.gutter_mm

    @property
    def paper_height_mm(self) -> float:
        """纸面高 = 页高。"""
        return self.page_height_mm

    @property
    def fold_x_mm(self) -> float:
        """折缝线（纸面/中缝中心线）x 坐标 = 页宽 + 中缝 / 2。"""
        return self.paper_width_mm / 2.0

    def slot_origin_x_mm(self, slot: Slot) -> float:
        """槽位左上角 x：左槽 0，右槽 = 页宽 + 中缝。所有槽位 y 恒为 0。"""
        if slot == "left":
            return 0.0
        if slot == "right":
            return self.page_width_mm + self.gutter_mm
        raise ValueError(f"非法槽位：{slot!r}，只支持 'left' / 'right'")

    def side_rotation_deg(self, side: Side) -> Literal[0, 180]:
        """该面页位旋转角：正面恒 0；背面 long=0、short=180。"""
        if side == "front":
            return 0
        if side == "back":
            return 0 if self.duplex_flip == "long" else 180
        raise ValueError(f"非法面：{side!r}，只支持 'front' / 'back'")

    # -- 实际槽位上的页码 ----------------------------------------------------

    def _imposed_page(self, imposed_sheet: dict, side: Side, slot: Slot):
        """按翻转模式取一张拼版结果在**实际槽位** ``(side, slot)`` 上的页码。

        正面：槽位与拼版结果一致；``long`` 背面交换左右槽（实际槽位取拼版背面
        另一侧的页）；``short`` 背面保持槽位。
        """
        if side == "front":
            return imposed_sheet["front"][slot]
        if side == "back":
            if self.duplex_flip == "long":
                imposed_slot: Slot = "right" if slot == "left" else "left"
                return imposed_sheet["back"][imposed_slot]
            return imposed_sheet["back"][slot]
        raise ValueError(f"非法面：{side!r}，只支持 'front' / 'back'")

    def place(
        self, imposed_sheet: dict, side: Side, slot: Slot
    ) -> Optional[Placement]:
        """生成一张拼版结果在指定实际槽位上的 :class:`Placement`；空白页位为 ``None``。"""
        page = self._imposed_page(imposed_sheet, side, slot)
        if page is None:
            return None
        return Placement(
            page=page,
            side=side,
            slot=slot,
            x_mm=self.slot_origin_x_mm(slot),
            y_mm=0.0,
            rotation_deg=self.side_rotation_deg(side),
        )

    def place_sheet(self, imposed_sheet: dict) -> dict:
        """生成一张纸正反面四个实际槽位的页位（空白页位为 ``None``）。"""
        return {
            side: {slot: self.place(imposed_sheet, side, slot) for slot in _SLOTS}
            for side in _SIDES
        }

    # -- 纸面区域判定 --------------------------------------------------------

    def region_at_x(self, x_mm: float) -> Literal["left", "gutter", "right"]:
        """按 x 坐标判定纸面区域：左槽 / 中缝 / 右槽。

        区间为左槽 ``[0, 页宽)``、中缝 ``[页宽, 页宽 + 中缝)``、
        右槽 ``[页宽 + 中缝, 纸面宽]``；``gutter_mm = 0`` 时中缝区间为空，
        ``x = 页宽`` 直接落入右槽。调用方须先确认点在纸面范围内。
        """
        if x_mm < self.page_width_mm:
            return "left"
        if x_mm < self.page_width_mm + self.gutter_mm:
            return "gutter"
        return "right"

    def contains_paper_point(self, x_mm: float, y_mm: float) -> bool:
        """点是否在纸面内（含四边边缘；NaN/Infinity 一律视为不在）。"""
        return (
            0.0 <= x_mm <= self.paper_width_mm
            and 0.0 <= y_mm <= self.paper_height_mm
        )

    # -- 双向点变换：页内 ⇄ 纸面 --------------------------------------------

    def page_to_paper_point(
        self, placement: Placement, page_x_mm: float, page_y_mm: float
    ) -> tuple[float, float]:
        """阅读方向页内点 -> 纸面点（按页位槽位原点与 0°/180° 旋转）。

        0°：纸面点 = 槽位原点 + 页内点；180°：绕页位中心旋转，
        ``纸面 x = 槽位 x + 页宽 − 页内 x``、``纸面 y = 页高 − 页内 y``。
        """
        if placement.rotation_deg == 180:
            return (
                placement.x_mm + self.page_width_mm - page_x_mm,
                placement.y_mm + self.page_height_mm - page_y_mm,
            )
        return (
            placement.x_mm + page_x_mm,
            placement.y_mm + page_y_mm,
        )

    def paper_to_page_point(
        self, placement: Placement, paper_x_mm: float, paper_y_mm: float
    ) -> tuple[float, float]:
        """纸面点 -> 阅读方向页内点，为 :meth:`page_to_paper_point` 的逆变换。

        0°：页内点 = 纸面点 − 槽位原点；180°：槽内坐标再逆转 180°，
        ``页内 x = 页宽 − (纸面 x − 槽位 x)``、``页内 y = 页高 − (纸面 y − 槽位 y)``。
        """
        dx = paper_x_mm - placement.x_mm
        dy = paper_y_mm - placement.y_mm
        if placement.rotation_deg == 180:
            return (
                self.page_width_mm - dx,
                self.page_height_mm - dy,
            )
        return dx, dy

    # -- 双向矩形变换：页内 ⇄ 纸面 ------------------------------------------

    def page_rect_to_paper(
        self,
        placement: Placement,
        x_mm: float,
        y_mm: float,
        width_mm: float,
        height_mm: float,
    ) -> tuple[float, float, float, float]:
        """阅读方向页内矩形（左上 x/y、宽、高）-> 纸面矩形。

        0°：纸面左上角 = 槽位左上角 + 页内左上角，宽高不变；180°：绕页位中心旋转，
        纸面左上角 =
        ``(槽位 x + 页宽 − x − width, 槽位 y + 页高 − y − height)``，宽高不变。
        非对称矩形（宽 ≠ 高）同样只做 180° 旋转，宽高不交换。
        """
        if placement.rotation_deg == 180:
            return (
                placement.x_mm + self.page_width_mm - x_mm - width_mm,
                placement.y_mm + self.page_height_mm - y_mm - height_mm,
                width_mm,
                height_mm,
            )
        return (
            placement.x_mm + x_mm,
            placement.y_mm + y_mm,
            width_mm,
            height_mm,
        )

    def paper_rect_to_page(
        self,
        placement: Placement,
        x_mm: float,
        y_mm: float,
        width_mm: float,
        height_mm: float,
    ) -> tuple[float, float, float, float]:
        """纸面矩形 -> 阅读方向页内矩形，为 :meth:`page_rect_to_paper` 的逆变换。

        0°：页内左上角 = 纸面左上角 − 槽位左上角；180°：
        ``页内 x = 槽位 x + 页宽 − 纸面 x − width``、
        ``页内 y = 槽位 y + 页高 − 纸面 y − height``，宽高不变。
        """
        if placement.rotation_deg == 180:
            return (
                placement.x_mm + self.page_width_mm - x_mm - width_mm,
                placement.y_mm + self.page_height_mm - y_mm - height_mm,
                width_mm,
                height_mm,
            )
        return (
            x_mm - placement.x_mm,
            y_mm - placement.y_mm,
            width_mm,
            height_mm,
        )
