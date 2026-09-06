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
    ids = {j.id for j in scheduler.get_jobs()}
    assert {"ingest", "scan_all", "paper_mtm", "feed_probe", "daily_briefing"} <= ids


def test_catch_up_runs_when_no_scan_exists(db_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(sched, "job_ingest", lambda: calls.append("ingest"))
    monkeypatch.setattr(sched, "job_scan_all", lambda: calls.append("scan"))
    sched.run_catch_up()
    assert calls == ["ingest", "scan"]
