"""原纸备料（stock-plan）算法单元测试。"""
import itertools
import random

import pytest

from app.imposition import (
    _choose_stock_usage,
    _fit_count,
    _pieces_per_sheet,
    plan_stock,
)


# ---------------------------------------------------------------------------
# 整行整列排布数量
# ---------------------------------------------------------------------------


def test_fit_count_basic_grid():
    # n 个成品 + (n-1) 个间隔：2*48 + 4 = 100 恰好排满
    assert _fit_count(100, 48, 4) == 2
    assert _fit_count(99, 48, 4) == 1
    assert _fit_count(320, 100, 10) == 3  # 3*100 + 2*10 = 320


def test_fit_count_zero_spacing():
    assert _fit_count(300, 100, 0) == 3
    assert _fit_count(299, 100, 0) == 2
    assert _fit_count(47, 48, 0) == 0


def test_fit_count_too_small_usable():
    assert _fit_count(5, 10, 0) == 0
    assert _fit_count(0, 0, 0) == 0


def test_fit_count_decimal_exact_no_epsilon_roundup():
    # 可用 299.99999995（300 − 2×0.000000025）：3 个 100mm 成品需 300，
    # 差 5e-8 排不下，不能用容差误判为 3
    assert _fit_count(299.99999995, 100, 0) == 2
    # 恰好贴边（占用 == 可用长度）仍可排入
    assert _fit_count(300, 100, 0) == 3
    assert _fit_count(300.0, 100.0, 0.0) == 3
    # 间隔同样按十进制核算：2 个 0.1 + 1 个 0.05 = 0.25 恰满；第 3 个需 0.4
    assert _fit_count(0.25, 0.1, 0.05) == 2
    assert _fit_count(0.3, 0.1, 0.05) == 2
    assert _fit_count(0.24999999, 0.1, 0.05) == 1


# ---------------------------------------------------------------------------
# 单张出数与纸纹朝向
# ---------------------------------------------------------------------------


def test_pieces_per_sheet_grain_height():
    # 成品 420×297，原纸 1000×1000、无留边无间隔：2 列 × 3 行
    assert _pieces_per_sheet(1000, 1000, "height", 420, 297, 0, 0)[:3] == (6, 2, 3)


def test_pieces_per_sheet_grain_width_rotates_layout():
    # 书脊（成品高 297）必须与沿宽纸纹平行：成品高沿原纸宽 500 -> 1 列，
    # 成品宽 420 沿原纸高 900 -> 2 行
    pieces, columns, rows, usable_w, usable_h = _pieces_per_sheet(
        500, 900, "width", 420, 297, 0, 0
    )
    assert (columns, rows) == (1, 2)
    assert pieces == 2
    assert (usable_w, usable_h) == (500, 900)
    # 同一原纸纸纹沿高：成品宽沿原纸宽 -> 1 列，成品高沿原纸高 -> 3 行
    assert _pieces_per_sheet(500, 900, "height", 420, 297, 0, 0)[:3] == (3, 1, 3)


def test_pieces_per_sheet_margins_and_spacing():
    # 原纸 460×330、留边 10 -> 可用 440×310；成品 200×140、间隔 5：
    # 列 floor((440+5)/(200+5))=2，行 floor((310+5)/(140+5))=2
    assert _pieces_per_sheet(460, 330, "height", 200, 140, 10, 5)[:3] == (4, 2, 2)


def test_pieces_per_sheet_unusable_region():
    # 留边后可用区域小于成品：行列均为 0
    pieces, columns, rows, usable_w, usable_h = _pieces_per_sheet(
        100, 100, "height", 200, 140, 10, 5
    )
    assert pieces == 0 and columns == 0 and rows == 0
    assert usable_w == 80 and usable_h == 80


def test_pieces_per_sheet_invalid_grain():
    with pytest.raises(ValueError):
        _pieces_per_sheet(100, 100, "long", 50, 50, 0, 0)


def test_pieces_per_sheet_tiny_margin_not_absorbed():
    # 原纸宽 300、成品宽 100、四周留边 0.000000025、间隔 0：
    # 可用宽 299.99999995，3 列需 300 -> 只能排 2 列（修复前容差误判 3 列）
    pieces, columns, rows, usable_w, usable_h = _pieces_per_sheet(
        300, 100, "height", 100, 50, 0.000000025, 0
    )
    assert (columns, rows, pieces) == (2, 1, 2)
    assert usable_w == 299.99999995
    assert usable_h == 99.99999995
    # 留边为 0 时恰好贴边，仍排满 3 列
    assert _pieces_per_sheet(300, 100, "height", 100, 50, 0, 0)[:3] == (6, 3, 2)


# ---------------------------------------------------------------------------
# 需求与成品尺寸沿用拼版 / 机台版面
# ---------------------------------------------------------------------------


