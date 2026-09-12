"""I-O3 engine tests (D2 §15.2), on hand-built synthetic chains.

The max-loss fixture reproduces D2 §9.3's **published** arithmetic exactly —
entry costs $12.40, exit costs $34.40 at 1x and $23.40 / $67.40 at 2x, giving
``pnl_r`` of −1.086 / −1.120 (1x) and −1.163 / −1.233 (2x).  If the engine and the
document ever disagree, one of them is wrong and this test says which numbers were
claimed.
"""

from __future__ import annotations

from datetime import date

import pytest

from signalforge.backtest.metrics import compute_metrics
from signalforge.backtest.montecarlo import bootstrap_ci
from signalforge.backtest.options_engine import (
    DteBasis,
    ExitReason,
    OptionLeg,
    OptionsCounters,
    OptionStructure,
    RBasis,
    StructureRefused,
    StructureType,
    run_options_backtest,
    simulate_structure,
)
from tests.options_chain_support import (
    EXPIRY,
    LONG_STRIKE,
    LONG_TICKER,
    SHORT_STRIKE,
    SHORT_TICKER,
    ChainFixture,
    build_fixture,
    credit_spread,
    put_contract,
    sessions_between,
    signal_at,
    worked_example_cost_model,
)

FORCE_CLOSE = date(2024, 3, 14)
FIRST = date(2024, 2, 1)
LAST = date(2024, 3, 20)


def _fixture(
    *,
    short_by_date: dict[date, float] | None = None,
    long_by_date: dict[date, float] | None = None,
    underlying_by_date: dict[date, float] | None = None,
    drop_short: set[date] = frozenset(),
    drop_long: set[date] = frozenset(),
    base_short: float = 2.00,
    base_long: float = 0.90,
    base_underlying: float = 505.0,
) -> ChainFixture:
    dates = sessions_between(FIRST, LAST)
    shorts = dict.fromkeys(dates, base_short) | (short_by_date or {})
    longs = dict.fromkeys(dates, base_long) | (long_by_date or {})
    unders = dict.fromkeys(dates, base_underlying) | (underlying_by_date or {})
    for d in drop_short:
        shorts.pop(d, None)
    for d in drop_long:
        longs.pop(d, None)
    return build_fixture(
        dates,
        unders,
        {SHORT_TICKER: shorts, LONG_TICKER: longs},
        [
            put_contract(SHORT_TICKER, SHORT_STRIKE, dates[0]),
            put_contract(LONG_TICKER, LONG_STRIKE, dates[0]),
        ],
    )


def _max_loss_fixture() -> ChainFixture:
    """Benign until the force-close session, where the structure is worth full width."""
    return _fixture(
        short_by_date={FORCE_CLOSE: 8.00},
        long_by_date={FORCE_CLOSE: 3.00},
        underlying_by_date={FORCE_CLOSE: 492.0},
    )


def _simulate(fx: ChainFixture, signal=None, *, cost_model=None, r_basis=RBasis.INCL):
    counters = OptionsCounters()
    trade, excluded, exit_idx = simulate_structure(
        fx.chain,
        signal or signal_at(0),
        cost_model=cost_model or worked_example_cost_model(),
        r_basis=r_basis,
        counters=counters,
    )
    return trade, excluded, exit_idx, counters


# ---------------------------------------------------------------------------
# Structure validation (D2 §4.2, §15.2 test 2)
# ---------------------------------------------------------------------------


def test_naked_short_is_not_representable() -> None:
    short = put_contract(SHORT_TICKER, SHORT_STRIKE, FIRST)
    with pytest.raises(StructureRefused):
        OptionStructure(
            structure_type=StructureType.VERTICAL_CREDIT,
            underlying_symbol="SPY",
            legs=(OptionLeg(short, -1),),
            contracts=1,
        )


def test_inverted_wings_are_refused() -> None:
    # A "long" wing sitting ABOVE the short put strike is not defined risk.
    short = put_contract(SHORT_TICKER, 495.0, FIRST)
    wrong = put_contract(LONG_TICKER, 500.0, FIRST)
    with pytest.raises(StructureRefused):
        credit_spread(short=short, long_=wrong)


