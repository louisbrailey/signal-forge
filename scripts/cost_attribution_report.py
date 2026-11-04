"""Fixed fee/friction factorial audit, not optimization or strategy promotion."""

from __future__ import annotations

import argparse
import hashlib
import inspect
import json
from dataclasses import asdict
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

from action_replay_report import read_metadata

from signalforge.backtest.actions import decision_series
from signalforge.backtest.costs import CostModel
from signalforge.backtest.funded import run_funded_replay
from signalforge.config.research import EventFilters, LiquidityFilters, RiskLimits
from signalforge.domain import Horizon
from signalforge.research.action_replay import load_dataset
from signalforge.research.funded_diagnostics import diagnose
from signalforge.research.historical_eligibility import HistoricalEligibility
from signalforge.research.regime import regime_from_proxy
from signalforge.research.strategies import default_strategies, signal_fn_for


def scenarios():
    """Predeclared 2x2 design; no return-based choice of costs or parameters."""
    return {
        "base": (CostModel(), 5.0),
        "commission_only": (
            CostModel(commission_per_share=0.005, commission_min_per_order=1),
            5.0,
        ),
        "friction_only": (CostModel(slippage_bps=10), 10.0),
        "combined_stress": (
            CostModel(commission_per_share=0.005, commission_min_per_order=1, slippage_bps=10),
            10.0,
        ),
    }


def run(snapshot, database, listing_evidence, output):
    output.mkdir(parents=True, exist_ok=False)
    metadata, mappings = read_metadata(database, listing_evidence)
    dataset = load_dataset(snapshot, mappings)
    for symbol, bars in dataset.series.items():
        if not bars.dates:
            raise ValueError(f"{symbol}: empty price history")
        if bars.dates[0] > dataset.start:
            listing = metadata[symbol].get("listing_date")
            if not listing or not dataset.start <= date.fromisoformat(listing) <= bars.dates[0]:
                raise ValueError(f"{symbol}: staggered history requires verified listing evidence")
    strategies = [s for s in default_strategies() if s.spec().horizon is not Horizon.INTRADAY]
    limits = RiskLimits(max_position_concentration_pct=5, max_correlated_exposure_pct=20)
    liquidity, events = LiquidityFilters(), EventFilters()
    design = {
        "status": "DESCRIPTIVE_PREVIOUSLY_OBSERVED_NOT_PROMOTABLE",
        "started_at": datetime.now(UTC).isoformat(),
        "dataset_sha256": dataset.manifest_hash,
        "metadata": {s: metadata[s] for s in dataset.series},
        "ticker_changes": [asdict(m) for m in mappings],
        "window": [str(dataset.start), str(dataset.end)],
        "scenarios": {
            k: {"costs": asdict(c), "spread_bps": s} for k, (c, s) in scenarios().items()
        },
        "specs": [asdict(s.spec()) for s in strategies],
        "strategy_source_hashes": {
            type(s)
            .__name__: hashlib.sha256(Path(inspect.getfile(type(s))).read_bytes())
            .hexdigest()
            for s in strategies
        },
        "initial_cash_usd": 10000,
        "risk_limits": limits.model_dump(),
        "liquidity_filters": liquidity.model_dump(),
        "event_filters": events.model_dump(),
        "max_drawdown_pct": 10,
        "runtime_source_hashes": {
            str(Path(inspect.getfile(obj)).name): hashlib.sha256(
                Path(inspect.getfile(obj)).read_bytes()
            ).hexdigest()
            for obj in (run_funded_replay, decision_series, HistoricalEligibility, read_metadata)
        },
        "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "no_tuning": True,
        "limitations": [
            "Current reference classifications/sector metadata and surviving universe, not PIT.",
            "Stocks without decision-time earnings coverage fail closed.",
            "Fees are sensitivity assumptions, not verified Webull API tariffs.",
            "Each strategy/scenario has separate cash; do not sum their returns.",
            "Different costs can change fills, admission and future trades; "
            "no additive attribution claim.",
        ],
    }
    (output / "design.json").write_text(json.dumps(design, default=str, indent=2))
    proxy = dataset.series["SPY"]
    regimes = {
        d: regime_from_proxy(decision_series(proxy, t, dataset.splits), t)
        for t, d in enumerate(proxy.dates)
    }
    results = {}
    for strategy in strategies:
        spec = strategy.spec()
        results[spec.versioned_key] = {}
        for label, (costs, spread) in scenarios().items():
            eligibility = HistoricalEligibility(
                {s: metadata[s]["instrument_type"] for s in dataset.series},
                liquidity,
                events,
                spec.horizon,
                {},
                spread,
            )
            replay = run_funded_replay(
                dataset.series,
                {s: signal_fn_for(strategy, regime_by_date=regimes) for s in dataset.series},
                {s: metadata[s]["sector"] or "unknown" for s in dataset.series},
                limits=limits,
                initial_cash=Decimal(10000),
                cost_model=costs,
                spread_bps=spread,
                warmup=0,
                splits=dataset.splits,
                dividends=dataset.dividends,
                ticker_changes=dataset.ticker_changes,
                eligibility=eligibility,
                max_drawdown_pct=10,
                allow_staggered_start=True,
            )
            diagnostics = diagnose(
                replay,
                start=dataset.start,
                end=dataset.end,
                initial_cash=Decimal(10000),
                source_reference=dataset.manifest_hash,
                strategy_version=spec.versioned_key,
                cost_model_reference=str(asdict(costs)),
            )
            results[spec.versioned_key][label] = {
                k: v
                for k, v in diagnostics.items()
                if k not in {"calendar_evidence", "closed_market_carry_dates"}
            }
            results[spec.versioned_key][label]["commission_paid_usd"] = str(
                sum((Decimal(f["commission"]) for f in replay.fills), Decimal(0))
            )
            # Keep decision/fill evidence independently, without a huge combined JSON.
            artifact = output / f"{spec.key}-{label}.json"
            artifact.write_text(json.dumps(asdict(replay), default=str))
        (output / "results.json").write_text(json.dumps(results, default=str, indent=2))
        print(json.dumps({"completed_strategy": spec.versioned_key}), flush=True)
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--listing-evidence", type=Path)
    args = parser.parse_args()
    run(args.snapshot, args.database, args.listing_evidence, args.output)
