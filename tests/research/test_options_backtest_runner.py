"""Segmentation, pooling guard, regime census and the four-way spread surface.

D2 §9.3, §9.5, §12.1, §12.3 and D4 §5.  Nothing here is wired into
``evaluate_promotion`` — the gate ladder is I-O4.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta

import pytest

from signalforge.backtest.options_engine import (
    OptionsCounters,
    RBasis,
    StructureType,
    simulate_structure,
)
from signalforge.data.series import PriceSeries
from signalforge.research.backtest_runner import _is_boundary
from signalforge.research.options_backtest_runner import (
    JOINT_CELLS,
    DualSpreadReport,
    MixedRStreams,
    assert_single_r_stream,
    is_oos_boundary,
    joint_regime_census,
    options_portfolio_metrics,
    options_risk_fraction,
    run_dual_spread,
    split_is_oos,
)
from tests.options_chain_support import (
    LONG_STRIKE,
    LONG_TICKER,
    SHORT_STRIKE,
    SHORT_TICKER,
    build_fixture,
    put_contract,
    sessions_between,
    signal_at,
    worked_example_cost_model,
)

FIRST = date(2024, 2, 1)
LAST = date(2024, 3, 20)
FORCE_CLOSE = date(2024, 3, 14)


def _fx(*, short_fc: float = 8.00, long_fc: float = 3.00, under_fc: float = 492.0):
    dates = sessions_between(FIRST, LAST)
    shorts = dict.fromkeys(dates, 2.0) | {FORCE_CLOSE: short_fc}
    longs = dict.fromkeys(dates, 0.9) | {FORCE_CLOSE: long_fc}
    unders = dict.fromkeys(dates, 505.0) | {FORCE_CLOSE: under_fc}
    return build_fixture(
        dates,
        unders,
        {SHORT_TICKER: shorts, LONG_TICKER: longs},
        [
            put_contract(SHORT_TICKER, SHORT_STRIKE, dates[0]),
            put_contract(LONG_TICKER, LONG_STRIKE, dates[0]),
        ],
    )


def _one_trade(**kwargs):
    fx = _fx(**kwargs)
    trade, _, _ = simulate_structure(
        fx.chain,
        signal_at(0),
        cost_model=worked_example_cost_model(),
        r_basis=RBasis.INCL,
        counters=OptionsCounters(),
    )
    assert trade is not None
    return trade


# ---------------------------------------------------------------------------
# IS / OOS (D2 §12.3)
# ---------------------------------------------------------------------------


def test_the_boundary_is_the_equity_functions_answer_on_the_underlying() -> None:
    fx = _fx()
    assert is_oos_boundary(fx.underlying) == _is_boundary(fx.underlying)


def test_split_assigns_by_entry_date_with_the_boundary_in_sample() -> None:
    trade = _one_trade()
    early = replace(trade, entry_date=date(2024, 2, 1))
    on_boundary = replace(trade, entry_date=date(2024, 2, 15))
    late = replace(trade, entry_date=date(2024, 3, 1))
    seg = split_is_oos([early, on_boundary, late], date(2024, 2, 15))
    assert seg.in_sample == (early, on_boundary)
    assert seg.out_of_sample == (late,)


# ---------------------------------------------------------------------------
# The pooling guard (D2 §9.5 — §15.2 test 23)
# ---------------------------------------------------------------------------


def test_a_mixed_structure_type_trade_list_raises_before_any_statistic() -> None:
    trade = _one_trade()
    other = replace(trade, structure_type=StructureType.CASH_SECURED_PUT)
    assert_single_r_stream([trade, trade])
    with pytest.raises(MixedRStreams):
        assert_single_r_stream([trade, other])


def test_a_mixed_r_basis_trade_list_raises_too() -> None:
    trade = _one_trade()
    with pytest.raises(MixedRStreams):
        assert_single_r_stream([trade, replace(trade, r_basis=RBasis.AT_PRINT)])


# ---------------------------------------------------------------------------
# The explicit risk_fraction (D2 §12.1 — §15.2 test 31)
# ---------------------------------------------------------------------------


def test_risk_fraction_is_r_over_start_equity_not_the_0_005_default() -> None:
    assert options_risk_fraction(390.0, 25_000.0) == pytest.approx(0.0156)
    assert options_risk_fraction(390.0, 25_000.0) > 3 * 0.005
    with pytest.raises(ValueError):
        options_risk_fraction(390.0, 0.0)
    with pytest.raises(ValueError):
        options_risk_fraction(0.0, 25_000.0)


def test_portfolio_metrics_are_computed_with_the_explicit_fraction() -> None:
    trade = _one_trade()
    pm = options_portfolio_metrics([trade], start_equity=25_000.0, r_dollars=trade.r_incl)
    # 1.56%-of-equity risk against a -1.086R trade is a far larger drawdown than the
    # 0.5% the function would otherwise assume.
    assert pm.max_drawdown_pct > 0.015


# ---------------------------------------------------------------------------
# Gate 6 / 6b census on backtest/regime.py's labels (D4 §5)
# ---------------------------------------------------------------------------


def _proxy(n: int = 900) -> PriceSeries:
    start = date(2020, 1, 1)
    rows = []
    price = 100.0
    d = start
    i = 0
    while i < n:
        if d.weekday() < 5:
            price *= 1.0006 if i % 300 < 200 else 0.9985
            rows.append((d, price, price * 1.01, price * 0.99, price, 1e6))
            i += 1
        d += timedelta(days=1)
    return PriceSeries.from_bars("SPY", rows)


def test_the_census_uses_the_function_the_gate_6_census_reads() -> None:
    proxy = _proxy()
    trade = _one_trade()
    trades = [replace(trade, entry_date=d) for d in proxy.dates[::37]]
    census = joint_regime_census(trades, proxy)
    assert census.regime_label_source == "signalforge.backtest.regime:label_regimes"
    assert set(census.joint_cells) == set(JOINT_CELLS)
    assert census.census_closes is True
    assert census.n_trades == len(trades)


def test_the_range_cell_is_vol_unlabelled_and_in_neither_marginal() -> None:
    proxy = _proxy()
    trade = _one_trade()
    trades = [replace(trade, entry_date=d) for d in proxy.dates[::11]]
    census = joint_regime_census(trades, proxy)
    assert census.range_bound_vol_labelled is False
    assert census.vol_marginals["highvol"] + census.vol_marginals["lowvol"] == sum(
        census.joint_cells.values()
    )
    assert census.range_bound_count == census.trend_buckets["range"]
    assert census.to_dict()["census_closes"] is True


def test_a_trade_with_no_proxy_bar_is_counted_and_the_census_still_closes() -> None:
    proxy = _proxy()
    trade = _one_trade()
    trades = [replace(trade, entry_date=date(1999, 1, 4))]
    census = joint_regime_census(trades, proxy)
    assert census.no_proxy_bar == 1
    assert census.census_closes is True


# ---------------------------------------------------------------------------
# The four-way (R basis x spread setting) surface (D2 §9.3)
# ---------------------------------------------------------------------------


def _signal_fn(chain, underlying, t):
    return signal_at(t) if t == 0 else None


def test_the_dual_spread_report_carries_four_cells_and_names_the_binding_one() -> None:
    fx = _fx()
    report = run_dual_spread(
        fx.chain,
        fx.underlying,
        _signal_fn,
        baseline=worked_example_cost_model(),
        stressed=worked_example_cost_model(spread_multiplier=2.0),
        warmup=0,
    )
    assert set(report.cells) == {"at_print@1x", "incl@1x", "at_print@2x", "incl@2x"}
    assert DualSpreadReport.BINDING_KEY == "incl@2x"
    rendered = report.to_dict()
    assert rendered["series_basis"] == "unclamped"
    assert rendered["binding_cell"] == "incl@2x"
    assert "replayed sealed result" in str(rendered["gate9_disclosure"])


def test_the_binding_cell_is_the_worst_of_the_four_on_a_positive_expectancy_sample() -> None:
    """D2 §9.3's "by construction" claim, on a sample where it actually holds."""
    fx = _fx(short_fc=0.02, long_fc=0.01, under_fc=505.0)
    report = run_dual_spread(
        fx.chain,
        fx.underlying,
        _signal_fn,
        baseline=worked_example_cost_model(),
        stressed=worked_example_cost_model(spread_multiplier=2.0),
        warmup=0,
    )
    assert report.binding_cell.metrics.expectancy_r > 0.0
    assert report.binding_is_worst is True
    assert report.worst_cell.key == DualSpreadReport.BINDING_KEY


