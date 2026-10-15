import pytest

from app.assistant import gates

CONTEXT = """## 行情摘要（600418，近20个交易日）
区间涨跌幅: 12.36%  区间最高: 24.72  区间最低: 12.0
日均成交额: 3273000000元（约32.73亿元）
## 技术指标
MA5=24.123  MA10=22.100
收盘价相对MA20: +5.20%
## 财务摘要
净资产收益率(%): -6.03
销售净利率(%): -3.2711
资产负债率(%): 72.4526
每股收益(元): 1.3241
总资产(元): 6.028785e+12
## 资金面
千股千评: 综合得分 61.09  机构参与度 0.3688  主力成本 21.73元  全市场排名 3244  市盈率 -30.72
龙虎榜(近一月统计): 上榜 3 次, 最近上榜日 2026-10-08, 龙虎榜净买额 4.03亿元, 近1个月涨跌幅 19.88%
大宗交易(近90日): 1 笔, 成交额合计 400.35万元, 平均折溢率 0.00%
## 事件面
业绩预告(报告期 20260630): 预告类型「减亏」, 预计值 -7.40亿元, 上年同期 -7.73亿元, 变动幅度 +4.25%
"""

GOOD_REPORT = """# 江淮汽车（600418）研究报告

## 一、投资要点
近20个交易日区间涨跌幅 12.36%，最新收盘 24.72元。
MACD 柱体变化、RSI14、均线排列见下节。

## 二、技术与量价
MA5=24.123 高于 MA20，均线呈多头排列。最新单日换手率与近5日量能比如下：
近5日 vs 前20日量能比值 2.10。

## 三、量能与资金面
千股千评综合得分 61.09，机构参与度 0.3688，主力成本 21.73元，全市场排名 3244。
龙虎榜近一月上榜 3 次，净买额 4.03亿元，最近上榜日 2026-10-08。
大宗交易近90日 1 笔，成交额合计 400.35万元，平均折溢率 0.00%。

## 四、财务分析与业绩预告
净资产收益率 -6.03%，销售净利率 -3.27%，资产负债率 72.45%，每股收益 1.32元。
业绩预告为减亏，预计值 -7.40亿元，上年同期 -7.73亿元，变动幅度 +4.25%。

## 五、风险提示
- 资产负债率 72.45% 偏高，偿债压力需跟踪。

## 六、结论
综合来看，基本面仍处修复初期，可跟踪三个信号：预告准确性、龙虎榜资金持续性、量能比值。
"""


def _pad(text: str, target: int) -> str:
    filler = "\n".join("补充说明文字" for _ in range(max(0, target - len(text) // 2)))
    return text + "\n" + filler


def test_completeness_accepts_all_six_sections():
    assert gates.check_completeness(GOOD_REPORT) == []


def test_completeness_reports_missing_sections():
    partial = GOOD_REPORT.replace("## 六、结论", "")
    problems = gates.check_completeness(partial)
    assert len(problems) == 1
    assert "1" in problems[0]


def test_numeric_accepts_all_context_values():
    assert gates.check_numeric(GOOD_REPORT, CONTEXT) == []


def test_numeric_flags_fabricated_percent():
    bad = GOOD_REPORT.replace("-6.03%", "-44.44%")
    problems = gates.check_numeric(bad, CONTEXT)
    assert problems == ["数字 -44.44% 在上下文中无对应值"]


def test_numeric_flags_fabricated_amount():
    bad = GOOD_REPORT.replace("21.73元", "88.88元")
    problems = gates.check_numeric(bad, CONTEXT)
    assert problems == ["数字 88.88元 在上下文中无对应值"]


def test_numeric_flags_fabricated_yi_amount():
    bad = GOOD_REPORT.replace("4.03亿元", "12.34亿元")
    problems = gates.check_numeric(bad, CONTEXT)
    assert problems == ["数字 12.34亿元 在上下文中无对应值"]


def test_numeric_accepts_unit_conversion():
    """4.03亿元 与上下文的 403000000 元 是同一量级，应视为有出处。"""
    amount_context = "龙虎榜净买额 403000000元"
    amount_report = "净买额约 4.03亿元。"
    assert gates.check_numeric(amount_report, amount_context) == []


def test_numeric_matches_bare_price_only_by_equality():
    """裸价格只做精确相等：报告复述「24.72元」应通过，编造「24.73元」仍须被抓。"""
    context = "区间最高: 24.72"
    assert gates.check_numeric("收盘 24.72元。", context) == []
    assert gates.check_numeric("收盘 24.73元。", context) == ["数字 24.73元 在上下文中无对应值"]


def test_numeric_parses_labelled_financial_rows():
    context = "净资产收益率(%): -6.03\n每股收益(元): 1.3241"
    report = "净资产收益率 -6.03%，每股收益 1.32元。"
    assert gates.check_numeric(report, context) == []


def test_numeric_skips_scientific_notation():
    """6.028785e+12 截断成 6.028785 会得到错误量级，必须跳过而非入池。"""
    amounts, percents, bare = gates._parse_context_numbers("总资产(元): 6.028785e+12")
    assert 6.028785 not in amounts
    assert 6028785000000.0 not in amounts


def test_numeric_empty_context_skips_check():
    assert gates.check_numeric("任意 12.36%", "") == []


def test_depth_rejects_thin_report():
    problems = gates.check_depth("## 一、投资要点\n内容太少")
    assert any("过薄" in p for p in problems)
    assert any("数字密度不足" in p for p in problems)


def test_depth_accepts_dense_report():
    dense = _pad(
        "".join(f"第{i}项指标 12.36%。\n" for i in range(gates.MIN_NUMBER_COUNT + 2)),
        900,
    )
    assert gates.check_depth(dense) == []


def test_validate_report_collects_all_dimensions():
    assert gates.validate_report(_pad(GOOD_REPORT, 1000), CONTEXT) == []


def test_validate_report_reports_every_failing_gate():
    problems = gates.validate_report("## 一、投资要点\n编造 99.99%", CONTEXT)
    assert any("章节" in p for p in problems)
    assert any("99.99" in p for p in problems)
    assert any("过薄" in p or "数字密度" in p for p in problems)


def test_validate_report_accepts_real_shaped_report():
    """数值门禁必须放行一份真实形状的报告，而非只对玩具数据有效。"""
    report = _pad(GOOD_REPORT, 1000)
    assert gates.check_completeness(report) == []
    assert gates.check_numeric(report, CONTEXT) == []
    assert gates.check_depth(report) == []
