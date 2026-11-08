"""Job-run bookkeeping survives lock contention (incident 2026-11-07).

While the hourly crypto paper job held the SQLite write lock for 77 minutes,
the failure record of ``options_paper_eod`` could not be written and 12
``job_run`` rows stayed ``running``. A bookkeeping write lost to the lock is
now deferred and retried once the lock is released, and ``running`` rows this
process does not own are closed as ``interrupted`` once they are stale.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

import signalforge.scheduler as sched
from signalforge.db.models import AuditLog, JobRun
from signalforge.db.session import reset_engine_cache, session_scope


def _short_busy_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIGNALFORGE_SQLITE_BUSY_TIMEOUT_MS", "50")
    reset_engine_cache()
    monkeypatch.setattr(sched, "retry_on_lock", lambda fn, **kw: fn())  # no waiting in the test


def _add_run(name: str, started: datetime, status: str = sched.JOB_RUN_RUNNING) -> int:
    with session_scope(write=True) as s:
        row = JobRun(name=name, started_at=started, status=status, detail="")
        s.add(row)
        s.flush()
        return int(row.id)


def _run(name: str) -> JobRun:
    with session_scope() as s:
        row = s.scalar(select(JobRun).where(JobRun.name == name))
        assert row is not None
        s.expunge(row)
        return row


def test_failure_record_lost_to_the_lock_is_written_once_the_lock_is_released(
    db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    _short_busy_timeout(monkeypatch)
    path = db_url.split("///", 1)[1]
    holders: list[sqlite3.Connection] = []

    def job() -> None:
        # Another job grabs the write lock mid-run and keeps it past our failure.
        holder = sqlite3.connect(path, timeout=0.05, isolation_level=None)
        holder.execute("BEGIN IMMEDIATE")
        holders.append(holder)
        raise RuntimeError("options feed broke")

    with pytest.raises(RuntimeError):
        sched.guarded("options_paper_eod", job)()
    # Neither the finish nor the failure record could land; both are kept.
    assert _run("options_paper_eod").status == sched.JOB_RUN_RUNNING
    assert len(sched._PENDING_RECORDS) == 2
    holders[0].execute("ROLLBACK")
    holders[0].close()

    # The next guarded job start flushes them, oldest first.
    sched.guarded("next_job", lambda: None)()
    assert sched._PENDING_RECORDS == []
    run = _run("options_paper_eod")
    assert run.status == "failed" and "options feed broke" in run.detail
    assert run.finished_at is not None and run.finished_at < _run("next_job").started_at
    with session_scope() as s:
        audit = s.scalar(
            select(AuditLog).where(
                AuditLog.action == "job.failed", AuditLog.entity == "options_paper_eod"
            )
        )
        assert audit is not None and "options feed broke" in audit.after_json["error"]
    # A finished row is no longer owned, so a later sweep may judge it.
    assert run.id not in sched._OWNED_RUN_IDS


def test_flush_stops_at_the_first_lock_failure_and_keeps_order(
    db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    _short_busy_timeout(monkeypatch)
    landed: list[str] = []

    def _locked() -> None:
        raise OperationalError("UPDATE ...", {}, sqlite3.OperationalError("database is locked"))

    calls: dict[str, Any] = {"a": _locked}
    sched._defer_record("a", lambda: calls["a"]())
    sched._defer_record("b", lambda: landed.append("b"))
    assert sched.flush_pending_job_records() == 0
    assert [r.label for r in sched._PENDING_RECORDS] == ["a", "b"] and landed == []
    calls["a"] = lambda: landed.append("a")
    assert sched.flush_pending_job_records() == 2
    assert landed == ["a", "b"] and sched._PENDING_RECORDS == []


def test_stale_running_rows_are_closed_but_owned_and_recent_rows_are_not(db_url: str) -> None:
    now = datetime(2026, 11, 8, 12, tzinfo=UTC)
    old = now - sched.STALE_RUNNING_AFTER - timedelta(minutes=1)
    stale = _add_run("daily_eod_update", old)
    owned = _add_run("crypto_hourly_paper", old)
    recent = _add_run("alerts", now - timedelta(hours=1))
    done = _add_run("universe_update", old, status="ok")
    sched._OWNED_RUN_IDS.add(owned)  # still in flight in this process

    assert sched.close_stale_job_runs(now) == 1
    with session_scope() as s:
        rows = {r.id: r for r in s.scalars(select(JobRun))}
        assert rows[stale].status == sched.JOB_RUN_INTERRUPTED
        assert rows[stale].detail.startswith("abandoned:")
        assert rows[stale].finished_at is not None
        assert rows[owned].status == sched.JOB_RUN_RUNNING
        assert rows[recent].status == sched.JOB_RUN_RUNNING
        assert rows[done].status == "ok" and rows[done].detail == ""
    assert sched.close_stale_job_runs(now) == 0  # idempotent


def test_guarded_job_start_sweeps_stale_rows_at_most_every_interval(
    db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    old = datetime.now(UTC) - sched.STALE_RUNNING_AFTER - timedelta(hours=1)
    first = _add_run("agents_daily", old)
    sched.enable_stale_job_sweep()  # the worker process (armed by run_catch_up)
    sched.guarded("grid_daily", lambda: None)()
    assert _run("agents_daily").status == sched.JOB_RUN_INTERRUPTED
    assert _run("grid_daily").status == "ok"

    second = _add_run("alerts", old)
    sched.guarded("grid_daily_2", lambda: None)()
    assert _run("alerts").status == sched.JOB_RUN_RUNNING  # sweep not due yet

    monkeypatch.setattr(sched, "STALE_SWEEP_EVERY_S", 0.0)
    sched.guarded("grid_daily_3", lambda: None)()
    assert _run("alerts").status == sched.JOB_RUN_INTERRUPTED
    assert first != second


def test_a_one_shot_job_process_never_sweeps_the_workers_rows(db_url: str) -> None:
    """``signalforge job run`` is not the worker: it knows only its own owned
    ids, so its guarded job must not close the worker's long in-flight rows."""
    old = datetime.now(UTC) - sched.STALE_RUNNING_AFTER - timedelta(hours=1)
    _add_run("daily_eod_update", old)  # e.g. the worker's long catch-up
    sched.guarded("grid_daily", lambda: None)()
    assert _run("daily_eod_update").status == sched.JOB_RUN_RUNNING
    assert _run("grid_daily").status == "ok"


