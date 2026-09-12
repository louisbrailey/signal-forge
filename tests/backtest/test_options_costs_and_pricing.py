"""``OptionCostModel`` and the print-based fill model (D2 §6, §7).

The cost-model tests exist because a zero-defaulted cost model would make gate 4b
pass vacuously — ``2 x 0 == 0`` — on every options evaluation for the life of the
program (D2 §7.4).  There must be no path on which the constants go unchosen.
"""

from __future__ import annotations

import math
import re
from datetime import date

import pytest

from signalforge.backtest.options_costs import OptionCostModel, Side
from signalforge.backtest.options_pricing import (
    FILL_MODEL,
    IvSource,
    ZeroSpreadRefused,
    adverse_fill,
    intrinsic_per_share,
    mark_from_iv,
)
from signalforge.data.option_chain import ContractPrint, Mark, Right
from tests.options_chain_support import worked_example_cost_model


def _print(px: float) -> ContractPrint:
    return ContractPrint(open=px, high=px, low=px, close=px, volume=10.0)


# ---------------------------------------------------------------------------
# No defaults (D2 §7.1, §7.4 — §15.2 test 27)
# ---------------------------------------------------------------------------


def test_every_field_is_required() -> None:
    with pytest.raises(TypeError):
        OptionCostModel()  # type: ignore[call-arg]


def test_a_zero_spread_model_is_not_a_cost_model() -> None:
    with pytest.raises(ValueError, match="not a cost model"):
        OptionCostModel(
            commission_per_contract=0.0,
            commission_min_per_order=0.0,
            exchange_fee_per_contract=0.0,
            spread_pct_of_last_print=0.0,
            spread_abs_floor_cents=0.0,
            tick_grid=((math.inf, 0.01),),
            assignment_fee=0.0,
            exercise_fee=0.0,
            spread_multiplier=1.0,
        )


def test_spread_multiplier_is_one_or_two_and_nothing_else() -> None:
    with pytest.raises(ValueError, match="spread_multiplier"):
        worked_example_cost_model(spread_multiplier=1.5)


def test_the_tick_grid_must_be_a_total_function() -> None:
    with pytest.raises(ValueError, match=re.escape("math.inf")):
        OptionCostModel(
            commission_per_contract=0.65,
            commission_min_per_order=0.0,
            exchange_fee_per_contract=0.05,
            spread_pct_of_last_print=0.03,
            spread_abs_floor_cents=5.0,
            tick_grid=((3.0, 0.05),),
            assignment_fee=0.0,
            exercise_fee=0.0,
            spread_multiplier=1.0,
        )


def test_a_zero_spread_on_a_priced_leg_is_refused_one_layer_down() -> None:
    """Non-zero in the constructor, zero in practice — the constructor cannot see it."""
    cm = OptionCostModel(
        commission_per_contract=0.0,
        commission_min_per_order=0.0,
        exchange_fee_per_contract=0.0,
        spread_pct_of_last_print=0.03,
        spread_abs_floor_cents=0.0,  # no floor, so a $0.00 print yields a $0.00 spread
        tick_grid=((math.inf, 0.01),),
        assignment_fee=0.0,
        exercise_fee=0.0,
        spread_multiplier=1.0,
    )
    with pytest.raises(ZeroSpreadRefused):
        adverse_fill(
            _print(0.0),
            cm,
            side=Side.SELL,
            strike=500.0,
            right=Right.PUT,
            underlying_close=505.0,
            dte=30,
        )


# ---------------------------------------------------------------------------
# Cost arithmetic (D2 §7.2)
# ---------------------------------------------------------------------------


def test_commission_and_fees_scale_with_contract_sides() -> None:
    cm = worked_example_cost_model()
    assert cm.commission(4) == pytest.approx(2.60)
    assert cm.fees(4) == pytest.approx(0.20)
    assert cm.commission(0) == 0.0


def test_commission_honours_the_per_order_minimum() -> None:
    cm = OptionCostModel(
        commission_per_contract=0.10,
        commission_min_per_order=1.00,
        exchange_fee_per_contract=0.0,
        spread_pct_of_last_print=0.03,
        spread_abs_floor_cents=5.0,
        tick_grid=((math.inf, 0.01),),
        assignment_fee=0.0,
        exercise_fee=0.0,
        spread_multiplier=1.0,
    )
    assert cm.commission(2) == pytest.approx(1.00)


def test_the_spread_is_the_max_of_floor_and_percentage_times_the_multiplier() -> None:
    cm = worked_example_cost_model()
    assert cm.spread(2.00, moneyness=0.99, dte=30) == pytest.approx(0.06)
    assert cm.spread(0.90, moneyness=1.02, dte=30) == pytest.approx(0.05)  # floor binds
    stressed = worked_example_cost_model(spread_multiplier=2.0)
    assert stressed.spread(2.00, moneyness=0.99, dte=30) == pytest.approx(0.12)
    assert stressed.spread(0.90, moneyness=1.02, dte=30) == pytest.approx(0.10)


# ---------------------------------------------------------------------------
# The fill model (D2 §6.2, §6.3 — §15.2 tests 11, 28, 30)
# ---------------------------------------------------------------------------


def test_a_buy_crosses_up_and_a_sale_crosses_down_by_a_FULL_spread() -> None:
    cm = worked_example_cost_model()
    buy = adverse_fill(
        _print(2.00),
        cm,
        side=Side.BUY,
        strike=500.0,
        right=Right.PUT,
        underlying_close=505.0,
        dte=30,
    )
    sell = adverse_fill(
        _print(2.00),
        cm,
        side=Side.SELL,
        strike=500.0,
        right=Right.PUT,
        underlying_close=505.0,
        dte=30,
    )
    assert buy.price == pytest.approx(2.06)
    assert sell.price == pytest.approx(1.94)