def test_mixed_expirations_and_underlyings_are_refused() -> None:
    short = put_contract(SHORT_TICKER, SHORT_STRIKE, FIRST)
    other_expiry = put_contract(LONG_TICKER, LONG_STRIKE, FIRST, expiration=date(2024, 4, 19))
    with pytest.raises(StructureRefused):
        credit_spread(short=short, long_=other_expiry)
    other_underlying = put_contract(LONG_TICKER, LONG_STRIKE, FIRST, underlying="QQQ")
    with pytest.raises(StructureRefused):
        credit_spread(short=short, long_=other_underlying)


def test_deliverable_and_style_refusals_are_named_counters() -> None:
    short = put_contract(SHORT_TICKER, SHORT_STRIKE, FIRST, shares_per_contract=90)
    with pytest.raises(StructureRefused) as exc:
        credit_spread(short=short)
    assert exc.value.counter == "shares_per_contract_refusals"

    euro = put_contract(SHORT_TICKER, SHORT_STRIKE, FIRST, exercise_style="european")
    with pytest.raises(StructureRefused) as exc2:
        credit_spread(short=euro)
    assert exc2.value.counter == "exercise_style_refusals"


def test_zero_qty_leg_is_refused() -> None:
    short = put_contract(SHORT_TICKER, SHORT_STRIKE, FIRST)
    long_ = put_contract(LONG_TICKER, LONG_STRIKE, FIRST)
    with pytest.raises(StructureRefused):
        OptionStructure(
            structure_type=StructureType.VERTICAL_CREDIT,
            underlying_symbol="SPY",
            legs=(OptionLeg(short, -1), OptionLeg(long_, 0)),
            contracts=1,
        )


def test_multiplier_is_read_per_leg_not_from_a_module_constant() -> None:
    leg = OptionLeg(put_contract(SHORT_TICKER, SHORT_STRIKE, FIRST, shares_per_contract=100), -1)
    assert leg.multiplier == leg.contract.shares_per_contract


def test_unimplemented_structure_types_are_refused() -> None:
    short = put_contract(SHORT_TICKER, SHORT_STRIKE, FIRST)
    with pytest.raises(StructureRefused):
        OptionStructure(
            structure_type=StructureType.CASH_SECURED_PUT,
            underlying_symbol="SPY",
            legs=(OptionLeg(short, -1),),
            contracts=1,
        )


# ---------------------------------------------------------------------------
# R, the two bases, and the published worked example (D2 §9.2, §9.3)
# ---------------------------------------------------------------------------


def test_max_loss_reproduces_the_published_worked_arithmetic() -> None:
    trade, excluded, _, counters = _simulate(_max_loss_fixture())
    assert excluded is None
    assert trade is not None
    assert trade.exit_reason is ExitReason.FORCE_CLOSE
    assert trade.net_credit_at_print == pytest.approx(110.0)
    assert trade.net_credit_received == pytest.approx(99.0)
    assert trade.entry_costs == pytest.approx(12.40)
    assert trade.exit_costs == pytest.approx(34.40)
    assert trade.r_at_print == pytest.approx(390.0)
    assert trade.r_incl == pytest.approx(402.40)
    assert trade.pnl_dollars == pytest.approx(-436.80)
    assert trade.pnl_r_incl == pytest.approx(-1.086, abs=1e-3)
    assert trade.pnl_r_at_print == pytest.approx(-1.120, abs=1e-3)
    # The -1 bound is BREACHED, not enforced; the clamp is a label only.
    assert trade.r_clamped is True
    assert trade.pnl_r == trade.pnl_r_incl
    assert trade.pnl_r_clamped == pytest.approx(-1.0)
    assert counters.r_clamped == 1
    # The stop did not protect: the realised loss is worse than stop x credit.
    assert trade.stop_non_binding is True


def test_two_x_spread_reproduces_the_published_stressed_arithmetic() -> None:
    trade, _, _, _ = _simulate(
        _max_loss_fixture(), cost_model=worked_example_cost_model(spread_multiplier=2.0)
    )
    assert trade is not None
    assert trade.net_credit_received == pytest.approx(88.0)
    assert trade.entry_costs == pytest.approx(23.40)
    assert trade.exit_costs == pytest.approx(67.40)
    assert trade.pnl_dollars == pytest.approx(-480.80)
    assert trade.r_incl == pytest.approx(413.40)
    assert trade.pnl_r_incl == pytest.approx(-1.163, abs=1e-3)
    assert trade.pnl_r_at_print == pytest.approx(-1.233, abs=1e-3)


