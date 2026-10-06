"""Incident 2026-09-28..30: ingest deadline, multi-session catch-up, EOD gap.

Three behaviours, all offline (no provider, no network — the ingest is either
the deterministic fixture adapter or a fake):

1. the daily-bar ingest stops at a wall-clock deadline BETWEEN symbols,
   releases the EOD lock, fails the job with a clear reason and leaves a
   resumable ``stopped`` run that the next ingest continues;
2. catch-up resolves EVERY missed completed session oldest-first — an ingest
   row and an explicit ``scan_skipped_missed_session`` row each — and only the
   latest completed session runs the real scan that may feed auto-simulation;
3. a last completed session with no successful EOD job run after its expected
   time + grace is flagged on ``/ops`` and by the health check.
"""

from __future__ import annotations

import types
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

import signalforge.scheduler as sched
from signalforge.config.research import ResearchConfig
from signalforge.config.settings import Settings, get_settings
from signalforge.db.models import AuditLog, IngestionRun, JobRun
from signalforge.db.session import get_sessionmaker, session_scope
from signalforge.db.types import utcnow
from signalforge.domain import FeedType
from signalforge.research.approved_scope_scan import AUDIT_COMPLETED

pytestmark = pytest.mark.safety


def _et(y: int, m: int, d: int, hh: int, mm: int) -> datetime:
    return datetime(y, m, d, hh, mm, tzinfo=ZoneInfo("America/New_York")).astimezone(UTC)


def _job_rows(name: str) -> list[JobRun]:
    with session_scope() as session:
        rows = list(session.scalars(select(JobRun).where(JobRun.name == name).order_by(JobRun.id)))
        session.expunge_all()
    return rows


# --------------------------------------------------------------------------- #
# 1. ingest deadline
# --------------------------------------------------------------------------- #
class _SteppingClock:
    """Deterministic monotonic clock: every reading is ``step`` seconds later."""

    def __init__(self, step: float) -> None:
        self.step = step
        self.t = 0.0

    def __call__(self) -> float:
        now = self.t
        self.t += self.step
        return now


