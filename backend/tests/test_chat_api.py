import pytest
from fastapi.testclient import TestClient

from app.api import main
from app.api.main import app
from app.data.storage import get_conn


@pytest.fixture
def client(tmp_path, monkeypatch):
    db = tmp_path / "test.sqlite"
    monkeypatch.setattr(main, "get_conn", lambda: get_conn(db))
    return TestClient(app)


def _payload() -> dict:
    return {"code": "300456", "messages": [{"role": "user", "content": "这只股票最近怎么样？"}]}


def test_chat_no_key_503(client, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(main, "GLM_API_KEY", "")
    resp = client.post("/api/chat", json=_payload())
    assert resp.status_code == 503


def test_chat_no_quotes_404(client, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(main, "GLM_API_KEY", "test-key")

    def missing(code: str) -> str:
        raise ValueError(f"no quotes for {code}")

    monkeypatch.setattr(main, "build_context", missing)
    resp = client.post("/api/chat", json=_payload())
    assert resp.status_code == 404


def test_chat_streams_200(client, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(main, "GLM_API_KEY", "test-key")
    monkeypatch.setattr(main, "build_context", lambda code: "## 行情摘要（300456）")
    monkeypatch.setattr(
        main, "stream_chat", lambda messages, api_key=None: iter(["数字", "解读。"])
    )
    resp = client.post("/api/chat", json=_payload())
    assert resp.status_code == 200
    assert resp.text == "数字解读。"
    assert resp.headers["content-type"].startswith("text/plain")


def test_chat_persists_turn(client, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(main, "GLM_API_KEY", "test-key")
    monkeypatch.setattr(main, "build_context", lambda code: "ctx")
    monkeypatch.setattr(
        main, "stream_chat", lambda messages, api_key=None: iter(["答", "案"])
    )
    resp = client.post("/api/chat", json=_payload())
    assert resp.text == "答案"

    conn = main.get_conn()
    try:
        msgs = main.read_chat_messages(conn, "300456")
    finally:
        conn.close()
    assert [(m["role"], m["content"]) for m in msgs] == [
        ("user", "这只股票最近怎么样？"),
        ("assistant", "答案"),
    ]


def test_chat_history_only_stores_last_user(client, monkeypatch: pytest.MonkeyPatch):
    """客户端第二轮传全量历史，只应新增本轮的 user+assistant，不重复存旧轮。"""
    monkeypatch.setattr(main, "GLM_API_KEY", "test-key")
    monkeypatch.setattr(main, "build_context", lambda code: "ctx")
    monkeypatch.setattr(main, "stream_chat", lambda messages, api_key=None: iter(["r1"]))
    client.post(
        "/api/chat",
        json={"code": "300456", "messages": [{"role": "user", "content": "第一问"}]},
    )
    monkeypatch.setattr(main, "stream_chat", lambda messages, api_key=None: iter(["r2"]))
    client.post(
        "/api/chat",
        json={
            "code": "300456",
            "messages": [
                {"role": "user", "content": "第一问"},
                {"role": "assistant", "content": "r1"},
                {"role": "user", "content": "第二问"},
            ],
        },
    )
    conn = main.get_conn()
    try:
        msgs = main.read_chat_messages(conn, "300456")
    finally:
        conn.close()
    assert [(m["role"], m["content"]) for m in msgs] == [
        ("user", "第一问"),
        ("assistant", "r1"),
        ("user", "第二问"),
        ("assistant", "r2"),
    ]


def test_chat_history_endpoint(client, monkeypatch: pytest.MonkeyPatch):
    conn = main.get_conn()
    try:
        main.append_chat_messages(
            conn, "000001", [{"role": "user", "content": "早前的提问"}]
        )
    finally:
        conn.close()
    resp = client.get("/api/chat/000001/history")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["role"] == "user"
    assert data[0]["content"] == "早前的提问"
    assert data[0]["created_at"]

    empty = client.get("/api/chat/999999/history")
    assert empty.status_code == 200
    assert empty.json() == []
