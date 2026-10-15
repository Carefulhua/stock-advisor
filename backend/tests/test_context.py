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
    fin = pd.DataFrame([
        {"日期": "2026-03-31 00:00:00", "净资产收益率(%)": 10.0, "销售毛利率(%)": 40.0},
        {"日期": "2026-06-30 00:00:00", "净资产收益率(%)": 11.5, "销售毛利率(%)": 42.0},
        {"日期": "2026-09-30 00:00:00", "净资产收益率(%)": 12.34, "销售毛利率(%)": 45.6},
    ])
    text = build_context_text("300001", q, fin, {"score": 71.37, "rank": 1})
    assert "净资产收益率(%): 10.0 → 11.5 → 12.34" in text
    assert "销售毛利率(%): 40.0 → 42.0 → 45.6" in text
    assert "财务数据截至 2026-09-30" in text
    assert "score=71.37" in text and "rank=1" in text
    assert WATCH_HINT not in text


def test_enriched_signals():
    q = make_quotes(80)
    text = build_context_text("300001", q, pd.DataFrame(), None)
    assert "均线排列: 多头排列" in text  # 单调上涨数据必然多头
    assert "MACD柱变化" in text
    assert "RSI14=" in text and "超买参考区" in text  # 单调上涨 -> RSI=100
    assert "多周期涨跌幅" in text and "近5日" in text and "近60日" in text
    assert "量能对比" in text  # amount 恒定-> 比值1.00
    assert "最新单日换手率: 1.50%" in text
    assert "近20日价格位置" in text


def test_streak_and_zone_helpers():
    from app.assistant.context import _macd_streak, _zone_rsi

    hist = pd.Series([0.1, 0.3, 0.6, 1.0])  # 连续放大3次
    assert "连续放大 3 日" in _macd_streak(hist)
    hist_down = pd.Series([1.0, 0.7, 0.4, 0.1])
    assert "连续缩小 3 日" in _macd_streak(hist_down)
    assert "超买" in _zone_rsi(75.0)
    assert "超卖" in _zone_rsi(25.0)
    assert "中性" in _zone_rsi(50.0)


def test_empty_quotes_raises():
    with pytest.raises(ValueError):
        build_context_text("000000", pd.DataFrame(columns=QUOTE_COLUMNS), pd.DataFrame(), None)


def _extra(**overrides) -> dict:
    data = {
        "comment": {
            "综合得分": 61.09, "机构参与度": 0.36882, "主力成本": 21.73,
            "关注指数": 96.0, "目前排名": 3244.0, "市盈率": -31.75,
        },
        "lhb": {
            "最近上榜日": "2026-10-08", "上榜次数": 3,
            "龙虎榜净买额": 402660474.63, "机构买入净额": 0.0,
            "近1个月涨跌幅": 19.88360815,
        },
        "dzjy": {
            "笔数": 1, "成交额合计": 4003500.0, "平均折溢率": 0.0,
            "最近交易日期": "2026-08-05", "最近成交价": 25.5, "最近收盘价": 25.5,
            "最近买方营业部": "A营业部", "最近卖方营业部": "B营业部",
        },
        "forecast": {
            "报告期": "20260630", "预测指标": "归属于上市公司股东的净利润",
            "预告类型": "减亏", "业绩变动幅度": 4.25, "预测数值": -740000000.0,
            "上年同期值": -772811700.0, "业绩变动原因": "(一)销量同比下滑。",
            "公告日期": "2026-07-09",
        },
    }
    data.update(overrides)
    return data


def test_capital_and_event_sections_when_extra_provided():
    q = make_quotes(60)
    text = build_context_text("600418", q, pd.DataFrame(), None, _extra())

    assert "## 资金面" in text and "## 事件面" in text
    assert "千股千评: 综合得分 61.09" in text
    assert "机构参与度 0.3688" in text
    assert "主力成本 21.73元" in text
    assert "全市场排名 3244" in text
    assert "龙虎榜(近一月统计): 上榜 3 次" in text
    assert "最近上榜日 2026-10-08" in text
    assert "龙虎榜净买额 4.03亿元" in text
    assert "近1个月涨跌幅 19.88%" in text
    assert "大宗交易(近90日): 1 笔" in text
    assert "成交额合计 400.35万元" in text
    assert "平均折溢率 0.00%" in text
    assert "业绩预告(报告期 20260630, 公告日 2026-07-09)" in text
    assert "预告类型「减亏」" in text
    assert "预计值 -7.40亿元" in text
    assert "上年同期 -7.73亿元" in text
    assert "变动幅度 4.25%" in text
    assert "业绩变动原因: (一)销量同比下滑。" in text


def test_no_capital_sections_without_extra():
    q = make_quotes(60)
    text = build_context_text("600418", q, pd.DataFrame(), None)
    assert "## 资金面" not in text
    assert "## 事件面" not in text


def test_capital_sections_fall_back_when_all_sources_empty():
    q = make_quotes(60)
    empty = {key: None for key in ("comment", "lhb", "dzjy", "forecast")}
    text = build_context_text("600418", q, pd.DataFrame(), None, empty)

    assert "千股千评: 无该股数据" in text
    assert "龙虎榜(近一月统计): 无上榜记录" in text
    assert "大宗交易(近90日): 无记录" in text
    assert "业绩预告: 无该股数据" in text


def test_missing_numeric_values_show_marker():
    q = make_quotes(60)
    text = build_context_text(
        "600418", q, pd.DataFrame(), None,
        _extra(lhb={"最近上榜日": "", "上榜次数": None, "龙虎榜净买额": None,
                    "机构买入净额": None, "近1个月涨跌幅": None}),
    )
    assert "上榜 数据缺失 次" in text
    assert "龙虎榜净买额 数据缺失" in text
    assert "最近上榜日 未知" in text


def test_financial_nan_shows_missing_marker_not_literal_nan():
    q = make_quotes(60)
    fin = pd.DataFrame([
        {"日期": "2026-03-31", "净资产收益率(%)": 10.0, "销售毛利率(%)": float("nan")},
        {"日期": "2026-06-30", "净资产收益率(%)": 11.5, "销售毛利率(%)": float("nan")},
        {"日期": "2026-09-30", "净资产收益率(%)": 12.34, "销售毛利率(%)": float("nan")},
    ])
    text = build_context_text("300001", q, fin, None)

    assert "nan" not in text.lower()
    assert "销售毛利率(%): 数据缺失 → 数据缺失 → 数据缺失" in text
    assert "净资产收益率(%): 10.0 → 11.5 → 12.34" in text


def test_financial_nan_date_falls_back_to_unknown():
    q = make_quotes(60)
    fin = pd.DataFrame([
        {"日期": float("nan"), "净资产收益率(%)": 10.0},
        {"日期": float("nan"), "净资产收益率(%)": 11.5},
    ])
    text = build_context_text("300001", q, fin, None)

    assert "财务数据截至: 未知" in text
    assert "nan" not in text.lower()


def test_long_window_high_low_anchors_with_dates():
    q = make_quotes(130)
    text = build_context_text("300001", q, pd.DataFrame(), None)

    last = q.iloc[-1]
    # 单调上涨数据：窗口内最高必为最后一根，故日期应为最后交易日
    assert (
        f"近1个月区间高低点: 最高 {last['high']}"
        f"（{last['date'].strftime('%Y-%m-%d')}）" in text
    )
    assert "近3个月区间高低点: 最高" in text
    assert "近半年区间高低点: 最高" in text
    assert "近1年区间高低点" not in text
    assert "近120日:" in text

