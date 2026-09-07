"""Portfolio-level performance metrics from an R-multiple trade stream.

Builds a *sequential* equity curve (one position's risk at a time, sized at a
fixed fraction of equity) and derives CAGR, annualised volatility, Sharpe,
Sortino, max drawdown %, exposure, turnover, hit rate, profit factor, and trade
count. Costs are already baked into ``pnl_r`` by the backtest engine.

This is a reporting layer only — it does not change any signal, threshold, or
sizing rule used by the live/paper path.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import date
from datetime import datetime as _dt

from signalforge.backtest.engine import SimTrade


@dataclass(frozen=True, slots=True)
class PortfolioMetrics:
    n_trades: int
    hit_rate: float
    profit_factor: float
    total_return_pct: float
    cagr_pct: float
    ann_vol_pct: float
    sharpe: float
    sortino: float
    max_drawdown_pct: float
    exposure: float  # fraction of the test span with an open position
    turnover_per_year: float  # round-trip trades per year
    avg_trade_r: float
    start_equity: float
    end_equity: float
    span_days: int

    def to_dict(self) -> dict[str, float | int]:
        return asdict(self)


def _as_date(x: date | _dt) -> date:
    return x.date() if isinstance(x, _dt) else x


def compute_portfolio_metrics(
    trades: Sequence[SimTrade],
    *,
    start_equity: float = 10_000.0,
    risk_fraction: float = 0.005,  # 0.5% of equity risked per trade (matches RiskLimits default)
    span_start: date | None = None,
    span_end: date | None = None,
) -> PortfolioMetrics:
    """``risk_fraction`` * equity is the $ risked on each trade; a trade returning
    ``pnl_r`` R changes equity by ``pnl_r * risk_fraction * equity``."""
    ordered = sorted(trades, key=lambda t: _as_date(t.entry_date))
    n = len(ordered)
    if n == 0:
        return PortfolioMetrics(
            0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            start_equity,
            start_equity,
            0,
        )

    first = span_start or _as_date(ordered[0].entry_date)
    last = span_end or max(_as_date(t.exit_date) for t in ordered)
    span_days = max((last - first).days, 1)

    equity = start_equity
    curve: list[float] = [equity]
    peak = equity
    max_dd = 0.0
    per_trade_returns: list[float] = []  # fractional equity change per trade
    exposure_days = 0
    for t in ordered:
        change = t.pnl_r * risk_fraction  # fraction of *current* equity
        equity *= 1.0 + change
        per_trade_returns.append(change)
        curve.append(equity)
        peak = max(peak, equity)
        max_dd = max(max_dd, (peak - equity) / peak if peak > 0 else 0.0)
        exposure_days += max(int(getattr(t, "bars_held", 0)), 0)

    wins = [r for r in per_trade_returns if r > 0]
    losses = [r for r in per_trade_returns if r <= 0]
    gross_profit = sum(wins)
    gross_loss = -sum(losses)
    mean_r = sum(per_trade_returns) / n
    var = sum((r - mean_r) ** 2 for r in per_trade_returns) / n
    std = math.sqrt(var)
    downside = [r for r in per_trade_returns if r < 0]
    dstd = math.sqrt(sum(r * r for r in downside) / n) if downside else 0.0

    trades_per_year = n / (span_days / 365.25)
    ann_factor = math.sqrt(trades_per_year) if trades_per_year > 0 else 0.0
    sharpe = (mean_r / std) * ann_factor if std > 0 else 0.0
    sortino = (mean_r / dstd) * ann_factor if dstd > 0 else 0.0

    total_return = equity / start_equity - 1.0
    years = span_days / 365.25
    cagr = (equity / start_equity) ** (1.0 / years) - 1.0 if years > 0 and equity > 0 else 0.0
    ann_vol = std * (math.sqrt(trades_per_year) if trades_per_year > 0 else 0.0)

    exposure = min(1.0, exposure_days / (span_days / 7 * 5)) if span_days else 0.0

    return PortfolioMetrics(
        n_trades=n,
        hit_rate=len(wins) / n,
        profit_factor=(gross_profit / gross_loss) if gross_loss > 0 else float("inf"),
        total_return_pct=round(total_return * 100, 3),
        cagr_pct=round(cagr * 100, 3),
        ann_vol_pct=round(ann_vol * 100, 3),
        sharpe=round(sharpe, 3),
        sortino=round(sortino, 3),
        max_drawdown_pct=round(max_dd * 100, 3),
        exposure=round(exposure, 4),
        turnover_per_year=round(trades_per_year, 2),
        avg_trade_r=round(mean_r / risk_fraction, 4),
        start_equity=start_equity,
        end_equity=round(equity, 2),
        span_days=span_days,
    )
