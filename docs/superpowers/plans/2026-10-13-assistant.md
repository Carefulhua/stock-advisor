# P3 解读助手 (Assistant) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 P2 分析页侧边栏提供 AI 对话，对当前股票的行情/指标/财务做解读（LLM 只解释，数字全部来自计算层）。

**Architecture:** 后端 FastAPI 新增 `app/assistant/`（context.py 纯函数拼上下文 + llm.py httpx 直调智谱 SSE），`POST /api/chat` 以 StreamingResponse 逐 token 回传；前端 `ChatPanel.tsx` 侧边栏用 fetch ReadableStream 渲染打字机效果。spec: `docs/superpowers/specs/2026-10-13-assistant-design.md`。

**Tech Stack:** Python 3.12 / FastAPI / httpx / pandas；Next.js 14 + ECharts（已有）；智谱 GLM（glm-4-flash 默认）。

## Global Constraints

- 非 git 仓库：计划中所有「Commit」步骤替换为「运行全量 pytest 确认通过」
- 测试命令：项目根执行 `.venv/bin/python -m pytest backend/tests -v`（pytest pyproject pythonpath=["backend"]）
- 无 LSP（basedpyright 未装）：验证 = pytest + `npx tsc --noEmit` + 实际运行
- 注释仅限第3类必要（数据源约束/单位换算/公式/安全红线）
- 禁止 `as any` / `@ts-ignore` / `any` 类型 / 空 catch / eslint-disable
- 架构红线：LLM 不给买卖点、不预测目标价；所有数字只能来自注入的上下文；GLM_API_KEY 只存服务端 env
- 环境：Node 18.19.1 / Next 14.2.35 / Python 3.12 / 已装 fastapi uvicorn（httpx 随 Task 2 装）
- UI 文案中文；API base `NEXT_PUBLIC_API_BASE` 默认 `http://127.0.0.1:8000`

---

### Task 1: 上下文拼装（config + context.py + 纯函数测试）

**Files:**
- Modify: `backend/app/core/config.py`（文件末尾追加 LLM 配置段）
- Create: `backend/app/assistant/__init__.py`（空文件）
- Create: `backend/app/assistant/context.py`
- Test: `backend/tests/test_context.py`

**Interfaces:**
- Consumes: `app.data.storage.QUOTE_COLUMNS`（12列，date 为 Timestamp，amount 单位元）、`app.analysis.indicators.{moving_average,macd,rsi,kdj}`、`read_quotes(code)`（首参是 code 字符串）
- Produces:
  - `build_context_text(code: str, quotes: pd.DataFrame, financials: pd.DataFrame, watch: dict | None) -> str`（纯函数，quotes 为空抛 `ValueError`）
  - `build_context(code: str) -> str`（IO 包装，Task 3 调用）
  - `WATCH_HINT = "未入选当前自选池"`、`FINANCIAL_FIELDS: list[str]`
  - config 新增 `GLM_API_KEY: str`（env，默认""）、`GLM_MODEL: str`（env，默认"glm-4-flash"）、`GLM_API_URL: str`（常量）、`GLM_TIMEOUT_SEC = 60.0`、`CHAT_HISTORY_LIMIT = 20`

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/test_context.py`：

```python
import pandas as pd
import pytest

from app.assistant.context import WATCH_HINT, build_context_text
from app.data.storage import QUOTE_COLUMNS


def make_quotes(n: int = 60) -> pd.DataFrame:
    dates = pd.date_range("2026-07-01", periods=n, freq="B")
    rows = []
    for i, dt in enumerate(dates):
        c = 10.0 + i
        prev = c - 1 if i else c
        rows.append({
            "date": dt, "code": "300001", "open": c - 0.5, "close": c,
            "high": c + 1.0, "low": c - 1.0, "volume": 1_000_000 + i,
            "amount": 2e8, "amplitude": 2.0,
            "pct_chg": (c / prev - 1) * 100, "chg": c - prev, "turnover": 1.5,
        })
    return pd.DataFrame(rows, columns=QUOTE_COLUMNS)


