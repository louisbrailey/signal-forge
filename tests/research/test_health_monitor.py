"""Strategy-health monitor: configurable, auditable downgrade/disable rules."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from signalforge.config.research import HealthMonitorConfig
from signalforge.db.models import (
    AuditLog,
    BacktestMetric,
    BacktestRun,
    Instrument,
    PaperAccount,
    PaperPosition,
    Strategy,
    StrategyHealth,
)
from signalforge.domain import Horizon, PositionSide, StrategyStatus
from signalforge.research.health_monitor import evaluate_strategy_health
from signalforge.research.persistence import upsert_strategy_version
from signalforge.research.strategies import default_strategies

STRAT = next(s for s in default_strategies() if s.spec().name.startswith("trend"))


def _seed(
    session: Session,
    *,
    status: StrategyStatus,
    oos_expectancy_r: float,
    paper_returns_r: list[float],
) -> Strategy:
    acct = PaperAccount(name="default", initial_cash=Decimal("10000"), cash=Decimal("10000"))
    inst = Instrument(symbol="AAA", instrument_type="stock")
    session.add_all([acct, inst])
    session.flush()

    ver = upsert_strategy_version(session, STRAT.spec())
    strat = session.get(Strategy, ver.strategy_id)
    assert strat is not None
    strat.status = status
    ver.status = status
    session.flush()

    run = BacktestRun(
        strategy_version_id=ver.id,
        params_json={},
        date_start=datetime(2023, 1, 1, tzinfo=UTC).date(),
        date_end=datetime(2024, 1, 1, tzinfo=UTC).date(),
        config_hash="test",
    )
    session.add(run)
    session.flush()
    session.add(
        BacktestMetric(
            run_id=run.id,
            segment="all",
            phase="out_of_sample",
            metrics_json={"expectancy_r": oos_expectancy_r, "n_trades": 200},
        )
    )
    session.flush()

    # Each closed position: entry 100, stop 98 -> $2/share risk, 10 shares -> $20 risk.
    opened = datetime(2024, 1, 2, tzinfo=UTC)
    for i, r in enumerate(paper_returns_r):
        session.add(
            PaperPosition(
                account_id=acct.id,
                instrument_id=inst.id,
                strategy_version_id=ver.id,
                horizon=Horizon.SHORT_SWING,
                side=PositionSide.LONG,
                qty=10,
                avg_price=Decimal("100"),
                stop_level=98.0,
                opened_at=opened + timedelta(days=i),
                closed_at=opened + timedelta(days=i, hours=6),
                realized_pnl=Decimal(str(round(r * 20.0, 2))),
            )
        )
    session.flush()
    return strat


def test_downgrades_paper_approved_on_a_sustained_shortfall(session: Session) -> None:
    strat = _seed(
        session,
        status=StrategyStatus.PAPER_APPROVED,
        oos_expectancy_r=0.30,
        paper_returns_r=[-0.4, -0.6] * 12 + [-0.5],  # 25 trades, mean -0.5R
    )
    out = evaluate_strategy_health(session)

    assessed = next(a for a in out if a.strategy == strat.name)
    assert assessed.action == "downgrade"
    assert assessed.from_status == "paper_approved"
    assert assessed.to_status == "experimental"
    assert strat.status is StrategyStatus.EXPERIMENTAL

    # A strategy_health row and an audit_log row are written.
    assert session.scalar(select(func.count()).select_from(StrategyHealth)) == 1
    log = session.scalar(select(AuditLog).where(AuditLog.action == "strategy.downgrade"))
    assert log is not None
    assert log.before_json == {"status": "paper_approved"}
    assert log.after_json["status"] == "experimental"
    assert log.after_json["n_paper_trades"] == 25


def test_disables_an_experimental_strategy_on_a_severe_shortfall(session: Session) -> None:
    strat = _seed(
        session,
        status=StrategyStatus.EXPERIMENTAL,
        oos_expectancy_r=0.30,
        paper_returns_r=[-0.45, -0.55] * 12 + [-0.5],
    )
    out = evaluate_strategy_health(session)
    assessed = next(a for a in out if a.strategy == strat.name)
    assert assessed.action == "disable"
    assert strat.status is StrategyStatus.DISABLED
    assert session.scalar(select(AuditLog).where(AuditLog.action == "strategy.disable")) is not None


def test_insufficient_closed_paper_trades_is_a_noop(session: Session) -> None:
    strat = _seed(
        session,
        status=StrategyStatus.PAPER_APPROVED,
        oos_expectancy_r=0.30,
        paper_returns_r=[-0.9] * 5,
    )
    out = evaluate_strategy_health(session)
    assessed = next(a for a in out if a.strategy == strat.name)
    assert assessed.action == "insufficient_data"
    assert strat.status is StrategyStatus.PAPER_APPROVED
    assert session.scalar(select(func.count()).select_from(StrategyHealth)) == 0


def test_min_paper_trades_threshold_is_configurable(session: Session) -> None:
    strat = _seed(
        session,
        status=StrategyStatus.PAPER_APPROVED,
        oos_expectancy_r=0.30,
        paper_returns_r=[-0.4, -0.6] * 12 + [-0.5],  # 25 trades
    )
    out = evaluate_strategy_health(session, config=HealthMonitorConfig(min_paper_trades=100))
    assert next(a for a in out if a.strategy == strat.name).action == "insufficient_data"
    assert strat.status is StrategyStatus.PAPER_APPROVED


def test_monitor_can_be_switched_off(session: Session) -> None:
    strat = _seed(
        session,
        status=StrategyStatus.PAPER_APPROVED,
        oos_expectancy_r=0.30,
        paper_returns_r=[-0.5] * 30,
    )
    out = evaluate_strategy_health(session, config=HealthMonitorConfig(enabled=False))
    assert out == []
    assert strat.status is StrategyStatus.PAPER_APPROVED


def test_a_still_profitable_strategy_below_its_backtest_is_left_alone(session: Session) -> None:
    strat = _seed(
        session,
        status=StrategyStatus.PAPER_APPROVED,
        oos_expectancy_r=0.50,
        paper_returns_r=[0.05, 0.15] * 12 + [0.1],  # mean +0.1R: below backtest but positive
    )
    out = evaluate_strategy_health(session)
    assessed = next(a for a in out if a.strategy == strat.name)
    assert assessed.action == "none"
    assert strat.status is StrategyStatus.PAPER_APPROVED
    # still recorded for the trend view
    assert session.scalar(select(func.count()).select_from(StrategyHealth)) == 1
