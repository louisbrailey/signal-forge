"""Paper Probation: the live-paper evidence view for every PAPER_APPROVED
strategy — its approved scope, its sealed/walk-forward evidence, and how its
REAL paper trades compare to what the promotion pipeline expected.

Read-only. Never writes a status, never places anything — the same
downgrade/disable rules already enforced by ``research.health_monitor`` are
only *reported* here, not duplicated.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from signalforge.db.models import (
    PaperPosition,
    Strategy,
    StrategySealedTest,
    StrategyVersion,
)
from signalforge.domain import StrategyStatus
from signalforge.research.approval_scope import approved_scopes
from signalforge.research.health_monitor import _latest_oos_expectancy, latest_health_by_strategy


@dataclass(slots=True)
class PaperTradeSummary:
    n_trades: int
    start_date: str | None
    realized_expectancy_r: float | None
    max_drawdown_pct: float | None
    equity_multiple: float | None


def _paper_trade_summary(
    session: Session, strategy_version_id: int, *, risk_fraction: float = 0.005
) -> PaperTradeSummary:
    """A simple, honest sequential R-multiple equity curve from this
    strategy's own closed paper positions — deliberately NOT routed through
    ``research.portfolio_metrics.compute_portfolio_metrics`` (built for
    ``SimTrade`` objects from a backtest, with fields — MAE/MFE, cost bps —
    a real paper position doesn't carry; fabricating them would be more
    misleading than a smaller, directly-honest computation here)."""
    positions = list(
        session.scalars(
            select(PaperPosition)
            .where(
                PaperPosition.strategy_version_id == strategy_version_id,
                PaperPosition.closed_at.is_not(None),
            )
            .order_by(PaperPosition.closed_at)
        )
    )
    r_values: list[float] = []
    first_date: datetime | None = None
    for p in positions:
        if p.stop_level is None:
            continue
        per_share_risk = abs(float(p.avg_price) - p.stop_level)
        risk_dollars = per_share_risk * p.qty
        if risk_dollars <= 0:
            continue
        r_values.append(float(p.realized_pnl) / risk_dollars)
        if first_date is None:
            first_date = p.opened_at

    if not r_values:
        return PaperTradeSummary(0, None, None, None, None)

    equity = 1.0
    peak = 1.0
    max_dd = 0.0
    for r in r_values:
        equity *= 1 + r * risk_fraction
        peak = max(peak, equity)
        max_dd = max(max_dd, (peak - equity) / peak if peak > 0 else 0.0)

    return PaperTradeSummary(
        n_trades=len(r_values),
        start_date=first_date.date().isoformat() if first_date else None,
        realized_expectancy_r=round(sum(r_values) / len(r_values), 4),
        max_drawdown_pct=round(max_dd * 100, 2),
        equity_multiple=round(equity, 4),
    )


def paper_probation_context(session: Session) -> dict[str, Any]:
    """Everything the Paper Probation dashboard page needs: one entry per
    PAPER_APPROVED strategy version."""
    health_by_name = latest_health_by_strategy(session)
    rows: list[dict[str, Any]] = []

    approved = session.execute(
        select(Strategy, StrategyVersion)
        .join(StrategyVersion, StrategyVersion.strategy_id == Strategy.id)
        .where(
            Strategy.status == StrategyStatus.PAPER_APPROVED,
            StrategyVersion.status == StrategyStatus.PAPER_APPROVED,
        )
    ).all()

    for strat, ver in approved:
        scopes = approved_scopes(session, ver.id)
        # StrategySealedTest is unique per (strategy_version_id,
        # dataset_snapshot_id) -- a version can carry more than one sealed
        # test (one per dataset it was ever evaluated against). Show the one
        # belonging to this strategy's actual approved scope, not an
        # arbitrary/unrelated one from a different dataset.
        sealed = None
        if scopes:
            sealed = session.scalar(
                select(StrategySealedTest).where(
                    StrategySealedTest.strategy_version_id == ver.id,
                    StrategySealedTest.dataset_snapshot_id == scopes[0].dataset_snapshot_id,
                )
            )
        oos_expectancy = _latest_oos_expectancy(session, ver.id)
        paper = _paper_trade_summary(session, ver.id)
        health = health_by_name.get(strat.name)

        shortfall = None
        if paper.realized_expectancy_r is not None and oos_expectancy is not None:
            shortfall = round(paper.realized_expectancy_r - oos_expectancy, 4)

        rows.append(
            {
                "strategy_key": strat.name,
                "version": ver.version,
                "horizon": strat.horizon.value,
                "strategy_version_id": ver.id,
                "approved_scopes": [
                    {
                        "evaluation_id": s.evaluation_id,
                        "dataset_snapshot_id": s.dataset_snapshot_id,
                        "config_hash": s.config_hash,
                        "spec_json_hash": s.spec_json_hash,
                        "sources": sorted(s.sources),
                        "universe_size": len(s.universe),
                        "universe": sorted(s.universe),
                    }
                    for s in scopes
                ],
                "sealed_test": (
                    {
                        "window": f"{sealed.window_start}..{sealed.window_end}",
                        "n_trades": sealed.metrics_json.get("n_trades"),
                        "expectancy_r": sealed.metrics_json.get("expectancy_r"),
                        "passed": sealed.passed,
                        "detail": sealed.detail,
                    }
                    if sealed is not None
                    else None
                ),
                "expected_oos_expectancy_r": oos_expectancy,
                "paper": {
                    "n_trades": paper.n_trades,
                    "start_date": paper.start_date,
                    "realized_expectancy_r": paper.realized_expectancy_r,
                    "max_drawdown_pct": paper.max_drawdown_pct,
                    "equity_multiple": paper.equity_multiple,
                    "shortfall_vs_expected_r": shortfall,
                },
                "health": (
                    {
                        "window_label": health.window_label,
                        "z_score": health.z_score,
                        "action": health.action,
                        "note": health.note,
                        "evaluated_at": health.evaluated_at.isoformat(),
                    }
                    if health is not None
                    else None
                ),
            }
        )

    return {
        "strategies": rows,
        "generated_at": date.today().isoformat(),
    }