def test_r_at_print_is_invariant_to_spread_multiplier_and_r_incl_is_not() -> None:
    """D2 §15.2 test 13.  Rev 1's form of this test, written against a denominator
    built from the credit *received*, would have failed — the received credit is
    already spread-adjusted."""
    base, _, _, _ = _simulate(_max_loss_fixture())
    stressed, _, _, _ = _simulate(
        _max_loss_fixture(), cost_model=worked_example_cost_model(spread_multiplier=2.0)
    )
    assert base is not None and stressed is not None
    assert base.r_at_print == pytest.approx(stressed.r_at_print)
    assert base.r_incl != pytest.approx(stressed.r_incl)


def test_cost_scales_with_legs_times_contracts_times_sides() -> None:
    """A 2-leg vertical round trip charges four full modelled spreads (D2 §7.2)."""
    trade, _, _, counters = _simulate(_max_loss_fixture())
    assert trade is not None
    assert counters.leg_sides_priced == 4
    # entry: two spreads ($6 + $5) + commission 2 x 0.65 + fees 2 x 0.05
    assert trade.entry_costs == pytest.approx(6.0 + 5.0 + 1.30 + 0.10)
    assert trade.exit_costs == pytest.approx(24.0 + 9.0 + 1.30 + 0.10)


def test_two_contracts_scale_every_dollar_figure_linearly() -> None:
    fx = _max_loss_fixture()
    one, _, _, _ = _simulate(fx)
    two, _, _, _ = _simulate(fx, signal_at(0, credit_spread(contracts=2)))
    assert one is not None and two is not None
    assert two.r_incl == pytest.approx(2 * one.r_incl)
    assert two.pnl_dollars == pytest.approx(2 * one.pnl_dollars)
    assert two.pnl_r_incl == pytest.approx(one.pnl_r_incl)


# ---------------------------------------------------------------------------
# Exit resolution: precedence and timing (D2 §10.1)
# ---------------------------------------------------------------------------


def test_spread_expiring_worthless_is_a_win_net_of_four_spreads() -> None:
    fx = _fixture(
        short_by_date={FORCE_CLOSE: 0.02},
        long_by_date={FORCE_CLOSE: 0.01},
    )
    trade, _, _, _ = _simulate(fx)
    assert trade is not None
    assert trade.exit_reason is ExitReason.FORCE_CLOSE
    assert trade.pnl_dollars > 0.0
    assert trade.pnl_r_incl == pytest.approx((99.0 - 7.0 - 2.80) / 402.40, abs=1e-9)
    assert trade.r_clamped is False


def test_a_triggered_stop_fills_at_t_plus_one_not_at_the_triggering_close() -> None:
    """D2 §15.2 test 25.  There is no resting stop order anywhere in this design."""
    dates = sessions_between(FIRST, LAST)
    trigger_day, fill_day = dates[10], dates[11]
    fx = _fixture(
        short_by_date={trigger_day: 4.00, fill_day: 4.50},
        long_by_date={trigger_day: 0.90, fill_day: 0.95},
    )
    trade, _, exit_idx, _ = _simulate(fx)
    assert trade is not None
    assert trade.exit_reason is ExitReason.STOP
    assert exit_idx == 11
    assert trade.exit_date == fill_day  # the session AFTER the trigger
    assert trade.exit_deferred_sessions == 0


def test_a_profit_target_also_fills_at_t_plus_one() -> None:
    dates = sessions_between(FIRST, LAST)
    trigger_day, fill_day = dates[6], dates[7]
    fx = _fixture(
        short_by_date={trigger_day: 1.00, fill_day: 0.95},
        long_by_date={trigger_day: 0.60, fill_day: 0.58},
    )
    trade, _, _, _ = _simulate(fx)
    assert trade is not None
    assert trade.exit_reason is ExitReason.PROFIT_TARGET
    assert trade.exit_date == fill_day


def test_a_time_stop_is_calendar_knowable_and_fills_at_its_own_session() -> None:
    fx = _fixture()
    sig = signal_at(0, time_stop_dte=10, time_stop_dte_basis=DteBasis.CALENDAR)
    trade, _, _, _ = _simulate(fx, sig)
    assert trade is not None
    assert trade.exit_reason is ExitReason.TIME_STOP
    assert (EXPIRY - trade.exit_date).days <= 10
    assert trade.exit_deferred_sessions == 0