def test_sections_recent20_interval_and_fallbacks():
    q = make_quotes(60)
    text = build_context_text("300001", q, pd.DataFrame(), None)
    assert "## 行情摘要" in text
    assert "## 技术指标" in text
    assert "## 财务摘要" in text
    assert "## 自选池" in text
    date_lines = [ln for ln in text.splitlines() if ln.startswith("2026-")]
    assert len(date_lines) == 20
    # recent20 首收盘=50, 末收盘=69 -> (69/50-1)*100 = 38.00%
    assert "38.00%" in text
    assert "日均成交额" in text and "亿元" in text
    assert "MA5=" in text and "RSI14=" in text and "MACD柱=" in text
    assert WATCH_HINT in text
    assert "财务数据未同步。" in text
    assert f"数据截至 {q.iloc[-1]['date'].strftime('%Y-%m-%d')}" in text


def test_financial_and_watch_present():
    q = make_quotes(60)
    fin = pd.DataFrame([{
        "日期": "2026-09-30 00:00:00",
        "净资产收益率(%)": 12.34,
        "销售毛利率(%)": 45.6,
    }])
    text = build_context_text("300001", q, fin, {"score": 71.37, "rank": 1})
    assert "净资产收益率(%): 12.34" in text
    assert "销售毛利率(%): 45.6" in text
    assert "财务数据截至 2026-09-30" in text
    assert "score=71.37" in text and "rank=1" in text
    assert WATCH_HINT not in text


def test_empty_quotes_raises():
    with pytest.raises(ValueError):
        build_context_text("000000", pd.DataFrame(columns=QUOTE_COLUMNS), pd.DataFrame(), None)
```

- [ ] **Step 2: 运行确认失败**

```bash
cd /home/jayden/stock-advisor && .venv/bin/python -m pytest backend/tests/test_context.py -v
```
Expected: FAIL（ModuleNotFoundError: app.assistant）

- [ ] **Step 3: config.py 末尾追加**

```python
# LLM（智谱 GLM）：key 只存服务端环境变量，禁止下发前端
GLM_API_KEY = os.environ.get("GLM_API_KEY", "")
GLM_MODEL = os.environ.get("GLM_MODEL", "glm-4-flash")
GLM_API_URL = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
GLM_TIMEOUT_SEC = 60.0
CHAT_HISTORY_LIMIT = 20
```

- [ ] **Step 4: 创建 `backend/app/assistant/__init__.py`**（空）与 `backend/app/assistant/context.py`**

```python
"""解读助手上下文：纯函数拼装（数字全部来自计算层，LLM 只读不产生）。"""
from __future__ import annotations

import pandas as pd

from app.analysis import indicators as ind
from app.data.storage import QUOTE_COLUMNS, get_conn, read_financials, read_quotes

FINANCIAL_FIELDS = [
    "净资产收益率(%)",
    "销售毛利率(%)",
    "销售净利率(%)",
    "净利润增长率(%)",
    "主营业务收入增长率(%)",
    "资产负债率(%)",
    "每股收益(元)",
    "总资产(元)",
]

WATCH_HINT = "未入选当前自选池"


def _fmt_date(value: object) -> str:
    return pd.Timestamp(value).strftime("%Y-%m-%d")


