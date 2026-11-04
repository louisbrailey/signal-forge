"""Run the fixed R1 experiment on a read-only Massive raw/action snapshot."""

from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import multiprocessing
from bisect import bisect_right
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict, replace
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

from action_replay_report import read_metadata
from refinement_rules import paired_lower_bound, refined_signal, refinement_kind, simple_benchmark

from signalforge.backtest.actions import decision_series
from signalforge.backtest.costs import CostModel
from signalforge.backtest.funded import run_funded_replay
from signalforge.config.research import EventFilters, LiquidityFilters, RiskLimits
from signalforge.domain import Horizon
from signalforge.research.action_replay import load_dataset
from signalforge.research.features.daily import sma
from signalforge.research.funded_diagnostics import diagnose
from signalforge.research.historical_eligibility import HistoricalEligibility
from signalforge.research.regime import regime_from_proxy
from signalforge.research.strategies import default_strategies, signal_fn_for

CASES = {
    "base": (CostModel(), 5.0),
    "friction": (CostModel(slippage_bps=10), 10.0),
    "stress": (
        CostModel(slippage_bps=10, commission_per_share=0.005, commission_min_per_order=1),
        10.0,
    ),
}
LIMITS = RiskLimits(max_position_concentration_pct=5, max_correlated_exposure_pct=20)
_CTX = {}
EXPECTED_MANIFEST = "edb199c01af7811a9ac8dd4237209af97cea476a9088949d7f84daa018dd8eb1"
EXPECTED_KEYS = {
    "trend_continuation.short_swing@0.1.0",
    "trend_continuation.medium_swing@0.1.0",
    "mean_reversion.short_swing@0.2.0",
    "relative_strength.medium_swing@0.1.0",
    "volatility_breakout.short_swing@0.2.0",
    "tsmom_etf.medium_swing@0.1.0",
    "tsmom_etf.position@0.1.0",
    "turn_of_month.short_swing@0.1.0",
    "high52_breakout.medium_swing@0.1.0",
    "trend_pullback.short_swing@0.1.0",
}


def atomic_json(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, default=str, sort_keys=True, indent=2, allow_nan=False))
    temporary.replace(path)


def preserve_json(path, value):
    """Resume can verify an outcome, never rewrite an existing disposition."""
    if path.exists():
        if json.loads(path.read_text()) != json.loads(json.dumps(value, default=str)):
            raise ValueError("Existing study outcome differs; refusing overwrite")
        return
    atomic_json(path, value)


def save_record(path, job, result):
    digest = hashlib.sha256(
        json.dumps(result, sort_keys=True, allow_nan=False).encode()
    ).hexdigest()
    atomic_json(path, {"job": list(job), "sha256": digest, "data": result})


def load_record(path, job):
    record = json.loads(path.read_text())
    result = record["data"]
    digest = hashlib.sha256(
        json.dumps(result, sort_keys=True, allow_nan=False).encode()
    ).hexdigest()
    if (
        record["job"] != list(job)
        or record["sha256"] != digest
        or [result[k] for k in ("key", "period", "cost_case")] != list(job)
    ):
        raise ValueError("Checkpoint identity/integrity failure")
    return result


def initialize(snapshot, database, listing):
    metadata, mappings = read_metadata(Path(database), Path(listing) if listing else None)
    dataset = load_dataset(Path(snapshot), mappings)
    for symbol, bars in dataset.series.items():
        if not bars.dates:
            raise ValueError(f"{symbol}: empty history")
        if bars.dates[0] > dataset.start:
            listed = metadata[symbol].get("listing_date")
            if not listed or not dataset.start <= date.fromisoformat(listed) <= bars.dates[0]:
                raise ValueError(f"{symbol}: missing listing evidence")
    proxy = dataset.series["SPY"]
    regimes, market_up = {}, {}
    for t, day in enumerate(proxy.dates):
        visible = decision_series(proxy, t, dataset.splits)
        regimes[day] = regime_from_proxy(visible, t)
        market_up[day] = bool(float(visible.close[t]) > sma(visible, t, 200))
    strategies = {
        s.spec().versioned_key: s
        for s in default_strategies()
        if s.spec().horizon is not Horizon.INTRADAY
    }
    _CTX.update(
        dataset=dataset,
        metadata=metadata,
        regimes=regimes,
        market_up=market_up,
        strategies=strategies,
    )


def window(dataset, last):
    return replace(
        dataset,
        series={s: b.head(bisect_right(b.dates, last) - 1) for s, b in dataset.series.items()},
        end=last,
        splits=tuple(s for s in dataset.splits if s.day <= last),
        dividends=tuple(d for d in dataset.dividends if d.ex_date <= last),
    )


def monthly_returns(marks):
    closes = {m["day"][:7]: float(m["net_liquidation_usd"]) for m in marks}
    previous = 10000.0
    result = {}
    for month, equity in sorted(closes.items()):
        result[month] = (equity / previous - 1) * 100
        previous = equity
    return result


