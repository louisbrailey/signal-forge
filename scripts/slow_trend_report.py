"""Cached-data-only evaluation of the preregistered monthly trend hypothesis."""

import argparse
import hashlib
import json
from dataclasses import asdict, replace
from datetime import date
from decimal import Decimal
from pathlib import Path

import numpy as np
from action_replay_report import read_metadata
from cost_aware_report import STRESS, prefix

from signalforge.backtest.actions import decision_series
from signalforge.backtest.costs import CostModel
from signalforge.backtest.funded import run_funded_replay
from signalforge.config.research import EventFilters, LiquidityFilters, RiskLimits
from signalforge.domain import Horizon
from signalforge.research.action_replay import load_dataset
from signalforge.research.funded_diagnostics import diagnose
from signalforge.research.historical_eligibility import HistoricalEligibility
from signalforge.research.prospective_funded import code_digest
from signalforge.research.regime import regime_from_proxy
from signalforge.research.slow_trend import UNIVERSE, VERSION, SlowTrendParams, signal


def replay(dataset, metadata, start, costs, spread, params, trend_filter=True):
    def decide(bars, t):
        return signal(bars, t, params, trend_filter=trend_filter)

    return run_funded_replay(
        dataset.series,
        dict.fromkeys(dataset.series, decide),
        {s: metadata[s]["sector"] or "unknown" for s in dataset.series},
        limits=RiskLimits(max_position_concentration_pct=5, max_correlated_exposure_pct=20),
        initial_cash=Decimal(10000),
        cost_model=costs,
        spread_bps=spread,
        warmup=252,
        splits=dataset.splits,
        dividends=dataset.dividends,
        entry_start=start,
        max_drawdown_pct=10,
        eligibility=HistoricalEligibility(
            dict.fromkeys(dataset.series, "etf"),
            LiquidityFilters(),
            EventFilters(),
            Horizon.POSITION,
            {},
            spread,
        ),
    )


def stats(result, dataset, start, regimes):
    result.marks = [m for m in result.marks if m["day"] >= str(start)]
    result.decisions = [d for d in result.decisions if d["day"] >= str(start)]
    metrics = diagnose(
        result,
        start=start,
        end=dataset.end,
        initial_cash=Decimal(10000),
        source_reference=dataset.manifest_hash,
        strategy_version=VERSION,
        cost_model_reference="SLOW_TREND_V1 fixed base/stress",
    )
    metrics.pop("calendar_evidence")
    metrics.pop("closed_market_carry_dates")
    peak = 10000.0
    drawdown = 0.0
    monthly = {}
    for m in result.marks:
        equity = float(m["net_liquidation_usd"])
        peak = max(peak, equity)
        drawdown = max(drawdown, 1 - equity / peak)
        monthly[m["day"][:7]] = equity
    previous = 10000.0
    returns = {}
    for month, equity in monthly.items():
        returns[month] = equity / previous - 1
        previous = equity
    # Attribution is operational entry counts, not falsely independent regime P&L.
    by_regime = {}
    for f in result.fills:
        if f["side"] == "buy":
            label = regimes[f["signal_day"]]
            by_regime[label] = by_regime.get(label, 0) + 1
    return metrics | {
        "maximum_drawdown_pct": drawdown * 100,
        "monthly_returns": returns,
        "entries_by_regime": by_regime,
    }


