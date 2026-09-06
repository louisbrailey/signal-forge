"""Scan accounting, quality gates, ranking, NO-TRADE as a first-class outcome."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from signalforge.data.adapters.fixture import FixtureMarketDataAdapter
from signalforge.data.ingest import ingest_universe
from signalforge.db.models import BacktestMetric, BacktestRun, Candidate, PaperAccount, ScanRun
from signalforge.domain import Horizon, QualityGate
from signalforge.research.candidates import persist_scan
from signalforge.research.display import probability_display
from signalforge.research.persistence import upsert_strategy_version
from signalforge.research.scan import run_scan
from signalforge.research.strategies import default_strategies

UNIVERSE = ["SPY", "AAPL", "MSFT", "NVDA", "XOM"]
AS_OF = date(2024, 6, 30)


def _seed(session: Session, *, oos_expectancy_r: float, oos_trades: int = 200) -> None:
    session.add(PaperAccount(name="default", initial_cash=10_000, cash=10_000))
    ingest_universe(
        session, FixtureMarketDataAdapter(), UNIVERSE, AS_OF - timedelta(days=365 * 5), AS_OF
    )
    session.flush()
    # Persist a backtest metric row per strategy so the OOS-evidence gate has input.
    for strat in default_strategies():
        ver = upsert_strategy_version(session, strat.spec())
        run = BacktestRun(
            strategy_version_id=ver.id,
            params_json={},
            date_start=AS_OF - timedelta(days=900),
            date_end=AS_OF,
            config_hash="test",
        )
        session.add(run)
        session.flush()
        session.add(
            BacktestMetric(
                run_id=run.id,
                segment="all",
                phase="out_of_sample",
                metrics_json={"expectancy_r": oos_expectancy_r, "n_trades": oos_trades},
                ci_json={
                    "expectancy_r": {"low": oos_expectancy_r - 0.05, "high": oos_expectancy_r + 0.2}
                },
            )
        )
    session.flush()


def test_scan_accounting_reconciles(session: Session) -> None:
    _seed(session, oos_expectancy_r=-0.8)  # no edge -> everything NO TRADE
    result = run_scan(session, Horizon.SHORT_SWING, as_of=AS_OF, symbols=UNIVERSE)

    passing = [c for c in result.candidates if c.quality_gate_status is QualityGate.PASSED]
    assert passing == []  # negative OOS expectancy fails the gate
    # every scanned symbol is accounted for as a candidate-draft or a no-strategy no-trade
    assert set(result.scanned) <= set(UNIVERSE)
    assert result.excluded_count + len(result.scanned) == len(UNIVERSE)
    assert result.no_trade, "expected NO TRADE entries"
    for c in result.candidates:
        assert c.quality_gate_status is QualityGate.NO_TRADE
        assert any("OOS expectancy" in g for g in c.failed_gates)


def test_no_strategy_for_intraday_excludes_everything(session: Session) -> None:
    _seed(session, oos_expectancy_r=0.3)
    result = run_scan(session, Horizon.INTRADAY, as_of=AS_OF, symbols=UNIVERSE)
    assert result.scanned == []
    assert result.excluded.get("no_strategy_for_horizon") == UNIVERSE or set(
        result.excluded.get("no_strategy_for_horizon", [])
    ) == set(UNIVERSE)


def test_stale_feed_excludes_all_and_disables_live_alerts(session: Session) -> None:
    _seed(session, oos_expectancy_r=0.3)
    # Age the feed far past the SHORT_SWING budget.
    from signalforge.db.models import DataFeedStatus

    row = session.scalar(select(DataFeedStatus).where(DataFeedStatus.provider == "fixture"))
    assert row is not None
    row.last_success_at = datetime.now(UTC) - timedelta(days=30)
    session.flush()

    result = run_scan(session, Horizon.SHORT_SWING, as_of=AS_OF, symbols=UNIVERSE)
    assert result.live_alerts_enabled is False
    assert set(result.excluded.get("stale_or_unavailable_feed", [])) == set(UNIVERSE)


def test_persist_scan_writes_run_and_candidate_rows(session: Session) -> None:
    _seed(session, oos_expectancy_r=-0.8)
    result = run_scan(session, Horizon.SHORT_SWING, as_of=AS_OF, symbols=UNIVERSE)
    run = persist_scan(session, result)
    session.flush()

    stored = session.get(ScanRun, run.id)
    assert stored is not None
    assert stored.universe_size == len(UNIVERSE)
    assert stored.scanned_count == len(result.scanned)
    assert stored.candidate_count == 0
    rows = list(session.scalars(select(Candidate).where(Candidate.scan_run_id == run.id)))
    assert len(rows) == len(result.candidates)
    assert all(r.quality_gate_status is QualityGate.NO_TRADE for r in rows)


@pytest.mark.safety
def test_s10_probability_never_shown_without_calibration(session: Session) -> None:
    _seed(session, oos_expectancy_r=-0.8)
    result = run_scan(session, Horizon.SHORT_SWING, as_of=AS_OF, symbols=UNIVERSE)
    for c in result.candidates:
        assert c.probability_calibrated is None
        assert c.calibration_ref is None
    assert probability_display(0.62, None) is None
    assert probability_display(None, "ref") is None
    assert probability_display(0.62, "reports/x.md") == "62%"
