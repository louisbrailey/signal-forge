"""Persist strategy versions and backtest results; read them back for the scanner."""

from __future__ import annotations

from dataclasses import asdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from signalforge.db.models import (
    BacktestMetric,
    BacktestRun,
    Strategy,
    StrategyVersion,
)
from signalforge.research.backtest_runner import StrategyBacktestResult
from signalforge.research.registry import StrategySpec


def upsert_strategy_version(session: Session, spec: StrategySpec) -> StrategyVersion:
    """Register (or refresh the spec of) a strategy version.

    ``status`` is **never** taken from ``spec.status`` — new rows get the ORM
    model's own default (``EXPERIMENTAL``), and an existing row's status is
    never touched here at all. Two reasons: (1) this function runs on every
    scan and every backtest report, and if it also overwrote status on an
    existing row it would silently reset a version ``research.promotion`` had
    just approved (or the health monitor had just downgraded) the next time a
    scan happened to run, desynchronising ``StrategyVersion.status`` from
    ``Strategy.status``; (2) ``spec`` is produced by a strategy class's own
    ``.spec()`` method — trusting its ``status`` field even on first creation
    would let a strategy author (or a copy-pasted spec) set
    ``PAPER_APPROVED`` directly, bypassing the pipeline entirely. Status
    transitions are the exclusive responsibility of ``research.promotion``
    (promote), ``research.health_monitor`` (downgrade/disable), and the
    dashboard's downgrade-only manual action.
    """
    strat = session.scalar(select(Strategy).where(Strategy.name == spec.name))
    if strat is None:
        strat = Strategy(
            name=spec.name,
            horizon=spec.horizon,
            permits_long=spec.permits_long,
            permits_short=spec.permits_short,
        )
        session.add(strat)
        session.flush()

    ver = session.scalar(
        select(StrategyVersion).where(
            StrategyVersion.strategy_id == strat.id, StrategyVersion.version == spec.version
        )
    )
    spec_json = {k: (list(v) if isinstance(v, tuple) else v) for k, v in asdict(spec).items()}
    if ver is None:
        ver = StrategyVersion(
            strategy_id=strat.id,
            version=spec.version,
            git_sha=spec.git_sha,
            spec_json=spec_json,
        )
        session.add(ver)
        session.flush()
    else:
        ver.git_sha = spec.git_sha
        ver.spec_json = spec_json
    return ver


def persist_backtest_result(
    session: Session,
    version: StrategyVersion,
    result: StrategyBacktestResult,
) -> BacktestRun:
    run = BacktestRun(
        strategy_version_id=version.id,
        params_json={"symbols": result.symbols},
        date_start=result.start,
        date_end=result.end,
        oos_start=result.start,  # coarse; IS/OOS split is by fraction in the runner
        oos_end=result.end,
        costs_json=dict(result.costs),
        config_hash=result.config_hash,
        git_sha=version.git_sha,
    )
    session.add(run)
    session.flush()

    session.add(
        BacktestMetric(
            run_id=run.id,
            segment="all",
            phase="in_sample",
            metrics_json=result.in_sample.to_dict(),
        )
    )
    session.add(
        BacktestMetric(
            run_id=run.id,
            segment="all",
            phase="out_of_sample",
            metrics_json=result.out_of_sample.to_dict(),
            ci_json=result.oos_ci,
        )
    )
    for label, metrics in result.by_regime.items():
        # Regime labels (e.g. "bull/high") are the unique segment key here; the
        # distinct phase keeps them out of the (run_id, "all", "out_of_sample") row.
        session.add(
            BacktestMetric(
                run_id=run.id,
                segment=label[:16],
                phase="oos_by_regime",
                metrics_json={"regime_label": label, **metrics.to_dict()},
            )
        )
    return run


def latest_oos_metric(session: Session, spec: StrategySpec) -> BacktestMetric | None:
    """Most recent out-of-sample 'all' metric row for this strategy+version."""
    return session.scalar(
        select(BacktestMetric)
        .join(BacktestRun, BacktestMetric.run_id == BacktestRun.id)
        .join(StrategyVersion, BacktestRun.strategy_version_id == StrategyVersion.id)
        .join(Strategy, StrategyVersion.strategy_id == Strategy.id)
        .where(
            Strategy.name == spec.name,
            StrategyVersion.version == spec.version,
            BacktestMetric.phase == "out_of_sample",
            BacktestMetric.segment == "all",
        )
        .order_by(BacktestRun.created_at.desc(), BacktestMetric.id.desc())
        .limit(1)
    )
