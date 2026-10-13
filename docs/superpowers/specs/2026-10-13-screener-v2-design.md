# 交互式选股（选股器 v2）设计文档

日期：2026-10-13
状态：已批准，待实施

## 1. 背景

现有选股器（`backend/app/screener/`）是硬编码权重打分：成交额 30% + PE 30% + 净利润增速 40%，固定取 Top 100，写死一套自过滤。用户无法表达自己的选股思路，只能接受这一套固定口径。

本次重做为交互式选股：用户输入条件（自然语言或表单）→ 全市场筛选 → 预览结果 → 确认后写池子 → 新股自动同步数据。另加「自选股」概念：手工添加、永远保留在展示池中。

## 2. 目标与非目标

### 目标
- 条件驱动的全市场筛选，维度覆盖估值/成长/质量/规模/活跃度/动量/行业
- 自然语言输入（AI 解析为结构化条件）+ 结构化表单，两条路殊途同归，表单为唯一数据来源
- 自选股：搜索添加 + 批量粘贴，永不被筛选条件移出
- 筛选结果预览后确认才写池子，条件写错不会静默洗池
- 新入池股票自动后台同步日线+财务，页面显示进度
- 独立页面 `/screen`

### 非目标
- 技术面筛选（需要全市场日线，回填需数小时；本版维度全部来自快照与业绩报表）
- 盘中实时行情（快照是收盘数据）
- 策略回测与策略研究员（归 P4）
- 常驻增量调度（问题1的根因，用户决定本次不处理）

## 3. 数据来源与字段目录

筛选只用两个全市场接口，**不下载日线**：

| 来源 | 接口 | 耗时 | 提供 |
|---|---|---|---|
| 全市场快照 | `ak.stock_zh_a_spot_tx()` | **~3.5min**（27次分页） | 估值/市值/成交额/活跃度/多周期涨跌幅/主力净流入 |
| 业绩报表 | `ak.stock_yjbb_em(date=报告期)` | ~4s | 盈利/成长/每股/ROE/毛利率/行业 |
| 上市日期 | `stock_info_sh_name_code` + `stock_info_sz_name_code` | ~2s | 上市日期（用于日期条件） |

### 3.1 字段目录（筛选可用维度）

单位在入库时统一：快照的 `turnover` 是万元 → ×1e4 存元；`ltsz`/`zsz` 是亿元 → ×1e8 存元。

| field | 中文标签 | 单位 | 来源列 |
|---|---|---|---|
| `pe_ttm` | 市盈率TTM | 倍 | 快照 `pe_ttm` |
| `pn` | 市净率 | 倍 | 快照 `pn` |
| `turnover` | 成交额 | 元 | 快照 `turnover` ×1e4 |
| `ltsz` | 流通市值 | 元 | 快照 `ltsz` ×1e8 |
| `zsz` | 总市值 | 元 | 快照 `zsz` ×1e8 |
| `hsl` | 换手率 | % | 快照 `hsl` |
| `lb` | 量比 | 倍 | 快照 `lb` |
| `zdf_y` | 年初至今涨幅 | % | 快照 `zdf_y` |
| `zdf_d20` | 近20日涨幅 | % | 快照 `zdf_d20` |
| `zdf_d60` | 近60日涨幅 | % | 快照 `zdf_d60` |
| `zljr` | 主力净流入 | 元 | 快照 `zljr` ×1e4 |
| `eps` | 每股收益 | 元 | 业绩 `每股收益` |
| `cfps` | 每股经营现金流 | 元 | 业绩 `每股经营现金流量` |
| `revenue_yoy` | 营收同比 | % | 业绩 `营业总收入-同比增长` |
| `net_profit_yoy` | 净利润同比 | % | 业绩 `净利润-同比增长` |
| `net_profit` | 净利润 | 元 | 业绩 `净利润-净利润` |
| `roe` | 净资产收益率 | % | 业绩 `净资产收益率` |
| `gross_margin` | 销售毛利率 | % | 业绩 `销售毛利率` |
| `industry` | 所处行业 | — | 业绩 `所处行业` |
| `list_date` | 上市日期 | date | 上市表 `上市日期` |

