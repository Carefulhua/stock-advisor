---
# Project Index

Artifact map and relationship to existing documentation for the stock-advisor project.

## Directory Structure

```
stock-advisor/
├── backend/          # Python backend (FastAPI + pytest)
│   ├── app/
│   │   ├── api/      # API endpoints
│   │   ├── assistant/ # AI assistant (report, llm, context)
│   │   ├── data/     # fetchers, storage, screener
│   │   └── core/     # config
│   └── tests/      # pytest suite (177 passed)
├── frontend/         # Next.js frontend (TypeScript + tsc + npm build)
│   ├── app/          # Pages & components
│   ├── package.json
│   └── tsconfig.json
├── .opencode/        # OpenCode session state
│   └── project/    # Project memory (MEMORY.md, HANDOFF.md, INDEX.md)
│   ├── MEMORY.md
│   ├── HANDOFF.md
│   └── INDEX.md
├── data/             # Persistent data (quotes parquet, financials parquet, snapshots)
├── .env              # GLM_API_KEY（由 _load_env_file 加载，重启不丢）
└── README.md
```

## Key Files Relationship

| Artifact | Purpose | Loads Automatically |
|----------|---------|---------------------|
| `.opencode/project/MEMORY.md` | Durable project facts & conventions | Yes (via host instructions) |
| `.opencode/project/HANDOFF.md` | Cross-session continuation delta | Yes (via host instructions) |
| `.opencode/project/INDEX.md` | Artifact map & doc relationships | No (manual review) |
| `backend/app/data/storage.py` | DB schema & chat_history, reports table | No |
| `backend/app/assistant/report.py` | 10-section report template + append_interpretation | No |
| `backend/app/api/main.py` | 3 new endpoints + chat integration | No |
| `frontend/app/learn/page.tsx` | 学习页组件（报告列表+查看+生成） | No |
| `frontend/app/page.tsx` | 导航入口 + 生成报告按钮 | No |
| `frontend/app/screen/page.tsx` | screen页导航入口 | No |

## Verification Commands

```bash
# Backend
cd backend && ../.venv/bin/python -m pytest -q

# TypeScript
cd frontend && npx tsc --noEmit

# Build
cd frontend && npm run build

# Full state check
cat .opencode/project/MEMORY.md
cat .opencode/project/HANDOFF.md
```

## Session Management

- Session journals: `.opencode/project/sessions/YYYY-MM-DD-HHMM-<agent>-<topic>.md` (temporary, not committed)
- `.opencode/project/sessions/` excluded from git via `.gitignore`
- Canonical state eligible to join normal Git commit

## Legacy Merge Notes

If legacy `.opencode/memory/PROJECT.md` existed, unique durable facts would be merged into this `MEMORY.md`; unmatched content discarded.

---

Source: auto-initialized by omni-memory skill on 2026-10-14; cross-referenced with current project state.