def build_context_text(
    code: str,
    quotes: pd.DataFrame,
    financials: pd.DataFrame,
    watch: dict | None,
) -> str:
    if quotes.empty:
        raise ValueError(f"no quotes for {code}")

    recent = quotes.tail(20)
    last = recent.iloc[-1]
    last_date = _fmt_date(last["date"])

    lines = [f"## 行情摘要（{code}，近20个交易日）", "日期 | 收盘 | 涨跌幅%"]
    for _, row in recent.iterrows():
        lines.append(
            f"{_fmt_date(row['date'])} | {row['close']} | {row['pct_chg']:.2f}"
        )
    interval_chg = (last["close"] / recent.iloc[0]["close"] - 1) * 100
    avg_amount = float(recent["amount"].mean())
    lines.append(
        f"区间涨跌幅: {interval_chg:.2f}%  区间最高: {recent['high'].max()}  "
        f"区间最低: {recent['low'].min()}  "
        f"日均成交额: {avg_amount:.0f}元（约{avg_amount / 1e8:.2f}亿元）"
    )

    close = quotes["close"]
    dif, dea, hist = ind.macd(close)
    k, d, j = ind.kdj(quotes["high"], quotes["low"], close)
    rsi14 = ind.rsi(close, 14)
    lines.append(f"## 技术指标（{last_date} 最新一根，基于全部日线计算）")
    lines.append(
        f"MA5={ind.moving_average(close, 5).iloc[-1]:.3f}  "
        f"MA10={ind.moving_average(close, 10).iloc[-1]:.3f}  "
        f"MA20={ind.moving_average(close, 20).iloc[-1]:.3f}  "
        f"MA60={ind.moving_average(close, 60).iloc[-1]:.3f}"
    )
    lines.append(
        f"DIF={dif.iloc[-1]:.4f}  DEA={dea.iloc[-1]:.4f}  MACD柱={hist.iloc[-1]:.4f}  "
        f"RSI14={rsi14.iloc[-1]:.2f}  K={k.iloc[-1]:.2f}  D={d.iloc[-1]:.2f}  J={j.iloc[-1]:.2f}"
    )

    lines.append("## 财务摘要")
    if financials.empty:
        lines.append("财务数据未同步。")
        fin_note = "未同步"
    else:
        fin_last = financials.iloc[-1]
        fin_note = str(fin_last.get("日期", "未知"))
        lines.append(f"财务数据截至: {fin_note}")
        for field in FINANCIAL_FIELDS:
            if field in financials.columns:
                lines.append(f"{field}: {fin_last[field]}")

    if watch:
        lines.append(f"## 自选池\nscore={watch['score']}  rank={watch['rank']}")
    else:
        lines.append(f"## 自选池\n{WATCH_HINT}")

    lines.append(f"数据截至 {last_date}，财务数据截至 {fin_note}。")
    return "\n".join(lines)


def build_context(code: str) -> str:
    quotes = read_quotes(code)
    financials = read_financials(code)
    conn = get_conn()
    try:
        watch_df = pd.read_sql_query(
            "SELECT score, rank FROM watchlist WHERE code = ?", conn, params=(code,)
        )
    finally:
        conn.close()
    watch = None
    if not watch_df.empty:
        watch = {"score": watch_df.iloc[0]["score"], "rank": watch_df.iloc[0]["rank"]}
    return build_context_text(code, quotes, financials, watch)
