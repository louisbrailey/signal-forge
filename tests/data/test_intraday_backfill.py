"""Intraday backfill: request plan, calendar chunking, resume, RTH purity.

No network anywhere: the Massive adapter is driven through an injected
``httpx.MockTransport`` and the ingest path through the deterministic fixture
adapter.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from signalforge.data.adapters.base import AdapterError, FeedType, IntradayBarAdapter
from signalforge.data.adapters.fixture import FixtureMarketDataAdapter
from signalforge.data.adapters.massive import MassiveAdapter
from signalforge.data.calendar import sessions as calendar_sessions
from signalforge.data.ingest import (
    PROVIDER_ROW_CAP,
    ingest_intraday_history,
    ingest_intraday_symbol,
    intraday_request_plan,
)
from signalforge.data.intraday_coverage import intraday_rth_coverage
from signalforge.data.series import PriceSeries
from signalforge.db.models import DataFeedStatus, IngestionRun, OHLCVIntraday
from signalforge.domain import LatencyCategory

# 2024-06-25 is a Tuesday NYSE session; 13:30 UTC == 09:30 ET.
_OPEN = datetime(2024, 6, 25, 13, 30, tzinfo=UTC)


# --------------------------------------------------------------------------- #
# the request plan: the API budget is stated before anything is fetched
# --------------------------------------------------------------------------- #
def test_plan_costs_the_designs_own_backfill() -> None:
    """The backfill actually needed for ORB, recomputed from the provider's
    real limit: the 50,000 cap counts ONE-MINUTE base aggregates (incident
    2026-10-26, ingestion_run 71), so a request may span ~52 sessions."""
    plan = intraday_request_plan(
        [f"SYM{i}" for i in range(24)],
        date(2016, 9, 1),
        date(2026, 10, 26),
        bar_size="15m",
        request_spacing_s=12.1,
    )
    assert plan.n_requests == 24 * 61 == 1464  # Sep-Oct 2016 .. Sep-Oct 2026
    assert 290.0 < plan.minutes < 300.0
    assert plan.max_rows_per_request <= PROVIDER_ROW_CAP
    assert 1_500_000 < plan.rth_rows < 1_600_000
    assert "1464 paced provider requests in 2-month chunks" in plan.summary()


def test_cap_is_checked_in_base_minutes_whatever_the_bar_size() -> None:
    """A year of 15m bars is only ~16k rows, but ~240k one-minute bases: the
    provider paginates it. The plan must refuse such a chunk for EVERY bar size."""
    for bar_size in ("5m", "15m", "1h"):
        with pytest.raises(ValueError, match="one-minute base aggregates"):
            intraday_request_plan(
                ["AAPL"], date(2017, 1, 1), date(2017, 12, 31), bar_size=bar_size, chunk_months=12
            )
        ok = intraday_request_plan(
            ["AAPL"], date(2017, 1, 1), date(2017, 12, 31), bar_size=bar_size
        )
        assert ok.max_rows_per_request <= PROVIDER_ROW_CAP
        assert ok.n_requests == 6


def test_plan_chunks_on_fixed_calendar_month_boundaries() -> None:
    plan = intraday_request_plan(["AAPL"], date(2023, 6, 15), date(2023, 12, 2), bar_size="15m")
    spans = [(c.start.isoformat(), c.end.isoformat()) for c in plan.chunks]
    assert spans == [
        ("2023-06-15", "2023-06-30"),  # aligned to the May-Jun block
        ("2023-07-01", "2023-08-31"),
        ("2023-09-01", "2023-10-31"),
        ("2023-11-01", "2023-12-02"),
    ]
    with pytest.raises(ValueError, match="must divide 12"):
        intraday_request_plan(["AAPL"], date(2023, 1, 1), date(2023, 3, 1), chunk_months=5)


# --------------------------------------------------------------------------- #
# the history run: IngestionRun, resume, gaps
# --------------------------------------------------------------------------- #
def test_history_records_an_ingestion_run_and_is_resumable(session: Session) -> None:
    start, end = date(2024, 6, 3), date(2024, 6, 28)
    run = ingest_intraday_history(
        session,
        FixtureMarketDataAdapter(),
        ["SPY", "AAPL"],
        start,
        end,
        bar_size="15m",
    )
    assert run.feed_type is FeedType.BAR_INTRADAY
    assert run.kind == "full_history"
    assert run.status == "ok"
    assert sorted(run.symbols_ok) == ["AAPL", "SPY"]
    assert run.symbols_failed == {}
    assert run.bars_written > 0
    assert run.requested_start == start and run.requested_end == end
    assert run.coverage_first is not None and run.coverage_last is not None
    assert "264" not in run.notes and "paced provider requests" in run.notes

    # re-entering the SAME run fetches nothing: every symbol is already ok
    before = run.bars_written
    again = ingest_intraday_history(
        session,
        FixtureMarketDataAdapter(),
        ["SPY", "AAPL"],
        start,
        end,
        bar_size="15m",
        resume_run_id=run.id,
    )
    assert again.id == run.id
    assert again.bars_written == before  # no double-counting, no re-fetch

    # a fresh run over the same span writes nothing new either (idempotent)
    third = ingest_intraday_history(
        session, FixtureMarketDataAdapter(), ["SPY"], start, end, bar_size="15m"
    )
    assert third.bars_written == 0
    assert third.bars_skipped > 0

    assert session.scalar(select(IngestionRun.id).where(IngestionRun.id == run.id)) == run.id


def test_history_releases_writer_during_fetch_and_resumes_committed_chunk(session: Session) -> None:
    import sqlite3

    class InterruptedAdapter(FixtureMarketDataAdapter):
        calls = 0

        def fetch_intraday_bars(self, symbol, start, end, *, bar_size="5m"):
            self.calls += 1
            # A separate connection must be able to write while the provider
            # request is in flight. A write-intent transaction here would fail.
            db_path = session.get_bind().url.database
            with sqlite3.connect(db_path, timeout=0.1) as conn:
                conn.execute("CREATE TABLE IF NOT EXISTS heartbeat_probe (n INTEGER)")
                conn.execute("INSERT INTO heartbeat_probe VALUES (1)")
            if self.calls == 2:
                raise KeyboardInterrupt()
            return super().fetch_intraday_bars(symbol, start, end, bar_size=bar_size)

    start, end = date(2024, 6, 3), date(2024, 7, 12)
    adapter = InterruptedAdapter()
    with pytest.raises(KeyboardInterrupt):
        ingest_intraday_history(session, adapter, ["SPY"], start, end, bar_size="15m")
    run = session.scalar(select(IngestionRun).order_by(IngestionRun.id.desc()))
    assert run is not None and run.status == "running"
    first_count = run.bars_written
    assert first_count > 0 and run.symbols_ok == []
    session.commit()
    resumed = ingest_intraday_history(
        session,
        FixtureMarketDataAdapter(),
        ["SPY"],
        start,
        end,
        bar_size="15m",
        resume_run_id=run.id,
    )
    assert resumed.status == "ok" and resumed.bars_written > first_count
    assert len(session.scalars(select(OHLCVIntraday)).all()) == resumed.bars_written


def test_history_reports_gaps_for_a_symbol_with_no_data(session: Session) -> None:
    class _NoBars:
        provider_name = "fixture"

        @property
        def capabilities(self):  # pragma: no cover - trivial
            return FixtureMarketDataAdapter().capabilities

        def fetch_intraday_bars(self, symbol, start, end, *, bar_size="5m"):
            if symbol == "AAPL":
                raise AdapterError("provider says no")
            return FixtureMarketDataAdapter().fetch_intraday_bars(
                symbol, start, end, bar_size=bar_size
            )

    assert isinstance(_NoBars(), IntradayBarAdapter)
    run = ingest_intraday_history(
        session, _NoBars(), ["SPY", "AAPL"], date(2024, 6, 3), date(2024, 6, 14), bar_size="15m"
    )
    assert run.status == "partial"
    assert run.symbols_ok == ["SPY"]
    assert "AAPL" in run.symbols_failed
    assert run.gaps_json.get("AAPL")
    assert "SPY" not in run.gaps_json


def test_backfill_does_not_register_a_feed_status_row(session: Session) -> None:
    """A one-off backfill is not a live feed. alerts.dispatch blocks every
    candidate and briefing alert while ANY feed row is stale, so registering
    BAR_INTRADAY here would quietly switch the live EOD probation's alerts off
    36 hours later."""
    ingest_intraday_history(
        session, FixtureMarketDataAdapter(), ["SPY"], date(2024, 6, 3), date(2024, 6, 14)
    )
    assert (
        session.scalar(
            select(DataFeedStatus).where(DataFeedStatus.feed_type == FeedType.BAR_INTRADAY)
        )
        is None
    )

    # the recurring path still registers one when it is asked to
    ingest_intraday_symbol(
        session,
        FixtureMarketDataAdapter(),
        "SPY",
        _OPEN - timedelta(days=1),
        _OPEN + timedelta(days=1),
        bar_size="15m",
        record_feed_status=True,
    )
    assert (
        session.scalar(
            select(DataFeedStatus).where(DataFeedStatus.feed_type == FeedType.BAR_INTRADAY)
        )
        is not None
    )


def test_history_covers_every_session_it_claims_to(session: Session) -> None:
    start, end = date(2024, 6, 3), date(2024, 6, 28)
    ingest_intraday_history(
        session, FixtureMarketDataAdapter(), ["SPY"], start, end, bar_size="15m"
    )
    rows = session.scalars(select(OHLCVIntraday)).all()
    assert all(r.session == "rth" and r.bar_size == "15m" for r in rows)
    assert all(r.is_simulated for r in rows)  # fixture data is always labelled
    days = {r.bar_start.astimezone().date() for r in rows}
    assert len(days) >= len(calendar_sessions(start, end)) - 1


# --------------------------------------------------------------------------- #
# B7: RTH purity at ingest AND at load
# --------------------------------------------------------------------------- #
def _write_bar(session: Session, stamp: datetime, sess: str) -> None:
    from signalforge.data.repository import get_or_create_instrument
    from signalforge.db.types import utcnow

    inst = get_or_create_instrument(session, "SPY")
    session.add(
        OHLCVIntraday(
            instrument_id=inst.id,
            bar_start=stamp,
            bar_size="15m",
            session=sess,
            open=100.0,
            high=101.0,
            low=99.0,
            close=100.0,
            volume=1_000.0,
            source="massive",
            latency_category=LatencyCategory.DELAYED,
            is_simulated=False,
            ingested_at=utcnow(),
            quality_flags=[],
        )
    )
    session.flush()


def test_load_intraday_drops_extended_hours_bars(session: Session) -> None:
    _write_bar(session, _OPEN, "rth")
    # 20:15 ET on 2024-06-25 == 00:15 UTC on 2024-06-26: a post-market bar that
    # `_session_date` would file under the NEXT session, corrupting its
    # opening range.
    _write_bar(session, datetime(2024, 6, 26, 0, 15, tzinfo=UTC), "post")
    _write_bar(session, datetime(2024, 6, 25, 12, 0, tzinfo=UTC), "pre")

    lo = datetime(2024, 6, 24, tzinfo=UTC)
    hi = datetime(2024, 6, 27, tzinfo=UTC)
    rth = PriceSeries.load_intraday(session, "SPY", lo, hi, bar_size="15m")
    assert list(rth.dates) == [_OPEN]

    everything = PriceSeries.load_intraday(
        session, "SPY", lo, hi, bar_size="15m", session_filter=None
    )
    assert len(everything) == 3  # the rows are still there; the loader excludes them


def test_ingest_skips_non_rth_bars_and_counts_them(session: Session) -> None:
    class _ExtendedHours:
        provider_name = "fixture"

        @property
        def capabilities(self):  # pragma: no cover - trivial
            return FixtureMarketDataAdapter().capabilities

        def fetch_intraday_bars(self, symbol, start, end, *, bar_size="5m"):
            from signalforge.data.adapters.base import IntradayBar, Provenance

            prov = Provenance(
                source="fixture",
                latency_category=LatencyCategory.HISTORICAL,
                retrieved_at=datetime.now(UTC),
                is_simulated=True,
            )
            return [
                IntradayBar("SPY", _OPEN, "15m", "rth", 1.0, 1.0, 1.0, 1.0, 1.0, prov),
                IntradayBar(
                    "SPY",
                    _OPEN - timedelta(hours=2),
                    "15m",
                    "pre",
                    1.0,
                    1.0,
                    1.0,
                    1.0,
                    1.0,
                    prov,
                ),
            ]

    r = ingest_intraday_symbol(
        session,
        _ExtendedHours(),
        "SPY",
        _OPEN - timedelta(days=1),
        _OPEN + timedelta(days=1),
        bar_size="15m",
    )
    assert r.bars_written == 1
    assert r.bars_skipped == 1  # counted, never silently dropped
    assert [b.session for b in session.scalars(select(OHLCVIntraday))] == ["rth"]


def test_a_fixture_backfill_satisfies_the_gate0_coverage_query(session: Session) -> None:
    """End to end: what the backfill writes is exactly what gate 0 demands."""
    start, end = date(2024, 6, 3), date(2024, 6, 28)
    ingest_intraday_history(
        session, FixtureMarketDataAdapter(), ["SPY"], start, end, bar_size="15m"
    )
    report = intraday_rth_coverage(
        session, ["SPY"], start=start, end=end, bar_size="15m", source="fixture"
    )
    # the fixture adapter is SIMULATED, so its rows must NOT satisfy gate 0
    assert not report.complete
    assert report.rows_rejected_simulated > 0
    assert "SIMULATED" in report.detail()


# --------------------------------------------------------------------------- #
# the Massive intraday adapter (offline, injected transport)
# --------------------------------------------------------------------------- #
_BAR_T = int(_OPEN.timestamp() * 1000)
PAYLOAD = {
    "status": "OK",
    "adjusted": True,
    "results": [{"t": _BAR_T, "o": 100, "h": 102, "l": 99, "c": 101, "v": 5000}],
}


def _adapter(payload=PAYLOAD, status=200, capture: list | None = None) -> MassiveAdapter:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "api.massive.com"
        assert "apiKey" not in request.url.params
        if capture is not None:
            capture.append(str(request.url))
        return httpx.Response(status, json=payload)

    return MassiveAdapter(
        "test-placeholder", client=httpx.Client(transport=httpx.MockTransport(handler))
    )


def test_massive_declares_a_delayed_intraday_capability() -> None:
    caps = {c.feed_type: c for c in _adapter().capabilities}
    assert set(caps) == {FeedType.BAR_DAILY, FeedType.BAR_INTRADAY}
    intraday = caps[FeedType.BAR_INTRADAY]
    assert intraday.latency_category is LatencyCategory.DELAYED
    assert intraday.latency_category.is_live is False  # S7: never labelled live
    assert intraday.delay_estimate == "15 min"
    assert intraday.rate_limit_per_min == 5


def test_massive_intraday_request_shape_and_session_labelling() -> None:
    seen: list[str] = []
    bars = _adapter(capture=seen).fetch_intraday_bars(
        "SPY", _OPEN, _OPEN + timedelta(hours=1), bar_size="15m"
    )
    assert "/v2/aggs/ticker/SPY/range/15/minute/2024-06-25/2024-06-25" in seen[0]
    assert "limit=50000" in seen[0] and "adjusted=true" in seen[0] and "sort=asc" in seen[0]
    assert len(bars) == 1
    b = bars[0]
    assert b.bar_start == _OPEN and b.bar_size == "15m" and b.session == "rth"
    assert b.provenance.latency_category is LatencyCategory.DELAYED
    assert b.provenance.is_simulated is False

    # "1h" maps to the hour unit, not 60 minutes
    seen.clear()
    _adapter(capture=seen).fetch_intraday_bars(
        "SPY", _OPEN, _OPEN + timedelta(hours=1), bar_size="1h"
    )
    assert "/range/1/hour/" in seen[0]


def test_massive_intraday_rejects_bad_input_and_incomplete_responses() -> None:
    a = _adapter()
    with pytest.raises(ValueError, match="aware"):
        a.fetch_intraday_bars("SPY", _OPEN.replace(tzinfo=None), _OPEN, bar_size="15m")
    with pytest.raises(ValueError, match="bar_size"):
        a.fetch_intraday_bars("SPY", _OPEN, _OPEN, bar_size="7m")

    for payload in (
        {},
        {**PAYLOAD, "next_url": "https://example.com/page2"},  # never paginate silently
        {**PAYLOAD, "adjusted": False},
        {**PAYLOAD, "results": []},
        {**PAYLOAD, "results": [{**PAYLOAD["results"][0], "l": 500}]},  # low above open
    ):
        with pytest.raises(AdapterError):
            _adapter(payload).fetch_intraday_bars(
                "SPY", _OPEN, _OPEN + timedelta(hours=1), bar_size="15m"
            )


def test_massive_intraday_drops_bars_outside_any_session() -> None:
    saturday = datetime(2024, 6, 22, 15, 0, tzinfo=UTC)
    payload = {
        "status": "OK",
        "adjusted": True,
        "results": [
            {"t": int(saturday.timestamp() * 1000), "o": 1, "h": 1, "l": 1, "c": 1, "v": 1},
        ],
    }
    with pytest.raises(AdapterError):  # every bar dropped -> "No bars"
        _adapter(payload).fetch_intraday_bars(
            "SPY", saturday - timedelta(hours=1), saturday + timedelta(hours=1), bar_size="15m"
        )


def test_massive_intraday_never_leaks_the_key() -> None:
    with pytest.raises(AdapterError) as exc:
        _adapter(status=403).fetch_intraday_bars(
            "SPY", _OPEN, _OPEN + timedelta(hours=1), bar_size="15m"
        )
    assert "test-placeholder" not in str(exc.value)


def test_each_chunk_spans_whole_new_york_days(session: Session) -> None:
    """Incident 2026-10-26 (ingestion_run 73): post-market bars on a chunk's
    last trading day fall after midnight UTC. A UTC end-of-day bound made the
    adapter reject every chunk ending on a trading day. Chunks are bounded by
    New York calendar days instead."""
    from zoneinfo import ZoneInfo

    ny = ZoneInfo("America/New_York")
    seen: list[tuple[datetime, datetime]] = []

    class _Recorder:
        provider_name = "fixture"

        @property
        def capabilities(self):  # pragma: no cover - trivial
            return FixtureMarketDataAdapter().capabilities

        def fetch_intraday_bars(self, symbol, start, end, *, bar_size="5m"):
            seen.append((start, end))
            return FixtureMarketDataAdapter().fetch_intraday_bars(
                symbol, start, end, bar_size=bar_size
            )

    # 2024-02-29 is a Thursday session: the Jan-Feb chunk ends on a trading day
    ingest_intraday_history(
        session, _Recorder(), ["SPY"], date(2024, 2, 26), date(2024, 3, 1), bar_size="15m"
    )
    (lo1, hi1), (lo2, _) = seen
    assert lo1.astimezone(ny) == datetime(2024, 2, 26, tzinfo=ny)
    assert hi1.astimezone(ny).date() == date(2024, 2, 29)
    # 19:45 ET post-market on the last day (00:45 UTC the next day) is inside
    late_post_market = datetime(2024, 3, 1, 0, 45, tzinfo=UTC)
    assert lo1 <= late_post_market <= hi1
    assert lo2.astimezone(ny) == datetime(2024, 3, 1, tzinfo=ny)


def test_a_failing_backfill_never_creates_a_feed_status_row(session: Session) -> None:
    """Incident 2026-10-26: failed backfill chunks recorded BAR_INTRADAY
    failures, creating a never-successful feed row that blocks every candidate
    and briefing alert. A backfill must leave feed status untouched on failure."""

    class _AlwaysFails:
        provider_name = "fixture"

        @property
        def capabilities(self):  # pragma: no cover - trivial
            return FixtureMarketDataAdapter().capabilities

        def fetch_intraday_bars(self, symbol, start, end, *, bar_size="5m"):
            raise AdapterError("provider says no")

    run = ingest_intraday_history(
        session, _AlwaysFails(), ["SPY"], date(2024, 6, 3), date(2024, 6, 14), bar_size="15m"
    )
    assert run.symbols_failed
    assert session.scalars(select(DataFeedStatus)).all() == []
