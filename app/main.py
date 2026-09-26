"""离线小册子拼版 API。"""
from __future__ import annotations

import math
from typing import Literal, Optional

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field, ConfigDict, field_validator, model_validator

from .imposition import (
    creep_plan,
    impose,
    impose_chapters,
    ink_zones,
    inspect_observed_sheets,
    locate_defects,
    plan_reprint,
    plan_stock,
    press_layout,
    staple_plan,
    trim_safety,
    UNREAD,
)
from .proof import (
    PROOF_MAX_SHEETS,
    render_proof_pdf,
    total_sheet_count,
    validate_sheet_limit,
)

app = FastAPI(
    title="离线小册子拼版 API",
    description=(
        "按帖拆分并完成小册子拼版（signature imposition）。"
        "左装订最外张正面为 末页/首页，背面为 次页/倒数第二页；"
        "右装订左右页位镜像交换。"
        "支持按章节首页分帖：章节不可跨帖，相邻章节可合帖。"
        "支持旧版/新版重印复用：四页位完全相同且均未改动的旧印张可整张复用。"
        "支持印张抽检：把乱序实物印张（可原样/左右镜像/正反互换/两者组合解释）"
        "与预期拼版配对并核对已知页位。"
        "支持机台版面：在拼版结果上给出纸面尺寸与正反面各页位的坐标、旋转角。"
        "支持瑕疵定位：把纸面上的瑕疵点（帖号/张号/面/坐标）反查为原稿页码"
        "与阅读方向的页内坐标，中缝与空白页位单独标记。"
        "支持墨区着墨面积：页内矩形随页位 0°/180° 方向映射到纸面，跨等宽墨区"
        "按交叠面积拆分，按帖/张/正反面/墨区给出 CMYK 各通道等效着墨面积乘印数。"
        "支持外裁/折缝安全检查：按实际页码给出阅读方向的受保护内容矩形，映射到纸面后"
        "逐张逐面核对中缝侧折缝安全距离与其余三边外裁安全距离（贴安全线合格），"
        "逐处返回帖号/张号/正反面/页码/违规边/纸面矩形，空白页位跳过。"
        "支持双面拼版校样：按机台版面输出可下载的 proof.pdf。"
        "支持订针计划：沿用分帖结果，在页高整数毫米刻度上避开留边与按帖禁针闭区间，"
        "以最大绝对偏差最小（并列再比偏差总和、针位字典序）为每帖规划递增订针针位。"
        "支持原纸备料：沿用拼版参数计算每册印张数并乘印数得到总需求，沿用机台版面的"
        "成品印张尺寸；在扣除四周留边的可用区域内按书脊与纸纹平行的唯一朝向，"
        "按十进制尺寸精确核算整行整列排布（n 个成品加 n−1 个间隔不超过可用长度才计入 n，"
        "恰好贴边仍可排入），给出各规格单张出数，并在库存内选择总面积最小"
        "（并列再比超产、用量字典序）的原纸组合。"
        "支持骑马订爬移补偿：沿用机台版面参数并接收单张纸厚度，按帖独立计算"
        "（最外张位移为 0，向内第 n 张爬移量为 2×(n−1)×厚度），各页位图像向"
        "纸面折缝中心平移，逐页位返回纸面水平位移与按 0°/180° 旋转换算的阅读方向"
        "稿件水平位移；爬移量达到单页宽度时返回 422。"
    ),
    version="1.11.0",
)


class ImpositionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total_pages: int = Field(
        ..., ge=1, description="总页数，正整数（1, 2, 3, ...）"
    )
    max_sheets_per_signature: int = Field(
        ..., ge=1, description="每帖最多纸张数，正整数；每帖最多容纳其 4 倍页数"
    )
    binding: Literal["left", "right"] = Field(
        ..., description="装订方向：left=左装订，right=右装订"
    )


class PagePair(BaseModel):
    left: Optional[int] = Field(..., description="左页页码，空白页为 null")
    right: Optional[int] = Field(..., description="右页页码，空白页为 null")


class Sheet(BaseModel):
    sheet_index: int = Field(..., description="帖内纸张序号，从 1 开始（1 为最外张）")
    front: PagePair = Field(..., description="正面左右页码")
    back: PagePair = Field(..., description="背面左右页码")


class Signature(BaseModel):
    signature_index: int = Field(..., description="帖号，从 1 开始")
    sheet_count: int = Field(..., description="本帖纸张数")
    page_count_padded: int = Field(..., description="本帖补齐空白后的总页数（4 的倍数）")
    sheets: list[Sheet] = Field(..., description="帖内纸张，按从外到内排列")


class ImpositionResponse(BaseModel):
    total_pages: int
    max_sheets_per_signature: int
    binding: Literal["left", "right"]
    signature_count: int
    signatures: list[Signature]


# ---------------------------------------------------------------------------
# 机台版面 /api/v1/impose/press-layout
# ---------------------------------------------------------------------------


class PressLayoutRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total_pages: int = Field(
        ..., ge=1, description="总页数，正整数（1, 2, 3, ...）"
    )
    max_sheets_per_signature: int = Field(
        ..., ge=1, description="每帖最多纸张数，正整数；每帖最多容纳其 4 倍页数"
    )
    binding: Literal["left", "right"] = Field(
        ..., description="装订方向：left=左装订，right=右装订"
    )
    page_width_mm: float = Field(..., description="单页宽度（mm），正数")
    page_height_mm: float = Field(..., description="单页高度（mm），正数")
    gutter_mm: float = Field(..., description="中缝宽度（mm），非负数")
    duplex_flip: Literal["long", "short"] = Field(
        ..., description="双面翻转方式：long=长边翻转，short=短边翻转"
    )

    @field_validator("page_width_mm", "page_height_mm")
    @classmethod
    def validate_positive_mm(cls, value: float) -> float:
        if not math.isfinite(value) or value <= 0:
            raise ValueError("页宽、页高必须为正数（有限数值，单位 mm）")
        return value

    @field_validator("gutter_mm")
    @classmethod
    def validate_non_negative_mm(cls, value: float) -> float:
        if not math.isfinite(value) or value < 0:
            raise ValueError("中缝宽度必须为非负数（有限数值，单位 mm）")
        return value


class PagePlacement(BaseModel):
    page: int = Field(..., description="页码，从 1 开始")
    x_mm: float = Field(
        ..., description="页位（未旋转时）左上角的 x 坐标（mm），以纸张左上角为原点"
    )
    y_mm: float = Field(..., description="页位（未旋转时）左上角的 y 坐标（mm），恒为 0")
    rotation_deg: Literal[0, 180] = Field(
        ..., description="绕页位中心的旋转角度（度）：正面与 long 背面为 0，short 背面为 180"
    )


class PlacementPair(BaseModel):
    left: Optional[PagePlacement] = Field(..., description="左槽页位，空白页为 null")
    right: Optional[PagePlacement] = Field(..., description="右槽页位，空白页为 null")


class PressLayoutSheet(BaseModel):
    sheet_index: int = Field(..., description="帖内纸张序号，从 1 开始（1 为最外张）")
    front: PlacementPair = Field(..., description="正面左右槽页位")
    back: PlacementPair = Field(..., description="背面左右槽页位")


class PressLayoutSignature(BaseModel):
    signature_index: int = Field(..., description="帖号，从 1 开始")
    sheet_count: int = Field(..., description="本帖纸张数")
    page_count_padded: int = Field(..., description="本帖补齐空白后的总页数（4 的倍数）")
    paper_width_mm: float = Field(..., description="纸面宽度（mm）= 2 × 页宽 + 中缝")
    paper_height_mm: float = Field(..., description="纸面高度（mm）= 页高")
    sheets: list[PressLayoutSheet] = Field(..., description="帖内纸张，按从外到内排列")


