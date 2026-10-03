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

from datetime import UTC, date, datetime, timedelta

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from signalforge.data import calendar
from signalforge.data.adapters.massive_options import MassiveOptionsAdapter
from signalforge.data.options_corporate_actions import (
    build_q_lookup,
    derive_dividend_yield_series,
    ingest_dividends_and_splits,
    splits_between,
    trailing_dividend_yield,
)
from signalforge.db.models import (
    DividendEvent,
    DividendYieldDaily,
    IngestionRun,
    Instrument,
    OHLCVDaily,
    SplitEvent,
)
from signalforge.domain import LatencyCategory

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


# --- the derived q series ----------------------------------------------------- #
_SERIES_START = date(2024, 9, 16)
_SERIES_END = date(2024, 12, 27)
_CLOSE = 500.0


def _seed_bars(session: Session, symbol: str, start: date, end: date, *, close: float) -> None:
    inst = Instrument(symbol=symbol, name=symbol, instrument_type="etf", exchange="ARCX")
    session.add(inst)
    session.flush()
    for d in calendar.sessions(start, end):
        session.add(
            OHLCVDaily(
                instrument_id=inst.id,
                session_date=d,
                open=close,
                high=close,
                low=close,
                close=close,
                adj_close=close,
                volume=1_000_000,
                source="massive",
                latency_category=LatencyCategory.HISTORICAL,
                ingested_at=datetime.now(UTC),
            )
        )
    session.flush()


def _series(session: Session, symbol: str) -> dict[date, DividendYieldDaily]:
    rows = session.scalars(
        select(DividendYieldDaily).where(DividendYieldDaily.symbol == symbol)
    ).all()
    return {r.session_date: r for r in rows}


def test_derived_series_is_point_in_time_per_session(session: Session) -> None:
    """``q(S)`` sums ex-dates in ``(S - 365d, S]`` only: the 2024-09-20 and
    2024-12-20 payments enter the series ON their ex-dates, never before."""
    ingest_dividends_and_splits(session, _adapter(), ["SPY"])
    _seed_bars(session, "SPY", _SERIES_START, _SERIES_END, close=_CLOSE)

    run = derive_dividend_yield_series(session, ["SPY"], _SERIES_START, _SERIES_END)
    rows = _series(session, "SPY")

    assert run.kind == "options_q_series"
    assert run.status == "ok"
    assert run.symbols_ok == ["SPY"]
    assert set(rows) == set(calendar.sessions(_SERIES_START, _SERIES_END))
    # the session BEFORE the September ex-date sees two payments ...
    before = rows[date(2024, 9, 19)]
    assert before.payments == 2 and before.q == (1.6 + 1.7) / _CLOSE
    # ... the ex-date session itself sees three
    on = rows[date(2024, 9, 20)]
    assert on.payments == 3 and on.q == (1.6 + 1.7 + 1.8) / _CLOSE
    # and the December payment is invisible until 2024-12-20
    assert rows[date(2024, 12, 19)].payments == 3
    assert rows[date(2024, 12, 20)].payments == 4
    assert rows[date(2024, 12, 20)].q == (1.6 + 1.7 + 1.8 + 1.9) / _CLOSE
    for r in rows.values():
        assert r.source == "vendor_dividends"
        assert r.reference_close == _CLOSE
        assert r.derived_from_run_id == run.id
        assert r.window_start == r.session_date - timedelta(days=365)
    # every row agrees with the one-shot helper on the same session
    y = trailing_dividend_yield(session, "SPY", date(2024, 10, 15), reference_close=_CLOSE)
    assert y is not None and rows[date(2024, 10, 15)].q == y.q
    assert run.bars_written == len(rows)
    assert run.coverage_first == _SERIES_START and run.coverage_last == _SERIES_END


