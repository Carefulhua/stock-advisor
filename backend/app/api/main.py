"""分析页 API：股票列表 / 日线 / 技术指标 / AI 解读对话 / 选股器。"""
from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from datetime import date
from typing import Literal

import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field

from app.analysis import indicators as ind
from app.assistant.context import build_context
from app.assistant.llm import LLMError, stream_chat
from app.core import config
from app.core.config import CHAT_HISTORY_LIMIT, GLM_API_KEY
from app.data import fetchers_baostock
from app.data.storage import (
    add_favorites,
    get_conn,
    list_stocks,
    read_favorites,
    read_quotes,
    read_watchlist,
    remove_favorite,
    replace_watchlist_by_codes,
)
from app.screener import fields as field_catalog
from app.screener import sync_job
from app.screener.conditions import FilterSpec
from app.screener.parse import ParseError, parse_query
from app.screener.run import _latest_report_period, run_filter
from app.screener.snapshot import (
    fetch_earnings_growth,
    fetch_listing_dates,
    market_code_index,
    market_snapshot_cached,
    merge_snapshot,
    snapshot_cache_state,
)

logger = logging.getLogger(__name__)


def startup_daily_sync() -> str | None:
    """服务启动即更新展示池（自选∪池子）的日线增量。

    走后台线程（复用 sync_job 进度与互斥），不阻塞服务启动；
    只补日线不拉财务——财务每只都要发一次 HTTP，留给手动/调度任务。
    """
    conn = get_conn()
    try:
        pool = read_watchlist(conn)
        favorites = read_favorites(conn)
    finally:
        conn.close()
    codes = sorted(set(pool["code"]) | set(favorites["code"]))
    # baostock 不覆盖北交所等，先过滤避免整轮记为失败
    codes = [code for code in codes if fetchers_baostock.is_supported(code)]
    if not codes:
        return None
    try:
        job_id = sync_job.start(codes, skip_financials=True)
    except sync_job.SyncBusyError:
        logger.info("startup sync skipped: 已有同步任务在运行")
        return None
    logger.info("startup sync started: %s 只, job=%s", len(codes), job_id)
    return job_id


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    startup_daily_sync()
    yield


