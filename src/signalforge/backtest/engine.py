"""Event-driven daily backtest loop (ARCHITECTURE.md §1.4).

Rules that keep the results honest:
* A signal at bar ``t`` sees only ``series.head(t)`` — look-ahead is structurally
  impossible.
* Entries fill at the **next** bar's open, with slippage + half-spread applied
  against the trade.
* Exits: stop (checked first, gaps filled at the open), then target, then a
  time stop at the close of the Nth bar, then end-of-data at the last close.
* Every fill price already includes modeled costs; ``pnl_r`` is in R multiples
  (risk = entry-to-stop distance), so position size cancels out.
* Deterministic: pure arithmetic over the input arrays, no RNG, no wall-clock.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date

from signalforge.backtest.costs import CostModel
from signalforge.backtest.series import PriceSeries
from signalforge.domain import Direction

SignalFn = Callable[[PriceSeries, int], "EntrySignal | None"]
_DOLLAR_RISK_PER_TRADE = 1_000.0  # for the $ equity curve only; metrics use R


@dataclass(frozen=True, slots=True)
class EntrySignal:
    direction: Direction  # LONG or SHORT
    stop_price: float
    time_stop_bars: int
    target_price: float | None = None
    reason: str = ""

    def __post_init__(self) -> None:
        if self.direction not in (Direction.LONG, Direction.SHORT):
            raise ValueError("EntrySignal.direction must be LONG or SHORT")
        if self.time_stop_bars < 1:
            raise ValueError("time_stop_bars must be >= 1")


@dataclass(frozen=True, slots=True)
class SimTrade:
    symbol: str
    direction: Direction
    entry_date: date
    entry_price: float
    exit_date: date
    exit_price: float
    bars_held: int
    pnl_r: float
    pnl_pct: float
    pnl_dollars: float
    mae_r: float
    mfe_r: float
    costs_bps: float
    exit_reason: str
    reason: str = ""


@dataclass(slots=True)
class BacktestOutcome:
    symbol: str
    trades: list[SimTrade] = field(default_factory=list)
    bars: int = 0
    first_date: date | None = None
    last_date: date | None = None

    @property
    def equity_curve_r(self) -> list[float]:
        eq = 0.0
        out = []
        for tr in self.trades:
            eq += tr.pnl_r
            out.append(eq)
        return out


def _sign(direction: Direction) -> int:
    return 1 if direction is Direction.LONG else -1


def run_backtest(
    series: PriceSeries,
    signal_fn: SignalFn,
    *,
    cost_model: CostModel | None = None,
    spread_bps: float = 5.0,
    warmup: int = 50,
) -> BacktestOutcome:
    cm = cost_model or CostModel()
    slip = (cm.slippage_bps + (spread_bps / 2 if cm.half_spread_fill_penalty else 0.0)) / 10_000.0
    n = len(series)
    outcome = BacktestOutcome(symbol=series.symbol, bars=n)
    if n:
        outcome.first_date, outcome.last_date = series.dates[0], series.dates[-1]

    t = max(warmup, 1)
    while t < n - 1:
        sig = signal_fn(series.head(t), t)
        if sig is None:
            t += 1
            continue

        d = _sign(sig.direction)
        entry_idx = t + 1
        raw_entry = series.open[entry_idx]
        entry_fill = raw_entry * (1 + d * slip)
        risk_per_share = abs(entry_fill - sig.stop_price)
        if risk_per_share <= 0:
            t += 1
            continue

        exit_idx, exit_fill, reason = _resolve_exit(series, entry_idx, entry_fill, sig, d, slip)

        # Excursions over the holding window (relative to entry, in R).
        seg_high = series.high[entry_idx : exit_idx + 1]
        seg_low = series.low[entry_idx : exit_idx + 1]
        if sig.direction is Direction.LONG:
            mfe = (float(seg_high.max()) - entry_fill) / risk_per_share
            mae = (float(seg_low.min()) - entry_fill) / risk_per_share
        else:
            mfe = (entry_fill - float(seg_low.min())) / risk_per_share
            mae = (entry_fill - float(seg_high.max())) / risk_per_share

        pnl_r = d * (exit_fill - entry_fill) / risk_per_share
        pnl_pct = d * (exit_fill / entry_fill - 1.0)
        outcome.trades.append(
            SimTrade(
                symbol=series.symbol,
                direction=sig.direction,
                entry_date=series.dates[entry_idx],
                entry_price=round(entry_fill, 4),
                exit_date=series.dates[exit_idx],
                exit_price=round(exit_fill, 4),
                bars_held=exit_idx - entry_idx,
                pnl_r=pnl_r,
                pnl_pct=pnl_pct,
                pnl_dollars=pnl_r * _DOLLAR_RISK_PER_TRADE,
                mae_r=mae,
                mfe_r=mfe,
                costs_bps=slip * 2 * 10_000.0,
                exit_reason=reason,
                reason=sig.reason,
            )
        )
        t = exit_idx + 1  # flat again; no overlapping positions

    return outcome


def _resolve_exit(
    series: PriceSeries,
    entry_idx: int,
    entry_fill: float,
    sig: EntrySignal,
    d: int,
    slip: float,
) -> tuple[int, float, str]:
    n = len(series)
    for u in range(entry_idx, n):
        o, hi, lo = series.open[u], series.high[u], series.low[u]
        # --- stop (checked first) ---
        if sig.direction is Direction.LONG and lo <= sig.stop_price:
            px = min(o, sig.stop_price) if u > entry_idx else sig.stop_price
            return u, px * (1 - slip), "stop"
        if sig.direction is Direction.SHORT and hi >= sig.stop_price:
            px = max(o, sig.stop_price) if u > entry_idx else sig.stop_price
            return u, px * (1 + slip), "stop"
        # --- target ---
        if sig.target_price is not None:
            if sig.direction is Direction.LONG and hi >= sig.target_price:
                px = max(o, sig.target_price) if u > entry_idx else sig.target_price
                return u, px * (1 - slip), "target"
            if sig.direction is Direction.SHORT and lo <= sig.target_price:
                px = min(o, sig.target_price) if u > entry_idx else sig.target_price
                return u, px * (1 + slip), "target"
        # --- time stop ---
        if u - entry_idx >= sig.time_stop_bars:
            return u, series.close[u] * (1 - d * slip), "time_stop"
    last = n - 1
    return last, series.close[last] * (1 - d * slip), "eod"
