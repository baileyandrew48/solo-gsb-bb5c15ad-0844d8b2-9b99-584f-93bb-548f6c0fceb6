"""订针计划（staple-plan）算法单元测试。"""
import pytest

from app.imposition import staple_plan, _plan_staple_signature


def _plan(**overrides):
    params = dict(
        page_height_mm=100.0,
        top_margin_mm=14.0,
        bottom_margin_mm=14.0,
        min_spacing_mm=10.0,
        staple_count=3,
        forbidden=[],
    )
    params.update(overrides)
    return _plan_staple_signature(**params)


def test_exact_ideal_positions():
    # 可用高 72，订 3 针：理想针位 32/50/68 恰为整数
    positions, max_deviation = _plan()
    assert positions == [32, 50, 68]
    assert max_deviation == 0.0
    assert positions == sorted(positions)


def test_positions_strictly_inside_margins():
    # 留边边界上的整数刻度不能下针：20、80 均不可用
    positions, _ = _plan(
        page_height_mm=100, top_margin_mm=20, bottom_margin_mm=20,
        min_spacing_mm=10, staple_count=2,
    )
    assert all(20 < p < 80 for p in positions)


def test_positions_within_page_for_zero_margins():
    # 上下留边为 0：针位仍须严格落在页高内（1..页高-1 的整数刻度）
    positions, _ = _plan(
        page_height_mm=50, top_margin_mm=0, bottom_margin_mm=0,
        min_spacing_mm=0, staple_count=2,
    )
    assert all(1 <= p <= 49 for p in positions)


def test_half_integer_ideals_lexicographic_tie():
    # 理想针位 38.5/61.5：[38,61] 与 [39,62] 最大偏差与偏差总和均相同，
    # 取针位序列字典序最小者
    positions, max_deviation = _plan(
        page_height_mm=100, top_margin_mm=15.5, bottom_margin_mm=15.5,
        min_spacing_mm=10, staple_count=2,
    )
    assert positions == [38, 61]
    assert max_deviation == pytest.approx(0.5)


def test_forbidden_closed_interval_endpoints_excluded():
    # 理想针位 30/50/70；禁区 [30, 30] 是闭区间，刻度 30 同样禁针
    positions, _ = _plan(
        top_margin_mm=10, bottom_margin_mm=10,
        min_spacing_mm=10, staple_count=3, forbidden=[(30, 30)],
    )
    assert 30 not in positions


def test_forbidden_zone_forces_shift():
    # 理想针位 30/50/70；禁区 [20,30] 闭区间封掉刻度 30（与 29），
    # 最贴近的可用刻度为 31（偏差 1 mm）
    positions, max_deviation = _plan(
        top_margin_mm=10, bottom_margin_mm=10,
        min_spacing_mm=10, staple_count=3, forbidden=[(20, 30)],
    )
    assert positions == [31, 50, 70]
    assert max_deviation == 1.0


def test_sum_of_deviations_tiebreak_before_lex():
    # 理想针位 30/50/70，中间针位 50 被禁区 [40,50] 封掉：
    # 最大偏差同为 1 mm 时，[30,51,70] 偏差总和为 1，
    # 优于总和为 2 的 [29,51,70] / [30,51,69]
    positions, max_deviation = _plan(
        top_margin_mm=10, bottom_margin_mm=10,
        min_spacing_mm=10, staple_count=3, forbidden=[(40, 50)],
    )
    assert positions == [30, 51, 70]
    assert max_deviation == 1.0


def test_lexicographic_tie_with_equal_sum():
    # 禁区 [20,30]、最小针距 50：理想针位 36.67/63.33，
    # [19,69] 与 [31,81] 最大偏差、偏差总和均相同 -> 取字典序最小
    positions, max_deviation = _plan(
        top_margin_mm=10, bottom_margin_mm=10,
        min_spacing_mm=50, staple_count=2, forbidden=[(20, 30)],
    )
    assert positions == [19, 69]
    assert max_deviation == pytest.approx(53 / 3, abs=1e-9)


def test_min_spacing_pushes_positions_apart():
    # 理想针位 20/40/60/80；最小针距 30 迫使四针等距外移，
    # 最优最大偏差 15 mm（[5,35,65,95]）
    positions, max_deviation = _plan(
        page_height_mm=100, top_margin_mm=0, bottom_margin_mm=0,
        min_spacing_mm=30, staple_count=4,
    )
    assert positions == [5, 35, 65, 95]
    assert all(b - a >= 30 for a, b in zip(positions, positions[1:]))
    assert max_deviation == 15.0


