"""个股研究报告生成：六节结构化模板 + 组装 LLM 消息。

模板骨架取自券商研究报告样例（天顺风能研究报告），但只保留学习工具数据能覆盖的章节，
宏观/行业/估值等无数据支撑的节已剔除；确有缺失的数据在该节内明写"数据不足"，不编造。
数据覆盖范围：行情与技术指标、财务三期、自选池、资金面（千股千评/龙虎榜/大宗交易）、
事件面（业绩预告）。
"""
from __future__ import annotations

REPORT_SYSTEM_TEMPLATE = """你是一位A股研究员，正在为学习工具撰写个股研究报告。请基于下方数据上下文，按固定六节结构输出 Markdown 报告。

三条红线（必须遵守）：
1. 只做研究与分析，不给买卖点，不预测目标涨跌，不出现"建议买入/卖出/加仓/减仓"等操作建议。
2. 所有数字只能引用上下文中出现的数字，禁止自行计算或编造；上下文未提供的信息（行业格局、宏观政策、估值分位、机构持仓、融资融券、股东户数、公告与新闻）明确说明无法覆盖，不得虚构。上下文已提供业绩预告，但不等于覆盖全部公告与消息面。
3. 必须给出数据截止日期（上下文最后一行给出）。

输出结构（严格按此六节，用 "## 一、xxx" 到 "## 六、xxx" 作二级标题）：
## 一、投资要点：3-4 条要点，每条先给结论再给依据
## 二、技术与量价：均线排列、收盘相对MA20偏离、MACD 及其柱体变化、RSI14/KDJ 所处区间、近5/20/60日多周期涨跌幅、近20日价格位置
## 三、量能与资金面：区间日均成交额、近5日与前20日量能比值、最新换手率、千股千评（综合得分/机构参与度/主力成本/市场关注指数/全市场排名）、龙虎榜上榜次数与净买额、大宗交易笔数与折溢率
## 四、财务分析与业绩预告：盈利与偿债结构（用 Markdown 表格列示最近3期关键指标对比）、千股千评市盈率、业绩预告的预告类型/预计值/同比变动/业绩变动原因
## 五、风险提示：bullet 列表，每条一个风险，依据只能来自上文事实
## 六、结论：一段总结 + 3 个可验证跟踪信号

格式要求：
- 开头用一级标题 "# {name}（{code}）研究报告"，其下注明主题/数据截止/研究性质。
- 关键多期数据对比用 Markdown 表格呈现。
- 每个专业术语首次出现时用一句话通俗解释。
- 总篇幅 1500 字以内，语言平实，不写空话套话。
- 上下文确实缺少某类数据时，在该节内写明"数据不足"，不要跳过标题、不要硬凑。
"""


def build_report_messages(context: str, name: str, code: str) -> list[dict]:
    """组装生成研究报告所需的 messages（system + 单条 user）。"""
    system = REPORT_SYSTEM_TEMPLATE.replace("{name}", str(name)).replace(
        "{code}", str(code)
    )
    return [
        {"role": "system", "content": system},
        {
            "role": "user",
            "content": f"请基于以下数据上下文撰写研究报告：\n\n{context}",
        },
    ]


INTERPRETATION_HEADING = "## AI解读追踪"


def append_interpretation(
    content: str, question: str, reply: str, timestamp: str
) -> str:
    """把一次 AI 解读追加到报告的「AI解读追踪」区。

    采用追加而非重写：已生成的六节分析保持不变，新解读按时间顺序沉淀，可回溯且不会损坏正文。
    """
    entry = f"\n### {timestamp}\n\n**问**：{question}\n\n**答**：{reply}\n"
    if INTERPRETATION_HEADING in content:
        return content + entry
    return content.rstrip() + "\n\n" + INTERPRETATION_HEADING + "\n" + entry
