"""Read-only venue repricing of the crypto paper books — synthetic bars only."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from typer.testing import CliRunner

from signalforge.backtest.costs import CostModel
from signalforge.backtest.engine import run_backtest
from signalforge.cli import app
from signalforge.db.models import CryptoPaperBook, CryptoPaperTrade
from signalforge.domain import Direction
from signalforge.paper import crypto_ledger as cl
from signalforge.paper.crypto_venue_report import render_text, reprice_r, venue_report
from signalforge.research.fx.harness import CRYPTO_MARKET, load_series
from signalforge.research.fx.strategies import CRYPTO_STRATEGIES
from signalforge.research.fx.venues import (
    COINBASE_CFM_INTRO,
    COINBASE_SPOT_INTRO,
    HARNESS_DEFAULT,
)
from tests.paper.test_crypto_ledger import STRATEGY, _add_bars, _closes, _sealed


def _book(session: Session) -> None:
    _add_bars(session, _closes())
    _sealed(session)
    cl.start_book(session, STRATEGY, now=datetime(2020, 6, 1, tzinfo=UTC))
    cl.run_cycle(session, STRATEGY, now=datetime(2026, 1, 1, tzinfo=UTC))


def test_harness_default_reproduces_the_recorded_r() -> None:
    kw = {
        "pair": "BTCUSD",
        "direction": "LONG",
        "entry_fill": 20024.0,
        "stop": 18000.0,
        "r_recorded": 1.37,
        "costs_bps": 26.0,
        "bars_held": 10,
        "bar_days": 1.0,
    }
    assert reprice_r(**kw, venue=HARNESS_DEFAULT) == pytest.approx(1.37, abs=1e-12)
    spot = reprice_r(**kw, venue=COINBASE_SPOT_INTRO)
    cfm = reprice_r(**kw, venue=COINBASE_CFM_INTRO)
    assert spot < cfm < 1.37
    funded = reprice_r(**kw, venue=COINBASE_CFM_INTRO.with_funding(1000))
    assert funded < cfm
    short = {**kw, "direction": "SHORT", "stop": 22000.0}
    assert reprice_r(**short, venue=HARNESS_DEFAULT) == pytest.approx(1.37, abs=1e-12)
    assert reprice_r(**short, venue=COINBASE_SPOT_INTRO) < 1.37


def test_closed_trades_reprice_like_an_engine_run_at_the_venue_cost(session: Session) -> None:
    """Exit timing does not depend on cost, so a closed paper trade repriced at
    spot equals the engine's own trade at the spot spread (same entry date)."""
    _book(session)
    report = venue_report(session)
    (book,) = report["books"]
    closed = [t for t in book["trades"] if t["status"] == "CLOSED"]
    assert closed, "fixture must close trades"
    assert book["harness_default_max_abs_error_r"] < 1e-9
    strat = next(s for s in CRYPTO_STRATEGIES if s.key == STRATEGY)
    engine = run_backtest(
        load_series(session, "BTCUSD", CRYPTO_MARKET),
        strat.signal,
        cost_model=CostModel(slippage_bps=1.0),
        spread_bps=COINBASE_SPOT_INTRO.engine_spread_bps("BTCUSD"),
        warmup=strat.warmup,
    )
    by_entry = {t.entry_date.isoformat(): t for t in engine.trades}
    for t in closed:
        assert t["r_venue"]["coinbase_spot_intro"] == pytest.approx(
            by_entry[t["entry"]].pnl_r, abs=1e-5
        )


def test_subtotals_and_long_only_view(session: Session) -> None:
    _book(session)
    (book,) = venue_report(session)["books"]
    rows = [t for t in book["trades"] if t["r_recorded"] is not None]
    for status, key in (("CLOSED", "closed"), ("OPEN", "open")):
        sel = [t for t in rows if t["status"] == status]
        longs = [t for t in sel if t["direction"] == Direction.LONG.value]
        sub, sub_l = book["subtotals"][key], book["subtotals"][f"{key}_long"]
        assert sub["n"] == len(sel) and sub_l["n"] == len(longs)
        if sel:
            assert sub["total_r"]["recorded"] == pytest.approx(sum(t["r_recorded"] for t in sel))
            assert sub["total_r"]["coinbase_cfm_intro"] == pytest.approx(
                sum(t["r_venue"]["coinbase_cfm_intro"] for t in sel)
            )
    text = render_text(venue_report(session))
    assert "closed, parent LONG trades" in text and "READ-ONLY" in text
    assert "not a *_long rule's book" in text and "not an unseen" in text


def test_a_subtotal_with_a_short_reports_no_spot_figure(session: Session) -> None:
    """Spot cannot short: any subtotal holding a SHORT row has no spot total
    (None / "n/a"); the cfm and recorded totals are still summed."""
    _book(session)
    report = venue_report(session)
    (book,) = report["books"]
    rows = [t for t in book["trades"] if t["r_recorded"] is not None]
    shorts = [t for t in rows if t["direction"] == Direction.SHORT.value]
    assert shorts, "fixture must hold a SHORT trade"
    for status, key in (("CLOSED", "closed"), ("OPEN", "open")):
        sel = [t for t in rows if t["status"] == status]
        sub, sub_l = book["subtotals"][key], book["subtotals"][f"{key}_long"]
        if any(t["direction"] == Direction.SHORT.value for t in sel):
            assert sub["total_r"]["coinbase_spot_intro"] is None
            assert sub["expectancy_r"]["coinbase_spot_intro"] is None
            assert sub["total_r"]["coinbase_cfm_intro"] is not None
        if sub_l["n"]:
            assert sub_l["total_r"]["coinbase_spot_intro"] is not None
    # each SHORT row keeps its informational spot figure
    assert all(t["r_venue"]["coinbase_spot_intro"] is not None for t in shorts)
    assert "spot n/a" in render_text(report)


def test_the_cli_report_writes_nothing(session: Session) -> None:
    _book(session)
    before = (
        session.scalar(select(func.count()).select_from(CryptoPaperTrade)),
        session.scalar(select(CryptoPaperBook.last_cycle_at)),
    )
    result = CliRunner().invoke(app, ["crypto", "paper-venue-report"])
    assert result.exit_code == 0, result.output
    assert STRATEGY in result.output and "coinbase_cfm_intro" in result.output
    as_json = CliRunner().invoke(app, ["crypto", "paper-venue-report", "--json"])
    assert as_json.exit_code == 0 and '"books"' in as_json.output
    session.expire_all()
    after = (
        session.scalar(select(func.count()).select_from(CryptoPaperTrade)),
        session.scalar(select(CryptoPaperBook.last_cycle_at)),
    )
    assert before == after


def test_an_empty_database_reports_no_books(session: Session) -> None:
    assert venue_report(session)["books"] == []
