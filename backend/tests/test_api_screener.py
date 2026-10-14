import types

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.api import main as main_mod
from app.data.storage import get_conn, read_watchlist, upsert_stocks
from app.screener import run as run_mod
from app.screener import score as screener_score


@pytest.fixture
def client(tmp_path, monkeypatch):
    db = tmp_path / "test.sqlite"
    monkeypatch.setattr(main_mod, "get_conn", lambda: get_conn(db))
    return TestClient(main_mod.app)


@pytest.fixture
def fake_market(monkeypatch):
    """全市场快照/业绩/财务三张表。列的归属必须与真实接口一致，否则 merge 会产生 _x/_y 后缀。"""
    snap = pd.DataFrame(
        [
            {"code": "000001", "name": "平安银行", "turnover": 3e9, "ltsz": 2e11, "pe_ttm": 5.0, "industry": "银行"},
            {"code": "000002", "name": "万科A", "turnover": 1e9, "ltsz": 1e11, "pe_ttm": 8.0, "industry": "房地产"},
            {"code": "000003", "name": "ST某某", "turnover": 1e9, "ltsz": 1e10, "pe_ttm": 9.0, "industry": "综合"},
            {"code": "600519", "name": "贵州茅台", "turnover": 5e9, "ltsz": 1e12, "pe_ttm": 25.0, "industry": "白酒"},
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
            {"code": "000001", "net_profit_yoy": 10.0, "roe": 9.0, "revenue_yoy": 1.0,
             "gross_margin": None, "cfps": 1.9},
            {"code": "000002", "net_profit_yoy": 30.0, "roe": 5.0, "revenue_yoy": -8.0,
             "gross_margin": 20.0, "cfps": 0.5},
            {"code": "000003", "net_profit_yoy": 50.0, "roe": 50.0, "revenue_yoy": 90.0,
             "gross_margin": 80.0, "cfps": 9.0},
            {"code": "600519", "net_profit_yoy": 20.0, "roe": 30.0, "revenue_yoy": 16.0,
             "gross_margin": 91.0, "cfps": 30.0},
        ]
    )
    fundamentals = pd.DataFrame(
        [
            {"code": "000001", "debt_ratio": 92.0, "net_margin": 28.0},
            {"code": "000002", "debt_ratio": 78.0, "net_margin": 4.0},
            {"code": "000003", "debt_ratio": 10.0, "net_margin": 60.0},
            {"code": "600519", "debt_ratio": 20.0, "net_margin": 50.0},
        ]
    )
    monkeypatch.setattr(run_mod.snapshot, "market_snapshot_cached", lambda: snap)
    monkeypatch.setattr(run_mod.snapshot, "fetch_listing_dates", lambda: listing)
    monkeypatch.setattr(run_mod.snapshot, "fetch_earnings_growth", lambda period: earnings)
    monkeypatch.setattr(run_mod.snapshot, "fetch_fundamentals", lambda period: fundamentals)
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

    monkeypatch.setattr(run_mod.snapshot, "market_snapshot_cached", _boom)

    resp = client.post("/api/screener/run", json={"conditions": [], "top": 10})

    assert resp.status_code == 502


def test_run_endpoint_survives_fundamentals_failure(client, fake_market, monkeypatch):
    """财务比率是两个可选维度，拉不到时只降级为缺列，不该让整个筛选 502。"""
    def _boom(period):
        raise RuntimeError("zcfz down")

    monkeypatch.setattr(run_mod.snapshot, "fetch_fundamentals", _boom)

    resp = client.post("/api/screener/run", json={"conditions": [], "top": 10})

    assert resp.status_code == 200
    assert resp.json()["fundamentals_ready"] is False
    assert "debt_ratio" not in resp.json()["columns"]


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


def test_score_endpoint_returns_ranked_rows_without_st(client, fake_market):
    resp = client.get("/api/screener/score", params={"top": 10})

    assert resp.status_code == 200
    body = resp.json()
    codes = [r["code"] for r in body["rows"]]
    assert "000003" not in codes
    assert body["rows"][0]["code"] == "600519"
    assert body["rows"][0]["rank"] == 1
    assert body["universe_size"] == 3
    assert body["fundamentals_ready"] is True
    assert set(body["factors"]) == set(screener_score.default_weights())
    assert "pct_debt_ratio" in body["columns"]
    assert all(0 <= r["score"] <= 100 for r in body["rows"])


def test_score_endpoint_respects_top(client, fake_market):
    resp = client.get("/api/screener/score", params={"top": 1})

    assert len(resp.json()["rows"]) == 1


def test_score_endpoint_rejects_out_of_range_top(client, fake_market):
    assert client.get("/api/screener/score", params={"top": 0}).status_code == 422
    assert client.get("/api/screener/score", params={"top": 501}).status_code == 422


def test_score_endpoint_snapshot_failure_returns_502(client, monkeypatch):
    def _boom():
        raise RuntimeError("snapshot down")

    monkeypatch.setattr(run_mod.snapshot, "market_snapshot_cached", _boom)

    assert client.get("/api/screener/score").status_code == 502