## 4. 数据模型

### 4.1 概念区分（本设计最关键的决策）

| 概念 | 存储 | 语义 |
|---|---|---|
| 池子 | 现有 `watchlist` 表（`code PK, name, score, rank, selected_at`） | 条件筛选产物，带 rank/score，每次应用整体替换 |
| 自选股 | **新表 `favorites`（`code PK, name, added_at`）** | 手工添加，不参与排名，筛选时永远保留 |
| 展示池 | 计算得出，无独立存储 | `watchlist ∪ favorites`；favorites 行 `is_favorite=1` 且排在最前 |

现有 `watchlist` 表结构与 `replace_watchlist`/`read_watchlist` 函数保持不变，仅新增 `favorites` 表与三个 CRUD 函数。`watchlist.score` 写入筛选排序后的序号位次对应的分数（若无打分则写 rank 的归一值，见 6.4）。

### 4.2 favorites 表

```sql
CREATE TABLE IF NOT EXISTS favorites (
    code TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    added_at TEXT NOT NULL
);
```

## 5. 条件模型（声明式 schema）

```json
{
  "conditions": [
    {"field": "net_profit_yoy", "op": "gte", "value": 20},
    {"field": "pe_ttm", "op": "between", "value": [10, 40]},
    {"field": "turnover", "op": "gte", "value": 200000000},
    {"field": "industry", "op": "in", "value": ["半导体", "软件开发"]}
  ],
  "sort_by": "net_profit_yoy",
  "top": 100
}
```

### 5.1 操作符

| 类型 | 字段 | 操作符 | value 形态 |
|---|---|---|---|
| 数值 | 除 `industry`/`list_date` 外全部 | `gte` `gt` `lte` `lt` `between` | 数字 / `[lo, hi]` |
| 枚举 | `industry` | `in` | 字符串数组 |
| 日期 | `list_date` | `gte` `lte` | `"YYYY-MM-DD"` |

**空值一律排除**（不做任何缺失数据蒙混过关），`in` 的空数组结果为空。

### 5.2 恒成立的自过滤

- 剔除 ST（名称含 `ST`）—— 保留为恒成立条件
- **不预置代码前缀限制**：全市场（含北交所）均可参与筛选，成交额/市值条件会自然滤掉流动性差的
- 不预置流动性/上市年限门槛：由用户按需在表单里表达

### 5.3 校验

pydantic 校验：field 必须在字段目录内、op 必须在该字段允许集合内、value 类型匹配（`between` 必须是长度 2 且 lo<hi 的数值数组）。校验失败返回 422 并在 `detail` 中给出出错字段名与原因。

## 6. 后端设计

### 6.1 模块划分

| 文件 | 职责 |
|---|---|
| `app/screener/fields.py` | 字段目录与操作符定义（单一事实来源，后端校验与前端渲染共用） |
| `app/screener/conditions.py` | 条件 pydantic 模型 + `evaluate(df, conditions)` 纯函数求值 |
| `app/screener/snapshot.py` | **扩展**：fetch_market_snapshot 增加 `pn/hsl/lb/zdf_*/zljr` 列映射；fetch_earnings_growth 改为返回业绩报表全部字段（`eps/cfps/revenue_yoy/net_profit_yoy/net_profit/roe/gross_margin/industry`）；新增全市场快照内存缓存 |
| `app/screener/parse.py` | 自然语言 → conditions JSON（调用现有 `app/assistant/llm.py` 的 GLM 客户端，非流式） |
| `app/screener/run.py` | **扩展**：CLI 保留；新增 `run_filter()` 纯函数（合并快照 → 求值 → 排序 → 取 top → 计算 diff） |
| `app/screener/sync_job.py` | 后台同步线程与进度状态（模块级单例状态） |
| `app/data/storage.py` | **扩展**：`_SCHEMA` 加 `favorites` 表；新增 `add_favorites` `remove_favorite` `read_favorites` `replace_watchlist_by_codes` |
| `app/api/main.py` | **扩展**：新增 7 个端点；CORS 保持 `["GET","POST","DELETE"]` |

