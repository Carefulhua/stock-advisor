"""选股编排：拉数 → 条件筛选 → 自选强制保留 → 池子差异。CLI 直接把结果应用到池子。"""
from __future__ import annotations

import argparse
import logging
from datetime import date

import pandas as pd

from app.core import config
from app.data.storage import get_conn, read_favorites, replace_watchlist_by_codes
from app.screener import conditions, fields, snapshot

logger = logging.getLogger(__name__)

DISPLAY_COLUMNS = [
    "code", "name", "rank", "is_favorite",
    "pe_ttm", "pn", "turnover", "ltsz", "zsz", "hsl", "lb",
    "zdf_y", "zdf_d20", "zdf_d60", "zljlr",
    "eps", "cfps", "revenue_yoy", "net_profit_yoy", "net_profit", "roe", "gross_margin",
    "debt_ratio", "net_margin", "revenue_qoq", "net_profit_qoq",
    "industry", "list_date",
]


def latest_report_period(today: date) -> str:
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


def load_merged_market(report_period: str | None = None) -> tuple[pd.DataFrame, bool]:
    """拉取并合并筛选/打分所需的全部维度，返回 (合并表, 财务比率是否就绪)。

    资产负债率/净利率来自另两个全市场报表接口，失败只降级为「这两列缺失」，
    不阻断筛选与打分——其余维度照常可用，故用单独标志回报而不是整段报错。
    """
    snap = snapshot.market_snapshot_cached()
    listing = snapshot.fetch_listing_dates()
    period = report_period or latest_report_period(date.today())
    earnings = snapshot.fetch_earnings_growth(period)
    fields.set_industry_options(
        sorted({str(v) for v in snap["industry"].dropna()}) if "industry" in snap.columns else []
    )
    fundamentals = None
    try:
        fundamentals = snapshot.fetch_fundamentals(period)
    except Exception as exc:
        logger.warning("fundamentals fetch failed: %s", exc)
    return snapshot.merge_snapshot(snap, listing, earnings, fundamentals), fundamentals is not None


def _display_columns(merged: pd.DataFrame) -> list[str]:
    return [c for c in DISPLAY_COLUMNS if c in merged.columns]


def run_filter(
    merged: pd.DataFrame,
    spec: conditions.FilterSpec,
    current_pool: list[str],
    favorites: list[str],
) -> dict:
    """条件筛选 + 自选强制保留的纯函数。

    rows = 条件命中的 Top N ∪ 自选全集（自选置顶，不受条件与 top 限制）；
    next_in = rows 中非自选且不在现池；next_out = 现池中既不在 rows 也不在自选。
    """
    fav_codes = {_normalize(code) for code in favorites}
    fav_codes.discard("")

    candidates = merged
    if "name" in candidates.columns:
        candidates = candidates[~candidates["name"].astype(str).str.contains("ST", na=False)]
    matched = conditions.evaluate(candidates, spec.conditions)
    total_matched = len(matched)

    selected = matched.sort_values(spec.sort_by, ascending=False).head(spec.top)

    rows = _assemble_rows(merged, selected, fav_codes)
    row_codes = rows["code"].tolist()
    pool = {_normalize(c) for c in current_pool}

    next_in = [c for c in row_codes if c not in fav_codes and c not in pool]
    next_out = [c for c in pool if c not in row_codes and c not in fav_codes]
    return {
        "rows": rows,
        "next_in": next_in,
        "next_out": next_out,
        "kept_favorites": [c for c in fav_codes if c],
        "total_matched": total_matched,
    }


def _normalize(code: str) -> str:
    text = str(code).strip().zfill(6)
    return text if len(text) == 6 and text.isdigit() else ""


def _assemble_rows(
    merged: pd.DataFrame,
    selected: pd.DataFrame,
    fav_codes: set[str],
) -> pd.DataFrame:
    """自选置顶 + 选中股按原顺序拼接，rank 从 1 连续重编。"""
    columns = _display_columns(merged)
    fav_rows = (
        merged[merged["code"].isin(fav_codes)][columns]
        if not merged.empty
        else merged
    )
    sel_rows = selected[columns] if not selected.empty else selected
    rows = pd.concat([fav_rows, sel_rows])
    rows = rows.drop_duplicates(subset="code", keep="first").reset_index(drop=True)
    rows["is_favorite"] = rows["code"].isin(fav_codes)
    rows["rank"] = range(1, len(rows) + 1)
    ordered = ["code", "name", "rank", "is_favorite"] + [
        c for c in columns if c not in ("code", "name")
    ]
    return rows[ordered]


def main() -> None:
    parser = argparse.ArgumentParser(description="选股筛选器")
    parser.add_argument("--top", type=int, default=config.SCREEN_TOP_N)
    parser.add_argument("--conditions-json", default="[]", help='条件列表 JSON，如 [{"field":"pe_ttm","op":"lte","value":15}]')
    parser.add_argument("--sort-by", default="net_profit_yoy")
    parser.add_argument("--report-period", default=None, help="业绩报告期 YYYYMMDD，缺省自动推断最近已披露期")
    args = parser.parse_args()

    spec = conditions.FilterSpec.model_validate_json(args.conditions_json)
    spec = spec.model_copy(update={"sort_by": args.sort_by, "top": args.top})

    merged, _ = load_merged_market(args.report_period)

    conn = get_conn()
    try:
        pool = conn.execute("SELECT code FROM watchlist").fetchall()
        current_pool = [r["code"] for r in pool]
        favorites = read_favorites(conn)["code"].tolist()
    finally:
        conn.close()

    result = run_filter(merged, spec, current_pool, favorites)
    logger.info("命中 %s 只，结果池 %s 只", result["total_matched"], len(result["rows"]))

    config.ensure_dirs()
    conn = get_conn()
    try:
        n = replace_watchlist_by_codes(conn, result["rows"][["code", "name", "rank"]])
    finally:
        conn.close()
    config.WATCHLIST_PATH.write_text(",".join(result["rows"]["code"]), encoding="utf-8")
    print(f"watchlist 写入 {n} 只 → {config.WATCHLIST_PATH}")
    print(result["rows"].head(10).to_string(index=False))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()