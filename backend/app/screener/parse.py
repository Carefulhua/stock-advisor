"""自然语言选股条件解析：LLM 只负责把中文条件翻译成声明式条件 JSON，判定仍由条件求值层完成。"""
from __future__ import annotations

import json
import re
from typing import Literal

from pydantic import ValidationError

from app.assistant.llm import LLMError, _stream_once
from app.core.config import GLM_API_KEY
from app.screener.conditions import FilterSpec
from app.screener.fields import catalog

ParseReason = Literal["llm", "json", "schema"]

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


class ParseError(Exception):
    """条件解析失败，reason 供前端区分提示文案。"""

    def __init__(self, reason: ParseReason, message: str = "") -> None:
        super().__init__(message or reason)
        self.reason = reason


def _prompt(query: str) -> str:
    return (
        "你是 A 股选股条件解析器。把用户的中文选股需求翻译成 JSON，"
        "只输出 JSON，不要解释，不要给买卖建议。\n"
        "JSON 结构：{\"conditions\": [{\"field\": 字段名, \"op\": 操作符, \"value\": 值}], "
        "\"sort_by\": 排序字段, \"top\": 数量}\n"
        f"可用字段目录：{json.dumps(catalog(), ensure_ascii=False)}\n"
        "规则：数值字段用 gte/gt/lte/lt/between（between 的 value 是两个数的数组）；"
        "行业字段用 in（value 是行业名数组）；上市日期用 gte/lte，value 形如 2020-01-01；"
        "sort_by 从数值字段中选，默认 net_profit_yoy；top 默认 100。\n"
        "单位换算（必须严格执行）：金额字段单位是元，「5亿」=500000000，「1.2万」=12000，"
        "「3000万」=30000000；不要把「亿」「万」原样填进 value。\n"
        f"用户需求：{query}"
    )


def _extract_json(text: str) -> str | None:
    fenced = _FENCE_RE.search(text)
    candidate = fenced.group(1) if fenced else text
    start = candidate.find("{")
    end = candidate.rfind("}")
    if start == -1 or end <= start:
        return None
    return candidate[start:end + 1]


def parse_query(query: str, api_key: str | None = None) -> FilterSpec:
    key = api_key if api_key is not None else GLM_API_KEY
    if not key:
        raise ParseError("llm", "服务端未配置 GLM_API_KEY")

    messages = [
        {"role": "system", "content": _prompt(query)},
        {"role": "user", "content": query},
    ]
    try:
        raw_text = "".join(_stream_once(messages, key))
    except LLMError as exc:
        raise ParseError("llm", str(exc)) from exc

    payload = _extract_json(raw_text)
    if payload is None:
        raise ParseError("json", "模型未返回 JSON")
    try:
        return FilterSpec.model_validate_json(payload)
    except ValidationError as exc:
        raise ParseError("schema", "条件字段或操作符不合法") from exc