```

- [ ] **Step 5: 运行确认通过**

```bash
cd /home/jayden/stock-advisor && .venv/bin/python -m pytest backend/tests/test_context.py -v
```
Expected: 3 passed

- [ ] **Step 6: 全量 pytest（替代 Commit）**

```bash
cd /home/jayden/stock-advisor && .venv/bin/python -m pytest backend/tests -q
```
Expected: 全部 passed（30 个 = 27 既有 + 3 新）

---

### Task 2: LLM 客户端（httpx + SSE 解析 + 重试）

**Files:**
- Modify: `backend/pyproject.toml`（经 `uv add httpx`）
- Create: `backend/app/assistant/llm.py`
- Test: `backend/tests/test_llm.py`

**Interfaces:**
- Consumes: `app.core.config.{GLM_API_URL, GLM_MODEL, GLM_TIMEOUT_SEC}`
- Produces:
  - `LLMError(Exception)`（所有上游失败统一抛出）
  - `stream_chat(messages: list[dict], api_key: str | None = None) -> Iterator[str]`（增量文本；key 为空抛 `LLMError`；仅首包失败重试 1 次，已产出内容后失败直接上抛）
  - 私有：`_parse_sse(raw_lines: Iterable[str]) -> Iterator[str]`、`_client() -> httpx.Client`、`_stream_once(messages, api_key)`

- [ ] **Step 1: 装依赖**

```bash
cd /home/jayden/stock-advisor && uv add httpx
```

- [ ] **Step 2: 写失败测试**

创建 `backend/tests/test_llm.py`：

```python
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
```

注：`monkeypatch.setattr` 自动还原 `_client` 工厂，无跨测试污染。

- [ ] **Step 3: 运行确认失败**

```bash
cd /home/jayden/stock-advisor && .venv/bin/python -m pytest backend/tests/test_llm.py -v
```
Expected: FAIL（ModuleNotFoundError: app.assistant.llm）

- [ ] **Step 4: 创建 `backend/app/assistant/llm.py`**

```python
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
```

- [ ] **Step 5: 运行确认通过**

```bash
cd /home/jayden/stock-advisor && .venv/bin/python -m pytest backend/tests/test_llm.py -v
```
Expected: 3 passed

- [ ] **Step 6: 全量 pytest（替代 Commit）**

```bash
cd /home/jayden/stock-advisor && .venv/bin/python -m pytest backend/tests -q
```
Expected: 全部 passed（33 个 = 30 既有 + 3 新）

---

### Task 3: POST /api/chat（流式端点 + system 红线 + CORS 放行 POST）

**Files:**
- Modify: `backend/app/api/main.py`（新增 chat 端点、SYSTEM_TEMPLATE，CORS allow_methods 改为 [GET, POST]）
- Test: `backend/tests/test_prompt.py`
- Test: `backend/tests/test_chat_api.py`

**Interfaces:**
- Consumes: `app.assistant.context.build_context`、`app.assistant.llm.{stream_chat, LLMError}`、`app.core.config.{GLM_API_KEY, CHAT_HISTORY_LIMIT}`、`app.data.storage.{read_quotes, get_conn}`
- Produces:
  - `SYSTEM_TEMPLATE: str`（角色 + 三红线 + `{context}` 占位）
  - `ChatMessage(role: str, content: str)`、`ChatRequest(code: str, messages: list[ChatMessage])`（pydantic v2，messages 只允许 user/assistant，校验在 main 模块内定义）
  - `POST /api/chat` → `StreamingResponse(media_type="text/plain; charset=utf-8")`；503 无 key / 404 无行情 / 502 LLMError（首包即失败）/ 200 空流
  - `build_system_prompt(context: str) -> str`（可测纯函数）

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/test_prompt.py`：

```python
from app.api.main import build_system_prompt


def test_system_prompt_contains_redlines_and_context():
    prompt = build_system_prompt("## 行情摘要（300001）")
    assert "不给买卖点" in prompt
    assert "不预测目标价" in prompt
    assert "只能引用" in prompt
    assert "## 行情摘要（300001）" in prompt
```

创建 `backend/tests/test_chat_api.py`：

```python
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
```

- [ ] **Step 2: 运行确认失败**

```bash
cd /home/jayden/stock-advisor && .venv/bin/python -m pytest backend/tests/test_prompt.py backend/tests/test_chat_api.py -v
```
Expected: FAIL（ImportError: build_system_prompt / ChatRequest 不存在）

- [ ] **Step 3: 修改 `backend/app/api/main.py`**

3a. 顶部新增导入与常量：

```python
from collections.abc import Iterator
from typing import Literal

from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field

from app.assistant.context import build_context
from app.assistant.llm import LLMError, stream_chat
from app.core.config import CHAT_HISTORY_LIMIT, GLM_API_KEY

SYSTEM_TEMPLATE = """你是A股投资学习工具的解读助手，正在为用户解读当前股票（代码见上下文）。

三条红线（必须遵守）：
1. 只解释现象与指标含义，不给买卖点，不预测目标价。
2. 所有数字只能引用下方上下文中出现的数字，禁止自行计算或编造。
3. 回答中要明示数据截至日期（上下文最后一行给出）。

{context}"""
```

3b. 定义请求模型与辅助函数：

```python
class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    code: str = Field(min_length=1, max_length=12)
    messages: list[ChatMessage]


def build_system_prompt(context: str) -> str:
    return SYSTEM_TEMPLATE.format(context=context)
```

3c. 端点：