def test_infeasible_when_spacing_exceeds_usable_height():
    # 可用高 80 mm（留边各 10）却要求最小针距 80 -> 无可行排列
    with pytest.raises(ValueError):
        _plan(
            top_margin_mm=10, bottom_margin_mm=10,
            min_spacing_mm=80, staple_count=2,
        )


def test_infeasible_when_zone_covers_all_ticks():
    # 禁区 [11,89] 覆盖全部合法刻度（留边各 10）
    with pytest.raises(ValueError):
        _plan(
            top_margin_mm=10, bottom_margin_mm=10,
            min_spacing_mm=10, staple_count=2, forbidden=[(11, 89)],
        )


def test_infeasible_when_zone_fragments_too_narrow():
    # 可用刻度被禁区切成 11..19 一段，放不下针距 50 的两根针
    with pytest.raises(ValueError):
        _plan(
            top_margin_mm=10, bottom_margin_mm=10,
            min_spacing_mm=50, staple_count=2, forbidden=[(20, 89)],
        )


def test_non_integer_page_height_uses_floor_ticks():
    # 页高 50.5、留边 0：刻度 1..50，且最大刻度须 < 50.5
    positions, _ = _plan(
        page_height_mm=50.5, top_margin_mm=0, bottom_margin_mm=0,
        min_spacing_mm=0, staple_count=2,
    )
    assert positions[-1] <= 50


def test_staple_plan_reuses_signatures_and_reports_error_index():
    # 6 页、每帖 1 张 -> 2 帖（第 2 帖补 2 空白）
    result = staple_plan(
        total_pages=6,
        max_sheets=1,
        binding="left",
        page_height_mm=100,
        staple_count=2,
        top_margin_mm=10,
        bottom_margin_mm=10,
        min_spacing_mm=10,
        forbidden_by_signature=[
            (2, [(20, 30)]),
        ],
    )
    assert result["signature_count"] == 2
    assert [
        (s["signature_index"], s["sheet_count"], s["page_count_padded"])
        for s in result["signatures"]
    ] == [(1, 1, 4), (2, 1, 4)]
    # 第 2 帖的禁区只影响第 2 帖
    assert 30 not in result["signatures"][1]["staple_positions_mm"]
    assert all(len(s["staple_positions_mm"]) == 2 for s in result["signatures"])


def test_staple_plan_error_points_at_signature():
    # 第 1 帖可行、第 2 帖因本帖禁区无可行排列：错误信息必须指出帖号
    with pytest.raises(ValueError, match="第 2 帖"):
        staple_plan(
            total_pages=6,
            max_sheets=1,
            binding="left",
            page_height_mm=100,
            staple_count=2,
            top_margin_mm=10,
            bottom_margin_mm=10,
            min_spacing_mm=10,
            forbidden_by_signature=[(2, [(11, 89)])],
        )


def test_staple_plan_invalid_signature_index():
    with pytest.raises(ValueError, match="帖号"):
        staple_plan(
            total_pages=4, max_sheets=1, binding="left",
            page_height_mm=100, staple_count=2,
            top_margin_mm=10, bottom_margin_mm=10, min_spacing_mm=10,
            forbidden_by_signature=[(2, [(1, 2)])],
        )


def test_staple_plan_duplicate_signature_index():
    with pytest.raises(ValueError, match="重复"):
        staple_plan(
            total_pages=8, max_sheets=1, binding="left",
            page_height_mm=100, staple_count=2,
            top_margin_mm=10, bottom_margin_mm=10, min_spacing_mm=10,
            forbidden_by_signature=[(1, [(1, 2)]), (1, [(3, 4)])],
        )


def test_staple_plan_invalid_interval_bounds():
    kwargs = dict(
        total_pages=4, max_sheets=1, binding="left",
        page_height_mm=100, staple_count=2,
        top_margin_mm=10, bottom_margin_mm=10, min_spacing_mm=10,
    )
    for intervals in ([(-1, 5)], [(80, 70)], [(1, 101)]):
        with pytest.raises(ValueError):
            staple_plan(**kwargs, forbidden_by_signature=[(1, intervals)])


def test_staple_plan_invalid_arguments():
    kwargs = dict(
        total_pages=4, max_sheets=1, binding="left",
        page_height_mm=100, staple_count=2,
        top_margin_mm=10, bottom_margin_mm=10, min_spacing_mm=10,
        forbidden_by_signature=[],
    )
    for override in (
        {"page_height_mm": 49}, {"page_height_mm": 1001},
        {"staple_count": 1}, {"staple_count": 5},
        {"top_margin_mm": -1}, {"bottom_margin_mm": -0.1},
        {"min_spacing_mm": -1},
        {"top_margin_mm": 90, "bottom_margin_mm": 10},
        {"binding": "top"},
    ):
        with pytest.raises(ValueError):
            staple_plan(**{**kwargs, **override})