def test_the_report_says_so_when_the_binding_cell_is_not_the_numerically_worst() -> None:
    """On a negative-expectancy sample the larger denominator FLATTERS the result, so
    the "worst of the four" claim inverts.  Such a sample fails gates 3 and 4 on any
    basis, so nothing is weakened — but the record must not repeat a false claim."""
    fx = _fx()
    report = run_dual_spread(
        fx.chain,
        fx.underlying,
        _signal_fn,
        baseline=worked_example_cost_model(),
        stressed=worked_example_cost_model(spread_multiplier=2.0),
        warmup=0,
    )
    assert report.binding_cell.metrics.expectancy_r < 0.0
    assert report.binding_is_worst is False
    assert report.worst_cell.key == "at_print@2x"
    assert report.to_dict()["binding_is_worst"] is False


def test_the_stressed_run_may_differ_in_exactly_one_recorded_scalar() -> None:
    fx = _fx()
    tampered = replace(
        worked_example_cost_model(spread_multiplier=2.0), commission_per_contract=0.99
    )
    with pytest.raises(ValueError, match="spread_multiplier and nothing else"):
        run_dual_spread(
            fx.chain,
            fx.underlying,
            _signal_fn,
            baseline=worked_example_cost_model(),
            stressed=tampered,
            warmup=0,
        )
    with pytest.raises(ValueError, match="gate 4b"):
        run_dual_spread(
            fx.chain,
            fx.underlying,
            _signal_fn,
            baseline=worked_example_cost_model(spread_multiplier=2.0),
            stressed=worked_example_cost_model(spread_multiplier=2.0),
            warmup=0,
        )


