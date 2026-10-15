from datetime import date, datetime

import pandas as pd

from app.data import storage
from app.screener import run as screener_run, snapshot


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


def test_latest_report_period_boundaries():
    assert screener_run.latest_report_period(date(2026, 4, 30)) == "20251231"
    assert screener_run.latest_report_period(date(2026, 5, 1)) == "20260331"
    assert screener_run.latest_report_period(date(2026, 8, 31)) == "20260331"
    assert screener_run.latest_report_period(date(2026, 9, 1)) == "20260630"
    assert screener_run.latest_report_period(date(2026, 10, 31)) == "20260630"
    assert screener_run.latest_report_period(date(2026, 11, 1)) == "20260930"
    assert screener_run.latest_report_period(date(2026, 10, 12)) == "20260630"