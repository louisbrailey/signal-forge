"""Every approved-scope session ends with exactly one explicit outcome.

Incident 2026-10-08..11-06: ``trend_continuation.short_swing`` (snapshot 3)
was scanned on 13 of 22 sessions; 10-14/10-19/10-20 carried a ``completed``
row with ``scanned=0`` and 10-21/11-05 left no record at all. A
``completed`` audit row was written with ``scanned=0``, and
``missed_sessions`` only owed sessions after the NEWEST completed row, so a
later session landing first hid an earlier gap. These tests pin the fix, all
offline on fixed 2024 dates:

* missed (no attempt at all) — owed by ``missed_sessions`` even after a later
  session was scanned, and recorded ``skipped: missed``;
* readiness-blocked — recorded ``skipped: readiness_blocked``, not owed;
* nothing scanned — recorded ``skipped: data_hold`` (stale/missing data) or
  ``skipped: all_excluded`` (other gates), never ``completed``;
* a scope that leaves the approved set is still closed out for the sessions
  inside its approved window;
* exactly one row per (session, scope), the open session never recorded, and
  nothing is ever scanned for a past session.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from freezegun import freeze_time
from sqlalchemy import select
from sqlalchemy.orm import Session
from typer.testing import CliRunner

import signalforge.scheduler as sched
from signalforge.db.models import AuditLog, JobRun, ScanRun
from signalforge.db.session import session_scope
from signalforge.domain import Horizon
from signalforge.research import scan_session_outcomes as mod
from signalforge.research.approved_scope_scan import (
    AUDIT_BLOCKED,
    AUDIT_COMPLETED,
    AUDIT_NOTHING_SCANNED,
    ApprovedScanGroup,
)
from signalforge.research.scan_session_outcomes import (
    NOT_IN_SCOPE,
    OPEN,
    REASON_ALL_EXCLUDED,
    REASON_DATA_HOLD,
    REASON_FAILED,
    REASON_MISSED,
    REASON_READINESS,
    SCANNED,
    SESSION_OUTCOME_ACTION,
    SKIPPED,
    ScopeKey,
    attempt_session,
    closed_sessions,
    pending_session_outcomes,
    record_session_outcomes,
    session_outcomes,
)

pytestmark = pytest.mark.safety

GROUP = ApprovedScanGroup(
    horizon=Horizon.SHORT_SWING,
    dataset_snapshot_id=3,
    dataset_key="universe_24",
    source="massive",
    symbols=("AAA", "BBB"),
    strategy_version_ids=(2,),
)
KEY = ScopeKey.of(GROUP)

D_SCANNED = date(2024, 6, 5)  # Wed: first good scan
D_MISSED = date(2024, 6, 6)  # Thu: no attempt at all (worker asleep)
D_BLOCKED = date(2024, 6, 7)  # Fri: readiness gate blocked the universe
D_HOLD = date(2024, 6, 10)  # Mon: scan ran, every symbol excluded
D_LATER = date(2024, 6, 11)  # Tue: scanned — lands AFTER the D_MISSED gap
D_FAILED = date(2024, 6, 12)  # Wed: the scan job failed
D_OPEN = date(2024, 6, 13)  # Thu: still the bar a scan requires
NOW = datetime(2024, 6, 13, 22, 0, tzinfo=UTC)  # 18:00 ET Thursday


def _et(d: date, hh: int, mm: int = 0) -> datetime:
    return datetime(d.year, d.month, d.day, hh, mm, tzinfo=ZoneInfo("America/New_York")).astimezone(
        UTC
    )


def _run(scanned: int, scan_run_id: int, key: ScopeKey = KEY) -> dict[str, Any]:
    return {
        "horizon": key.horizon,
        "scan_run_id": scan_run_id,
        "scanned": scanned,
        "candidates": 0,
        "no_trade": scanned,
        "dataset_snapshot_id": key.dataset_snapshot_id,
        "dataset_key": "universe_24",
        "n_symbols": 2,
        "source": key.source,
        "strategy_version_ids": [2],
    }


def _audit(session: Session, action: str, ts: datetime, payload: dict[str, Any]) -> None:
    session.add(
        AuditLog(
            ts=ts,
            actor="scheduler",
            action=action,
            entity="approved_scope_scan",
            before_json={},
            after_json=payload,
        )
    )


def _scanned(session: Session, day: date, scan_run_id: int, *, scanned: int = 2) -> None:
    _audit(
        session,
        AUDIT_COMPLETED,
        _et(day, 18),
        {"readiness_enforced": True, "runs": [_run(scanned, scan_run_id)], "blocked_universes": []},
    )


def _blocked(session: Session, day: date) -> None:
    _audit(
        session,
        AUDIT_BLOCKED,
        _et(day, 18),
        {
            "reason": "stale feed: massive/bar_daily",
            "dataset_snapshot_id": 3,
            "dataset_key": "universe_24",
            "source": "massive",
            "n_symbols": 2,
            "horizons": ["SHORT_SWING"],
        },
    )


def _nothing_scanned(
    session: Session,
    day: date,
    scan_run_id: int,
    exclusions: dict[str, int] | None = None,
    *,
    in_payload: bool = False,
) -> None:
    exclusions = exclusions or {"stale_or_unavailable_feed": 2}
    session.add(
        ScanRun(
            id=scan_run_id,
            horizon=Horizon.SHORT_SWING,
            started_at=_et(day, 18),
            finished_at=_et(day, 18),
            config_hash="x" * 64,
            universe_size=2,
            scanned_count=0,
            excluded_count=2,
            no_trade_count=0,
            candidate_count=0,
            exclusions_json={k: {"count": n, "symbols": []} for k, n in exclusions.items()},
            data_snapshot_ref="t",
        )
    )
    _audit(
        session,
        AUDIT_NOTHING_SCANNED,
        _et(day, 18),
        {
            "readiness_enforced": True,
            "runs": [{**_run(0, scan_run_id), **({"excluded": exclusions} if in_payload else {})}],
            "blocked_universes": [],
            "reason": "nothing scanned",
        },
    )


def _failed_job(session: Session, day: date) -> None:
    session.add(
        JobRun(
            name="approved_scope_scan",
            started_at=_et(day, 18),
            finished_at=_et(day, 18, 1),
            status="failed",
            detail="RuntimeError('boom')",
        )
    )


@pytest.fixture
def groups(monkeypatch: pytest.MonkeyPatch) -> list[ApprovedScanGroup]:
    current = [GROUP]
    monkeypatch.setattr(mod, "approved_scan_groups", lambda session, cfg=None: (current, []))
    return current


def _incident_history(session: Session) -> None:
    _scanned(session, D_SCANNED, 10)
    # D_MISSED: nothing at all
    _blocked(session, D_BLOCKED)
    _nothing_scanned(session, D_HOLD, 12)
    _scanned(session, D_LATER, 13)
    _failed_job(session, D_FAILED)
    _scanned(session, D_OPEN, 15)
    session.commit()


def _outcome_rows(session: Session) -> list[dict[str, Any]]:
    return [
        r.after_json
        for r in session.scalars(
            select(AuditLog).where(AuditLog.action == SESSION_OUTCOME_ACTION).order_by(AuditLog.id)
        )
    ]


# --------------------------------------------------------------------------- #
def test_attempts_belong_to_the_bar_the_scan_required() -> None:
    # 16:30 ET is after the 16:00 close: a scan then requires TODAY's bar
    assert attempt_session(_et(D_LATER, 16, 30)) == D_LATER
    assert attempt_session(_et(D_LATER, 15, 59)) == D_HOLD
    # Saturday/Sunday belong to Friday
    assert attempt_session(_et(date(2024, 6, 9), 12)) == D_BLOCKED
    assert closed_sessions(NOW, 3) == [D_HOLD, D_LATER, D_FAILED]
    assert closed_sessions(NOW, 0) == []


def test_every_closed_session_gets_exactly_one_explicit_outcome(
    session: Session, groups: list[ApprovedScanGroup]
) -> None:
    _incident_history(session)

    written = record_session_outcomes(session, now=NOW, lookback=10)
    session.commit()
    got = {(o.session_date, o.outcome, o.reason) for o in written}
    assert got == {
        (D_SCANNED, SCANNED, SCANNED),
        (D_MISSED, SKIPPED, REASON_MISSED),
        (D_BLOCKED, SKIPPED, REASON_READINESS),
        (D_HOLD, SKIPPED, REASON_DATA_HOLD),
        (D_LATER, SCANNED, SCANNED),
        (D_FAILED, SKIPPED, REASON_FAILED),
    }
    # sessions before the scope's first attempt are not "missed"; the open
    # session (its bar is still the one to scan) is never closed out early
    assert all(o.session_date >= D_SCANNED for o in written)
    assert D_OPEN not in {o.session_date for o in written}

    rows = {r["session"]: r for r in _outcome_rows(session)}
    assert len(rows) == len(_outcome_rows(session)) == 6
    assert rows[D_HOLD.isoformat()]["detail"].endswith("(stale_or_unavailable_feed=2)")
    assert "stale feed" in rows[D_BLOCKED.isoformat()]["detail"]
    assert "boom" in rows[D_FAILED.isoformat()]["detail"]
    assert rows[D_LATER.isoformat()]["evidence"]["scan_run_ids"] == [13]
    assert all(r["scope"] == "3:SHORT_SWING:massive" for r in rows.values())
    assert all("never scanned after the fact" in r["note"] for r in rows.values())

    # idempotent: a second pass (and a later one) writes nothing new
    assert record_session_outcomes(session, now=NOW, lookback=10) == []
    assert pending_session_outcomes(session, now=NOW + timedelta(hours=3), lookback=10) == []
    assert len(_outcome_rows(session)) == 6


def test_the_open_session_is_shown_but_not_recorded_until_it_closes(
    session: Session, groups: list[ApprovedScanGroup]
) -> None:
    _scanned(session, D_SCANNED, 10)
    session.commit()
    # D_OPEN has no attempt yet: open, not missed
    view = {o.session_date: o for o in session_outcomes(session, now=NOW, n_sessions=10)}
    assert view[D_OPEN].outcome == OPEN and not view[D_OPEN].recorded
    record_session_outcomes(session, now=NOW, lookback=10)
    session.commit()
    assert D_OPEN.isoformat() not in {r["session"] for r in _outcome_rows(session)}

    # once Friday's close has passed, Thursday can no longer be scanned: missed
    friday = _et(date(2024, 6, 14), 18)
    written = record_session_outcomes(session, now=friday, lookback=10)
    assert [(o.session_date, o.reason) for o in written] == [(D_OPEN, REASON_MISSED)]
    # nothing was scanned to produce it — a record, not a backfilled scan
    assert session.scalar(select(ScanRun).where(ScanRun.started_at >= _et(D_OPEN, 0))) is None


def test_a_scope_dropped_and_re_approved_is_only_owed_from_its_current_approval(
    session: Session, groups: list[ApprovedScanGroup]
) -> None:
    other = ScopeKey(11, "MEDIUM_SWING", "massive")
    # our scope scanned on D_SCANNED, then an attempt WITHOUT it (not approved),
    # then it is back from D_LATER on
    _scanned(session, D_SCANNED, 10)
    _audit(
        session,
        AUDIT_COMPLETED,
        _et(D_BLOCKED, 18),
        {"readiness_enforced": True, "runs": [_run(2, 20, other)], "blocked_universes": []},
    )
    _scanned(session, D_LATER, 13)
    session.commit()
    written = {
        o.session_date: o.reason
        for o in record_session_outcomes(session, now=NOW)
        if o.scope == KEY
    }
    # both approved windows are closed out; the stretch between them is not owed
    assert written == {
        D_SCANNED: SCANNED,
        D_MISSED: REASON_MISSED,
        D_LATER: SCANNED,
        D_FAILED: REASON_MISSED,
    }
    view = {
        o.session_date: o
        for o in session_outcomes(session, now=NOW, n_sessions=10)
        if o.scope == KEY
    }
    assert view[D_BLOCKED].outcome == view[D_HOLD].outcome == NOT_IN_SCOPE
    assert "outside this scope's approved window" in view[D_HOLD].detail


def test_a_scope_dropped_before_a_missed_session_closes_is_still_closed_out(
    session: Session, groups: list[ApprovedScanGroup]
) -> None:
    """Review finding: X scanned D_SCANNED, nothing ran D_MISSED, X revoked on
    D_BLOCKED before the close and another scope's EOD scan ran. X's window
    sessions used to stay unrecorded forever (only current groups were
    owed)."""
    other = ScopeKey(11, "MEDIUM_SWING", "massive")
    _scanned(session, D_SCANNED, 10)
    session.commit()
    groups.clear()  # revoked
    _audit(
        session,
        AUDIT_COMPLETED,
        _et(D_BLOCKED, 17, 45),
        {"readiness_enforced": True, "runs": [_run(2, 20, other)], "blocked_universes": []},
    )
    session.commit()
    written = record_session_outcomes(session, now=_et(D_BLOCKED, 18), lookback=10)
    session.commit()
    assert [(o.session_date, o.scope, o.reason) for o in written] == [
        (D_SCANNED, KEY, SCANNED),
        (D_MISSED, KEY, REASON_MISSED),
    ]
    assert all(not o.approved_now for o in written)
    assert "time it was dropped is not on record" in written[1].detail

    # re-approved and scanned on D_LATER: only the new window is owed now
    groups.append(GROUP)
    _scanned(session, D_LATER, 13)
    session.commit()
    written = record_session_outcomes(session, now=NOW, lookback=10)
    session.commit()
    assert [(o.session_date, o.reason) for o in written if o.scope == KEY] == [
        (D_LATER, SCANNED),
        (D_FAILED, REASON_MISSED),
    ]
    # the other scope was listed on D_BLOCKED and dropped by D_LATER's attempt
    assert [(o.session_date, o.reason) for o in written if o.scope == other] == [
        (D_BLOCKED, SCANNED),
        (D_HOLD, REASON_MISSED),
    ]
    rows = sorted(r["session"] for r in _outcome_rows(session) if r["scope"] == KEY.token)
    assert rows == [d.isoformat() for d in (D_SCANNED, D_MISSED, D_LATER, D_FAILED)]
    view = {
        o.session_date: o
        for o in session_outcomes(session, now=NOW, n_sessions=10)
        if o.scope == KEY
    }
    assert view[D_MISSED].recorded and view[D_MISSED].reason == REASON_MISSED
    assert view[D_BLOCKED].outcome == NOT_IN_SCOPE


def test_a_dropped_scope_with_no_attempt_since_is_owed_up_to_now(
    session: Session, groups: list[ApprovedScanGroup]
) -> None:
    # X scanned D_SCANNED, then nothing ran at all and X is no longer approved:
    # the drop time is unknown, so the gap is recorded, never passed over
    _scanned(session, D_SCANNED, 10)
    session.commit()
    groups.clear()
    written = record_session_outcomes(session, now=NOW, lookback=10)
    assert [o.session_date for o in written] == [
        D_SCANNED,
        D_MISSED,
        D_BLOCKED,
        D_HOLD,
        D_LATER,
        D_FAILED,
    ]
    view = {o.session_date: o for o in session_outcomes(session, now=NOW, n_sessions=10)}
    assert view[D_OPEN].outcome == NOT_IN_SCOPE  # no longer approved: not open


def test_nothing_scanned_is_a_data_hold_only_when_data_exclusions_dominate(
    session: Session, groups: list[ApprovedScanGroup]
) -> None:
    _scanned(session, D_SCANNED, 10)
    # stale data excluded most symbols: a data hold
    _nothing_scanned(session, D_MISSED, 11, {"stale_or_unavailable_feed": 2, "liquidity": 1})
    # earnings + liquidity emptied the run (counts carried on the attempt row)
    _nothing_scanned(
        session,
        D_BLOCKED,
        12,
        {"earnings_event_window": 2, "missing_or_short_history": 1},
        in_payload=True,
    )
    # an even split is not "dominated" by data
    _nothing_scanned(session, D_HOLD, 13, {"liquidity": 1, "stale_or_unavailable_feed": 1})
    session.commit()
    got = {o.session_date: o for o in record_session_outcomes(session, now=NOW, lookback=10)}
    assert got[D_MISSED].reason == REASON_DATA_HOLD
    assert got[D_BLOCKED].reason == REASON_ALL_EXCLUDED
    assert "earnings_event_window=2, missing_or_short_history=1" in got[D_BLOCKED].detail
    assert got[D_HOLD].reason == REASON_ALL_EXCLUDED
    assert all(got[d].outcome == SKIPPED for d in (D_MISSED, D_BLOCKED, D_HOLD))


def test_a_readiness_bypassed_manual_scan_is_not_evidence(
    session: Session, groups: list[ApprovedScanGroup]
) -> None:
    _scanned(session, D_SCANNED, 10)
    _audit(
        session,
        AUDIT_COMPLETED,
        _et(D_MISSED, 18),
        {"readiness_enforced": False, "runs": [_run(2, 11)], "blocked_universes": []},
    )
    session.commit()
    view = {o.session_date: o for o in session_outcomes(session, now=NOW, n_sessions=10)}
    assert (view[D_MISSED].outcome, view[D_MISSED].reason) == (SKIPPED, REASON_MISSED)


# --------------------------------------------------------------------------- #
# scheduler integration
# --------------------------------------------------------------------------- #
def test_a_later_session_landing_first_no_longer_hides_an_earlier_gap(db_url: str) -> None:
    """The 11-05 shape: D_MISSED never ran, then D_LATER scanned. The old rule
    (gap measured from the NEWEST completed row) owed nothing before D_LATER."""
    with session_scope(write=True) as session:
        _incident_history(session)
    owed, why = sched.missed_sessions(NOW)
    # only the session with NO attempt is owed for catch-up (bars + skip row);
    # blocked / nothing-scanned / failed sessions had attempts and get their
    # reason from the outcome record instead
    assert owed == [D_MISSED], why
    assert "no approved-scope scan attempt for: 2024-06-06" in why


def test_nothing_is_owed_before_the_first_completed_scan(db_url: str) -> None:
    with session_scope(write=True) as session:
        _scanned(session, D_LATER, 13)
    # sessions before the first completed scan are never owed; the one after is
    owed, _why = sched.missed_sessions(NOW)
    assert owed == [D_FAILED]
    with session_scope(write=True) as session:
        _failed_job(session, D_FAILED)
    owed, why = sched.missed_sessions(NOW)
    assert owed == [] and "had an approved-scope scan attempt" in why


def test_scheduler_records_outcomes_best_effort_and_once(
    db_url: str, groups: list[ApprovedScanGroup], monkeypatch: pytest.MonkeyPatch
) -> None:
    with session_scope(write=True) as session:
        _incident_history(session)
    assert sched.record_scan_session_outcomes(NOW) == 6
    assert sched.record_scan_session_outcomes(NOW) == 0  # read-only no-op path

    def _boom(*_a: object, **_k: object) -> list[object]:
        raise RuntimeError("bookkeeping broke")

    monkeypatch.setattr(mod, "pending_session_outcomes", _boom)
    assert sched.record_scan_session_outcomes(NOW) == 0  # never raises into the job


def test_outcome_recording_survives_a_settings_failure(
    db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    import signalforge.config as config

    def _broken() -> object:
        raise RuntimeError("settings broke")

    monkeypatch.setattr(config, "get_settings", _broken)
    assert sched.record_scan_session_outcomes(NOW) == 0


@freeze_time("2024-06-13T22:00:00Z")
def test_catch_up_records_an_owed_session_after_its_skip_row(
    db_url: str, groups: list[ApprovedScanGroup], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The outcome row of a newly owed missed session is written AFTER its
    ``scan_skipped_missed_session`` row, so it cites that job run."""
    with session_scope(write=True) as session:
        _incident_history(session)

    def _fake_catch_up(session_date: date) -> bool:  # no provider: just the skip row
        sched._record_job_run(
            sched.MISSED_SESSION_SKIP_JOB,
            datetime.now(UTC),
            "skipped",
            f"{sched._session_tag(session_date)}: approved-scope scan NOT run (test)",
        )
        return False

    monkeypatch.setattr(sched, "_catch_up_missed_session", _fake_catch_up)
    monkeypatch.setattr(sched, "catch_up_pending", lambda now=None: (False, "test"))
    sched.job_catch_up()

    with session_scope() as session:
        skip_id = session.scalar(
            select(JobRun.id).where(JobRun.name == sched.MISSED_SESSION_SKIP_JOB)
        )
        rows = {r["session"]: r for r in _outcome_rows(session)}
    assert skip_id is not None
    assert rows[D_MISSED.isoformat()]["reason"] == REASON_MISSED
    assert rows[D_MISSED.isoformat()]["evidence"]["missed_session_skip_job_run_id"] == skip_id
    assert f"job_run #{skip_id}" in rows[D_MISSED.isoformat()]["detail"]
    assert len(rows) == 6


