"""选股 CLI：拉数 → 过滤 → 打分 → Top N → 落库 + 导出。"""
from __future__ import annotations

import argparse
import logging
from datetime import date

import pandas as pd

from app.core import config
from app.data.storage import get_conn, replace_watchlist
from app.screener import rules, snapshot

logger = logging.getLogger(__name__)


def _latest_report_period(today: date) -> str:
    """推断最近已披露报告期(YYYYMMDD)。披露截止：一季报4/30、中报8/31、三季报10/31。"""
    y = today.year
    md = (today.month, today.day)
    if md <= (4, 30):
        return f"{y - 1}1231"
    if md <= (8, 31):
        return f"{y}0331"
    if md <= (10, 31):
        return f"{y}0630"
    return f"{y}0930"


def run_screening(merged: pd.DataFrame, params: argparse.Namespace, as_of: date) -> pd.DataFrame:
    """编排：硬过滤 → 打分 → Top N。返回 code/name/score/rank。"""
    filtered = rules.apply_hard_filters(
        merged,
        as_of=as_of,
        min_float_mv=params.min_float_mv,
        min_amount=params.min_amount,
        min_listing_years=params.min_listing_years,
    )
    logger.info("硬过滤后候选: %s", len(filtered))
    scored = rules.score_stocks(
        filtered,
        weight_amount=params.weight_amount,
        weight_pe=params.weight_pe,
        weight_growth=params.weight_growth,
    )
    top = rules.select_top(scored, params.top)
    return top[["code", "name", "score", "rank"]]


def main() -> None:
    parser = argparse.ArgumentParser(description="选股筛选器")
    parser.add_argument("--top", type=int, default=config.SCREEN_TOP_N)
    parser.add_argument("--min-float-mv", type=float, default=config.SCREEN_MIN_FLOAT_MV)
    parser.add_argument("--min-amount", type=float, default=config.SCREEN_MIN_AMOUNT)
    parser.add_argument("--min-listing-years", type=int, default=config.SCREEN_MIN_LISTING_YEARS)
    parser.add_argument("--weight-amount", type=float, default=config.SCREEN_WEIGHT_AMOUNT)
    parser.add_argument("--weight-pe", type=float, default=config.SCREEN_WEIGHT_PE)
    parser.add_argument("--weight-growth", type=float, default=config.SCREEN_WEIGHT_GROWTH)
    parser.add_argument("--report-period", default=None, help="业绩报告期 YYYYMMDD，缺省自动推断最近已披露期")
    args = parser.parse_args()

    snap = snapshot.fetch_market_snapshot()
    listing = snapshot.fetch_listing_dates()
    period = args.report_period or _latest_report_period(date.today())
    earnings = snapshot.fetch_earnings_growth(period)
    merged = snapshot.merge_snapshot(snap, listing, earnings)

    watchlist = run_screening(merged, args, date.today())

    config.ensure_dirs()
    conn = get_conn()
    try:
        n = replace_watchlist(conn, watchlist)
    finally:
        conn.close()
    config.WATCHLIST_PATH.write_text(",".join(watchlist["code"]), encoding="utf-8")
    print(f"watchlist 写入 {n} 只 → {config.WATCHLIST_PATH}")
    print(watchlist.head(10).to_string(index=False))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
