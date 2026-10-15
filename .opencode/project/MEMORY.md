---
# Project Memory Index

Durable preferences and facts about the stock-advisor project.

## Working Preferences

- pytest: `../.venv/bin/python -m pytest backend/tests -q` (177 pass)
- tsc: `cd frontend && npx tsc --noEmit` (clean)
- npm build: `npm run build` (passes, .next must trigger dev server restart)
- venv in project root: `backend下用 ../.venv/bin/...`，非 `.venv/bin/uvicorn`
- Comments/docstrings: 按优先级逐条说明，只保留必要项（第3类）；禁 any/@ts-ignore/空 catch
- git-master: GIT_MASTER=1 前缀；未经明确要求不提交
- 全量验证后必须重启 tmux web 与 api

## Recurring Lessons

- Three条红线：禁买卖建议词、数字只能引用上下文、无法覆盖的信息明说
- SYSTEM_TEMPLATE 五节结构：走势概览/技术面/量能与筹码/财务面/风险提示
- 前端: .next 覆盖会挂 dev server，build 后必须重启
- 数据层：全市场快照每日缓存，逐股财务数据仅 144 只

## Confirmed Architecture

- backend/screener: ak.stock_yjbb_em (业绩报表，16列) + ak.stock_zcfz_em (资产负债表，15列含资产负债率) + ak.stock_lrb_em (利润表，15列)
- 全市场快照: `market_snapshot_cached()`（当日首次调用拉取≈3.5分钟，同日后续命中缓存）
- screener run.py: `load_merged_market()` 共用拉数路径（snap+listing+earnings+fundamentals）
- score.py: 7因子百分位归一化 + 权重加权 = 0-100 综合分
- screener 输出不含买卖建议（仅输出排名与分项得分）

## Memory References

- `backend/app/screener/snapshot.py` —全市场接口与合并逻辑
- `backend/app/screener/score.py` —多因子打分器
- `backend/app/api/main.py` —三条新增端点与 chat 落库追踪
- `frontend/app/learn/page.tsx` —学习页组件（新建）
- `frontend/app/page.tsx` —导航入口与生成报告按钮
- `frontend/app/screen/page.tsx` —screen页导航入口

## Session State

- Last verification: `.venv/bin/python -m pytest backend/tests -q` 177 passed
- Build: `cd frontend && npm run build` 通过
- Last commit: 本轮改动未提交（8文件backend+4文件frontend待提交）
- 待确认: 是否 git push 到 origin/main

---

Source: auto-initialized by omni-memory skill on 2026-10-14; verified against current project state.