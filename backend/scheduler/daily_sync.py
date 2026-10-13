"""每日收盘后增量同步调度 (工作日 15:30 Asia/Shanghai)。

运行: uv run python backend/scheduler/daily_sync.py
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apscheduler.schedulers.blocking import BlockingScheduler  # noqa: E402
from apscheduler.triggers.cron import CronTrigger  # noqa: E402

from app.data.sync import run_sync  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)


def job() -> None:
    logger.info("daily sync start")
    result = run_sync()
    logger.info(
        "daily sync done: quotes=%s failed=%s financials=%s failed=%s",
        result.quotes_synced,
        len(result.quotes_failed),
        result.financials_synced,
        len(result.financials_failed),
    )


def main() -> None:
    scheduler = BlockingScheduler(timezone="Asia/Shanghai")
    # baostock 收盘后约 17:30-20:00 才写入当日数据, 20:30 保证可取到
    scheduler.add_job(job, CronTrigger(day_of_week="mon-fri", hour=20, minute=30))
    logger.info("scheduler started: weekdays 20:30 Asia/Shanghai")
    scheduler.start()


if __name__ == "__main__":
    main()
