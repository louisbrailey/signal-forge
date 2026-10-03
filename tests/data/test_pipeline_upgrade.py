"""Retry/backoff, history discovery, ingestion-run auditing, and data validation."""

from __future__ import annotations

from datetime import date, timedelta

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from signalforge.data.adapters import massive as massive_module
from signalforge.data.adapters.base import AdapterError
from signalforge.data.adapters.fixture import FixtureMarketDataAdapter
from signalforge.data.adapters.massive import MassiveAdapter
from signalforge.data.discover import discover_history_depth
from signalforge.data.ingest import ingest_daily_history
from signalforge.data.validate import validate_daily
from signalforge.db.models import IngestionRun


@pytest.fixture(autouse=True)
def _no_real_sleeping(monkeypatch: pytest.MonkeyPatch) -> None:
    """The adapter backs off (1.5/3/6/12 s) before retrying a retryable status.
    That is right in production and ruinous offline: the retry tests below
    inject 503/429 deliberately, and a real backoff would charge up to 22.5 s
    per test for a rate limit that does not exist here.

    Patch ``_sleep`` itself, NOT ``time.sleep``. The backoff is a chunked wait
    driven by ``time.monotonic()`` (so the kill switch stays responsive), and
    neutering ``time.sleep`` alone converts it into a busy-spin of exactly the
    same duration -- slower, not faster."""
    monkeypatch.setattr(massive_module.MassiveAdapter, "_sleep", lambda self, _s: None)


# --------------------------- retry / backoff ------------------------------- #
def test_massive_retries_transient_5xx_then_succeeds() -> None:
    calls = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(503, text="temporarily unavailable")
        return httpx.Response(
            200,
            json={
                "status": "OK",
                "adjusted": True,
                "results": [{"t": 1704186000000, "o": 1, "h": 2, "l": 0.5, "c": 1.5, "v": 10}],
            },
        )

    a = MassiveAdapter(
        "k",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        min_request_spacing_s=0.0,
    )
    bars = a.fetch_daily_bars("AAPL", date(2024, 1, 2), date(2024, 1, 3))
    assert calls["n"] == 3 and len(list(bars)) == 1


def test_massive_gives_up_after_max_attempts_without_leaking_key() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(429, text="rate limited SECRETKEY")

    a = MassiveAdapter(
        "SECRETKEY",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        min_request_spacing_s=0.0,
    )
    with pytest.raises(AdapterError) as exc:
        a.fetch_daily_bars("AAPL", date(2024, 1, 2), date(2024, 1, 3))
    assert exc.value.rate_limited is True
    assert "attempts" in str(exc.value) and "SECRETKEY" not in str(exc.value)


# --------------------------- history discovery --------------------------- #
def test_discover_history_depth_binary_searches_a_boundary() -> None:
    cutoff = date.today() - timedelta(days=int(6 * 365.25))

    class _Adapter:
        provider_name = "stub"

        def fetch_daily_bars(self, sym: str, start: date, end: date):
            if start >= cutoff:
                return [object()]
            return []

        def fetch_corporate_actions(self, *a):
            return []

        def fetch_earnings(self, *a):
            return []

    depth = discover_history_depth(_Adapter(), max_years_back=15, known_good_years_back=2)
    assert depth.first_unavailable < depth.earliest_available
    assert abs((depth.earliest_available - cutoff).days) <= 5
    assert depth.safe_start() > depth.earliest_available


# ----------------- ingestion run: audit + idempotency ------------------- #
def test_ingest_daily_history_records_run_and_is_idempotent(session: Session) -> None:
    syms = ["SPY", "AAPL"]
    start, end = date(2022, 1, 3), date(2024, 6, 28)
    run1 = ingest_daily_history(
        session, FixtureMarketDataAdapter(), syms, start, end, kind="full_history"
    )
    assert run1.status == "ok"
    assert run1.bars_written > 0 and set(run1.symbols_ok) == set(syms)
    assert run1.requested_start == start and run1.requested_end == end
    assert run1.coverage_first is not None and run1.coverage_last is not None

    run2 = ingest_daily_history(
        session, FixtureMarketDataAdapter(), syms, start, end, kind="full_history"
    )
    assert run2.bars_written == 0  # everything already present
    assert run2.bars_skipped > 0
    assert session.scalar(select(IngestionRun).where(IngestionRun.id == run1.id)) is not None


def test_ingest_daily_history_resume_skips_completed_symbols(session: Session) -> None:
    run = ingest_daily_history(
        session, FixtureMarketDataAdapter(), ["SPY"], date(2022, 1, 3), date(2024, 6, 28)
    )
    written_first = run.bars_written
    # resume the same run with an extra symbol; SPY is already in symbols_ok
    run_r = ingest_daily_history(
        session,
        FixtureMarketDataAdapter(),
        ["SPY", "MSFT"],
        date(2022, 1, 3),
        date(2024, 6, 28),
        resume_run_id=run.id,
    )
    assert run_r.id == run.id
    assert "MSFT" in run_r.symbols_ok and "SPY" in run_r.symbols_ok
    assert run_r.bars_written > written_first  # MSFT's bars were added


# --------------------------- data validation ---------------------------- #
def test_validate_daily_passes_on_clean_fixture_data(session: Session) -> None:
    ingest_daily_history(
        session, FixtureMarketDataAdapter(), ["SPY", "AAPL"], date(2021, 1, 4), date(2024, 6, 28)
    )
    res = validate_daily(session, ["SPY", "AAPL"], source="fixture")
    names = {c.name for c in res.checks}
    assert {
        "symbol_coverage",
        "chronological_order",
        "no_duplicate_sessions",
        "db_unique_bars",
        "session_completeness",
        "ohlcv_sanity",
        "adjustment_behaviour",
        "timezone_consistency",
    } <= names
    assert res.checks[0].name == "symbol_coverage"
    assert res.passed is True
    assert res.coverage["SPY"]["n_bars"] > 100


def test_validate_daily_flags_missing_symbol(session: Session) -> None:
    ingest_daily_history(
        session, FixtureMarketDataAdapter(), ["SPY"], date(2023, 1, 3), date(2024, 6, 28)
    )
    res = validate_daily(session, ["SPY", "NOPE"], source="fixture")
    cov = next(c for c in res.checks if c.name == "symbol_coverage")
    assert cov.passed is False and "NOPE" in cov.detail
    assert res.passed is False
