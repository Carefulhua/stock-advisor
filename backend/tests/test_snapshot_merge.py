import akshare as ak
import pandas as pd
import pytest

from app.screener import snapshot


def raw_snapshot() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "code": ["sh600000", "sz000001", "sz300750"],
            "name": ["浦发银行", "平安银行", "宁德时代"],
            "zxj": [10.0, 11.0, 180.0],
            "zd": [0.1, -0.2, 3.0],
            "zdf": [1.0, -1.8, 1.7],
            "zf": [2.0, 3.0, 4.0],
            "lb": [1.1, 0.9, 1.5],
            "hsl": [0.8, 0.6, 2.2],
            "turnover": [100000.0, 200000.0, 500000.0],
            "volume": [1000.0, 2000.0, 3000.0],
            "pe_ttm": [5.0, 6.0, 30.0],
            "pn": [0.6, 0.7, 4.2],
            "ltsz": [1000.0, 2000.0, 5000.0],
            "zsz": [1200.0, 2500.0, 9000.0],
            "zljlr": [-5000.0, 3000.0, 12000.0],
            "zdf_y": [10.0, -5.0, 40.0],
            "zdf_d5": [1.0, -2.0, 5.0],
            "zdf_d10": [2.0, -3.0, 8.0],
            "zdf_d20": [3.0, -4.0, 12.0],
            "zdf_d60": [6.0, -8.0, 20.0],
        }
    )


def test_fetch_market_snapshot_maps_columns_and_units(monkeypatch):
    monkeypatch.setattr(snapshot, "_with_retry", lambda fn, **kw: raw_snapshot())
    got = snapshot.fetch_market_snapshot()
    assert list(got["code"]) == ["600000", "000001", "300750"]
    assert got.loc[0, "turnover"] == pytest.approx(1e9)
    assert got.loc[0, "ltsz"] == pytest.approx(1e11)
    assert got.loc[0, "zsz"] == pytest.approx(1.2e11)
    assert got.loc[0, "zljlr"] == pytest.approx(-5e7)
    assert got.loc[0, "pe_ttm"] == pytest.approx(5.0)
    assert got.loc[0, "pn"] == pytest.approx(0.6)
    assert got.loc[2, "zdf_d60"] == pytest.approx(20.0)


def raw_earnings() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "股票代码": ["600000", "000001"],
            "每股收益": [1.2, 0.8],
            "每股经营现金流量": [1.5, None],
            "营业总收入-同比增长": [10.5, -3.2],
            "营业总收入-季度环比增长": [2.5, -1.1],
            "净利润-净利润": [50000000000.0, 30000000000.0],
            "净利润-同比增长": [12.5, -4.0],
            "净利润-季度环比增长": [3.5, -0.8],
            "净资产收益率": [9.8, 7.1],
            "销售毛利率": [45.0, None],
            "所处行业": ["银行", "银行"],
        }
    )


def test_fetch_earnings_growth_returns_all_fields(monkeypatch):
    monkeypatch.setattr(snapshot, "_with_retry", lambda fn, **kw: raw_earnings())
    got = snapshot.fetch_earnings_growth("20260630")
    assert list(got["code"]) == ["600000", "000001"]
    assert got.loc[0, "eps"] == pytest.approx(1.2)
    assert got.loc[0, "cfps"] == pytest.approx(1.5)
    assert pd.isna(got.loc[1, "cfps"])
    assert got.loc[0, "revenue_yoy"] == pytest.approx(10.5)
    assert got.loc[0, "revenue_qoq"] == pytest.approx(2.5)
    assert got.loc[1, "revenue_qoq"] == pytest.approx(-1.1)
    assert got.loc[0, "net_profit"] == pytest.approx(5e10)
    assert got.loc[0, "net_profit_yoy"] == pytest.approx(12.5)
    assert got.loc[0, "net_profit_qoq"] == pytest.approx(3.5)
    assert got.loc[1, "net_profit_qoq"] == pytest.approx(-0.8)
    assert got.loc[0, "roe"] == pytest.approx(9.8)
    assert got.loc[0, "gross_margin"] == pytest.approx(45.0)
    assert got.loc[0, "industry"] == "银行"


def raw_balance() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "股票代码": ["600000", "000001", "300750"],
            "资产负债率": [91.8, 91.9, 60.2],
        }
    )


def raw_income() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "股票代码": ["600000", "000001", "300750"],
            "净利润": [5.0e10, 4.4e10, 3.0e10],
            "营业总收入": [1.0e11, 1.0e11, 1.0e11],
        }
    )


def test_fetch_fundamentals_derives_debt_ratio_and_net_margin(monkeypatch):
    def fake_retry(fn, **kwargs):
        return raw_balance() if fn is ak.stock_zcfz_em else raw_income()

    monkeypatch.setattr(snapshot, "_with_retry", fake_retry)

    got = snapshot.fetch_fundamentals("20260630").set_index("code")

    assert set(got.index) == {"600000", "000001", "300750"}
    assert got.loc["600000", "debt_ratio"] == pytest.approx(91.8)
    assert got.loc["300750", "debt_ratio"] == pytest.approx(60.2)
    assert got.loc["600000", "net_margin"] == pytest.approx(50.0)
    assert got.loc["300750", "net_margin"] == pytest.approx(30.0)


