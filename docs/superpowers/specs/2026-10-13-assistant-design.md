# P3 解读助手（AI Assistant）设计

日期：2026-10-13
状态：已与用户确认设计，待 spec 审阅

## 目标

在 P2 分析页右侧提供 AI 对话侧边栏，对当前股票的行情、技术指标、财务数据做解读。
LLM 只做解释，永不给买卖点；所有数字由后端计算层生成并注入，LLM 不产生数字。

## 决策记录（brainstorming 结论）

| 决策点 | 结论 |
|---|---|
| LLM 供应商 | 智谱 GLM（用户已有/申请 key），默认模型 `glm-4-flash`（免费），可换 `glm-4-plus` |
| 交互形态 | 分析页右侧可收合侧边栏对话 |
| 注入上下文 | 行情 + 技术 + 财务全量（计算层拼好注入，非工具按需查询） |
| 实现方式 | 后端代理 + SSE 流式（否决前端直调：key 暴露 + 违反数字来自计算层约定） |

## 架构与数据流

```
浏览器侧边栏 ──POST /api/chat {code, messages[]}──▶ FastAPI
                                                    │
                                    ┌───────────────┴───────────────┐
                                    │ 1. context.py 拼上下文块        │
                                    │    (read_quotes/indicators/    │
                                    │     read_financials/watchlist) │
                                    │ 2. system = 角色+硬约束+上下文  │
                                    │ 3. llm.py → 智谱 SSE           │
                                    └───────────────┬───────────────┘
                                                    ▼
                                    StreamingResponse (text/plain, 逐token)
```

### 后端新模块 `backend/app/assistant/`

- `context.py`：纯函数 `build_context(code) -> str`。读取该股日线 parquet（近20交易日）、
  `app/analysis/indicators.py` 现算指标、financials parquet 最近一期、watchlist 排名，
  拼成结构化文本块。数据缺失时对应小节写「未同步」而非编造。
- `llm.py`：httpx 直调智谱 REST `https://open.bigmodel.cn/api/paas/v4/chat/completions`，
  `Authorization: Bearer ${GLM_API_KEY}`，解析 SSE `data:` 行产出增量文本，`data: [DONE]` 结束。
  不引入智谱官方 SDK。
- `api/main.py` 新增 `POST /api/chat`：入参 `{code: str, messages: [{role, content}]}`。
  后端构造 `[system, *history, user]`，其中 system = 角色说明 + 硬约束 + build_context(code)。
  响应为 `StreamingResponse`（`text/plain; charset=utf-8`），逐段转发 LLM 增量文本。

### 配置（`app/core/config.py`）

- `GLM_API_KEY = os.environ.get("GLM_API_KEY", "")`
- `GLM_MODEL = os.environ.get("GLM_MODEL", "glm-4-flash")`
- `GLM_API_URL = "https://open.bigmodel.cn/api/paas/v4/chat/completions"`（常量）

### 对话历史

- 前端内存态持有 `messages`，随每次请求整体上传；不落库。
- 后端仅保留最近 20 条历史（超出从头丢弃），防止 token 超限。
- 前端**切换股票时清空对话**，防止上下文错配。

## Prompt 硬约束（架构红线，写入 system）

1. 只解释数据，不给买卖点，不预测目标价，不输出「建议买入/卖出/加仓/减仓」。
2. 所有数字只能引用上下文块中的数据；上下文没有的，回答「数据中没有」。
3. 明示数据截至日期；中文回答；面向个人投资者学习场景，可解释术语。

## 注入上下文明细（全部计算层生成）

1. **行情摘要**：近 20 个交易日逐日（日期/收盘价/涨跌幅%）；区间涨跌幅、区间最高/最低价、
   日均成交额（元，附换算为亿元的可读值）。
2. **技术指标**（最新一根，现算）：MA5/10/20/60、DIF/DEA/MACD柱、RSI14、K/D/J。
3. **财务摘要**（financials parquet 最近一期，列名已实测确认）：
   `净资产收益率(%)`、`销售毛利率(%)`、`销售净利率(%)`、`净利润增长率(%)`、
   `主营业务收入增长率(%)`、`资产负债率(%)`、`每股收益(元)`、`总资产(元)`、`日期`。
4. **自选池**：score、rank；未入选写「未入选当前自选池」。
5. 末尾固定行：`数据截至 {最后交易日}，财务数据截至 {财务日期}。`

## 前端侧边栏

- 分析页顶栏新增「AI解读」按钮，点击切换右侧 380px 可收合面板（图表区域自适应收缩）。
- 面板结构：消息气泡列表（user 右/assistant 左）+ 底部输入框。
- assistant 回答流式打字机渲染（fetch + ReadableStream 读取后端流式响应体，纯文本增量直接追加）。
- Enter 发送，Shift+Enter 换行；发送中禁用发送按钮。
- 空态显示静态提示文案（不自动发送预设问题）。
- API 返回 4xx/5xx 时在面板内显示红色错误行，可重试。

## 错误处理

| 场景 | 行为 |
|---|---|
| 未配置 `GLM_API_KEY` | `/api/chat` 返回 503，detail 明确提示配置方法 |
| 智谱请求超时（60s）/5xx | 后端重试 1 次，仍失败返回 502 + 可读 detail |
| 股票无数据（code 无效） | 404 |
| 前端流中断 | 面板显示「连接中断」，保留已渲染部分 |

## 测试与验收

**单测（pytest）**

1. `test_context.py`：合成 quotes/financials/watchlist 数据断言——近20日行数、区间涨跌幅、
   指标值、9 个财务字段、数据截至行全部出现；无财务数据时输出「未同步」且不抛错。
2. `test_prompt.py`：system prompt 含「不给买卖点」「只能引用」约束原文。
3. `test_chat_api.py`：mock `llm.stream` 后 TestClient 走通 /api/chat（流式拼接结果正确）；
   无 key 时 503。

**E2E（playwright）**：打开分析页 → 点「AI解读」→ 发问「这只股票近期走势如何」→
断言流式回答逐步出现、内容非空、无 console 错误。

## 非目标

- 不做对话历史持久化/多会话
- 不做 function calling 工具查询
- 不做策略研究员角色（属 P4 回测台范围）
- 不做语音/图片输入

## 运行前置

- 用户需设置环境变量 `GLM_API_KEY`（open.bigmodel.cn 控制台申请）。
- 财务上下文依赖该股 financials 已同步（当前自选池 100 只已全部同步 ✓）。
