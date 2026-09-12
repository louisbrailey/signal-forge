"""Dividend and split reference ingestion — offline contract tests.

These two tables exist for one reason each, and both reasons are a
one-directional bias rather than noise:

* ``q`` defaults to 0.0 in the pricing path, which underprices puts on a
  dividend-paying underlying — in a premium-SELLING strategy's own favour. The
  trailing yield here is the rank-1 source that replaces the default, and it
  must be point-in-time and must never fall back to 0.0.
* stored equity bars are back-adjusted while option strikes are not, so a cycle
  crossing a split is mis-struck in a way that looks exactly like an empty
  chain. ``splits_between`` is what lets that cycle be NAMED.
"""

from __future__ import annotations

from datetime import date

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from signalforge.data.adapters.massive_options import MassiveOptionsAdapter
from signalforge.data.options_corporate_actions import (
    ingest_dividends_and_splits,
    splits_between,
    trailing_dividend_yield,
)
from signalforge.db.models import DividendEvent, SplitEvent

_DIVS = [
    {
        "ex_dividend_date": "2024-03-15",
        "cash_amount": 1.6,
        "frequency": 4,
        "pay_date": "2024-03-20",
    },
    {"ex_dividend_date": "2024-06-21", "cash_amount": 1.7, "frequency": 4},
    {"ex_dividend_date": "2024-09-20", "cash_amount": 1.8, "frequency": 4},
    {"ex_dividend_date": "2024-12-20", "cash_amount": 1.9, "frequency": 4},
    {"ex_dividend_date": "bad-date", "cash_amount": 9.9},  # silently unusable
]
_SPLITS = [
    {"execution_date": "2024-06-10", "split_from": 1, "split_to": 10},
    {"execution_date": "2020-08-31", "split_from": 1, "split_to": 4},
]


def _make_client(*, fail: bool = False, calls: list[str] | None = None) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if calls is not None:
            calls.append(url)
        if fail:
            return httpx.Response(403, json={"status": "ERROR"})
        if "/v3/reference/dividends" in url:
            return httpx.Response(200, json={"status": "OK", "results": _DIVS})
        if "/v3/reference/splits" in url:
            return httpx.Response(200, json={"status": "OK", "results": _SPLITS})
        return httpx.Response(404, json={})

    return httpx.Client(transport=httpx.MockTransport(handler))


def _adapter(**kw: object) -> MassiveOptionsAdapter:
    return MassiveOptionsAdapter("k", client=_make_client(**kw))  # type: ignore[arg-type]


def _count(session: Session, model: type) -> int:
    return session.scalar(select(func.count()).select_from(model)) or 0


# --------------------------------------------------------------------------- #
def test_ingest_writes_both_tables_and_a_real_ingestion_run(session: Session) -> None:
    run = ingest_dividends_and_splits(session, _adapter(), ["SPY"])

    assert run.status == "ok"
    assert run.kind == "options_q_reference"
    assert run.symbols_ok == ["SPY"]
    # the malformed ex-date is dropped by the adapter, never stored as a guess
    assert _count(session, DividendEvent) == 4
    assert _count(session, SplitEvent) == 2
    assert run.bars_written == 6
    assert run.gaps_json["SPY"]["dividends_written"] == 4
    assert run.gaps_json["SPY"]["splits_written"] == 2
    assert run.gaps_json["SPY"]["first_ex_date"] == "2024-03-15"


def test_ingest_is_idempotent_on_symbol_date_source(session: Session) -> None:
    ingest_dividends_and_splits(session, _adapter(), ["SPY"])
    run2 = ingest_dividends_and_splits(session, _adapter(), ["SPY"])

    assert _count(session, DividendEvent) == 4
    assert _count(session, SplitEvent) == 2
    assert run2.bars_written == 0
    assert run2.bars_skipped == 6


