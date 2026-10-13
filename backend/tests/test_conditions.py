import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from app.screener.conditions import Condition, FilterSpec, evaluate


def make_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "code": ["000001", "000002", "000003", "000004", "000005", "000006", "000007", "000008"],
            "name": ["甲", "乙", "丙", "丁", "戊", "己", "庚", "辛"],
            "pe_ttm": [10.0, 20.0, 30.0, 20.0, -5.0, np.nan, 15.0, 25.0],
            "net_profit_yoy": [50.0, -10.0, 30.0, 30.0, 80.0, 20.0, np.nan, 5.0],
            "industry": ["半导体", "银行", "半导体", "医药", "银行", "医药", "汽车", None],
            "list_date": pd.to_datetime(
                ["2015-01-05", "2020-06-01", "2018-03-03", "2012-11-11", "2019-09-09", "2016-02-02", "2021-01-01", "2014-05-05"]
            ),
        }
    )


def codes(df: pd.DataFrame) -> list[str]:
    return list(df["code"])


def test_gte_includes_boundary():
    got = evaluate(make_df(), [Condition(field="pe_ttm", op="gte", value=20.0)])
    assert codes(got) == ["000002", "000003", "000004", "000008"]


def test_gt_excludes_boundary():
    got = evaluate(make_df(), [Condition(field="pe_ttm", op="gt", value=20.0)])
    assert codes(got) == ["000003", "000008"]


def test_lte_and_lt():
    # 000005 的 pe_ttm=-5（亏损股）同样满足 <=15 与 <15
    le = evaluate(make_df(), [Condition(field="pe_ttm", op="lte", value=15.0)])
    assert codes(le) == ["000001", "000005", "000007"]
    lt = evaluate(make_df(), [Condition(field="pe_ttm", op="lt", value=15.0)])
    assert codes(lt) == ["000001", "000005"]


def test_between_includes_both_bounds():
    got = evaluate(make_df(), [Condition(field="pe_ttm", op="between", value=[15.0, 25.0])])
    assert codes(got) == ["000002", "000004", "000007", "000008"]


def test_nan_values_are_excluded():
    got = evaluate(make_df(), [Condition(field="pe_ttm", op="lte", value=100.0)])
    assert "000006" not in codes(got)
    growth = evaluate(make_df(), [Condition(field="net_profit_yoy", op="gte", value=-100.0)])
    assert "000007" not in codes(growth)


def test_multiple_conditions_are_anded():
    got = evaluate(
        make_df(),
        [
            Condition(field="pe_ttm", op="lte", value=25.0),
            Condition(field="net_profit_yoy", op="gte", value=20.0),
        ],
    )
    assert codes(got) == ["000001", "000004", "000005"]


def test_industry_in_operator():
    got = evaluate(make_df(), [Condition(field="industry", op="in", value=["半导体", "汽车"])])
    assert codes(got) == ["000001", "000003", "000007"]


def test_industry_in_empty_list_returns_no_rows():
    got = evaluate(make_df(), [Condition(field="industry", op="in", value=[])])
    assert got.empty


def test_industry_in_drops_null_category():
    got = evaluate(make_df(), [Condition(field="industry", op="in", value=["医药"])])
    assert codes(got) == ["000004", "000006"]


def test_list_date_gte_and_lte():
    got = evaluate(make_df(), [Condition(field="list_date", op="gte", value="2019-01-01")])
    assert codes(got) == ["000002", "000005", "000007"]
    before = evaluate(make_df(), [Condition(field="list_date", op="lte", value="2015-01-05")])
    assert codes(before) == ["000001", "000004", "000008"]


def test_empty_conditions_returns_all_rows():
    assert len(evaluate(make_df(), [])) == 8


def test_unknown_field_rejected():
    with pytest.raises(ValidationError):
        Condition(field="nope", op="gte", value=1.0)


def test_operator_not_allowed_for_kind_rejected():
    with pytest.raises(ValidationError):
        Condition(field="pe_ttm", op="in", value=[1.0])
    with pytest.raises(ValidationError):
        Condition(field="industry", op="gte", value=1.0)


def test_between_requires_two_bounds():
    with pytest.raises(ValidationError):
        Condition(field="pe_ttm", op="between", value=[1.0])
    with pytest.raises(ValidationError):
        Condition(field="pe_ttm", op="between", value=[5.0, 1.0])


def test_between_rejects_non_numeric_value():
    with pytest.raises(ValidationError):
        Condition(field="pe_ttm", op="between", value="1,2")


def test_filter_spec_defaults_and_validation():
    spec = FilterSpec(conditions=[Condition(field="roe", op="gte", value=10.0)])
    assert spec.sort_by == "net_profit_yoy"
    assert spec.top == 100
    with pytest.raises(ValidationError):
        FilterSpec(conditions=[], sort_by="unknown_field")
    with pytest.raises(ValidationError):
        FilterSpec(conditions=[], top=0)


def test_filter_spec_json_roundtrip():
    spec = FilterSpec.model_validate(
        {"conditions": [{"field": "pe_ttm", "op": "between", "value": [5, 20]}], "sort_by": "roe", "top": 50}
    )
    assert spec.conditions[0].value == [5.0, 20.0]
    assert spec.model_dump(mode="json")["sort_by"] == "roe"