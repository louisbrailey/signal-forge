"""Backtest performance metrics (ARCHITECTURE.md §1.4).

All figures are **net of modeled costs** (costs are already baked into the trade
fills). The risk-adjusted figure is a per-trade Sharpe-like ratio, annualised by
trade frequency — it is explicitly *not* computed from a daily return stream and
should be read with that limitation in mind.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import asdict, dataclass

from signalforge.backtest.engine import SimTrade

_TRADING_DAYS_PER_YEAR = 252


@dataclass(frozen=True, slots=True)
class Metrics:
    n_trades: int
    win_rate: float
    avg_win_r: float
    avg_loss_r: float
    expectancy_r: float
    profit_factor: float
    max_drawdown_r: float
    risk_adjusted_ratio: float  # per-trade Sharpe-like, freq-annualised (see module docstring)
    avg_bars_held: float
    trades_per_year: float
    exposure: float  # fraction of sessions spent in a position
    largest_losing_streak: int
    gross_profit_r: float
    gross_loss_r: float
    total_return_r: float

    def to_dict(self) -> dict[str, float | int]:
        return asdict(self)


def _max_drawdown(equity: Sequence[float]) -> float:
    peak = 0.0
    max_dd = 0.0
    for v in equity:
        peak = max(peak, v)
        max_dd = max(max_dd, peak - v)
    return max_dd


def _losing_streak(trades: Sequence[SimTrade]) -> int:
    worst = cur = 0
    for tr in trades:
        if tr.pnl_r < 0:
            cur += 1
            worst = max(worst, cur)
        else:
            cur = 0
    return worst


def compute_metrics(
    trades: Sequence[SimTrade],
    *,
    total_sessions: int | None = None,
) -> Metrics:
    n = len(trades)
    if n == 0:
        return Metrics(0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0, 0.0, 0.0, 0.0)

    rs = [t.pnl_r for t in trades]
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r <= 0]
    gross_profit = sum(wins)
    gross_loss = -sum(losses)

    mean_r = sum(rs) / n
    var = sum((r - mean_r) ** 2 for r in rs) / n
    std_r = math.sqrt(var)

    bars_held = [t.bars_held for t in trades]
    span_days = max(1, sum(bars_held))  # rough: sessions with exposure
    trades_per_year = n / (span_days / _TRADING_DAYS_PER_YEAR) if span_days else 0.0
    risk_adjusted = (mean_r / std_r) * math.sqrt(max(trades_per_year, 1e-9)) if std_r > 0 else 0.0

    exposure = min(1.0, sum(bars_held) / total_sessions) if total_sessions else float("nan")

    # equity curve in R
    eq, acc = [], 0.0
    for r in rs:
        acc += r
        eq.append(acc)

    return Metrics(
        n_trades=n,
        win_rate=len(wins) / n,
        avg_win_r=(sum(wins) / len(wins)) if wins else 0.0,
        avg_loss_r=(sum(losses) / len(losses)) if losses else 0.0,
        expectancy_r=mean_r,
        profit_factor=(gross_profit / gross_loss) if gross_loss > 0 else float("inf"),
        max_drawdown_r=_max_drawdown(eq),
        risk_adjusted_ratio=risk_adjusted,
        avg_bars_held=sum(bars_held) / n,
        trades_per_year=trades_per_year,
        exposure=exposure,
        largest_losing_streak=_losing_streak(trades),
        gross_profit_r=gross_profit,
        gross_loss_r=gross_loss,
        total_return_r=sum(rs),
    )
