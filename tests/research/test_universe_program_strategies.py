"""Pre-registered 2026-11-02 program (PREREGISTRATION_universe_program_2026-11-02.md):
tsmom_etf, turn_of_month, FX-3 and CRYPTO-2 — spec completeness, calendar
causality, signal logic and registry wiring. Synthetic series only."""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np

from signalforge.data.calendar import sessions
from signalforge.data.series import PriceSeries
from signalforge.domain import Direction, Horizon
from signalforge.research.fx import sealed
from signalforge.research.fx.harness import CRYPTO2_MARKET, FX3_GATES, FX3_MARKET
from signalforge.research.fx.strategies import (
    CRYPTO2_STRATEGIES,
    CRYPTO_STRATEGIES,
    FX3_STRATEGIES,
)
from signalforge.research.promotion import _sensitivity_plan
from signalforge.research.regime import NEUTRAL, RegimeState, Trend, Vol
from signalforge.research.registry import StrategyStatus
from signalforge.research.strategies import TsmomEtf, TurnOfMonth, default_strategies
from signalforge.research.strategies.base import StrategyContext
from signalforge.research.strategies.calendar_rules import (
    is_last_session_of_month,
    is_penultimate_session_of_month,
    next_sessions,
)
from signalforge.research.strategies.tsmom_etf import TsmomParams
from signalforge.research.strategies.turn_of_month import TurnOfMonthParams

RISK_OFF = RegimeState(Trend.BEAR, Vol.HIGH, date(2024, 1, 1))


def _session_series(closes: list[float], start: date = date(2018, 1, 2)) -> PriceSeries:
    days = sessions(start, start + timedelta(days=int(len(closes) * 1.6) + 30))[: len(closes)]
    rows = [
        (d, c * 0.999, c * 1.005, c * 0.995, c, 1_000_000.0)
        for d, c in zip(days, closes, strict=True)
    ]
    return PriceSeries.from_bars("ETF", rows)


# ---- calendar rules -------------------------------------------------------- #
def test_month_end_lookups_match_the_exchange_calendar() -> None:
    # 2024-03-28 (Thu) was the last session of March 2024 (Good Friday 03-29 closed).
    assert is_last_session_of_month(date(2024, 3, 28))
    assert not is_last_session_of_month(date(2024, 3, 27))
    assert is_penultimate_session_of_month(date(2024, 3, 27))
    assert not is_penultimate_session_of_month(date(2024, 3, 28))
    # December resolves across the year boundary.
    assert is_last_session_of_month(date(2023, 12, 29))
    assert next_sessions(date(2023, 12, 29), 1) == (date(2024, 1, 2),)


def test_calendar_rules_never_read_future_bars() -> None:
    series = _session_series([100.0 + i * 0.1 for i in range(400)])
    t = 300
    strat = TsmomEtf()
    tom = TurnOfMonth()
    a = (
        strat.evaluate(series.head(t + 1), t, StrategyContext(regime=NEUTRAL)),
        tom.evaluate(series.head(t + 1), t, StrategyContext(regime=NEUTRAL)),
    )
    shocked = PriceSeries(
        series.symbol,
        series.dates,
        series.open,
        series.high * 3,
        series.low / 3,
        np.where(np.arange(len(series)) > t, series.close * 2, series.close),
        series.volume,
    )
    b = (
        strat.evaluate(shocked.head(t + 1), t, StrategyContext(regime=NEUTRAL)),
        tom.evaluate(shocked.head(t + 1), t, StrategyContext(regime=NEUTRAL)),
    )
    assert a == b


# ---- tsmom_etf ------------------------------------------------------------- #
def test_tsmom_fires_long_only_at_month_end_in_an_uptrend_and_ignores_regime() -> None:
    series = _session_series([100.0 * (1.0008**i) for i in range(400)])
    strat = TsmomEtf()
    fired = [
        t
        for t in range(260, len(series))
        if strat.evaluate(series, t, StrategyContext(regime=RISK_OFF))
    ]
    assert fired, "no month-end signal in a steady uptrend"
    for t in fired:
        assert is_last_session_of_month(series.dates[t])
        sig = strat.evaluate(series, t, StrategyContext(regime=RISK_OFF))
        assert sig is not None and sig.direction is Direction.LONG
        assert sig.target_price is None and sig.time_stop_bars == 21
        assert sig.stop_price < series.close[t]
    # Every month end in range fired, and nothing else did.
    month_ends = [t for t in range(260, len(series)) if is_last_session_of_month(series.dates[t])]
    assert fired == month_ends


