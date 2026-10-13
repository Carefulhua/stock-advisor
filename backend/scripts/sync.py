"""手动同步入口。

用法:
    uv run python backend/scripts/sync.py                 # 全市场增量
    uv run python backend/scripts/sync.py --limit 20      # 只同步前20只(测试)
    uv run python backend/scripts/sync.py --codes 000001,600519
    uv run python backend/scripts/sync.py --full-history  # 从2005年起拉全历史
    uv run python backend/scripts/sync.py --skip-financials
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.data.sync import run_sync  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="A股数据同步")
    parser.add_argument("--codes", help="逗号分隔的股票代码, 默认全市场")
    parser.add_argument("--limit", type=int, help="只同步前 N 只(调试用)")
    parser.add_argument("--full-history", action="store_true", help="从2005年拉全历史")
    parser.add_argument("--skip-financials", action="store_true", help="跳过财务指标")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    codes = args.codes.split(",") if args.codes else None
    result = run_sync(
        codes=codes,
        limit=args.limit,
        full_history=args.full_history,
        skip_financials=args.skip_financials,
    )

    print(
        f"股票列表: {result.stocks_synced} | "
        f"日线成功: {result.quotes_synced} 失败: {len(result.quotes_failed)} | "
        f"财务成功: {result.financials_synced} 失败: {len(result.financials_failed)}"
    )
    if result.quotes_failed:
        print(f"日线失败代码: {','.join(result.quotes_failed[:20])}")
    if result.financials_failed:
        print(f"财务失败代码: {','.join(result.financials_failed[:20])}")
    return 1 if result.quotes_failed and result.quotes_synced == 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