def paired_interval(candidate, comparator):
    if candidate.keys() != comparator.keys() or len(candidate) < 6:
        raise ValueError("Paired monthly evidence is incomplete")
    differences = np.array([candidate[k] - comparator[k] for k in sorted(candidate)])
    rng = np.random.default_rng(20261103)
    n = len(differences)
    samples = []
    for _ in range(2000):
        starts = rng.integers(0, n, size=(n + 2) // 3)
        indices = ((starts[:, None] + np.arange(3)) % n).ravel()[:n]
        samples.append(float(differences[indices].mean()) * 100)
    return {
        "months": n,
        "mean_monthly_excess_pct": float(differences.mean()) * 100,
        "ci95_pct": np.quantile(samples, [0.025, 0.975]).tolist(),
        "method": "paired circular 3-month blocks; 2000 draws; seed 20261103",
    }


def run(dataset, metadata, output):
    if not set(UNIVERSE) <= dataset.series.keys():
        raise ValueError("Missing preregistered symbol")
    for s in UNIVERSE:
        if metadata[s]["instrument_type"] != "etf":
            raise ValueError("Verified ETF metadata required")
    dataset = replace(
        dataset,
        series={s: dataset.series[s] for s in UNIVERSE},
        splits=tuple(s for s in dataset.splits if s.symbol in UNIVERSE),
        dividends=tuple(d for d in dataset.dividends if d.symbol in UNIVERSE),
        ticker_changes=(),
    )
    output.mkdir(parents=True, exist_ok=False)
    root = Path(__file__).resolve().parents[1]
    design = {
        "strategy": VERSION,
        "input_sha256": dataset.manifest_hash,
        "code_digest": code_digest(),
        "source_hashes": {
            p: hashlib.sha256((root / p).read_bytes()).hexdigest()
            for p in (
                "docs/research/SLOW_TREND_V1.md",
                "scripts/slow_trend_report.py",
                "src/signalforge/research/slow_trend.py",
                "uv.lock",
            )
        },
        "coverage": {
            s: [str(b.dates[0]), str(b.dates[-1]), len(b)] for s, b in dataset.series.items()
        },
        "status": "EXPERIMENTAL_NOT_PROMOTABLE",
        "no_untouched_test": True,
        "disclaimer": "Research signal only — no order was placed.",
    }
    (output / "design.json").write_text(json.dumps(design, indent=2))
    spy = dataset.series["SPY"]
    regimes = {}
    for t, day in enumerate(spy.dates):
        r = regime_from_proxy(decision_series(spy, t, dataset.splits), t)
        regimes[str(day)] = f"{r.trend.value}/{r.vol.value}"
    outcomes = {}
    periods = [("continuous", date(2018, 1, 1), dataset.end)] + [
        (str(y), date(y, 1, 1), min(date(y, 12, 31), dataset.end))
        for y in range(2021, dataset.end.year + 1)
    ]
    for label, start, end in periods:
        subset = prefix(dataset, end)
        start = next(d for d in spy.dates if d >= start)
        outcomes[label] = {}
        for scenario, costs, spread in (("base", CostModel(), 5), ("stress", STRESS, 10)):
            outcomes[label][scenario] = {}
            for name, trend in (("candidate", True), ("simpler", False)):
                result = replay(subset, metadata, start, costs, spread, SlowTrendParams(), trend)
                outcomes[label][scenario][name] = stats(result, subset, start, regimes)
                (output / f"{label}-{scenario}-{name}.json").write_text(
                    json.dumps(asdict(result), default=str)
                )
        print(json.dumps({"completed": label}), flush=True)
    sensitivity = {}
    for field, values in {
        "sma_window": (160, 240),
        "stop_atr": (2.4, 3.6),
        "holding_sessions": (100, 151),
    }.items():
        for value in values:
            p = replace(SlowTrendParams(), **{field: value})
            start = next(d for d in spy.dates if d >= date(2018, 1, 1))
            result = replay(dataset, metadata, start, STRESS, 10, p)
            sensitivity[f"{field}={value}"] = stats(result, dataset, start, regimes)
    ci = {
        scenario: paired_interval(
            books["candidate"]["monthly_returns"], books["simpler"]["monthly_returns"]
        )
        for scenario, books in outcomes["continuous"].items()
    }
    summary = design | {"results": outcomes, "sensitivity": sensitivity, "paired_evidence": ci}
    (output / "summary.json").write_text(json.dumps(summary, default=str, indent=2))
    return summary


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("snapshot", type=Path)
    p.add_argument("output", type=Path)
    p.add_argument("--database", type=Path, required=True)
    p.add_argument("--listing-evidence", type=Path, required=True)
    a = p.parse_args()
    meta, changes = read_metadata(a.database, a.listing_evidence)
    run(load_dataset(a.snapshot, changes), meta, a.output)
