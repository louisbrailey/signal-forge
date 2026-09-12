"""``signalforge options coverage-report`` — the COVERAGE-SUMMARY-ONLY gate.

Policy is not enforcement. What makes this command safe to run before the
strategy pre-registration is committed is not the docstring, it is that the type
it renders has no field that could hold a price, an IV, a greek, a return, a
credit or a P&L — and no field that could hold a volume or a trade count either,
because a per-strike volume profile is a liquidity signal a selection rule could
be reverse-engineered from.

These tests assert that mechanically: the field names are checked, the rendered
output is checked against the bar values actually stored, and the command is
checked to be read-only.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from typer.testing import CliRunner

from signalforge.cli import app
from signalforge.data.adapters.massive_options import MassiveOptionsAdapter
from signalforge.data.calendar import sessions as _sessions
from signalforge.data.options_backfill import (
    CycleBackfillCaps,
    OptionsCoverageSummary,
    backfill_option_cycles,
)
from signalforge.db.models import Instrument, OHLCVDaily, OptionAggregateDaily
from signalforge.domain import LatencyCategory

WINDOW_START = date(2024, 1, 2)
WINDOW_END = date(2024, 5, 31)

# Deliberately distinctive, and deliberately OUTSIDE the range any count,
# fraction or pacing figure this command prints could land on — so a match in
# the rendered text is a leak and never a coincidence.
_OPEN, _HIGH, _LOW, _CLOSE, _VWAP = 13.57, 24.68, 11.13, 19.73, 17.31
_VOLUME, _TRANSACTIONS = 909_090, 70_707


def _seed_equity(session: Session, symbol: str = "SPY", level: float = 400.0) -> None:
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
    session.flush()


_AGG_RE = re.compile(r"/v2/aggs/ticker/(?P<tk>[^/]+)/range/1/day/(?P<a>[\d-]+)/(?P<b>[\d-]+)")
_EXP_RE = re.compile(r"O:[A-Z]+(?P<yy>\d\d)(?P<mm>\d\d)(?P<dd>\d\d)[CP]")


def _client() -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "/v3/reference/options/contracts" in url:
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
            e = _EXP_RE.search(m["tk"])
            assert e
            expiry = date(2000 + int(e["yy"]), int(e["mm"]), int(e["dd"]))
            a, b = date.fromisoformat(m["a"]), date.fromisoformat(m["b"])
            out = [
                {
                    "t": int(datetime(d.year, d.month, d.day, tzinfo=UTC).timestamp() * 1000),
                    "o": _OPEN,
                    "h": _HIGH,
                    "l": _LOW,
                    "c": _CLOSE,
                    "v": _VOLUME,
                    "vw": _VWAP,
                    "n": _TRANSACTIONS,
                }
                for d in _sessions(a, min(b, expiry))
            ]
            return httpx.Response(200, json={"status": "OK", "results": out})
        return httpx.Response(404, json={})

    return httpx.Client(transport=httpx.MockTransport(handler))


def _run(session: Session) -> int:
    _seed_equity(session)
    run = backfill_option_cycles(
        session,
        MassiveOptionsAdapter("k", client=_client()),
        ["SPY"],
        caps=CycleBackfillCaps(
            window_start=WINDOW_START, window_end=WINDOW_END, max_total_bars=1_000_000
        ),
    )
    session.commit()
    return int(run.id)


# --------------------------------------------------------------------------- #
def test_no_field_of_the_summary_can_hold_an_outcome() -> None:
    """The check is on NAMES, so it fires when a field is ADDED — not only when
    one happens to be populated with something recognisable."""
    OptionsCoverageSummary.assert_price_free()


def test_the_report_prints_counts_and_never_a_stored_bar_value(
    db_url: str, session: Session
) -> None:
    run_id = _run(session)
    stored = session.scalar(select(func.count()).select_from(OptionAggregateDaily)) or 0
    assert stored > 0  # the bars really are in the table this command could read

    result = CliRunner().invoke(app, ["options", "coverage-report", "--run", str(run_id)])
    assert result.exit_code == 0, result.output
    out = result.output

    assert f"run #{run_id}" in out
    assert "cycles:" in out and "covered" in out
    assert "contracts:" in out and "bars:" in out
    assert "continuity" in out
    assert "decision 6" in out  # the ceiling raise is reported with the run
    assert "basis=vendor_as_of" in out

    for leaked in (_OPEN, _HIGH, _LOW, _CLOSE, _VWAP):
        assert f"{leaked}" not in out
    # volume and transactions are sealed even though they are not prices: a
    # per-strike volume profile is a liquidity signal.
    assert str(_VOLUME) not in out
    assert str(_TRANSACTIONS) not in out
    assert "iv" not in out.lower().split()


def test_an_unknown_run_id_fails_loudly_rather_than_printing_an_empty_summary(
    db_url: str,
) -> None:
    result = CliRunner().invoke(app, ["options", "coverage-report", "--run", "999999"])
    assert result.exit_code == 1
    assert "not found" in result.output


def test_the_report_writes_nothing(db_url: str, session: Session) -> None:
    run_id = _run(session)
    before = session.scalar(select(func.count()).select_from(OptionAggregateDaily)) or 0

    assert (
        CliRunner().invoke(app, ["options", "coverage-report", "--run", str(run_id)]).exit_code == 0
    )

    session.expunge_all()
    after = session.scalar(select(func.count()).select_from(OptionAggregateDaily)) or 0
    assert after == before


def _refuse_network(*_a: object, **_k: object) -> None:
    raise AssertionError("this command must not issue a provider request")


def test_a_dry_run_prints_the_exact_request_plan_and_fetches_nothing(
    db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The multi-day run is planned before it is started. The plan is
    arithmetic over pre-registered parameters, so it costs a provider nothing
    and can be re-read at any time."""
    monkeypatch.setattr(httpx, "get", _refuse_network)
    result = CliRunner().invoke(
        app,
        ["options", "cycle-backfill", "--underlyings", "SPY,QQQ", "--dry-run"],
    )
    assert result.exit_code == 0, result.output
    out = result.output
    assert "plan:" in out and "DRY RUN" in out
    assert "LADDER_17" in out and "34 contracts/cycle" in out
    assert "requests:" in out and "listing" in out and "aggregate" in out
    assert "pacing" in out and "no-retry lower bound" in out
    assert "of the 2,000,000 ceiling" in out
    assert "destination: the configured database" in out


def test_the_cycle_backfill_confirms_before_it_starts_a_multi_day_fetch(
    db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The config flag that used to refuse this command outright is gone — the
    run is now safe beside the worker (one short write transaction per cycle).
    What replaces it is a plan the operator sees and a prompt they answer; a
    scheduled window passes --yes deliberately."""
    monkeypatch.setattr(httpx, "get", _refuse_network)
    result = CliRunner().invoke(
        app, ["options", "cycle-backfill", "--underlyings", "SPY"], input="n\n"
    )
    assert result.exit_code == 1
    assert "plan:" in result.output
    assert "Start fetching now?" in result.output
