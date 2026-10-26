"""Frozen prospective diagnostics, independent of decisions and paper trading.

No outcome is a strategy return or probability of profit. Overlapping cohorts
and forecast windows are not independent observations.
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime
from statistics import mean
from typing import Any

from signalforge.backtest.costs import CostModel
from signalforge.data.calendar import rth_bounds_utc

PROTOCOL = "shadow-outcomes-v1"


def evaluate(payload: dict[str, Any], generated: str, bars: list[dict[str, Any]]) -> dict[str, Any]:
    """Validate provenance and availability before computing any outcome."""
    if payload.get("evaluation_protocol") != PROTOCOL:
        return {"status": "excluded", "reason": "legacy_without_frozen_context"}
    if payload.get("mode") != "prospective_shadow" or payload.get("data_stale") is not False:
        return {"status": "excluded", "reason": "replay_or_stale"}
    try:
        stamp = datetime.fromisoformat(payload["completed_at"])
        started = datetime.fromisoformat(generated)
        dates = payload["dates"]
        if stamp.tzinfo is None or len(dates) not in (5, 20) or dates != sorted(set(dates)):
            raise ValueError
        bounds = rth_bounds_utc(datetime.fromisoformat(dates[0]).date())
        if bounds is None:
            raise ValueError
        first_open, _ = bounds
        if started.tzinfo is None or stamp < started or stamp >= first_open:
            return {"status": "excluded", "reason": "forecast_not_before_entry"}
        if len(bars) < len(dates):
            return {"status": "pending", "reason": "future_sessions_not_complete"}
        if [b["date"] for b in bars] != dates:
            raise ValueError
        for b in bars:
            if b["source"] != "massive" or b["simulated"] or not b["adjusted"] or b["flags"]:
                raise ValueError
            if not all(math.isfinite(b[k]) and b[k] > 0 for k in ("open", "close")):
                raise ValueError
        paths = payload["paths"]
        if len(paths) != 3 or any(len(p) != len(dates) for p in paths):
            raise ValueError
        if not all(math.isfinite(x) and x > 0 for p in paths for x in p):
            raise ValueError
        base = float(payload["unchanged_baseline"])
        if not math.isfinite(base) or base <= 0:
            raise ValueError
        predicted = [mean(p[i] for p in paths) for i in range(len(dates))]
        costs = payload["evaluation_costs"]
        cm = CostModel(**costs["model"])
        spread = costs["spread_bps"]
        if spread != 5.0 or cm != CostModel():
            return {"status": "excluded", "reason": "cost_protocol_mismatch"}
        entry, exit_price = bars[0]["open"], bars[-1]["close"]
        entry_cost = cm.total_entry_cost(entry, 1, spread)
        exit_cost = cm.total_entry_cost(exit_price, 1, spread)
        net = (exit_price - exit_cost) / (entry + entry_cost) - 1
        kronos_positive = predicted[-1] > base + 2 * cm.total_entry_cost(base, 1, spread)
        candidates = payload["candidate_snapshot"]
        if any(datetime.fromisoformat(c["created_at"]) > started for c in candidates):
            raise ValueError
        strategy_positive = any(
            c["direction"] == "LONG" and c["gate"] == "PASSED" for c in candidates
        )
        cohorts = []
        if strategy_positive:
            cohorts.append("strategy_positive")
        if kronos_positive:
            cohorts.append("kronos_positive")
        if strategy_positive and kronos_positive:
            cohorts.append("agreement")
        if strategy_positive != kronos_positive:
            cohorts.append("disagreement")
        return {
            "status": "mature",
            "protocol": PROTOCOL,
            "cohorts": cohorts,
            "net_fixed_horizon_return": net,
            "mae": mean(abs(p - b["close"]) for p, b in zip(predicted, bars, strict=True)),
            "baseline_mae": mean(abs(base - b["close"]) for b in bars),
            "observations": bars,
            "forecast_sha256": hashlib.sha256(
                json.dumps(payload, sort_keys=True).encode()
            ).hexdigest(),
            "notice": (
                "Diagnostic only; not strategy P&L. " "Research signal only — no order was placed."
            ),
        }
    except (KeyError, TypeError, ValueError, OverflowError):
        return {"status": "excluded", "reason": "invalid_context_or_observations"}