class PressLayoutResponse(BaseModel):
    total_pages: int
    max_sheets_per_signature: int
    binding: Literal["left", "right"]
    page_width_mm: float
    page_height_mm: float
    gutter_mm: float
    duplex_flip: Literal["long", "short"]
    paper_width_mm: float = Field(..., description="纸面宽度（mm）= 2 × 页宽 + 中缝")
    paper_height_mm: float = Field(..., description="纸面高度（mm）= 页高")
    signature_count: int
    signatures: list[PressLayoutSignature]


# ---------------------------------------------------------------------------
# 瑕疵定位 /api/v1/impose/locate-defects
# ---------------------------------------------------------------------------


class DefectPoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    signature_index: int = Field(..., ge=1, description="帖号，从 1 开始")
    sheet_index: int = Field(
        ..., ge=1, description="帖内张号，从 1 开始（1 为最外张）"
    )
    side: Literal["front", "back"] = Field(
        ..., description="正反面：front=正面，back=背面"
    )
    x_mm: float = Field(
        ..., description="瑕疵点 x 坐标（mm），以纸面左上角为原点、向右为正"
    )
    y_mm: float = Field(
        ..., description="瑕疵点 y 坐标（mm），以纸面左上角为原点、向下为正"
    )

    @field_validator("x_mm", "y_mm")
    @classmethod
    def validate_finite_mm(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("瑕疵点坐标必须为有限数值（单位 mm）")
        return value


class LocateDefectsRequest(PressLayoutRequest):
    """瑕疵定位请求：机台版面全部参数 + 瑕疵点列表，复用同一套校验。"""

    model_config = ConfigDict(extra="forbid")

    defects: list[DefectPoint] = Field(
        ..., min_length=1, description="瑕疵点列表，至少 1 个"
    )

    @model_validator(mode="after")
    def validate_defect_points(self) -> "LocateDefectsRequest":
        # 帖号/张号越界、坐标越出纸面时 locate_defects 抛 ValueError -> 422；
        # 这里仅做校验，响应结果在端点内重新计算
        locate_defects(
            total_pages=self.total_pages,
            max_sheets=self.max_sheets_per_signature,
            binding=self.binding,
            page_width_mm=self.page_width_mm,
            page_height_mm=self.page_height_mm,
            gutter_mm=self.gutter_mm,
            duplex_flip=self.duplex_flip,
            defects=[
                (d.signature_index, d.sheet_index, d.side, d.x_mm, d.y_mm)
                for d in self.defects
            ],
        )
        return self


class DefectLocation(BaseModel):
    defect_index: int = Field(
        ..., description="瑕疵点序号，从 1 开始（按请求 defects 顺序）"
    )
    location: Literal["page", "gutter", "blank"] = Field(
        ..., description="落点类型：page=页内，gutter=中缝，blank=空白页位"
    )
    page: Optional[int] = Field(
        ..., description="原稿页码；gutter/blank 为 null"
    )
    page_x_mm: Optional[float] = Field(
        ..., description="阅读方向页内 x 坐标（mm），从页面左上角起算；gutter/blank 为 null"
    )
    page_y_mm: Optional[float] = Field(
        ..., description="阅读方向页内 y 坐标（mm），从页面左上角起算；gutter/blank 为 null"
    )


class LocateDefectsResponse(BaseModel):
    total_pages: int
    max_sheets_per_signature: int
    binding: Literal["left", "right"]
    page_width_mm: float
    page_height_mm: float
    gutter_mm: float
    duplex_flip: Literal["long", "short"]
    paper_width_mm: float = Field(..., description="纸面宽度（mm）= 2 × 页宽 + 中缝")
    paper_height_mm: float = Field(..., description="纸面高度（mm）= 页高")
    defect_count: int = Field(..., description="瑕疵点总数")
    defects: list[DefectLocation] = Field(
        ..., description="逐点定位结果，按请求 defects 顺序"
    )


# ---------------------------------------------------------------------------
# 墨区着墨面积 /api/v1/impose/ink-zones
# ---------------------------------------------------------------------------


class InkRectangle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    x_mm: float = Field(
        ..., description="矩形左上角 x（mm），以页面左上角为原点、向右为正"
    )
    y_mm: float = Field(
        ..., description="矩形左上角 y（mm），以页面左上角为原点、向下为正"
    )
    width_mm: float = Field(..., description="矩形宽（mm），正数")
    height_mm: float = Field(..., description="矩形高（mm），正数")
    cyan: float = Field(..., ge=0, le=1, description="青通道覆盖率，0～1")
    magenta: float = Field(..., ge=0, le=1, description="品通道覆盖率，0～1")
    yellow: float = Field(..., ge=0, le=1, description="黄通道覆盖率，0～1")
    black: float = Field(..., ge=0, le=1, description="黑通道覆盖率，0～1")

    @field_validator("x_mm", "y_mm", "width_mm", "height_mm")
    @classmethod
    def validate_finite_rect(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("矩形坐标与宽高必须为有限数值（单位 mm）")
        return value

    @field_validator("width_mm", "height_mm")
    @classmethod
    def validate_positive_rect(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("矩形宽、高必须为正数")
        return value


class PageInk(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page: int = Field(..., ge=1, description="页码，从 1 开始；同一页码只能出现一次")
    rectangles: list[InkRectangle] = Field(
        ..., min_length=1, description="该页的页内矩形列表，互不重叠且完整落在页面内"
    )

    @field_validator("page", mode="before")
    @classmethod
    def reject_non_integer_page(cls, value):
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("页码必须为整数（不接受布尔值或小数）")
        return value


class InkZonesRequest(PressLayoutRequest):
    """墨区请求：机台版面全部参数 + 墨区数、印数与各页页内矩形。"""

    model_config = ConfigDict(extra="forbid")

    zone_count: int = Field(
        ..., ge=1, le=16, description="纸面宽度方向等宽墨区数量，1～16 的整数"
    )
    copies: int = Field(..., ge=1, description="印数，正整数")
    page_inks: list[PageInk] = Field(
        ...,
        description=(
            "各页页内矩形及 CMYK 覆盖率；页码有效、同页只出现一次、"
            "矩形互不重叠且完整落在页面内；空白页无需给出"
        ),
    )

    @field_validator("zone_count", "copies", mode="before")
    @classmethod
    def reject_non_integer(cls, value):
        # Pydantic 默认会把 true 强转成 1、2.0 强转成 2；这两项必须是严格整数
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("必须为整数（不接受布尔值或小数）")
        return value

    @model_validator(mode="after")
    def validate_ink_rectangles(self) -> "InkZonesRequest":
        # 页码有效性、同页重复、矩形越界/重叠由 ink_zones 统一校验，
        # 失败抛 ValueError -> 422；响应结果在端点内重新计算
        ink_zones(
            total_pages=self.total_pages,
            max_sheets=self.max_sheets_per_signature,
            binding=self.binding,
            page_width_mm=self.page_width_mm,
            page_height_mm=self.page_height_mm,
            gutter_mm=self.gutter_mm,
            duplex_flip=self.duplex_flip,
            zone_count=self.zone_count,
            copies=self.copies,
            page_inks=[
                (
                    item.page,
                    [
                        (
                            rect.x_mm,
                            rect.y_mm,
                            rect.width_mm,
                            rect.height_mm,
                            rect.cyan,
                            rect.magenta,
                            rect.yellow,
                            rect.black,
                        )
                        for rect in item.rectangles
                    ],
                )
                for item in self.page_inks
            ],
        )
        return self


class InkZoneResult(BaseModel):
    zone_index: int = Field(..., description="墨区序号，从 1 开始（纸面左侧起算）")
    cyan_mm2: float = Field(
        ..., description="青通道等效着墨面积乘印数（mm²）"
    )
    magenta_mm2: float = Field(
        ..., description="品通道等效着墨面积乘印数（mm²）"
    )
    yellow_mm2: float = Field(
        ..., description="黄通道等效着墨面积乘印数（mm²）"
    )
    black_mm2: float = Field(
        ..., description="黑通道等效着墨面积乘印数（mm²）"
    )


class InkZonesSheet(BaseModel):
    sheet_index: int = Field(..., description="帖内纸张序号，从 1 开始（1 为最外张）")
    front: Optional[list[InkZoneResult]] = Field(
        None, description="正面各墨区结果，按墨区序号升序；整面无着墨时缺省"
    )
    back: Optional[list[InkZoneResult]] = Field(
        None, description="背面各墨区结果，按墨区序号升序；整面无着墨时缺省"
    )


class InkZonesSignature(BaseModel):
    signature_index: int = Field(..., description="帖号，从 1 开始")
    sheet_count: int = Field(..., description="本帖纸张数")
    page_count_padded: int = Field(..., description="本帖补齐空白后的总页数（4 的倍数）")
    sheets: list[InkZonesSheet] = Field(..., description="帖内纸张，按从外到内排列")


class InkZonesResponse(BaseModel):
    total_pages: int
    max_sheets_per_signature: int
    binding: Literal["left", "right"]
    page_width_mm: float
    page_height_mm: float
    gutter_mm: float
    duplex_flip: Literal["long", "short"]
    paper_width_mm: float = Field(..., description="纸面宽度（mm）= 2 × 页宽 + 中缝")
    paper_height_mm: float = Field(..., description="纸面高度（mm）= 页高")
    zone_count: int = Field(..., description="等宽墨区数量（1～16）")
    zone_width_mm: float = Field(
        ..., description="单个墨区宽度（mm）= 纸面宽度 / 墨区数量"
    )
    copies: int = Field(..., description="印数（正整数），各通道结果已乘该印数")
    signature_count: int
    signatures: list[InkZonesSignature]


# ---------------------------------------------------------------------------
# 外裁/折缝安全检查 /api/v1/impose/trim-safety
# ---------------------------------------------------------------------------


class ProtectedRectangle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    x_mm: float = Field(
        ..., description="矩形左上角 x（mm），以页面左上角为原点、向右为正"
    )
    y_mm: float = Field(
        ..., description="矩形左上角 y（mm），以页面左上角为原点、向下为正"
    )
    width_mm: float = Field(..., description="矩形宽（mm），正数")
    height_mm: float = Field(..., description="矩形高（mm），正数")

    @field_validator("x_mm", "y_mm", "width_mm", "height_mm")
    @classmethod
    def validate_finite_rect(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("矩形坐标与宽高必须为有限数值（单位 mm）")
        return value

    @field_validator("width_mm", "height_mm")
    @classmethod
    def validate_positive_rect(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("矩形宽、高必须为正数")
        return value


class PageProtected(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page: int = Field(..., ge=1, description="页码，从 1 开始；同一页码只能出现一次")
    rectangles: list[ProtectedRectangle] = Field(
        ..., min_length=1, description="该页阅读方向的受保护内容矩形列表，完整落在页面内（允许贴边）"
    )

    @field_validator("page", mode="before")
    @classmethod
    def reject_non_integer_page(cls, value):
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("页码必须为整数（不接受布尔值或小数）")
        return value


class TrimSafetyRequest(PressLayoutRequest):
    """外裁/折缝安全检查请求：机台版面全部参数 + 安全距离与各页受保护矩形。"""

    model_config = ConfigDict(extra="forbid")

    outer_trim_mm: float = Field(
        ..., description="外裁安全距离（mm），非负有限数值；用于中缝以外的三边"
    )
    fold_safety_mm: float = Field(
        ..., description="折缝安全距离（mm），非负有限数值；用于中缝侧"
    )
    page_protected: list[PageProtected] = Field(
        ...,
        description=(
            "按实际页码给出的各页阅读方向受保护内容矩形；页码有效、同页只出现一次、"
            "矩形完整落在页面内；空白页无需给出；列表可为空（无受保护内容）"
        ),
    )

    @field_validator("outer_trim_mm", "fold_safety_mm")
    @classmethod
    def validate_non_negative_safety_mm(cls, value: float) -> float:
        if not math.isfinite(value) or value < 0:
            raise ValueError("外裁、折缝安全距离必须为非负数（有限数值，单位 mm）")
        return value

    @model_validator(mode="after")
    def validate_trim_safety(self) -> "TrimSafetyRequest":
        # 页码有效性、同页重复、矩形越界由 trim_safety 统一校验，
        # 失败抛 ValueError -> 422；响应结果在端点内重新计算
        trim_safety(
            total_pages=self.total_pages,
            max_sheets=self.max_sheets_per_signature,
            binding=self.binding,
            page_width_mm=self.page_width_mm,
            page_height_mm=self.page_height_mm,
            gutter_mm=self.gutter_mm,
            duplex_flip=self.duplex_flip,
            outer_trim_mm=self.outer_trim_mm,
            fold_safety_mm=self.fold_safety_mm,
            page_protected=[
                (
                    item.page,
                    [
                        (rect.x_mm, rect.y_mm, rect.width_mm, rect.height_mm)
                        for rect in item.rectangles
                    ],
                )
                for item in self.page_protected
            ],
        )
        return self


class PaperRectangle(BaseModel):
    x_mm: float = Field(
        ..., description="纸面矩形左上角 x（mm），以纸面左上角为原点、向右为正"
    )
    y_mm: float = Field(
        ..., description="纸面矩形左上角 y（mm），以纸面左上角为原点、向下为正"
    )
    width_mm: float = Field(..., description="纸面矩形宽（mm）")
    height_mm: float = Field(..., description="纸面矩形高（mm）")


class TrimSafetyViolation(BaseModel):
    signature_index: int = Field(..., description="帖号，从 1 开始")
    sheet_index: int = Field(..., description="帖内张号，从 1 开始（1 为最外张）")
    side: Literal["front", "back"] = Field(
        ..., description="正反面：front=正面，back=背面"
    )
    page: int = Field(..., description="违规矩形所属原稿页码（从 1 开始）")
    edge: Literal["top", "bottom", "outer", "fold"] = Field(
        ...,
        description=(
            "违规边：top=纸面顶边（外裁），bottom=纸面底边（外裁），"
            "outer=纸面外侧竖边（左槽靠左缘、右槽靠右缘，外裁），"
            "fold=中缝折缝侧（折缝安全距离）"
        ),
    )
    rectangle: PaperRectangle = Field(
        ..., description="受保护矩形按页位 0°/180° 映射后的纸面矩形"
    )


class TrimSafetyResponse(BaseModel):
    total_pages: int
    max_sheets_per_signature: int
    binding: Literal["left", "right"]
    page_width_mm: float
    page_height_mm: float
    gutter_mm: float
    duplex_flip: Literal["long", "short"]
    paper_width_mm: float = Field(..., description="纸面宽度（mm）= 2 × 页宽 + 中缝")
    paper_height_mm: float = Field(..., description="纸面高度（mm）= 页高")
    outer_trim_mm: float = Field(..., description="外裁安全距离（mm）")
    fold_safety_mm: float = Field(..., description="折缝安全距离（mm）")
    violation_count: int = Field(..., description="越线违规总数")
    violations: list[TrimSafetyViolation] = Field(
        ...,
        description=(
            "逐处越线明细，按帖号、张号、正反面、左右槽与请求矩形顺序排列；"
            "同一矩形越过多条安全线时逐边各记一条（top、bottom、outer、fold）"
        ),
    )


# ---------------------------------------------------------------------------
# 双面拼版校样 PDF /api/v1/impose/proof.pdf
# ---------------------------------------------------------------------------


class ProofRequest(PressLayoutRequest):
    """校样 PDF 请求：参数与机台版面完全一致，复用同一套校验。"""

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def validate_sheet_count(self) -> "ProofRequest":
        # 印张总数由总页数决定（每张 4 页，含末帖补白），与每帖张数无关
        validate_sheet_limit(self.total_pages)
        return self


class ChapterImpositionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total_pages: int = Field(
        ..., ge=1, description="总页数，正整数（1, 2, 3, ...）"
    )
    max_sheets_per_signature: int = Field(
        ..., ge=1, description="每帖最多纸张数，正整数；每帖最多容纳其 4 倍页数"
    )
    binding: Literal["left", "right"] = Field(
        ..., description="装订方向：left=左装订，right=右装订"
    )
    chapter_starts: list[int] = Field(
        ..., min_length=1, description="各章节首页页码，严格递增且首项为 1"
    )

    @model_validator(mode="after")
    def validate_chapter_starts(self) -> "ChapterImpositionRequest":
        starts = self.chapter_starts
        if starts[0] != 1:
            raise ValueError("chapter_starts 首项必须为 1")
        if any(curr <= prev for prev, curr in zip(starts, starts[1:])):
            raise ValueError("chapter_starts 必须严格递增")
        if starts[-1] > self.total_pages:
            raise ValueError("chapter_starts 不能超过 total_pages")
        capacity = self.max_sheets_per_signature * 4
        ends = starts[1:] + [self.total_pages + 1]
        for start, end in zip(starts, ends):
            if end - start > capacity:
                raise ValueError(
                    f"起始页为 {start} 的章节共 {end - start} 页，"
                    f"超过单帖容量 {capacity} 页（4 × max_sheets_per_signature）"
                )
        return self


class ChapterSignature(BaseModel):
    signature_index: int = Field(..., description="帖号，从 1 开始")
    sheet_count: int = Field(..., description="本帖纸张数")
    page_count_padded: int = Field(..., description="本帖补齐空白后的总页数（4 的倍数）")
    page_start: int = Field(..., description="本帖原页起始页码")
    page_end: int = Field(..., description="本帖原页结束页码")
    blank_count: int = Field(..., description="本帖尾部补齐的空白页数")
    sheets: list[Sheet] = Field(..., description="帖内纸张，按从外到内排列")


class ChapterImpositionResponse(BaseModel):
    total_pages: int
    max_sheets_per_signature: int
    binding: Literal["left", "right"]
    chapter_starts: list[int]
    signature_count: int
    signatures: list[ChapterSignature]


class ReprintRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    old_page_ids: list[str] = Field(
        ..., min_length=1, description="旧版页面 ID，按阅读顺序排列，非空字符串且不重复"
    )
    new_page_ids: list[str] = Field(
        ..., min_length=1, description="新版页面 ID，按阅读顺序排列，非空字符串且不重复"
    )
    max_sheets_per_signature: int = Field(
        ..., ge=1, description="两版共用的每帖最多纸张数，正整数；每帖最多容纳其 4 倍页数"
    )
    binding: Literal["left", "right"] = Field(
        ..., description="两版共用的装订方向：left=左装订，right=右装订"
    )
    changed_page_ids: list[str] = Field(
        ..., description="新版内容改动的页面 ID，可重复、可空；每项必须属于新版"
    )

    @model_validator(mode="after")
    def validate_page_ids(self) -> "ReprintRequest":
        for field_name in ("old_page_ids", "new_page_ids"):
            page_ids = getattr(self, field_name)
            if any(not page_id or not page_id.strip() for page_id in page_ids):
                raise ValueError(f"{field_name} 中不能包含空字符串页面 ID")
            if len(page_ids) != len(set(page_ids)):
                raise ValueError(f"{field_name} 中的页面 ID 不能重复")
        if any(not page_id or not page_id.strip() for page_id in self.changed_page_ids):
            raise ValueError("changed_page_ids 中不能包含空字符串页面 ID")
        new_set = set(self.new_page_ids)
        unknown = [page_id for page_id in self.changed_page_ids if page_id not in new_set]
        if unknown:
            raise ValueError(
                f"changed_page_ids 中的页面 ID 必须属于新版：{unknown}"
            )
        return self


class IdPagePair(BaseModel):
    left: Optional[str] = Field(..., description="左页页面 ID，空白页为 null")
    right: Optional[str] = Field(..., description="右页页面 ID，空白页为 null")


class ReprintSheet(BaseModel):
    sheet_index: int = Field(..., description="新版帖内纸张序号，从 1 开始（1 为最外张）")
    front: IdPagePair = Field(..., description="正面左右页面 ID")
    back: IdPagePair = Field(..., description="背面左右页面 ID")
    reused: bool = Field(
        ..., description="是否复用旧版印张；false 表示整张重印"
    )
    old_signature_index: Optional[int] = Field(
        ..., description="复用的旧帖号（从 1 开始）；整张重印时为 null"
    )
    old_sheet_index: Optional[int] = Field(
        ..., description="复用的旧帖内张号（从 1 开始，1 为最外张）；整张重印时为 null"
    )


class ReprintSignature(BaseModel):
    signature_index: int = Field(..., description="新版帖号，从 1 开始")
    sheet_count: int = Field(..., description="本帖纸张数")
    page_count_padded: int = Field(..., description="本帖补齐空白后的总页数（4 的倍数）")
    sheets: list[ReprintSheet] = Field(..., description="帖内纸张，按从外到内排列")


class ReprintResponse(BaseModel):
    old_page_ids: list[str]
    new_page_ids: list[str]
    changed_page_ids: list[str]
    max_sheets_per_signature: int
    binding: Literal["left", "right"]
    signature_count: int = Field(..., description="新版帖数")
    reprint_sheet_count: int = Field(..., description="整张重印的总张数")
    signatures: list[ReprintSignature] = Field(..., description="新版逐帖的复用/重印计划")


# ---------------------------------------------------------------------------
# 印张抽检 /api/v1/impose/inspect
# ---------------------------------------------------------------------------

# 页位取值：页面 ID（非空字符串，不能为 "?"）、null（空白）或 "?"（未读出），
# 由 InspectPagePair 的 left/right（Optional[str]）承载。


class InspectPagePair(BaseModel):
    model_config = ConfigDict(extra="forbid")

    left: Optional[str] = Field(..., description='左页页面 ID；null=空白，"?"=未读出')
    right: Optional[str] = Field(..., description='右页页面 ID；null=空白，"?"=未读出')

    @field_validator("left", "right")
    @classmethod
    def validate_slot(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and not value.strip():
            raise ValueError('页位不能是空字符串；未读出请用 "?"，空白页请用 null')
        return value


class ObservedSheet(BaseModel):
    model_config = ConfigDict(extra="forbid")

    front: InspectPagePair = Field(..., description="实物印张正面（拍摄/读数时的朝向）")
    back: InspectPagePair = Field(..., description="实物印张背面（拍摄/读数时的朝向）")


class InspectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page_ids: list[str] = Field(
        ..., min_length=1, description="页面 ID，按阅读顺序排列，非空字符串、互不重复且不能为 \"?\""
    )
    max_sheets_per_signature: int = Field(
        ..., ge=1, description="每帖最多纸张数，正整数；每帖最多容纳其 4 倍页数"
    )
    binding: Literal["left", "right"] = Field(
        ..., description="装订方向：left=左装订，right=右装订"
    )
    observed_sheets: list[ObservedSheet] = Field(
        ..., min_length=1, description="乱序的实物印张；每个页位为页面 ID、null（空白）或 \"?\"（未读出）"
    )

    @model_validator(mode="after")
    def validate_page_ids(self) -> "InspectRequest":
        if any(not page_id or not page_id.strip() for page_id in self.page_ids):
            raise ValueError("page_ids 中不能包含空字符串页面 ID")
        if any(page_id == "?" for page_id in self.page_ids):
            raise ValueError('页面 ID 不能为 "?"')
        if len(self.page_ids) != len(set(self.page_ids)):
            raise ValueError("page_ids 不能重复")
        return self


class SlotError(BaseModel):
    position: Literal["front_left", "front_right", "back_left", "back_right"] = Field(
        ..., description="与预期不符的页位（按观测原样的朝向）"
    )
    observed: Optional[str] = Field(..., description="该页位的实测值：页面 ID 或 null（空白）")
    expected: Optional[str] = Field(..., description="该页位按选定变换解释后的预期页面 ID 或 null")


class InspectedObservation(BaseModel):
    observation_index: int = Field(..., description="观测序号，从 1 开始（按请求 observed_sheets 顺序）")
    front: InspectPagePair = Field(..., description="观测原样的正面左右页位（可能含 \"?\"）")
    back: InspectPagePair = Field(..., description="观测原样的背面左右页位（可能含 \"?\"）")
    matched: bool = Field(..., description="是否与某张预期印张成功配对")
    signature_index: Optional[int] = Field(..., description="配对预期印张的帖号（从 1 开始）；无法配对时为 null")
    sheet_index: Optional[int] = Field(..., description="配对预期印张的帖内张号（从 1 开始，1 为最外张）；无法配对时为 null")
    transform: Optional[
        Literal["none", "mirror_lr", "flip_fb", "mirror_lr_flip_fb"]
    ] = Field(
        ...,
        description=(
            "观测相对预期的变换：none=原样，mirror_lr=左右镜像，"
            "flip_fb=正反互换，mirror_lr_flip_fb=两者组合；无法配对时为 null"
        ),
    )
    matched_slot_count: int = Field(..., description="已读页位与预期吻合的数量（\"?\" 不计入；null 对 null 算吻合）")
    errors: list[SlotError] = Field(..., description="已知页位错误明细（\"?\" 不计错），按页位顺序排列")


class UnmatchedObservation(BaseModel):
    observation_index: int = Field(..., description="无法配对的观测序号，从 1 开始")
    front: InspectPagePair = Field(..., description="观测原样的正面左右页位（可能含 \"?\"）")
    back: InspectPagePair = Field(..., description="观测原样的背面左右页位（可能含 \"?\"）")


class UnseenSheet(BaseModel):
    signature_index: int = Field(..., description="未见预期印张的帖号，从 1 开始")
    sheet_index: int = Field(..., description="未见预期印张的帖内张号，从 1 开始（1 为最外张）")
    front: IdPagePair = Field(..., description="正面左右页面 ID，空白页为 null")
    back: IdPagePair = Field(..., description="背面左右页面 ID，空白页为 null")


class InspectResponse(BaseModel):
    page_ids: list[str]
    max_sheets_per_signature: int
    binding: Literal["left", "right"]
    matched_observation_count: int = Field(..., description="成功配对的观测数")
    unmatched_observation_count: int = Field(..., description="无法配对的观测数")
    unseen_sheet_count: int = Field(..., description="未见的预期印张数")
    observations: list[InspectedObservation] = Field(..., description="每张观测（按请求顺序）的配对与核对结果")
    unmatched_observations: list[UnmatchedObservation] = Field(..., description="无法配对的观测明细，按观测序号排列")
    unseen_signatures: list[UnseenSheet] = Field(..., description="未见的预期印张，按帖号/张号排列")


# ---------------------------------------------------------------------------
# 订针计划 /api/v1/impose/staple-plan
# ---------------------------------------------------------------------------


class StapleForbiddenInterval(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start_mm: float = Field(
        ..., description="禁针闭区间起点（mm），以页顶为原点、向下为正"
    )
    end_mm: float = Field(
        ..., description="禁针闭区间终点（mm），以页顶为原点、向下为正"
    )

    @field_validator("start_mm", "end_mm")
    @classmethod
    def validate_finite_mm(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("禁针区间端点必须为有限数值（单位 mm）")
        return value


class SignatureForbiddenZones(BaseModel):
    model_config = ConfigDict(extra="forbid")

    signature_index: int = Field(
        ..., ge=1, description="帖号，从 1 开始；每帖至多出现一次"
    )
    intervals: list[StapleForbiddenInterval] = Field(
        ...,
        min_length=1,
        description="该帖的禁针闭区间列表（区间端点为 mm，闭区间端点上的整数刻度同样禁针）",
    )


class StaplePlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total_pages: int = Field(
        ..., ge=1, description="总页数，正整数（1, 2, 3, ...）"
    )
    max_sheets_per_signature: int = Field(
        ..., ge=1, description="每帖最多纸张数，正整数；每帖最多容纳其 4 倍页数"
    )
    binding: Literal["left", "right"] = Field(
        ..., description="装订方向：left=左装订，right=右装订"
    )
    page_height_mm: float = Field(
        ..., ge=50, le=1000, description="页高（mm），50～1000 的有限数值"
    )
    staple_count: int = Field(
        ..., ge=2, le=4, description="每帖订针数，2～4 的整数"
    )
    top_margin_mm: float = Field(
        ..., description="上留边（mm），非负有限数值；上留边 + 下留边须小于页高"
    )
    bottom_margin_mm: float = Field(
        ..., description="下留边（mm），非负有限数值；上留边 + 下留边须小于页高"
    )
    min_spacing_mm: float = Field(
        ..., description="相邻订针最小针距（mm），非负有限数值"
    )
    forbidden_zones: list[SignatureForbiddenZones] = Field(
        default_factory=list,
        description="按帖号给出的禁针闭区间；可空（省略），无禁针要求的帖无需给出",
    )

    @field_validator("staple_count", mode="before")
    @classmethod
    def reject_non_integer_staple_count(cls, value):
        # Pydantic 默认会把 true 强转成 1、2.0 强转成 2；订针数必须是严格整数
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("订针数必须为整数（不接受布尔值或小数）")
        return value

    @field_validator(
        "page_height_mm",
        "top_margin_mm",
        "bottom_margin_mm",
        "min_spacing_mm",
    )
    @classmethod
    def validate_finite_dimension(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("尺寸参数必须为有限数值（单位 mm）")
        return value

    @field_validator("top_margin_mm", "bottom_margin_mm", "min_spacing_mm")
    @classmethod
    def validate_non_negative_mm(cls, value: float) -> float:
        if value < 0:
            raise ValueError("留边与最小针距必须为非负数（单位 mm）")
        return value

    @model_validator(mode="after")
    def validate_staple_plan(self) -> "StaplePlanRequest":
        # 帖号越界/重复、禁针区间端点非法（负值、起点 > 终点、超出页高等）、
        # 留边之和不小于页高，以及某帖无可行排列，均由 staple_plan 统一校验，
        # 失败抛 ValueError -> 422；响应结果在端点内重新计算
        staple_plan(
            total_pages=self.total_pages,
            max_sheets=self.max_sheets_per_signature,
            binding=self.binding,
            page_height_mm=self.page_height_mm,
            staple_count=self.staple_count,
            top_margin_mm=self.top_margin_mm,
            bottom_margin_mm=self.bottom_margin_mm,
            min_spacing_mm=self.min_spacing_mm,
            forbidden_by_signature=[
                (
                    item.signature_index,
                    [(interval.start_mm, interval.end_mm) for interval in item.intervals],
                )
                for item in self.forbidden_zones
            ],
        )
        return self


class StaplePlanSignature(BaseModel):
    signature_index: int = Field(..., description="帖号，从 1 开始")
    sheet_count: int = Field(..., description="本帖纸张数（沿用 impose 分帖结果）")
    page_count_padded: int = Field(..., description="本帖补齐空白后的总页数（4 的倍数）")
    staple_positions_mm: list[int] = Field(
        ...,
        description=(
            "自页顶起算的订针针位（mm，整数毫米刻度），自上而下严格递增；"
            "避开留边与该帖禁针闭区间，相邻针距不小于最小针距"
        ),
    )
    max_deviation_mm: float = Field(
        ...,
        description=(
            "本帖各针相对理想针位的最大绝对偏差（mm）；"
            "理想针位 i = 上留边 + i × (页高 − 上留边 − 下留边) / (订针数 + 1)"
        ),
    )


class StaplePlanResponse(BaseModel):
    total_pages: int
    max_sheets_per_signature: int
    binding: Literal["left", "right"]
    page_height_mm: float
    staple_count: int = Field(..., description="每帖订针数（2～4）")
    top_margin_mm: float
    bottom_margin_mm: float
    min_spacing_mm: float
    signature_count: int
    signatures: list[StaplePlanSignature]


# ---------------------------------------------------------------------------
# 原纸备料 /api/v1/impose/stock-plan
# ---------------------------------------------------------------------------


class StockPaperSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    width_mm: int = Field(..., ge=1, description="原纸宽度（mm），正整数")
    height_mm: int = Field(..., ge=1, description="原纸高度（mm），正整数")
    inventory: int = Field(..., ge=0, le=30, description="库存张数，0～30 的整数")
    grain: Literal["width", "height"] = Field(
        ..., description="纸纹方向：width=纸纹沿原纸宽度，height=纸纹沿原纸高度"
    )

    @field_validator("width_mm", "height_mm", "inventory", mode="before")
    @classmethod
    def reject_non_integer(cls, value):
        # 宽高与库存必须是严格整数（不接受布尔值或小数）
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("必须为整数（不接受布尔值或小数）")
        return value


class StockPlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total_pages: int = Field(
        ..., ge=1, description="总页数，正整数（沿用普通拼版的分帖参数）"
    )
    max_sheets_per_signature: int = Field(
        ..., ge=1, description="每帖最多纸张数，正整数；每帖最多容纳其 4 倍页数"
    )
    binding: Literal["left", "right"] = Field(
        ..., description="装订方向：left=左装订，right=右装订"
    )
    page_width_mm: float = Field(..., description="单页宽度（mm），正数")
    page_height_mm: float = Field(..., description="单页高度（mm），正数；书脊沿页高")
    gutter_mm: float = Field(..., description="中缝宽度（mm），非负数")
    copies: int = Field(..., ge=1, description="印数，正整数")
    papers: list[StockPaperSpec] = Field(
        ...,
        min_length=1,
        max_length=6,
        description="原纸规格列表，1～6 种；按输入顺序作为用量字典序与结果顺序",
    )
    margin_mm: float = Field(
        ..., description="原纸四周统一留边（mm），非负有限数值"
    )
    spacing_mm: float = Field(
        ..., description="相邻成品印张之间的统一裁切间隔（mm），非负有限数值"
    )

    @field_validator("copies", mode="before")
    @classmethod
    def reject_non_integer_copies(cls, value):
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("印数必须为整数（不接受布尔值或小数）")
        return value

    @field_validator("page_width_mm", "page_height_mm")
    @classmethod
    def validate_positive_mm(cls, value: float) -> float:
        if not math.isfinite(value) or value <= 0:
            raise ValueError("页宽、页高必须为正数（有限数值，单位 mm）")
        return value

    @field_validator("gutter_mm", "margin_mm", "spacing_mm")
    @classmethod
    def validate_non_negative_mm(cls, value: float) -> float:
        if not math.isfinite(value) or value < 0:
            raise ValueError("中缝、留边与裁切间隔必须为非负数（有限数值，单位 mm）")
        return value

    @model_validator(mode="after")
    def validate_stock_plan(self) -> "StockPlanRequest":
        # 每册印张数、成品尺寸、单张出数与库存可行性均由 plan_stock 统一校验，
        # 失败抛 ValueError -> 422；响应结果在端点内重新计算
        plan_stock(
            total_pages=self.total_pages,
            max_sheets=self.max_sheets_per_signature,
            binding=self.binding,
            page_width_mm=self.page_width_mm,
            page_height_mm=self.page_height_mm,
            gutter_mm=self.gutter_mm,
            copies=self.copies,
            papers=[
                (p.width_mm, p.height_mm, p.inventory, p.grain)
                for p in self.papers
            ],
            margin_mm=self.margin_mm,
            spacing_mm=self.spacing_mm,
        )
        return self


class StockPaperResult(BaseModel):
    paper_index: int = Field(..., description="原纸规格序号，从 1 开始（按请求顺序）")
    width_mm: int = Field(..., description="原纸宽度（mm）")
    height_mm: int = Field(..., description="原纸高度（mm）")
    grain: Literal["width", "height"] = Field(
        ..., description="纸纹方向：width=沿宽，height=沿高"
    )
    inventory: int = Field(..., description="库存张数（0～30）")
    pieces_per_sheet: int = Field(
        ..., description="该规格单张原纸的成品印张出数（整行 × 整列）"
    )
    columns: int = Field(..., description="单张沿原纸宽度方向排布的成品列数")
    rows: int = Field(..., description="单张沿原纸高度方向排布的成品行数")
    usable_width_mm: float = Field(
        ..., description="扣除四周留边后的可用宽度（mm）= 原纸宽 − 2 × 留边"
    )
    usable_height_mm: float = Field(
        ..., description="扣除四周留边后的可用高度（mm）= 原纸高 − 2 × 留边"
    )
    used: int = Field(..., description="选中的用量（张），不超过库存")
    production: int = Field(..., description="该规格总产量 = 用量 × 单张出数")
    area_mm2: int = Field(..., description="该规格耗用总面积（mm²）= 用量 × 单张面积")


class StockPlanResponse(BaseModel):
    total_pages: int
    max_sheets_per_signature: int
    binding: Literal["left", "right"]
    page_width_mm: float
    page_height_mm: float
    gutter_mm: float
    copies: int = Field(..., description="印数（正整数）")
    margin_mm: float = Field(..., description="四周留边（mm）")
    spacing_mm: float = Field(..., description="裁切间隔（mm）")
    signature_count: int = Field(..., description="沿用拼版结果的帖数")
    sheets_per_copy: int = Field(
        ..., description="每册印张数（沿用拼版分帖结果，含末帖补白张）"
    )
    total_demand: int = Field(
        ..., description="总需求 = 每册印张数 × 印数"
    )
    sheet_width_mm: float = Field(
        ..., description="成品印张宽度（mm）= 2 × 页宽 + 中缝"
    )
    sheet_height_mm: float = Field(..., description="成品印张高度（mm）= 页高")
    papers: list[StockPaperResult] = Field(
        ..., description="各规格原纸的单张出数、排布与用量结果，按请求顺序"
    )
    total_production: int = Field(..., description="选中组合的成品印张总产量")
    surplus: int = Field(
        ..., description="余量（超产）= 总产量 − 总需求，非负整数"
    )
    total_area_mm2: int = Field(
        ..., description="选中组合耗用的原纸总面积（mm²），为可行组合中的最小值"
    )


# ---------------------------------------------------------------------------
# 骑马订爬移补偿 /api/v1/impose/creep-plan
# ---------------------------------------------------------------------------


class CreepPlanRequest(PressLayoutRequest):
    """爬移补偿请求：机台版面全部参数 + 单张纸厚度，复用同一套校验。"""

    model_config = ConfigDict(extra="forbid")

    thickness_mm: float = Field(
        ..., description="单张纸厚度（mm），正数（有限值）"
    )

    @field_validator("thickness_mm")
    @classmethod
    def validate_thickness_mm(cls, value: float) -> float:
        if not math.isfinite(value) or value <= 0:
            raise ValueError("单张纸厚度必须为正数（有限数值，单位 mm）")
        return value

    @model_validator(mode="after")
    def validate_creep_plan(self) -> "CreepPlanRequest":
        # 爬移量达到单页宽度时 creep_plan 抛 ValueError -> 422；
        # 这里仅做校验，响应结果在端点内重新计算
        creep_plan(
            total_pages=self.total_pages,
            max_sheets=self.max_sheets_per_signature,
            binding=self.binding,
            page_width_mm=self.page_width_mm,
            page_height_mm=self.page_height_mm,
            gutter_mm=self.gutter_mm,
            duplex_flip=self.duplex_flip,
            thickness_mm=self.thickness_mm,
        )
        return self


class CreepSlot(BaseModel):
    page: Optional[int] = Field(
        ..., description="页码，从 1 开始；空白页位（末帖补白）为 null"
    )
    paper_shift_x_mm: float = Field(
        ...,
        description=(
            "纸面水平位移（mm）：正=向纸面右侧、负=向纸面左侧；"
            "左槽为正、右槽为负，均指向纸面折缝中心"
        ),
    )
    artwork_shift_x_mm: float = Field(
        ...,
        description=(
            "阅读方向稿件水平位移（mm）：按页位 0°/180° 旋转换算，"
            "0° 与纸面位移相同、180° 取反"
        ),
    )


class CreepPair(BaseModel):
    left: CreepSlot = Field(..., description="左槽页位")
    right: CreepSlot = Field(..., description="右槽页位")


class CreepSheet(BaseModel):
    sheet_index: int = Field(..., description="帖内纸张序号，从 1 开始（1 为最外张）")
    creep_mm: float = Field(
        ..., description="本张爬移量（mm）= 2 × (张号 − 1) × 单张纸厚度；最外张为 0"
    )
    front: CreepPair = Field(..., description="正面左右槽页位")
    back: CreepPair = Field(..., description="背面左右槽页位")


class CreepSignature(BaseModel):
    signature_index: int = Field(..., description="帖号，从 1 开始")
    sheet_count: int = Field(..., description="本帖纸张数")
    page_count_padded: int = Field(..., description="本帖补齐空白后的总页数（4 的倍数）")
    sheets: list[CreepSheet] = Field(..., description="帖内纸张，按从外到内排列")


class CreepPlanResponse(BaseModel):
    total_pages: int
    max_sheets_per_signature: int
    binding: Literal["left", "right"]
    page_width_mm: float
    page_height_mm: float
    gutter_mm: float
    duplex_flip: Literal["long", "short"]
    thickness_mm: float
    paper_width_mm: float = Field(..., description="纸面宽度（mm）= 2 × 页宽 + 中缝")
    paper_height_mm: float = Field(..., description="纸面高度（mm）= 页高")
    signature_count: int
    signatures: list[CreepSignature]


@app.get("/health", tags=["健康检查"])
def health() -> dict:
    return {"status": "ok"}


@app.post(
    "/api/v1/impose",
    response_model=ImpositionResponse,
    tags=["拼版"],
    summary="小册子拼版",
)
def create_imposition(request: ImpositionRequest) -> ImpositionResponse:
    signatures = impose(
        total_pages=request.total_pages,
        max_sheets=request.max_sheets_per_signature,
        binding=request.binding,
    )
    return ImpositionResponse(
        total_pages=request.total_pages,
        max_sheets_per_signature=request.max_sheets_per_signature,
        binding=request.binding,
        signature_count=len(signatures),
        signatures=signatures,
    )


@app.post(
    "/api/v1/impose/press-layout",
    response_model=PressLayoutResponse,
    tags=["拼版"],
    summary="机台版面：纸面尺寸与各页位坐标、旋转角",
)
def create_press_layout(request: PressLayoutRequest) -> PressLayoutResponse:
    layout = press_layout(
        total_pages=request.total_pages,
        max_sheets=request.max_sheets_per_signature,
        binding=request.binding,
        page_width_mm=request.page_width_mm,
        page_height_mm=request.page_height_mm,
        gutter_mm=request.gutter_mm,
        duplex_flip=request.duplex_flip,
    )
    return PressLayoutResponse(**layout)


@app.post(
    "/api/v1/impose/locate-defects",
    response_model=LocateDefectsResponse,
    tags=["拼版"],
    summary="瑕疵定位：纸面坐标反查原稿页码与页内坐标",
)
def create_locate_defects(request: LocateDefectsRequest) -> LocateDefectsResponse:
    result = locate_defects(
        total_pages=request.total_pages,
        max_sheets=request.max_sheets_per_signature,
        binding=request.binding,
        page_width_mm=request.page_width_mm,
        page_height_mm=request.page_height_mm,
        gutter_mm=request.gutter_mm,
        duplex_flip=request.duplex_flip,
        defects=[
            (d.signature_index, d.sheet_index, d.side, d.x_mm, d.y_mm)
            for d in request.defects
        ],
    )
    return LocateDefectsResponse(**result)


@app.post(
    "/api/v1/impose/ink-zones",
    response_model=InkZonesResponse,
    response_model_exclude_none=True,
    tags=["拼版"],
    summary="墨区着墨面积：页内矩形按页位映射后跨等宽墨区拆分",
)
def create_ink_zones(request: InkZonesRequest) -> InkZonesResponse:
    result = ink_zones(
        total_pages=request.total_pages,
        max_sheets=request.max_sheets_per_signature,
        binding=request.binding,
        page_width_mm=request.page_width_mm,
        page_height_mm=request.page_height_mm,
        gutter_mm=request.gutter_mm,
        duplex_flip=request.duplex_flip,
        zone_count=request.zone_count,
        copies=request.copies,
        page_inks=[
            (
                item.page,
                [
                    (
                        rect.x_mm,
                        rect.y_mm,
                        rect.width_mm,
                        rect.height_mm,
                        rect.cyan,
                        rect.magenta,
                        rect.yellow,
                        rect.black,
                    )
                    for rect in item.rectangles
                ],
            )
            for item in request.page_inks
        ],
    )
    return InkZonesResponse(**result)


@app.post(
    "/api/v1/impose/trim-safety",
    response_model=TrimSafetyResponse,
    tags=["拼版"],
    summary="外裁/折缝安全检查：受保护内容映射纸面后核对安全距离",
    responses={
        422: {"description": "参数非法，或受保护矩形越出页面（错误信息指出页码与矩形）"},
    },
)
def create_trim_safety(request: TrimSafetyRequest) -> TrimSafetyResponse:
    result = trim_safety(
        total_pages=request.total_pages,
        max_sheets=request.max_sheets_per_signature,
        binding=request.binding,
        page_width_mm=request.page_width_mm,
        page_height_mm=request.page_height_mm,
        gutter_mm=request.gutter_mm,
        duplex_flip=request.duplex_flip,
        outer_trim_mm=request.outer_trim_mm,
        fold_safety_mm=request.fold_safety_mm,
        page_protected=[
            (
                item.page,
                [
                    (rect.x_mm, rect.y_mm, rect.width_mm, rect.height_mm)
                    for rect in item.rectangles
                ],
            )
            for item in request.page_protected
        ],
    )
    return TrimSafetyResponse(**result)


@app.post(
    "/api/v1/impose/proof.pdf",
    response_class=Response,
    tags=["拼版"],
    summary="双面拼版校样：下载 proof.pdf",
    responses={
        200: {"content": {"application/pdf": {}}, "description": "可下载的双面拼版校样 PDF"},
        422: {"description": "参数非法或印张数超过 100 张"},
    },
)
def create_proof_pdf(request: ProofRequest) -> Response:
    layout = press_layout(
        total_pages=request.total_pages,
        max_sheets=request.max_sheets_per_signature,
        binding=request.binding,
        page_width_mm=request.page_width_mm,
        page_height_mm=request.page_height_mm,
        gutter_mm=request.gutter_mm,
        duplex_flip=request.duplex_flip,
    )
    pdf_bytes = render_proof_pdf(layout)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="proof.pdf"'},
    )


@app.post(
    "/api/v1/impose/chapters",
    response_model=ChapterImpositionResponse,
    tags=["拼版"],
    summary="按章节分帖的小册子拼版",
)
def create_chapter_imposition(
    request: ChapterImpositionRequest,
) -> ChapterImpositionResponse:
    signatures = impose_chapters(
        total_pages=request.total_pages,
        max_sheets=request.max_sheets_per_signature,
        binding=request.binding,
        chapter_starts=request.chapter_starts,
    )
    return ChapterImpositionResponse(
        total_pages=request.total_pages,
        max_sheets_per_signature=request.max_sheets_per_signature,
        binding=request.binding,
        chapter_starts=request.chapter_starts,
        signature_count=len(signatures),
        signatures=signatures,
    )


@app.post(
    "/api/v1/impose/reprint",
    response_model=ReprintResponse,
    tags=["重印"],
    summary="旧版/新版重印复用计算",
)
def create_reprint_plan(request: ReprintRequest) -> ReprintResponse:
    plan = plan_reprint(
        old_page_ids=request.old_page_ids,
        new_page_ids=request.new_page_ids,
        max_sheets=request.max_sheets_per_signature,
        binding=request.binding,
        changed_page_ids=request.changed_page_ids,
    )
    return ReprintResponse(
        old_page_ids=request.old_page_ids,
        new_page_ids=request.new_page_ids,
        changed_page_ids=request.changed_page_ids,
        max_sheets_per_signature=request.max_sheets_per_signature,
        binding=request.binding,
        signature_count=plan["signature_count"],
        reprint_sheet_count=plan["reprint_sheet_count"],
        signatures=plan["signatures"],
    )


@app.post(
    "/api/v1/impose/inspect",
    response_model=InspectResponse,
    tags=["抽检"],
    summary="印张抽检：实物印张与预期拼版配对核对",
)
def inspect_sheets(request: InspectRequest) -> InspectResponse:
    observed = [
        (
            sheet.front.left if sheet.front.left != "?" else UNREAD,
            sheet.front.right if sheet.front.right != "?" else UNREAD,
            sheet.back.left if sheet.back.left != "?" else UNREAD,
            sheet.back.right if sheet.back.right != "?" else UNREAD,
        )
        for sheet in request.observed_sheets
    ]
    result = inspect_observed_sheets(
        page_ids=request.page_ids,
        max_sheets=request.max_sheets_per_signature,
        binding=request.binding,
        observed_sheets=observed,
    )

    def render_slot(value):
        return "?" if value is UNREAD else value

    def render_pair(pair: dict) -> dict:
        return {"left": render_slot(pair["left"]), "right": render_slot(pair["right"])}

    observations = []
    for item in result["observations"]:
        observations.append(
            {
                "observation_index": item["observation_index"],
                "front": render_pair(item["front"]),
                "back": render_pair(item["back"]),
                "matched": item["matched"],
                "signature_index": item["signature_index"],
                "sheet_index": item["sheet_index"],
                "transform": item["transform"],
                "matched_slot_count": item["matched_slot_count"],
                "errors": [
                    {
                        "position": error["position"],
                        "observed": render_slot(error["observed"]),
                        "expected": render_slot(error["expected"]),
                    }
                    for error in item["errors"]
                ],
            }
        )

    unmatched = [
        {
            "observation_index": item["observation_index"],
            "front": render_pair(item["front"]),
            "back": render_pair(item["back"]),
        }
        for item in result["unmatched_observations"]
    ]

    return InspectResponse(
        page_ids=request.page_ids,
        max_sheets_per_signature=request.max_sheets_per_signature,
        binding=request.binding,
        matched_observation_count=result["matched_observation_count"],
        unmatched_observation_count=result["unmatched_observation_count"],
        unseen_sheet_count=result["unseen_sheet_count"],
        observations=observations,
        unmatched_observations=unmatched,
        unseen_signatures=result["unseen_signatures"],
    )


@app.post(
    "/api/v1/impose/staple-plan",
    response_model=StaplePlanResponse,
    tags=["拼版"],
    summary="订针计划：逐帖在整数毫米刻度上规划最优递增订针针位",
    responses={
        422: {"description": "参数非法，或某帖无可行订针排列（错误信息指出帖号）"},
    },
)
def create_staple_plan(request: StaplePlanRequest) -> StaplePlanResponse:
    result = staple_plan(
        total_pages=request.total_pages,
        max_sheets=request.max_sheets_per_signature,
        binding=request.binding,
        page_height_mm=request.page_height_mm,
        staple_count=request.staple_count,
        top_margin_mm=request.top_margin_mm,
        bottom_margin_mm=request.bottom_margin_mm,
        min_spacing_mm=request.min_spacing_mm,
        forbidden_by_signature=[
            (
                item.signature_index,
                [(interval.start_mm, interval.end_mm) for interval in item.intervals],
            )
            for item in request.forbidden_zones
        ],
    )
    return StaplePlanResponse(**result)


@app.post(
    "/api/v1/impose/stock-plan",
    response_model=StockPlanResponse,
    tags=["备料"],
    summary="原纸备料：单张出数与库存内总面积最小的原纸组合优选",
    responses={
        422: {"description": "参数非法，或库存原纸无法满足总需求（错误信息给出产能与需求）"},
    },
)
def create_stock_plan(request: StockPlanRequest) -> StockPlanResponse:
    result = plan_stock(
        total_pages=request.total_pages,
        max_sheets=request.max_sheets_per_signature,
        binding=request.binding,
        page_width_mm=request.page_width_mm,
        page_height_mm=request.page_height_mm,
        gutter_mm=request.gutter_mm,
        copies=request.copies,
        papers=[
            (p.width_mm, p.height_mm, p.inventory, p.grain)
            for p in request.papers
        ],
        margin_mm=request.margin_mm,
        spacing_mm=request.spacing_mm,
    )
    return StockPlanResponse(**result)


@app.post(
    "/api/v1/impose/creep-plan",
    response_model=CreepPlanResponse,
    tags=["拼版"],
    summary="骑马订爬移补偿：各页位图像向折缝中心的水平位移",
    responses={
        422: {"description": "参数非法，或某张爬移量达到单页宽度（错误信息指出帖号与张号）"},
    },
)
def create_creep_plan(request: CreepPlanRequest) -> CreepPlanResponse:
    result = creep_plan(
        total_pages=request.total_pages,
        max_sheets=request.max_sheets_per_signature,
        binding=request.binding,
        page_width_mm=request.page_width_mm,
        page_height_mm=request.page_height_mm,
        gutter_mm=request.gutter_mm,
        duplex_flip=request.duplex_flip,
        thickness_mm=request.thickness_mm,
    )
    return CreepPlanResponse(**result)


def _json_safe(value: object) -> object:
    """把错误明细中的非 JSON 有限浮点（NaN/Infinity）与异常对象替换为可序列化值。

    标准 JSON 不支持 NaN/Infinity：FastAPI 默认 422 响应会回显输入值，
    若请求体含 ``NaN`` / ``Infinity``，默认渲染会抛 ValueError 并落到 500。
    """
    if isinstance(value, float):
        if math.isnan(value):
            return "NaN"
        if math.isinf(value):
            return "Infinity" if value > 0 else "-Infinity"
        return value
    if isinstance(value, BaseException):
        return str(value)
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    _request: Request, exc: RequestValidationError
) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": _json_safe(exc.errors())})


@app.exception_handler(Exception)
async def unhandled_exception_handler(_request, exc: Exception) -> JSONResponse:
    # 兜底：未预期错误统一返回 500，避免向前端泄漏堆栈
    return JSONResponse(status_code=500, content={"detail": "内部错误"})
