"""同步编排: 股票列表 + 日线(增量) + 财务指标。

被 scripts/sync.py 与 scheduler 调用。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta

from app.core import config
from app.data import fetchers, fetchers_baostock, storage

logger = logging.getLogger(__name__)


@dataclass
class SyncResult:
    stocks_synced: int = 0
    quotes_synced: int = 0
    quotes_failed: list[str] = field(default_factory=list)
    financials_synced: int = 0
    financials_failed: list[str] = field(default_factory=list)


def sync_stock_list(conn) -> int:
    df = fetchers.fetch_stock_list()
    n = storage.upsert_stocks(conn, df)
    logger.info("stock list synced: %s", n)
    return n


def sync_quotes(
    conn,
    codes: list[str],
    start_date: str | None = None,
    end_date: str | None = None,
) -> tuple[int, list[str]]:
    """增量同步日线: 从本地最新交易日的下一天开始拉取。"""
    end = end_date or date.today().strftime("%Y%m%d")
    ok, failed = 0, []
    for code in codes:
        try:
            last = storage.last_quote_date(code)
            if last is not None:
                start = (last + timedelta(days=1)).strftime("%Y%m%d")
                if start > end:
                    storage.mark_quotes_synced(conn, code)
                    ok += 1
                    continue
            else:
                start = start_date or config.DEFAULT_START_DATE
            df = fetchers_baostock.fetch_daily(code, start_date=start, end_date=end)
            storage.append_quotes(code, df)
            storage.mark_quotes_synced(conn, code)
            ok += 1
        except Exception as exc:  # 单只失败不中断整体
            logger.warning("quotes sync failed for %s: %s", code, exc)
            failed.append(code)
    return ok, failed


def sync_financials(conn, codes: list[str]) -> tuple[int, list[str]]:
    ok, failed = 0, []
    for code in codes:
        try:
            df = fetchers.fetch_financials(code)
            if not df.empty:
                storage.write_financials(code, df)
            storage.mark_financials_synced(conn, code)
            ok += 1
        except Exception as exc:
            logger.warning("financials sync failed for %s: %s", code, exc)
            failed.append(code)
    return ok, failed


def run_sync(
    codes: list[str] | None = None,
    limit: int | None = None,
    full_history: bool = False,
    skip_financials: bool = False,
) -> SyncResult:
    """执行一轮同步。codes 为空则同步全市场。"""
    config.ensure_dirs()
    conn = storage.get_conn()
    result = SyncResult()

    try:
        result.stocks_synced = sync_stock_list(conn)

        if codes is None:
            codes = storage.list_stocks(conn)["code"].tolist()
        if limit is not None:
            codes = codes[:limit]

        unsupported = [c for c in codes if not fetchers_baostock.is_supported(c)]
        if unsupported:
            logger.info(
                "skip %s codes unsupported by baostock (北交所等)",
                len(unsupported),
            )
        codes = [c for c in codes if fetchers_baostock.is_supported(c)]

        start = "20050101" if full_history else config.DEFAULT_START_DATE
        result.quotes_synced, result.quotes_failed = sync_quotes(
            conn, codes, start_date=start
        )

        if not skip_financials:
            result.financials_synced, result.financials_failed = sync_financials(
                conn, codes
            )
    finally:
        fetchers_baostock.logout()
        conn.close()
    return result
