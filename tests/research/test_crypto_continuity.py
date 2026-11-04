"""Missing calendar bars invalidate crypto evidence; never compress a long gap."""

from datetime import UTC, date, datetime, timedelta

from signalforge.research.fx.continuity import missing_intervals


def test_calendar_gaps_include_missing_window_edges_and_empty_pairs() -> None:
    d = date(2025, 1, 1)
    assert missing_intervals([d, d + timedelta(days=3)], timedelta(days=1)) == 2
    assert (
        missing_intervals(
            [d + timedelta(days=1)], timedelta(days=1), start=d, end=d + timedelta(days=2)
        )
        == 2
    )
    assert missing_intervals([], timedelta(days=1), start=d, end=d + timedelta(days=2)) == 3
    assert missing_intervals([], timedelta(days=1)) == 1
    assert missing_intervals([d, d + timedelta(days=1)], timedelta(days=1)) == 0


def test_hourly_gaps_are_measured_in_hours() -> None:
    d = datetime(2025, 1, 1, tzinfo=UTC)
    assert missing_intervals([d, d + timedelta(hours=4)], timedelta(hours=1)) == 3


def test_a_crypto_research_pass_cannot_ignore_missing_development_bars() -> None:
    import numpy as np

    from signalforge.data.series import PriceSeries
    from signalforge.research.fx.harness import CRYPTO2_MARKET, FxGates, evaluate_strategy
    from signalforge.research.fx.strategies import CRYPTO2_STRATEGIES

    d = date(2020, 1, 1)
    dates = [d + timedelta(days=i if i < 400 else i + 50) for i in range(1000)]
    prices = 100.0 * np.exp(np.arange(1000) * 0.002)
    series = PriceSeries.from_bars(
        "BNBUSD",
        [(day, p, p * 1.01, p * 0.99, p, 0.0) for day, p in zip(dates, prices, strict=True)],
    )
    gates = FxGates(
        min_oos_trades=0,
        min_ci_low_r=-999,
        min_oos_expectancy_r=-999,
        min_positive_folds=0,
        min_positive_pair_frac=0,
        min_stress_expectancy_r=-999,
    )
    result = evaluate_strategy(
        CRYPTO2_STRATEGIES[0],
        {"BNBUSD": series},
        seal_from=date(2023, 1, 1),
        gates=gates,
        market=CRYPTO2_MARKET,
    )
    assert result.verdict == "DEV_FAIL"
    assert any("data continuity: BNBUSD development window missing 50" in r for r in result.reasons)


def test_admissibility_policy_is_pinned_and_small_gaps_are_recorded_not_fatal() -> None:
    import numpy as np

    from signalforge.data.series import PriceSeries
    from signalforge.research.fx.continuity import (
        DAILY_POLICY,
        HOURLY_POLICY,
        continuity_breach,
        gap_profile,
    )
    from signalforge.research.fx.harness import CRYPTO2_MARKET, FxGates, evaluate_strategy
    from signalforge.research.fx.strategies import CRYPTO2_STRATEGIES

    assert (DAILY_POLICY.max_missing_frac, DAILY_POLICY.max_gap_bars) == (0.01, 7)
    assert (HOURLY_POLICY.max_missing_frac, HOURLY_POLICY.max_gap_bars) == (0.01, 48)
    d = date(2020, 1, 1)
    # One missing day in 1,000: inside policy — counted, not fatal.
    dates = [d + timedelta(days=i if i < 400 else i + 1) for i in range(1000)]
    g = gap_profile(dates, timedelta(days=1))
    assert (g.missing, g.longest_gap) == (1, 1) and continuity_breach(
        dates, timedelta(days=1)
    ) is None
    # An 8-day hole breaches the longest-gap rule even though it is < 1% of bars.
    hole = [d + timedelta(days=i if i < 400 else i + 8) for i in range(1000)]
    assert continuity_breach(hole, timedelta(days=1)) is not None
    # 1.5% missing spread as single days breaches the fraction rule.
    sparse = [d + timedelta(days=i) for i in range(1000) if i % 60 != 0]
    assert continuity_breach(sparse, timedelta(days=1)) is not None
    # Hourly: a 192-hour hole breaches; a 24-hour one does not.
    h0 = datetime(2024, 1, 1, tzinfo=UTC)
    long_hole = [h0 + timedelta(hours=i if i < 5000 else i + 192) for i in range(20000)]
    short_hole = [h0 + timedelta(hours=i if i < 5000 else i + 24) for i in range(20000)]
    assert continuity_breach(long_hole, timedelta(hours=1)) is not None
    assert continuity_breach(short_hole, timedelta(hours=1)) is None
    # Through the harness: the one-day gap produces no continuity reason.
    prices = 100.0 * np.exp(np.arange(1000) * 0.002)
    series = PriceSeries.from_bars(
        "XRPUSD",
        [(day, p, p * 1.01, p * 0.99, p, 0.0) for day, p in zip(dates, prices, strict=True)],
    )
    gates = FxGates(
        min_oos_trades=0,
        min_ci_low_r=-999,
        min_oos_expectancy_r=-999,
        min_positive_folds=0,
        min_positive_pair_frac=0,
        min_stress_expectancy_r=-999,
    )
    result = evaluate_strategy(
        CRYPTO2_STRATEGIES[0],
        {"XRPUSD": series},
        seal_from=date(2023, 1, 1),
        gates=gates,
        market=CRYPTO2_MARKET,
    )
    assert not any("data continuity" in r for r in result.reasons)