def test_derived_series_writes_no_row_without_dividend_history(session: Session) -> None:
    """Never a 0.0 row: a session with nothing in its trailing window is ABSENT."""
    _seed_bars(session, "SPY", date(2023, 1, 3), date(2023, 1, 31), close=_CLOSE)
    run = derive_dividend_yield_series(session, ["SPY"], date(2023, 1, 3), date(2023, 1, 31))
    assert run.status == "ok"
    assert _count(session, DividendYieldDaily) == 0
    assert run.bars_written == 0
    assert run.gaps_json["SPY"]["sessions_without_history"] == len(
        calendar.sessions(date(2023, 1, 3), date(2023, 1, 31))
    )

    # with history only from 2024-03-15, the sessions before it stay absent
    ingest_dividends_and_splits(session, _adapter(), ["SPY"])
    _seed_bars(session, "QQQ", date(2024, 3, 11), date(2024, 3, 19), close=_CLOSE)
    # QQQ has bars but no dividends at all -> nothing, and no error
    run2 = derive_dividend_yield_series(session, ["QQQ"], date(2024, 3, 11), date(2024, 3, 19))
    assert run2.status == "ok" and _count(session, DividendYieldDaily) == 0
    # SPY needs bars in that range too
    spy = session.scalar(select(Instrument).where(Instrument.symbol == "SPY"))
    assert spy is not None
    for d in calendar.sessions(date(2024, 3, 11), date(2024, 3, 19)):
        session.add(
            OHLCVDaily(
                instrument_id=spy.id,
                session_date=d,
                open=_CLOSE,
                high=_CLOSE,
                low=_CLOSE,
                close=_CLOSE,
                volume=1.0,
                source="massive",
                latency_category=LatencyCategory.HISTORICAL,
                ingested_at=datetime.now(UTC),
            )
        )
    session.flush()
    derive_dividend_yield_series(session, ["SPY"], date(2024, 3, 11), date(2024, 3, 19))
    rows = _series(session, "SPY")
    assert min(rows) == date(2024, 3, 15)  # first ex-date; nothing earlier
    assert all(r.q > 0 for r in rows.values())


def test_derived_series_is_idempotent_and_records_a_run_per_derivation(
    session: Session,
) -> None:
    ingest_dividends_and_splits(session, _adapter(), ["SPY"])
    _seed_bars(session, "SPY", _SERIES_START, _SERIES_END, close=_CLOSE)
    run1 = derive_dividend_yield_series(session, ["SPY"], _SERIES_START, _SERIES_END)
    n = _count(session, DividendYieldDaily)
    run2 = derive_dividend_yield_series(session, ["SPY"], _SERIES_START, _SERIES_END)

    assert run2.id != run1.id
    assert _count(session, DividendYieldDaily) == n
    assert run2.bars_written == 0 and run2.bars_skipped == n
    # unchanged rows keep their original provenance
    assert {r.derived_from_run_id for r in _series(session, "SPY").values()} == {run1.id}
    assert (
        session.scalar(
            select(func.count())
            .select_from(IngestionRun)
            .where(IngestionRun.kind == "options_q_series")
        )
        == 2
    )


def test_derived_series_reports_a_symbol_without_bars_as_failed(session: Session) -> None:
    ingest_dividends_and_splits(session, _adapter(), ["SPY"])
    run = derive_dividend_yield_series(session, ["SPY"], _SERIES_START, _SERIES_END)
    assert run.status == "failed"
    assert "no massive daily bars" in run.symbols_failed["SPY"]
    assert _count(session, DividendYieldDaily) == 0


def test_build_q_lookup_matches_exact_sessions_only(session: Session) -> None:
    """Off-series is ``None`` — a non-entry for the strategy, never a carried or
    interpolated value and never 0.0."""
    ingest_dividends_and_splits(session, _adapter(), ["SPY"])
    _seed_bars(session, "SPY", _SERIES_START, _SERIES_END, close=_CLOSE)
    derive_dividend_yield_series(session, ["SPY"], _SERIES_START, _SERIES_END)

    q = build_q_lookup(session, ["spy", "QQQ"])
    assert q("SPY", date(2024, 10, 15)) == (1.6 + 1.7 + 1.8) / _CLOSE
    assert q("spy", date(2024, 10, 15)) == q("SPY", date(2024, 10, 15))
    assert q("SPY", date(2024, 10, 12)) is None  # a Saturday: not a session, no row
    assert q("SPY", date(2024, 9, 13)) is None  # before the derived range
    assert q("SPY", date(2025, 1, 2)) is None  # after it
    assert q("QQQ", date(2024, 10, 15)) is None  # no series at all
    assert build_q_lookup(session, ["SPY"], source="other")("SPY", date(2024, 10, 15)) is None
    assert build_q_lookup(session, [])("SPY", date(2024, 10, 15)) is None


