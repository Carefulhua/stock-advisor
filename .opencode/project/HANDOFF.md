---
# Global Handoff

Cross-project and OpenCode-configuration continuation state. Retrieve only when relevant.

- Updated: 2026-10-14
- Current focus: project-state initialization complete
- Current focus: finish omni-memory setup for stock-advisor

## Completed

- omni-memory: project memory, handoff, index initialized
- backend: 177 pytest pass, tsc clean, npm build success
- frontend: learn/page.tsx created, nav & button additions, globals.css styles
- GLM key persistence: config.py + .env + gitignore 修复（重启不丢 key）
- COLUMN_LABELS/SORTABLE 4新字段补齐（page.tsx + screen/page.tsx）
- GLM_API_KEY持久化修复（config.py 加 _load_env_file + backend/.env + gitignore）

## Current Changes

- `.opencode/project/` 初始化: MEMORY.md, HANDOFF.md, INDEX.md
- 前端: learn/page.tsx + page.tsx nav + screen/page.tsx + globals.css 补全
- 记忆三件套：选股维度扩容（zcfz_em/lrb_em），多因子打分器，学习页 UI
- GLM key 持久化（不再因 tmux 重启而丢失）

## Decisions and Findings

- 不集成 stockaskill 代码：数据层重复、非 package 导入、输出违反 SYSTEM_TEMPLATE 红线
- 可借鉴的两处：factors/base.py 百分位归一化 + config.py 因子权重体系
- 资产负债率/净利率 通过全市场接口 ak.stock_zcfz_em + ak.stock_lrb_em 获得（11分页≈2秒）
- 七因子打分器权重总和 = 1.00（roe(.20)/revenue_yoy(.15)/net_profit_yoy(.15)/net_margin(.15)/debt_ratio(.15 lower-better)/gross_margin(.10)/cfps(.10)）

## Verification

- pytest 177 passed 全绿
- tsc --noEmit 通过
- npm run build 通过
- Playwright E2E：四个新维度在下拉命中 4/4；UI 确认 28 列表头全渲染

## Blockers and Risks

- npm run build 持破坏运行中的 dev server（.next 被覆盖 → 500），build 后必须重启 tmux web
- 全量验证未跑：真实 GLM 生成报告 + Playwright 查看/刷新
- 内内：常驻增量调度用户明确先不动；财务同步仍手动

## Exact Next Actions

- 确认是否 git push 到 origin/main（本轮改动未提交）
- 若确认: `git status` 干净 → `git add .` → `git commit -m "..."` → `git push`
- 若否: 继续在本地验证，待用户明确
- 前端: 若有新需求，按 omni-memory 模式增补 memory 与handoff

---

Source: auto-initialized by omni-memory skill on 2026-10-14; verified against current project state.