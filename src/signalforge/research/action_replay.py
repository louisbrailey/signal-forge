"""Offline action-aware strategy comparison; never a production promotion path."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from signalforge.backtest.actions import (
    Dividend,
    Split,
    TickerChange,
    decision_series,
    stitch_ticker,
)
from signalforge.backtest.costs import CostModel
from signalforge.backtest.funded import run_funded_replay
from signalforge.config.research import EventFilters, LiquidityFilters, RiskLimits
from signalforge.data.series import PriceSeries
from signalforge.domain import Horizon
from signalforge.research.funded_diagnostics import diagnose
from signalforge.research.historical_eligibility import HistoricalEligibility
from signalforge.research.regime import regime_from_proxy
from signalforge.research.strategies import default_strategies, signal_fn_for


@dataclass
class ActionDataset:
    series: dict[str, PriceSeries]
    splits: tuple[Split, ...]
    dividends: tuple[Dividend, ...]
    ticker_changes: tuple[TickerChange, ...]
    manifest_hash: str
    start: date
    end: date


def load_dataset(root: Path, changes: tuple[TickerChange, ...] = ()) -> ActionDataset:
    manifest_text = (root / "manifest.json").read_text()
    manifest = json.loads(manifest_text)
    start, end = date.fromisoformat(manifest["start"]), date.fromisoformat(manifest["end"])
    data: dict[str, PriceSeries] = {}
    splits = []
    dividends = []
    seen: set[tuple[str, str]] = set()
    for ref in manifest["records"]:
        path = (root / ref["file"]).resolve()
        if path.parent != root.resolve():
            raise ValueError("Snapshot path escapes dataset")
        record = json.loads(path.read_text())
        if (
            record["sha256"] != ref["sha256"]
            or hashlib.sha256(record["raw"].encode()).hexdigest() != ref["sha256"]
            or record["source"] != "massive"
        ):
            raise ValueError("Source snapshot integrity failed")
        if ref != ({k: v for k, v in record.items() if k != "raw"} | {"file": path.name}):
            raise ValueError("Snapshot metadata mismatch")
        if record["requested_start"] != str(start) or record["requested_end"] != str(end):
            raise ValueError("Mixed snapshot windows")
        symbol, kind = record["symbol"], record["kind"]
        if (symbol, kind) in seen:
            raise ValueError("Duplicate endpoint evidence")
        seen.add((symbol, kind))
        payload = json.loads(record["raw"])
        if payload.get("next_url"):
            raise ValueError("Truncated endpoint evidence")
        rows = payload.get("results", [])
        if kind == "bars":
            if payload.get("adjusted") is not False:
                raise ValueError("Unadjusted execution bars required")
            data[symbol] = PriceSeries.from_bars(
                symbol,
                [
                    (
                        datetime.fromtimestamp(r["t"] / 1000, ZoneInfo("America/New_York")).date(),
                        r["o"],
                        r["h"],
                        r["l"],
                        r["c"],
                        r["v"],
                    )
                    for r in rows
                ],
            )
        elif kind == "splits":
            for r in rows:
                splits.append(
                    Split(
                        symbol,
                        date.fromisoformat(r["execution_date"]),
                        Decimal(str(r["split_to"])) / Decimal(str(r["split_from"])),
                        "massive",
                    )
                )
        elif kind == "dividends":
            for r in rows:
                if not r.get("pay_date"):
                    raise ValueError(f"{symbol}: missing dividend pay date")
                dividends.append(
                    Dividend(
                        symbol,
                        date.fromisoformat(r["ex_dividend_date"]),
                        date.fromisoformat(r["pay_date"]),
                        Decimal(str(r["cash_amount"])),
                        "massive",
                        r.get("currency", ""),
                    )
                )
        else:
            raise ValueError("Unknown snapshot endpoint")
    for symbol in data:
        if not all((symbol, kind) in seen for kind in ("bars", "splits", "dividends")):
            raise ValueError("Missing action coverage, including explicit empty results")
    applied = []
    for change in changes:
        if change.old not in data and change.new not in data:
            continue
        if change.old not in data or change.new not in data:
            raise ValueError("Both verified ticker legs required")
        applied.append(change)
        data[change.new] = stitch_ticker(data.pop(change.old), data[change.new], change)
        # Each dated ticker leg is authoritative only on its side of the seam.
        splits = [
            Split(change.new if s.symbol == change.old else s.symbol, s.day, s.ratio, s.source)
            for s in splits
            if not (
                (s.symbol == change.old and s.day >= change.effective)
                or (s.symbol == change.new and s.day < change.effective)
            )
        ]
        dividends = [
            Dividend(
                change.new if d.symbol == change.old else d.symbol,
                d.ex_date,
                d.pay_date,
                d.amount,
                d.source,
                d.currency,
            )
            for d in dividends
            if not (
                (d.symbol == change.old and d.ex_date >= change.effective)
                or (d.symbol == change.new and d.ex_date < change.effective)
            )
        ]
    return ActionDataset(
        data,
        tuple(splits),
        tuple(dividends),
        tuple(applied),
        hashlib.sha256(manifest_text.encode()).hexdigest(),
        start,
        end,
    )


def input_fingerprints(dataset: ActionDataset) -> dict[str, str]:
    """Rolling raw-data identity: later requests cannot silently revise prior inputs."""
    days = sorted({d for b in dataset.series.values() for d in b.dates})
    indexes = {s: {d: i for i, d in enumerate(b.dates)} for s, b in dataset.series.items()}
    h = hashlib.sha256(b"raw-actions-prefix-v1")
    output = {}
    events: tuple[Split | Dividend, ...] = (*dataset.splits, *dataset.dividends)
    for day in days:
        for symbol, b in sorted(dataset.series.items()):
            i = indexes[symbol].get(day)
            row = (
                None
                if i is None
                else [float(a[i]) for a in (b.open, b.high, b.low, b.close, b.volume)]
            )
            h.update(json.dumps([str(day), symbol, row], separators=(",", ":")).encode())
        for event in events:
            effective = event.day if isinstance(event, Split) else event.ex_date
            if effective == day:
                h.update(json.dumps(asdict(event), default=str, sort_keys=True).encode())
        output[str(day)] = h.hexdigest()
    return output


def compare(
    dataset: ActionDataset,
    metadata: dict[str, dict[str, str]],
    *,
    entry_start: date | None = None,
    evaluation_start: date | None = None,
    prospective: bool = False,
) -> dict[str, Any]:
    """All unchanged daily baselines; same cash/costs/eligibility; no winner selection.

    Stock event calendars absent from this initial snapshot schema => fail closed.
    ETFs are exempt from corporate earnings. Current sector metadata remains a
    disclosed limitation. OOS approval is NOT retroactively applied to history.
    """
    metadata = {s: metadata[s] for s in dataset.series}
    listing_gaps = {}
    for symbol, bars in dataset.series.items():
        if not bars.dates:
            raise ValueError(f"{symbol}: no raw history")
        if bars.dates[0] > dataset.start:
            listing = metadata[symbol].get("listing_date")
            if not listing or not dataset.start <= date.fromisoformat(listing) <= bars.dates[0]:
                raise ValueError(f"{symbol}: later start needs verified listing evidence")
            from signalforge.data.calendar import sessions

            listing_gaps[symbol] = [
                str(d)
                for d in sessions(date.fromisoformat(listing), bars.dates[0])
                if d < bars.dates[0]
            ]
    limits = RiskLimits(max_position_concentration_pct=5, max_correlated_exposure_pct=20)
    scenarios = {
        "base": (CostModel(), 5.0),
        "stress": (
            CostModel(commission_per_share=0.005, commission_min_per_order=1, slippage_bps=10),
            10.0,
        ),
    }
    proxy = dataset.series["SPY"]
    regimes = {
        day: regime_from_proxy(decision_series(proxy, t, dataset.splits), t)
        for t, day in enumerate(proxy.dates)
    }
    results = {}
    for strategy in default_strategies():
        if strategy.spec().horizon is Horizon.INTRADAY:
            continue
        spec = strategy.spec()
        by_cost = {}
        for label, (costs, spread) in scenarios.items():
            policy = HistoricalEligibility(
                {s: metadata[s]["instrument_type"] for s in dataset.series},
                LiquidityFilters(),
                EventFilters(),
                spec.horizon,
                {},
                spread,
            )
            replay = run_funded_replay(
                dataset.series,
                {s: signal_fn_for(strategy, regime_by_date=regimes) for s in dataset.series},
                {s: metadata[s]["sector"] or "unknown" for s in dataset.series},
                limits=limits,
                cost_model=costs,
                spread_bps=spread,
                warmup=0,
                splits=dataset.splits,
                dividends=dataset.dividends,
                ticker_changes=dataset.ticker_changes,
                eligibility=policy,
                max_drawdown_pct=10,
                allow_staggered_start=True,
                entry_start=entry_start,
                liquidate_at_end=not prospective,
            )
            if evaluation_start:
                replay.marks = [m for m in replay.marks if m["day"] >= str(evaluation_start)]
                replay.decisions = [
                    d for d in replay.decisions if d["day"] >= str(evaluation_start)
                ]
            by_cost[label] = {
                "cost_model": asdict(costs),
                "spread_bps": spread,
                "result": asdict(replay),
                "diagnostics": (
                    None
                    if prospective
                    else diagnose(
                        replay,
                        start=evaluation_start or dataset.start,
                        end=dataset.end,
                        initial_cash=Decimal(10000),
                        source_reference=dataset.manifest_hash,
                        strategy_version=spec.versioned_key,
                        cost_model_reference=str(asdict(costs)),
                    )
                ),
            }
        results[spec.versioned_key] = {"strategy_spec": asdict(spec), "scenarios": by_cost}
    return {
        "status": "DESCRIPTIVE_UNVALIDATED",
        "dataset_sha256": dataset.manifest_hash,
        "input_prefix_fingerprints": input_fingerprints(dataset),
        "metadata": metadata,
        "unobserved_listing_sessions": listing_gaps,
        "regime_by_session": {str(d): r.to_dict() for d, r in regimes.items()},
        "start": str(dataset.start),
        "end": str(dataset.end),
        "risk_limits": limits.model_dump(),
        "drawdown_entry_halt_pct": 10,
        "books": results,
        "limitations": [
            "Current surviving universe and current sector metadata, not PIT selection.",
            "No PIT earnings evidence: stock entries blocked; ETF earnings not applicable.",
            "Research comparison bypasses promotion only; not a production-equivalent approval.",
            "Cash dividends on closed-market pay dates settle next observed session.",
            "Modeled costs and gap risk; drawdown entry halt cannot guarantee a loss cap.",
        ],
        "disclaimer": "Research signal only — no order was placed.",
    }