def test_r_at_print_holds_the_denominator_still_across_the_two_spread_settings() -> None:
    fx = _fx()
    report = run_dual_spread(
        fx.chain,
        fx.underlying,
        _signal_fn,
        baseline=worked_example_cost_model(),
        stressed=worked_example_cost_model(spread_multiplier=2.0),
        warmup=0,
    )
    base_trade = report.baseline.trades[0]
    stress_trade = report.stressed.trades[0]
    assert base_trade.r_at_print == pytest.approx(stress_trade.r_at_print)
    assert base_trade.r_incl != pytest.approx(stress_trade.r_incl)
    # No gate binds on at_print; it is reported so the 1x -> 2x move is attributable
    # entirely to the numerator.
    assert (
        report.cells["at_print@1x"].metrics.expectancy_r
        > report.cells["at_print@2x"].metrics.expectancy_r
    )


def test_every_reported_cell_names_its_series_basis_as_unclamped() -> None:
    fx = _fx()
    report = run_dual_spread(
        fx.chain,
        fx.underlying,
        _signal_fn,
        baseline=worked_example_cost_model(),
        stressed=worked_example_cost_model(spread_multiplier=2.0),
        warmup=0,
    )
    for cell in report.cells.values():
        assert cell.series_basis == "unclamped"
        assert cell.metrics.expectancy_r < -1.0  # the unclamped breach survives
