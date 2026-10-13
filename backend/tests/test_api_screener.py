import types

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.api import main as main_mod
from app.data.storage import get_conn, read_watchlist, upsert_stocks


@pytest.fixture
def client(tmp_path, monkeypatch):
    db = tmp_path / "test.sqlite"
    monkeypatch.setattr(main_mod, "get_conn", lambda: get_conn(db))
    return TestClient(main_mod.app)


@pytest.fixture
def fake_market(monkeypatch):
    snap = pd.DataFrame(
        [
            {"code": "000001", "name": "平安银行", "turnover": 3e9, "ltsz": 2e11, "pe_ttm": 5.0,
             "industry": "银行"},
            {"code": "000002", "name": "万科A", "turnover": 1e9, "ltsz": 1e11, "pe_ttm": 8.0,
             "industry": "房地产"},
            {"code": "000003", "name": "ST某某", "turnover": 1e9, "ltsz": 1e10, "pe_ttm": 9.0,
             "industry": "综合"},
            {"code": "600519", "name": "贵州茅台", "turnover": 5e9, "ltsz": 1e12, "pe_ttm": 25.0,
             "industry": "白酒"},
        ]
    )
    listing = pd.DataFrame(
        [
            {"code": "000001", "list_date": pd.Timestamp("1991-04-03")},
            {"code": "000002", "list_date": pd.Timestamp("1991-01-29")},
            {"code": "000003", "list_date": pd.Timestamp("1991-01-01")},
            {"code": "600519", "list_date": pd.Timestamp("2001-08-27")},
        ]
    )
    earnings = pd.DataFrame(
        [
            {"code": "000001", "net_profit_yoy": 10.0},
            {"code": "000002", "net_profit_yoy": 30.0},
            {"code": "000003", "net_profit_yoy": 50.0},
            {"code": "600519", "net_profit_yoy": 20.0},
        ]
    )
    monkeypatch.setattr(main_mod, "market_snapshot_cached", lambda: snap)
    monkeypatch.setattr(main_mod, "fetch_listing_dates", lambda: listing)
    monkeypatch.setattr(main_mod, "fetch_earnings_growth", lambda period: earnings)
    return snap


@pytest.fixture
def record_sync_jobs(monkeypatch):
    """拦截后台同步任务，只记录调用，避免真实拉数据。"""
    calls: list[list[str]] = []

    def _fake_start(codes, skip_financials=False):
        calls.append(list(codes))
        return f"job-{len(calls)}"

    monkeypatch.setattr(main_mod.sync_job, "start", _fake_start)
    return types.SimpleNamespace(calls=calls)


@pytest.fixture
def seed_stocks(client):
    """把候选股票写入 stocks 表：favorites/apply 的 name 由此解析。"""
    stocks = pd.DataFrame(
        [
            {"code": "000001", "name": "平安银行"},
            {"code": "000002", "name": "万科A"},
            {"code": "000003", "name": "ST某某"},
            {"code": "600519", "name": "贵州茅台"},
        ]
    )
    conn = main_mod.get_conn()
    try:
        upsert_stocks(conn, stocks)
    finally:
        conn.close()
    return stocks


def test_fields_endpoint_lists_catalog(client):
    resp = client.get("/api/screener/fields")

    assert resp.status_code == 200
    fields = resp.json()
    assert len(fields) >= 19
    assert any(f["field"] == "pe_ttm" for f in fields)
    assert any(f["field"] == "industry" for f in fields)


def test_status_endpoint_reports_llm_and_cache(client, monkeypatch):
    monkeypatch.setattr(main_mod, "GLM_API_KEY", "")
    monkeypatch.setattr(main_mod, "snapshot_cache_state", lambda: False)

    resp = client.get("/api/screener/status")

    assert resp.status_code == 200
    assert resp.json() == {"llm_enabled": False, "snapshot_cached": False}


def test_parse_endpoint_without_key_returns_503(client, monkeypatch):
    monkeypatch.setattr(main_mod, "GLM_API_KEY", "")

    resp = client.post("/api/screener/parse", json={"query": "市盈率低的"})

    assert resp.status_code == 503


