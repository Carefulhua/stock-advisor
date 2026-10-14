"""周期重采样：把日线 OHLCV 聚合成周/月/季/年 K 线，供图表切换周期。"""
from __future__ import annotations

import pandas as pd

BAR_PERIODS = ("day", "week", "month", "quarter", "year")

# pandas 频率别名 -> to_period 周期别名（周以自然周为单位，月末/季末/年末为边界）
_PERIOD_FREQ = {"week": "W", "month": "M", "quarter": "Q", "year": "Y"}

_AGG = {
    "date": "last",
    "open": "first",
    "high": "max",
    "low": "min",
    "close": "last",
    "volume": "sum",
    "amount": "sum",
}


def resample_bars(df: pd.DataFrame, period: str) -> pd.DataFrame:
    """按 period 聚合日线为该周期 K 线；date 取周期内最后一个交易日。"""
    if period not in BAR_PERIODS:
        raise ValueError(f"unsupported period: {period}")
    if period == "day":
        return df.reset_index(drop=True)
    keys = df["date"].dt.to_period(_PERIOD_FREQ[period])
    return df.groupby(keys, sort=True).agg(_AGG).reset_index(drop=True)
