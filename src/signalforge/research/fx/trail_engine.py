"""Backtest with an optional trailing-channel exit — FX research only (FX-2).

The equity backtest engine (``signalforge.backtest.engine``) is frozen by hash
(``tests/backtest/test_equity_core_frozen.py``), so the FX-2 trailing exit
lives here instead of being added to it. This loop mirrors ``run_backtest``
line for line: next-open entry with slippage + half spread, stop checked
first (gap-aware), then target, then — new — a close back through the prior
``trail_channel``-bar low (long) or high (short), then the time stop, then
end of data. With ``trail_channel=None`` it reproduces ``run_backtest``
exactly; ``tests/research/test_fx_trail_engine.py`` proves that parity.
"""

from __future__ import annotations

from signalforge.backtest.costs import CostModel
from signalforge.backtest.engine import (
    BacktestOutcome,
    EntrySignal,
    SignalFn,
    SimTrade,
)
from signalforge.data.series import PriceSeries
from signalforge.domain import Direction

_DOLLAR_RISK_PER_TRADE = 1_000.0  # matches the frozen engine; $ curve only


def _sign(direction: Direction) -> int:
    return 1 if direction is Direction.LONG else -1


def _resolve_exit(
    series: PriceSeries,
    entry_idx: int,
    entry_fill: float,
    sig: EntrySignal,
    d: int,
    slip: float,
    trail_channel: int | None,
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
        # --- trailing channel: this bar's close vs the PRIOR bars only ---
        if trail_channel is not None and u > entry_idx:
            lo_i = max(0, u - trail_channel)
            c = float(series.close[u])
            if sig.direction is Direction.LONG and c < float(series.low[lo_i:u].min()):
                return u, c * (1 - slip), "trail"
            if sig.direction is Direction.SHORT and c > float(series.high[lo_i:u].max()):
                return u, c * (1 + slip), "trail"
        # --- time stop ---
        if u - entry_idx >= sig.time_stop_bars:
            return u, series.close[u] * (1 - d * slip), "time_stop"
    last = n - 1
    return last, series.close[last] * (1 - d * slip), "eod"


def run_backtest_trailing(
    series: PriceSeries,
    signal_fn: SignalFn,
    *,
    trail_channel: int | None,
    cost_model: CostModel | None = None,
    spread_bps: float = 5.0,
    warmup: int = 50,
) -> BacktestOutcome:
    if trail_channel is not None and trail_channel < 2:
        raise ValueError("trail_channel must be >= 2 bars")
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
        entry_fill = series.open[entry_idx] * (1 + d * slip)
        risk_per_share = abs(entry_fill - sig.stop_price)
        if risk_per_share <= 0:
            t += 1
            continue
        exit_idx, exit_fill, reason = _resolve_exit(
            series, entry_idx, entry_fill, sig, d, slip, trail_channel
        )
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
        t = exit_idx + 1
    return outcome
