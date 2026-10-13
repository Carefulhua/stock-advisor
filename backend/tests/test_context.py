import pandas as pd
import pytest

from app.assistant.context import WATCH_HINT, build_context_text
from app.data.storage import QUOTE_COLUMNS


def make_quotes(n: int = 60) -> pd.DataFrame:
    dates = pd.date_range("2026-07-01", periods=n, freq="B")
    rows = []
    for i, dt in enumerate(dates):
        c = 10.0 + i
        prev = c - 1 if i else c
        rows.append({
            "date": dt, "code": "300001", "open": c - 0.5, "close": c,
            "high": c + 1.0, "low": c - 1.0, "volume": 1_000_000 + i,
            "amount": 2e8, "amplitude": 2.0,
            "pct_chg": (c / prev - 1) * 100, "chg": c - prev, "turnover": 1.5,
        })
    return pd.DataFrame(rows, columns=QUOTE_COLUMNS)


def test_sections_recent20_interval_and_fallbacks():
    q = make_quotes(60)
    text = build_context_text("300001", q, pd.DataFrame(), None)
    assert "## 行情摘要" in text
    assert "## 技术指标" in text
    assert "## 财务摘要" in text
    assert "## 自选池" in text
    date_lines = [ln for ln in text.splitlines() if ln.startswith("2026-")]
    assert len(date_lines) == 20
    # recent20 首收盘=50, 末收盘=69 -> (69/50-1)*100 = 38.00%
    assert "38.00%" in text
    assert "日均成交额" in text and "亿元" in text
    assert "MA5=" in text and "RSI14=" in text and "MACD柱=" in text
    assert WATCH_HINT in text
    assert "财务数据未同步。" in text
    assert f"数据截至 {q.iloc[-1]['date'].strftime('%Y-%m-%d')}" in text


def test_financial_and_watch_present():
    q = make_quotes(60)
    fin = pd.DataFrame([{
        "日期": "2026-09-30 00:00:00",
        "净资产收益率(%)": 12.34,
        "销售毛利率(%)": 45.6,
    }])
    text = build_context_text("300001", q, fin, {"score": 71.37, "rank": 1})
    assert "净资产收益率(%): 12.34" in text
    assert "销售毛利率(%): 45.6" in text
    assert "财务数据截至 2026-09-30" in text
    assert "score=71.37" in text and "rank=1" in text
    assert WATCH_HINT not in text


def test_empty_quotes_raises():
    with pytest.raises(ValueError):
        build_context_text("000000", pd.DataFrame(columns=QUOTE_COLUMNS), pd.DataFrame(), None)
