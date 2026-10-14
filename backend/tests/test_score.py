import pandas as pd
import pytest

from app.screener import score


def universe() -> pd.DataFrame:
    """6 只样本：roe/负债率/净利率等逐只单调，便于验证打分方向与排序。"""
    return pd.DataFrame(
        {
            "code": ["000001", "000002", "000003", "000004", "000005", "000006"],
            "name": ["A", "B", "C", "D", "E", "F"],
            "roe": [5.0, 10.0, 15.0, 20.0, 25.0, 30.0],
            "debt_ratio": [80.0, 65.0, 50.0, 40.0, 30.0, 20.0],
            "net_margin": [2.0, 5.0, 9.0, 14.0, 20.0, 28.0],
            "revenue_yoy": [1.0, 3.0, 6.0, 10.0, 15.0, 22.0],
            "net_profit_yoy": [-5.0, 2.0, 8.0, 15.0, 25.0, 40.0],
            "gross_margin": [10.0, 20.0, 30.0, 40.0, 50.0, 60.0],
            "cfps": [0.1, 0.3, 0.6, 1.0, 1.5, 2.2],
        }
    )


def test_scores_stay_in_zero_to_hundred_and_rank_is_dense():
    got = score.score_universe(universe())

    assert got["score"].between(0, 100).all()
    assert list(got["rank"]) == list(range(1, len(got) + 1))
    assert list(got["code"]) == ["000006", "000005", "000004", "000003", "000002", "000001"]


def test_higher_is_better_factor_rewards_larger_values():
    got = score.score_universe(universe())
    top = got.iloc[0]

    assert top["code"] == "000006"
    assert top["pct_roe"] == pytest.approx(1.0)
    assert top["pct_revenue_yoy"] == pytest.approx(1.0)


def test_lower_is_better_factor_inverts_percentile():
    """资产负债率方向与其余因子相反：负债越高，百分位越低。

    pandas 的 rank(pct=True) 给最小值 1/n 而非 1，故最优档位是 1-1/n、最差档位恰为 0。
    """
    df = universe()
    got = score.score_universe(df).set_index("code")
    by_debt = df.sort_values("debt_ratio", ascending=False)["code"].tolist()

    pcts = list(got.loc[by_debt, "pct_debt_ratio"])
    assert pcts == sorted(pcts)
    assert pcts[0] == pytest.approx(0.0)
    assert pcts[-1] == pytest.approx(1.0 - 1 / len(df), abs=1e-4)


def test_missing_factor_values_score_neutral_not_worst():
    """缺失值取中性 0.5，否则「未披露财报」会被当成所有因子最差。"""
    df = universe()
    df.loc[0, "roe"] = None
    df.loc[0, "debt_ratio"] = None

    got = score.score_universe(df).set_index("code")

    assert got.loc["000001", "pct_roe"] == pytest.approx(score.NEUTRAL_PERCENTILE)
    assert got.loc["000001", "pct_debt_ratio"] == pytest.approx(score.NEUTRAL_PERCENTILE)


def test_absent_factor_column_is_skipped_and_remaining_weights_renormalized():
    df = universe().drop(columns=["cfps", "gross_margin"])

    got = score.score_universe(df)

    assert "pct_cfps" not in got.columns
    assert "pct_gross_margin" not in got.columns
    assert got["score"].between(0, 100).all()
    assert got.iloc[0]["code"] == "000006"
    remaining = score.resolve_factors(df.columns.tolist())
    assert {spec.field for spec in remaining} == {
        "roe", "revenue_yoy", "net_profit_yoy", "net_margin", "debt_ratio",
    }
    assert sum(spec.weight for spec in remaining) == pytest.approx(1.0)


def test_custom_weights_shift_the_ranking():
    df = pd.DataFrame(
        {
            "code": ["A", "B", "C"],
            "name": ["高增长高负债", "低增长低负债", "居中"],
            "revenue_yoy": [50.0, 1.0, 25.0],
            "debt_ratio": [90.0, 10.0, 50.0],
        }
    )

    growth_heavy = score.score_universe(df, weights={"revenue_yoy": 1.0})
    safety_heavy = score.score_universe(df, weights={"debt_ratio": 1.0})

    assert growth_heavy.iloc[0]["code"] == "A"
    assert safety_heavy.iloc[0]["code"] == "B"


def test_weights_with_only_zero_weight_produce_no_factors():
    assert score.resolve_factors(universe().columns.tolist(), {"roe": 0.0}) == []


def test_resolve_factors_normalizes_weights_to_one():
    specs = score.resolve_factors(universe().columns.tolist())

    assert sum(spec.weight for spec in specs) == pytest.approx(1.0)
    assert {spec.field for spec in specs} == set(score.default_weights())


def test_unknown_weight_factor_raises():
    with pytest.raises(KeyError):
        score.score_universe(universe(), weights={"not_a_factor": 1.0})


def test_empty_frame_returns_empty_result_with_expected_columns():
    got = score.score_universe(pd.DataFrame())

    assert got.empty
    assert list(got.columns) == ["code", "name", "score", "rank"]


def test_frame_without_code_column_returns_empty_result():
    got = score.score_universe(pd.DataFrame({"roe": [1.0, 2.0]}))

    assert got.empty


def test_top_limits_rows_after_ranking():
    got = score.score_universe(universe(), top=3)

    assert len(got) == 3
    assert list(got["rank"]) == [1, 2, 3]


def test_non_numeric_factor_values_are_treated_as_missing():
    df = universe()
    df["roe"] = df["roe"].astype(object)
    df.loc[0, "roe"] = "N/A"

    got = score.score_universe(df).set_index("code")

    assert got.loc["000001", "pct_roe"] == pytest.approx(score.NEUTRAL_PERCENTILE)


def test_non_contiguous_index_does_not_shift_component_scores():
    """调用方剔除 ST 后索引会不连续（0,1,3），百分位必须按位置而非下标对齐。"""
    df = universe().drop(index=[3, 4])

    got = score.score_universe(df, weights={"roe": 1.0}).set_index("code")

    assert set(got.index) == {"000001", "000002", "000003", "000006"}
    assert got["pct_roe"].notna().all()
    assert got.loc["000006", "pct_roe"] == pytest.approx(1.0)
    assert got.loc["000001", "pct_roe"] == pytest.approx(0.25)


def test_tied_factor_values_share_the_same_percentile():
    df = pd.DataFrame({"code": ["A", "B", "C"], "roe": [5.0, 5.0, 9.0]})

    got = score.score_universe(df, weights={"roe": 1.0}).set_index("code")

    assert got.loc["A", "pct_roe"] == got.loc["B", "pct_roe"]
    assert got.loc["C", "pct_roe"] == pytest.approx(1.0)
