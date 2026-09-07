"""Ingestion: normalized rows, raw-payload cache, feed status, dedupe."""

from __future__ import annotations

from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from signalforge.data.adapters.base import AdapterError, FeedType
from signalforge.data.adapters.fixture import FixtureMarketDataAdapter
from signalforge.data.feeds import feed_status_report
from signalforge.data.ingest import ingest_symbol, ingest_universe, record_feed_failure
from signalforge.db.models import DataFeedStatus, OHLCVDaily, RawPayloadCache
from signalforge.domain import LatencyCategory

START, END = date(2023, 1, 1), date(2023, 6, 30)


def test_ingest_writes_normalized_bars_with_provenance(session: Session) -> None:
    report = ingest_universe(session, FixtureMarketDataAdapter(), ["AAPL", "SPY"], START, END)
    session.commit()
    assert report.bars_written > 100
    assert report.errors == []

    bars = list(session.scalars(select(OHLCVDaily)))
    assert bars
    for b in bars:
        assert b.source == "fixture"
        assert b.is_simulated is True
        assert b.latency_category is LatencyCategory.HISTORICAL
        assert b.ingested_at.tzinfo is not None
        assert b.quality_flags == []


def test_raw_payload_is_cached_for_audit(session: Session) -> None:
    ingest_symbol(session, FixtureMarketDataAdapter(), "AAPL", START, END)
    session.commit()
    raw = list(session.scalars(select(RawPayloadCache)))
    assert raw and raw[0].provider == "fixture"
    assert "SIMULATED" in raw[0].payload


def test_reingest_is_idempotent(session: Session) -> None:
    ingest_symbol(session, FixtureMarketDataAdapter(), "AAPL", START, END)
    session.commit()
    first = int(session.scalar(select(func.count()).select_from(OHLCVDaily)) or 0)

    result = ingest_symbol(session, FixtureMarketDataAdapter(), "AAPL", START, END)
    session.commit()
    second = int(session.scalar(select(func.count()).select_from(OHLCVDaily)) or 0)
    assert second == first
    assert result.bars_written == 0
    assert result.bars_skipped == first


def test_feed_status_records_success(session: Session) -> None:
    ingest_symbol(session, FixtureMarketDataAdapter(), "AAPL", START, END)
    session.commit()
    row = session.scalar(
        select(DataFeedStatus).where(
            DataFeedStatus.provider == "fixture",
            DataFeedStatus.feed_type == FeedType.BAR_DAILY,
        )
    )
    assert row is not None
    assert row.last_success_at is not None
    assert row.consecutive_failures == 0
    assert row.latency_category is LatencyCategory.HISTORICAL


def test_adapter_error_is_recorded_as_feed_failure(session: Session) -> None:
    class _Broken(FixtureMarketDataAdapter):
        def fetch_daily_bars(self, *a: object, **k: object):  # type: ignore[override]
            raise AdapterError("provider unreachable")

    result = ingest_symbol(session, _Broken(), "AAPL", START, END)
    session.commit()
    assert result.error == "provider unreachable"

    report = feed_status_report()
    feeds = {(f["provider"], f["feed_type"]): f for f in report["feeds"]}
    bar_feed = feeds[("fixture", "BAR_DAILY")]
    assert bar_feed["consecutive_failures"] == 1
    assert bar_feed["is_stale"] is True  # never succeeded
    assert bar_feed["is_live"] is False


def test_rate_limited_failure_sets_backoff(session: Session) -> None:
    record_feed_failure(
        session, "stooq", FeedType.BAR_DAILY, "HTTP 429", rate_limited=True
    )
    session.commit()
    row = session.scalar(
        select(DataFeedStatus).where(DataFeedStatus.provider == "stooq")
    )
    assert row is not None and row.rate_limited_until is not None