def period_result(replay, start):
    if any(date.fromisoformat(f["day"]) < start for f in replay.fills):
        raise ValueError("Annual book must start flat; pre-period fills found")
    return replace(
        replay,
        marks=[m for m in replay.marks if date.fromisoformat(m["day"]) >= start],
        decisions=[d for d in replay.decisions if date.fromisoformat(d["day"]) >= start],
    )


def run_case(job):
    key, period, label = job
    start = date(2017, 1, 1) if period == "development" else date(int(period), 1, 1)
    end = min(date(2020 if period == "development" else int(period), 12, 31), _CTX["dataset"].end)
    dataset = window(_CTX["dataset"], end)
    metadata, regimes = _CTX["metadata"], _CTX["regimes"]
    costs, spread = CASES[label]
    benchmark = key == "simple_spy"
    strategy = None if benchmark else _CTX["strategies"][key]
    base = simple_benchmark if benchmark else signal_fn_for(strategy, regime_by_date=regimes)
    arms = (
        {"baseline": base}
        if benchmark
        else {
            "baseline": base,
            "candidate": refined_signal(base, strategy.key, _CTX["market_up"]),
        }
    )
    output = {
        "key": key,
        "period": period,
        "cost_case": label,
        "start": str(start),
        "end": str(end),
        "arms": {},
    }
    for arm, fn in arms.items():

        def dated_signal(bars, t, underlying=fn):
            return underlying(bars, t) if bars.dates[t] >= start else None

        replay = run_funded_replay(
            dataset.series,
            dict.fromkeys(dataset.series, dated_signal),
            {s: metadata[s]["sector"] or "unknown" for s in dataset.series},
            limits=LIMITS,
            cost_model=costs,
            spread_bps=spread,
            warmup=0,
            splits=dataset.splits,
            dividends=dataset.dividends,
            ticker_changes=dataset.ticker_changes,
            entry_start=start,
            allow_staggered_start=True,
            max_drawdown_pct=10,
            eligibility=HistoricalEligibility(
                {s: metadata[s]["instrument_type"] for s in dataset.series},
                LiquidityFilters(),
                EventFilters(),
                Horizon.POSITION if benchmark else strategy.spec().horizon,
                {},
                spread,
            ),
        )
        replay = period_result(replay, start)
        summary = diagnose(
            replay,
            start=start,
            end=end,
            initial_cash=Decimal(10000),
            source_reference=dataset.manifest_hash,
            strategy_version=key + ":R1:" + arm,
            cost_model_reference=str(asdict(costs)),
        )
        metrics = {
            k: v
            for k, v in summary.items()
            if k not in {"income_targets", "calendar_evidence", "closed_market_carry_dates"}
        }
        metrics["max_drawdown_pct"] = float(
            summary["income_targets"]["cashflow_adjusted_drawdown_pct"]
        )
        metrics["monthly_returns_pct"] = monthly_returns(replay.marks)
        regime_pnl = defaultdict(float)
        previous = 10000.0
        for mark in replay.marks:
            state = regimes[date.fromisoformat(mark["day"])]
            equity = float(mark["net_liquidation_usd"])
            regime_pnl[f"{state.trend.value}/{state.vol.value}"] += equity - previous
            previous = equity
        metrics["regime_daily_pnl_usd"] = dict(regime_pnl)
        output["arms"][arm] = {
            "metrics": metrics,
            "fills": replay.fills,
            "decisions": replay.decisions,
            "marks": replay.marks,
        }
    return output


def verdicts(records, keys):
    output = {}
    for key in keys:
        cost_verdicts = {}
        for label in CASES:
            rows = [records[(key, str(y), label)]["arms"] for y in (2021, 2022, 2023)]
            base, candidate = [
                {
                    m: v
                    for row in rows
                    for m, v in row[arm]["metrics"]["monthly_returns_pct"].items()
                }
                for arm in ("baseline", "candidate")
            ]
            interval = paired_lower_bound(candidate, base)
            gains = [r["candidate"]["metrics"]["net_return_pct"] for r in rows]
            delta = [
                r["candidate"]["metrics"]["net_return_pct"]
                - r["baseline"]["metrics"]["net_return_pct"]
                for r in rows
            ]
            candidate_dd = max(r["candidate"]["metrics"]["max_drawdown_pct"] for r in rows)
            baseline_dd = max(r["baseline"]["metrics"]["max_drawdown_pct"] for r in rows)
            trades = sum(r["candidate"]["metrics"]["closed_trades"] for r in rows)
            gates = {
                "positive_mean_annual_return": sum(gains) > 0,
                "two_positive_years": sum(v > 0 for v in gains) >= 2,
                "two_improved_years": sum(v > 0 for v in delta) >= 2,
                "thirty_trades": trades >= 30,
                "drawdown_not_materially_worse": candidate_dd <= baseline_dd + 1,
                "adjusted_lower_bound_positive": interval["lower_bound_pp"] > 0,
            }
            cost_verdicts[label] = {
                "gates": gates,
                "interval": interval,
                "trades": trades,
                "mean_annual_return_pct": sum(gains) / 3,
            }
        passed = all(all(case["gates"].values()) for case in cost_verdicts.values())
        output[key] = {
            "status": "PROSPECTIVE_RESEARCH_ONLY" if passed else "REJECT_REFINEMENT",
            "cost_cases": cost_verdicts,
            "promotable": False,
        }
    return output


