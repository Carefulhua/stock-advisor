"""三路数据拉取与合并：市场快照 / 上市日期 / 业绩报表。

筛选所需的全维度指标全部来自「腾讯全市场快照 + 业绩报表」两个全市场接口，不下载日线。
腾讯快照约需 3.5 分钟（27 次分页），因此按自然日做进程内缓存，同一天只拉一次。
"""
from __future__ import annotations

from datetime import date

import akshare as ak
import pandas as pd

from app.data.fetchers import _with_retry
from app.data.fetchers_baostock import is_supported

SNAPSHOT_NUMERIC_COLUMNS = [
    "zxj", "zd", "zdf", "zf", "lb", "hsl", "pe_ttm", "pn",
    "zdf_y", "zdf_d5", "zdf_d10", "zdf_d20", "zdf_d60",
]
# 腾讯接口单位换算：成交额/主力净流入为万元，市值为亿元，统一存为元
WAN_TO_YUAN = 1e4
YI_TO_YUAN = 1e8


def fetch_market_snapshot() -> pd.DataFrame:
    """全市场快照(腾讯)。东财 push2 按 IP 限频会整段封禁，故走腾讯源。"""
    raw = _with_retry(ak.stock_zh_a_spot_tx)
    df = raw[["code", "name", "turnover", "ltsz", "zsz", "zljlr", *SNAPSHOT_NUMERIC_COLUMNS]].copy()
    df.columns = ["code", "name", "turnover", "ltsz", "zsz", "zljlr", *SNAPSHOT_NUMERIC_COLUMNS]
    df["code"] = df["code"].astype(str).str[-6:].str.zfill(6)
    for column in ["turnover", "ltsz", "zsz", "zljlr", *SNAPSHOT_NUMERIC_COLUMNS]:
        df[column] = pd.to_numeric(df[column], errors="coerce")
    df["turnover"] = df["turnover"] * WAN_TO_YUAN
    df["zljlr"] = df["zljlr"] * WAN_TO_YUAN
    df["ltsz"] = df["ltsz"] * YI_TO_YUAN
    df["zsz"] = df["zsz"] * YI_TO_YUAN
    return df


def fetch_listing_dates() -> pd.DataFrame:
    """沪深两市上市日期: code, list_date。上交所分主板A股与科创板两批拉取。"""
    frames = []
    for symbol in ("主板A股", "科创板"):
        raw = _with_retry(ak.stock_info_sh_name_code, symbol=symbol)
        part = raw[["证券代码", "上市日期"]].copy()
        part.columns = ["code", "list_date"]
        frames.append(part)
    raw = _with_retry(ak.stock_info_sz_name_code, symbol="A股列表")
    part = raw[["A股代码", "A股上市日期"]].copy()
    part.columns = ["code", "list_date"]
    frames.append(part)
    df = pd.concat(frames, ignore_index=True)
    df["code"] = df["code"].astype(str).str.zfill(6)
    df["list_date"] = pd.to_datetime(df["list_date"], errors="coerce")
    return df.dropna(subset=["list_date"]).drop_duplicates(subset=["code"]).reset_index(drop=True)


EARNINGS_COLUMN_MAP = {
    "每股收益": "eps",
    "每股经营现金流量": "cfps",
    "营业总收入-同比增长": "revenue_yoy",
    "净利润-净利润": "net_profit",
    "净利润-同比增长": "net_profit_yoy",
    "净资产收益率": "roe",
    "销售毛利率": "gross_margin",
    "所处行业": "industry",
}


def fetch_earnings_growth(report_period: str) -> pd.DataFrame:
    """全市场业绩报表: code + 8 个业绩字段。report_period 形如 20260630。"""
    raw = _with_retry(ak.stock_yjbb_em, date=report_period)
    df = raw[["股票代码", *EARNINGS_COLUMN_MAP]].rename(columns=EARNINGS_COLUMN_MAP)
    df["code"] = df["股票代码"].astype(str).str.zfill(6)
    df = df.drop(columns=["股票代码"])
    for column in EARNINGS_COLUMN_MAP.values():
        if column != "industry":
            df[column] = pd.to_numeric(df[column], errors="coerce")
    df["industry"] = df["industry"].where(df["industry"].notna())
    return df.drop_duplicates(subset=["code"]).reset_index(drop=True)


def merge_snapshot(
    snapshot: pd.DataFrame,
    listing: pd.DataFrame,
    earnings: pd.DataFrame,
) -> pd.DataFrame:
    """以快照为左表按 code 合并上市日期与业绩报表（纯函数，不做任何单位换算）。"""
    return snapshot.merge(listing, on="code", how="left").merge(earnings, on="code", how="left")


_SNAPSHOT_CACHE: tuple[str, pd.DataFrame] | None = None


def _cache_key() -> str:
    return date.today().isoformat()


def market_snapshot_cached() -> pd.DataFrame:
    """当日首次调用拉取全市场快照（约 3.5 分钟），同日后续调用直接命中缓存。"""
    global _SNAPSHOT_CACHE
    key = _cache_key()
    if _SNAPSHOT_CACHE is not None and _SNAPSHOT_CACHE[0] == key:
        return _SNAPSHOT_CACHE[1]
    frame = fetch_market_snapshot()
    _SNAPSHOT_CACHE = (key, frame)
    return frame


def snapshot_cache_state() -> bool:
    return _SNAPSHOT_CACHE is not None and _SNAPSHOT_CACHE[0] == _cache_key()


def market_code_index() -> pd.DataFrame:
    """全市场 code→name 索引，供自选搜索与名称解析复用当日快照缓存。

    只保留 baostock 支持的 0/3/6 开头代码：搜出来却同步不了的票（如北交所）没有意义。
    """
    snap = market_snapshot_cached()
    df = snap[["code", "name"]].dropna()
    df["name"] = df["name"].astype(str).str.strip()
    keep = df["code"].map(is_supported) & df["name"].ne("")
    return df[keep].drop_duplicates(subset=["code"]).reset_index(drop=True)


def clear_snapshot_cache() -> None:
    global _SNAPSHOT_CACHE
    _SNAPSHOT_CACHE = None