def test_tsmom_shorts_only_when_allowed_and_is_flat_when_trend_and_filter_disagree() -> None:
    down = _session_series([100.0 * (0.9992**i) for i in range(400)])
    strat = TsmomEtf()
    t = next(i for i in range(260, len(down)) if is_last_session_of_month(down.dates[i]))
    assert strat.evaluate(down, t, StrategyContext(regime=NEUTRAL)) is None
    sig = strat.evaluate(down, t, StrategyContext(regime=NEUTRAL, allow_short=True))
    assert sig is not None and sig.direction is Direction.SHORT
    # Up over 12 months but below the 10-month SMA (a late collapse): no trade either way.
    closes = [100.0 * (1.001**i) for i in range(330)] + [
        100.0 * (1.001**330) * (0.9985**k) for k in range(1, 71)
    ]
    mixed = _session_series(closes)
    t2 = max(i for i in range(260, len(mixed)) if is_last_session_of_month(mixed.dates[i]))
    assert strat.evaluate(mixed, t2, StrategyContext(regime=NEUTRAL, allow_short=True)) is None


def test_tsmom_params_are_the_pre_registered_defaults() -> None:
    p = TsmomParams()
    assert (p.lookback, p.sma_window, p.atr_window, p.stop_atr, p.time_stop_bars) == (
        252,
        210,
        20,
        3.0,
        21,
    )


# ---- turn_of_month --------------------------------------------------------- #
def test_turn_of_month_fires_on_the_penultimate_session_only_long_only() -> None:
    series = _session_series([100.0 + np.sin(i / 7) for i in range(300)])
    strat = TurnOfMonth()
    fired = [
        t
        for t in range(20, len(series))
        if strat.evaluate(series, t, StrategyContext(regime=RISK_OFF))
    ]
    expected = [
        t for t in range(20, len(series)) if is_penultimate_session_of_month(series.dates[t])
    ]
    assert fired == expected and fired
    sig = strat.evaluate(series, fired[0], StrategyContext(regime=RISK_OFF, allow_short=True))
    assert sig is not None and sig.direction is Direction.LONG
    assert sig.time_stop_bars == 3 and sig.target_price is None
    assert TurnOfMonthParams() == TurnOfMonthParams(hold_bars=3, atr_window=14, stop_atr=3.0)


# ---- registry / gate-5 grids ---------------------------------------------- #
def test_new_strategies_are_registered_experimental_with_complete_specs_and_grids() -> None:
    keys = {s.key for s in default_strategies()}
    assert {"tsmom_etf.medium_swing", "turn_of_month.short_swing"} <= keys
    for strat in (TsmomEtf(), TurnOfMonth()):
        spec = strat.spec()
        assert spec.missing_fields() == []
        assert spec.status is StrategyStatus.EXPERIMENTAL
        plan = _sensitivity_plan(strat)
        assert plan is not None
        factory, grid = plan
        assert len(grid) == 2 and all(len(v) == 3 for v in grid.values())
        built = factory({k: v[0] for k, v in grid.items()})
        assert built.key == strat.key
    assert TsmomEtf().spec().horizon is Horizon.MEDIUM_SWING
    assert TurnOfMonth().spec().horizon is Horizon.SHORT_SWING
    assert TurnOfMonth().spec().permits_short is False


# ---- FX-3 / CRYPTO-2 ------------------------------------------------------- #
def test_fx3_and_crypto2_versions_are_distinct_and_seal_under_their_own_rows() -> None:
    assert FX3_MARKET.version == "FX-3" and FX3_GATES.holding_cost_bps_per_day == 1.0
    assert [s.key for s in FX3_STRATEGIES] == ["fx_mom_21"]
    assert CRYPTO2_MARKET.version == "CRYPTO-2"
    keys = [s.key for s in CRYPTO2_STRATEGIES]
    assert keys == [f"{s.key}_u10" for s in CRYPTO_STRATEGIES] + ["crypto_mom_21_u10"]
    # The carried-over rules are the SAME functions with the SAME params.
    for old, new in zip(CRYPTO_STRATEGIES, CRYPTO2_STRATEGIES[:3], strict=True):
        assert new.signal is old.signal and new.params == old.params
    mk, _strat, gates = sealed._lookup("fx", "fx_mom_21")
    assert mk.version == "FX-3" and gates is FX3_GATES
    mk2, strat2, _ = sealed._lookup("crypto", "crypto_donchian_55_u10")
    assert mk2.version == "CRYPTO-2" and strat2.signal is CRYPTO_STRATEGIES[0].signal
    mk1, _, _ = sealed._lookup("crypto", "crypto_donchian_55")
    assert mk1.version == "CRYPTO-1"