# --- `signalforge options q-series` (review item F) --------------------------- #
def test_q_series_cli_refuses_while_a_live_worker_heartbeat_exists(session: Session) -> None:
    from typer.testing import CliRunner

    from signalforge.cli import app
    from signalforge.db.models import IngestionRun, WorkerHeartbeat

    ingest_dividends_and_splits(session, _adapter(), ["SPY"])
    _seed_bars(session, "SPY", _SERIES_START, _SERIES_END, close=_CLOSE)
    now = datetime.now(UTC)
    session.add(
        WorkerHeartbeat(
            worker="scheduler",
            host="some-other-host",
            pid=1,
            started_at=now - timedelta(minutes=5),
            last_beat_at=now,
        )
    )
    session.commit()

    args = [
        "options",
        "q-series",
        "--symbols",
        "SPY",
        "--since",
        _SERIES_START.isoformat(),
        "--until",
        _SERIES_END.isoformat(),
    ]
    res = CliRunner().invoke(app, args)
    assert res.exit_code == 2, res.output
    assert "REFUSED" in res.output and "live scheduler heartbeat" in res.output
    session.expire_all()
    assert _count(session, DividendYieldDaily) == 0
    q_runs = (
        select(func.count())
        .select_from(IngestionRun)
        .where(IngestionRun.kind == "options_q_series")
    )
    assert session.scalar(q_runs) == 0

    # a STALE heartbeat is not a live worker: the same command now runs
    hb = session.scalar(select(WorkerHeartbeat))
    assert hb is not None
    hb.last_beat_at = now - timedelta(hours=1)
    session.commit()
    res = CliRunner().invoke(app, args)
    assert res.exit_code == 0, res.output
    session.expire_all()
    assert _count(session, DividendYieldDaily) == len(calendar.sessions(_SERIES_START, _SERIES_END))
    assert session.scalar(q_runs) == 1


def test_q_series_cli_refuses_while_the_worker_lock_is_held(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from typer.testing import CliRunner

    import signalforge.worker_lock as wl
    from signalforge.cli import app

    monkeypatch.setattr(wl, "worker_lock_holder", lambda path=None: "12345")
    res = CliRunner().invoke(app, ["options", "q-series", "--symbols", "SPY"])
    assert res.exit_code == 2
    assert "holds the write lock" in res.output
    assert _count(session, DividendYieldDaily) == 0


def test_per_symbol_commits_retry_a_locked_unit_and_keep_finished_ones(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Each underlying is its own committed unit: a transient lock on the second
    is retried whole, and the first is already durable when it happens."""
    from sqlalchemy.exc import OperationalError

    import signalforge.data.options_corporate_actions as oca
    import signalforge.db.retry as retry
    from signalforge.db.session import get_sessionmaker

    ingest_dividends_and_splits(session, _adapter(), ["SPY"])
    _seed_bars(session, "SPY", _SERIES_START, _SERIES_END, close=_CLOSE)
    _seed_bars(session, "QQQ", _SERIES_START, _SERIES_END, close=_CLOSE)
    session.commit()
    monkeypatch.setattr(retry.time, "sleep", lambda _s: None)

    real = oca.get_daily_bars
    seen: list[tuple[str, int]] = []

    def flaky(sess: Session, sym: str, *a: object, **kw: object):  # type: ignore[no-untyped-def]
        if sym == "QQQ" and not any(s == "QQQ" for s, _ in seen):
            with get_sessionmaker()() as other:  # what a second connection can see NOW
                seen.append((sym, _count(other, DividendYieldDaily)))
            raise OperationalError("SELECT 1", {}, Exception("database is locked"))
        return real(sess, sym, *a, **kw)

    monkeypatch.setattr(oca, "get_daily_bars", flaky)
    run = derive_dividend_yield_series(
        session, ["SPY", "QQQ"], _SERIES_START, _SERIES_END, commit_per_symbol=True
    )
    n = len(calendar.sessions(_SERIES_START, _SERIES_END))
    # SPY's rows were committed before QQQ's unit hit the lock
    assert seen == [("QQQ", n)]
    assert run.status == "ok" and run.symbols_ok == ["SPY", "QQQ"]
    assert run.bars_written == n  # QQQ has no dividend history: no rows, never 0.0
    assert not session.in_transaction()
