"""Scan accounting, quality gates, ranking, NO-TRADE as a first-class outcome."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from signalforge.data.adapters.base import FeedType
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


def _seed(
    session: Session,
    *,
    oos_expectancy_r: float,
    oos_trades: int = 200,
    regimes: tuple[str, ...] = ("bull/low", "bear/high"),
) -> None:
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
        for label in regimes:
            session.add(
                BacktestMetric(
                    run_id=run.id,
                    segment=label[:16],
                    phase="oos_by_regime",
                    metrics_json={
                        "regime_label": label,
                        "expectancy_r": oos_expectancy_r,
                        "n_trades": 40,
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


def test_oos_regime_coverage_helper_counts_distinct_regimes(session: Session) -> None:
    from signalforge.config.research import QualityThresholds
    from signalforge.research.scan import _oos_regime_coverage

    q = QualityThresholds()
    assert q.min_oos_regimes >= 2 and q.min_trades_per_regime >= 1

    ver = upsert_strategy_version(session, default_strategies()[0].spec())
    run = BacktestRun(
        strategy_version_id=ver.id,
        params_json={},
        date_start=AS_OF,
        date_end=AS_OF,
        config_hash="t",
    )
    session.add(run)
    session.flush()
    session.add_all(
        [
            BacktestMetric(
                run_id=run.id,
                segment="bull/low",
                phase="oos_by_regime",
                metrics_json={"regime_label": "bull/low", "n_trades": 40},
            ),
            BacktestMetric(
                run_id=run.id,
                segment="bear/high",
                phase="oos_by_regime",
                metrics_json={"regime_label": "bear/high", "n_trades": 5},  # below threshold
            ),
        ]
    )
    session.flush()

    # bull/high + bull/low would collapse to one trend; here bear/high is under
    # the per-regime trade floor, so only "bull" is covered.
    n, labels = _oos_regime_coverage(session, run.id, q.min_trades_per_regime)
    assert n == 1 and labels == ["bull"]
    n2, labels2 = _oos_regime_coverage(session, run.id, 1)
    assert n2 == 2 and labels2 == ["bear", "bull"]


def test_intraday_scan_without_an_intraday_feed_is_stale(session: Session) -> None:
    # Only daily bars are seeded — the BAR_INTRADAY feed has never succeeded, so
    # the INTRADAY freshness gate fails: every symbol excluded, live alerts off.
    _seed(session, oos_expectancy_r=0.3)
    result = run_scan(session, Horizon.INTRADAY, as_of=AS_OF, symbols=UNIVERSE)
    assert result.scanned == []
    assert result.live_alerts_enabled is False
    assert set(result.excluded.get("stale_or_unavailable_feed", [])) == set(UNIVERSE)


def test_intraday_scan_runs_end_to_end_with_intraday_bars(session: Session) -> None:
    from datetime import UTC, datetime, timedelta

    from signalforge.data.adapters.fixture import FixtureMarketDataAdapter
    from signalforge.data.ingest import ingest_intraday_universe
    from signalforge.db.models import DataFeedStatus
    from signalforge.db.types import utcnow

    _seed(session, oos_expectancy_r=-0.8)
    now = datetime(2024, 6, 28, 19, 0, tzinfo=UTC)
    ingest_intraday_universe(
        session,
        FixtureMarketDataAdapter(),
        UNIVERSE,
        now - timedelta(days=6),
        now,
        bar_size="15m",
    )
    # make the intraday feed look fresh relative to the scan's "now"
    for row in session.scalars(
        select(DataFeedStatus).where(DataFeedStatus.feed_type == FeedType.BAR_INTRADAY)
    ):
        row.last_success_at = utcnow()
    session.flush()

    result = run_scan(session, Horizon.INTRADAY, as_of=date(2024, 6, 28), symbols=UNIVERSE)
    assert result.live_alerts_enabled is True
    assert set(result.scanned) <= set(UNIVERSE) and result.scanned  # some were evaluated
    # NO TRADE candidates (negative OOS expectancy) or plain "no trigger" — both fine
    assert result.excluded_count + len(result.scanned) == len(UNIVERSE)


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

    # With no calibration, the canonical NO-TRADE line is shown verbatim.
    from signalforge.research.display import NO_TRADE_MESSAGE, confidence_note

    assert NO_TRADE_MESSAGE == "NO TRADE — insufficient evidence or poor risk/reward."
    assert NO_TRADE_MESSAGE in confidence_note(None)
    assert NO_TRADE_MESSAGE not in confidence_note("reports/x.md")
