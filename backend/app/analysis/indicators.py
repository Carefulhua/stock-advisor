"""技术指标计算（纯函数：输入收盘价/高低价序列，输出同长 Series）。"""
from __future__ import annotations

import pandas as pd


def moving_average(close: pd.Series, window: int) -> pd.Series:
    return close.rolling(window).mean()


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> tuple[pd.Series, pd.Series, pd.Series]:
    """返回 (DIF, DEA, MACD柱), MACD柱 = (DIF-DEA)*2。"""
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    dif = ema_fast - ema_slow
    dea = dif.ewm(span=signal, adjust=False).mean()
    hist = (dif - dea) * 2
    return dif, dea, hist


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Wilder 平滑 RSI; 无波动(全涨/全跌/恒定)时按边界 100/0/50 处理。"""
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - 100 / (1 + rs)
    rsi[avg_loss == 0] = 100.0
    rsi[(avg_gain == 0) & (avg_loss == 0)] = 50.0
    rsi[(avg_gain == 0) & (avg_loss > 0)] = 0.0
    return rsi


def kdj(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    n: int = 9,
    m1: int = 3,
    m2: int = 3,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """经典 KDJ(9,3,3); K/D 用 m1/m2 平滑, J=3K-2D。"""
    low_n = low.rolling(n, min_periods=1).min()
    high_n = high.rolling(n, min_periods=1).max()
    rsv = (close - low_n) / (high_n - low_n) * 100
    rsv = rsv.fillna(50.0)
    k = rsv.ewm(alpha=1 / m1, adjust=False).mean()
    d = k.ewm(alpha=1 / m2, adjust=False).mean()
    j = 3 * k - 2 * d
    return k, d, j