@pytest.fixture
def fetched(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Replace the per-symbol fetch+write with a recorder (no provider)."""
    from signalforge.data.ingest import SymbolIngestResult

    seen: list[str] = []

    def _fake_ingest_symbol(session, adapter, symbol, start, end):  # type: ignore[no-untyped-def]
        seen.append(symbol)
        return SymbolIngestResult(symbol=symbol.upper(), bars_written=1)

    monkeypatch.setattr("signalforge.data.ingest.ingest_symbol", _fake_ingest_symbol)
    return seen


def test_ingest_stops_at_the_deadline_between_symbols_and_resumes(
    db_url: str, monkeypatch: pytest.MonkeyPatch, fetched: list[str]
) -> None:
    universe = list(get_settings().research.universe)
    assert len(universe) > 6
    assert get_settings().eod_ingest_deadline_minutes == 45.0  # conservative default

    # 10 minutes per clock reading: start=0, then one poll before each symbol
    # (10, 20, 30, 40 -> run; 50 -> past the 45 min deadline). Exactly four
    # symbols are fetched and committed; the fifth is never started.
    monkeypatch.setattr(sched, "_clock", _SteppingClock(600.0))
    with pytest.raises(sched.IngestDeadlineExceeded) as err:
        sched.job_ingest()
    reason = str(err.value)
    assert reason == (
        f"deadline exceeded after 4/{len(universe)} symbols (45 min); resume on next catch-up"
    )
    assert fetched == universe[:4]

    with session_scope() as session:
        runs = list(session.scalars(select(IngestionRun)))
        assert len(runs) == 1
        stopped = runs[0]
        stopped_id = stopped.id
        assert stopped.status == "stopped"  # never ok/partial: nothing scans on it
        assert stopped.symbols_ok == universe[:4]
        assert stopped.bars_written == 4
        assert stopped.gaps_json["deadline"]["symbols_done"] == 4
        assert "deadline exceeded after 4/" in stopped.notes
    # a stopped run never satisfies the catch-up — the session is still owed
    assert sched.catch_up_pending()[0] is True

    # Next ingest (clock no longer advancing): only the REMAINING symbols are
    # fetched, and the same run row is completed rather than a second one made.
    fetched.clear()
    monkeypatch.setattr(sched, "_clock", lambda: 0.0)
    sched.job_ingest()
    assert fetched == universe[4:]
    with session_scope() as session:
        runs = list(session.scalars(select(IngestionRun)))
        assert len(runs) == 1 and runs[0].id == stopped_id
        assert runs[0].status == "ok"
        assert runs[0].symbols_ok == universe
        assert runs[0].bars_written == len(universe)
        assert "deadline" not in runs[0].gaps_json
        assert runs[0].gaps_json["resumed_after_deadline"] == {"carried_over": 4}
    assert sched.catch_up_pending()[0] is False


def test_deadline_fails_the_eod_job_releases_the_lock_and_skips_both_scans(
    db_url: str, monkeypatch: pytest.MonkeyPatch, fetched: list[str]
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(sched, "job_scan_all", lambda: calls.append("scan"))
    monkeypatch.setattr(sched, "job_approved_scope_scan", lambda: calls.append("approved"))
    monkeypatch.setattr(sched, "_clock", _SteppingClock(600.0))

    with pytest.raises(sched.IngestDeadlineExceeded):
        sched.guarded("daily_eod_update", sched.job_daily_eod_update)()

    assert calls == []  # never scan a half-fetched session
    assert not sched._EOD_UPDATE_LOCK.locked()  # the lock is not held past the deadline
    assert sched._EOD_UNIT_STARTED_AT is None
    # The clock started when the LOCK was taken (reading 0) and the ingest
    # reused that reading — the locked unit as a whole is what is bounded.
    assert len(fetched) == 4
    (row,) = _job_rows("daily_eod_update")
    assert row.status == "failed"
    assert "deadline exceeded after 4/" in row.detail
    assert "resume on next catch-up" in row.detail


def test_a_stopped_run_from_before_the_session_cutoff_is_not_resumed(
    db_url: str, monkeypatch: pytest.MonkeyPatch, fetched: list[str]
) -> None:
    """Symbols fetched before the session's bars were published may lack that
    session's bar, so such a run must be redone in full, not carried over."""
    universe = list(get_settings().research.universe)
    monkeypatch.setattr(sched, "_clock", _SteppingClock(600.0))
    with pytest.raises(sched.IngestDeadlineExceeded):
        sched.job_ingest()
    cutoff = sched._session_cutoff_utc(sched.last_completed_session())
    with session_scope(write=True) as session:
        run = session.scalar(select(IngestionRun))
        assert run is not None
        run.started_at = cutoff - timedelta(minutes=5)

    fetched.clear()
    monkeypatch.setattr(sched, "_clock", lambda: 0.0)
    sched.job_ingest()
    assert fetched == universe  # a full pass
    with session_scope() as session:
        statuses = sorted(r.status for r in session.scalars(select(IngestionRun)))
    assert statuses == ["ok", "stopped"]  # the old row is left as the record it is


def test_kill_switch_still_skips_the_eod_update(db_url: str, fetched: list[str]) -> None:
    from signalforge.killswitch import get_kill_switch

    get_kill_switch().engage(reason="halt", actor="pytest")
    sched.guarded("daily_eod_update", sched.job_daily_eod_update)()
    assert fetched == []
    (row,) = _job_rows("daily_eod_update")
    assert row.status == "skipped" and "kill switch" in row.detail


# --------------------------------------------------------------------------- #
# 2. multi-session catch-up
# --------------------------------------------------------------------------- #
def _window(n: int = 10) -> list[date]:
    return sched._lookback_sessions(sched.last_completed_session(), n)


def _anchor_scan_completed(session_date: date, *, readiness_enforced: bool = True) -> None:
    """An approved-scope scan that completed while ``session_date`` was the
    last completed session."""
    with session_scope(write=True) as session:
        session.add(
            AuditLog(
                # exactly at the cutoff: never in the future, whatever time it is
                ts=sched._session_cutoff_utc(session_date),
                actor="scheduler",
                action=AUDIT_COMPLETED,
                entity="approved_scope_scan",
                before_json={},
                after_json={"readiness_enforced": readiness_enforced, "runs": []},
            )
        )


@pytest.fixture
def chain(monkeypatch: pytest.MonkeyPatch) -> types.SimpleNamespace:
    """A fake provider pass + a real ``job_approved_scope_scan`` whose scan and
    auto-simulation entry points are recorded."""
    rec = types.SimpleNamespace(ingests=0, scans=0, approved=0, auto_sim=[], fail_ingest=False)

    def _fake_job_ingest() -> None:
        rec.ingests += 1
        if rec.fail_ingest:
            raise RuntimeError("provider down")
        configured = list(get_settings().research.universe)
        now = utcnow()
        with session_scope(write=True) as session:
            session.add(
                IngestionRun(
                    provider="fixture",
                    feed_type=FeedType.BAR_DAILY,
                    kind="incremental",
                    requested_start=now.date() - timedelta(days=400),
                    requested_end=now.date(),
                    symbols_requested=configured,
                    symbols_ok=configured,
                    symbols_failed={},
                    status="ok",
                    started_at=now,
                    finished_at=now,
                )
            )

    def _fake_approved_scan(session, **_kw):  # type: ignore[no-untyped-def]
        rec.approved += 1
        return types.SimpleNamespace(
            ran=True,
            runs=[{"scan_run_id": 700 + rec.approved}],
            blocked_reason="",
            blocked_universes=[],
            skipped_versions=[],
        )

    def _fake_auto_sim(session, scan_run_ids):  # type: ignore[no-untyped-def]
        rec.auto_sim.append(list(scan_run_ids))
        return types.SimpleNamespace(
            enabled=True, considered=0, accepted=[], rejected=[], watched=[], skipped=[]
        )

    def _fake_scan_all() -> None:
        rec.scans += 1

    monkeypatch.setattr(sched, "job_ingest", _fake_job_ingest)
    monkeypatch.setattr(sched, "job_scan_all", _fake_scan_all)
    monkeypatch.setattr(
        "signalforge.research.approved_scope_scan.run_approved_scope_scan", _fake_approved_scan
    )
    monkeypatch.setattr("signalforge.paper.auto_simulate.auto_simulate_scan_runs", _fake_auto_sim)
    return rec


def test_three_missed_sessions_are_resolved_oldest_first_and_only_the_latest_is_scanned(
    db_url: str, chain: types.SimpleNamespace
) -> None:
    window = _window()
    _anchor_scan_completed(window[-4])  # last good session: 4 before the latest
    missed = window[-3:]
    owed, why = sched.missed_sessions()
    assert owed == missed, why

    sched.guarded("catch_up", sched.job_catch_up)()

    # one ingest row + one explicit skip row PER missed session, oldest first
    ingest_rows = _job_rows(sched.MISSED_SESSION_INGEST_JOB)
    skip_rows = _job_rows(sched.MISSED_SESSION_SKIP_JOB)
    assert [r.detail.split(":")[0] for r in ingest_rows] == [
        f"session={d.isoformat()}" for d in missed
    ]
    assert [r.detail.split(":")[0] for r in skip_rows] == [
        f"session={d.isoformat()}" for d in missed
    ]
    assert all(r.status == "ok" for r in ingest_rows)
    assert all(r.status == "skipped" for r in skip_rows)
    assert all("NOT run" in r.detail and "no auto-simulation" in r.detail for r in skip_rows)
    # interleaved per session: ingest(s1), skip(s1), ingest(s2), skip(s2), ...
    order = sorted([*ingest_rows, *skip_rows], key=lambda r: r.id)
    assert [r.name for r in order] == [
        sched.MISSED_SESSION_INGEST_JOB,
        sched.MISSED_SESSION_SKIP_JOB,
    ] * 3

    # ONE provider pass served all three sessions AND the latest one: the
    # 400-day window ends today, so re-fetching it per session would only
    # hammer the provider for bars already stored.
    assert chain.ingests == 1
    assert "fetched now" in ingest_rows[0].detail
    assert all("already ingested" in r.detail for r in ingest_rows[1:])

    # The real scan chain ran exactly once — for the LATEST completed session —
    # and that is the only scan handed to auto-simulation. No scan exists for a
    # missed past session, so nothing from one can ever be simulated.
    assert chain.scans == 1
    assert chain.approved == 1
    assert chain.auto_sim == [[701]]
    assert len(_job_rows("approved_scope_scan")) == 1
    (catch_up_row,) = _job_rows("catch_up")
    assert catch_up_row.status == "ok"
    assert not sched._EOD_UPDATE_LOCK.locked()

    # Idempotent: a second catch-up finds nothing owed and writes nothing new.
    assert sched.missed_sessions()[0] == []
    sched.guarded("catch_up", sched.job_catch_up)()
    assert chain.ingests == 1 and chain.scans == 1 and chain.auto_sim == [[701]]
    assert len(_job_rows(sched.MISSED_SESSION_INGEST_JOB)) == 3
    assert len(_job_rows(sched.MISSED_SESSION_SKIP_JOB)) == 3


def test_missed_sessions_only_no_latest_scan_and_no_auto_simulation_when_latest_is_current(
    db_url: str, chain: types.SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The latest session's bars are already in (a covering ingest exists), so
    only the missed past sessions are resolved: no provider pass at all, no
    scan, and — the point — nothing offered to auto-simulation."""
    window = _window()
    _anchor_scan_completed(window[-3])
    sched.job_ingest()  # (the fake) a covering ok run, finished now
    assert chain.ingests == 1
    assert sched.catch_up_pending()[0] is False

    sched.job_catch_up()

    assert chain.ingests == 1  # covered already — no second pass
    assert chain.scans == 0 and chain.approved == 0 and chain.auto_sim == []
    assert len(_job_rows(sched.MISSED_SESSION_SKIP_JOB)) == 2
    assert all("already ingested" in r.detail for r in _job_rows(sched.MISSED_SESSION_INGEST_JOB))


def test_look_back_is_bounded(db_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    far = _window(30)
    _anchor_scan_completed(far[0])  # 30 sessions ago
    owed, _why = sched.missed_sessions()
    assert owed == _window(10)  # default look-back: the 10 most recent only

    monkeypatch.setenv("CATCH_UP_LOOKBACK_SESSIONS", "2")
    get_settings.cache_clear()
    owed, _why = sched.missed_sessions()
    assert owed == _window(10)[-2:]

    monkeypatch.setenv("CATCH_UP_LOOKBACK_SESSIONS", "0")
    get_settings.cache_clear()
    assert sched.missed_sessions()[0] == []


def test_nothing_is_owed_without_an_anchor_or_from_a_readiness_bypassed_scan(
    db_url: str,
) -> None:
    owed, why = sched.missed_sessions()
    assert owed == [] and "nothing to catch up since" in why
    # a manual scan with the readiness gate bypassed is not proof of a good session
    _anchor_scan_completed(_window()[-2], readiness_enforced=False)
    assert sched.missed_sessions()[0] == []
    # a scan while the latest session was current: no gap
    _anchor_scan_completed(sched.last_completed_session())
    owed, why = sched.missed_sessions()
    assert owed == [] and "no gap" in why


def test_failed_ingest_leaves_the_session_owed_with_no_skip_row_and_then_backs_off(
    db_url: str, chain: types.SimpleNamespace
) -> None:
    window = _window()
    _anchor_scan_completed(window[-3])
    chain.fail_ingest = True

    with pytest.raises(RuntimeError, match="provider down"):
        sched.guarded("catch_up", sched.job_catch_up)()

    assert not sched._EOD_UPDATE_LOCK.locked()
    assert _job_rows(sched.MISSED_SESSION_SKIP_JOB) == []  # never claimed as resolved
    (failed,) = _job_rows(sched.MISSED_SESSION_INGEST_JOB)
    assert failed.status == "failed"
    assert failed.detail.startswith(f"session={window[-2].isoformat()}")
    assert chain.scans == 0 and chain.auto_sim == []
    # a broken provider is retried after the back-off, not hammered
    owed, why = sched.missed_sessions()
    assert owed == [] and "backing off" in why
    owed, _why = sched.missed_sessions(utcnow() + sched.CATCH_UP_RETRY_BACKOFF)
    assert owed and owed[0] == window[-2]


def test_startup_catch_up_resolves_missed_sessions_and_never_crashes_startup(
    db_url: str, chain: types.SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    window = _window()
    _anchor_scan_completed(window[-3])
    monkeypatch.setattr(sched, "_last_scan_age", lambda: timedelta(hours=1))  # scan is fresh

    sched.run_catch_up()
    assert len(_job_rows(sched.MISSED_SESSION_SKIP_JOB)) == 2
    assert chain.scans == 0 and chain.auto_sim == []  # past sessions only

    # a failing pass is recorded and swallowed: the worker must still start
    with session_scope(write=True) as session:
        for row in session.scalars(select(JobRun)):
            session.delete(row)
        for run in session.scalars(select(IngestionRun)):
            session.delete(run)
    chain.fail_ingest = True
    sched.run_catch_up()  # must not raise
    (row,) = _job_rows(sched.MISSED_SESSIONS_JOB)
    assert row.status == "failed"


# --------------------------------------------------------------------------- #
# 3. EOD gap visibility
# --------------------------------------------------------------------------- #
_SESSION = date(2024, 6, 12)  # a Wednesday
_CUTOFF = _et(2024, 6, 12, 17, 30)


def _add_job_run(name: str, started: datetime, status: str = "ok") -> None:
    with session_scope(write=True) as session:
        session.add(JobRun(name=name, started_at=started, finished_at=started, status=status))


def test_eod_gap_is_flagged_only_after_expected_time_plus_grace(db_url: str) -> None:
    assert get_settings().eod_gap_grace_minutes == 120.0
    gap, why = sched.eod_gap(_CUTOFF + timedelta(minutes=119))
    assert gap is False and "not yet overdue" in why

    late = _CUTOFF + timedelta(minutes=121)
    gap, why = sched.eod_gap(late)
    assert gap is True
    assert "no successful EOD job run for 2024-06-12" in why and "no ok EOD run ever" in why

    # the 30-minute catch_up row is written ok even when it did nothing, and a
    # failed EOD run is not a run: neither closes the gap
    _add_job_run("catch_up", _CUTOFF + timedelta(minutes=30))
    _add_job_run("daily_eod_update", _CUTOFF + timedelta(minutes=1), status="failed")
    _add_job_run("daily_eod_update", _CUTOFF - timedelta(hours=24))  # yesterday's
    gap, why = sched.eod_gap(late)
    assert gap is True and "last ok EOD run: " in why

    _add_job_run("daily_eod_update", _CUTOFF + timedelta(minutes=40))
    gap, why = sched.eod_gap(late)
    assert gap is False and "daily_eod_update ok" in why


def test_a_multi_day_gap_names_every_unscanned_session(db_url: str) -> None:
    """The incident shape: nothing ran for days. Friday 06-07 was the last
    scanned session; by Wednesday night Mon/Tue are missed and Wed is overdue."""
    with session_scope(write=True) as session:
        session.add(
            AuditLog(
                ts=_et(2024, 6, 7, 18, 30),
                actor="scheduler",
                action=AUDIT_COMPLETED,
                entity="approved_scope_scan",
                before_json={},
                after_json={"readiness_enforced": True},
            )
        )
    now = _et(2024, 6, 12, 23, 0)
    assert sched.missed_sessions(now)[0] == [date(2024, 6, 10), date(2024, 6, 11)]
    gap, why = sched.eod_gap(now)
    assert gap is True
    assert "earlier sessions also unscanned: 2024-06-10, 2024-06-11" in why


def test_ops_status_surfaces_the_eod_gap_as_a_failed_readiness_check(
    db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from signalforge.app.views import ops_status_context

    monkeypatch.setattr(sched, "eod_gap", lambda now=None: (True, "no successful EOD job run"))
    with get_sessionmaker()() as session:
        ctx = ops_status_context(session)
    assert ctx["eod_gap"] == {"gap": True, "reason": "no successful EOD job run"}
    check = next(
        c for c in ctx["checks"] if c["label"] == "EOD update ran for last completed session"
    )
    assert check["ok"] is False and check["note"] == "no successful EOD job run"
    assert ctx["overall_ready"] is False

    monkeypatch.setattr(sched, "eod_gap", lambda now=None: (False, "daily_eod_update ok"))
    with get_sessionmaker()() as session:
        ctx = ops_status_context(session)
    check = next(
        c for c in ctx["checks"] if c["label"] == "EOD update ran for last completed session"
    )
    assert check["ok"] is True


def test_health_check_logs_the_gap_as_degraded_without_failing(
    db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    events: list[tuple[str, dict[str, object]]] = []
    monkeypatch.setattr(sched, "job_feed_probe", lambda: None)
    monkeypatch.setattr(sched, "eod_gap", lambda now=None: (True, "no successful EOD job run"))
    monkeypatch.setattr(
        sched._log, "warning", lambda event, **kw: events.append((event, kw)), raising=False
    )
    sched.guarded("health_check", sched.job_health_check)()
    assert ("health.eod_gap", {"status": "degraded", "detail": "no successful EOD job run"}) in (
        events
    )
    (row,) = _job_rows("health_check")
    assert row.status == "ok"  # visible, not a new failure loop


# --------------------------------------------------------------------------- #
# 4. the new fields are operating policy — they can never move a scope hash
# --------------------------------------------------------------------------- #
_NEW_FIELDS = ("eod_ingest_deadline_minutes", "catch_up_lookback_sessions", "eod_gap_grace_minutes")


def test_new_worker_fields_live_on_settings_and_leave_every_config_hash_unchanged() -> None:
    assert set(_NEW_FIELDS) <= set(Settings.model_fields)
    assert not set(_NEW_FIELDS) & set(ResearchConfig.model_fields)
    assert not set(_NEW_FIELDS) & set(ResearchConfig.SCOPE_HASH_FIELDS)

    default = Settings()
    changed = Settings(
        eod_ingest_deadline_minutes=5, catch_up_lookback_sessions=3, eod_gap_grace_minutes=30
    )
    assert changed.research.config_hash == default.research.config_hash
    assert changed.research.full_config_hash == default.research.full_config_hash
    # ...and the default scope hash is exactly the hash of a bare ResearchConfig
    assert default.research.config_hash == ResearchConfig().config_hash


# --------------------------------------------------------------------------- #
# 5. incident 2026-10-05: host slept mid-ingest
# --------------------------------------------------------------------------- #
class _ReadingsClock:
    """Deterministic raw clock source: returns ``readings`` in order, then
    repeats the last one."""

    def __init__(self, *readings: float) -> None:
        self.readings = list(readings)

    def __call__(self) -> float:
        if len(self.readings) > 1:
            return self.readings.pop(0)
        return self.readings[0]


def test_a_wall_clock_jump_with_no_monotonic_progress_trips_the_deadline_between_symbols(
    db_url: str, monkeypatch: pytest.MonkeyPatch, fetched: list[str]
) -> None:
    """``time.monotonic`` does not advance while a Mac sleeps. The host slept
    ~3 h mid-ingest on 2026-10-05 and the 45-minute deadline never expired.
    The deadline clock must count wall-clock time too."""
    assert sched._clock is sched._deadline_clock  # the default, not a test stub
    # monotonic frozen at its base: zero elapsed, forever
    monkeypatch.setattr(sched, "_mono_source", lambda: sched._MONO_BASE)
    # wall clock: lock taken (0), first poll before symbol 1 (0), then the
    # machine wakes up 3 hours later before symbol 2
    monkeypatch.setattr(
        sched,
        "_wall_source",
        _ReadingsClock(sched._WALL_BASE, sched._WALL_BASE, sched._WALL_BASE + 3 * 3600.0),
    )

    with pytest.raises(sched.IngestDeadlineExceeded) as excinfo:
        sched.guarded("daily_eod_update", sched.job_daily_eod_update)()

    assert len(fetched) == 1  # stopped BETWEEN symbols, after the one that completed
    assert "deadline exceeded after 1/" in str(excinfo.value)
    assert not sched._EOD_UPDATE_LOCK.locked()
    with session_scope() as session:
        (run,) = list(session.scalars(select(IngestionRun)))
        assert run.status == sched.INGEST_STATUS_STOPPED
        assert run.gaps_json["deadline"]["symbols_done"] == 1


def test_deadline_clock_is_the_larger_of_monotonic_and_wall_elapsed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sched, "_mono_source", lambda: sched._MONO_BASE + 10.0)
    monkeypatch.setattr(sched, "_wall_source", lambda: sched._WALL_BASE + 3600.0)
    assert sched._deadline_clock() == 3600.0  # a sleep counts in full
    # a wall clock stepped backwards (NTP) cannot shrink the budget
    monkeypatch.setattr(sched, "_wall_source", lambda: sched._WALL_BASE - 3600.0)
    assert sched._deadline_clock() == 10.0


def test_guarded_writes_a_running_row_first_and_finishes_the_same_row(db_url: str) -> None:
    seen: list[tuple[int, str, datetime | None]] = []

    def _body() -> None:
        (row,) = _job_rows("traced")
        seen.append((row.id, row.status, row.finished_at))

    sched.guarded("traced", _body)()
    (row,) = _job_rows("traced")
    assert seen == [(row.id, sched.JOB_RUN_RUNNING, None)]  # visible while in flight
    assert row.status == "ok" and row.finished_at is not None  # same row, now finished

    def _boom() -> None:
        raise RuntimeError("provider down")

    with pytest.raises(RuntimeError):
        sched.guarded("traced_fail", _boom)()
    (row,) = _job_rows("traced_fail")
    assert row.status == "failed" and "provider down" in row.detail


def test_a_killed_job_leaves_a_running_row_and_startup_marks_it_interrupted(
    db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SIGTERM/SIGKILL/host sleep: ``guarded()`` never gets to write the final
    status (a ``BaseException`` stands in for the process dying). The row
    with its start time is the only trace, and the next worker start-up turns
    it into an explicit ``interrupted`` outcome."""

    def _killed() -> None:
        raise SystemExit(143)

    with pytest.raises(SystemExit):
        sched.guarded("daily_eod_update", _killed)()
    (row,) = _job_rows("daily_eod_update")
    assert row.status == sched.JOB_RUN_RUNNING and row.finished_at is None
    started = row.started_at

    # a row started AFTER this process started belongs to a live job: untouched
    future = datetime.now(UTC) + timedelta(hours=1)
    with session_scope(write=True) as session:
        session.add(JobRun(name="live_job", started_at=future, status=sched.JOB_RUN_RUNNING))

    monkeypatch.setattr(sched, "_last_scan_age", lambda: timedelta(0))  # fresh: no ingest
    monkeypatch.setattr(sched, "job_catch_up_missed_sessions", lambda: None)
    sched.run_catch_up()  # the worker start-up path

    (row,) = _job_rows("daily_eod_update")
    assert row.status == sched.JOB_RUN_INTERRUPTED
    assert row.detail == "worker restarted"
    assert row.started_at == started and row.finished_at is not None
    (live,) = _job_rows("live_job")
    assert live.status == sched.JOB_RUN_RUNNING


def test_running_and_interrupted_rows_are_not_eod_evidence(db_url: str) -> None:
    late = _CUTOFF + timedelta(minutes=121)
    _add_job_run("daily_eod_update", _CUTOFF + timedelta(minutes=1), status="running")
    _add_job_run("approved_scope_scan", _CUTOFF + timedelta(minutes=2), status="interrupted")
    gap, why = sched.eod_gap(late)
    assert gap is True and "no ok EOD run ever" in why

    # /ops: shown as the last attempt, never as a success
    from signalforge.app.views import ops_status_context

    with get_sessionmaker()() as session:
        ctx = ops_status_context(session)
    jobs = {j["name"]: j for j in ctx["jobs"]}
    assert jobs["daily_eod_update"]["status"] == "running"
    assert jobs["daily_eod_update"]["last_success_at"] is None
    assert jobs["approved_scope_scan"]["status"] == "interrupted"
    assert jobs["approved_scope_scan"]["last_success_at"] is None


def test_catch_up_losing_the_lock_race_skips_quietly_without_announcing_a_run(
    db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The cron EOD update takes the lock between catch-up's ``locked()`` peek
    and its own acquire. Before: ``catch_up.running`` was logged and the EOD
    body silently skipped. Now catch-up holds the lock itself, so it logs
    ``catch_up.skipped`` and runs nothing."""
    events: list[tuple[str, str]] = []
    monkeypatch.setattr(
        sched._log, "warning", lambda event, **kw: events.append(("warning", event)), raising=False
    )
    monkeypatch.setattr(
        sched._log, "info", lambda event, **kw: events.append(("info", event)), raising=False
    )
    steps: list[bool] = []
    monkeypatch.setattr(sched, "_eod_update_steps", lambda *, ingest: steps.append(ingest))
    monkeypatch.setattr(sched, "_safe_missed_sessions", lambda: [])

    def _pending_and_race(now: datetime | None = None) -> tuple[bool, str]:
        assert sched._EOD_UPDATE_LOCK.acquire(blocking=False)  # the cron job wins
        return True, "owed"

    monkeypatch.setattr(sched, "catch_up_pending", _pending_and_race)
    try:
        sched.job_catch_up()
    finally:
        sched._EOD_UPDATE_LOCK.release()

    assert steps == []
    assert ("info", "catch_up.skipped") in events
    assert ("warning", "catch_up.running") not in events

    # and with the lock free, the SAME path runs the chain under catch-up's own lock
    events.clear()
    monkeypatch.setattr(sched, "catch_up_pending", lambda now=None: (True, "owed"))
    sched.job_catch_up()
    assert steps == [True]
    assert ("warning", "catch_up.running") in events
    assert not sched._EOD_UPDATE_LOCK.locked()