def test_mom21_is_causal_and_sign_of_one_month_return() -> None:
    rng = np.random.default_rng(7)
    closes = 1.2 * np.exp(np.cumsum(rng.normal(0, 0.005, 400)))
    days = [date(2015, 1, 5) + timedelta(days=i) for i in range(400)]
    series = PriceSeries.from_bars(
        "EURUSD", [(d, c, c * 1.002, c * 0.998, c, 0.0) for d, c in zip(days, closes, strict=True)]
    )
    strat = FX3_STRATEGIES[0]
    for t in range(strat.warmup, 390, 11):
        head = series.head(t)
        sig = strat.signal(head, t)
        r = head.close[-1] / head.close[-22] - 1
        assert sig is not None
        assert sig.direction is (Direction.LONG if r > 0 else Direction.SHORT)
        assert sig.time_stop_bars == 21
        shocked_close = head.close.copy()
        shocked = PriceSeries(
            head.symbol, head.dates, head.open, head.high, head.low, shocked_close, head.volume
        )
        assert strat.signal(shocked, t) == sig


# ---- refinement round 1 (§7) ----------------------------------------------- #
def test_tsmom_position_is_the_same_signal_held_for_a_quarter() -> None:
    from signalforge.research.fx.harness import CRYPTO3_MARKET
    from signalforge.research.fx.hourly import CRYPTO_H2_VERSION, HOURLY_VERSIONS
    from signalforge.research.fx.strategies import CRYPTO3_STRATEGIES

    swing, position = TsmomEtf(), TsmomEtf(Horizon.POSITION)
    assert position.key == "tsmom_etf.position" and swing.key == "tsmom_etf.medium_swing"
    assert position.params == TsmomParams(time_stop_bars=63)
    assert position.params.lookback == swing.params.lookback
    series = _session_series([100.0 * (1.0008**i) for i in range(400)])
    t = next(i for i in range(260, len(series)) if is_last_session_of_month(series.dates[i]))
    a = swing.evaluate(series, t, StrategyContext(regime=NEUTRAL))
    b = position.evaluate(series, t, StrategyContext(regime=NEUTRAL))
    assert a is not None and b is not None
    assert (a.direction, a.stop_price) == (b.direction, b.stop_price)
    assert (a.time_stop_bars, b.time_stop_bars) == (21, 63)
    assert "tsmom_etf.position" in {s.key for s in default_strategies()}
    factory, grid = _sensitivity_plan(position)  # type: ignore[misc]
    assert factory({k: v[0] for k, v in grid.items()}).key == "tsmom_etf.position"
    # CRYPTO-3: long-only twin of crypto_mom_21.
    assert CRYPTO3_MARKET.version == "CRYPTO-3"
    (long_only,) = CRYPTO3_STRATEGIES
    assert long_only.key == "crypto_mom_21_long_u10"
    assert sealed._lookup("crypto", long_only.key)[0].version == "CRYPTO-3"
    # CRYPTO-H2 is a label for the same hourly rules on a wider universe.
    assert CRYPTO_H2_VERSION == "CRYPTO-H2" and CRYPTO_H2_VERSION in HOURLY_VERSIONS


def test_crypto3_never_shorts_and_matches_the_parent_on_longs() -> None:
    from signalforge.research.fx.strategies import CRYPTO2_STRATEGIES, CRYPTO3_STRATEGIES

    parent = next(s for s in CRYPTO2_STRATEGIES if s.key == "crypto_mom_21_u10")
    (child,) = CRYPTO3_STRATEGIES
    rng = np.random.default_rng(11)
    closes = 30.0 * np.exp(np.cumsum(rng.normal(0, 0.03, 500)))
    days = [date(2019, 1, 1) + timedelta(days=i) for i in range(500)]
    series = PriceSeries.from_bars(
        "XRPUSD", [(d, c, c * 1.01, c * 0.99, c, 0.0) for d, c in zip(days, closes, strict=True)]
    )
    saw_long = saw_short = False
    for t in range(parent.warmup, 495, 3):
        head = series.head(t)
        p, c = parent.signal(head, t), child.signal(head, t)
        if p is None:
            assert c is None
        elif p.direction is Direction.LONG:
            saw_long = True
            assert c == p
        else:
            saw_short = True
            assert c is None
    assert saw_long and saw_short
