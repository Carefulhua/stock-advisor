"""智谱 GLM 流式客户端：SSE 增量解析，首包失败重试 1 次。"""
from __future__ import annotations

import json
import time
from collections.abc import Iterable, Iterator

import httpx

from app.core.config import GLM_API_URL, GLM_MODEL, GLM_TIMEOUT_SEC


class LLMError(Exception):
    """上游 LLM 调用失败（无 key / 非 200 / 超时 / 响应不可解析）。"""


def _parse_sse(raw_lines: Iterable[str]) -> Iterator[str]:
    for line in raw_lines:
        line = line.strip()
        if not line.startswith("data:"):
            continue
        payload = line[len("data:"):].strip()
        if payload == "[DONE]":
            break
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            continue
        choices = data.get("choices") or []
        if not choices:
            continue
        delta = choices[0].get("delta") or {}
        content = delta.get("content")
        if content:
            yield content


_client_cache: httpx.Client | None = None


def _client() -> httpx.Client:
    # 模块级工厂：测试通过替换本函数注入 MockTransport
    global _client_cache
    if _client_cache is None:
        _client_cache = httpx.Client(timeout=GLM_TIMEOUT_SEC)
    return _client_cache


def _stream_once(messages: list[dict], api_key: str) -> Iterator[str]:
    payload = {"model": GLM_MODEL, "messages": messages, "stream": True, "temperature": 0.6}
    try:
        with _client().stream(
            "POST",
            GLM_API_URL,
            json=payload,
            headers={"Authorization": f"Bearer {api_key}"},
        ) as resp:
            if resp.status_code != 200:
                resp.read()
                raise LLMError(f"GLM HTTP {resp.status_code}")
            yield from _parse_sse(resp.iter_lines())
    except httpx.HTTPError as exc:
        raise LLMError(str(exc)) from exc


def stream_chat(messages: list[dict], api_key: str | None = None) -> Iterator[str]:
    key = api_key if api_key is not None else _default_key()
    if not key:
        raise LLMError("GLM_API_KEY not configured")

    emitted = False
    for attempt in range(2):
        try:
            for chunk in _stream_once(messages, key):
                emitted = True
                yield chunk
            return
        except LLMError:
            # 仅首包（尚未产出任何内容）失败重试 1 次；已产出后失败直接上抛，避免半截重复
            if emitted or attempt == 1:
                raise
            time.sleep(1.0)


def _default_key() -> str:
    from app.core import config

    return config.GLM_API_KEY


def complete_chat(messages: list[dict], api_key: str | None = None) -> str:
    """非流式对话：收集完整回复文本。

    研究报告是一次性整段产出（无需边收边渲染），故复用 stream_chat 收集后返回，
    不另写一套请求逻辑。
    """
    key = api_key if api_key is not None else _default_key()
    if not key:
        raise LLMError("GLM_API_KEY not configured")
    return "".join(stream_chat(messages, api_key=key))
