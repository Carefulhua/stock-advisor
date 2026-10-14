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


def _pct(now: float, base: float) -> float:
    return (now / base - 1) * 100


def _ma_alignment(ma5: float, ma10: float, ma20: float, ma60: float) -> str:
    if ma5 > ma10 > ma20 > ma60:
        return "多头排列（MA5>MA10>MA20>MA60）"
    if ma5 < ma10 < ma20 < ma60:
        return "空头排列（MA5<MA10<MA20<MA60）"
    return "交织状态（未形成多头/空头排列）"


def _macd_streak(hist: pd.Series) -> str:
    """最近一根柱相对前一根的变化方向与连续天数。"""
    h = hist.dropna().tail(30)
    if len(h) < 2:
        return "样本不足"
    diffs = h.diff().dropna()
    direction = 1 if diffs.iloc[-1] > 0 else (-1 if diffs.iloc[-1] < 0 else 0)
    if direction == 0:
        return "与前一日基本持平"
    streak = 0
    for v in reversed(diffs.tolist()):
        d = 1 if v > 0 else (-1 if v < 0 else 0)
        if d != direction:
            break
        streak += 1
    word = "连续放大" if direction > 0 else "连续缩小"
    return f"已{word} {streak} 日"


def _zone_rsi(value: float) -> str:
    if value >= 70:
        return "处于70以上（传统经验的超买参考区）"
    if value <= 30:
        return "处于30以下（传统经验的超卖参考区）"
    return "处于30-70之间（中性区间）"


def _zone_kdj_j(value: float) -> str:
    if value >= 100:
        return "J值>=100（传统经验的高位参考）"
    if value <= 0:
        return "J值<=0（传统经验的低位参考）"
    return "J值处于0-100之间"


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
    ma5_series = ind.moving_average(close, 5)
    ma10_series = ind.moving_average(close, 10)
    ma20_series = ind.moving_average(close, 20)
    ma60_series = ind.moving_average(close, 60)
    ma5, ma10, ma20, ma60 = (
        ma5_series.iloc[-1], ma10_series.iloc[-1], ma20_series.iloc[-1], ma60_series.iloc[-1]
    )
    dif, dea, hist = ind.macd(close)
    k, d, j = ind.kdj(quotes["high"], quotes["low"], close)
    rsi14 = ind.rsi(close, 14)

    lines.append(f"## 技术指标（{last_date} 最新一根，基于全部日线计算）")
    lines.append(
        f"MA5={ma5:.3f}  MA10={ma10:.3f}  MA20={ma20:.3f}  MA60={ma60:.3f}"
    )
    lines.append(f"均线排列: {_ma_alignment(ma5, ma10, ma20, ma60)}")
    lines.append(f"收盘价相对MA20: {(_pct(float(last['close']), float(ma20))):+.2f}%")
    lines.append(
        f"DIF={dif.iloc[-1]:.4f}  DEA={dea.iloc[-1]:.4f}  MACD柱={hist.iloc[-1]:.4f}  "
        f"MACD柱变化: {_macd_streak(hist)}  "
        f"RSI14={rsi14.iloc[-1]:.2f}（{_zone_rsi(float(rsi14.iloc[-1]))}）  "
        f"K={k.iloc[-1]:.2f}  D={d.iloc[-1]:.2f}  J={j.iloc[-1]:.2f}（{_zone_kdj_j(float(j.iloc[-1]))}）"
    )

    n = len(quotes)
    period_lines = []
    for label, days in (("近5日", 5), ("近20日", 20), ("近60日", 60)):
        if n > days:
            period_lines.append(f"{label}: {_pct(float(last['close']), float(quotes['close'].iloc[-1 - days])):+.2f}%")
    if period_lines:
        lines.append(f"多周期涨跌幅（相对区间起点收盘）:  {'  '.join(period_lines)}")

    vol_recent = quotes["amount"].tail(5).mean()
    vol_prev = quotes["amount"].iloc[-25:-5].mean() if n >= 25 else float("nan")
    if vol_prev == vol_prev:  # not NaN
        lines.append(
            f"量能对比: 近5日日均成交额 {vol_recent:.0f}元, "
            f"其前20日日均 {vol_prev:.0f}元, 比值 {vol_recent / vol_prev:.2f}"
        )
    lines.append(f"最新单日换手率: {float(last['turnover']):.2f}%")

    if n >= 20:
        hi20 = float(recent["high"].max())
        lo20 = float(recent["low"].min())
        last_close = float(last["close"])
        if lo20 < hi20:
            pos = (last_close - lo20) / (hi20 - lo20) * 100
            lines.append(
                f"近20日价格位置: 最高 {hi20}  最低 {lo20}, "
                f"收盘位于该区间的 {pos:.0f}% 处（0%=贴最低, 100%=贴最高）"
            )

    lines.append("## 财务摘要")
    if financials.empty:
        lines.append("财务数据未同步。")
        fin_note = "未同步"
    else:
        recent_fin = financials.tail(3)
        fin_note = str(recent_fin.iloc[-1].get("日期", "未知"))
        lines.append(f"财务数据截至: {fin_note}（按报告期从旧到新列出最近3期）")
        for field in FINANCIAL_FIELDS:
            if field not in financials.columns:
                continue
            values = " → ".join(str(v) for v in recent_fin[field].tolist())
            lines.append(f"{field}: {values}")

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
