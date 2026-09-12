"""D6 §4.1 — "notional", defined per structure type, with the worked arithmetic.

An undefined word in a limit is not a limit: for decision 12's short vertical the
candidate readings of "notional" span two orders of magnitude (net credit
~$50-150, max loss $350, gross short-leg strike value $60k+), so a cap written
against the bare word is either inert or a total ban depending on who implements
it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from signalforge.execution.intents import (
    ComboOrderIntent,
    CostModelFeedback,
    IntentKind,
    IntentRefused,
    OrderIntent,
    OrderLeg,
    OrderSide,
    StructureType,
    UndefinedNotional,
    client_order_id_for,
    combo_notional,
    compute_expires_at,
    single_notional,
)

NOW = datetime(2026, 9, 11, 15, 0, tzinfo=UTC)
COSTS = CostModelFeedback(modelled_fill_price=1.50, modelled_spread_bps=5.0)


def _ticker(strike: float) -> str:
    return f"O:SPY260918P{int(strike * 1000):08d}"


def _vertical(
    *,
    short_strike: float = 470.0,
    long_strike: float = 465.0,
    net_credit: float = 1.50,
    contracts: int = 1,
    structure: StructureType = StructureType.SHORT_VERTICAL,
    spc: int = 100,
) -> ComboOrderIntent:
    legs = (
        OrderLeg(
            side=OrderSide.SELL_TO_OPEN,
            ratio=1,
            shares_per_contract=spc,
            option_ticker=_ticker(short_strike),
            strike=short_strike,
        ),
        OrderLeg(
            side=OrderSide.BUY_TO_OPEN,
            ratio=1,
            shares_per_contract=spc,
            option_ticker=_ticker(long_strike),
            strike=long_strike,
        ),
    )
    return ComboOrderIntent(
        client_order_id="x" * 32,
        intent_kind=IntentKind.OPEN,
        legs=legs,
        contracts=contracts,
        net_limit_price=net_credit,
        structure_type=structure,
        adapter_name="paper_reference",
        created_at=NOW,
        expires_at=NOW + timedelta(minutes=15),
        cost_model=COSTS,
    )


def test_the_worked_o3_example_from_the_adr() -> None:
    """5-wide SPY put credit spread, 1 contract, net credit $1.50:
    max loss = (5.00 - 1.50) * 100 * 1 = $350, and that IS the notional."""
    assert combo_notional(_vertical()) == pytest.approx(350.0)


def test_notional_is_not_the_net_credit_and_not_the_gross_strike_value() -> None:
    notional = combo_notional(_vertical())
    net_credit = 1.50 * 100
    gross_short_strike = 470.0 * 100
    assert notional != pytest.approx(net_credit)  # trivially passes every cap
    assert notional != pytest.approx(gross_short_strike)  # blocks every spread
    assert net_credit < notional < gross_short_strike


def test_the_worked_example_against_the_operator_limits() -> None:
    """§4.1's arithmetic, reproduced: $350 passes the $1,000 per-order cap and
    fails both the $250 per-structure max loss and the 0.5%-of-$25,000 ($125)
    percent form."""
    notional = combo_notional(_vertical())
    assert notional <= 1_000.0  # decision 4 per-order notional cap
    assert notional > 250.0  # decision 4 per-structure max loss
    assert notional > 0.005 * 25_000.0  # map §3.2 percent form


def test_notional_scales_with_contracts() -> None:
    assert combo_notional(_vertical(contracts=3)) == pytest.approx(1_050.0)


def test_a_credit_wider_than_the_spread_has_no_defined_max_loss() -> None:
    with pytest.raises(UndefinedNotional, match="max loss"):
        combo_notional(_vertical(net_credit=5.0))


def test_a_debit_is_not_a_short_vertical() -> None:
    with pytest.raises(UndefinedNotional, match="positive net credit"):
        combo_notional(_vertical(net_credit=-1.0))


def test_a_zero_width_vertical_is_refused() -> None:
    with pytest.raises(UndefinedNotional, match="strike width"):
        combo_notional(_vertical(long_strike=470.0))


def test_a_vertical_without_strikes_is_refused() -> None:
    intent = _vertical()
    stripped = tuple(
        OrderLeg(
            side=leg.side,
            ratio=leg.ratio,
            shares_per_contract=leg.shares_per_contract,
            option_ticker=leg.option_ticker,
        )
        for leg in intent.legs
    )
    with pytest.raises(UndefinedNotional, match="strike on every leg"):
        combo_notional(_vertical_with_legs(intent, stripped))


def _vertical_with_legs(intent: ComboOrderIntent, legs: tuple[OrderLeg, ...]) -> ComboOrderIntent:
    from dataclasses import replace

    return replace(intent, legs=legs)


def test_cash_secured_put_notional_is_full_collateral() -> None:
    legs = (
        OrderLeg(
            side=OrderSide.SELL_TO_OPEN,
            ratio=1,
            shares_per_contract=100,
            option_ticker="O:SPY260918P00470000",
            strike=470.0,
        ),
        OrderLeg(
            side=OrderSide.BUY_TO_OPEN,
            ratio=1,
            shares_per_contract=100,
            option_ticker="O:SPY260918P00400000",
            strike=400.0,
        ),
    )
    intent = _vertical_with_legs(_vertical(structure=StructureType.CASH_SECURED_PUT), legs)
    assert combo_notional(intent) == pytest.approx(47_000.0)


def test_covered_call_notional_is_the_underlying_market_value() -> None:
    from dataclasses import replace

    intent = replace(
        _vertical(structure=StructureType.COVERED_CALL), underlying_reference_price=471.0
    )
    assert combo_notional(intent) == pytest.approx(47_100.0)


def test_a_covered_call_without_an_underlying_price_is_refused() -> None:
    with pytest.raises(UndefinedNotional, match="underlying"):
        combo_notional(_vertical(structure=StructureType.COVERED_CALL))


def test_a_structure_with_no_row_in_the_table_cannot_produce_a_notional() -> None:
    """The fail-closed form: a new structure requires an explicit definition in
    §4.1 BEFORE it can be built, never a default."""
    from dataclasses import replace

    intent = replace(_vertical(), structure_type="iron_condor")  # type: ignore[arg-type]
    with pytest.raises(UndefinedNotional, match="no notional definition"):
        combo_notional(intent)


def test_equity_notional_is_qty_times_price() -> None:
    assert single_notional(10, 471.0, 1) == pytest.approx(4_710.0)
    assert single_notional(2, 1.50, 100) == pytest.approx(300.0)


def test_an_equity_intent_reports_its_own_notional() -> None:
    intent = OrderIntent(
        client_order_id="y" * 32,
        intent_kind=IntentKind.OPEN,
        side=OrderSide.BUY_TO_OPEN,
        qty=10,
        limit_price=471.0,
        shares_per_contract=1,
        adapter_name="paper_reference",
        created_at=NOW,
        expires_at=NOW + timedelta(minutes=15),
        cost_model=COSTS,
        symbol="SPY",
    )
    assert intent.max_notional == pytest.approx(4_710.0)


# --- leg invariants --------------------------------------------------------


def test_a_non_standard_deliverable_is_refused_at_intent_time() -> None:
    """A non-100 deliverable is the machine-readable signature of an OCC
    adjustment (§14 rule 5)."""
    with pytest.raises(IntentRefused, match="OCC adjustment"):
        OrderLeg(
            side=OrderSide.SELL_TO_OPEN,
            ratio=1,
            shares_per_contract=110,
            option_ticker="O:SPY260918P00470000",
        )


def test_a_leg_carries_exactly_one_instrument() -> None:
    with pytest.raises(IntentRefused):
        OrderLeg(side=OrderSide.BUY_TO_OPEN, ratio=1, shares_per_contract=1)
    with pytest.raises(IntentRefused):
        OrderLeg(
            side=OrderSide.BUY_TO_OPEN,
            ratio=1,
            shares_per_contract=1,
            symbol="SPY",
            option_ticker="O:SPY260918P00470000",
        )


def test_a_combo_needs_at_least_two_legs() -> None:
    with pytest.raises(IntentRefused, match="at least two legs"):
        _vertical_with_legs(_vertical(), (_vertical().legs[0],))


# --- idempotency and expiry -----------------------------------------------


def test_the_client_order_id_is_deterministic_and_carries_no_attempt_counter() -> None:
    legs = _vertical().legs
    first = client_order_id_for(source_trade_id=7, legs=legs)
    second = client_order_id_for(source_trade_id=7, legs=legs)
    assert first == second


def test_two_different_structures_on_one_paper_trade_do_not_collide() -> None:
    a = client_order_id_for(source_trade_id=7, legs=_vertical().legs)
    b = client_order_id_for(
        source_trade_id=7, legs=_vertical(short_strike=475.0, long_strike=470.0).legs
    )
    c = client_order_id_for(source_trade_id=8, legs=_vertical().legs)
    assert len({a, b, c}) == 3


def test_expiry_is_the_earlier_of_the_session_end_and_the_age_cap() -> None:
    assert compute_expires_at(
        created_at=NOW, max_intent_age_minutes=15, session_end_utc=NOW + timedelta(hours=2)
    ) == NOW + timedelta(minutes=15)
    assert compute_expires_at(
        created_at=NOW, max_intent_age_minutes=180, session_end_utc=NOW + timedelta(hours=1)
    ) == NOW + timedelta(hours=1)
    assert compute_expires_at(
        created_at=NOW, max_intent_age_minutes=15, session_end_utc=None
    ) == NOW + timedelta(minutes=15)
