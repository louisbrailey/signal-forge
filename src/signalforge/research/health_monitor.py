"""Strategy-health monitor (ARCHITECTURE.md §5.3, Phase 2).

Compares each strategy version's rolling *live-paper* expectancy against its
out-of-sample backtest expectancy. A material, statistically meaningful shortfall
auto-downgrades ``paper_approved`` -> ``experimental``; a severe shortfall on an
already-experimental strategy -> ``disabled``.

The rules live in ``HealthMonitorConfig`` (version-controlled, folded into
``config_hash``, shown in Strategy Lab). Every transition writes a
``strategy_health`` row, an ``audit_log`` row, and a JSONL audit line.

Deterministic: no RNG, no LLM, no network.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from signalforge import audit
from signalforge.config.research import HealthMonitorConfig
from signalforge.db.models import (
    AuditLog,
    BacktestMetric,
    BacktestRun,
    PaperPosition,
    Strategy,
    StrategyHealth,
    StrategyVersion,
)
from signalforge.db.types import utcnow
from signalforge.domain import StrategyStatus
from signalforge.observability import get_logger

_log = get_logger("health_monitor")

_NO_ACTION = "none"


@dataclass(frozen=True, slots=True)
class HealthAssessment:
    strategy: str
    version: str
    window_label: str
    n_paper_trades: int
    paper_expectancy_r: float
    backtest_expectancy_r: float
    z_score: float
    action: str  # none | downgrade | disable | insufficient_data | no_backtest | disabled
    from_status: str
    to_status: str


def _paper_returns_r(session: Session, strategy_version_id: int) -> list[float]:
    """R-multiples of every closed paper position for this strategy version.

    R = realized P&L / initial dollar risk (entry-to-stop distance * shares).
    ``realized_pnl`` is already signed for the position's side, so a winning
    long and a winning short both yield a positive R.
    """
    positions = session.scalars(
        select(PaperPosition).where(
            PaperPosition.strategy_version_id == strategy_version_id,
            PaperPosition.closed_at.is_not(None),
        )
    )
    out: list[float] = []
    for p in positions:
        if p.stop_level is None:
            continue
        per_share_risk = abs(float(p.avg_price) - p.stop_level)
        risk_dollars = per_share_risk * p.qty
        if risk_dollars <= 0:
            continue
        out.append(float(p.realized_pnl) / risk_dollars)
    return out


def _latest_oos_expectancy(session: Session, strategy_version_id: int) -> float | None:
    metric = session.scalar(
        select(BacktestMetric)
        .join(BacktestRun, BacktestMetric.run_id == BacktestRun.id)
        .where(
            BacktestRun.strategy_version_id == strategy_version_id,
            BacktestMetric.phase == "out_of_sample",
            BacktestMetric.segment == "all",
        )
        .order_by(BacktestRun.created_at.desc(), BacktestMetric.id.desc())
        .limit(1)
    )
    if metric is None:
        return None
    value = metric.metrics_json.get("expectancy_r")
    return float(value) if value is not None else None


def _decide(
    status: StrategyStatus, z: float, paper_exp: float, cfg: HealthMonitorConfig
) -> tuple[StrategyStatus, str]:
    """Return the (possibly unchanged) status and the action label.

    Both transitions also require paper expectancy to be outright negative, so a
    still-profitable strategy that merely trails a rich backtest is left alone.
    """
    if paper_exp >= 0 or z > cfg.downgrade_z:
        return status, _NO_ACTION
    if status is StrategyStatus.PAPER_APPROVED:
        return StrategyStatus.EXPERIMENTAL, "downgrade"
    if status is StrategyStatus.EXPERIMENTAL and z <= cfg.disable_z:
        return StrategyStatus.DISABLED, "disable"
    return status, _NO_ACTION


def _resolve_config(session: Session, config: HealthMonitorConfig | None) -> HealthMonitorConfig:
    if config is not None:
        return config
    from signalforge.settings_store import effective_research_config

    return effective_research_config(session).health_monitor


def evaluate_strategy_health(
    session: Session, *, config: HealthMonitorConfig | None = None
) -> list[HealthAssessment]:
    """Assess every strategy version; apply and record any status transitions."""
    cfg = _resolve_config(session, config)
    assessments: list[HealthAssessment] = []
    if not cfg.enabled:
        return assessments

    rows = session.execute(
        select(StrategyVersion, Strategy).join(Strategy, StrategyVersion.strategy_id == Strategy.id)
    ).all()

    for ver, strat in rows:
        from_status = strat.status.value
        if strat.status is StrategyStatus.DISABLED:
            assessments.append(
                HealthAssessment(
                    strat.name,
                    ver.version,
                    "n/a",
                    0,
                    0.0,
                    0.0,
                    0.0,
                    "disabled",
                    from_status,
                    from_status,
                )
            )
            continue

        returns = _paper_returns_r(session, ver.id)
        n = len(returns)
        window = f"last_{n}_paper_trades"

        if n < cfg.min_paper_trades:
            assessments.append(
                HealthAssessment(
                    strat.name,
                    ver.version,
                    window,
                    n,
                    0.0,
                    0.0,
                    0.0,
                    "insufficient_data",
                    from_status,
                    from_status,
                )
            )
            continue

        bt_exp = _latest_oos_expectancy(session, ver.id)
        paper_exp = sum(returns) / n
        if bt_exp is None:
            assessments.append(
                HealthAssessment(
                    strat.name,
                    ver.version,
                    window,
                    n,
                    round(paper_exp, 4),
                    0.0,
                    0.0,
                    "no_backtest",
                    from_status,
                    from_status,
                )
            )
            continue

        variance = sum((r - paper_exp) ** 2 for r in returns) / n
        std_err = math.sqrt(variance / n) or 1e-9
        z = (paper_exp - bt_exp) / std_err

        new_status, action = _decide(strat.status, z, paper_exp, cfg)
        note = f"paper {paper_exp:+.3f}R vs backtest {bt_exp:+.3f}R over {n} trades (z={z:+.2f})"

        if action != _NO_ACTION:
            strat.status = new_status
            ver.status = new_status
            session.flush()
            session.add(
                AuditLog(
                    ts=utcnow(),
                    actor="health_monitor",
                    action=f"strategy.{action}",
                    entity=f"{strat.name}@{ver.version}",
                    before_json={"status": from_status},
                    after_json={
                        "status": new_status.value,
                        "z_score": round(z, 3),
                        "paper_expectancy_r": round(paper_exp, 4),
                        "backtest_expectancy_r": round(bt_exp, 4),
                        "n_paper_trades": n,
                        "rule": f"z<={cfg.downgrade_z} (downgrade) / z<={cfg.disable_z} (disable)",
                    },
                )
            )
            audit.record(
                f"strategy.{action}",
                actor="health_monitor",
                entity=f"{strat.name}@{ver.version}",
                before=from_status,
                after=new_status.value,
                z_score=round(z, 3),
                n_paper_trades=n,
            )
            _log.warning(
                "health.transition",
                strategy=strat.name,
                version=ver.version,
                action=action,
                z=round(z, 2),
                paper_exp=round(paper_exp, 3),
                bt_exp=round(bt_exp, 3),
            )

        session.add(
            StrategyHealth(
                strategy_version_id=ver.id,
                window_label=window,
                paper_expectancy=paper_exp,
                backtest_expectancy=bt_exp,
                z_score=z,
                action=action,
                note=note,
                evaluated_at=utcnow(),
            )
        )
        session.flush()
        assessments.append(
            HealthAssessment(
                strategy=strat.name,
                version=ver.version,
                window_label=window,
                n_paper_trades=n,
                paper_expectancy_r=round(paper_exp, 4),
                backtest_expectancy_r=round(bt_exp, 4),
                z_score=round(z, 3),
                action=action,
                from_status=from_status,
                to_status=strat.status.value,
            )
        )
    return assessments


def run_health_monitor(
    session: Session, *, config: HealthMonitorConfig | None = None
) -> list[HealthAssessment]:
    """Scheduler entry point: assess health and log a one-line cycle summary."""
    result = evaluate_strategy_health(session, config=config)
    _log.info(
        "health.cycle",
        assessed=len(result),
        transitions=sum(1 for a in result if a.action in ("downgrade", "disable")),
    )
    return result


def latest_health_by_strategy(session: Session) -> dict[str, StrategyHealth]:
    """Most recent StrategyHealth row per strategy name (for Strategy Lab)."""
    rows = session.execute(
        select(Strategy.name, StrategyHealth)
        .join(StrategyVersion, StrategyHealth.strategy_version_id == StrategyVersion.id)
        .join(Strategy, StrategyVersion.strategy_id == Strategy.id)
        .order_by(StrategyHealth.evaluated_at.desc(), StrategyHealth.id.desc())
    ).all()
    out: dict[str, StrategyHealth] = {}
    for name, health in rows:
        out.setdefault(name, health)
    return out
