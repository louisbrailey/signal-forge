"""Freshness gate — S8: a stale/rate-limited required feed fails the gate."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from signalforge.data.adapters.base import FeedType
from signalforge.data.adapters.fixture import FixtureMarketDataAdapter
from signalforge.data.freshness import check_feeds_fresh, gate_for_horizon
from signalforge.data.ingest import ingest_symbol, record_feed_failure
from signalforge.db.models import DataFeedStatus
from signalforge.db.types import utcnow
from signalforge.domain import Horizon

pytestmark = pytest.mark.safety

REQUIRED = [("fixture", FeedType.BAR_DAILY)]


def _age_last_success(session: Session, provider: str, delta: timedelta) -> None:
    row = session.scalar(select(DataFeedStatus).where(DataFeedStatus.provider == provider))
    assert row is not None
    row.last_success_at = utcnow() - delta
    session.flush()


def _ingest(session: Session) -> None:
    ingest_symbol(
        session, FixtureMarketDataAdapter(), "AAPL", date(2023, 1, 1), date(2023, 6, 30)
    )
    session.flush()


def test_fresh_feed_passes(session: Session) -> None:
    _ingest(session)
    result = check_feeds_fresh(session, REQUIRED, timedelta(hours=48))
    assert result.fresh is True
    assert result.reasons == []


def test_missing_feed_fails(session: Session) -> None:
    result = check_feeds_fresh(session, REQUIRED, timedelta(hours=48))
    assert result.fresh is False
    assert "no successful fetch" in result.reasons[0]


def test_stale_feed_fails_the_gate(session: Session) -> None:
    _ingest(session)
    _age_last_success(session, "fixture", timedelta(days=5))
    result = check_feeds_fresh(session, REQUIRED, timedelta(hours=48))
    assert result.fresh is False
    assert "stale" in result.reasons[0]


def test_rate_limited_feed_fails_the_gate(session: Session) -> None:
    _ingest(session)
    record_feed_failure(
        session, "fixture", FeedType.BAR_DAILY, "429", rate_limited=True
    )
    session.flush()
    result = check_feeds_fresh(session, REQUIRED, timedelta(days=999))
    assert result.fresh is False
    assert "rate-limited" in result.reasons[0]


def test_gate_for_horizon_uses_config_budget(session: Session) -> None:
    _ingest(session)
    # SHORT_SWING budget is 1 day; a 2-day-old success should fail.
    _age_last_success(session, "fixture", timedelta(days=2))
    result = gate_for_horizon(session, Horizon.SHORT_SWING, REQUIRED)
    assert result.fresh is False
