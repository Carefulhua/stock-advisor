import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.api import main as main_mod
from app.assistant import gates, report as report_mod
from app.data.storage import get_conn, read_report, upsert_stocks

CONTEXT = """## 行情摘要（600418，近20个交易日）
区间涨跌幅: 12.36%
日均成交额: 3273000000元（约32.73亿元）
## 财务摘要
净资产收益率(%): -6.03
资产负债率(%): 72.4526
每股收益(元): 1.3241
## 资金面
主力成本 21.73元  龙虎榜净买额 4.03亿元  成交额合计 400.35万元
## 事件面
预计值 -7.40亿元  变动幅度 +4.25%
"""

GOOD_REPORT = """# 江淮汽车（600418）研究报告

## 一、投资要点
近20个交易日区间涨跌幅 12.36%，日均成交额 32.73亿元。

## 二、技术与量价
均线排列与 MACD、RSI14、KDJ 区间见上下文。

## 三、量能与资金面
主力成本 21.73元，龙虎榜净买额 4.03亿元，大宗交易成交额合计 400.35万元。
区间日均成交额 32.73亿元，主力成本 21.73元，龙虎榜净买额 4.03亿元。

## 四、财务分析与业绩预告
净资产收益率 -6.03%，资产负债率 72.45%，每股收益 1.32元。
业绩预告预计值 -7.40亿元，变动幅度 +4.25%。

## 五、风险提示
- 资产负债率 72.45% 偏高，需跟踪偿债压力。

## 六、结论
基本面仍处修复初期，可跟踪预告准确性、资金持续性、量能比值三个信号。
"""


def _pad(text: str, target: int) -> str:
    filler = "\n".join("补充说明文字" for _ in range(max(0, target - len(text) // 2)))
    return text + "\n" + filler


@pytest.fixture
def client(tmp_path, monkeypatch):
    db = tmp_path / "test.sqlite"
    monkeypatch.setattr(main_mod, "get_conn", lambda: get_conn(db))
    return TestClient(main_mod.app), db


@pytest.fixture
def ready(monkeypatch):
    """LLM 已配置，stocks 表有 600418，可省去 build_context 的真实取数。"""
    monkeypatch.setattr(main_mod, "GLM_API_KEY", "test-key")
    monkeypatch.setattr(main_mod, "build_context", lambda code: CONTEXT)
    monkeypatch.setattr(main_mod, "complete_chat", lambda *a, **k: _pad(GOOD_REPORT, 1000))
    return CONTEXT


def test_generate_persists_and_returns_report(client, ready):
    http, db = client
    resp = http.post("/api/report/600418/generate")
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == "600418"
    assert "## 六、结论" in body["content"]

    stored = read_report(get_conn(db), "600418")
    assert stored is not None
    assert stored["code"] == "600418"


def test_generate_rejects_report_failing_gates(client, monkeypatch):
    monkeypatch.setattr(main_mod, "GLM_API_KEY", "test-key")
    monkeypatch.setattr(main_mod, "build_context", lambda code: CONTEXT)
    monkeypatch.setattr(main_mod, "complete_chat", lambda *a, **k: "## 一、投资要点\n编造 99.99%")

    resp = client[0].post("/api/report/600418/generate")
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert "99.99" in detail
    assert "章节" in detail or "过薄" in detail


def test_generate_rejects_thin_report(client, monkeypatch):
    monkeypatch.setattr(main_mod, "GLM_API_KEY", "test-key")
    monkeypatch.setattr(main_mod, "build_context", lambda code: CONTEXT)
    monkeypatch.setattr(main_mod, "complete_chat", lambda *a, **k: "## 一、投资要点\n太短")

    resp = client[0].post("/api/report/600418/generate")
    assert resp.status_code == 422
    assert "过薄" in resp.json()["detail"]


def test_generate_preserves_interpretation_log(client, monkeypatch):
    monkeypatch.setattr(main_mod, "GLM_API_KEY", "test-key")
    monkeypatch.setattr(main_mod, "build_context", lambda code: CONTEXT)
    monkeypatch.setattr(main_mod, "complete_chat", lambda *a, **k: _pad(GOOD_REPORT, 1000))

    client[0].post("/api/report/600418/generate")
    from app.data.storage import upsert_report

    conn = get_conn(client[1])
    with_report = read_report(conn, "600418")
    updated = report_mod.append_interpretation(
        with_report["content"], "MACD怎么看？", "MACD 是趋势指标。", "2026-10-15 10:00"
    )
    upsert_report(conn, "600418", with_report["name"], updated)
    conn.close()

    resp = client[0].post("/api/report/600418/generate")
    assert resp.status_code == 200
    assert report_mod.INTERPRETATION_HEADING in resp.json()["content"]
    assert "MACD怎么看？" in resp.json()["content"]


def test_generate_requires_api_key(client, monkeypatch):
    monkeypatch.setattr(main_mod, "GLM_API_KEY", "")
    resp = client[0].post("/api/report/600418/generate")
    assert resp.status_code == 503


def test_generate_without_quotes_returns_404(client, monkeypatch):
    monkeypatch.setattr(main_mod, "GLM_API_KEY", "test-key")

    def _missing(_code: str) -> str:
        raise ValueError("no quotes")

    monkeypatch.setattr(main_mod, "build_context", _missing)
    resp = client[0].post("/api/report/600418/generate")
    assert resp.status_code == 404


def test_generate_upstream_error_returns_502(client, monkeypatch):
    from app.assistant.llm import LLMError

    monkeypatch.setattr(main_mod, "GLM_API_KEY", "test-key")
    monkeypatch.setattr(main_mod, "build_context", lambda code: CONTEXT)

    def _boom(*_a, **_k) -> str:
        raise LLMError("upstream 500")

    monkeypatch.setattr(main_mod, "complete_chat", _boom)
    resp = client[0].post("/api/report/600418/generate")
    assert resp.status_code == 502


def test_validate_report_is_pure():
    """门禁不得修改输入，也不得依赖调用顺序。"""
    content = _pad(GOOD_REPORT, 1000)
    first = gates.validate_report(content, CONTEXT)
    second = gates.validate_report(content, CONTEXT)
    assert first == second == []
    assert content == _pad(GOOD_REPORT, 1000)


def test_reports_list_and_read(client, monkeypatch):
    monkeypatch.setattr(main_mod, "GLM_API_KEY", "test-key")
    monkeypatch.setattr(main_mod, "build_context", lambda code: CONTEXT)
    monkeypatch.setattr(main_mod, "complete_chat", lambda *a, **k: _pad(GOOD_REPORT, 1000))
    http, db = client
    upsert_stocks(get_conn(db), pd.DataFrame([{"code": "600418", "name": "江淮汽车"}]))

    http.post("/api/report/600418/generate")
    listing = http.get("/api/reports")
    assert listing.status_code == 200
    assert listing.json()[0]["code"] == "600418"

    detail = http.get("/api/report/600418")
    assert detail.status_code == 200
    assert "## 六、结论" in detail.json()["content"]


def test_read_missing_report_returns_404(client):
    resp = client[0].get("/api/report/999999")
    assert resp.status_code == 404
