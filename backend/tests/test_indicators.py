import numpy as np
import pandas as pd
import pytest

from app.analysis import indicators


def _closes(vals):
    return pd.Series([float(v) for v in vals])


def test_ma_matches_pandas_mean():
    closes = _closes([1, 2, 3, 4, 5, 6, 7])
    got = indicators.moving_average(closes, 3)
    assert list(got[:2]) == [pytest.approx(np.nan, nan_ok=True), pytest.approx(np.nan, nan_ok=True)]
    assert list(got[2:]) == [pytest.approx(2.0), pytest.approx(3.0), pytest.approx(4.0), pytest.approx(5.0), pytest.approx(6.0)]


def test_macd_zero_on_constant_series():
    closes = _closes([10.0] * 50)
    dif, dea, hist = indicators.macd(closes)
    assert dif.abs().max() < 1e-9
    assert dea.abs().max() < 1e-9
    assert hist.abs().max() < 1e-9


def test_macd_dif_positive_on_uptrend():
    closes = _closes([float(i) for i in range(1, 60)])
    dif, dea, hist = indicators.macd(closes)
    assert dif.iloc[-1] > 0
    assert hist.iloc[-1] > 0


def test_rsi_bounds_and_constant():
    constant = _closes([5.0] * 30)
    r = indicators.rsi(constant, 14)
    assert r.iloc[-1] == 0.0 or np.isnan(r.iloc[-1]) or r.iloc[-1] == 50.0
    up = _closes([float(i) for i in range(1, 40)])
    r_up = indicators.rsi(up, 14)
    assert 0 <= r_up.iloc[-1] <= 100
    assert r_up.iloc[-1] > 70
    down = _closes([float(40 - i) for i in range(1, 40)])
    r_down = indicators.rsi(down, 14)
    assert r_down.iloc[-1] < 30


def test_kdj_bounds_and_classic_values():
    n = 40
    rng = np.random.default_rng(7)
    close = pd.Series(100 + rng.normal(0, 2, n).cumsum())
    high = close + rng.uniform(0.5, 2.0, n)
    low = close - rng.uniform(0.5, 2.0, n)
    k, d, j = indicators.kdj(high, low, close)
    assert ((k >= 0) & (k <= 100)).all()
    assert ((d >= 0) & (d <= 100)).all()
    assert len(j) == n


def test_kdj_strict_uptrend_k_near_100():
    n = 20
    close = pd.Series([100.0 + i for i in range(n)])
    high = close + 1.0
    low = close - 1.0
    k, d, j = indicators.kdj(high, low, close)
    assert k.iloc[-1] > 80
    assert j.iloc[-1] > k.iloc[-1]