def run(args):
    initialize(args.snapshot, args.database, args.listing_evidence)
    dataset = _CTX["dataset"]
    if dataset.manifest_hash != EXPECTED_MANIFEST or set(_CTX["strategies"]) != EXPECTED_KEYS:
        raise ValueError("R1 requires its pinned snapshot and exact ten-strategy registry")
    if dataset.end < date(2023, 12, 31) or dataset.start > date(2017, 1, 1):
        raise ValueError("Study requires complete development and 2021-2023 validation coverage")
    specs = []
    for s in _CTX["strategies"].values():
        spec = asdict(s.spec())
        spec.pop("git_sha", None)
        specs.append(spec)
    source_objects = [
        run_case,
        refined_signal,
        read_metadata,
        run_funded_replay,
        decision_series,
        HistoricalEligibility,
    ]
    sources = {
        str(Path(inspect.getfile(obj)).resolve()): hashlib.sha256(
            Path(inspect.getfile(obj)).read_bytes()
        ).hexdigest()
        for obj in source_objects + [type(s) for s in _CTX["strategies"].values()]
    }
    design = {
        "protocol": "R1-20261104",
        "protocol_sha256": hashlib.sha256(
            (
                Path(__file__).parents[1] / "docs/research/REFINEMENT_STUDY_2026-11-04.md"
            ).read_bytes()
        ).hexdigest(),
        "manifest_hash": dataset.manifest_hash,
        "specs": specs,
        "source_hashes": sources,
        "metadata": _CTX["metadata"],
        "limits": LIMITS.model_dump(),
        "costs": {k: [asdict(c), s] for k, (c, s) in CASES.items()},
        "no_untouched_test": True,
        "no_promotion": True,
        "rules": {k: refinement_kind(s.key) for k, s in _CTX["strategies"].items()},
    }
    design = json.loads(json.dumps(design, default=str))
    output = Path(args.output)
    if output.exists():
        if not args.resume or json.loads((output / "design.json").read_text()) != design:
            raise ValueError("Output exists; resume requires identical code, metadata and protocol")
    else:
        output.mkdir(parents=True)
        atomic_json(output / "design.json", design)
        atomic_json(output / "started.json", {"at": datetime.now(UTC).isoformat()})
    keys = list(_CTX["strategies"])
    records = {}
    stages = [
        ["development", "2021", "2022", "2023"],
        [str(y) for y in range(2024, dataset.end.year + 1)],
    ]
    for stage, periods in enumerate(stages):
        jobs = [(k, y, c) for k in [*keys, "simple_spy"] for y in periods for c in CASES]
        pending = []
        for job in jobs:
            path = output / ("__".join(job) + ".json")
            if path.exists():
                records[job] = load_record(path, job)
            else:
                pending.append(job)
        with ProcessPoolExecutor(
            max_workers=args.workers,
            mp_context=multiprocessing.get_context("spawn"),
            initializer=initialize,
            initargs=(args.snapshot, args.database, args.listing_evidence),
        ) as pool:
            futures = {pool.submit(run_case, job): job for job in pending}
            for future in as_completed(futures):
                job = futures[future]
                result = future.result()
                save_record(output / ("__".join(job) + ".json"), job, result)
                records[job] = result
                print(
                    json.dumps(
                        {
                            "complete": job,
                            "remaining": len(pending) - sum(f.done() for f in futures),
                        }
                    ),
                    flush=True,
                )
        if stage == 0:
            preserve_json(output / "validation-disposition.json", verdicts(records, keys))
            print(json.dumps({"validation_recorded_before_followup": True}), flush=True)
    summary = [
        {k: v for k, v in r.items() if k != "arms"}
        | {"arms": {a: v["metrics"] for a, v in r["arms"].items()}}
        for _, r in sorted(records.items())
    ]
    preserve_json(output / "summary.json", summary)
    counts = {"jobs": len(records), "cases": sum(len(r["arms"]) for r in records.values())}
    complete = output / "completed.json"
    if complete.exists():
        recorded = json.loads(complete.read_text())
        if any(recorded[k] != v for k, v in counts.items()):
            raise ValueError("Completion counts do not match checkpoints")
    else:
        atomic_json(complete, {"at": datetime.now(UTC).isoformat(), **counts})


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("snapshot")
    p.add_argument("output")
    p.add_argument("--database", required=True)
    p.add_argument("--listing-evidence")
    p.add_argument("--workers", type=int, default=2, choices=range(1, 5))
    p.add_argument("--resume", action="store_true")
    run(p.parse_args())
