"""Metrics, walk-forward split, bootstrap CI, leakage detector, regime labels."""

from __future__ import annotations

from datetime import date

import pytest

from signalforge.backtest.engine import EntrySignal, SimTrade, run_backtest
from signalforge.backtest.leakage import LookaheadDetected, assert_no_lookahead
from signalforge.backtest.metrics import compute_metrics
from signalforge.backtest.montecarlo import bootstrap_ci
from signalforge.backtest.regime import label_regimes
from signalforge.backtest.walkforward import run_walkforward
from signalforge.data.series import PriceSeries
from signalforge.domain import Direction


def _trade(pnl_r: float, bars: int = 3) -> SimTrade:
    return SimTrade(
        symbol="T",
        direction=Direction.LONG,
        entry_date=date(2021, 1, 1),
        entry_price=100.0,
        exit_date=date(2021, 1, 5),
        exit_price=100.0 + pnl_r,
        bars_held=bars,
        pnl_r=pnl_r,
        pnl_pct=pnl_r / 100,
        pnl_dollars=pnl_r * 1000,
        mae_r=-0.5,
        mfe_r=1.0,
        costs_bps=6.0,
        exit_reason="target" if pnl_r > 0 else "stop",
    )


def test_metrics_match_hand_computation() -> None:
    trades = [_trade(2.0), _trade(-1.0), _trade(-1.0), _trade(3.0), _trade(-1.0)]
    m = compute_metrics(trades, total_sessions=100)
    assert m.n_trades == 5
    assert m.win_rate == pytest.approx(0.4)
    assert m.expectancy_r == pytest.approx((2 - 1 - 1 + 3 - 1) / 5)
    assert m.profit_factor == pytest.approx(5 / 3)
    assert m.largest_losing_streak == 2
    assert m.gross_profit_r == pytest.approx(5.0)
    assert m.gross_loss_r == pytest.approx(3.0)
    assert 0 < m.exposure <= 1


def test_max_drawdown_in_r() -> None:
    # cumulative equity: 2, 1, 0, 3, 2 -> peak 2 then down to 0 => max drawdown 2R
    m = compute_metrics([_trade(2.0), _trade(-1.0), _trade(-1.0), _trade(3.0), _trade(-1.0)])
    assert m.max_drawdown_r == pytest.approx(2.0)


def test_empty_metrics_are_zero() -> None:
    m = compute_metrics([])
    assert m.n_trades == 0 and m.expectancy_r == 0.0


def test_bootstrap_ci_brackets_point_and_is_seed_stable() -> None:
    returns = [2.0, -1.0, -1.0, 3.0, -1.0, 1.5, -1.0, 2.5]
    a = bootstrap_ci(returns, seed=42)
    b = bootstrap_ci(returns, seed=42)
    assert a == b
    exp = a["expectancy_r"]
    assert exp["low"] <= exp["point"] <= exp["high"]
    wr = a["win_rate"]
    assert 0.0 <= wr["low"] <= wr["point"] <= wr["high"] <= 1.0
    assert wr["point"] == pytest.approx(0.5)  # 4 of 8 trades > 0


def test_leakage_detector_flags_a_future_reading_feature() -> None:
    rows = [(date(2021, 1, 1), 100.0 + i, 100.0 + i, 100.0 + i, 100.0 + i, 1e6) for i in range(60)]
    series = PriceSeries.from_bars("L", rows)

    def clean_sma(s: PriceSeries, t: int) -> float:
        # indexed relative to t -> identical whether or not future bars exist
        return float(s.close[max(0, t - 9) : t + 1].mean())

    def leaky(s: PriceSeries, t: int) -> float:
        # reads bars ahead of t -> value shifts once more bars exist
        return float(s.close[min(t + 3, len(s) - 1)])

    assert_no_lookahead(clean_sma, series)
    with pytest.raises(LookaheadDetected):
        assert_no_lookahead(leaky, series)


def test_walkforward_reports_is_and_oos_separately(uptrend_with_dips: PriceSeries) -> None:
    def buy_dip(s: PriceSeries, t: int) -> EntrySignal | None:
        if s.close[-1] / s.close[-2] - 1 < -0.02:
            ref = float(s.close[-1])
            return EntrySignal(Direction.LONG, ref * 0.965, 8, ref * 1.04)
        return None

    outcome = run_backtest(uptrend_with_dips, buy_dip, warmup=5)
    report = run_walkforward(uptrend_with_dips, buy_dip, n_folds=3, outcome=outcome)

    assert report.in_sample_end < report.oos_start
    assert report.n_trades_total == len(outcome.trades)
    fold_trades = sum(f.n_trades for f in report.folds)
    oos_trades = sum(
        1 for t in outcome.trades if report.oos_start <= t.entry_date <= report.oos_end
    )
    assert fold_trades == oos_trades
    assert "metrics" in report.to_dict()["out_of_sample"]  # type: ignore[index]


def test_regime_labels_a_bull_series(uptrend_with_dips: PriceSeries) -> None:
    labels = label_regimes(uptrend_with_dips)
    non_warmup = [v for v in labels.values() if v != "warmup"]
    assert non_warmup, "expected some labelled sessions"
    assert any(v.startswith("bull") or v == "range_bound" for v in non_warmup)
