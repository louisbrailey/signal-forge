"""Run control for the multi-day options backfill — commit boundaries, kill
switch, pass bounds, and the zero-network request plan.

These are the properties the real ~29,000-request run depends on, and every one
of them is invisible in a short offline pass unless it is asserted directly:

* a failure on cycle N leaves cycles 1..N-1 **committed and visible to another
  connection** — not merely flushed into a transaction that the enclosing scope
  will roll back;
* the ``IngestionRun`` row is committed BEFORE the first request, so an abort of
  any kind leaves an id to ``--resume``;
* the kill switch ends the run at a cycle boundary: terminal, resumable, and
  never destructive of what was already fetched;
* ``--max-cycles`` / ``--max-minutes`` end a PASS, not the dataset;
* the request plan is arithmetic over pre-registered parameters and issues
  nothing.

The observer session is the point of most of these: it is a SECOND connection,
so a row it can see is a row that was really committed.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from signalforge.data.adapters import massive_options as mo
from signalforge.data.adapters.massive_options import MassiveOptionsAdapter
from signalforge.data.calendar import sessions as _sessions
from signalforge.data.options_backfill import (
    RUN_STATUS_KILLED,
    RUN_STATUS_STOPPED,
    BackfillRequestPlan,
    CycleBackfillCaps,
    RunBounds,
    backfill_option_cycles,
    completed_cycle_units,
    coverage_summary,
    plan_cycle_backfill,
)
from signalforge.db.models import IngestionRun, Instrument, OHLCVDaily, OptionAggregateDaily
from signalforge.db.session import get_sessionmaker
from signalforge.domain import LatencyCategory
from signalforge.killswitch import get_kill_switch

WINDOW_START = date(2024, 1, 2)
WINDOW_END = date(2024, 9, 30)


@pytest.fixture(autouse=True)
def _no_real_sleeping(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mo.MassiveOptionsAdapter, "_sleep", lambda self, _s: None)


def _seed_equity(session: Session, symbol: str = "SPY", *, level: float = 400.0) -> None:
    inst = Instrument(symbol=symbol, name=symbol, instrument_type="etf", exchange="ARCX")
    session.add(inst)
    session.flush()
    for d in _sessions(WINDOW_START - timedelta(days=120), WINDOW_END):
        session.add(
            OHLCVDaily(
                instrument_id=inst.id,
                session_date=d,
                open=level,
                high=level,
                low=level,
                close=level,
                volume=1_000_000,
                source="massive",
                latency_category=LatencyCategory.HISTORICAL,
                ingested_at=datetime.now(UTC),
                is_simulated=False,
            )
        )
    session.commit()


_AGG_RE = re.compile(r"/v2/aggs/ticker/(?P<tk>[^/]+)/range/1/day/(?P<a>[\d-]+)/(?P<b>[\d-]+)")
_EXP_RE = re.compile(r"O:[A-Z]+(?P<yy>\d\d)(?P<mm>\d\d)(?P<dd>\d\d)[CP]")


def _client(
    *,
    listing_urls: list[str] | None = None,
    agg_urls: list[str] | None = None,
    boom_on_listing: int | None = None,
    engage_kill_on_listing: int | None = None,
) -> httpx.Client:
    """A three-cycle SPY chain. ``boom_on_listing`` raises a non-adapter error
    on the Nth listing call; ``engage_kill_on_listing`` engages the real kill
    switch just before answering the Nth one, so the NEXT request raises."""
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "/v3/reference/options/contracts" in url:
            seen.append(url)
            if listing_urls is not None:
                listing_urls.append(url)
            if boom_on_listing is not None and len(seen) == boom_on_listing:
                raise RuntimeError("provider melted down mid-run")
            if engage_kill_on_listing is not None and len(seen) == engage_kill_on_listing:
                get_kill_switch().engage("test: operator halt mid-backfill", actor="test")
            exp = re.search(r"expiration_date\.gte=([\d-]+)", url)
            assert exp
            expiry = date.fromisoformat(exp.group(1))
            rows = []
            k = 340.0
            while k <= 460.0 + 1e-9:
                for cp, right in (("C", "call"), ("P", "put")):
                    rows.append(
                        {
                            "ticker": f"O:SPY{expiry:%y%m%d}{cp}{round(k * 1000):08d}",
                            "contract_type": right,
                            "strike_price": round(k, 2),
                            "expiration_date": expiry.isoformat(),
                            "exercise_style": "american",
                            "shares_per_contract": 100,
                        }
                    )
                k += 1.0
            return httpx.Response(200, json={"status": "OK", "results": rows})
        m = _AGG_RE.search(url)
        if m:
            if agg_urls is not None:
                agg_urls.append(url)
            e = _EXP_RE.search(m["tk"])
            assert e
            expiry = date(2000 + int(e["yy"]), int(e["mm"]), int(e["dd"]))
            a, b = date.fromisoformat(m["a"]), date.fromisoformat(m["b"])
            out = [
                {
                    "t": int(datetime(d.year, d.month, d.day, tzinfo=UTC).timestamp() * 1000),
                    "o": 1.0,
                    "h": 1.5,
                    "l": 0.8,
                    "c": 1.2,
                    "v": 10,
                    "vw": 1.1,
                    "n": 3,
                }
                for d in _sessions(a, min(b, expiry))
            ]
            return httpx.Response(200, json={"status": "OK", "results": out})
        return httpx.Response(404, json={})

    return httpx.Client(transport=httpx.MockTransport(handler))


def _adapter(**kw: object) -> MassiveOptionsAdapter:
    return MassiveOptionsAdapter("k", client=_client(**kw))  # type: ignore[arg-type]


def _caps(**kw: object) -> CycleBackfillCaps:
    base: dict[str, object] = {
        "window_start": WINDOW_START,
        "window_end": WINDOW_END,
        "max_total_bars": 1_000_000,
    }
    base.update(kw)
    return CycleBackfillCaps(**base)  # type: ignore[arg-type]


def _observer() -> Session:
    """A SECOND connection. What it can see has actually been committed."""
    return get_sessionmaker()()


# --- commit boundaries ------------------------------------------------------ #
def test_a_failure_mid_run_leaves_every_earlier_cycle_committed(session: Session) -> None:
    """The shipped path flushed and never committed, so one exception discarded
    days of fetching. Each cycle is now its own transaction."""
    _seed_equity(session)
    with pytest.raises(RuntimeError, match="melted down"):
        backfill_option_cycles(
            session, _adapter(boom_on_listing=3), ["SPY"], caps=_caps(), options_config_hash="h"
        )
    session.rollback()  # whatever the caller's scope would do on the way out

    with _observer() as obs:
        assert (obs.scalar(select(func.count()).select_from(OptionAggregateDaily)) or 0) > 0
        run = obs.scalars(select(IngestionRun)).one()
        cycles = run.gaps_json["SPY"]["cycles"]
        assert len(cycles) == 2  # the two that completed; the third never landed
        assert all(c["excluded"] is None for c in cycles.values())
        assert run.bars_written > 0


def test_the_run_row_is_committed_before_the_first_request(session: Session) -> None:
    """A resume id has to survive an abort of any kind — including one on the
    very first cycle, which is where the shipped path lost the row entirely."""
    _seed_equity(session)
    with pytest.raises(RuntimeError):
        backfill_option_cycles(session, _adapter(boom_on_listing=1), ["SPY"], caps=_caps())
    session.rollback()

    with _observer() as obs:
        run = obs.scalars(select(IngestionRun)).one()
        assert run.id is not None and run.status == "running"
        assert run.kind == "options_cycle_backfill"
        assert obs.scalar(select(func.count()).select_from(OptionAggregateDaily)) == 0


def test_no_write_transaction_is_open_while_a_request_is_in_flight(session: Session) -> None:
    """The project rule, asserted where it is actually broken: the write lock is
    never held across a paced provider call."""
    _seed_equity(session)
    states: list[bool] = []

    original = MassiveOptionsAdapter.fetch_option_aggregates

    def spy(self: MassiveOptionsAdapter, *a: object, **k: object) -> object:
        states.append(session.in_transaction())
        return original(self, *a, **k)  # type: ignore[arg-type]

    MassiveOptionsAdapter.fetch_option_aggregates = spy  # type: ignore[method-assign,assignment]
    try:
        backfill_option_cycles(session, _adapter(), ["SPY"], caps=_caps())
    finally:
        MassiveOptionsAdapter.fetch_option_aggregates = original  # type: ignore[method-assign]
    assert states and not any(states)


# --- the kill switch -------------------------------------------------------- #
def test_the_kill_switch_ends_the_run_at_a_cycle_boundary_without_discarding_it(
    session: Session,
) -> None:
    _seed_equity(session)
    run = backfill_option_cycles(session, _adapter(engage_kill_on_listing=2), ["SPY"], caps=_caps())
    assert run.status == RUN_STATUS_KILLED
    stop = run.gaps_json["__run__"]["stopped"]
    assert stop["status"] == RUN_STATUS_KILLED
    assert "Kill switch engaged" in stop["reason"]
    assert stop["cycles_this_pass"] == 1
    assert stop["resume_with"] == run.id
    assert "SPY" not in (run.symbols_ok or [])  # never marked done

    session.rollback()
    with _observer() as obs:
        committed = obs.scalars(select(IngestionRun)).one()
        assert committed.status == RUN_STATUS_KILLED
        assert committed.bars_written > 0
        assert len(committed.gaps_json["SPY"]["cycles"]) == 1
        assert (obs.scalar(select(func.count()).select_from(OptionAggregateDaily)) or 0) > 0


def test_a_killed_run_resumes_from_its_own_id_and_completes(session: Session) -> None:
    _seed_equity(session)
    killed = backfill_option_cycles(
        session, _adapter(engage_kill_on_listing=2), ["SPY"], caps=_caps()
    )
    assert killed.status == RUN_STATUS_KILLED
    done_before = completed_cycle_units(killed)
    assert done_before == 1

    get_kill_switch().release("test: resume", actor="test")
    resumed = backfill_option_cycles(
        session, _adapter(), ["SPY"], caps=_caps(), resume_run_id=killed.id
    )
    assert resumed.id == killed.id
    assert resumed.status == "ok"
    assert resumed.gaps_json["__run__"].get("stopped") is None
    cov = coverage_summary(resumed)
    assert cov.cycles_covered == cov.cycles_total > 1
    assert cov.stopped_reason == ""


def test_the_kill_switch_is_terminal_for_the_pass_not_retried(session: Session) -> None:
    """It halts on the FIRST request of the pass and nothing else is attempted —
    the switch is never retried, and it costs no further provider budget."""
    _seed_equity(session)
    get_kill_switch().engage("test: already halted", actor="test")
    urls: list[str] = []
    run = backfill_option_cycles(session, _adapter(listing_urls=urls), ["SPY"], caps=_caps())
    assert run.status == RUN_STATUS_KILLED
    assert urls == []
    assert run.bars_written == 0
    assert run.id is not None  # and the row still exists to resume from


# --- pass bounds ------------------------------------------------------------ #
def test_max_cycles_ends_the_pass_at_a_cycle_boundary_and_resumes(session: Session) -> None:
    _seed_equity(session)
    first = backfill_option_cycles(
        session, _adapter(), ["SPY"], caps=_caps(), bounds=RunBounds(max_cycles=1)
    )
    assert first.status == RUN_STATUS_STOPPED
    assert first.gaps_json["__run__"]["stopped"]["reason"] == "max_cycles=1"
    assert len(first.gaps_json["SPY"]["cycles"]) == 1
    assert "SPY" in (first.symbols_failed or {})
    assert coverage_summary(first).stopped_reason == "max_cycles=1"

    second = backfill_option_cycles(
        session, _adapter(), ["SPY"], caps=_caps(), resume_run_id=first.id
    )
    assert second.status == "ok"
    cov = coverage_summary(second)
    assert cov.cycles_covered == cov.cycles_total > 1


def test_max_minutes_can_end_a_pass_before_a_single_request(session: Session) -> None:
    """The bound is checked BETWEEN cycles, so an already-expired window costs
    the provider nothing at all."""
    _seed_equity(session)
    urls: list[str] = []
    run = backfill_option_cycles(
        session,
        _adapter(listing_urls=urls),
        ["SPY"],
        caps=_caps(),
        bounds=RunBounds(max_minutes=0.0),
    )
    assert run.status == RUN_STATUS_STOPPED
    assert run.gaps_json["__run__"]["stopped"]["reason"] == "max_minutes=0"
    assert urls == []
    assert run.bars_written == 0


def test_a_bounded_pass_never_marks_an_unfinished_underlying_done(session: Session) -> None:
    """`if u in ok: continue` would make a resume skip every cycle the bounded
    pass never reached."""
    _seed_equity(session)
    run = backfill_option_cycles(
        session, _adapter(), ["SPY"], caps=_caps(), bounds=RunBounds(max_cycles=1)
    )
    assert "SPY" not in (run.symbols_ok or [])
    assert "pass ended" in run.symbols_failed["SPY"]


def test_a_resume_refuses_to_splice_a_different_dataset_onto_the_same_run(
    session: Session,
) -> None:
    """Ten nightly passes under one run id: a changed window or ladder would
    leave one provenance record describing only the last night."""
    _seed_equity(session)
    first = backfill_option_cycles(
        session, _adapter(), ["SPY"], caps=_caps(), bounds=RunBounds(max_cycles=1)
    )
    with pytest.raises(ValueError, match="splice two datasets"):
        backfill_option_cycles(
            session,
            _adapter(),
            ["SPY"],
            caps=_caps(window_end=WINDOW_END - timedelta(days=60)),
            resume_run_id=first.id,
        )
    with pytest.raises(ValueError, match="options_config_hash"):
        backfill_option_cycles(
            session,
            _adapter(),
            ["SPY"],
            caps=_caps(),
            options_config_hash="different",
            resume_run_id=first.id,
        )
    # raising the bar ceiling is NOT drift: it is how an operator recovers
    # budget-limited coverage, and the run records it
    resumed = backfill_option_cycles(
        session, _adapter(), ["SPY"], caps=_caps(max_total_bars=2_000_000), resume_run_id=first.id
    )
    assert resumed.gaps_json["__run__"]["max_total_bars"] == 2_000_000


def test_every_pacing_a_multi_pass_run_used_is_kept(session: Session) -> None:
    """D1 §7.5 wants the pacing ACTUALLY used recorded. Over ten passes,
    overwriting it would describe only the final night."""
    _seed_equity(session)
    slow = MassiveOptionsAdapter("k", client=_client(), min_request_spacing_s=12.1)
    first = backfill_option_cycles(
        session, slow, ["SPY"], caps=_caps(), bounds=RunBounds(max_cycles=1)
    )
    fast = MassiveOptionsAdapter("k", client=_client(), min_request_spacing_s=0.5)
    second = backfill_option_cycles(session, fast, ["SPY"], caps=_caps(), resume_run_id=first.id)
    prov = second.gaps_json["__run__"]
    assert prov["pacing_s"] == 0.5
    assert sorted(prov["pacing_s_passes"]) == [0.5, 12.1]


# --- the request plan ------------------------------------------------------- #
def _plan(**kw: object) -> BackfillRequestPlan:
    return plan_cycle_backfill(["SPY", "QQQ"], caps=_caps(), pacing_s=12.1, **kw)  # type: ignore[arg-type]


def test_the_plan_is_arithmetic_over_pre_registered_parameters() -> None:
    plan = _plan()
    assert plan.units_total == len(plan.underlyings) * len(plan.cycles)
    assert plan.contracts_per_cycle_max == 34  # 17 rungs x 2 rights
    assert plan.listing_requests == plan.units_remaining * plan.listing_pages_assumed
    assert plan.aggregate_requests == plan.units_remaining * 34
    assert plan.requests_total == plan.listing_requests + plan.aggregate_requests
    assert plan.hours_at_pacing == pytest.approx(plan.requests_total * 12.1 / 3600.0)
    # DTE-60 back to a 5-session buffer, forward to expiry
    assert 40 <= plan.sessions_per_cycle_min <= plan.sessions_per_cycle_max <= 55
    assert plan.bars_max == round(plan.aggregate_requests * plan.sessions_per_cycle_mean)
    assert plan.ladder_id == "LADDER_17"
    assert plan.strike_listing_basis == "vendor_as_of"


def test_the_plan_subtracts_what_a_previous_pass_already_settled() -> None:
    full = _plan()
    resumed = _plan(units_done=3)
    assert resumed.units_total == full.units_total
    assert resumed.units_remaining == full.units_remaining - 3
    assert resumed.requests_total < full.requests_total


def test_the_plan_holds_no_price_field() -> None:
    """Printed before any option data exists, so it lives under the same
    counts-and-completeness rule as the coverage summary."""
    import dataclasses

    forbidden = ("price", "iv", "greek", "return", "pnl", "credit", "premium", "volume", "quote")
    for f in dataclasses.fields(BackfillRequestPlan):
        assert not any(tok in f.name.lower() for tok in forbidden), f.name


def test_completed_units_ignore_a_retryable_exclusion(session: Session) -> None:
    """A cycle left on a transient fetch failure still costs requests next pass,
    so it must not be subtracted from the plan."""
    _seed_equity(session)
    run = backfill_option_cycles(
        session, _adapter(), ["SPY"], caps=_caps(), bounds=RunBounds(max_cycles=2)
    )
    assert completed_cycle_units(run) == 2
    run.gaps_json["SPY"]["cycles"][sorted(run.gaps_json["SPY"]["cycles"])[0]][
        "excluded"
    ] = "contract_fetch_failed"
    assert completed_cycle_units(run) == 1