app = FastAPI(title="stock-advisor api", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["GET", "POST", "DELETE"],
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
    """展示池 = 筛选池 ∪ 自选，自选置顶且标 is_favorite，供分析页下拉与默认选股。"""
    conn = get_conn()
    try:
        pool = read_watchlist(conn)
        favorites = read_favorites(conn)
    finally:
        conn.close()
    favorite_codes = set(favorites["code"])
    merged = pd.concat([favorites[["code", "name"]], pool[["code", "name"]]], ignore_index=True)
    merged = merged.drop_duplicates(subset=["code"], keep="first")
    merged["is_favorite"] = merged["code"].isin(favorite_codes)
    return _records(merged[["code", "name", "is_favorite"]])


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


class ParseRequest(BaseModel):
    query: str = Field(min_length=1, max_length=200)


class FavoriteRequest(BaseModel):
    codes: list[str] = Field(min_length=1, max_length=500)


class ApplyRequest(BaseModel):
    codes: list[str] = Field(min_length=1, max_length=1000)


def _names_for(conn, codes: list[str]) -> list[tuple[str, str]]:
    """解析 code → (code, name)。stocks 表优先，未收录的回落到全市场代码表。"""
    rows = conn.execute(
        "SELECT code, name FROM stocks WHERE code IN ({})".format(
            ",".join("?" * len(codes))
        ),
        codes,
    ).fetchall()
    found = {row[0]: row[1] for row in rows}
    missing = [code for code in codes if code not in found]
    if missing:
        index = market_code_index()
        known = {row.code: row.name for row in index.itertuples()}
        found.update({code: known[code] for code in missing if code in known})
    return [(code, found[code]) for code in codes if code in found]


@app.get("/api/stocks/search")
def stocks_search(q: str = Query(min_length=1, max_length=20)) -> list[dict]:
    """全市场代码/名称搜索（复用当日快照缓存），供自选添加使用。"""
    try:
        index = market_code_index()
    except Exception as exc:
        logger.warning("stock search index failed: %s", exc)
        raise HTTPException(status_code=502, detail=f"全市场代码表拉取失败: {exc}")
    keyword = q.strip()
    hit = index[index["code"].str.contains(keyword, regex=False) | index["name"].str.contains(keyword, regex=False)]
    return _records(hit.head(20))


@app.get("/api/screener/fields")
def screener_fields() -> list[dict]:
    return field_catalog.catalog()


@app.get("/api/screener/status")
def screener_status() -> dict:
    return {"llm_enabled": bool(GLM_API_KEY), "snapshot_cached": snapshot_cache_state()}


@app.post("/api/screener/parse")
def screener_parse(req: ParseRequest) -> dict:
    if not GLM_API_KEY:
        raise HTTPException(status_code=503, detail="服务端未配置 GLM_API_KEY")
    try:
        spec = parse_query(req.query, api_key=GLM_API_KEY)
    except ParseError as exc:
        code = 502 if exc.reason == "llm" else 422
        raise HTTPException(status_code=code, detail=str(exc))
    return _spec_payload(spec)


def _spec_payload(spec: FilterSpec) -> dict:
    return {
        "conditions": [c.model_dump() for c in spec.conditions],
        "sort_by": spec.sort_by,
        "top": spec.top,
    }


@app.post("/api/screener/run")
def screener_run(spec: FilterSpec) -> dict:
    started = time.perf_counter()
    try:
        snap = market_snapshot_cached()
        listing = fetch_listing_dates()
        earnings = fetch_earnings_growth(_latest_report_period(date.today()))
    except Exception as exc:
        logger.warning("screener snapshot fetch failed: %s", exc)
        raise HTTPException(status_code=502, detail=f"行情快照拉取失败: {exc}")

    field_catalog.set_industry_options(
        sorted({str(v) for v in snap["industry"].dropna()}) if "industry" in snap.columns else []
    )
    merged = merge_snapshot(snap, listing, earnings)

    conn = get_conn()
    try:
        pool = read_watchlist(conn)["code"].tolist()
        favorites = read_favorites(conn)["code"].tolist()
    finally:
        conn.close()

    result = run_filter(merged, spec, pool, favorites)
    rows = result["rows"]
    return {
        "rows": _records(rows),
        "columns": list(rows.columns),
        "next_in": result["next_in"],
        "next_out": result["next_out"],
        "kept_favorites": result["kept_favorites"],
        "total_matched": result["total_matched"],
        "elapsed_sec": round(time.perf_counter() - started, 2),
        "cached": snapshot_cache_state(),
    }


@app.post("/api/screener/apply")
def screener_apply(req: ApplyRequest) -> dict:
    conn = get_conn()
    try:
        pairs = _names_for(conn, [c.zfill(6) for c in req.codes])
        if not pairs:
            raise HTTPException(status_code=422, detail="代码均不在股票列表中")
        frame = pd.DataFrame(pairs, columns=["code", "name"]).assign(score=0.0, rank=range(1, len(pairs) + 1))
        applied = replace_watchlist_by_codes(conn, frame)
        config.ensure_dirs()
        config.WATCHLIST_PATH.write_text(",".join(code for code, _ in pairs), encoding="utf-8")
    finally:
        conn.close()

    try:
        job_id = sync_job.start([code for code, _ in pairs])
    except sync_job.SyncBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"applied": applied, "sync_job_id": job_id}


@app.get("/api/favorites")
def favorites_list() -> list[dict]:
    conn = get_conn()
    try:
        return _records(read_favorites(conn))
    finally:
        conn.close()


@app.post("/api/favorites")
def favorites_add(req: FavoriteRequest) -> dict:
    codes = [c.zfill(6) for c in req.codes]
    conn = get_conn()
    try:
        before = set(read_favorites(conn)["code"])
        pairs = _names_for(conn, codes)
        added, skipped = add_favorites(conn, pairs)
    finally:
        conn.close()
    # 加自选即同步：用户加自选就是要在分析页看它，不同步则点开只有「无数据」
    new_codes = [code for code, _ in pairs if code not in before]
    sync_job_id: str | None = None
    if new_codes:
        try:
            sync_job_id = sync_job.start(new_codes)
        except sync_job.SyncBusyError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
    return {"added": added, "skipped": skipped + (len(codes) - len(pairs)), "sync_job_id": sync_job_id}


@app.delete("/api/favorites/{code}")
def favorites_delete(code: str) -> dict:
    conn = get_conn()
    try:
        return {"deleted": remove_favorite(conn, code)}
    finally:
        conn.close()


@app.get("/api/sync/status")
def sync_status() -> dict:
    return sync_job.get_status()
