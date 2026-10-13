import json

import httpx
import pytest

from app.assistant import llm
from app.assistant.llm import LLMError, _parse_sse, stream_chat


def sse_lines(*chunks: str) -> list[str]:
    lines = [f"data: {json.dumps({'choices': [{'delta': {'content': c}}]})}" for c in chunks]
    lines.append("data: [DONE]")
    return lines


def test_parse_sse_yields_content_and_stops_at_done():
    raw = sse_lines("你好", "，", "世界")
    assert list(_parse_sse(raw)) == ["你好", "，", "世界"]


def test_stream_chat_success_via_mock_transport(monkeypatch: pytest.MonkeyPatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="\n".join(sse_lines("A", "B")))

    monkeypatch.setattr(
        llm, "_client", lambda: httpx.Client(transport=httpx.MockTransport(handler))
    )
    assert "".join(stream_chat([{"role": "user", "content": "hi"}], "key")) == "AB"


def test_stream_chat_empty_key_raises():
    with pytest.raises(LLMError):
        list(stream_chat([{"role": "user", "content": "hi"}], ""))
