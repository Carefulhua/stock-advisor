"""分析页 API：股票列表 / 日线 / 技术指标 / AI 解读对话。"""
from __future__ import annotations

from collections.abc import Iterator
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field

from app.analysis import indicators as ind
from app.assistant.context import build_context
from app.assistant.llm import LLMError, stream_chat
from app.core.config import CHAT_HISTORY_LIMIT, GLM_API_KEY
from app.data.storage import get_conn, list_stocks, read_quotes, read_watchlist

app = FastAPI(title="stock-advisor api")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

SYSTEM_TEMPLATE = """你是A股投资学习工具的解读助手，正在为用户解读当前股票（代码见上下文）。

三条红线（必须遵守）：
1. 只解释现象与指标含义，不给买卖点，不预测目标价。
2. 所有数字只能引用下方上下文中出现的数字，禁止自行计算或编造。
3. 回答中要明示数据截至日期（上下文最后一行给出）。

{context}"""


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    code: str = Field(min_length=1, max_length=12)
    messages: list[ChatMessage]


def build_system_prompt(context: str) -> str:
    return SYSTEM_TEMPLATE.format(context=context)


def _records(df):
    import json

    return json.loads(df.to_json(orient="records", date_format="iso"))


@app.get("/api/stocks")
def stocks() -> list[dict]:
    conn = get_conn()
    try:
        all_stocks = list_stocks(conn)
        watch = read_watchlist(conn)
    finally:
        conn.close()
    watch_codes = set(watch["code"])
    return [
        {"code": r.code, "name": r.name, "in_watchlist": r.code in watch_codes}
        for r in all_stocks.itertuples()
    ]


@app.get("/api/watchlist")
def watchlist() -> list[dict]:
    conn = get_conn()
    try:
        return _records(read_watchlist(conn))
    finally:
        conn.close()


@app.get("/api/quotes/{code}")
def quotes(code: str, start: str | None = Query(None), end: str | None = Query(None)) -> list[dict]:
    df = read_quotes(code, start=start, end=end)
    if df.empty:
        raise HTTPException(status_code=404, detail=f"no quotes for {code}")
    return _records(df)


@app.get("/api/indicators/{code}")
def chart_data(code: str, start: str | None = Query(None), end: str | None = Query(None)) -> dict:
    """返回 K线 OHLCV + 指标，一次请求喂饱前端图表。"""
    quotes = read_quotes(code, start=start, end=end)
    if quotes.empty:
        raise HTTPException(status_code=404, detail=f"no quotes for {code}")
    close = quotes["close"]
    out = quotes[["date", "open", "high", "low", "close", "volume", "amount"]].copy()
    out["ma5"] = ind.moving_average(close, 5)
    out["ma10"] = ind.moving_average(close, 10)
    out["ma20"] = ind.moving_average(close, 20)
    out["ma60"] = ind.moving_average(close, 60)
    dif, dea, hist = ind.macd(close)
    out["dif"] = dif
    out["dea"] = dea
    out["macd_hist"] = hist
    out["rsi14"] = ind.rsi(close, 14)
    k, d, j = ind.kdj(quotes["high"], quotes["low"], close)
    out["k"] = k
    out["d"] = d
    out["j"] = j
    return {"code": code, "rows": _records(out)}


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
