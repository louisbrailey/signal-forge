"""Worker liveness, expected-session logic, and catch-up readiness.

Covers the new always-on runtime primitives in ``signalforge.scheduler``
(`record_heartbeat`, `last_completed_session`, `_session_cutoff_utc`,
`catch_up_pending`, `job_catch_up`, the `catch_up` JobSpec) and how the
Operational Status page (`ops_status_context` + `/ops`) surfaces them.

No network; nothing here reads `.env` — the autouse `isolated_data_dir`
fixture (tests/conftest.py) points every setting at a throwaway SQLite DB
and blanks provider credentials before each test runs.
"""

from __future__ import annotations

import os
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

import signalforge.scheduler as sched
from signalforge.app.views import ops_status_context
from signalforge.db.models import IngestionRun, JobRun, WorkerHeartbeat
from signalforge.db.session import get_sessionmaker, session_scope
from signalforge.domain import FeedType
from signalforge.scheduler import (
    CATCH_UP_RETRY_BACKOFF,
    WORKER_STALE_AFTER_S,
    _session_cutoff_utc,
    build_scheduler,
    catch_up_pending,
    default_job_specs,
    job_catch_up,
    last_completed_session,
    record_heartbeat,
)

# registered_client lives in tests/app/conftest.py, scoped to the tests/app/
# subtree; re-import it (aliased, so it doesn't collide with the parameter
# name in the tests below) so pytest can find it as a fixture from this
# top-level test module too. `client` must stay importable under its exact
# name -- it's registered_client's own fixture dependency.
from tests.app.conftest import client  # noqa: F401
from tests.app.conftest import registered_client as _registered_client  # noqa: F401

pytestmark = pytest.mark.safety


@pytest.fixture
def ops_client(_registered_client):  # noqa: F811
    """A signed-in TestClient, for the /ops rendering tests below."""
    return _registered_client


def _et(y: int, m: int, d: int, hh: int, mm: int) -> datetime:
    """Build an aware America/New_York datetime, then hand back the
    equivalent aware-UTC instant — matching how a real caller would pass
    ``now`` (spec: "aware UTC datetimes built from America/New_York")."""
    return datetime(y, m, d, hh, mm, tzinfo=ZoneInfo("America/New_York")).astimezone(UTC)


# --------------------------------------------------------------------------- #
# last_completed_session
# --------------------------------------------------------------------------- #
def test_last_completed_session_wednesday_after_cutoff_is_the_same_day() -> None:
    now = _et(2024, 6, 12, 18, 0)  # Wednesday, after the 17:30 ET cutoff
    assert last_completed_session(now) == date(2024, 6, 12)


def test_last_completed_session_wednesday_before_cutoff_is_tuesday() -> None:
    now = _et(2024, 6, 12, 10, 0)  # Wednesday, before the 17:30 ET cutoff
    assert last_completed_session(now) == date(2024, 6, 11)


def test_last_completed_session_saturday_is_friday() -> None:
    now = _et(2024, 6, 15, 12, 0)  # Saturday, any time
    assert last_completed_session(now) == date(2024, 6, 14)


def test_last_completed_session_monday_before_cutoff_is_previous_friday() -> None:
    now = _et(2024, 6, 10, 9, 0)  # Monday, before the 17:30 ET cutoff
    assert last_completed_session(now) == date(2024, 6, 7)


# --------------------------------------------------------------------------- #
# catch_up_pending
# --------------------------------------------------------------------------- #
_NOW = _et(2024, 6, 12, 19, 0)  # Wednesday, well after the 17:30 ET cutoff
_EXPECTED = date(2024, 6, 12)
_CUTOFF = _session_cutoff_utc(_EXPECTED)


def test_catch_up_pending_with_no_ingestion_run_at_all(db_url: str) -> None:
    pending, reason = catch_up_pending(_NOW)
    assert pending is True
    assert "no OK daily-bar ingestion" in reason


def test_catch_up_pending_false_when_ok_ingest_finished_after_the_cutoff(db_url: str) -> None:
    finished = _CUTOFF + timedelta(minutes=5)
    with session_scope() as session:
        session.add(
            IngestionRun(
                provider="fixture",
                feed_type=FeedType.BAR_DAILY,
                requested_start=date(2024, 6, 11),
                requested_end=_EXPECTED,
                status="ok",
                started_at=finished - timedelta(minutes=10),
                finished_at=finished,
            )
        )
    pending, _reason = catch_up_pending(_NOW)
    assert pending is False


def test_catch_up_pending_true_when_ok_ingest_finished_before_the_cutoff(db_url: str) -> None:
    finished = _CUTOFF - timedelta(hours=1)
    with session_scope() as session:
        session.add(
            IngestionRun(
                provider="fixture",
                feed_type=FeedType.BAR_DAILY,
                requested_start=date(2024, 6, 10),
                requested_end=date(2024, 6, 11),
                status="ok",
                started_at=finished - timedelta(minutes=10),
                finished_at=finished,
            )
        )
    pending, reason = catch_up_pending(_NOW)
    assert pending is True
    assert finished.isoformat() in reason


def test_catch_up_pending_backs_off_after_a_recent_failed_attempt(db_url: str) -> None:
    started = _NOW - timedelta(minutes=30)
    with session_scope() as session:
        session.add(
            JobRun(
                name="daily_eod_update",
                status="failed",
                started_at=started,
                finished_at=started + timedelta(minutes=1),
                detail="provider down",
            )
        )
    pending, reason = catch_up_pending(_NOW)
    assert pending is False
    assert "backing off" in reason


