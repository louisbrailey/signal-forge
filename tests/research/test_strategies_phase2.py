"""Phase 2 strategies: relative strength, volatility breakout, intraday ORB."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from signalforge.data.series import PriceSeries
from signalforge.domain import Direction, Horizon
from signalforge.research.regime import RegimeState, Trend, Vol
from signalforge.research.strategies import IntradayORB, RelativeStrength, VolatilityBreakout
from signalforge.research.strategies.base import StrategyContext

BULL = RegimeState(Trend.BULL, Vol.LOW, date(2024, 1, 1), market_ret_20d=0.01, market_ret_63d=0.02)
BEAR = RegimeState(Trend.BEAR, Vol.HIGH, date(2024, 1, 1), market_ret_63d=-0.05)


def _daily(closes: list[float]) -> PriceSeries:
    d = date(2022, 1, 3)
    rows = []
    for c in closes:
        rows.append((d, c * 0.999, c * 1.01, c * 0.99, c, 2_000_000.0))
        d += timedelta(days=1)
    return PriceSeries.from_bars("X", rows)


def test_relative_strength_fires_when_beating_the_market_in_a_bull_regime() -> None:
    # +40% over the window vs market +2% -> big excess; steadily above SMA100
    closes = [100.0 * (1.0025**i) for i in range(140)]
    sig = RelativeStrength(Horizon.MEDIUM_SWING).evaluate(
        _daily(closes), 139, StrategyContext(regime=BULL)
    )
    assert sig is not None and sig.direction is Direction.LONG
    assert sig.stop_price < closes[-1] < (sig.target_price or 0)


def test_relative_strength_silent_without_a_market_return() -> None:
    closes = [100.0 * (1.0025**i) for i in range(140)]
    no_mkt = RegimeState(Trend.BULL, Vol.LOW, date(2024, 1, 1))
    assert RelativeStrength().evaluate(_daily(closes), 139, StrategyContext(regime=no_mkt)) is None


def _series_with_bars(bars: list[tuple[float, float, float, float]]) -> PriceSeries:
    d = date(2022, 1, 3)
    rows = []
    for o, h, lo, c in bars:
        rows.append((d, o, h, lo, c, 2_000_000.0))
        d += timedelta(days=1)
    return PriceSeries.from_bars("X", rows)


def test_volatility_breakout_fires_after_a_squeeze_and_range_break() -> None:
    bars: list[tuple[float, float, float, float]] = []
    # 55 wide-range bars around 100 (ATR ~ 6), then 24 tight bars (ATR ~ 0.6)
    for i in range(55):
        c = 100.0 + (3 if i % 2 else -3)
        bars.append((c, c + 3, c - 3, c))
    for _ in range(24):
        bars.append((100.0, 100.3, 99.7, 100.0))
    bars.append((100.0, 106.0, 100.0, 105.0))  # break well above the 20d high
    sig = VolatilityBreakout(Horizon.SHORT_SWING).evaluate(
        _series_with_bars(bars), len(bars) - 1, StrategyContext(regime=BULL)
    )
    assert sig is not None and sig.direction is Direction.LONG


def test_volatility_breakout_silent_without_contraction() -> None:
    bars = [(100.0 + (5 if i % 2 else -5),) * 1 for i in range(80)]
    wide = [(c[0], c[0] + 6, c[0] - 6, c[0]) for c in bars]
    wide.append((max(b[3] for b in wide), max(b[3] for b in wide) + 6, 90.0, 120.0))
    assert (
        VolatilityBreakout().evaluate(
            _series_with_bars(wide), len(wide) - 1, StrategyContext(regime=BULL)
        )
        is None
    )


def _intraday(bar_closes: list[float], start_hour_utc: int = 13) -> PriceSeries:
    t = datetime(2024, 6, 25, start_hour_utc, 30, tzinfo=UTC)
    rows = []
    for c in bar_closes:
        rows.append((t, c, c * 1.002, c * 0.998, c, 30_000.0))
        t += timedelta(minutes=15)
    return PriceSeries.from_bars("X", rows)


def test_intraday_orb_breaks_out_above_the_opening_range() -> None:
    # first 3 bars: 100, 101, 100.5 -> OR high ~101*1.002; then break above
    closes = [100.0, 101.0, 100.5, 100.7, 103.5]  # bar index 4 = 5th bar, close well above OR
    sig = IntradayORB().evaluate(_intraday(closes), 4, StrategyContext(regime=BULL))
    assert sig is not None
    assert sig.direction is Direction.LONG
    assert sig.stop_price < 101.0  # opposite (low) edge of the opening range
    assert (sig.target_price or 0) > closes[4]


def test_intraday_orb_gated_by_risk_off_regime() -> None:
    closes = [100.0, 101.0, 100.5, 100.7, 103.5]
    assert IntradayORB().evaluate(_intraday(closes), 4, StrategyContext(regime=BEAR)) is None
