"""Scheduler: kill-switch gating on every job, catch-up trigger, job registry."""

from __future__ import annotations

from pathlib import Path

import pytest

import signalforge.scheduler as sched
from signalforge.killswitch import get_kill_switch
from signalforge.scheduler import build_scheduler, default_job_specs, guarded

pytestmark = pytest.mark.safety


def test_guarded_job_is_a_noop_while_engaged(isolated_data_dir: Path) -> None:
    ran: list[str] = []
    job = guarded("demo", lambda: ran.append("x"))

    job()
    assert ran == ["x"]

    get_kill_switch().engage(reason="halt", actor="pytest")
    job()  # must NOT raise, must NOT run
    assert ran == ["x"]

    get_kill_switch().release(reason="resume", actor="pytest")
    job()
    assert ran == ["x", "x"]


def test_every_default_job_is_wrapped_by_the_guard(
    isolated_data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    for spec in default_job_specs():
        monkeypatch.setattr(sched, spec.fn.__name__, lambda n=spec.name: calls.append(n))

    get_kill_switch().engage(reason="halt", actor="pytest")
    # Re-read the (now patched) functions and run each through the guard.
    for spec in default_job_specs():
        guarded(spec.name, spec.fn)()
    assert calls == []  # kill switch blocked all of them

    get_kill_switch().release(reason="resume", actor="pytest")
    for spec in default_job_specs():
        guarded(spec.name, spec.fn)()
    assert sorted(calls) == sorted(s.name for s in default_job_specs())


def test_build_scheduler_registers_every_job(db_url: str) -> None:
    scheduler = build_scheduler()
    jobs = {j.id: j for j in scheduler.get_jobs()}
    assert {
        "daily_eod_update",
        "paper_mtm",
        "feed_probe",
        "health_check",
        "news_poll",
        "daily_briefing",
        "strategy_health",
    } <= set(jobs)
    # the single post-close update runs on a daily cron, not a fixed interval
    assert type(jobs["daily_eod_update"].trigger).__name__ == "CronTrigger"
    assert type(jobs["paper_mtm"].trigger).__name__ == "IntervalTrigger"


def test_guarded_records_a_job_failure_for_the_alert_policy(db_url: str) -> None:
    """A raising job must still raise (callers/APScheduler need to see it), but
    also leaves an audit_log 'job.failed' row so plan_alerts can surface it."""
    from sqlalchemy import select

    from signalforge.db.models import AuditLog
    from signalforge.db.session import session_scope

    def _boom() -> None:
        raise ValueError("simulated ingest failure")

    with pytest.raises(ValueError):
        guarded("demo_failing_job", _boom)()

    with session_scope() as session:
        row = session.scalar(
            select(AuditLog).where(
                AuditLog.action == "job.failed", AuditLog.entity == "demo_failing_job"
            )
        )
        assert row is not None
        assert "simulated ingest failure" in row.after_json["error"]


def test_catch_up_runs_when_no_scan_exists(db_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(sched, "job_ingest", lambda: calls.append("ingest"))
    monkeypatch.setattr(sched, "job_scan_all", lambda: calls.append("scan"))
    sched.run_catch_up()
    assert calls == ["ingest", "scan"]