def test_catch_up_pending_resumes_after_the_backoff_window(db_url: str) -> None:
    assert timedelta(hours=2) == CATCH_UP_RETRY_BACKOFF
    started = _NOW - timedelta(hours=3)  # older than CATCH_UP_RETRY_BACKOFF
    with session_scope() as session:
        session.add(
            JobRun(
                name="daily_eod_update",
                status="failed",
                started_at=started,
                finished_at=started + timedelta(minutes=1),
                detail="provider down",
            )
        )
    pending, reason = catch_up_pending(_NOW)
    assert pending is True
    assert "no OK daily-bar ingestion" in reason


# --------------------------------------------------------------------------- #
# job_catch_up
# --------------------------------------------------------------------------- #
def test_job_catch_up_runs_the_eod_update_when_pending(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(sched, "catch_up_pending", lambda: (True, "x"))
    monkeypatch.setattr(sched, "job_daily_eod_update", lambda: calls.append("ran"))
    job_catch_up()
    assert calls == ["ran"]


def test_job_catch_up_does_nothing_when_not_pending(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(sched, "catch_up_pending", lambda: (False, "y"))
    monkeypatch.setattr(sched, "job_daily_eod_update", lambda: calls.append("ran"))
    job_catch_up()
    assert calls == []


# --------------------------------------------------------------------------- #
# default_job_specs / build_scheduler: the new catch_up job
# --------------------------------------------------------------------------- #
def test_default_job_specs_includes_a_catch_up_spec_every_30_minutes() -> None:
    specs = {s.name: s for s in default_job_specs()}
    assert "catch_up" in specs
    assert specs["catch_up"].interval_minutes == 30
    assert specs["catch_up"].cron_hour is None  # interval trigger, not a daily cron


def test_build_scheduler_registers_the_catch_up_job(db_url: str) -> None:
    scheduler = build_scheduler()
    jobs = {j.id: j for j in scheduler.get_jobs()}
    assert "catch_up" in jobs
    assert type(jobs["catch_up"].trigger).__name__ == "IntervalTrigger"


# --------------------------------------------------------------------------- #
# record_heartbeat
# --------------------------------------------------------------------------- #
def test_record_heartbeat_upserts_a_single_row_with_next_runs(db_url: str) -> None:
    started_at = _et(2024, 6, 12, 17, 0)

    record_heartbeat(None, started_at=started_at)

    with session_scope() as session:
        rows = list(session.scalars(select(WorkerHeartbeat)))
        assert len(rows) == 1
        assert rows[0].worker == "scheduler"
        assert rows[0].next_runs_json == {}
        first_id = rows[0].id
        first_beat = rows[0].last_beat_at

    class _FakeJob:
        def __init__(self, id: str, next_run_time: datetime) -> None:
            self.id = id
            self.next_run_time = next_run_time

    next_run_time = datetime(2024, 6, 13, 17, 30, tzinfo=ZoneInfo("America/New_York"))

    class _FakeScheduler:
        def get_jobs(self) -> list[_FakeJob]:
            return [_FakeJob("daily_eod_update", next_run_time)]

    record_heartbeat(_FakeScheduler(), started_at=started_at)

    with session_scope() as session:
        rows = list(session.scalars(select(WorkerHeartbeat)))
        assert len(rows) == 1  # updated in place -- no second row
        row = rows[0]
        assert row.id == first_id
        assert row.pid == os.getpid()
        assert row.last_beat_at >= first_beat
        assert row.next_runs_json == {"daily_eod_update": next_run_time.astimezone(UTC).isoformat()}


# --------------------------------------------------------------------------- #
# /ops page: worker liveness + catch-up section, readiness checklist
# --------------------------------------------------------------------------- #
def test_ops_page_with_no_heartbeat_shows_worker_down_and_catchup_pending(
    ops_client,
) -> None:
    r = ops_client.get("/ops")
    assert r.status_code == 200
    text = r.text
    assert "not running" in text
    assert "will not fire: no worker" in text
    assert "PENDING" in text
    assert "Worker running (heartbeat)" in text
    assert "Daily bars current for last completed session" in text
    assert "No catch-up pending" in text

    with get_sessionmaker()() as session:
        ctx = ops_status_context(session)
    assert ctx["worker"]["running"] is False
    assert ctx["worker"]["seen"] is False


def test_ops_page_with_a_fresh_heartbeat_shows_worker_running(ops_client) -> None:
    now = datetime.now(UTC)
    next_run_iso = (now + timedelta(hours=1)).isoformat()
    with session_scope() as session:
        session.add(
            WorkerHeartbeat(
                worker="scheduler",
                host="testhost",
                pid=4321,
                started_at=now,
                last_beat_at=now,
                next_runs_json={"daily_eod_update": next_run_iso},
            )
        )

    r = ops_client.get("/ops")
    assert r.status_code == 200
    assert "running" in r.text
    assert next_run_iso[:16] in r.text

    with get_sessionmaker()() as session:
        ctx = ops_status_context(session)
    assert ctx["worker"]["running"] is True


def test_ops_page_stale_heartbeat_is_seen_but_not_running(ops_client) -> None:
    stale_beat = datetime.now(UTC) - timedelta(seconds=WORKER_STALE_AFTER_S + 30)
    with session_scope() as session:
        session.add(
            WorkerHeartbeat(
                worker="scheduler",
                host="testhost",
                pid=1,
                started_at=stale_beat,
                last_beat_at=stale_beat,
                next_runs_json={},
            )
        )

    with get_sessionmaker()() as session:
        ctx = ops_status_context(session)
    assert ctx["worker"]["running"] is False
    assert ctx["worker"]["seen"] is True