def test_worker_start_up_arms_the_stale_sweep(db_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sched, "_last_scan_age", lambda: timedelta(hours=1))  # no catch-up
    monkeypatch.setattr(sched, "job_catch_up_missed_sessions", lambda: None)
    assert not sched._stale_sweep_enabled
    sched.run_catch_up()
    assert sched._stale_sweep_enabled
    old = datetime.now(UTC) - sched.STALE_RUNNING_AFTER - timedelta(hours=1)
    _add_run("alerts", old)  # went stale while this worker kept running
    monkeypatch.setattr(sched, "STALE_SWEEP_EVERY_S", 0.0)  # start-up already swept once
    sched.guarded("grid_daily", lambda: None)()
    assert _run("alerts").status == sched.JOB_RUN_INTERRUPTED


def test_a_job_finishing_after_the_sweep_still_records_its_real_outcome(db_url: str) -> None:
    """A false close is self-correcting: the finish write updates the same row."""
    started = datetime.now(UTC) - sched.STALE_RUNNING_AFTER - timedelta(hours=1)
    row_id = _add_run("long_catch_up", started)
    assert sched.close_stale_job_runs() == 1
    sched._finish_job_run(row_id, "long_catch_up", started, "ok")
    run = _run("long_catch_up")
    assert run.id == row_id and run.status == "ok" and run.detail == ""