```python
@app.post("/api/chat")
def chat(req: ChatRequest) -> Response:
    if not GLM_API_KEY:
        raise HTTPException(status_code=503, detail="服务端未配置 GLM_API_KEY")
    try:
        context = build_context(req.code)
    except ValueError:
        raise HTTPException(status_code=404, detail=f"no quotes for {req.code}")

    system = build_system_prompt(context)
    history = [
        {"role": m.role, "content": m.content}
        for m in req.messages[-CHAT_HISTORY_LIMIT:]
    ]
    messages = [{"role": "system", "content": system}, *history]

    iterator = stream_chat(messages, api_key=GLM_API_KEY)
    try:
        first = next(iterator)
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=f"LLM upstream error: {exc}")
    except StopIteration:
        return Response(status_code=200, media_type="text/plain")

    def gen() -> Iterator[str]:
        yield first
        yield from iterator

    return StreamingResponse(gen(), media_type="text/plain; charset=utf-8")
```

3d. CORS：`allow_methods=["GET"]` → `allow_methods=["GET", "POST"]`；`allow_headers` 若存在需包含 `content-type`。

- [ ] **Step 4: 运行确认通过**

```bash
cd /home/jayden/stock-advisor && .venv/bin/python -m pytest backend/tests/test_prompt.py backend/tests/test_chat_api.py -v
```
Expected: 4 passed

- [ ] **Step 5: 全量 pytest（替代 Commit）**

```bash
cd /home/jayden/stock-advisor && .venv/bin/python -m pytest backend/tests -q
```
Expected: 全部 passed（37 个 = 33 既有 + 4 新）

---

### Task 4: 前端侧边栏 ChatPanel（流式打字机）

**Files:**
- Create: `frontend/app/ChatPanel.tsx`
- Modify: `frontend/app/page.tsx`（「AI解读」按钮 + 布局改造）
- Modify: `frontend/app/globals.css`（面板与气泡样式）

**Interfaces:**
- Consumes: `POST {API_BASE}/api/chat`（body `{"code": string, "messages": [{role, content}]}`，响应 `text/plain` 增量流）；`API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8000"`（与 page.tsx 现有常量一致）
- Produces:
  - `ChatPanel: React.FC<{ code: string; onClose: () => void }>`
  - `ChatMsg = { role: "user" | "assistant"; content: string }`
  - 布局：`.body` 改 flex（height calc(100vh-96px)），`.chart` flex:1 min-width:0，`.chat-panel` width:380px
- 约束：无 `any`、无 `@ts-ignore`、空 catch 禁止（catch 里必须 set error 文案）

- [ ] **Step 1: 创建 `frontend/app/ChatPanel.tsx`**

