"""Paper Probation: the live-paper evidence view for every PAPER_APPROVED
strategy — its approved scope, its sealed/walk-forward evidence, and how its
REAL paper trades compare to what the promotion pipeline expected.

Read-only. Never writes a status, never places anything — the same
downgrade/disable rules already enforced by ``research.health_monitor`` are
only *reported* here, not duplicated.

The options section (D3 §7.3) is read-only in the same sense and one degree
stronger: :func:`options_paper_status` touches ORM models and nothing else. It
deliberately does **not** import ``paper.options_ledger`` / ``options_marks`` /
``options_auto_simulate``, because ``signalforge.app`` imports this module and
contract S16 forbids the app layer from reaching the options paper decision path
— by any number of hops. A status panel is a reader; it must not drag the door
it reports on into the app's import graph.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from signalforge.db.models import (
    JobRun,
    OptionsPosition,
    OptionsReconcileReport,
    PaperAccount,
    PaperPosition,
    Strategy,
    StrategySealedTest,
    StrategyVersion,
)
from signalforge.db.types import utcnow
from signalforge.domain import StrategyStatus
from signalforge.research.approval_scope import approved_scopes
from signalforge.research.health_monitor import (
    _latest_oos_expectancy,
    closed_options_r_multiples,
    is_options_strategy_version,
    latest_health_by_strategy,
)
from signalforge.settings_store import effective_research_config, get_setting

#: The scheduled EOD chain's job name (``scheduler.OPTIONS_EOD_JOB``). Spelled
#: here rather than imported: ``signalforge.scheduler`` pulls in the agents,
#: alerts and briefing layers, and this module is on the app's import path.
OPTIONS_EOD_JOB_NAME = "options_paper_eod"

#: The second guard's own setting (``paper.options_ledger.OPTIONS_AUTO_SIM_*``),
#: spelled here for the same reason — reporting a switch must not import the door.
OPTIONS_AUTO_SIM_SETTING = "auto_simulate_options_enabled"
OPTIONS_AUTO_SIM_CAP_SETTING = "auto_simulate_options_max_per_day"


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


def options_paper_status(session: Session, *, as_of: date | None = None) -> dict[str, Any]:
    """The SIMULATED options paper book's operating state — READ-ONLY.

    Four facts, which are the four that decide whether the options branch could
    do anything at all (D3 §7.3):

    * **account** — the configured options account, or its absence. Absence is
      not an error here: it is the state of every deployment that has not opted
      in, and it is one of the two conditions the EOD chain returns early on.
    * **open structures** — how many, on which underlyings, and how much
      collateral they hold.
    * **reconciliation age** — the second guard's condition AA needs a dated,
      CLEAN ``options_reconcile_report`` for the fill session. A missing row
      refuses exactly as a divergent row refuses, so "none" and "stale" are
      reported as distinct facts, never collapsed into a warning.
    * **last EOD chain run** — whether ``options_paper_eod`` ran, when, and with
      what outcome. A clean reconciliation that is four days old means the chain
      is not running, which is precisely what a status page must show.

    Writes nothing, opens nothing, reconciles nothing.
    """
    on = as_of or date.today()
    cfg = effective_research_config(session)
    account_name = cfg.options_risk.paper_account_name
    acct = session.scalar(select(PaperAccount).where(PaperAccount.name == account_name))

    last_run = session.scalar(
        select(JobRun)
        .where(JobRun.name == OPTIONS_EOD_JOB_NAME)
        .order_by(JobRun.started_at.desc())
        .limit(1)
    )
    chain = {
        "job": OPTIONS_EOD_JOB_NAME,
        "enabled": bool(cfg.options.paper_eod_enabled),
        "setting_key": "research.options.paper_eod_enabled",
        "last_run_at": last_run.started_at.isoformat() if last_run else None,
        "last_run_status": last_run.status if last_run else None,
        "last_run_detail": (last_run.detail or "")[:200] if last_run else None,
        "hours_since_last_run": (
            round((utcnow() - last_run.started_at).total_seconds() / 3600, 1) if last_run else None
        ),
    }
    auto_sim = {
        "setting_key": OPTIONS_AUTO_SIM_SETTING,
        "enabled": get_setting(session, OPTIONS_AUTO_SIM_SETTING, False) is True,
        "max_per_day": get_setting(session, OPTIONS_AUTO_SIM_CAP_SETTING, 0),
    }
    if acct is None:
        return {
            "exists": False,
            "account": account_name,
            "as_of": on.isoformat(),
            "open_structures": [],
            "n_open": 0,
            "collateral_reserved": 0.0,
            "reconciliation": None,
            "eod_chain": chain,
            "auto_simulate": auto_sim,
            "notice": "SIMULATED options paper account — no order was ever placed.",
        }

    open_rows = list(
        session.scalars(
            select(OptionsPosition).where(
                OptionsPosition.account_id == acct.id, OptionsPosition.closed_at.is_(None)
            )
        )
    )
    n_closed = (
        session.scalar(
            select(OptionsPosition.id)
            .where(OptionsPosition.account_id == acct.id, OptionsPosition.closed_at.is_not(None))
            .limit(1)
        )
        is not None
    )
    report = session.scalar(
        select(OptionsReconcileReport)
        .where(OptionsReconcileReport.account_id == acct.id)
        .order_by(OptionsReconcileReport.as_of.desc(), OptionsReconcileReport.id.desc())
        .limit(1)
    )
    reconciliation = (
        None
        if report is None
        else {
            "as_of": report.as_of.isoformat(),
            "clean": bool(report.clean),
            "age_days": (on - report.as_of).days,
            "findings": [str(f.get("check")) for f in report.findings_json],
            "open_structures": report.open_structures,
        }
    )
    return {
        "exists": True,
        "account": acct.name,
        "as_of": on.isoformat(),
        "cash": float(acct.cash),
        "collateral_reserved": float(acct.collateral_reserved),
        "spendable_cash": float(acct.spendable_cash),
        "n_open": len(open_rows),
        "has_closed_structures": n_closed,
        "open_structures": [
            {
                "position_id": p.id,
                "underlying": p.underlying_symbol,
                "structure_type": p.structure_type,
                "contracts": p.contracts,
                "expiration": p.expiration_date.isoformat(),
                "dte": (p.expiration_date - on).days,
                "r_dollars": float(p.r_dollars),
                "collateral_reserved": float(p.collateral_reserved),
            }
            for p in open_rows
        ],
        "reconciliation": reconciliation,
        "eod_chain": chain,
        "auto_simulate": auto_sim,
        "notice": "SIMULATED options paper account — no order was ever placed.",
    }


def _options_version_summary(session: Session, strategy_version_id: int) -> dict[str, Any] | None:
    """The options half of ONE version's live evidence, or ``None`` for an
    equity family — asked through the health monitor's own explicit predicate so
    the two readers cannot drift apart on what "an options strategy" means."""
    if not is_options_strategy_version(session, strategy_version_id):
        return None
    series = closed_options_r_multiples(session, strategy_version_id)
    n_open = len(
        list(
            session.scalars(
                select(OptionsPosition.id).where(
                    OptionsPosition.strategy_version_id == strategy_version_id,
                    OptionsPosition.closed_at.is_(None),
                )
            )
        )
    )
    return {
        "n_closed_structures": series.n,
        "n_open_structures": n_open,
        "realized_expectancy_r": (
            round(sum(series.r_multiples) / series.n, 4) if series.n else None
        ),
        "clamped_at_minus_1r": series.clamped,
        "unclamped_min_r": series.unclamped_min,
    }


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
                # None for an equity family — the equity block above is
                # untouched either way (D3 §7.3).
                "options": _options_version_summary(session, ver.id),
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
        "options_paper": options_paper_status(session),
        "generated_at": date.today().isoformat(),
    }
