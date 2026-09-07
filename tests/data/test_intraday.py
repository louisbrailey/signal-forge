"""Phase 2 — intraday bars: calendar sessions, fixture adapter, ingest, series."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from signalforge.data.adapters.base import FeedType
from signalforge.data.adapters.fixture import FixtureMarketDataAdapter
from signalforge.data.calendar import is_rth, rth_bounds_utc, session_of
from signalforge.data.feeds import feed_status_report
from signalforge.data.ingest import ingest_intraday_universe
from signalforge.data.series import PriceSeries
from signalforge.db.models import DataFeedStatus, OHLCVIntraday
from signalforge.domain import LatencyCategory

# 2024-06-25 is a Tuesday NYSE session; 09:30 ET == 13:30 UTC (EDT).
_OPEN = datetime(2024, 6, 25, 13, 30, tzinfo=UTC)


def test_calendar_classifies_intraday_timestamps() -> None:
    assert session_of(_OPEN) == "rth"
    assert is_rth(_OPEN)
    assert session_of(_OPEN - timedelta(hours=2)) == "pre"
    assert session_of(_OPEN + timedelta(hours=7)) == "post"  # after 16:00 ET
    assert session_of(datetime(2024, 6, 22, 15, 0, tzinfo=UTC)) == "closed"  # Saturday
    b = rth_bounds_utc(_OPEN.date())
    assert b is not None and b[0] == _OPEN


def test_fixture_intraday_is_deterministic_rth_only_and_simulated() -> None:
    a = FixtureMarketDataAdapter()
    start, end = _OPEN - timedelta(days=1), _OPEN + timedelta(days=1, hours=7)
    first = a.fetch_intraday_bars("SPY", start, end, bar_size="30m")
    second = a.fetch_intraday_bars("SPY", start, end, bar_size="30m")
    assert first and [b.close for b in first] == [b.close for b in second]
    assert all(b.session == "rth" and is_rth(b.bar_start) for b in first)
    assert all(b.provenance.is_simulated and not b.provenance.latency_category.is_live for b in first)


def test_fixture_intraday_validates_inputs() -> None:
    a = FixtureMarketDataAdapter()
    with pytest.raises(ValueError, match="bar_size"):
        a.fetch_intraday_bars("SPY", _OPEN, _OPEN + timedelta(hours=1), bar_size="7m")
    with pytest.raises(ValueError, match="aware"):
        a.fetch_intraday_bars("SPY", _OPEN.replace(tzinfo=None), _OPEN, bar_size="5m")


def test_ingest_intraday_persists_dedupes_and_records_feed_status(session: Session) -> None:
    end = _OPEN + timedelta(days=2)
    start = _OPEN - timedelta(days=1)
    r = ingest_intraday_universe(
        session, FixtureMarketDataAdapter(), ["SPY", "AAPL"], start, end, bar_size="15m"
    )
    session.commit()
    assert r.bars_written > 50

    rows = list(session.scalars(select(OHLCVIntraday)))
    assert all(b.source == "fixture" and b.is_simulated for b in rows)
    assert all(b.latency_category is LatencyCategory.HISTORICAL for b in rows)
    assert all(b.bar_size == "15m" for b in rows)

    again = ingest_intraday_universe(
        session, FixtureMarketDataAdapter(), ["SPY", "AAPL"], start, end, bar_size="15m"
    )
    assert again.bars_written == 0

    feed = feed_status_report(session)
    intraday = [f for f in feed["feeds"] if f["feed_type"] == FeedType.BAR_INTRADAY.value]
    assert intraday and intraday[0]["is_live"] is False and intraday[0]["is_simulated"] is True
    assert session.scalar(
        select(DataFeedStatus.last_success_at).where(
            DataFeedStatus.feed_type == FeedType.BAR_INTRADAY
        )
    ) is not None


def test_price_series_load_intraday(session: Session) -> None:
    end = _OPEN + timedelta(days=2)
    start = _OPEN - timedelta(days=1)
    ingest_intraday_universe(
        session, FixtureMarketDataAdapter(), ["SPY"], start, end, bar_size="1h"
    )
    session.flush()
    ser = PriceSeries.load_intraday(session, "SPY", start, end, bar_size="1h")
    assert len(ser) >= 10
    assert isinstance(ser.dates[0], datetime) and ser.dates[0].tzinfo is not None
    assert list(ser.dates) == sorted(ser.dates)
