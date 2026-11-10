"""Persist strategy versions and backtest results; read them back for the scanner."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import asdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from signalforge.db.models import (
    BacktestMetric,
    BacktestRun,
    DataSnapshot,
    Strategy,
    StrategyPromotionEvaluation,
    StrategyVersion,
)
from signalforge.research.backtest_runner import StrategyBacktestResult
from signalforge.research.registry import StrategySpec

# Fields excluded from spec_json_hash: git_sha changes on every commit to the
# repo (unrelated strategies included), so hashing it would falsely invalidate
# an approval scope on any unrelated commit; status/notes carry no executable
# meaning. Every OTHER field (rule_definition, feature_definitions,
# entry/exit/stop logic, time_stop, ...) embeds the strategy's live numeric
# parameters via string interpolation (see e.g. TrendContinuation.spec()), so
# hashing them genuinely detects a parameter change even when the version
# string wasn't bumped.
_HASH_EXCLUDED_SPEC_FIELDS = frozenset({"git_sha", "status", "notes"})


def spec_json_hash(spec: StrategySpec) -> str:
    """sha256 of a strategy spec's parameter-bearing fields — used to detect
    whether a strategy's actual behavior has drifted since it was approved,
    independent of the repo-wide git_sha and independent of whether its
    `version` string was bumped (see research.promotion.approval_scope)."""
    payload = {
        k: (list(v) if isinstance(v, tuple) else v)
        for k, v in asdict(spec).items()
        if k not in _HASH_EXCLUDED_SPEC_FIELDS
    }
    canonical = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


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
    *,
    provenance: Mapping[str, Any] | None = None,
) -> BacktestRun:
    """Persist one backtest as a ``BacktestRun`` plus its metric rows.

    ``provenance`` is merged into ``params_json`` beside the symbol list so a
    run recorded for a specific purpose (e.g. the development-window OOS
    backtest of ``research.promotion.record_development_oos_backtest``) states
    which dataset snapshot and window it measured. It never overrides
    ``symbols``, measured data provenance, or the executable spec hash.

    Legacy runs remain untouched. Missing provenance on an old row means
    unknown, never evidence that its inputs were real."""
    strategy = session.get(Strategy, version.strategy_id)
    if (
        strategy is None
        or strategy.name != result.spec.name
        or version.version != result.spec.version
    ):
        raise ValueError("Backtest result does not match the strategy version being recorded")
    run = BacktestRun(
        strategy_version_id=version.id,
        params_json={
            **dict(provenance or {}),
            "symbols": result.symbols,
            "spec_json_hash": spec_json_hash(result.spec),
            "data_provenance": {
                "schema_version": 1,
                "sources": list(result.data.sources),
                "simulated": result.data.simulated,
                "bars": result.data.bars,
                "first": result.data.first.isoformat() if result.data.first else None,
                "last": result.data.last.isoformat() if result.data.last else None,
            },
        },
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


def oos_provenance_failures(params: object) -> list[str]:
    """Explicitly forced/non-reproducing evidence cannot qualify a candidate.

    Recording an exploratory result is separate from using it as evaluated OOS
    evidence. Missing legacy provenance stays unknown; it is not reconstructed
    or labelled reproduced. No saved metrics, flags or strategy status change.
    """
    if not isinstance(params, dict):
        return []
    reasons = []
    allowed = params.get("allow_mismatch")
    if allowed is True:
        reasons.append("allow_mismatch=true")
    elif allowed is not None and allowed is not False:
        reasons.append("invalid allow_mismatch flag")
    mismatched = params.get("mismatched_inputs")
    if isinstance(mismatched, list) and mismatched:
        names = ", ".join(str(name) for name in mismatched)
        reasons.append(f"mismatched_inputs: {names}")
    elif mismatched is not None and not isinstance(mismatched, list):
        reasons.append("invalid mismatched_inputs metadata")
    reproduces = params.get("reproduces_evaluation")
    if isinstance(reproduces, dict):
        failed = sorted(str(key) for key, value in reproduces.items() if value is False)
        if failed:
            reasons.append(f"reproduces_evaluation=false: {', '.join(failed)}")
    if not reasons:
        return []
    return [
        f"OOS provenance mismatch ({'; '.join(reasons)}); "
        "not eligible candidate evidence for the evaluated inputs"
    ]


def latest_oos_metric(session: Session, spec: StrategySpec) -> BacktestMetric | None:
    """Most recent OOS 'all' metric for this strategy+version, including forced
    runs. Consumers must check provenance; never fall back to an older good run."""
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


def oos_scope_failures(
    session: Session,
    metric: BacktestMetric | None,
    spec: StrategySpec,
    *,
    config_hash: str,
    dataset_snapshot_id: int | None,
    source: str,
    symbols: object,
) -> list[str]:
    """Validate the ACTUAL latest row against actual scan scope, never select
    another row. SELECT-only even with a caller's pending ORM changes.

    Scope membership uses sets; the saved record separately retains its linked
    evaluation's exact bootstrap/input order. Unknown legacy scope is ineligible.
    """
    from signalforge.research.approval_scope import ApprovedScope, scan_scope_matches

    def refuse(reason: str) -> list[str]:
        return [f"OOS scope mismatch: {reason}"]

    def symbol_list(value: object) -> list[str] | None:
        if not isinstance(value, (list, tuple, set, frozenset)) or not value:
            return None
        if not all(isinstance(s, str) and s and s == s.strip() for s in value):
            return None
        return [s.upper() for s in value]

    def positive_id(value: object) -> bool:
        return isinstance(value, int) and not isinstance(value, bool) and value > 0

    with session.no_autoflush:
        if metric is None or metric.run is None:
            return refuse("no recorded run")
        run = metric.run
        params = run.params_json
        if not isinstance(params, dict):
            return refuse("saved provenance missing or malformed")
        if failures := oos_provenance_failures(params):
            return failures
        if "allow_mismatch" in params and params["allow_mismatch"] is not False:
            return refuse("override flag must be absent or literally False")
        if "mismatched_inputs" in params and (
            not isinstance(params["mismatched_inputs"], list) or params["mismatched_inputs"]
        ):
            return refuse("mismatched_inputs must be absent or an empty list")
        flags = params.get("reproduces_evaluation")
        required = {"symbols", "window_start", "until", "source", "config_hash"}
        if (
            not isinstance(flags, dict)
            or set(flags) != required
            or not all(v is True for v in flags.values())
        ):
            return refuse("complete five literal-True reproduction flags required")
        if not config_hash or run.config_hash != config_hash:
            return refuse("saved run config_hash does not match actual scan config")
        if not positive_id(dataset_snapshot_id) or not isinstance(source, str) or not source:
            return refuse("actual scan dataset/source identity is missing")
        scan_symbols = symbol_list(symbols)
        saved_symbols = symbol_list(params.get("symbols"))
        if scan_symbols is None or saved_symbols is None:
            return refuse("scan or saved universe is missing or malformed")
        if params.get("purpose") != "development_oos":
            return refuse("saved purpose is not development_oos")
        saved_snapshot = params.get("dataset_snapshot")
        if (
            not isinstance(saved_snapshot, dict)
            or not positive_id(saved_snapshot.get("id"))
            or saved_snapshot["id"] != dataset_snapshot_id
            or not isinstance(saved_snapshot.get("key"), str)
            or not saved_snapshot["key"]
        ):
            return refuse("saved dataset identity does not match actual scan dataset")
        saved_source = params.get("source")
        source_values = [saved_source] if isinstance(saved_source, str) else saved_source
        if (
            not isinstance(source_values, (list, tuple))
            or not source_values
            or not all(isinstance(s, str) and s for s in source_values)
        ):
            return refuse("saved source is missing or malformed")
        if set(source_values) != {source} or set(saved_symbols) != set(scan_symbols):
            return refuse("saved source/universe does not match actual scan scope")
        data = params.get("data_provenance")
        if isinstance(data, dict) and "sources" in data:
            measured_sources = data["sources"]
            if (
                not isinstance(measured_sources, list)
                or not all(isinstance(s, str) for s in measured_sources)
                or set(measured_sources) != {source}
            ):
                return refuse("measured input source contradicts saved scan scope")
        executable_hash = spec_json_hash(spec)
        if params.get("spec_json_hash") != executable_hash:
            return refuse("saved executable spec hash differs from current strategy")
        identity = session.execute(
            select(Strategy.name, StrategyVersion.version)
            .join(StrategyVersion, StrategyVersion.strategy_id == Strategy.id)
            .where(StrategyVersion.id == run.strategy_version_id)
        ).one_or_none()
        if identity is None or tuple(identity) != (spec.name, spec.version):
            return refuse("run belongs to a different strategy/version")
        evaluation_id = params.get("promotion_evaluation_id")
        if not positive_id(evaluation_id):
            return refuse("linked evaluation identity is missing or malformed")
        e = StrategyPromotionEvaluation
        row = session.execute(
            select(
                e.id,
                e.strategy_version_id,
                e.dataset_snapshot_id,
                e.passed,
                e.config_hash,
                e.spec_json_hash,
                e.universe_json,
                e.data_provenance_json,
                DataSnapshot.key,
                DataSnapshot.symbols_json.label("snapshot_symbols"),
            )
            .join(DataSnapshot, DataSnapshot.id == e.dataset_snapshot_id)
            .where(e.id == evaluation_id)
        ).one_or_none()
        if (
            row is None
            or row.strategy_version_id != run.strategy_version_id
            or row.passed is not True
        ):
            return refuse("linked evaluation is not a passing approval for this version")
        approved_symbols = symbol_list(row.universe_json)
        approved_data = row.data_provenance_json
        approved_sources = approved_data.get("sources") if isinstance(approved_data, dict) else None
        if (
            approved_symbols is None
            or not isinstance(approved_sources, list)
            or not approved_sources
            or not all(isinstance(s, str) and s for s in approved_sources)
        ):
            return refuse("linked approved scope is missing or malformed")
        snapshot_symbols = symbol_list(row.snapshot_symbols)
        if snapshot_symbols is None or set(snapshot_symbols) != set(scan_symbols):
            return refuse("dataset snapshot universe differs from actual scan scope")
        if row.key != saved_snapshot["key"] or saved_symbols != approved_symbols:
            return refuse("saved dataset key/input order differs from linked evaluation")
        scope = ApprovedScope(
            row.id,
            row.dataset_snapshot_id,
            row.config_hash,
            row.spec_json_hash,
            frozenset(approved_symbols),
            frozenset(approved_sources),
        )
        if not scan_scope_matches(
            [scope],
            dataset_snapshot_id=dataset_snapshot_id,
            config_hash=config_hash,
            spec_json_hash=executable_hash,
            source=source,
            universe=frozenset(scan_symbols),
        ):
            return refuse("latest evidence and linked approval do not bind to actual scan scope")
        return []
