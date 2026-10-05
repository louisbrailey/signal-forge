"""The paper time stop counts XNYS SESSIONS, like the backtested N-bar rule.

``time_stop_days=10`` is the 10th trading session after the entry date — not
entry + 10 calendar days (about seven sessions). Weekends and exchange
holidays do not count. Existing open positions are moved to the session rule by
an explicit, logged, idempotent migration that runs on the next mark.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from signalforge.db.models import AuditLog, Candidate, OHLCVDaily, PaperPosition, PaperTrade
from signalforge.domain import LatencyCategory
from signalforge.paper.ledger import (
    TIME_STOP_MIGRATION_ACTION,
    _time_stop_date,
    accept_candidate,
    mark_to_market,
    migrate_time_stops_to_sessions,
)


def _d(dt: datetime) -> date:
    return dt.date()


def test_ten_bars_skips_weekends() -> None:
    # Entry Mon 2024-03-04. Sessions after it: Mar 5,6,7,8 (4), 11-15 (9), 18 (10).
    assert _d(_time_stop_date(date(2024, 3, 4), 10)) == date(2024, 3, 18)
    # The old calendar rule gave 2024-03-14 — only the 8th session.
    assert date(2024, 3, 4) + timedelta(days=10) == date(2024, 3, 14)


def test_holidays_do_not_count() -> None:
    # Entry Fri 2024-01-05. MLK Day (Mon 2024-01-15) is not a session:
    # Jan 8,9,10,11,12 (5), 16,17,18,19 (9), 22 (10).
    assert _d(_time_stop_date(date(2024, 1, 5), 10)) == date(2024, 1, 22)
    # Entry Wed 2024-07-03, one bar: Jul 4 is a holiday -> Fri Jul 5.
    assert _d(_time_stop_date(date(2024, 7, 3), 1)) == date(2024, 7, 5)
    # Entry Tue 2024-12-24: Dec 25 closed -> 1st session Thu Dec 26; 2nd Fri Dec 27;
    # 3rd Mon Dec 30; 4th Tue Dec 31; Jan 1 closed -> 5th Thu Jan 2 2025.
    assert _d(_time_stop_date(date(2024, 12, 24), 5)) == date(2025, 1, 2)


def test_weekend_entry_counts_from_the_next_session() -> None:
    # A Saturday acceptance (weekend re-scan): the first bar is Monday.
    assert _d(_time_stop_date(date(2024, 3, 9), 1)) == date(2024, 3, 11)
    assert _d(_time_stop_date(date(2024, 3, 9), 5)) == date(2024, 3, 15)


def test_forty_bars_medium_swing() -> None:
    # Entry Thu 2026-10-01, 40 sessions. Oct 2 (1); Oct 5-30 = 20 sessions (21);
    # Nov 2-25 = 18 sessions (39; Thanksgiving Thu Nov 26 closed); Fri Nov 27 (40).
    assert _d(_time_stop_date(date(2026, 10, 1), 40)) == date(2026, 11, 27)
    # The calendar rule would have exited on 2026-11-10, thirteen sessions early.
    assert date(2026, 10, 1) + timedelta(days=40) == date(2026, 11, 10)


def test_zero_or_negative_bars_is_refused() -> None:
    with pytest.raises(ValueError, match="at least one session"):
        _time_stop_date(date(2024, 3, 4), 0)


def test_new_position_gets_a_session_time_stop(
    session: Session, passing_candidate: Candidate, account
) -> None:
    res = accept_candidate(session, passing_candidate.id, as_of=date(2024, 1, 5))
    pos = session.get(PaperPosition, res.position_id)
    assert pos is not None and pos.time_stop_date is not None
    assert pos.time_stop_date.date() == date(2024, 1, 22)  # 10 sessions, MLK skipped


def _flat_bars(session: Session, instrument_id: int, start: date, end: date) -> None:
    d = start
    while d <= end:
        session.add(
            OHLCVDaily(
                instrument_id=instrument_id,
                session_date=d,
                open=100.0,
                high=100.5,
                low=99.5,
                close=100.0,
                volume=1_000_000,
                adj_close=100.0,
                source="fixture_ts",
                latency_category=LatencyCategory.HISTORICAL,
                is_simulated=True,
                is_adjusted=True,
                ingested_at=datetime(2024, 4, 1, tzinfo=UTC),
                quality_flags=[],
            )
        )
        d += timedelta(days=1)
    session.flush()


def test_position_exits_on_the_tenth_session_not_the_tenth_calendar_day(
    session: Session, passing_candidate: Candidate, account
) -> None:
    passing_candidate.invalidation_level = 90.0  # never hit by the flat bars
    passing_candidate.target_level = 130.0
    session.flush()
    _flat_bars(session, passing_candidate.instrument_id, date(2024, 3, 1), date(2024, 3, 25))
    from signalforge.db.models import ScanRun

    run = session.get(ScanRun, passing_candidate.scan_run_id)
    assert run is not None
    run.source = "fixture_ts"
    session.flush()

    res = accept_candidate(session, passing_candidate.id, as_of=date(2024, 3, 4))
    # Day 10 on the calendar (Thu Mar 14, the 8th session): still open.
    assert mark_to_market(session, as_of=date(2024, 3, 14)).closed == 0
    # The 9th session (Fri Mar 15): still open.
    assert mark_to_market(session, as_of=date(2024, 3, 15)).closed == 0
    # The 10th session (Mon Mar 18): time stop.
    assert mark_to_market(session, as_of=date(2024, 3, 18)).closed == 1
    pos = session.get(PaperPosition, res.position_id)
    assert pos is not None and pos.closed_at is not None
    assert pos.closed_at.date() == date(2024, 3, 18)
    audit = session.scalar(select(AuditLog).where(AuditLog.action == "paper.position_closed"))
    assert audit is not None and audit.after_json["exit_reason"] == "time_stop"


def test_legacy_calendar_time_stop_is_migrated_explicitly_logged_and_idempotent(
    session: Session, passing_candidate: Candidate, account
) -> None:
    res = accept_candidate(session, passing_candidate.id, as_of=date(2024, 3, 4))
    pos = session.get(PaperPosition, res.position_id)
    assert pos is not None
    # Reproduce a position opened by the old rule: entry + 10 calendar days.
    legacy = datetime(2024, 3, 14, tzinfo=UTC)
    pos.time_stop_date = legacy
    session.flush()
    snapshot = dict(session.get(PaperTrade, res.paper_trade_id).plan_json)  # type: ignore[union-attr]

    changes = migrate_time_stops_to_sessions(session)
    assert changes == [
        {
            "position_id": pos.id,
            "paper_trade_id": res.paper_trade_id,
            "time_stop_bars": 10,
            "before": legacy.isoformat(),
            "after": datetime(2024, 3, 18, tzinfo=UTC).isoformat(),
        }
    ]
    session.refresh(pos)
    assert pos.time_stop_date == datetime(2024, 3, 18, tzinfo=UTC)
    audits = list(
        session.scalars(select(AuditLog).where(AuditLog.action == TIME_STOP_MIGRATION_ACTION))
    )
    assert len(audits) == 1
    assert audits[0].entity == f"paper_position:{pos.id}"
    assert audits[0].before_json == {"time_stop_date": legacy.isoformat()}
    assert audits[0].after_json["time_stop_bars"] == 10

    # Idempotent: a second run — and the mark that calls it — changes nothing more.
    assert migrate_time_stops_to_sessions(session) == []
    mark_to_market(session, as_of=date(2024, 3, 5))
    assert (
        len(
            list(
                session.scalars(
                    select(AuditLog).where(AuditLog.action == TIME_STOP_MIGRATION_ACTION)
                )
            )
        )
        == 1
    )
    # The immutable trade evidence is untouched.
    assert session.get(PaperTrade, res.paper_trade_id).plan_json == snapshot  # type: ignore[union-attr]


def test_the_next_mark_runs_the_migration(
    session: Session, passing_candidate: Candidate, account
) -> None:
    res = accept_candidate(session, passing_candidate.id, as_of=date(2024, 3, 4))
    pos = session.get(PaperPosition, res.position_id)
    assert pos is not None
    pos.time_stop_date = datetime(2024, 3, 14, tzinfo=UTC)
    session.flush()
    mark_to_market(session, as_of=date(2024, 3, 5))
    session.refresh(pos)
    assert pos.time_stop_date == datetime(2024, 3, 18, tzinfo=UTC)
    assert session.scalar(select(AuditLog).where(AuditLog.action == TIME_STOP_MIGRATION_ACTION))
