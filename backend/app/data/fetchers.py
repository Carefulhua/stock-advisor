"""akshare 数据采集封装。

所有函数返回规范化 DataFrame; 网络失败向上抛出, 由同步层决定重试/跳过。
"""
from __future__ import annotations

import logging
import random
import time

import akshare as ak
import pandas as pd

from app.core import config

logger = logging.getLogger(__name__)

# akshare 中文列名 -> 英文规范列名
_HIST_COLUMN_MAP = {
    "日期": "date",
    "股票代码": "code",
    "开盘": "open",
    "收盘": "close",
    "最高": "high",
    "最低": "low",
    "成交量": "volume",
    "成交额": "amount",
    "振幅": "amplitude",
    "涨跌幅": "pct_chg",
    "涨跌额": "chg",
    "换手率": "turnover",
}


def _throttle() -> None:
    time.sleep(config.REQUEST_INTERVAL_SEC)


def _with_retry(fn, *args, attempts: int = 4, **kwargs):
    """网络请求重试: 指数退避 + 随机抖动，应对数据源限频断连。

    限频冷却可能持续分钟级，退避基数较大 (5s → 10s → 20s)。
    """
    last_exc: Exception | None = None
    for i in range(attempts):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001 - 数据源异常类型不可控
            last_exc = exc
            if i == attempts - 1:
                break
            backoff = 5 * (2**i) + random.uniform(0, 2)
            logger.warning(
                "%s failed (attempt %s/%s), retry in %.1fs: %s",
                getattr(fn, "__name__", "fetch"), i + 1, attempts, backoff, exc,
            )
            time.sleep(backoff)
    raise last_exc


def fetch_stock_list() -> pd.DataFrame:
    """全市场 A 股代码+名称。"""
    _throttle()
    df = _with_retry(ak.stock_info_a_code_name)
    df = df[["code", "name"]].copy()
    df["code"] = df["code"].astype(str).str.zfill(6)
    return df.drop_duplicates(subset=["code"]).reset_index(drop=True)


def fetch_daily(
    code: str,
    start_date: str,
    end_date: str,
    adjust: str = "qfq",
) -> pd.DataFrame:
    """单只股票日线(前复权), 返回规范化英文列。"""
    _throttle()
    df = _with_retry(
        ak.stock_zh_a_hist,
        symbol=code,
        period="daily",
        start_date=start_date,
        end_date=end_date,
        adjust=adjust,
    )
    if df is None or df.empty:
        return pd.DataFrame(columns=list(_HIST_COLUMN_MAP.values()))
    df = df.rename(columns=_HIST_COLUMN_MAP)
    df["code"] = code
    df["date"] = pd.to_datetime(df["date"])
    df["volume"] = df["volume"] * 100  # 东财单位=手 -> 归一化为股
    numeric_cols = [
        "open", "close", "high", "low", "volume", "amount",
        "amplitude", "pct_chg", "chg", "turnover",
    ]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df[list(_HIST_COLUMN_MAP.values())]


def fetch_financials(code: str) -> pd.DataFrame:
    """单只股票主要财务指标(中文列名, 按报告期倒序)。"""
    _throttle()
    df = _with_retry(ak.stock_financial_analysis_indicator, symbol=code)
    if df is None or df.empty:
        return pd.DataFrame()
    # 去除 akshare 重复列名(保留首个)
    df = df.loc[:, ~pd.Index(df.columns).duplicated()]
    return df.reset_index(drop=True)