def test_demand_includes_padded_last_signature():
    # 5 页、每帖 1 张：第 2 帖补 3 空白仍占 1 张 -> 每册 2 张；印数 3 -> 需求 6
    result = plan_stock(
        5, 1, "left", 210, 297, 0, 3, [(1000, 1000, 30, "height")], 0, 0
    )
    assert result["signature_count"] == 2
    assert result["sheets_per_copy"] == 2
    assert result["total_demand"] == 6
    # 成品尺寸沿用机台版面：2×页宽+中缝 × 页高
    assert result["sheet_width_mm"] == 420
    assert result["sheet_height_mm"] == 297
    paper = result["papers"][0]
    assert (paper["pieces_per_sheet"], paper["columns"], paper["rows"]) == (6, 2, 3)
    assert paper["used"] == 1
    assert result["total_production"] == 6
    assert result["surplus"] == 0
    assert result["total_area_mm2"] == 1_000_000


# ---------------------------------------------------------------------------
# 组合优选：总面积 -> 超产 -> 用量字典序
# ---------------------------------------------------------------------------


def test_min_area_prefers_smaller_sheets_when_exact():
    # 成品 100×100：A 300×300 出 9（面积 90000），B 200×200 出 4（面积 40000）
    # 需求 4：1 张 B 面积 40000 恰好满足
    result = plan_stock(
        4, 1, "left", 50, 100, 0, 4,
        [(300, 300, 30, "height"), (200, 200, 30, "height")],
        0, 0,
    )
    assert [p["used"] for p in result["papers"]] == [0, 1]
    assert result["total_area_mm2"] == 40000
    assert result["surplus"] == 0


def test_area_priority_beats_overproduction():
    # A 300×300 出 9（面积 90000），B 200×200 出 4（面积 40000）；需求 5：
    # 1 张 A -> 产 9 超 4 面积 90000；2 张 B -> 产 8 超 3 面积 80000
    # 面积优先：选 B（即使 B 的单张利用率更低）
    result = plan_stock(
        4, 1, "left", 50, 100, 0, 5,
        [(300, 300, 30, "height"), (200, 200, 30, "height")],
        0, 0,
    )
    assert [p["used"] for p in result["papers"]] == [0, 2]
    assert result["total_area_mm2"] == 80000
    assert result["total_production"] == 8
    assert result["surplus"] == 3


def test_overproduction_tiebreak():
    # 仅一种原纸、出 2 张：需求 3 必须用 2 张，产 4 超 1
    result = plan_stock(
        4, 1, "left", 50, 100, 0, 3, [(100, 200, 30, "height")], 0, 0
    )
    assert result["papers"][0]["used"] == 2
    assert result["total_production"] == 4
    assert result["surplus"] == 1


def test_lex_usage_tiebreak_equal_area_and_production():
    # A 200×100（2 出，面积 20000），B 100×200（2 出，面积 20000）：
    # 需求 1 时 (1,0) 与 (0,1) 面积、产量完全相同；按输入顺序用量字典序最小
    # 即 (0,1)（首位可 0 则 0）
    result = plan_stock(
        4, 1, "left", 50, 100, 0, 1,
        [(200, 100, 30, "height"), (100, 200, 30, "height")],
        0, 0,
    )
    assert [p["used"] for p in result["papers"]] == [0, 1]
    assert result["total_area_mm2"] == 20000
    assert result["surplus"] == 1
    # 输入顺序调换后仍取“靠后规格 1 张”
    reversed_result = plan_stock(
        4, 1, "left", 50, 100, 0, 1,
        [(100, 200, 30, "height"), (200, 100, 30, "height")],
        0, 0,
    )
    assert [p["used"] for p in reversed_result["papers"]] == [0, 1]


def test_inventory_zero_spec_skipped():
    result = plan_stock(
        4, 1, "left", 50, 100, 0, 2,
        [(200, 200, 0, "height"), (200, 200, 30, "height")],
        0, 0,
    )
    assert [p["used"] for p in result["papers"]] == [0, 1]


def test_inventory_caps_capacity():
    # 2 出/张、库存 10 -> 满负荷 20；需求 30 不可行
    with pytest.raises(ValueError, match="20"):
        plan_stock(
            4, 1, "left", 50, 100, 0, 30, [(200, 100, 10, "height")], 0, 0
        )


def test_all_specs_zero_pieces_infeasible():
    # 成品 420×297 无法排入 400×280：产能 0 < 需求 1
    with pytest.raises(ValueError):
        plan_stock(
            4, 1, "left", 210, 297, 0, 1, [(400, 280, 30, "height")], 0, 0
        )


def test_infeasible_message_states_capacity_and_demand():
    # 500×400 对 420×297 出 1，库存 30 -> 产能 30 < 需求 100
    with pytest.raises(ValueError) as exc_info:
        plan_stock(
            4, 1, "left", 210, 297, 0, 100, [(500, 400, 30, "height")], 0, 0
        )
    message = str(exc_info.value)
    assert "30" in message and "100" in message