### 6.2 API 端点

| 方法 | 路径 | 入参 | 出参 |
|---|---|---|---|
| GET | `/api/screener/fields` | — | 字段目录：[{field,label,unit,kind,ops}]，kind ∈ `number`/`enum`/`date`；enum 带 `options`（行业全集） |
| GET | `/api/screener/status` | — | `{llm_enabled: bool, snapshot_cached: bool}` |
| POST | `/api/screener/parse` | `{query: str}` | `{conditions, sort_by}`；无 key → 503，LLM 失败 → 502，JSON 不合 schema → 422 |
| POST | `/api/screener/run` | `{conditions, sort_by, top}` | `{rows, next_in, next_out, kept_favorites, total_matched, elapsed_sec, cached}` |
| POST | `/api/screener/apply` | `{codes: [str]}` | `{applied: int, sync_job_id}` 并启动后台同步 |
| GET | `/api/favorites` | — | `[{code,name,added_at}]` |
| POST | `/api/favorites` | `{codes: [str]}` | `{added:int, skipped:int}`（skipped=已在池子或格式非法） |
| DELETE | `/api/favorites/{code}` | — | `{deleted: bool}` |
| GET | `/api/sync/status` | — | `{running: bool, total: int, done: int, failed: int, current: str|None, started_at, finished_at}` |

`sync/status` 与 `screener/run` 之外，复用现有 `/api/stocks`（搜索）、`/api/quotes/{code}`、`/api/indicators/{code}`、`/api/chat` 不变。

### 6.3 rows 结构

每行：`{code, name, industry, is_favorite, rank, plus 各字段目录中的数值字段}`，按 `sort_by` 降序，favorites 置顶。

### 6.4 diff 计算

`run_filter` 输出 `next_in`（池子中不存在且满足条件、不含 favorites）、`next_out`（当前池子中不满足条件且不是 favorites 的代码）、`kept_favorites`（强制保留的自选）。三者互斥且并集覆盖全池。

`apply` 只做一件事：把 `codes` 按序写进 `watchlist`（`rank` = 序号，`score` = `round(100 * (1 - (rank-1)/max(n-1,1)), 2)`，即首位 100 分、末位 0 分的相对排名分；`name` 取自快照），不动 `favorites`。

### 6.5 快照缓存

模块级 `_snapshot_cache: tuple[date_str, DataFrame] | None`。同日重复调用直接返回缓存；交易日变化则失效。`/api/screener/status` 暴露 `snapshot_cached` 让前端能提示「首次约 3-5 分钟」。

### 6.6 后台同步

`sync_job.py` 提供 `start(codes) -> job_id` 与 `get_status()`。单后台线程复用现有 `run_sync(codes=..., full_history=False)`，逐只完成后更新进度；单只失败计入 `failed` 不中断；线程结束后 `running=False`。并发保护：已有任务在跑时返回 409。

## 7. 前端设计（`/screen`）

### 7.1 导航

现有分析页加左侧/顶部导航「分析 | 选股」，`/screen` 为新路由。

### 7.2 布局

```
┌─ 导航 ────────────────────────────────┐
│ 自然语言输入框 [解析]  (无key时禁用+提示) │
├─ 条件表单（动态渲染）      ┬─ 自选管理 ─┤
│  [net_profit_yoy >= __]    │ 搜索添加    │
│  [pe_ttm  10 ~ 40]         │ 批量粘贴    │
│  [industry ∈ __]           │ 列表(可删) │
│  [+ 添加条件] [清除]        │            │
├─ 排序 ▾  数量 [100]  [开始筛选]           │
├─ 结果表格（含 自选标记 / 将新入池 / 移出）  │
│  [应用到池子]  同步进度条 ▓▓▓▓░░ 37/100  │
└───────────────────────────────────────┘
```

### 7.3 行为要点