def test_parse_endpoint_returns_conditions(client, monkeypatch):
    monkeypatch.setattr(main_mod, "GLM_API_KEY", "k")

    def _fake_parse(query, api_key=None):
        from app.screener.conditions import FilterSpec

        return FilterSpec.model_validate(
            {"conditions": [{"field": "pe_ttm", "op": "lte", "value": 20}], "top": 50}
        )

    monkeypatch.setattr(main_mod, "parse_query", _fake_parse)

    resp = client.post("/api/screener/parse", json={"query": "市盈率低的"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["top"] == 50
    assert body["conditions"][0]["field"] == "pe_ttm"


def test_parse_endpoint_llm_failure_returns_502(client, monkeypatch):
    from app.screener.parse import ParseError

    monkeypatch.setattr(main_mod, "GLM_API_KEY", "k")

    def _fake_parse(query, api_key=None):
        raise ParseError("llm", "上游失败")

    monkeypatch.setattr(main_mod, "parse_query", _fake_parse)

    resp = client.post("/api/screener/parse", json={"query": "市盈率低的"})

    assert resp.status_code == 502


def test_parse_endpoint_schema_failure_returns_422(client, monkeypatch):
    from app.screener.parse import ParseError

    monkeypatch.setattr(main_mod, "GLM_API_KEY", "k")

    def _fake_parse(query, api_key=None):
        raise ParseError("schema", "字段不合法")

    monkeypatch.setattr(main_mod, "parse_query", _fake_parse)

    resp = client.post("/api/screener/parse", json={"query": "市盈率低的"})

    assert resp.status_code == 422


def test_run_endpoint_returns_rows_and_diff(client, fake_market, monkeypatch):
    monkeypatch.setattr(main_mod, "GLM_API_KEY", "")
    monkeypatch.setattr(main_mod, "snapshot_cache_state", lambda: True)

    conn = main_mod.get_conn()
    try:
        conn.execute(
            "INSERT INTO watchlist(code, name, score, rank, selected_at) VALUES(?,?,?,?,?)",
            ("000001", "平安银行", 50.0, 1, "2026-10-12"),
        )
        conn.execute(
            "INSERT INTO favorites(code, name, added_at) VALUES(?,?,?)",
            ("600519", "贵州茅台", "2026-10-13"),
        )
        conn.commit()
    finally:
        conn.close()

    resp = client.post(
        "/api/screener/run",
        json={"conditions": [{"field": "pe_ttm", "op": "lte", "value": 10}],
              "sort_by": "net_profit_yoy", "top": 10},
    )

    assert resp.status_code == 200
    body = resp.json()
    codes = [r["code"] for r in body["rows"]]
    assert "000001" in codes and "000002" in codes
    assert "000003" not in codes  # ST 恒剔除
    assert "600519" in codes  # 自选强制保留（不满足 pe_ttm<=10）
    assert body["kept_favorites"] == ["600519"]
    assert body["next_in"] == ["000002"]
    assert body["next_out"] == []
    assert body["cached"] is True
    assert body["elapsed_sec"] >= 0


def test_run_endpoint_snapshot_failure_returns_502(client, monkeypatch):
    def _boom():
        raise RuntimeError("snapshot down")

    monkeypatch.setattr(main_mod, "market_snapshot_cached", _boom)

    resp = client.post("/api/screener/run", json={"conditions": [], "top": 10})

    assert resp.status_code == 502


def test_run_endpoint_invalid_condition_returns_422(client, fake_market):
    resp = client.post(
        "/api/screener/run",
        json={"conditions": [{"field": "pe_ttm", "op": "neq", "value": 3}]},
    )

    assert resp.status_code == 422


def test_apply_endpoint_writes_watchlist_and_starts_sync(client, seed_stocks, fake_market, monkeypatch):
    started: dict = {}

    def _fake_start(codes, skip_financials=False):
        started["codes"] = codes
        return "job-123"

    monkeypatch.setattr(main_mod.sync_job, "start", _fake_start)

    resp = client.post("/api/screener/apply", json={"codes": ["000001", "000002"]})

    assert resp.status_code == 200
    body = resp.json()
    assert body["applied"] == 2
    assert body["sync_job_id"] == "job-123"
    assert started["codes"] == ["000001", "000002"]

    conn = main_mod.get_conn()
    try:
        pool = read_watchlist(conn)
    finally:
        conn.close()
    assert pool["code"].tolist() == ["000001", "000002"]
    assert pool["name"].tolist() == ["平安银行", "万科A"]
    assert pool["rank"].tolist() == [1, 2]


def test_apply_endpoint_empty_codes_returns_422(client):
    resp = client.post("/api/screener/apply", json={"codes": []})

    assert resp.status_code == 422


def test_apply_endpoint_when_sync_busy_returns_409(client, seed_stocks, monkeypatch):
    from app.screener.sync_job import SyncBusyError

    def _busy(codes, skip_financials=False):
        raise SyncBusyError("busy")

    monkeypatch.setattr(main_mod.sync_job, "start", _busy)

    resp = client.post("/api/screener/apply", json={"codes": ["000001"]})

    assert resp.status_code == 409


def test_favorites_crud_roundtrip(client, seed_stocks, record_sync_jobs):
    empty = client.get("/api/favorites")
    assert empty.status_code == 200
    assert empty.json() == []

    added = client.post("/api/favorites", json={"codes": ["000001"]})
    assert added.status_code == 200
    assert added.json() == {"added": 1, "skipped": 0, "sync_job_id": "job-1"}
    assert record_sync_jobs.calls == [["000001"]]

    again = client.post("/api/favorites", json={"codes": ["000001"]})
    assert again.json()["added"] == 0
    assert again.json()["skipped"] == 1
    assert record_sync_jobs.calls == [["000001"]]

    unknown = client.post("/api/favorites", json={"codes": ["999999"]})
    assert unknown.json()["added"] == 0
    assert unknown.json()["skipped"] == 1

    listed = client.get("/api/favorites").json()
    assert listed[0]["code"] == "000001"
    assert listed[0]["name"] == "平安银行"

    deleted = client.delete("/api/favorites/000001")
    assert deleted.status_code == 200
    assert deleted.json() == {"deleted": True}

    assert client.delete("/api/favorites/000001").json() == {"deleted": False}


def test_favorites_add_only_syncs_newly_added_codes(client, seed_stocks, record_sync_jobs):
    client.post("/api/favorites", json={"codes": ["000001"]})

    resp = client.post("/api/favorites", json={"codes": ["000001", "000002"]})

    assert resp.json() == {"added": 1, "skipped": 1, "sync_job_id": "job-2"}
    assert record_sync_jobs.calls == [["000001"], ["000002"]]


def test_favorites_add_conflicts_when_sync_running(client, seed_stocks, monkeypatch):
    def _busy(codes, skip_financials=False):
        raise main_mod.sync_job.SyncBusyError("已有同步任务在运行")

    monkeypatch.setattr(main_mod.sync_job, "start", _busy)

    resp = client.post("/api/favorites", json={"codes": ["000001"]})

    assert resp.status_code == 409


def test_watchlist_merges_favorites_first(client, seed_stocks):
    conn = main_mod.get_conn()
    conn.execute(
        "INSERT INTO watchlist(code, name, score, rank, selected_at) VALUES('000002','万科A',0.0,1,'2026-10-13')"
    )
    conn.execute(
        "INSERT INTO watchlist(code, name, score, rank, selected_at) VALUES('000003','ST某某',0.0,2,'2026-10-13')"
    )
    conn.execute(
        "INSERT INTO favorites(code, name, added_at) VALUES('600519','贵州茅台','2026-10-13')"
    )
    conn.commit()
    conn.close()

    rows = client.get("/api/watchlist").json()

    assert [r["code"] for r in rows] == ["600519", "000002", "000003"]
    assert [r["is_favorite"] for r in rows] == [True, False, False]


def test_watchlist_does_not_duplicate_codes_in_both_tables(client, seed_stocks):
    conn = main_mod.get_conn()
    conn.execute(
        "INSERT INTO watchlist(code, name, score, rank, selected_at) VALUES('600519','贵州茅台',0.0,1,'2026-10-13')"
    )
    conn.execute(
        "INSERT INTO favorites(code, name, added_at) VALUES('600519','贵州茅台','2026-10-13')"
    )
    conn.commit()
    conn.close()

    rows = client.get("/api/watchlist").json()

    assert [r["code"] for r in rows] == ["600519"]
    assert rows[0]["is_favorite"] is True


def test_sync_status_endpoint_reports_job_state(client, monkeypatch):
    monkeypatch.setattr(main_mod.sync_job, "get_status", lambda: {"running": False, "total": 0, "done": 0})

    resp = client.get("/api/sync/status")

    assert resp.status_code == 200
    assert resp.json()["running"] is False