def test_force_close_takes_precedence_on_the_expiry_minus_one_session() -> None:
    trade, _, _, _ = _simulate(_max_loss_fixture())
    assert trade is not None
    assert trade.exit_date == FORCE_CLOSE
    assert trade.exit_reason is ExitReason.FORCE_CLOSE


def test_a_triggered_exit_with_a_missing_leg_defers_and_is_counted() -> None:
    dates = sessions_between(FIRST, LAST)
    trigger_day, blocked, fill_day = dates[10], dates[11], dates[12]
    fx = _fixture(
        short_by_date={trigger_day: 4.00, fill_day: 4.20},
        drop_short={blocked},
    )
    trade, _, _, counters = _simulate(fx)
    assert trade is not None
    assert trade.exit_date == fill_day
    assert trade.exit_deferred_sessions == 1
    assert counters.exit_deferred_sessions == [1]
    assert trade.unmarked_sessions == 1


# ---------------------------------------------------------------------------
# Missing bars: non-entry, unmarked sessions, exclusions (D2 §6.4, §10.2)
# ---------------------------------------------------------------------------


def test_a_missing_leg_bar_on_the_entry_session_is_a_non_entry() -> None:
    dates = sessions_between(FIRST, LAST)
    fx = _fixture(drop_long={dates[1]})
    trade, excluded, _, counters = _simulate(fx)
    assert trade is None and excluded is None
    assert counters.non_entry_missing_leg_bar == 1


def test_an_unpriceable_force_close_excludes_the_cycle_and_measures_its_bias() -> None:
    fx = _fixture(drop_long={FORCE_CLOSE})
    trade, excluded, _, counters = _simulate(fx)
    assert trade is None
    assert excluded is not None
    assert excluded.reason == "force_close_unpriceable"
    assert counters.force_close_unpriceable_exclusions == 1
    # Intrinsic-at-expiry from the underlying alone: S=505 leaves both puts OTM,
    # so the excluded cycle would have kept the whole print credit.
    assert excluded.intrinsic_pnl_r == pytest.approx(110.0 / 402.40, abs=1e-9)


def test_a_mark_only_session_fires_no_trigger_and_increments_unmarked_sessions() -> None:
    """D2 §15.2 test 24.  A session the engine cannot price from prints contributes
    nothing: no mark, no unrealised value, and it can fire neither the stop nor the
    profit target."""
    dates = sessions_between(FIRST, LAST)
    gap = dates[5]
    fx = _fixture(short_by_date={gap: 99.0}, drop_long={gap})
    trade, _, _, _ = _simulate(fx)
    assert trade is not None
    # The 99.0 short print would trip the stop if a one-legged premium were used.
    assert trade.exit_reason is ExitReason.FORCE_CLOSE
    assert trade.unmarked_sessions == 1


# ---------------------------------------------------------------------------
# Intrinsic floor, pin band, assignment (D2 §10.3, §10.4, §10.6)
# ---------------------------------------------------------------------------


def test_a_stale_deep_itm_short_print_cannot_produce_a_fictional_profit() -> None:
    """The short leg is never bought back below intrinsic (D2 §10.3)."""
    stale = _fixture(
        short_by_date={FORCE_CLOSE: 0.40},
        long_by_date={FORCE_CLOSE: 0.10},
        underlying_by_date={FORCE_CLOSE: 494.0},  # short put $6 in the money
    )
    trade, _, _, _ = _simulate(stale)
    assert trade is not None
    assert trade.pnl_dollars < 0.0
    # The floor lifted the buy-back from $0.40 to $6.00 intrinsic.
    assert trade.exit_costs > 6.0


def test_the_intrinsic_floor_is_buy_side_only_and_the_gap_is_measured() -> None:
    """D2 §15.2 test 30.  Applying the floor to a leg being SOLD would raise assumed
    proceeds, which is favourable to the strategy, not conservative."""
    fx = _fixture(
        short_by_date={FORCE_CLOSE: 8.00},
        long_by_date={FORCE_CLOSE: 0.10},  # stale long print, deeply ITM
        underlying_by_date={FORCE_CLOSE: 492.0},  # long put $3 in the money
    )
    trade, _, _, counters = _simulate(fx)
    assert trade is not None
    # long leg sold at its stale print minus a spread, NOT lifted to intrinsic
    assert counters.long_leg_intrinsic_gap_dollars > 250.0


