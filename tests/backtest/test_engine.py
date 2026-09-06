"""Backtest engine: fills, exits, determinism, and no look-ahead."""

from __future__ import annotations

from datetime import date, timedelta

from signalforge.backtest.engine import EntrySignal, run_backtest
from signalforge.data.series import PriceSeries
from signalforge.domain import Direction


def buy_the_dip(series: PriceSeries, t: int) -> EntrySignal | None:
    if len(series) < 3:
        return None
    prev_ret = series.close[-1] / series.close[-2] - 1.0
    if prev_ret < -0.02:
        ref = float(series.close[-1])
        return EntrySignal(
            direction=Direction.LONG,
            stop_price=ref * 0.965,
            target_price=ref * 1.04,
            time_stop_bars=8,
            reason="dip",
        )
    return None


def _series(prefix: str, closes: list[float]) -> PriceSeries:
    d = date(2021, 1, 1)
    rows = []
    for c in closes:
        rows.append((d, c, c * 1.003, c * 0.997, c, 1_000_000.0))
        d += timedelta(days=1)
    return PriceSeries.from_bars(prefix, rows)


def test_recovers_positive_expectancy_on_a_favourable_series(
    uptrend_with_dips: PriceSeries,
) -> None:
    out = run_backtest(uptrend_with_dips, buy_the_dip, warmup=5)
    assert len(out.trades) >= 10
    exp = sum(t.pnl_r for t in out.trades) / len(out.trades)
    assert exp > 0.1
    assert out.equity_curve_r[-1] > 0


def test_is_deterministic(uptrend_with_dips: PriceSeries) -> None:
    a = run_backtest(uptrend_with_dips, buy_the_dip, warmup=5)
    b = run_backtest(uptrend_with_dips, buy_the_dip, warmup=5)
    assert [(t.entry_date, t.exit_date, t.pnl_r, t.exit_reason) for t in a.trades] == [
        (t.entry_date, t.exit_date, t.pnl_r, t.exit_reason) for t in b.trades
    ]


def test_no_overlapping_positions(uptrend_with_dips: PriceSeries) -> None:
    out = run_backtest(uptrend_with_dips, buy_the_dip, warmup=5)
    for earlier, later in zip(out.trades, out.trades[1:], strict=False):
        assert later.entry_date > earlier.exit_date


def test_stop_is_hit_on_a_declining_series() -> None:
    series = _series("DOWN", [100.0 - 0.8 * i for i in range(25)])

    def go_long_once(s: PriceSeries, t: int) -> EntrySignal | None:
        if t != 3:
            return None
        return EntrySignal(Direction.LONG, stop_price=float(s.close[-1]) * 0.98, time_stop_bars=20)

    out = run_backtest(series, go_long_once, warmup=1)
    assert len(out.trades) == 1
    assert out.trades[0].exit_reason == "stop"
    assert -1.7 < out.trades[0].pnl_r < -0.7


def test_target_is_hit_on_a_rising_series() -> None:
    series = _series("UP", [100.0 * (1.01**i) for i in range(20)])

    def go_long_once(s: PriceSeries, t: int) -> EntrySignal | None:
        if t != 3:
            return None
        ref = float(s.close[-1])
        return EntrySignal(
            Direction.LONG, stop_price=ref * 0.9, target_price=ref * 1.03, time_stop_bars=20
        )

    out = run_backtest(series, go_long_once, warmup=1)
    assert len(out.trades) == 1
    assert out.trades[0].exit_reason == "target"
    assert out.trades[0].pnl_r > 0


def test_time_stop_forces_exit() -> None:
    series = _series("SLOW", [100.0 + 0.01 * i for i in range(30)])

    def go_long_once(s: PriceSeries, t: int) -> EntrySignal | None:
        if t != 3:
            return None
        ref = float(s.close[-1])
        return EntrySignal(
            Direction.LONG, stop_price=ref * 0.5, target_price=ref * 2.0, time_stop_bars=5
        )

    out = run_backtest(series, go_long_once, warmup=1)
    assert out.trades[0].exit_reason == "time_stop"
    assert out.trades[0].bars_held == 5


def test_signal_only_sees_history() -> None:
    series = _series("H", [100.0 + i for i in range(30)])
    seen: list[int] = []

    def spy(s: PriceSeries, t: int) -> EntrySignal | None:
        seen.append(len(s))
        assert len(s) == t + 1  # head(t) => t+1 bars
        return None

    run_backtest(series, spy, warmup=3)
    assert seen and max(seen) < len(series)
