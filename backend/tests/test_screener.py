from datetime import datetime, date

import pandas as pd
import pytest

from app.data import storage
from app.screener import rules, snapshot


def test_replace_watchlist_replaces_and_orders(tmp_path):
    conn = storage.get_conn(tmp_path / "t.db")
    first = pd.DataFrame(
        {"code": ["600000", "000001"], "name": ["A", "B"], "score": [90.0, 80.0], "rank": [1, 2]}
    )
    assert storage.replace_watchlist(conn, first, selected_at=datetime(2026, 10, 12)) == 2
    second = pd.DataFrame({"code": ["300750"], "name": ["C"], "score": [95.0], "rank": [1]})
    assert storage.replace_watchlist(conn, second, selected_at=datetime(2026, 10, 12)) == 1

    got = storage.read_watchlist(conn)
    assert list(got["code"]) == ["300750"]
    assert got.iloc[0]["score"] == 95.0
    assert got.iloc[0]["rank"] == 1
    assert got.iloc[0]["selected_at"] == "2026-10-12T00:00:00"
    conn.close()


def _mk(code="600000", name="浦发银行", amount=2e9, pe=10.0, float_mv=1e11,
        list_date="2000-01-01", profit_yoy=20.0):
    return {
        "code": code, "name": name, "amount": amount, "pe": pe,
        "float_mv": float_mv, "list_date": pd.Timestamp(list_date),
        "profit_yoy": profit_yoy,
    }


def _df(*rows):
    return pd.DataFrame(list(rows))


AS_OF = date(2026, 10, 12)
FILTER_KW = dict(as_of=AS_OF, min_float_mv=50e8, min_amount=1e8, min_listing_years=1)


def test_hard_filter_drops_st():
    df = _df(_mk(code="600001", name="ST某某"), _mk(code="600000"))
    assert list(rules.apply_hard_filters(df, **FILTER_KW)["code"]) == ["600000"]


def test_hard_filter_drops_non_main_board():
    df = _df(_mk(code="830001"), _mk(code="000001"), _mk(code="300001"), _mk(code="600001"))
    got = rules.apply_hard_filters(df, **FILTER_KW)
    assert list(got["code"]) == ["000001", "300001", "600001"]


def test_hard_filter_drops_zero_amount_and_unlisted_date():
    df = _df(_mk(code="600001", amount=0.0), _mk(code="600002", list_date=pd.NaT))
    assert rules.apply_hard_filters(df, **FILTER_KW).empty


def test_hard_filter_drops_new_listing():
    df = _df(_mk(code="600001", list_date="2026-01-01"), _mk(code="600002", list_date="2020-01-01"))
    assert list(rules.apply_hard_filters(df, **FILTER_KW)["code"]) == ["600002"]


def test_hard_filter_liquidity_either_or():
    df = _df(
        _mk(code="600001", float_mv=1e11, amount=5e7),
        _mk(code="600002", float_mv=1e9, amount=2e8),
        _mk(code="600003", float_mv=1e9, amount=5e7),
    )
    got = rules.apply_hard_filters(df, **FILTER_KW)
    assert list(got["code"]) == ["600001", "600002"]


def test_score_amount_direction_and_pe_direction():
    df = _df(
        _mk(code="600001", amount=1e9, pe=5.0, profit_yoy=0.0),
        _mk(code="600002", amount=3e9, pe=20.0, profit_yoy=0.0),
    )
    by_amount = rules.score_stocks(df, weight_amount=1.0, weight_pe=0.0, weight_growth=0.0)
    s = {r["code"]: r["score"] for r in by_amount.to_dict("records")}
    assert s["600002"] > s["600001"]
    by_pe = rules.score_stocks(df, weight_amount=0.0, weight_pe=1.0, weight_growth=0.0)
    s = {r["code"]: r["score"] for r in by_pe.to_dict("records")}
    assert s["600001"] > s["600002"]


def test_score_negative_pe_and_nan_growth_give_zero():
    df = _df(_mk(code="600001", pe=-3.0, profit_yoy=float("nan")))
    got = rules.score_stocks(df, weight_amount=0.0, weight_pe=0.5, weight_growth=0.5)
    assert got.iloc[0]["score"] == 0.0


def test_select_top_orders_and_ranks():
    df = _df(
        _mk(code="600001", amount=1e9), _mk(code="600002", amount=3e9), _mk(code="600003", amount=2e9)
    )
    scored = rules.score_stocks(df, weight_amount=1.0, weight_pe=0.0, weight_growth=0.0)
    got = rules.select_top(scored, 2)
    assert list(got["code"]) == ["600002", "600003"]
    assert list(got["rank"]) == [1, 2]


def test_select_top_insufficient_raises():
    df = _df(_mk(code="600001"))
    with pytest.raises(ValueError, match="候选不足"):
        rules.select_top(df, 100)


def test_merge_snapshot_left_joins_on_code():
    snap = pd.DataFrame({
        "code": ["600000", "000001"],
        "name": ["浦发银行", "平安银行"],
        "amount": [2e9, 3e9],
        "pe": [10.0, 5.0],
        "float_mv": [1e11, 2e11],
    })
    listing = pd.DataFrame({
        "code": ["600000", "000001"],
        "list_date": [pd.Timestamp("1999-11-10"), pd.Timestamp("1991-04-03")],
    })
    earnings = pd.DataFrame({"code": ["600000"], "profit_yoy": [12.5]})

    got = snapshot.merge_snapshot(snap, listing, earnings)
    assert len(got) == 2
    row1 = got.loc[got["code"] == "000001"].iloc[0]
    assert pd.isna(row1["profit_yoy"])
    assert row1["list_date"] == pd.Timestamp("1991-04-03")


from app.screener import run as screener_run


class _P:
    min_float_mv = 50e8
    min_amount = 1e8
    min_listing_years = 1
    weight_amount = 0.3
    weight_pe = 0.3
    weight_growth = 0.4
    top = 2


def test_run_screening_end_to_end_synthetic():
    merged = _df(
        _mk(code="600001", name="甲", amount=5e9, pe=8.0, profit_yoy=30.0),
        _mk(code="600002", name="乙", amount=4e9, pe=6.0, profit_yoy=10.0),
        _mk(code="600003", name="丙", amount=3e9, pe=30.0, profit_yoy=-5.0),
        _mk(code="600004", name="ST丁", amount=9e9, pe=5.0, profit_yoy=99.0),
    )
    got = screener_run.run_screening(merged, _P, date(2026, 10, 12))
    assert list(got["code"]) == ["600001", "600002"]
    assert list(got["rank"]) == [1, 2]
    assert list(got.columns) == ["code", "name", "score", "rank"]


def test_latest_report_period_boundaries():
    assert screener_run._latest_report_period(date(2026, 4, 30)) == "20251231"
    assert screener_run._latest_report_period(date(2026, 5, 1)) == "20260331"
    assert screener_run._latest_report_period(date(2026, 8, 31)) == "20260331"
    assert screener_run._latest_report_period(date(2026, 9, 1)) == "20260630"
    assert screener_run._latest_report_period(date(2026, 10, 31)) == "20260630"
    assert screener_run._latest_report_period(date(2026, 11, 1)) == "20260930"
    assert screener_run._latest_report_period(date(2026, 10, 12)) == "20260630"
