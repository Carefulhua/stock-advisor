from __future__ import annotations

import pandas as pd
import pytest

from app.screener.conditions import Condition, FilterSpec
from app.screener.run import run_filter


def make_merged() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "code": ["000001", "000002", "000003", "600004", "600005", "600006"],
            "name": ["平安银行", "万科A", "ST康美", "中信银行", "贵州茅台", "恒瑞医药"],
            "pe_ttm": [5.0, 8.0, 20.0, 6.0, 30.0, 40.0],
            "net_profit_yoy": [10.0, 30.0, 50.0, 8.0, 25.0, 60.0],
            "turnover": [1e9, 2e9, 3e9, 4e9, 5e9, 6e9],
            "list_date": pd.to_datetime(["2010-01-01"] * 6),
        }
    )


def test_excludes_st_stocks():
    merged = make_merged()
    result = run_filter(merged, FilterSpec(), [], [])
    assert "000003" not in set(result["rows"]["code"])


def test_sorts_by_sort_by_field_desc() -> None:
    result = run_filter(make_merged(), FilterSpec(sort_by="net_profit_yoy"), [], [])
    assert result["rows"]["code"].tolist() == ["600006", "000002", "600005", "000001", "600004"]


def test_top_limits_row_count() -> None:
    result = run_filter(make_merged(), FilterSpec(top=2), [], [])
    assert result["rows"]["code"].tolist() == ["600006", "000002"]
    assert result["total_matched"] == 5


def test_total_matched_is_pre_top_count() -> None:
    spec = FilterSpec(conditions=[Condition(field="pe_ttm", op="lte", value=10.0)], top=1)
    result = run_filter(make_merged(), spec, [], [])
    assert result["total_matched"] == 3
    assert len(result["rows"]) == 1


def test_conditions_narrow_candidates() -> None:
    spec = FilterSpec(
        conditions=[Condition(field="pe_ttm", op="between", value=[0.0, 10.0])],
        sort_by="net_profit_yoy",
    )
    result = run_filter(make_merged(), spec, [], [])
    assert result["rows"]["code"].tolist() == ["000002", "000001", "600004"]


def test_zero_match_returns_empty_rows_without_error() -> None:
    spec = FilterSpec(conditions=[Condition(field="pe_ttm", op="gte", value=100.0)])
    result = run_filter(make_merged(), spec, [], [])
    assert result["rows"].empty
    assert result["next_in"] == []
    assert result["total_matched"] == 0


def test_favorites_are_kept_even_when_they_fail_conditions() -> None:
    spec = FilterSpec(conditions=[Condition(field="pe_ttm", op="lte", value=10.0)])
    result = run_filter(make_merged(), spec, [], ["600006"])
    assert result["kept_favorites"] == ["600006"]
    assert "600006" in result["rows"]["code"].tolist()
    assert result["rows"].iloc[0]["code"] == "600006"


def test_favorites_are_not_duplicated_when_already_selected() -> None:
    result = run_filter(make_merged(), FilterSpec(), [], ["600006"])
    assert result["rows"]["code"].tolist().count("600006") == 1


def test_rows_mark_favorites_with_flag() -> None:
    result = run_filter(make_merged(), FilterSpec(), [], ["600004"])
    rows = result["rows"]
    assert rows.loc[rows["code"] == "600004", "is_favorite"].tolist() == [True]
    assert rows.loc[rows["code"] == "600006", "is_favorite"].tolist() == [False]


def test_next_in_excludes_pool_members_and_favorites() -> None:
    result = run_filter(make_merged(), FilterSpec(), ["600004", "000001"], ["600006"])
    assert set(result["next_in"]) == {"000002", "600005"}
    assert result["next_out"] == []


def test_next_out_lists_pool_members_that_dropped_out() -> None:
    spec = FilterSpec(conditions=[Condition(field="pe_ttm", op="lte", value=10.0)])
    result = run_filter(make_merged(), spec, ["000001", "600006"], ["000002"])
    # 000001 命中条件但已在池中 → 不算新入池；600004 命中条件且不在池中 → 新入池
    assert result["next_in"] == ["600004"]
    assert result["next_out"] == ["600006"]
    assert result["kept_favorites"] == ["000002"]


def test_favorite_never_reported_as_next_out() -> None:
    spec = FilterSpec(conditions=[Condition(field="pe_ttm", op="lte", value=10.0)])
    result = run_filter(make_merged(), spec, ["600006"], ["600006"])
    assert result["next_out"] == []


def test_rank_is_continuous_from_one_with_favorites_first() -> None:
    result = run_filter(make_merged(), FilterSpec(top=2), [], ["600004"])
    assert result["rows"]["rank"].tolist() == [1, 2, 3]
    assert result["rows"]["code"].tolist() == ["600004", "600006", "000002"]


def test_rows_expose_display_columns() -> None:
    result = run_filter(make_merged(), FilterSpec(), [], [])
    expected = {"code", "name", "rank", "is_favorite", "pe_ttm", "net_profit_yoy", "turnover"}
    assert expected.issubset(result["rows"].columns)


def test_missing_value_rows_are_excluded() -> None:
    merged = make_merged()
    merged.loc[0, "pe_ttm"] = None
    spec = FilterSpec(conditions=[Condition(field="pe_ttm", op="lte", value=10.0)])
    result = run_filter(merged, spec, [], [])
    assert "000001" not in result["rows"]["code"].tolist()
    assert result["total_matched"] == 2


def test_pool_and_favorites_do_not_mutate_inputs() -> None:
    pool = ["000001"]
    favorites = ["600006"]
    merged = make_merged()
    run_filter(merged, FilterSpec(), pool, favorites)
    assert pool == ["000001"]
    assert favorites == ["600006"]