def test_fetch_fundamentals_blank_net_margin_when_revenue_missing(monkeypatch):
    income = raw_income()
    income.loc[2, "营业总收入"] = 0.0
    monkeypatch.setattr(
        snapshot,
        "_with_retry",
        lambda fn, **kw: raw_balance() if fn is ak.stock_zcfz_em else income,
    )

    got = snapshot.fetch_fundamentals("20260630").set_index("code")

    assert pd.isna(got.loc["300750", "net_margin"])
    assert got.loc["300750", "debt_ratio"] == pytest.approx(60.2)


def test_merge_snapshot_left_joins_and_fills_missing():
    snap = pd.DataFrame({"code": ["600000", "000001", "300750"], "name": ["A", "B", "C"], "pe_ttm": [5.0, 6.0, 30.0]})
    listing = pd.DataFrame({"code": ["600000", "000001"], "list_date": pd.to_datetime(["2000-01-01", "2005-06-01"])})
    earnings = pd.DataFrame({"code": ["600000"], "net_profit_yoy": [12.5], "industry": ["银行"]})
    got = snapshot.merge_snapshot(snap, listing, earnings)
    assert len(got) == 3
    assert pd.isna(got.loc[2, "net_profit_yoy"])
    assert pd.isna(got.loc[2, "list_date"])
    assert got.loc[0, "net_profit_yoy"] == pytest.approx(12.5)


def test_merge_snapshot_adds_fundamentals_when_provided():
    snap = pd.DataFrame({"code": ["600000", "000001"], "name": ["A", "B"]})
    listing = pd.DataFrame({"code": ["600000"], "list_date": pd.to_datetime(["2000-01-01"])})
    earnings = pd.DataFrame({"code": ["600000"], "roe": [9.8]})
    fundamentals = pd.DataFrame({"code": ["600000"], "debt_ratio": [91.8], "net_margin": [50.0]})

    got = snapshot.merge_snapshot(snap, listing, earnings, fundamentals)

    assert got.loc[0, "debt_ratio"] == pytest.approx(91.8)
    assert got.loc[0, "net_margin"] == pytest.approx(50.0)
    assert pd.isna(got.loc[1, "debt_ratio"])


def test_snapshot_cache_serves_same_day(monkeypatch):
    calls = []

    def fake_fetch() -> pd.DataFrame:
        calls.append(1)
        return pd.DataFrame({"code": ["600000"], "name": ["A"], "turnover": [1.0]})

    monkeypatch.setattr(snapshot, "fetch_market_snapshot", fake_fetch)
    monkeypatch.setattr(snapshot, "_SNAPSHOT_CACHE", None)
    snapshot._SNAPSHOT_CACHE = None
    first = snapshot.market_snapshot_cached()
    second = snapshot.market_snapshot_cached()
    assert len(calls) == 1
    assert first is second
    assert snapshot.snapshot_cache_state() is True


def test_snapshot_cache_refetched_next_day(monkeypatch):
    calls = []

    def fake_fetch() -> pd.DataFrame:
        calls.append(1)
        return pd.DataFrame({"code": ["600000"], "name": ["A"], "turnover": [float(len(calls))]})

    monkeypatch.setattr(snapshot, "fetch_market_snapshot", fake_fetch)
    snapshot._SNAPSHOT_CACHE = None
    snapshot.market_snapshot_cached()
    snapshot._SNAPSHOT_CACHE = ("1999-01-01", pd.DataFrame({"code": ["x"]}))
    got = snapshot.market_snapshot_cached()
    assert len(calls) == 2
    assert got.loc[0, "turnover"] == pytest.approx(2.0)


def test_market_code_index_excludes_unsupported_prefixes(monkeypatch):
    """北交所等代码 baostock 不支持，搜出来也同步不了，不该出现在可选列表里。"""
    snap = pd.DataFrame(
        [
            {"code": "600036", "name": "招商银行"},
            {"code": "830799", "name": "艾融软件"},
            {"code": "872925", "name": "北交所股"},
            {"code": "400001", "name": "老三板"},
        ]
    )
    monkeypatch.setattr(snapshot, "market_snapshot_cached", lambda: snap)

    index = snapshot.market_code_index()

    assert list(index["code"]) == ["600036"]


def test_market_code_index_drops_rows_without_name(monkeypatch):
    snap = pd.DataFrame([{"code": "600036", "name": "招商银行"}, {"code": "600037", "name": None}])
    monkeypatch.setattr(snapshot, "market_snapshot_cached", lambda: snap)

    index = snapshot.market_code_index()

    assert list(index["code"]) == ["600036"]


def test_market_code_index_columns_are_code_and_name(monkeypatch):
    snap = pd.DataFrame([{"code": "600036", "name": "招商银行", "pe_ttm": 5.0}])
    monkeypatch.setattr(snapshot, "market_snapshot_cached", lambda: snap)

    assert list(snapshot.market_code_index().columns) == ["code", "name"]


def test_snapshot_cache_state_false_when_empty():
    snapshot._SNAPSHOT_CACHE = None
    assert snapshot.snapshot_cache_state() is False