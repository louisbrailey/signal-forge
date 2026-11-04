"""Experimental cost-aware admission. Never registered, scheduled or promoted."""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import date
from decimal import ROUND_CEILING, Decimal
from typing import Any

import numpy as np

from signalforge.backtest.funded import EntryProposal, EntryVerdict, FundedReplay, sell_price

VERSION = "cost_aware_trend.short_swing@0.1.0"


@dataclass(frozen=True)
class TrainingTrade:
    symbol: str
    entry_day: date
    exit_day: date
    gross_return: float
    regime: str


@dataclass(frozen=True)
class EdgeModel:
    trained_through: date
    count: int
    months: int
    regimes: dict[str, int]
    lower_return: float | None
    status: str
    sample_hash: str


def training_trades(
    replay: FundedReplay, regimes: dict[date, str], cutoff: date
) -> tuple[TrainingTrade, ...]:
    """Require complete paired records; only exits available by cutoff become labels."""
    opened: dict[str, dict[str, Any]] = {}
    samples = []
    for fill in replay.fills:
        if date.fromisoformat(fill["day"]) > cutoff:
            continue
        symbol = fill["symbol"]
        if fill["side"] == "buy":
            if symbol in opened:
                raise ValueError("Duplicate training entry")
            opened[symbol] = fill
        else:
            buy = opened.pop(symbol)
            if fill["reason"] == "end_of_data":
                continue
            notional = Decimal(buy["price"]) * buy["shares"]
            gross = (
                Decimal(fill["realized_pnl_usd"])
                + Decimal(buy["modeled_cost_usd"])
                + Decimal(fill["modeled_cost_usd"])
            )
            samples.append(
                TrainingTrade(
                    symbol,
                    date.fromisoformat(buy["day"]),
                    date.fromisoformat(fill["day"]),
                    float(gross / notional),
                    regimes[date.fromisoformat(buy["signal_day"])],
                )
            )
    return tuple(samples)


def fit_edge(samples: tuple[TrainingTrade, ...], cutoff: date) -> EdgeModel:
    # Filter before validation/statistics/hashing: future outcomes cannot change a model.
    known = sorted(
        (s for s in samples if s.exit_day <= cutoff),
        key=lambda s: (s.exit_day, s.entry_day, s.symbol),
    )
    if any(s.entry_day > s.exit_day or not math.isfinite(s.gross_return) for s in known):
        raise ValueError("Invalid historical label")
    digest = hashlib.sha256(
        json.dumps([asdict(s) for s in known], default=str, sort_keys=True).encode()
    ).hexdigest()
    months: dict[str, list[float]] = defaultdict(list)
    regimes = dict(Counter(s.regime for s in known))
    for s in known:
        months[s.exit_day.isoformat()[:7]].append(s.gross_return)
    n, m = len(known), len(months)
    if n < 100 or m < 24 or sum(v >= 10 for v in regimes.values()) < 2:
        return EdgeModel(cutoff, n, m, regimes, None, "INSUFFICIENT_EVIDENCE", digest)
    totals = np.array([sum(v) for _, v in sorted(months.items())])
    counts = np.array([len(v) for _, v in sorted(months.items())])
    draws = np.random.default_rng(20261103).integers(0, m, size=(2000, m))
    means = totals[draws].sum(axis=1) / counts[draws].sum(axis=1)
    lower = float(np.quantile(means, 0.05))
    return EdgeModel(
        cutoff, n, m, regimes, lower, "ESTIMATED" if lower > 0 else "NONPOSITIVE_EDGE", digest
    )


def admit(model: EdgeModel, proposal: EntryProposal) -> EntryVerdict:
    """Veto only; actual fill size is supplied after existing cash and risk sizing."""
    if model.trained_through >= proposal.signal_day:
        raise ValueError("Training must precede the decision-time signal")
    if (
        proposal.shares < 1
        or not proposal.notional.is_finite()
        or proposal.notional <= 0
        or not proposal.reference_open.is_finite()
        or proposal.reference_open <= 0
    ):
        raise ValueError("Invalid proposed lot")
    # Always retain the pre-registered stress budget, even in the base-cost ablation.
    raw = proposal.reference_open
    stress_buy = (raw * Decimal("1.0015")).quantize(Decimal(".01"), rounding=ROUND_CEILING)
    stress_sell = sell_price(float(raw), 0.0015)
    fee = max(Decimal(1), Decimal(".005") * proposal.shares)
    budget = max(proposal.round_trip_cost, (stress_buy - stress_sell) * proposal.shares + 2 * fee)
    benefit = (
        Decimal(str(model.lower_return)) * proposal.notional if model.lower_return else Decimal(0)
    )
    required = budget * Decimal("1.5")
    accepted = model.status == "ESTIMATED" and benefit > required
    reason = (
        "cost_edge_passed"
        if accepted
        else (
            "insufficient_training_evidence"
            if model.status == "INSUFFICIENT_EVIDENCE"
            else "estimated_edge_does_not_cover_costs"
        )
    )
    return EntryVerdict(
        accepted,
        reason,
        {
            "strategy": VERSION,
            "trained_through": str(model.trained_through),
            "training_sample_hash": model.sample_hash,
            "training_trades": model.count,
            "training_months": model.months,
            "training_regimes": model.regimes,
            "lower_gross_return": model.lower_return,
            "proposed_shares": proposal.shares,
            "proposed_notional_usd": str(proposal.notional),
            "estimated_round_trip_cost_usd": str(budget),
            "required_edge_usd": str(required),
            "estimated_lower_gross_pnl_usd": str(benefit),
            "accepted": accepted,
            "signal_day": str(proposal.signal_day),
            "entry_day": str(proposal.day),
            "explanation": "Training-only bootstrap estimate, not a probability of profit.",
        },
    )