def test_sale_proceeds_are_floored_at_zero_and_the_floor_is_counted() -> None:
    """The routine pathological case: a $0.05 wing against a $0.05 floor."""
    cm = worked_example_cost_model()
    fill = adverse_fill(
        _print(0.05),
        cm,
        side=Side.SELL,
        strike=495.0,
        right=Right.PUT,
        underlying_close=505.0,
        dte=5,
    )
    assert fill.price == 0.0
    assert fill.spread_ge_print is True
    assert fill.proceeds_floored_at_zero is False  # exactly zero, not negative
    deeper = adverse_fill(
        _print(0.04),
        cm,
        side=Side.SELL,
        strike=495.0,
        right=Right.PUT,
        underlying_close=505.0,
        dte=5,
    )
    assert deeper.price == 0.0
    assert deeper.proceeds_floored_at_zero is True


def test_tick_rounding_is_away_from_the_engine_on_both_sides() -> None:
    cm = OptionCostModel(
        commission_per_contract=0.0,
        commission_min_per_order=0.0,
        exchange_fee_per_contract=0.0,
        spread_pct_of_last_print=0.01,
        spread_abs_floor_cents=0.0,
        tick_grid=((math.inf, 0.05),),
        assignment_fee=0.0,
        exercise_fee=0.0,
        spread_multiplier=1.0,
    )
    # raw buy 2.02 -> rounds UP to 2.05; raw sale 1.98 -> rounds DOWN to 1.95
    buy = adverse_fill(
        _print(2.00),
        cm,
        side=Side.BUY,
        strike=500.0,
        right=Right.PUT,
        underlying_close=505.0,
        dte=30,
    )
    sell = adverse_fill(
        _print(2.00),
        cm,
        side=Side.SELL,
        strike=500.0,
        right=Right.PUT,
        underlying_close=505.0,
        dte=30,
    )
    assert buy.price == pytest.approx(2.05)
    assert sell.price == pytest.approx(1.95)
    assert cm.round_to_tick(2.05, side=Side.BUY) == pytest.approx(2.05)
    assert cm.round_to_tick(2.05, side=Side.SELL) == pytest.approx(2.05)


def test_the_intrinsic_floor_lifts_a_buy_back_and_never_a_sale() -> None:
    cm = worked_example_cost_model()
    buy = adverse_fill(
        _print(0.40),
        cm,
        side=Side.BUY,
        strike=500.0,
        right=Right.PUT,
        underlying_close=494.0,  # $6 intrinsic against a stale $0.40 print
        dte=1,
        apply_intrinsic_floor=True,
    )
    assert buy.price > 6.0
    assert buy.intrinsic_floor_applied is True

    sell = adverse_fill(
        _print(0.40),
        cm,
        side=Side.SELL,
        strike=500.0,
        right=Right.PUT,
        underlying_close=494.0,
        dte=1,
        apply_intrinsic_floor=True,  # ignored on a sale, by design
    )
    assert sell.price < 0.40
    assert sell.intrinsic_floor_applied is False
    assert sell.intrinsic_gap == pytest.approx(6.0 - sell.price)


# ---------------------------------------------------------------------------
# Types that forbid a class of bug (D2 §6.4, §6.6)
# ---------------------------------------------------------------------------


def test_iv_source_has_no_realized_vol_member() -> None:
    """Realised vol sits below implied on average; marking short premium at it would
    inflate simulated credit capture on exactly the trades the edge is claimed on."""
    assert "realized_vol" not in {m.value for m in IvSource}
    assert not hasattr(IvSource, "REALIZED_VOL")


def test_a_mark_can_never_be_filled_on() -> None:
    cm = worked_example_cost_model()
    mark = mark_from_iv(
        505.0, 500.0, 0.1, 0.04, 0.20, right=Right.PUT, q=0.0, iv_source=IvSource.LOCAL_BS_INVERTED
    )
    assert isinstance(mark, Mark)
    assert mark.iv_source == IvSource.LOCAL_BS_INVERTED.value
    with pytest.raises(TypeError, match="Mark"):
        adverse_fill(
            mark,  # type: ignore[arg-type]
            cm,
            side=Side.BUY,
            strike=500.0,
            right=Right.PUT,
            underlying_close=505.0,
            dte=30,
        )


def test_intrinsic_uses_the_shared_black_scholes_convention() -> None:
    assert intrinsic_per_share(494.0, 500.0, Right.PUT) == pytest.approx(6.0)
    assert intrinsic_per_share(505.0, 500.0, Right.PUT) == pytest.approx(0.0)
    assert intrinsic_per_share(505.0, 500.0, Right.CALL) == pytest.approx(5.0)


def test_the_fill_model_label_carries_both_disclosures() -> None:
    assert "print_not_mid" in FILL_MODEL
    assert "close_basis_stop" in FILL_MODEL
    assert "PLACEHOLDER" in FILL_MODEL
    assert "equities" in FILL_MODEL  # the 403 applies to BOTH asset classes


def test_moneyness_refuses_a_non_positive_underlying() -> None:
    cm = worked_example_cost_model()
    with pytest.raises(ValueError, match="underlying_close"):
        adverse_fill(
            _print(1.0),
            cm,
            side=Side.BUY,
            strike=500.0,
            right=Right.PUT,
            underlying_close=0.0,
            dte=date(2024, 1, 1).day,
        )
