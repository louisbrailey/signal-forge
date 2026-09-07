"""Portfolio-level metrics from an R-multiple trade stream."""

from __future__ import annotations

import math
from datetime import date

from signalforge.domain import Direction
from signalforge.research.portfolio_metrics import compute_portfolio_metrics


def _t(entry: date, exit_: date, pnl_r: float, bars: int = 5):
    from signalforge.backtest.engine import SimTrade

    return SimTrade(
        symbol="X",
        direction=Direction.LONG,
        entry_date=entry,
        entry_price=100.0,
        exit_date=exit_,
        exit_price=100.0 + pnl_r,
        bars_held=bars,
        pnl_r=pnl_r,
        pnl_pct=pnl_r / 100,
        pnl_dollars=pnl_r * 50,
        mae_r=-0.3,
        mfe_r=0.6,
        costs_bps=3.0,
        exit_reason="target",
    )


def test_empty_trades_returns_flat_metrics() -> None:
    pm = compute_portfolio_metrics([])
    assert pm.n_trades == 0 and pm.total_return_pct == 0.0 and pm.max_drawdown_pct == 0.0
    assert pm.end_equity == pm.start_equity


def test_all_winners_grow_equity_no_drawdown() -> None:
    rs = [0.8, 1.2, 0.9, 1.1, 1.0, 1.3, 0.7, 1.0, 1.1, 0.9]  # all > 0, some dispersion
    ts = [_t(date(2020, 1, i + 1), date(2020, 1, i + 3), r) for i, r in enumerate(rs)]
    pm = compute_portfolio_metrics(ts, start_equity=10_000, risk_fraction=0.01)
    eq = 10_000.0
    for r in rs:
        eq *= 1 + r * 0.01
    assert pm.end_equity == round(eq, 2)
    assert pm.max_drawdown_pct == 0.0
    assert pm.hit_rate == 1.0 and pm.profit_factor == math.inf
    assert pm.sharpe > 0 and pm.sortino == 0.0  # no losing trades -> downside dev is 0


def test_mixed_stream_has_drawdown_and_bounded_ratios() -> None:
    seq = [1.0, -1.0, 2.0, -1.0, -1.0, 3.0, -1.0, 1.5]
    ts = [_t(date(2021, 1, i + 1), date(2021, 1, i + 4), r) for i, r in enumerate(seq)]
    pm = compute_portfolio_metrics(ts, span_start=date(2021, 1, 1), span_end=date(2021, 12, 31))
    assert pm.n_trades == 8
    assert 0 < pm.hit_rate < 1
    assert pm.max_drawdown_pct > 0  # the -1,-1 run creates a dip
    assert pm.turnover_per_year > 0
    # avg_trade_r is the mean R-multiple (mean fractional change / risk_fraction)
    assert abs(pm.avg_trade_r - sum(seq) / len(seq)) < 1e-6


def test_losing_stream_shows_negative_cagr_and_pf_below_one() -> None:
    rs = [-0.3, -0.7, -0.5, -0.6, -0.4, -0.8, -0.5, -0.5, -0.6, -0.4] * 2  # all losers, dispersed
    ts = [_t(date(2022, 1, i + 1), date(2022, 1, i + 3), r) for i, r in enumerate(rs)]
    pm = compute_portfolio_metrics(ts, span_start=date(2022, 1, 1), span_end=date(2023, 1, 1))
    assert pm.total_return_pct < 0 and pm.cagr_pct < 0
    assert pm.profit_factor == 0.0  # no wins
    assert pm.sharpe < 0 and pm.sortino < 0
