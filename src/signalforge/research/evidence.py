"""Read-only inventory of recorded evidence, separate from promotion decisions.

An old version, absent test, zero-trade run, and negative measured expectancy
are different outcomes. Positive expectancy alone is never an approval.
No backtest or sealed evaluation is run by this module.
"""

from __future__ import annotations

import math
from collections import Counter
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from signalforge.db.models import BacktestMetric, Strategy, StrategyVersion
from signalforge.research.persistence import (
    latest_oos_metric,
    oos_provenance_failures,
    spec_json_hash,
)
from signalforge.research.registry import StrategySpec
from signalforge.research.strategies import default_strategies

DISCLAIMER = "Research signal only — no order was placed."


def _finite(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def metric_evidence(metric: BacktestMetric | None, spec: StrategySpec) -> dict[str, Any]:
    """Display exactly the saved values without turning missing metrics into 0.

    Provenance is reported as unknown on legacy runs. It is deliberately not
    reconstructed from today's mutable bar tables or StrategyVersion.spec_json.
    """
    if metric is None:
        return {
            "state": "unrecorded",
            "label": "No recorded OOS backtest",
            "warnings": ["Missing evidence is not a measured loss or a zero return."],
            "run_id": None,
        }

    run = metric.run
    params = run.params_json or {}
    metrics = metric.metrics_json or {}
    n = _finite(metrics.get("n_trades"))
    expectancy = _finite(metrics.get("expectancy_r"))
    if n is None or n < 0 or not n.is_integer() or expectancy is None:
        state, label = "invalid_metrics", "Incomplete or invalid OOS metrics"
    elif n == 0:
        state, label = "no_trades", "Unevaluated: no OOS trades"
    elif expectancy > 0:
        state, label = "positive_point_estimate", "Positive OOS point estimate; validation separate"
    elif expectancy < 0:
        state, label = "negative_point_estimate", "Negative OOS point estimate"
    else:
        state, label = "zero_point_estimate", "Zero OOS point estimate"

    warnings = oos_provenance_failures(params)
    if warnings:
        state, label = "ambiguous_provenance", "Ambiguous OOS evidence: forced or mismatched inputs"
    raw_data = params.get("data_provenance")
    data = raw_data if isinstance(raw_data, dict) else {}
    sources = data.get("sources")
    source_label = (
        ", ".join(sources)
        if isinstance(sources, list) and sources and all(isinstance(s, str) for s in sources)
        else "unknown"
    )
    simulated = data.get("simulated")
    bars = _finite(data.get("bars"))
    data_kind = "unknown"
    if simulated is True:
        data_kind = "simulated"
        warnings.append("SIMULATED inputs cannot support a real-data performance claim.")
    elif simulated is False and bars is not None and bars > 0 and source_label != "unknown":
        data_kind = "real_recorded"
    else:
        warnings.append("Input provenance is unknown or empty; real-data status is unverified.")

    saved_hash = params.get("spec_json_hash")
    if saved_hash is None:
        warnings.append("Legacy run has no saved executable-spec hash.")
    elif saved_hash != spec_json_hash(spec):
        warnings.append("Saved executable-spec hash differs from the current rules.")

    raw_ci = (metric.ci_json or {}).get("expectancy_r")
    ci = raw_ci if isinstance(raw_ci, dict) else {}
    low, high = _finite(ci.get("low")), _finite(ci.get("high"))
    ci_valid = low is not None and high is not None and low <= high
    if not ci_valid:
        warnings.append("No valid saved expectancy confidence interval.")
    elif low is not None and low <= 0:
        warnings.append("Expectancy confidence interval includes zero or losses.")

    if not run.costs_json:
        warnings.append("Transaction-cost assumptions were not saved with this run.")

    return {
        "state": state,
        "label": label,
        "run_id": run.id,
        "recorded_at": run.created_at.isoformat(),
        "window_start": run.date_start.isoformat(),
        "window_end": run.date_end.isoformat(),
        "split": params.get("is_oos_split", "per-symbol chronological 60/40 split"),
        "n_trades": int(n) if n is not None and n >= 0 and n.is_integer() else None,
        "expectancy_r": expectancy,
        "profit_factor": _finite(metrics.get("profit_factor")),
        "max_drawdown_r": _finite(metrics.get("max_drawdown_r")),
        "ci_low": low if ci_valid else None,
        "ci_high": high if ci_valid else None,
        "source": source_label,
        "data_kind": data_kind,
        "data": data,
        "costs": run.costs_json or {},
        "warnings": warnings,
    }


def evidence_inventory(session: Session) -> dict[str, Any]:
    """Only registered CURRENT code versions count in current-strategy totals.

    Options/crypto families outside the equity baseline registry are listed as
    unlisted, not labelled retired or counted as failed equity strategies.
    """
    specs = [s.spec() for s in default_strategies()]
    names = {s.name for s in specs}
    active = {(s.name, s.version) for s in specs}
    rows = list(
        session.execute(
            select(Strategy.name, StrategyVersion.version, StrategyVersion.status)
            .join(StrategyVersion, StrategyVersion.strategy_id == Strategy.id)
            .order_by(Strategy.name, StrategyVersion.version)
        )
    )
    current = []
    for spec in specs:
        evidence = metric_evidence(latest_oos_metric(session, spec), spec)
        current.append(
            {"name": spec.name, "version": spec.version, "horizon": spec.horizon.value, **evidence}
        )
    return {
        "current": current,
        "counts": dict(Counter(row["state"] for row in current)),
        "current_strategy_count": len(current),
        "registered_version_count": len(rows),
        "superseded": [
            {"name": name, "version": version, "status": status.value}
            for name, version, status in rows
            if name in names and (name, version) not in active
        ],
        "unlisted": [
            {"name": name, "version": version, "status": status.value}
            for name, version, status in rows
            if name not in names
        ],
        "disclaimer": DISCLAIMER,
        "scope": (
            "Recorded equity baseline OOS metrics; promotion, funded replay "
            "and paper P&L are separate."
        ),
    }