def test_plan_stock_tiny_margin_capacity_and_feasibility():
    # 任务场景：原纸 300×100、成品 100×50、留边 0.000000025、间隔 0
    # 可用宽 299.99999995 -> 单张 2 列 × 1 行 = 2；需求 3（每册 1 张 × 印数 3）
    # 库存 1 张产能 2 < 3 -> 不可行（修复前误判产能 3 而放行）
    with pytest.raises(ValueError) as exc_info:
        plan_stock(
            4, 1, "left", 50, 50, 0, 3, [(300, 100, 1, "height")], 0.000000025, 0
        )
    message = str(exc_info.value)
    assert "2" in message and "3" in message
    # 库存 2 张 -> 产能 4 可行：用 2 张产 4，超产 1
    result = plan_stock(
        4, 1, "left", 50, 50, 0, 3, [(300, 100, 2, "height")], 0.000000025, 0
    )
    paper = result["papers"][0]
    assert (paper["pieces_per_sheet"], paper["columns"], paper["rows"]) == (2, 2, 1)
    assert paper["usable_width_mm"] == 299.99999995
    assert paper["usable_height_mm"] == 99.99999995
    assert paper["used"] == 2
    assert result["total_production"] == 4
    assert result["surplus"] == 1


def test_plan_stock_decimal_sheet_width_exact_fit():
    # 页宽 0.05、中缝 0.2 -> 成品宽十进制恰为 0.3（二进制浮点合成得
    # 0.30000000000000004）；原纸 1×1、留边 0.35 -> 可用 0.3×0.3，恰好贴边排 1×1
    result = plan_stock(
        4, 1, "left", 0.05, 0.3, 0.2, 1, [(1, 1, 1, "height")], 0.35, 0
    )
    assert result["papers"][0]["pieces_per_sheet"] == 1
    assert result["surplus"] == 0


# ---------------------------------------------------------------------------
# 参数校验
# ---------------------------------------------------------------------------


def _base_kwargs(**overrides):
    params = dict(
        total_pages=4,
        max_sheets=1,
        binding="left",
        page_width_mm=100,
        page_height_mm=100,
        gutter_mm=0,
        copies=1,
        papers=[(200, 200, 1, "height")],
        margin_mm=0,
        spacing_mm=0,
    )
    params.update(overrides)
    return params


def test_invalid_imposition_and_layout_params():
    for overrides in (
        {"total_pages": 0},
        {"max_sheets": 0},
        {"binding": "top"},
        {"page_width_mm": 0},
        {"page_height_mm": -1},
        {"gutter_mm": -0.5},
        {"copies": 0},
        {"margin_mm": -1},
        {"spacing_mm": float("nan")},
        {"page_width_mm": float("inf")},
    ):
        with pytest.raises(ValueError):
            plan_stock(**_base_kwargs(**overrides))


def test_copies_must_be_strict_integer():
    with pytest.raises(ValueError):
        plan_stock(**_base_kwargs(copies=True))
    with pytest.raises(ValueError):
        plan_stock(**_base_kwargs(copies=2.0))


def test_paper_count_limits():
    six = [(200, 200, 1, "height")] * 6
    assert len(plan_stock(**_base_kwargs(papers=six))["papers"]) == 6
    with pytest.raises(ValueError):
        plan_stock(**_base_kwargs(papers=six + [(200, 200, 1, "height")]))
    with pytest.raises(ValueError):
        plan_stock(**_base_kwargs(papers=[]))


def test_paper_field_validation():
    for paper in (
        (0, 200, 1, "height"),       # 宽非正
        (200, -1, 1, "height"),      # 高负
        (200, 200, 31, "height"),    # 库存超 30
        (200, 200, -1, "height"),    # 库存负
        (200, 200, 1, "long"),       # 纸纹取值非法
        (200.0, 200, 1, "height"),   # 宽非整数
        (True, 200, 1, "height"),    # 布尔不接受
    ):
        with pytest.raises(ValueError):
            plan_stock(**_base_kwargs(papers=[paper]))


# ---------------------------------------------------------------------------
# 折半枚举优选：对小规模穷举结果做随机交叉验证
# ---------------------------------------------------------------------------


def test_choose_stock_usage_matches_brute_force():
    rng = random.Random(20260925)
    for _ in range(3000):
        n = rng.randint(1, 6)
        pieces = [rng.randint(0, 6) for _ in range(n)]
        areas = [rng.randint(1, 5) for _ in range(n)]
        inventories = [rng.randint(0, 4) for _ in range(n)]
        demand = rng.randint(1, 15)

        usage = _choose_stock_usage(pieces, areas, inventories, demand)

        best = None
        for combo in itertools.product(*[range(i + 1) for i in inventories]):
            production = sum(u * p for u, p in zip(combo, pieces))
            if production < demand:
                continue
            area = sum(u * a for u, a in zip(combo, areas))
            key = (area, production, combo)
            if best is None or key < best:
                best = key

        if best is None:
            assert usage is None
        else:
            production = sum(u * p for u, p in zip(usage, pieces))
            area = sum(u * a for u, a in zip(usage, areas))
            assert (area, production, tuple(usage)) == best
