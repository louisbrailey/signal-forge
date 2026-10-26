"""One-time sealed-year test for FX/crypto research strategies.

Rules (pre-registered with FX-1 / CRYPTO-1):

1. **Only after a development pass.** The development evaluation is recomputed
   in the same call; a strategy that is not ``DEV_PASS`` right now is refused
   and the sealed year stays unseen.
2. **Exactly once per strategy version.** A ``currency_sealed_test`` row is
   written as ``IN_PROGRESS`` and committed BEFORE any sealed bar is read. The
   unique key (market, version, strategy_key) refuses every later attempt, and
   a crash mid-run still consumes the look. Changing a parameter is a new
   version with its own development run.
3. **Same costs, same rules.** Trades are simulated over the full history (so
   indicators have their warm-up) and only trades ENTERED in the sealed window
   count. Gates: at least ``sealed_min_trades`` trades, expectancy >= 0 at
   base cost and at the stress multiplier.
4. **Research only.** ``SEALED_PASS`` is evidence, not a trade permission:
   nothing here reaches paper, alerts or execution (import contract S17).
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from signalforge.backtest.costs import CostModel
from signalforge.backtest.engine import SimTrade
from signalforge.backtest.metrics import compute_metrics
from signalforge.db.models import CurrencySealedTest
from signalforge.research.fx.harness import (
    CRYPTO_MARKET,
    FX2_GATES,
    FX2_MARKET,
    FX_MARKET,
    FxGates,
    ResearchMarket,
    backtest,
    evaluate_strategy,
    holding_cost_r,
    load_series,
    sealed_start,
)
from signalforge.research.fx.strategies import (
    CRYPTO_STRATEGIES,
    FX2_STRATEGIES,
    FX_STRATEGIES,
    FxStrategy,
)

SEALED_MIN_TRADES = 10
SEALED_MIN_EXPECTANCY_R = 0.0
SEALED_MIN_STRESS_EXPECTANCY_R = 0.0

# Each market lists its pre-registered versions: (market+version, strategies,
# the gates that version was pre-registered with).
_MARKETS: dict[str, tuple[tuple[ResearchMarket, tuple[FxStrategy, ...], FxGates], ...]] = {
    "fx": ((FX_MARKET, FX_STRATEGIES, FxGates()), (FX2_MARKET, FX2_STRATEGIES, FX2_GATES)),
    "crypto": ((CRYPTO_MARKET, CRYPTO_STRATEGIES, FxGates()),),
}


class SealedTestRefused(RuntimeError):
    """The sealed year may not be evaluated (already used, or no dev pass)."""


def _lookup(market: str, key: str) -> tuple[ResearchMarket, FxStrategy, FxGates]:
    if market not in _MARKETS:
        raise ValueError(f"unknown market {market!r}; expected one of {sorted(_MARKETS)}")
    known: list[str] = []
    for mk, strategies, gates in _MARKETS[market]:
        for s in strategies:
            known.append(s.key)
            if s.key == key:
                return mk, s, gates
    raise ValueError(f"unknown {market} strategy {key!r}: {known}")


def _strategy(market: str, key: str) -> tuple[ResearchMarket, FxStrategy]:
    mk, s, _ = _lookup(market, key)
    return mk, s


def existing(session: Session, market: str, key: str) -> CurrencySealedTest | None:
    mk, _ = _strategy(market, key)
    return session.scalar(
        select(CurrencySealedTest).where(
            CurrencySealedTest.market == mk.name,
            CurrencySealedTest.version == mk.version,
            CurrencySealedTest.strategy_key == key,
        )
    )


def run_sealed_test(
    session: Session,
    market: str,
    strategy_key: str,
    pairs: Sequence[str],
    *,
    gates: FxGates | None = None,
    now: datetime | None = None,
) -> CurrencySealedTest:
    mk, strat, registered_gates = _lookup(market, strategy_key)
    gates = gates or registered_gates
    prior = existing(session, market, strategy_key)
    if prior is not None:
        raise SealedTestRefused(
            f"{mk.name} {mk.version} {strategy_key} already used its sealed year "
            f"({prior.verdict}, {prior.sealed_from}..{prior.sealed_to}). "
            "A changed parameter is a new version with its own development run."
        )

    series_by_pair = {p: load_series(session, p, mk) for p in pairs}
    series_by_pair = {p: s for p, s in series_by_pair.items() if len(s)}
    if not series_by_pair:
        raise SealedTestRefused(f"no {mk.name} history for the requested pairs")
    seal_from = sealed_start(series_by_pair, gates.sealed_days)
    seal_to = max(s.dates[-1] for s in series_by_pair.values())

    # 1) development gate, recomputed now — the sealed window is not read here
    dev = evaluate_strategy(strat, series_by_pair, seal_from=seal_from, gates=gates, market=mk)
    if dev.verdict != "DEV_PASS":
        raise SealedTestRefused(
            f"{strategy_key} is {dev.verdict} on the development window: " + "; ".join(dev.reasons)
        )

    # 2) consume the look BEFORE touching sealed bars
    row = CurrencySealedTest(
        market=mk.name,
        version=mk.version,
        strategy_key=strategy_key,
        sealed_from=seal_from,
        sealed_to=seal_to,
        pairs=sorted(series_by_pair),
        dev_summary={
            "pooled": dev.pooled,
            "ci_expectancy_r": dev.ci_expectancy_r,
            "stress_expectancy_r": dev.stress_expectancy_r,
            "fold_expectancy_r": dev.fold_expectancy_r,
        },
        verdict="IN_PROGRESS",
    )
    session.add(row)
    session.commit()

    # 3) sealed evaluation
    h = hashlib.sha256()
    cm = CostModel(slippage_bps=gates.slippage_bps)
    base: list[SimTrade] = []
    stress: list[SimTrade] = []
    per_pair: list[dict[str, Any]] = []
    for pair, series in sorted(series_by_pair.items()):
        for i, d in enumerate(series.dates):
            if d >= seal_from:
                h.update(
                    f"{pair}|{d}|{series.open[i]!r}|{series.high[i]!r}|"
                    f"{series.low[i]!r}|{series.close[i]!r}\n".encode()
                )
        spread = mk.spread(pair)
        b = backtest(strat, series, cost_model=cm, spread_bps=spread)
        st = backtest(
            strat, series, cost_model=cm, spread_bps=spread * gates.stress_spread_multiplier
        )
        pb = [t for t in b.trades if t.entry_date >= seal_from]
        ps = [t for t in st.trades if t.entry_date >= seal_from]
        base += pb
        stress += ps
        per_pair.append(
            {
                "pair": pair,
                "trades": len(pb),
                "expectancy_r": compute_metrics(pb).expectancy_r,
                "stress_expectancy_r": compute_metrics(ps).expectancy_r,
            }
        )

    m = compute_metrics(base)
    sm = compute_metrics(stress)
    held_r: float | None = None
    if gates.holding_cost_bps_per_day > 0 and base:
        fracs = sorted(abs(t.pnl_pct / t.pnl_r) for t in base if t.pnl_r)
        fallback = fracs[len(fracs) // 2] if fracs else 0.0
        held_r = sum(
            t.pnl_r - holding_cost_r(t, gates.holding_cost_bps_per_day, fallback) for t in base
        ) / len(base)
    reasons = []
    if m.n_trades < SEALED_MIN_TRADES:
        reasons.append(f"sealed trades {m.n_trades} < {SEALED_MIN_TRADES}")
    if m.expectancy_r < SEALED_MIN_EXPECTANCY_R:
        reasons.append(f"sealed expectancy {m.expectancy_r:.3f}R < {SEALED_MIN_EXPECTANCY_R}R")
    if sm.expectancy_r < SEALED_MIN_STRESS_EXPECTANCY_R:
        reasons.append(
            f"sealed {gates.stress_spread_multiplier:g}x-cost expectancy "
            f"{sm.expectancy_r:.3f}R < {SEALED_MIN_STRESS_EXPECTANCY_R}R"
        )
    if held_r is not None and held_r < gates.min_holding_stress_expectancy_r:
        reasons.append(
            f"sealed {gates.holding_cost_bps_per_day:g}bp/day holding-cost expectancy "
            f"{held_r:.3f}R < {gates.min_holding_stress_expectancy_r}R"
        )
    row.data_sha256 = h.hexdigest()
    row.result = {
        "metrics": m.to_dict(),
        "stress_expectancy_r": sm.expectancy_r,
        "holding_stress_expectancy_r": held_r,
        "pairs": per_pair,
        "reasons": reasons,
        "gates": {
            "min_trades": SEALED_MIN_TRADES,
            "min_expectancy_r": SEALED_MIN_EXPECTANCY_R,
            "min_stress_expectancy_r": SEALED_MIN_STRESS_EXPECTANCY_R,
        },
        "notice": "Sealed-year research result. Not a trade permission. No order was placed.",
    }
    row.verdict = "SEALED_PASS" if not reasons else "SEALED_FAIL"
    row.evaluated_at = now or datetime.now(UTC)
    session.commit()
    return row


def describe(row: CurrencySealedTest) -> str:
    m = row.result.get("metrics", {})
    lines = [
        f"{row.market} {row.version} {row.strategy_key}: {row.verdict}",
        f"  sealed window {row.sealed_from} .. {row.sealed_to} over {', '.join(row.pairs)}",
        f"  trades {m.get('n_trades', 0)}, expectancy {m.get('expectancy_r', 0.0):+.3f}R, "
        f"stress {row.result.get('stress_expectancy_r', 0.0):+.3f}R",
    ]
    lines += [f"  - {r}" for r in row.result.get("reasons", [])]
    return "\n".join(lines)