def test_job_names_match_the_scheduler() -> None:
    assert sched.MISSED_SESSION_SKIP_JOB == mod.MISSED_SKIP_JOB
    assert set(mod.SCAN_JOBS) <= set(sched.EOD_EVIDENCE_JOBS)
    assert sched.MISSED_SESSION_INGEST_JOB in mod.CONTEXT_JOBS
    assert sched.MISSED_SESSIONS_JOB in mod.CONTEXT_JOBS


@freeze_time("2024-06-13T22:00:00Z")
def test_cli_lists_per_session_outcomes_read_only(
    db_url: str, groups: list[ApprovedScanGroup]
) -> None:
    from signalforge.cli import app

    with session_scope(write=True) as session:
        _incident_history(session)
    result = CliRunner().invoke(app, ["approved-scope-sessions", "-n", "10"])
    assert result.exit_code == 0, result.output
    out = result.output
    assert "SHORT_SWING on snapshot 3" in out
    assert "2024-06-06  SKIPPED      missed" in out
    assert "2024-06-07  SKIPPED      readiness_blocked" in out
    assert "2024-06-10  SKIPPED      data_hold" in out
    assert "2024-06-12  SKIPPED      scan_failed" in out
    assert "2024-06-11  SCANNED" in out and "2024-06-13  SCANNED" in out
    assert "UNRECORDED" in out
    with session_scope() as session:
        assert _outcome_rows(session) == []  # the CLI never writes

    gaps = CliRunner().invoke(app, ["approved-scope-sessions", "-n", "10", "--gaps-only"])
    assert gaps.exit_code == 0 and "2024-06-11" not in gaps.output
    assert "2024-06-06" in gaps.output