def test_a_failed_symbol_stays_retryable_and_a_resume_completes_it(session: Session) -> None:
    run = ingest_dividends_and_splits(session, _adapter(fail=True), ["SPY"])
    assert run.status == "failed"
    assert "SPY" in (run.symbols_failed or {})
    assert run.symbols_ok in (None, [])
    assert _count(session, DividendEvent) == 0

    resumed = ingest_dividends_and_splits(session, _adapter(), ["SPY"], resume_run_id=run.id)
    assert resumed.id == run.id
    assert resumed.status == "ok"
    assert resumed.symbols_failed == {}
    assert _count(session, DividendEvent) == 4


def test_a_symbol_already_ok_is_not_re_fetched_on_resume(session: Session) -> None:
    run = ingest_dividends_and_splits(session, _adapter(), ["SPY"])
    calls: list[str] = []
    ingest_dividends_and_splits(
        session,
        MassiveOptionsAdapter("k", client=_make_client(calls=calls)),
        ["SPY"],
        resume_run_id=run.id,
    )
    assert calls == []


# --- q ---------------------------------------------------------------------- #
def test_trailing_yield_is_point_in_time_and_sums_only_past_ex_dates(session: Session) -> None:
    ingest_dividends_and_splits(session, _adapter(), ["SPY"])

    # As at 2024-09-30 the December payment has NOT happened. A yield that
    # included it would be a dividend leaking backwards into a decision.
    y = trailing_dividend_yield(session, "SPY", date(2024, 9, 30), reference_close=500.0)
    assert y is not None
    assert y.payments == 3
    assert y.q == (1.6 + 1.7 + 1.8) / 500.0
    assert y.source == "vendor_dividends"
    assert y.window_end == date(2024, 9, 30)

    later = trailing_dividend_yield(session, "SPY", date(2024, 12, 31), reference_close=500.0)
    assert later is not None
    assert later.payments == 4


def test_trailing_yield_returns_None_rather_than_zero_when_there_is_no_history(
    session: Session,
) -> None:
    """q = 0 is not a measurement. The caller must fall to put-call parity or
    fail gate 0.g — it may never silently price at zero."""
    assert trailing_dividend_yield(session, "SPY", date(2024, 9, 30), reference_close=500.0) is None

    ingest_dividends_and_splits(session, _adapter(), ["SPY"])
    # before the first ex-date in the series, still nothing to rest on
    assert trailing_dividend_yield(session, "SPY", date(2023, 1, 3), reference_close=500.0) is None
    # a nonsensical reference is refused rather than dividing by it
    assert trailing_dividend_yield(session, "SPY", date(2024, 9, 30), reference_close=0.0) is None


def test_trailing_yield_drops_payments_older_than_the_trailing_window(session: Session) -> None:
    ingest_dividends_and_splits(session, _adapter(), ["SPY"])
    y = trailing_dividend_yield(session, "SPY", date(2024, 12, 31), reference_close=500.0)
    assert y is not None and y.payments == 4
    # 2024-03-15 falls out of a 12-month window ending 2025-03-15
    y2 = trailing_dividend_yield(session, "SPY", date(2025, 3, 15), reference_close=500.0)
    assert y2 is not None and y2.payments == 3


# --- splits ------------------------------------------------------------------ #
def test_splits_between_names_the_event_a_cycle_crosses(session: Session) -> None:
    ingest_dividends_and_splits(session, _adapter(), ["SPY"])

    crossing = splits_between(session, "SPY", date(2024, 5, 1), date(2024, 7, 19))
    assert [s.execution_date for s in crossing] == [date(2024, 6, 10)]
    assert crossing[0].split_to / crossing[0].split_from == 10.0

    assert splits_between(session, "SPY", date(2024, 7, 1), date(2024, 9, 20)) == []
    # the interval is half-open on the left: a split ON the start is not crossed
    assert splits_between(session, "SPY", date(2024, 6, 10), date(2024, 7, 19)) == []
    assert len(splits_between(session, "SPY", date(2024, 6, 9), date(2024, 6, 10))) == 1
