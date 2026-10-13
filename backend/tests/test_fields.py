import pytest

from app.screener import fields

NUMERIC_OPS = ("gte", "gt", "lte", "lt", "between")


def test_catalog_entries_are_complete():
    catalog = fields.catalog()
    assert len(catalog) == len(fields.FIELDS)
    for item in catalog:
        assert item["label"], item
        assert item["unit"], item
        assert item["kind"] in {"number", "enum", "date"}, item
        assert item["ops"], item


def test_numeric_fields_support_five_operators():
    for item in fields.catalog():
        if item["kind"] == "number":
            assert tuple(item["ops"]) == NUMERIC_OPS, item["field"]


def test_industry_is_enum_with_in_operator():
    industry = fields.by_name("industry")
    assert industry.kind == "enum"
    assert tuple(industry.ops) == ("in",)


def test_industry_options_populated_at_runtime():
    fields.set_industry_options(["半导体", "银行"])
    try:
        industry = next(item for item in fields.catalog() if item["field"] == "industry")
        assert industry["options"] == ["半导体", "银行"]
    finally:
        fields.set_industry_options([])


def test_list_date_is_date_kind():
    assert fields.by_name("list_date").kind == "date"


def test_is_known():
    assert fields.is_known("pe_ttm") is True
    assert fields.is_known("net_profit_yoy") is True
    assert fields.is_known("nope") is False


def test_ops_for_unknown_field_raises():
    with pytest.raises(KeyError):
        fields.ops_for("nope")


def test_by_name_unknown_field_raises():
    with pytest.raises(KeyError):
        fields.by_name("nope")


def test_spec_table_has_expected_fields():
    expected = {
        "pe_ttm", "pn", "turnover", "ltsz", "zsz", "hsl", "lb",
        "zdf_y", "zdf_d20", "zdf_d60", "zljlr",
        "eps", "cfps", "revenue_yoy", "net_profit_yoy", "net_profit",
        "roe", "gross_margin", "industry", "list_date",
    }
    assert {item["field"] for item in fields.catalog()} == expected