def test_score_endpoint_still_works_without_fundamentals(client, fake_market, monkeypatch):
    def _boom(period):
        raise RuntimeError("zcfz down")

    monkeypatch.setattr(run_mod.snapshot, "fetch_fundamentals", _boom)

    resp = client.get("/api/screener/score")

    body = resp.json()
    assert body["fundamentals_ready"] is False
    assert "debt_ratio" not in body["factors"]
    assert "net_margin" not in body["factors"]
    assert body["rows"]


@pytest.fixture
def fake_index(monkeypatch):
    """全市场代码表（含从未同步过的票），供搜索与名称解析。"""
    index = pd.DataFrame(
        [
            {"code": "600036", "name": "招商银行"},
            {"code": "600519", "name": "贵州茅台"},
            {"code": "000001", "name": "平安银行"},
        ]
    )
    monkeypatch.setattr(main_mod, "market_code_index", lambda: index)
    return index


def test_stock_search_matches_by_code_and_name(client, fake_index):
    by_code = client.get("/api/stocks/search", params={"q": "60003"})
    assert by_code.status_code == 200
    assert [r["code"] for r in by_code.json()] == ["600036"]

    by_name = client.get("/api/stocks/search", params={"q": "茅台"})
    assert [r["code"] for r in by_name.json()] == ["600519"]


def test_stock_search_requires_query(client, fake_index):
    assert client.get("/api/stocks/search", params={"q": ""}).status_code == 422


def test_stock_search_returns_502_when_snapshot_unavailable(client, monkeypatch):
    def _boom():
        raise RuntimeError("行情快照拉取失败")

    monkeypatch.setattr(main_mod, "market_code_index", _boom)

    resp = client.get("/api/stocks/search", params={"q": "600"})

    assert resp.status_code == 502


def test_stock_search_limits_results(client, monkeypatch):
    index = pd.DataFrame([{"code": f"60000{i}", "name": f"股票{i}"} for i in range(30)])
    monkeypatch.setattr(main_mod, "market_code_index", lambda: index)

    resp = client.get("/api/stocks/search", params={"q": "股票"})

    assert len(resp.json()) == 20


def test_favorites_add_resolves_name_for_never_synced_code(client, fake_index):
    """代码不在 stocks 表（从未同步过）时，名称应从全市场代码表解析，否则加自选会被静默丢弃。"""
    resp = client.post("/api/favorites", json={"codes": ["600036"]})

    assert resp.json()["added"] == 1
    assert client.get("/api/favorites").json()[0]["name"] == "招商银行"


def test_sync_status_endpoint_reports_job_state(client, monkeypatch):
    monkeypatch.setattr(main_mod.sync_job, "get_status", lambda: {"running": False, "total": 0, "done": 0})

    resp = client.get("/api/sync/status")

    assert resp.status_code == 200
    assert resp.json()["running"] is False

def test_startup_sync_starts_display_pool_only_daily(client, monkeypatch):
    """启动同步范围=自选∪池子、只补日线，且过滤 baostock 不支持的市场。"""
    started: dict = {}

    def _fake_start(codes, skip_financials=False):
        started["codes"] = list(codes)
        started["skip_financials"] = skip_financials
        return "job-startup"

    monkeypatch.setattr(main_mod.sync_job, "start", _fake_start)
    conn = main_mod.get_conn()
    conn.execute(
        "INSERT INTO watchlist(code, name, score, rank, selected_at) VALUES('600519','贵州茅台',0.0,1,'2026-10-13')"
    )
    conn.execute(
        "INSERT INTO watchlist(code, name, score, rank, selected_at) VALUES('830799','北交所股',0.0,2,'2026-10-13')"
    )
    conn.execute("INSERT INTO favorites(code, name, added_at) VALUES('000001','平安银行','2026-10-13')")
    conn.commit()
    conn.close()

    job_id = main_mod.startup_daily_sync()

    assert job_id == "job-startup"
    assert started["codes"] == ["000001", "600519"]
    assert started["skip_financials"] is True


def test_startup_sync_skips_when_display_pool_empty(client, monkeypatch):
    monkeypatch.setattr(
        main_mod.sync_job, "start", lambda *args, **kwargs: pytest.fail("空展示池不应启动同步")
    )

    assert main_mod.startup_daily_sync() is None


def test_startup_sync_skips_when_job_busy(client, monkeypatch):
    conn = main_mod.get_conn()
    conn.execute("INSERT INTO favorites(code, name, added_at) VALUES('000001','平安银行','2026-10-13')")
    conn.commit()
    conn.close()

    def _busy(codes, skip_financials=False):
        raise main_mod.sync_job.SyncBusyError("已有同步任务在运行")

    monkeypatch.setattr(main_mod.sync_job, "start", _busy)

    assert main_mod.startup_daily_sync() is None
