"""解读助手上下文：纯函数拼装（数字全部来自计算层，LLM 只读不产生）。"""
from __future__ import annotations

import pandas as pd

from app.analysis import indicators as ind
from app.data.storage import QUOTE_COLUMNS, get_conn, read_financials, read_quotes

FINANCIAL_FIELDS = [
    "净资产收益率(%)",
    "销售毛利率(%)",
    "销售净利率(%)",
    "净利润增长率(%)",
    "主营业务收入增长率(%)",
    "资产负债率(%)",
    "每股收益(元)",
    "总资产(元)",
]

WATCH_HINT = "未入选当前自选池"


def _fmt_date(value: object) -> str:
    return pd.Timestamp(value).strftime("%Y-%m-%d")


def build_context_text(
    code: str,
    quotes: pd.DataFrame,
    financials: pd.DataFrame,
    watch: dict | None,
) -> str:
    if quotes.empty:
        raise ValueError(f"no quotes for {code}")

    recent = quotes.tail(20)
    last = recent.iloc[-1]
    last_date = _fmt_date(last["date"])

    lines = [f"## 行情摘要（{code}，近20个交易日）", "日期 | 收盘 | 涨跌幅%"]
    for _, row in recent.iterrows():
        lines.append(
            f"{_fmt_date(row['date'])} | {row['close']} | {row['pct_chg']:.2f}"
        )
    interval_chg = (last["close"] / recent.iloc[0]["close"] - 1) * 100
    avg_amount = float(recent["amount"].mean())
    lines.append(
        f"区间涨跌幅: {interval_chg:.2f}%  区间最高: {recent['high'].max()}  "
        f"区间最低: {recent['low'].min()}  "
        f"日均成交额: {avg_amount:.0f}元（约{avg_amount / 1e8:.2f}亿元）"
    )

    close = quotes["close"]
    dif, dea, hist = ind.macd(close)
    k, d, j = ind.kdj(quotes["high"], quotes["low"], close)
    rsi14 = ind.rsi(close, 14)
    lines.append(f"## 技术指标（{last_date} 最新一根，基于全部日线计算）")
    lines.append(
        f"MA5={ind.moving_average(close, 5).iloc[-1]:.3f}  "
        f"MA10={ind.moving_average(close, 10).iloc[-1]:.3f}  "
        f"MA20={ind.moving_average(close, 20).iloc[-1]:.3f}  "
        f"MA60={ind.moving_average(close, 60).iloc[-1]:.3f}"
    )
    lines.append(
        f"DIF={dif.iloc[-1]:.4f}  DEA={dea.iloc[-1]:.4f}  MACD柱={hist.iloc[-1]:.4f}  "
        f"RSI14={rsi14.iloc[-1]:.2f}  K={k.iloc[-1]:.2f}  D={d.iloc[-1]:.2f}  J={j.iloc[-1]:.2f}"
    )

    lines.append("## 财务摘要")
    if financials.empty:
        lines.append("财务数据未同步。")
        fin_note = "未同步"
    else:
        fin_last = financials.iloc[-1]
        fin_note = str(fin_last.get("日期", "未知"))
        lines.append(f"财务数据截至: {fin_note}")
        for field in FINANCIAL_FIELDS:
            if field in financials.columns:
                lines.append(f"{field}: {fin_last[field]}")

    if watch:
        lines.append(f"## 自选池\nscore={watch['score']}  rank={watch['rank']}")
    else:
        lines.append(f"## 自选池\n{WATCH_HINT}")

    lines.append(f"数据截至 {last_date}，财务数据截至 {fin_note}。")
    return "\n".join(lines)


def build_context(code: str) -> str:
    quotes = read_quotes(code)
    financials = read_financials(code)
    conn = get_conn()
    try:
        watch_df = pd.read_sql_query(
            "SELECT score, rank FROM watchlist WHERE code = ?", conn, params=(code,)
        )
    finally:
        conn.close()
    watch = None
    if not watch_df.empty:
        watch = {"score": watch_df.iloc[0]["score"], "rank": watch_df.iloc[0]["rank"]}
    return build_context_text(code, quotes, financials, watch)
