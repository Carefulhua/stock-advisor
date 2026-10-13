import threading
import time

import pytest

from app.screener import sync_job as sync_job_mod


@pytest.fixture(autouse=True)
def clean_state():
    sync_job_mod._reset()
    yield
    sync_job_mod._reset()


def _wait_idle(timeout: float = 5.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = sync_job_mod.get_status()
        if not status["running"]:
            return status
        time.sleep(0.01)
    raise AssertionError("同步任务未在超时内结束")


def test_get_status_initial_is_idle():
    status = sync_job_mod.get_status()

    assert status["running"] is False
    assert status["total"] == 0
    assert status["done"] == 0
    assert status["failed"] == 0
    assert status["job_id"] is None


def test_start_returns_job_id_and_finishes(monkeypatch):
    monkeypatch.setattr(sync_job_mod, "sync_quotes", lambda conn, codes: (1, []))
    monkeypatch.setattr(sync_job_mod, "sync_financials", lambda conn, codes: (1, []))

    job_id = sync_job_mod.start(["000001", "000002"])
    status = _wait_idle()

    assert isinstance(job_id, str) and job_id
    assert status["job_id"] == job_id
    assert status["total"] == 2
    assert status["done"] == 2
    assert status["failed"] == 0
    assert status["started_at"] is not None
    assert status["finished_at"] is not None


def test_start_counts_failed_codes(monkeypatch):
    def _quotes(conn, codes):
        if codes[0] == "000002":
            return 0, [codes[0]]
        return 1, []

    monkeypatch.setattr(sync_job_mod, "sync_quotes", _quotes)
    monkeypatch.setattr(sync_job_mod, "sync_financials", lambda conn, codes: (1, []))

    sync_job_mod.start(["000001", "000002"])
    status = _wait_idle()

    assert status["total"] == status["done"] + status["failed"]
    assert status["done"] == 1
    assert status["failed"] == 1


def test_start_skips_financials_when_sync_skips(monkeypatch):
    calls: list[list[str]] = []
    monkeypatch.setattr(sync_job_mod, "sync_quotes", lambda conn, codes: (1, []))
    monkeypatch.setattr(
        sync_job_mod, "sync_financials", lambda conn, codes: calls.append(codes) or (1, [])
    )

    sync_job_mod.start(["000001"], skip_financials=True)
    status = _wait_idle()

    assert calls == []
    assert status["done"] == 1


def test_second_start_while_running_raises_busy(monkeypatch):
    gate = threading.Event()
    monkeypatch.setattr(sync_job_mod, "sync_quotes", lambda conn, codes: gate.wait(2) or (1, []))
    monkeypatch.setattr(sync_job_mod, "sync_financials", lambda conn, codes: (1, []))

    sync_job_mod.start(["000001"])
    assert sync_job_mod.get_status()["running"] is True

    with pytest.raises(sync_job_mod.SyncBusyError):
        sync_job_mod.start(["000002"])

    gate.set()
    _wait_idle()


def test_start_with_empty_codes_finishes_immediately():
    status = _wait_idle() if sync_job_mod.start([]) else sync_job_mod.get_status()

    assert status["running"] is False
    assert status["total"] == 0


def test_reset_clears_previous_job():
    sync_job_mod._reset()

    status = sync_job_mod.get_status()
    assert status["job_id"] is None
    assert status["total"] == 0