"""Gate 0 for INTRADAY is a real ``ohlcv_intraday`` query, not a hard-coded fail.

The load-bearing test here is the FIRST one: with zero intraday rows the gate
must still fail. Replacing an unconditional failure with a query is only
R4-permissible because the query can never be easier to satisfy — so the
regression that proves it was not turned into a fabricated pass is the one that
matters most.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from signalforge.config.research import ResearchConfig
from signalforge.data.calendar import rth_bounds_utc
from signalforge.data.calendar import sessions as calendar_sessions
from signalforge.data.intraday_coverage import (
    bar_minutes,
    expected_rth_bars,
    intraday_rth_coverage,
)
from signalforge.data.repository import get_or_create_instrument
from signalforge.db.models import OHLCVIntraday
from signalforge.db.types import utcnow
from signalforge.domain import LatencyCategory
from signalforge.research.promotion import evaluate_promotion
from signalforge.research.strategies import IntradayORB

SOURCE = "massive"

# A gate-0-legal window: the sealed year ends at UNTIL, and the pre-sealed span
# clears MIN_PRESEALED_DAYS (350).
SINCE = date(2024, 9, 22)
UNTIL = date(2026, 9, 8)
PRE_SEALED_END = date(2025, 9, 7)


def _write_intraday(
    session: Session,
    symbols: list[str],
    start: date,
    end: date,
    *,
    bar_size: str = "1h",
    source: str = SOURCE,
    simulated: bool = False,
    sess: str = "rth",
    skip_sessions: set[date] | None = None,
    drop_last_bar_on: set[date] | None = None,
) -> int:
    """Write a complete (or deliberately holed) RTH history from the calendar."""
    step = timedelta(minutes=bar_minutes(bar_size))
    skip = skip_sessions or set()
    short = drop_last_bar_on or set()
    now = utcnow()
    written = 0
    rows: list[OHLCVIntraday] = []
    for sym in symbols:
        inst = get_or_create_instrument(session, sym)
        for day in calendar_sessions(start, end):
            if day in skip:
                continue
            bounds = rth_bounds_utc(day)
            assert bounds is not None
            n = expected_rth_bars(day, bar_size) - (1 if day in short else 0)
            t = bounds[0]
            for _ in range(n):
                rows.append(
                    OHLCVIntraday(
                        instrument_id=inst.id,
                        bar_start=t,
                        bar_size=bar_size,
                        session=sess,
                        open=100.0,
                        high=100.5,
                        low=99.5,
                        close=100.2,
                        volume=10_000.0,
                        source=source,
                        latency_category=LatencyCategory.DELAYED,
                        is_simulated=simulated,
                        ingested_at=now,
                        quality_flags=[],
                    )
                )
                t += step
                written += 1
    session.add_all(rows)
    session.flush()
    return written


def _daily_history(session: Session, symbols: list[str]) -> None:
    from signalforge.data.adapters.fixture import FixtureMarketDataAdapter
    from signalforge.data.ingest import ingest_universe

    ingest_universe(session, FixtureMarketDataAdapter(), symbols, SINCE, UNTIL)
    session.flush()


def _cfg(bar_size: str = "1h") -> ResearchConfig:
    return ResearchConfig().model_copy(update={"intraday_bar_size": bar_size})


def _gate(result, number: int):
    return next((g for g in result.gates if g.number == number), None)


# --------------------------------------------------------------------------- #
# the regression: absent data must still fail
# --------------------------------------------------------------------------- #
def test_gate0_still_fails_with_zero_intraday_rows(session: Session) -> None:
    _daily_history(session, ["SPY", "AAPL"])
    result = evaluate_promotion(
        session,
        IntradayORB(),
        symbols=["AAPL"],
        start=SINCE,
        end=UNTIL,
        source=SOURCE,
        config=_cfg(),
    )
    gate0 = _gate(result, 0)
    assert gate0 is not None and gate0.passed is False
    assert not result.passed
    assert result.verdict.startswith("NO TRADE")
    # the ladder stops at gate 0 — gates 1-10 are never reported on data the
    # evaluation has just declared unfit
    assert [g.number for g in result.gates] == [0]
    ev = gate0.evidence["intraday_coverage"]
    assert ev["rows_counted"] == 0
    assert ev["complete"] is False
    assert ev["sessions_expected"] > 200


def test_gate0_applies_the_min_presealed_span_check_it_used_to_skip(
    session: Session,
) -> None:
    """(e) in the design's gate-0 spec: the early return skipped the shared
    window-length check entirely. INTRADAY now falls through to it, so a short
    window fails for the RIGHT reason."""
    _daily_history(session, ["SPY"])
    result = evaluate_promotion(
        session,
        IntradayORB(),
        symbols=["AAPL"],
        start=date(2026, 1, 1),
        end=UNTIL,
        source=SOURCE,
        config=_cfg(),
    )
    gate0 = _gate(result, 0)
    assert gate0 is not None and gate0.passed is False
    assert "too short" in gate0.detail
    assert not result.passed


# --------------------------------------------------------------------------- #
# a complete history passes, and the ladder then runs on INTRADAY bars
# --------------------------------------------------------------------------- #
def test_gate0_passes_on_a_complete_history_and_the_ladder_continues(
    session: Session,
) -> None:
    _daily_history(session, ["SPY", "AAPL"])
    _write_intraday(session, ["AAPL"], SINCE, PRE_SEALED_END)
    result = evaluate_promotion(
        session,
        IntradayORB(),
        symbols=["AAPL"],
        start=SINCE,
        end=UNTIL,
        source=SOURCE,
        config=_cfg(),
    )
    gate0 = _gate(result, 0)
    assert gate0 is not None and gate0.passed is True, gate0.detail if gate0 else "no gate 0"
    assert "100% RTH coverage" in gate0.detail
    # fall-through: every later gate is now computed
    assert [g.number for g in result.gates] == list(range(11))
    # and it was computed on INTRADAY bars (B1) — the daily proxy would have
    # produced a provenance record of daily bars instead
    assert result.data_provenance["sources"] == [SOURCE]


# --------------------------------------------------------------------------- #
# every way the query stays strict
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "kwargs,reason",
    [
        ({"skip_sessions": {date(2025, 3, 4)}}, "absent"),
        ({"drop_last_bar_on": {date(2025, 3, 4)}}, "short"),
        ({"bar_size": "15m"}, "another bar size"),
        ({"simulated": True}, "SIMULATED"),
        ({"sess": "post"}, "non-RTH"),
        ({"source": "some_other_provider"}, "another source"),
    ],
)
def test_coverage_is_not_satisfied_by_nearly_right_data(
    session: Session, kwargs: dict, reason: str
) -> None:
    _write_intraday(session, ["AAPL"], SINCE, PRE_SEALED_END, **kwargs)
    report = intraday_rth_coverage(
        session, ["AAPL"], start=SINCE, end=PRE_SEALED_END, bar_size="1h", source=SOURCE
    )
    assert not report.complete
    assert reason in report.detail()


def test_coverage_complete_only_when_every_symbol_is_complete(session: Session) -> None:
    _write_intraday(session, ["AAPL"], SINCE, PRE_SEALED_END)
    _write_intraday(session, ["MSFT"], SINCE, PRE_SEALED_END, skip_sessions={date(2025, 1, 15)})
    one = intraday_rth_coverage(
        session, ["AAPL"], start=SINCE, end=PRE_SEALED_END, bar_size="1h", source=SOURCE
    )
    assert one.complete and one.per_symbol[0].coverage_fraction == 1.0

    both = intraday_rth_coverage(
        session,
        ["AAPL", "MSFT"],
        start=SINCE,
        end=PRE_SEALED_END,
        bar_size="1h",
        source=SOURCE,
    )
    assert not both.complete
    assert [s.symbol for s in both.incomplete_symbols] == ["MSFT"]
    assert both.per_symbol[0].complete  # AAPL is untouched by MSFT's hole


def test_half_days_use_the_calendars_own_bar_count(session: Session) -> None:
    """2024-11-29 is a 09:30-13:00 NYSE early close: 14 bars at 15m, not 26.
    The expectation comes from the calendar, so there is no half-day list to
    forget to update."""
    assert expected_rth_bars(date(2024, 11, 29), "15m") == 14
    assert expected_rth_bars(date(2024, 11, 27), "15m") == 26
    assert expected_rth_bars(date(2024, 11, 28), "15m") == 0  # Thanksgiving: closed

    lo, hi = date(2024, 11, 25), date(2024, 12, 2)
    _write_intraday(session, ["AAPL"], lo, hi, bar_size="15m")
    report = intraday_rth_coverage(
        session, ["AAPL"], start=lo, end=hi, bar_size="15m", source=SOURCE
    )
    assert report.complete, report.detail()

    # a full 26-bar day written over the early close is ALSO wrong: those bars
    # did not trade
    extra = report.per_symbol[0]
    assert extra.sessions_expected == len(calendar_sessions(lo, hi))


def test_off_calendar_rows_are_reported_not_ignored(session: Session) -> None:
    _write_intraday(session, ["AAPL"], SINCE, PRE_SEALED_END)
    inst = get_or_create_instrument(session, "AAPL")
    session.add(
        OHLCVIntraday(
            instrument_id=inst.id,
            bar_start=datetime(2025, 1, 18, 15, 0, tzinfo=UTC),  # a Saturday
            bar_size="1h",
            session="rth",
            open=1.0,
            high=1.0,
            low=1.0,
            close=1.0,
            volume=1.0,
            source=SOURCE,
            latency_category=LatencyCategory.DELAYED,
            is_simulated=False,
            ingested_at=utcnow(),
            quality_flags=[],
        )
    )
    session.flush()
    report = intraday_rth_coverage(
        session, ["AAPL"], start=SINCE, end=PRE_SEALED_END, bar_size="1h", source=SOURCE
    )
    assert not report.complete
    assert "off-calendar" in report.detail()