```tsx
"use client";

import { useEffect, useRef, useState } from "react";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8000";

type ChatMsg = { role: "user" | "assistant"; content: string };

interface ChatPanelProps {
  code: string;
  onClose: () => void;
}

export default function ChatPanel({ code, onClose }: ChatPanelProps) {
  const [msgs, setMsgs] = useState<ChatMsg[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setMsgs([]);
    setError("");
  }, [code]);

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [msgs]);

  async function send() {
    const question = input.trim();
    if (!question || busy) return;
    const next: ChatMsg[] = [...msgs, { role: "user", content: question }];
    setMsgs(next);
    setInput("");
    setBusy(true);
    setError("");
    try {
      const res = await fetch(`${API_BASE}/api/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ code, messages: next }),
      });
      if (!res.ok || !res.body) {
        const detail = await res.text().catch(() => "");
        throw new Error(`请求失败(${res.status}) ${detail}`);
      }
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let acc = "";
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        acc += decoder.decode(value, { stream: true });
        const current = acc;
        setMsgs([...next, { role: "assistant", content: current }]);
      }
      if (!acc) throw new Error("模型未返回内容");
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      setError(message || "连接中断，请重试");
    } finally {
      setBusy(false);
    }
  }

  return (
    <aside className="chat-panel">
      <div className="chat-head">
        <span>AI 解读 · {code}</span>
        <button onClick={onClose} aria-label="关闭">✕</button>
      </div>
      <div className="chat-body" ref={scrollRef}>
        {msgs.length === 0 && (
          <div className="chat-empty">
            针对当前股票提问，数据由后端计算层注入，AI只做解读。
          </div>
        )}
        {msgs.map((m, i) => (
          <div key={i} className={`chat-msg ${m.role}`}>
            <pre>{m.content}</pre>
            {busy && m.role === "assistant" && i === msgs.length - 1 && (
              <span className="chat-cursor" />
            )}
          </div>
        ))}
        {error && <div className="chat-error">{error}</div>}
      </div>
      <div className="chat-input">
        <textarea
          value={input}
          placeholder="Enter 发送，Shift+Enter 换行"
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              void send();
            }
          }}
          disabled={busy}
          rows={2}
        />
        <button onClick={() => void send()} disabled={busy || !input.trim()}>
          {busy ? "…" : "发送"}
        </button>
      </div>
    </aside>
  );
}
```

- [ ] **Step 2: `frontend/app/page.tsx` 集成**

- 顶部 import `ChatPanel`
- 新增 state：`const [chatOpen, setChatOpen] = useState(false);`
- 顶栏右侧加按钮：`<button className="ai-toggle" onClick={() => setChatOpen((v) => !v)}>{chatOpen ? "收起解读" : "AI解读"}</button>`
- 布局：原滚动容器改为 `<div className="body">`，内含 `<div className="chart">…原图表内容…</div>` + `{chatOpen && <ChatPanel code={code} onClose={() => setChatOpen(false)} />}`
- 注意：原 page.tsx 的滚动/高度样式迁移到 `.chart`（overflow-y:auto），保证面板固定不随图表滚动

- [ ] **Step 3: `frontend/app/globals.css` 追加面板样式**

```css
.body { display: flex; height: calc(100vh - 96px); }
.chart { flex: 1; min-width: 0; overflow-y: auto; }
.ai-toggle { /* 跟随现有按钮风格 */ }
.chat-panel {
  width: 380px; flex-shrink: 0; border-left: 1px solid #1f2937;
  display: flex; flex-direction: column; background: #0d1117;
}
.chat-head {
  display: flex; justify-content: space-between; align-items: center;
  padding: 10px 14px; border-bottom: 1px solid #1f2937; font-size: 13px;
}
.chat-head button { background: none; border: none; color: #8b949e; cursor: pointer; }
.chat-body { flex: 1; overflow-y: auto; padding: 12px 14px; }
.chat-empty { color: #8b949e; font-size: 13px; line-height: 1.7; }
.chat-msg { margin-bottom: 12px; }
.chat-msg pre {
  white-space: pre-wrap; word-break: break-word;
  font-family: inherit; font-size: 13px; line-height: 1.7; margin: 0;
}
.chat-msg.user pre { color: #79c0ff; text-align: right; }
.chat-msg.assistant pre { color: #e6edf3; }
.chat-cursor {
  display: inline-block; width: 7px; height: 14px; background: #58a6ff;
  animation: blink 1s step-end infinite;
}
@keyframes blink { 50% { opacity: 0; } }
.chat-error { color: #f85149; font-size: 12px; margin-top: 8px; }
.chat-input {
  display: flex; gap: 8px; padding: 10px 14px;
  border-top: 1px solid #1f2937;
}
.chat-input textarea {
  flex: 1; resize: none; background: #161b22; color: #e6edf3;
  border: 1px solid #30363d; border-radius: 6px; padding: 8px;
  font-family: inherit; font-size: 13px;
}
.chat-input button {
  align-self: flex-end; padding: 8px 14px; border-radius: 6px;
  border: none; background: #238636; color: #fff; cursor: pointer;
}
.chat-input button:disabled { opacity: 0.5; cursor: default; }
```

（颜色/间距沿用 globals.css 现有深色变量；若已有同类值以现有文件为准，冲突时改现有规则而非重复定义。）

- [ ] **Step 4: 类型检查与构建**

```bash
cd /home/jayden/stock-advisor/frontend && npx tsc --noEmit && npm run build
```
Expected: 0 错误（build 成功）

注：build 会覆盖 `.next`，若 dev server（tmux `web`）正在运行，build 后需重启 dev：

```bash
tmux kill-session -t web 2>/dev/null; cd /home/jayden/stock-advisor/frontend && rm -rf .next && (npm run dev >/dev/null 2>&1 &)
```
（或按 Global Constraints 用 tmux 会话重启，保持 `web` 会话存在）

---

### Task 5: 实盘验收（API key 落地 + Playwright E2E）

**Files:**
- Test（临时）: `frontend/e2e-assistant.mjs`（验收后删除）
- 运维: 重启 tmux `api` 会话加载新代码与 `GLM_API_KEY`

**Interfaces:**
- Consumes: 运行中的 `api`（127.0.0.1:8000）与 `web`（localhost:3000）tmux 会话、智谱 key
- Produces: 可用的侧边栏对话（真实模型回复）+ 截图证据 + 环境清理

- [ ] **Step 1: 全量 pytest**

```bash
cd /home/jayden/stock-advisor && .venv/bin/python -m pytest backend/tests -q
```
Expected: 37 passed

- [ ] **Step 2: 获取 GLM_API_KEY 并重启后端**

向用户索取 `GLM_API_KEY`（若用户提供则写入 tmux `api` 会话环境；若用户暂无 key，仅验收 503 路径并向用户说明）：

```bash
tmux kill-session -t api 2>/dev/null
tmux new-session -d -s api -c /home/jayden/stock-advisor/backend \
  "GLM_API_KEY=<用户提供> ../.venv/bin/uvicorn app.api.main:app --host 127.0.0.1 --port 8000"
```

冒烟（无 key 环境则走 503 断言）：

```bash
curl -s -o /dev/null -w "%{http_code}\n" -X POST http://127.0.0.1:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"code":"300456","messages":[{"role":"user","content":"最近走势如何"}]}'
```
Expected: 有 key → 200（流式文本）；无 key → 503

- [ ] **Step 3: 前端 dev 就绪确认**

```bash
tmux has-session -t web && curl -s -o /dev/null -w "%{http_code}\n" http://localhost:3000
```
Expected: 会话存在且 HTTP 200（若 Task 4 后未重启，按 Task 4 Step 4 注重启）

- [ ] **Step 4: Playwright E2E**

```bash
cd /home/jayden/stock-advisor/frontend && npm i -D playwright@1.61.0
```

创建 `frontend/e2e-assistant.mjs`（executablePath 指向既有 chromium `/home/jayden/.cache/ms-playwright/chromium-1234/chrome-linux64/chrome`；Node 18 只装 1.61）：

- 打开 http://localhost:3000 → 等 K 线渲染 → 点「AI解读」→ 面板出现空态文案
- 在 textarea 输入「这只股票最近20个交易日走势如何？」→ Enter 发送
- 等待 assistant 气泡文本 > 20 字（超时 90s）
- 断言：气泡包含「数据截至」（红线3生效）；console error 数 = 0
- 截图 `frontend/.e2e-assistant.png`

```bash
node e2e-assistant.mjs
```
Expected: 退出码 0，断言全过

- [ ] **Step 5: 清理**

```bash
cd /home/jayden/stock-advisor/frontend && npm uninstall playwright && rm -f e2e-assistant.mjs
```
截图保留给用户审阅（验收后可自行删除）。

- [ ] **Step 6: 最终全量验证（替代 Commit）**

```bash
cd /home/jayden/stock-advisor && .venv/bin/python -m pytest backend/tests -q \
  && cd frontend && npx tsc --noEmit
```
Expected: pytest 全 passed + tsc 0 错误

---

## 自审

- [x] spec 覆盖：`docs/superpowers/specs/2026-10-13-assistant-design.md` 的每条需求都能映射到 Task 1-5（context 拼装→T1，llm 流式+重试→T2，端点+红线+错误码→T3，侧边栏+切股清空+空态→T4，key 落地+E2E→T5，测试矩阵→各任务测试步骤）
- [x] 无占位符：所有代码块完整可运行，无 `...`/`<TODO>`
- [x] 类型一致：`build_context_text(code, quotes, financials, watch: dict | None) -> str`、`stream_chat(messages: list[dict], api_key: str | None = None) -> Iterator[str]`、`ChatRequest{code: str, messages: list[ChatMessage]}` 在 T1/T2/T3 三处定义一致
- [x] 错误码一致：503（无 key）/404（无行情）/502（LLMError）在 T3 接口与测试断言一致
- [x] 计数一致：27 既有 +3(T1) +3(T2) +4(T3) = 37
