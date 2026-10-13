"""三路数据拉取与合并：市场快照 / 上市日期 / 业绩增速。"""
from __future__ import annotations

import akshare as ak
import pandas as pd

from app.data.fetchers import _with_retry


def fetch_market_snapshot() -> pd.DataFrame:
    """全市场快照(腾讯): code, name, amount(元), pe(TTM), float_mv(元)。

    东财 push2 按 IP 限频会整段封禁, 快照改走腾讯; turnover 单位万元, ltsz 单位亿元。
    """
    raw = _with_retry(ak.stock_zh_a_spot_tx)
    df = raw[["code", "name", "turnover", "pe_ttm", "ltsz"]].copy()
    df.columns = ["code", "name", "amount", "pe", "float_mv"]
    df["code"] = df["code"].astype(str).str[-6:].str.zfill(6)
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce") * 1e4
    df["pe"] = pd.to_numeric(df["pe"], errors="coerce")
    df["float_mv"] = pd.to_numeric(df["float_mv"], errors="coerce") * 1e8
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


def fetch_earnings_growth(date: str) -> pd.DataFrame:
    """业绩报表净利润同比增速: code, profit_yoy(%)。date 形如 20260630。

    用 stock_yjbb_em(业绩报表, 全市场); stock_yjkb_em 是业绩快报(仅少数公司)。
    """
    raw = _with_retry(ak.stock_yjbb_em, date=date)
    df = raw[["股票代码", "净利润-同比增长"]].copy()
    df.columns = ["code", "profit_yoy"]
    df["code"] = df["code"].astype(str).str.zfill(6)
    df["profit_yoy"] = pd.to_numeric(df["profit_yoy"], errors="coerce")
    return df.drop_duplicates(subset=["code"]).reset_index(drop=True)


def merge_snapshot(
    snapshot: pd.DataFrame,
    listing: pd.DataFrame,
    earnings: pd.DataFrame,
) -> pd.DataFrame:
    """以快照为左表按 code 合并上市日期与业绩增速。"""
    return snapshot.merge(listing, on="code", how="left").merge(earnings, on="code", how="left")
