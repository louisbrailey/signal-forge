"""Alert policy: OFF by default, caps, quiet hours, dedupe, kill-switch, mandatory lines."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from signalforge import RESEARCH_ONLY_NOTICE
from signalforge.alerts.dispatch import plan_alerts, run_alert_cycle
from signalforge.alerts.render import render_candidate_alert
from signalforge.data.adapters.fixture import FixtureMarketDataAdapter
from signalforge.data.ingest import ingest_universe
from signalforge.db.models import AlertLog, DataFeedStatus, PaperAccount
from signalforge.db.types import utcnow
from signalforge.domain import AlertStatus, AlertType
from signalforge.killswitch import KillSwitchEngaged, get_kill_switch
from signalforge.settings_store import set_setting

NOON = datetime(2024, 6, 30, 16, 0, tzinfo=UTC)  # 16:00 UTC ~ daytime in most zones


def _seed_feed_and_briefing(session: Session) -> None:
    session.add(PaperAccount(name="default", initial_cash=10_000, cash=10_000))
    ingest_universe(
        session, FixtureMarketDataAdapter(), ["SPY"], date(2024, 1, 1), date(2024, 6, 30)
    )
    session.flush()
    set_setting(
        session, "last_briefing", {"as_of": "2024-06-30", "text": "brief", "narrative": None}
    )


def test_nothing_is_sent_until_alerts_enabled(session: Session) -> None:
    _seed_feed_and_briefing(session)
    r = run_alert_cycle(session, now=NOON)
    assert r.enabled is False
    assert r.sent == 0
    assert (
        session.scalar(func.count(AlertLog.id).select()) == 0
        or session.scalar(select(func.count()).select_from(AlertLog)) == 0
    )


def test_briefing_alert_is_sent_once_then_deduped(session: Session) -> None:
    _seed_feed_and_briefing(session)
    set_setting(session, "alerts_enabled", True)

    r1 = run_alert_cycle(session, now=NOON)
    assert r1.sent >= 1
    sent = session.scalar(
        select(func.count())
        .select_from(AlertLog)
        .where(AlertLog.alert_type == AlertType.DAILY_BRIEFING, AlertLog.status == AlertStatus.SENT)
    )
    assert sent == 1

    r2 = run_alert_cycle(session, now=NOON + timedelta(minutes=5))
    assert r2.sent == 0  # deduped by key


def test_stale_feed_yields_only_a_data_issue_alert(session: Session) -> None:
    _seed_feed_and_briefing(session)
    for row in session.scalars(select(DataFeedStatus)):
        row.last_success_at = utcnow() - timedelta(days=30)
    session.flush()

    planned = plan_alerts(session, NOON)
    kinds = {p.alert_type for p in planned}
    assert kinds == {AlertType.DATA_ISSUE}
    assert all(p.overnight_ok for p in planned)


def test_recent_ingestion_failure_yields_a_data_issue_alert(session: Session) -> None:
    """A failed/partial ingestion run in the last 24h is a data issue, distinct
    from (and detected independently of) a stale feed."""
    from signalforge.db.models import IngestionRun
    from signalforge.domain import FeedType

    _seed_feed_and_briefing(session)
    session.add(
        IngestionRun(
            provider="massive",
            feed_type=FeedType.BAR_DAILY,
            kind="incremental",
            requested_start=date(2024, 6, 1),
            requested_end=date(2024, 6, 30),
            status="failed",
            started_at=utcnow() - timedelta(hours=2),
        )
    )
    session.flush()

    planned = plan_alerts(session, NOON)
    kinds = {p.alert_type for p in planned}
    assert AlertType.DATA_ISSUE in kinds
    data_issue = next(p for p in planned if p.alert_type is AlertType.DATA_ISSUE)
    assert "massive" in data_issue.body and "failed" in data_issue.body
    assert data_issue.overnight_ok is True
    # briefing/candidate alerts are untouched (no stale feed, just an ingestion failure)
    assert AlertType.DAILY_BRIEFING in kinds


def test_recent_job_failure_yields_a_system_health_alert(session: Session) -> None:
    from signalforge.db.models import AuditLog

    _seed_feed_and_briefing(session)
    session.add(
        AuditLog(
            ts=utcnow() - timedelta(hours=1),
            actor="scheduler",
            action="job.failed",
            entity="daily_eod_update",
            before_json={},
            after_json={"error": "AdapterError: network request failed"},
        )
    )
    session.flush()

    planned = plan_alerts(session, NOON)
    kinds = {p.alert_type for p in planned}
    assert AlertType.SYSTEM_HEALTH in kinds
    sys_health = next(p for p in planned if p.alert_type is AlertType.SYSTEM_HEALTH)
    assert "daily_eod_update" in sys_health.body
    assert sys_health.overnight_ok is True
    assert AlertType.DAILY_BRIEFING in kinds  # a job failure alone doesn't block the briefing


def test_every_alert_carries_the_research_only_notice(session: Session) -> None:
    from signalforge.db.models import AuditLog

    _seed_feed_and_briefing(session)
    session.add(
        AuditLog(
            ts=utcnow() - timedelta(hours=1),
            actor="scheduler",
            action="job.failed",
            entity="x",
            before_json={},
            after_json={"error": "boom"},
        )
    )
    session.flush()
    for row in session.scalars(select(DataFeedStatus)):
        row.last_success_at = utcnow() - timedelta(days=30)
    session.flush()

    for p in plan_alerts(session, NOON):
        assert RESEARCH_ONLY_NOTICE in p.body


def test_quiet_hours_suppress_briefing_but_not_health(session: Session) -> None:
    _seed_feed_and_briefing(session)
    set_setting(session, "alerts_enabled", True)
    set_setting(session, "quiet_hours", {"start": 0, "end": 23})  # basically always quiet

    r = run_alert_cycle(session, now=datetime(2024, 6, 30, 3, 0, tzinfo=UTC))
    assert r.sent == 0
    assert any("quiet hours" in s for s in r.suppressed)


@pytest.mark.safety
def test_kill_switch_blocks_the_alert_cycle(session: Session, isolated_data_dir) -> None:
    _seed_feed_and_briefing(session)
    set_setting(session, "alerts_enabled", True)
    get_kill_switch().engage(reason="halt", actor="pytest")
    with pytest.raises(KillSwitchEngaged):
        run_alert_cycle(session, now=NOON)


def test_candidate_alert_body_has_every_mandatory_field() -> None:
    c = {
        "id": 7,
        "symbol": "AAPL",
        "sector": "Tech",
        "horizon": "SHORT_SWING",
        "strategy": "trend_continuation.short_swing",
        "strategy_version": "0.1.0",
        "direction": "LONG",
        "entry_low": 99.0,
        "entry_high": 101.0,
        "stop": 95.0,
        "target": 110.0,
        "reward_risk": 2.5,
        "risk_dollars": 50.0,
        "risk_pct": 0.5,
        "reference_price": 100.0,
        "as_of": "2024-06-30T00:00:00+00:00",
        "event_risk": {"upcoming_earnings": ["2024-07-25"]},
        "data_freshness": {"fresh": True, "reasons": []},
        "reasons_qualify": ["trend + volume"],
        "reasons_fail": ["whipsaw"],
    }
    subject, body = render_candidate_alert(c)
    assert "AAPL" in subject and "SHORT_SWING" in subject
    for needle in [
        "Instrument:",
        "Horizon:",
        "Strategy:",
        "Reference price:",
        "Data freshness:",
        "Entry zone:",
        "Invalidation:",
        "Reward : risk:",
        "Event risk:",
        "Why it qualified:",
        "Why it could fail:",
        "/candidates/7",
        RESEARCH_ONLY_NOTICE,
    ]:
        assert needle in body, needle
