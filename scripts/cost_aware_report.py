"""Isolated cost-aware trend experiment, using cached historical data only."""

import argparse
import hashlib
import json
from bisect import bisect_right
from dataclasses import asdict, replace
from datetime import date
from decimal import Decimal
from pathlib import Path

from action_replay_report import read_metadata

from signalforge.backtest.actions import decision_series
from signalforge.backtest.costs import CostModel
from signalforge.backtest.funded import run_funded_replay
from signalforge.config.research import EventFilters, LiquidityFilters, RiskLimits
from signalforge.domain import Horizon
from signalforge.research.action_replay import load_dataset
from signalforge.research.cost_aware import VERSION, admit, fit_edge, training_trades
from signalforge.research.funded_diagnostics import diagnose
from signalforge.research.historical_eligibility import HistoricalEligibility
from signalforge.research.prospective_funded import code_digest
from signalforge.research.regime import regime_from_proxy
from signalforge.research.strategies import signal_fn_for
from signalforge.research.strategies.trend_continuation import TrendContinuation

STRESS = CostModel(commission_per_share=0.005, commission_min_per_order=1, slippage_bps=10)


def prefix(dataset, end):
    series = {
        s: b.head(bisect_right(b.dates, end) - 1)
        for s, b in dataset.series.items()
        if b.dates[0] <= end
    }
    last = max(b.dates[-1] for b in series.values())
    return replace(
        dataset,
        series=series,
        end=last,
        splits=tuple(s for s in dataset.splits if s.day <= last),
        dividends=tuple(d for d in dataset.dividends if d.ex_date <= last),
    )


def replay(dataset, metadata, regimes, costs, spread, *, start=None, model=None):
    base = signal_fn_for(TrendContinuation(), regime_by_date=regimes)

    def signal(series, t):
        if start is not None and series.dates[t] < start:
            return None
        return base(series, t)

    policy = HistoricalEligibility(
        {s: metadata[s]["instrument_type"] for s in dataset.series},
        LiquidityFilters(),
        EventFilters(),
        Horizon.SHORT_SWING,
        {},
        spread,
    )
    result = run_funded_replay(
        dataset.series,
        dict.fromkeys(dataset.series, signal),
        {s: metadata[s]["sector"] or "unknown" for s in dataset.series},
        limits=RiskLimits(max_position_concentration_pct=5, max_correlated_exposure_pct=20),
        cost_model=costs,
        spread_bps=spread,
        warmup=0,
        splits=dataset.splits,
        dividends=dataset.dividends,
        ticker_changes=dataset.ticker_changes,
        allow_staggered_start=True,
        eligibility=policy,
        max_drawdown_pct=10,
        entry_start=start,
        entry_admission=(lambda p: admit(model, p)) if model else None,
    )
    if start:
        result.marks = [m for m in result.marks if m["day"] >= str(start)]
        result.decisions = [d for d in result.decisions if d["day"] >= str(start)]
    return result


def run(dataset, metadata, output):
    for symbol, bars in dataset.series.items():
        if bars.dates[0] > dataset.start:
            listing = metadata[symbol].get("listing_date")
            if not listing or not dataset.start <= date.fromisoformat(listing) <= bars.dates[0]:
                raise ValueError("Staggered history requires verified listing evidence")
    # Never use or modify an existing study/output directory.
    output.mkdir(parents=True, exist_ok=False)
    root = Path(__file__).resolve().parents[1]
    protocol = root / "docs/research/COST_AWARE_TREND_V1.md"
    sources = [
        root / p
        for p in (
            "scripts/cost_aware_report.py",
            "src/signalforge/research/cost_aware.py",
            "src/signalforge/backtest/funded.py",
            "uv.lock",
        )
    ]
    design = {
        "strategy": VERSION,
        "status": "EXPERIMENTAL_NOT_PROMOTABLE",
        "protocol_sha256": hashlib.sha256(protocol.read_bytes()).hexdigest(),
        "input_sha256": dataset.manifest_hash,
        "research_code_digest": code_digest(),
        "sources": {
            str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources
        },
        "years": list(range(2021, dataset.end.year + 1)),
        "metadata": metadata,
        "no_untouched_historical_test": True,
        "disclaimer": "Research signal only — no order was placed.",
    }
    (output / "design.json").write_text(json.dumps(design, indent=2))
    proxy = dataset.series["SPY"]
    regimes = {
        day: regime_from_proxy(decision_series(proxy, t, dataset.splits), t)
        for t, day in enumerate(proxy.dates)
    }
    folds = []
    for year in design["years"]:
        cutoff = date(year - 1, 12, 31)
        train = prefix(dataset, cutoff)
        training = replay(train, metadata, regimes, STRESS, 10)
        labels = training_trades(training, {d: r.trend.value for d, r in regimes.items()}, cutoff)
        model = fit_edge(labels, cutoff)
        evaluation = prefix(dataset, min(date(year, 12, 31), dataset.end))
        start = next(d for d in evaluation.series["SPY"].dates if d.year == year)
        outcomes = {}
        for scenario, costs, spread in (("base", CostModel(), 5), ("stress", STRESS, 10)):
            outcomes[scenario] = {}
            for name, gate in (("baseline", None), ("candidate", model)):
                result = replay(
                    evaluation, metadata, regimes, costs, spread, start=start, model=gate
                )
                stats = diagnose(
                    result,
                    start=start,
                    end=evaluation.end,
                    initial_cash=Decimal(10000),
                    source_reference=dataset.manifest_hash,
                    strategy_version=VERSION if gate else "trend_continuation.short_swing@0.1.0",
                    cost_model_reference=str(asdict(costs)),
                )
                outcomes[scenario][name] = {"diagnostics": stats, "replay": asdict(result)}
        fold = {
            "year": year,
            "train_start": str(train.start),
            "train_end": str(train.end),
            "evaluation_start": str(start),
            "evaluation_end": str(evaluation.end),
            "period": "validation" if year <= 2023 else "previously_observed_followup",
            "model": asdict(model),
            "outcomes": outcomes,
        }
        (output / f"fold-{year}.json").write_text(json.dumps(fold, default=str))
        folds.append(fold)
        print(
            json.dumps(
                {
                    "completed_year": year,
                    "model_status": model.status,
                    "training_trades": model.count,
                }
            ),
            flush=True,
        )
    summary = {
        **design,
        "folds": [
            {k: v for k, v in fold.items() if k != "outcomes"}
            | {
                "results": {
                    s: {
                        name: {
                            k: v
                            for k, v in b["diagnostics"].items()
                            if k not in ("calendar_evidence", "closed_market_carry_dates")
                        }
                        for name, b in books.items()
                    }
                    for s, books in fold["outcomes"].items()
                }
            }
            for fold in folds
        ],
    }
    (output / "summary.json").write_text(json.dumps(summary, default=str, indent=2))
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--listing-evidence", type=Path, required=True)
    args = parser.parse_args()
    metadata, changes = read_metadata(args.database, args.listing_evidence)
    run(load_dataset(args.snapshot, changes), metadata, args.output)
