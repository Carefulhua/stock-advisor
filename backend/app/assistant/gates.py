"""报告质量门禁：完整性 / 数值一致性 / 信息密度。

方法论来源：equity-researcher 的 13 项完整性检查（缺字段降级而非硬凑）、
Kenneth2378 的 numeric validation gate 与 depth gate。

三个门禁都在 LLM 生成之后、报告落库之前按纯函数执行：
报告不达标时拒绝落库，返回显式的缺失清单，而不是交付一份薄报告。
"""
from __future__ import annotations

import re

# 六节模板的章节标题正则。generate 时模板固定，故只需匹配序号前缀。
SECTION_PATTERN = re.compile(r"^##\s*[一二三四五六]、", re.MULTILINE)

EXPECTED_SECTIONS = 6

# context.py 实际能提供的上下文节，与 build_context_text 的输出一一对应。
CONTEXT_SECTIONS = [
    "行情摘要",
    "技术指标",
    "资金面",
    "事件面",
    "财务摘要",
    "自选池",
]

NUMBER_PATTERN = re.compile(r"-?\d+(?:\.\d+)?\s*(?:%|元|亿元|万元|亿|万)")
AMOUNT_PATTERN = re.compile(r"(?P<value>-?[\d,]+(?:\.\d+)?)\s*(?P<unit>亿元|万元|亿|万|元)")
PERCENT_PATTERN = re.compile(r"-?[\d,]+(?:\.\d+)?\s*\)?\s*%")
# 财务摘要的写法是「净资产收益率(%): 12.34」「每股收益(元): 1.32」，单位写在列名
# 的括号里而非数字之后，故需额外匹配这种顺序，否则整个财务摘要进不了校验池。
LABELLED_NUMBER_PATTERN = re.compile(r"\((?:%|元)\)\s*[:：]?\s*(?P<value>-?[\d,]+(?:\.\d+)?)")

# Kenneth2378 depth gate 阈值：1500 字模板下，低于 800 字或带单位数字少于 12 个视为薄报告。
MIN_CHARS = 800
MIN_NUMBER_COUNT = 12

TOLERANCE = 0.02


def _to_yuan(value: str, unit: str) -> float:
    """把「1.5亿元」「23.4万元」「12.5元」统一换算成元，便于跨单位比对。"""
    number = float(value.replace(",", ""))
    if unit.startswith("亿"):
        return number * 1e8
    if unit.startswith("万"):
        return number * 1e4
    return number


def _is_plain_decimal(text: str, end: int) -> bool:
    """判断 match 结束处之后是否紧跟科学计数法的 e/E（如 6.028785e+12）。

    科学计数法解析不出完整量级，宁可漏掉该值也不要让错误量级污染校验池。
    """
    return end >= len(text) or text[end] not in "eE"


BARE_NUMBER_PATTERN = re.compile(r"(?<![\d.%])(\d+(?:\.\d+)?)(?![\d.%])")


def _parse_context_numbers(context: str) -> tuple[set[float], set[float], set[float]]:
    """从上下文提取数字，返回（带单位金额, 百分比, 裸数字）三个池。

    带单位池只收显式带单位的金额与百分比；裸数字（价格/排名/均线值）单独成池，
    仅用于把报告里「24.72元」这类复述与上下文中的裸「24.72」对上，不参与单位换算。
    科学计数法（如总资产 6.028785e+12）不解析：正则取不到小数部分会得到错误的
    量级，宁可漏掉该值也不要污染校验池。
    """
    amounts = {
        _to_yuan(m.group("value"), m.group("unit"))
        for m in AMOUNT_PATTERN.finditer(context)
    }
    amounts |= {
        float(m.group("value").replace(",", ""))
        for m in LABELLED_NUMBER_PATTERN.finditer(context)
        if _is_plain_decimal(context, m.end()) and m.group(0).startswith("(元)")
    }
    percents = {
        _percent_value(m.group(0)) for m in PERCENT_PATTERN.finditer(context)
    } | {
        float(m.group("value").replace(",", ""))
        for m in LABELLED_NUMBER_PATTERN.finditer(context)
        if m.group(0).startswith("(%")
    }
    bare = {
        float(m.group(1))
        for m in BARE_NUMBER_PATTERN.finditer(context)
        if _is_plain_decimal(context, m.end()) and _is_plain_decimal(context, m.start() - 1)
    }
    return amounts, percents, bare


def check_completeness(content: str) -> list[str]:
    """equity-researcher 13 项检查的代码化：报告必须包含全部六节标题。"""
    found = SECTION_PATTERN.findall(content)
    missing = EXPECTED_SECTIONS - len(found)
    if missing > 0:
        return [f"报告缺少 {missing} 个章节（应为六节，实际 {len(found)} 节）"]
    return []


def _report_number(text: str) -> tuple[float, str] | None:
    """把报告里的一个带单位数字解析成 (值, 口径)；无法解析则返回 None。

    百分比与金额共用 NUMBER_PATTERN 出口，但口径分开，避免把 72.45% 拿去和
    24.72 元 比较。
    """
    if PERCENT_PATTERN.search(text) is not None:
        return _percent_value(text), "percent"
    match = AMOUNT_PATTERN.search(text)
    if match is None:
        return None
    return _to_yuan(match.group("value"), match.group("unit")), "amount"


def _percent_value(text: str) -> float:
    return float(text.replace(",", "").split(")")[-1].rstrip("%"))


def check_numeric(content: str, context: str) -> list[str]:
    """Kenneth2378 numeric validation gate：报告中每个带单位的数字都要能在上下文找到。

    带单位金额与百分比按各自口径 + TOLERANCE 容许的单位换算/四舍五入比对；
    裸数字池只做精确相等比对，仅用于把「24.72元」与上下文里的裸「24.72」对上，
    不参与单位换算，否则编造的金额会借单位换算绕过校验。
    """
    amounts, percents, bare = _parse_context_numbers(context)
    if not amounts and not percents and not bare:
        return []
    problems: list[str] = []
    for match in NUMBER_PATTERN.finditer(content):
        parsed = _report_number(match.group(0))
        if parsed is None:
            continue
        value, kind = parsed
        if value in bare:
            continue
        pool = percents if kind == "percent" else amounts
        if not any(abs(value - c) <= max(TOLERANCE * abs(c), TOLERANCE) for c in pool):
            problems.append(f"数字 {match.group(0)} 在上下文中无对应值")
            if len(problems) >= 5:
                break
    return problems


def check_depth(content: str) -> list[str]:
    """Kenneth2378 depth gate：字数与数字密度不达标即拒绝落库。"""
    problems: list[str] = []
    body = re.sub(r"\s", "", content)
    if len(body) < MIN_CHARS:
        problems.append(f"报告过薄：{len(body)} 字 < {MIN_CHARS} 字下限")
    numbers = len(NUMBER_PATTERN.findall(content))
    if numbers < MIN_NUMBER_COUNT:
        problems.append(f"数字密度不足：{numbers} 个 < {MIN_NUMBER_COUNT} 个下限")
    return problems


def validate_report(content: str, context: str) -> list[str]:
    """汇总三个门禁的问题清单；空列表表示可以落库。"""
    problems = check_completeness(content)
    problems += check_numeric(content, context)
    problems += check_depth(content)
    return problems
