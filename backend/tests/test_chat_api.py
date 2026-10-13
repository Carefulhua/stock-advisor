import pytest
from fastapi.testclient import TestClient

from app.api import main
from app.api.main import app

client = TestClient(app)


def _payload() -> dict:
    return {"code": "300456", "messages": [{"role": "user", "content": "这只股票最近怎么样？"}]}


def test_chat_no_key_503(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(main, "GLM_API_KEY", "")
    resp = client.post("/api/chat", json=_payload())
    assert resp.status_code == 503


def test_chat_no_quotes_404(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(main, "GLM_API_KEY", "test-key")

    def missing(code: str) -> str:
        raise ValueError(f"no quotes for {code}")

    monkeypatch.setattr(main, "build_context", missing)
    resp = client.post("/api/chat", json=_payload())
    assert resp.status_code == 404


def test_chat_streams_200(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(main, "GLM_API_KEY", "test-key")
    monkeypatch.setattr(main, "build_context", lambda code: "## 行情摘要（300456）")
    monkeypatch.setattr(
        main, "stream_chat", lambda messages, api_key=None: iter(["数字", "解读。"])
    )
    resp = client.post("/api/chat", json=_payload())
    assert resp.status_code == 200
    assert resp.text == "数字解读。"
    assert resp.headers["content-type"].startswith("text/plain")
