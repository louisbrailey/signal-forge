"""Strategy backtest over a seeded fixture universe + report rendering."""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy.orm import Session

from signalforge.data.adapters.fixture import FixtureMarketDataAdapter
from signalforge.data.ingest import ingest_universe
from signalforge.domain import Horizon
from signalforge.research.backtest_runner import run_strategy_over_universe
from signalforge.research.reporting import render_report_md
from signalforge.research.strategies import MeanReversion, TrendContinuation

SYMS = ["SPY", "AAPL", "MSFT", "NVDA"]


def _seed(session: Session) -> tuple[date, date]:
    end = date(2024, 6, 30)
    start = end - timedelta(days=365 * 3)
    ingest_universe(session, FixtureMarketDataAdapter(), SYMS, start, end)
    session.flush()
    return start, end


def test_runner_produces_is_and_oos_metrics(session: Session) -> None:
    start, end = _seed(session)
    result = run_strategy_over_universe(
        session, TrendContinuation(Horizon.SHORT_SWING), SYMS, start, end, proxy_symbol="SPY"
    )
    assert result.n_trades >= 1
    assert result.in_sample.n_trades + result.out_of_sample.n_trades == result.n_trades
    d = result.to_dict()
    assert d["strategy"] == "trend_continuation.short_swing"
    assert "out_of_sample_ci" in d
    assert set(result.per_symbol_trades) <= set(SYMS)
    # provenance reflects the fixture ingest, never silently claims real data
    assert result.data.sources == ("fixture",)
    assert result.data.simulated is True
    assert result.data.bars > 0 and result.data.first is not None
    assert "fixture" in render_report_md(result) and "SIMULATED" in render_report_md(result)


def test_report_markdown_has_the_required_sections(session: Session) -> None:
    start, end = _seed(session)
    result = run_strategy_over_universe(session, MeanReversion(), SYMS, start, end)
    md = render_report_md(result)
    assert "# Backtest report — mean_reversion.short_swing" in md
    assert "## In-sample vs out-of-sample" in md
    assert "bootstrap 95% CI" in md
    assert "Hypothetical research output" in md
    assert "EXPERIMENTAL" in md
