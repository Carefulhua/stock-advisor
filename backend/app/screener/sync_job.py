"""选股池后台同步任务：逐只推进进度，供前端轮询 /api/sync/status。

不走 data.sync.run_sync：它每次都会拉全市场股票列表，逐只调用会产生 N 次
无用的列表请求；这里直接调用逐只的 sync_quotes / sync_financials。
"""
from __future__ import annotations

import logging
import threading
import uuid
from datetime import datetime

from app.core import config
from app.data import fetchers_baostock, storage
from app.data.sync import sync_financials, sync_quotes

logger = logging.getLogger(__name__)


class SyncBusyError(Exception):
    """已有同步任务在运行。"""


_lock = threading.Lock()
_state: dict[str, object] = {
    "running": False,
    "total": 0,
    "done": 0,
    "failed": 0,
    "current": None,
    "started_at": None,
    "finished_at": None,
    "job_id": None,
}


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def get_status() -> dict:
    with _lock:
        return dict(_state)


def _reset() -> None:
    with _lock:
        _state.update(
            running=False,
            total=0,
            done=0,
            failed=0,
            current=None,
            started_at=None,
            finished_at=None,
            job_id=None,
        )


def _worker(codes: list[str], job_id: str, skip_financials: bool) -> None:
    config.ensure_dirs()
    conn = storage.get_conn()
    try:
        for code in codes:
            with _lock:
                _state["current"] = code
            ok, failed = sync_quotes(conn, [code])
            if not skip_financials and not failed:
                fin_ok, fin_failed = sync_financials(conn, [code])
                if fin_failed:
                    failed = fin_failed
                    ok = 0
                else:
                    ok = ok + fin_ok
            with _lock:
                if failed:
                    _state["failed"] = int(_state["failed"]) + 1
                else:
                    _state["done"] = int(_state["done"]) + 1
    except Exception:
        logger.exception("选股池同步任务异常: %s", job_id)
    finally:
        fetchers_baostock.logout()
        conn.close()
        with _lock:
            _state["current"] = None
            _state["running"] = False
            _state["finished_at"] = _now()


def start(codes: list[str], skip_financials: bool = False) -> str:
    job_id = uuid.uuid4().hex[:12]
    with _lock:
        if _state["running"]:
            raise SyncBusyError("已有同步任务在运行")
        _state.update(
            running=True,
            total=len(codes),
            done=0,
            failed=0,
            current=None,
            started_at=_now(),
            finished_at=None,
            job_id=job_id,
        )
    thread = threading.Thread(
        target=_worker, args=(list(codes), job_id, skip_financials), daemon=True
    )
    thread.start()
    return job_id