def test_a_pinned_force_close_is_flagged() -> None:
    fx = _fixture(
        short_by_date={FORCE_CLOSE: 0.60},
        long_by_date={FORCE_CLOSE: 0.10},
        underlying_by_date={FORCE_CLOSE: 500.5},
    )
    trade, _, _, counters = _simulate(fx)
    assert trade is not None
    assert trade.pin_risk_flag is True
    assert counters.pin_risk_flag == 1


def test_assignment_risk_is_recorded_not_modelled() -> None:
    dates = sessions_between(FIRST, LAST)
    deep = dates[8]
    fx = _fixture(underlying_by_date={deep: 480.0})
    sig = signal_at(0, stop_multiple_of_credit=100.0, assignment_itm_threshold_pct=0.01)
    trade, _, _, counters = _simulate(fx, sig)
    assert trade is not None
    assert trade.assignment_risk is True
    assert counters.assignment_risk == 1


# ---------------------------------------------------------------------------
# Gate-facing series: the clamp is a label, never the gated data (D2 §9.4)
# ---------------------------------------------------------------------------


def test_the_gate_statistic_moves_when_a_sub_minus_one_r_trade_is_present() -> None:
    """D2 §15.2 test 26: gates consume the UNCLAMPED series."""
    trade, _, _, _ = _simulate(_max_loss_fixture())
    assert trade is not None
    unclamped = [trade.pnl_r]
    clamped = [trade.pnl_r_clamped]
    assert unclamped[0] < clamped[0]
    assert (
        bootstrap_ci(unclamped)["expectancy_r"]["point"]
        < bootstrap_ci(clamped)["expectancy_r"]["point"]
    )
    # compute_metrics runs over the trade objects themselves, unclamped.
    assert compute_metrics([trade]).expectancy_r == pytest.approx(trade.pnl_r)


# ---------------------------------------------------------------------------
# The loop (D2 §12.4)
# ---------------------------------------------------------------------------


def test_the_loop_hands_the_strategy_a_truncated_view_and_goes_flat_between_cycles() -> None:
    fx = _max_loss_fixture()
    seen: list[int] = []

    def signal_fn(chain, underlying, t):
        seen.append(len(chain))
        assert len(chain) == t + 1
        assert len(underlying) == t + 1
        return signal_at(t) if t == 0 else None

    outcome = run_options_backtest(
        fx.chain, fx.underlying, signal_fn, cost_model=worked_example_cost_model(), warmup=0
    )
    assert len(outcome.trades) == 1
    assert seen[0] == 1
    # Re-entry only resumes after the cycle closed — no overlapping positions.
    exit_idx = fx.index_of(outcome.trades[0].exit_date)
    assert max(seen) - 1 > exit_idx


def test_the_loop_counts_a_structure_refusal_raised_by_the_strategy() -> None:
    fx = _max_loss_fixture()

    def signal_fn(chain, underlying, t):
        if t == 0:
            raise StructureRefused("shares_per_contract_refusals", "vendor omitted the field")
        return None

    outcome = run_options_backtest(
        fx.chain, fx.underlying, signal_fn, cost_model=worked_example_cost_model(), warmup=0
    )
    assert outcome.trades == []
    assert outcome.counters.shares_per_contract_refusals == 1


def test_the_engine_refuses_a_chain_and_underlying_of_different_length() -> None:
    fx = _max_loss_fixture()
    with pytest.raises(ValueError, match="same session list"):
        run_options_backtest(
            fx.chain,
            fx.underlying.head(5),
            lambda c, u, t: None,
            cost_model=worked_example_cost_model(),
        )


def test_an_option_trade_carries_the_four_fields_the_metrics_stack_reads() -> None:
    trade, _, _, _ = _simulate(_max_loss_fixture())
    assert trade is not None
    for field_name in ("entry_date", "exit_date", "pnl_r", "bars_held"):
        assert hasattr(trade, field_name)
    assert isinstance(trade.entry_date, date)
    assert trade.bars_held >= 1
    # structure_type and r_basis are REQUIRED fields so a statistic can never be
    # computed over a pooled R stream without the pooling being visible (D2 §9.5).
    assert trade.structure_type is StructureType.VERTICAL_CREDIT
    assert trade.r_basis is RBasis.INCL
    assert compute_metrics([trade]).n_trades == 1