- 表单由 `GET /api/screener/fields` 动态渲染，新增字段无需改前端
- 自然语言解析成功后**回填表单**（可编辑再跑），解析失败提示手填，表单状态不丢
- 筛选中显示 loading 并提示「首次需拉取全市场快照，约 3-5 分钟」
- 结果表格顶部汇总条：`筛出 137 只 · 将新入池 52 · 将移出 15 · 自选 8 只保留`
- 未点「应用到池子」前不写任何库
- 应用后轮询 `/api/sync/status`（2s 间隔）刷新进度条；运行中在结果行标 `同步中`
- 切走页面不中断同步（后端线程）

## 8. 错误处理

| 场景 | 行为 |
|---|---|
| 快照/业绩拉取失败 | 复用现有 `_with_retry`（4次退避）；仍失败 → 502，页面**保留上次结果不清空** |
| 条件字段/操作符/value 非法 | 422，detail 指明出错字段 |
| 筛选出 0 只 | 200 + 空 rows + 提示「条件过严，建议放宽」，**不报错** |
| 无 GLM key | `/api/screener/status` 返回 false，前端禁用自然语言框；表单照常可用 |
| 粘贴自选含非法代码 | 逐个校验，计入 `skipped`，不整批失败 |
| 同步任务已在跑 | 409 + 提示已有任务进行中 |
| 池中股票尚未同步完就点开 | `/api/quotes/{code}` 404，页面显示「数据同步中」 |

## 9. 测试与验收

### 9.1 单测（pytest，全部 TDD 红→绿）
- `test_conditions.py`：5 种数值操作符 ×（命中/不命中/空值被排除）、`between` 边界值、`industry in`、日期操作符、非法 field/op/value 各一条 422
- `test_fields.py`：字段目录自洽（每个 field 有 label/unit/ops；数值字段 ops 集合一致）
- `test_parse.py`：mock GLM 返回合法 JSON / 非法 JSON / 非 JSON 文本
- `test_screener_run.py`：`run_filter` diff 计算（next_in/next_out/kept_favorites 三者互斥且并集正确）、排序、top 截断、favorites 置顶
- `test_favorites.py`：CRUD、批量添加跳过重复、删除、池子不受影响
- `test_sync_job.py`：进度状态机（running→done/failed 计数）

### 9.2 实盘验收
1. 跑一次筛选（真实全市场），核对结果合理性（抽查 3 只的 PE/净利同比/行业与公开数据一致）
2. 应用到池子 → 池子变为新结果，favorites 未被移出
3. 同步进度从 0 走到 100，点新股票能出 K 线与 AI 解读
4. Playwright E2E：自然语言输入 → 表单回填 → 筛选 → 预览 → 应用 → 进度条 → 新股 K 线，0 console 错误
5. 全量 pytest 通过

## 10. 决策记录

| 决策 | 取舍与理由 |
|---|---|
| favorites 独立表，不复用 watchlist | watchlist 有 score/rank 语义且每次整体替换；混在一起会让「自选」被筛选洗掉 |
| 维度不含技术面 | 技术面需全市场日线（数小时回填），与「十几秒出结果」的体验目标冲突 |
| 恒定过滤只留 ST，不限代码前缀 | 北交所流动性差应由用户的成交额/市值条件表达，而非写死规则 |
| 自然语言仅解析为表单值 | 表单是唯一数据来源，保证筛选可复现；AI 不参与计算，避免幻觉数字 |
| 无条件不足报错 | v1 是固定 Top100 场景；v2 是任意条件筛选，0 结果是合法结果 |
| 后台同步而非同步后再应用 | 用户确认要先看到池子更新；同步耗时 20-25min 不应阻塞确认动作 |
| 快照按交易日内存缓存 | 3.5min 的接口不能每次筛选都重拉；同日复用使二次筛选秒级 |

## 11. 遗留与后续

- 常驻增量调度（问题1根因）：用户决定本次不处理，数据会再次滞后，需手动跑 `scripts/sync.py`
- 快照缓存仅内存，进程重启后失效（下次筛选重新 3.5min）
- P4 回测台与策略研究员未开始