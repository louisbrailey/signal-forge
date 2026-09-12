"""D6 §10 — the OMS reconstructs position origin; the broker never owes it.

The gap this closes, in one sentence: ``PositionSnapshot`` carries no
``originating_client_order_id``, ``reconcile()`` treats its absence as a
``FOREIGN_POSITION``, and nothing in ``src/`` performed the reconstruction §10
assigns to the OMS — so an adapter could reconcile CLEAN only while flat, and an
adapter that diverges the moment it fills is an adapter that cannot be armed.

What is asserted here is the boundary, not the happy path: attribution explains a
position from the OMS's OWN pre-submission records, exactly, or it does not
explain it at all. There is no partial credit and no repair anywhere in this
file, because an automatic reconciliation fix is an unreviewed order.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy.orm import Session

from signalforge.execution import oms
from signalforge.execution.events import ExecutionEventType, record_execution_event
from signalforge.execution.intents import (
    CostModelFeedback,
    IntentKind,
    OrderIntent,
    OrderLeg,
    OrderSide,
    PositionLeg,
    PositionSnapshot,
    StructureType,
)
from signalforge.execution.states import OrderState
from tests.execution.conftest import ADAPTER, NOW

SHORT_PUT = "SPY261218P00460000"
LONG_PUT = "SPY261218P00455000"


def _equity_intent(
    client_order_id: str, *, qty: int = 10, side: OrderSide | None = None
) -> OrderIntent:
    return OrderIntent(
        client_order_id=client_order_id,
        intent_kind=IntentKind.OPEN,
        side=side or OrderSide.BUY_TO_OPEN,
        qty=qty,
        limit_price=475.0,
        shares_per_contract=1,
        adapter_name=ADAPTER,
        created_at=NOW,
        expires_at=NOW + timedelta(minutes=15),
        cost_model=CostModelFeedback(modelled_fill_price=470.0, modelled_spread_bps=5.0),
        symbol="SPY",
        state=OrderState.VALIDATED,
    )


def _snapshot(*legs: PositionLeg) -> PositionSnapshot:
    return PositionSnapshot(adapter_name=ADAPTER, legs=tuple(legs))


def _fill(session: Session, client_order_id: str, *, units: float, state: OrderState) -> None:
    """What an adapter writes back after a fill: the size, and the transition."""
    record_execution_event(
        session,
        event_type=ExecutionEventType.FILL,
        adapter_name=ADAPTER,
        client_order_id=client_order_id,
        state_from=OrderState.SUBMITTING.value,
        state_to=state.value,
        payload={"filled_units": units},
    )


def _submit(session: Session, intent: OrderIntent) -> OrderIntent:
    submitted = oms.record_submitting(session, intent)
    assert isinstance(submitted, OrderIntent)
    return submitted


def test_the_submitting_record_carries_the_leg_composition(session: Session) -> None:
    """The reconstruction is only possible because the OMS writes down what it
    authorised BEFORE submitting it."""
    _submit(session, _equity_intent("cid-legs"))

    from sqlalchemy import select

    from signalforge.db.models import ExecutionEvent

    payload = session.scalar(
        select(ExecutionEvent.payload_json).where(
            ExecutionEvent.client_order_id == "cid-legs",
            ExecutionEvent.event_type == ExecutionEventType.SUBMITTING.value,
        )
    )
    assert payload[oms.SUBMITTED_UNITS_KEY] == 10
    assert payload[oms.SUBMITTED_LEGS_KEY] == [
        {"instrument_key": "SPY", "sign": 1, "ratio": 1, "shares_per_contract": 1}
    ]


def test_a_filled_order_explains_the_position_it_opened(session: Session) -> None:
    _submit(session, _equity_intent("cid-open"))
    _fill(session, "cid-open", units=10, state=OrderState.FILLED)

    attributed = oms.attribute_positions(
        session,
        adapter_name=ADAPTER,
        positions=[_snapshot(PositionLeg(instrument_key="SPY", signed_qty=10.0))],
    )

    assert len(attributed) == 1
    assert attributed[0].originating_client_order_id == "cid-open"
    assert attributed[0].contributing_client_order_ids == ("cid-open",)
    assert attributed[0].unexplained == ()
    assert attributed[0].attributed


def test_the_earliest_contributing_order_is_the_originating_one(session: Session) -> None:
    """Two orders in the same instrument net to one broker leg. The one that
    OPENED it is the id the position is attributed to; the later one added."""
    _submit(session, _equity_intent("cid-first", qty=10))
    _fill(session, "cid-first", units=10, state=OrderState.FILLED)
    _submit(session, _equity_intent("cid-second", qty=5))
    _fill(session, "cid-second", units=5, state=OrderState.FILLED)

    attributed = oms.attribute_positions(
        session,
        adapter_name=ADAPTER,
        positions=[_snapshot(PositionLeg(instrument_key="SPY", signed_qty=15.0))],
    )

    assert attributed[0].originating_client_order_id == "cid-first"
    assert attributed[0].contributing_client_order_ids == ("cid-first", "cid-second")


def test_a_position_the_oms_never_submitted_is_not_attributed(session: Session) -> None:
    """The core refusal. Adapter-side events naming an id are not a local
    authorisation: only a SUBMITTING record with a leg composition is."""
    _fill(session, "never-authorised", units=10, state=OrderState.FILLED)

    attributed = oms.attribute_positions(
        session,
        adapter_name=ADAPTER,
        positions=[_snapshot(PositionLeg(instrument_key="SPY", signed_qty=10.0))],
    )

    assert attributed[0].originating_client_order_id == ""
    assert not attributed[0].attributed
    assert "SPY" in attributed[0].unexplained[0]


def test_a_quantity_that_does_not_match_exactly_is_not_attributed(session: Session) -> None:
    """'Mostly ours' is not a category: a broker leg bigger than local records
    explain is foreign, and so is one smaller."""
    _submit(session, _equity_intent("cid-partial-explain"))
    _fill(session, "cid-partial-explain", units=10, state=OrderState.FILLED)

    for broker_qty in (11.0, 9.0, -10.0):
        attributed = oms.attribute_positions(
            session,
            adapter_name=ADAPTER,
            positions=[_snapshot(PositionLeg(instrument_key="SPY", signed_qty=broker_qty))],
        )
        assert attributed[0].originating_client_order_id == "", broker_qty


def test_one_unexplained_leg_makes_the_whole_position_foreign(session: Session) -> None:
    """A structure is attributed as a structure. An explained leg beside an
    unexplained one is a book the system does not understand."""
    _submit(session, _equity_intent("cid-equity"))
    _fill(session, "cid-equity", units=10, state=OrderState.FILLED)

    attributed = oms.attribute_positions(
        session,
        adapter_name=ADAPTER,
        positions=[
            _snapshot(
                PositionLeg(instrument_key="SPY", signed_qty=10.0),
                PositionLeg(instrument_key=SHORT_PUT, signed_qty=-2.0, shares_per_contract=100),
            )
        ],
    )

    assert attributed[0].originating_client_order_id == ""
    assert len(attributed[0].unexplained) == 1
    assert SHORT_PUT in attributed[0].unexplained[0]


def test_a_resting_order_is_not_a_position(session: Session) -> None:
    """SUBMITTING with no fill contributes nothing: a working order the OMS
    wrote down does not explain a book the broker reports."""
    _submit(session, _equity_intent("cid-resting"))

    attributed = oms.attribute_positions(
        session,
        adapter_name=ADAPTER,
        positions=[_snapshot(PositionLeg(instrument_key="SPY", signed_qty=10.0))],
    )

    assert attributed[0].originating_client_order_id == ""


def test_a_partial_with_no_reported_size_is_not_a_quantity(session: Session) -> None:
    """PARTIAL with no ``filled_units`` is ``None``, not the requested size:
    'partially, by an amount nobody recorded' cannot explain anything."""
    _submit(session, _equity_intent("cid-mystery-partial"))
    record_execution_event(
        session,
        event_type=ExecutionEventType.FILL,
        adapter_name=ADAPTER,
        client_order_id="cid-mystery-partial",
        state_from=OrderState.SUBMITTING.value,
        state_to=OrderState.PARTIAL.value,
    )

    attributed = oms.attribute_positions(
        session,
        adapter_name=ADAPTER,
        positions=[_snapshot(PositionLeg(instrument_key="SPY", signed_qty=10.0))],
    )

    assert attributed[0].originating_client_order_id == ""


def test_a_cancelled_or_rejected_order_explains_nothing(session: Session) -> None:
    for cid, state, event in (
        ("cid-cancelled", OrderState.CANCELLED, ExecutionEventType.CANCELLATION),
        ("cid-rejected", OrderState.REJECTED, ExecutionEventType.REJECTION),
    ):
        _submit(session, _equity_intent(cid))
        record_execution_event(
            session,
            event_type=event,
            adapter_name=ADAPTER,
            client_order_id=cid,
            state_from=OrderState.SUBMITTING.value,
            state_to=state.value,
        )

    attributed = oms.attribute_positions(
        session,
        adapter_name=ADAPTER,
        positions=[_snapshot(PositionLeg(instrument_key="SPY", signed_qty=10.0))],
    )

    assert attributed[0].originating_client_order_id == ""


def test_a_short_leg_is_explained_by_a_sell_to_open(session: Session) -> None:
    """The sign is read from the side, so a short position is explained by the
    order that shorted it and NOT by one that bought the same instrument."""
    _submit(session, _equity_intent("cid-short", side=OrderSide.SELL_TO_OPEN))
    _fill(session, "cid-short", units=10, state=OrderState.FILLED)

    short_book = oms.attribute_positions(
        session,
        adapter_name=ADAPTER,
        positions=[_snapshot(PositionLeg(instrument_key="SPY", signed_qty=-10.0))],
    )
    long_book = oms.attribute_positions(
        session,
        adapter_name=ADAPTER,
        positions=[_snapshot(PositionLeg(instrument_key="SPY", signed_qty=10.0))],
    )

    assert short_book[0].originating_client_order_id == "cid-short"
    assert long_book[0].originating_client_order_id == ""


def test_a_close_nets_the_position_away(session: Session) -> None:
    """After a protective close the broker reports no position at all, and the
    OMS's own book nets to zero — which is the state that has to reconcile."""
    _submit(session, _equity_intent("cid-opened"))
    _fill(session, "cid-opened", units=10, state=OrderState.FILLED)
    _submit(session, _equity_intent("cid-closed", side=OrderSide.SELL_TO_CLOSE))
    _fill(session, "cid-closed", units=10, state=OrderState.FILLED)

    book = oms.local_net_book(session, adapter_name=ADAPTER)

    assert sum(fill.signed_qty for fill in book["SPY"]) == 0.0
    assert oms.attribute_positions(session, adapter_name=ADAPTER, positions=[]) == ()


def test_an_adapter_supplied_origin_is_kept(session: Session) -> None:
    """The reconstruction exists for brokers that report no origin. One that
    does report an origin keeps it — its own record is better evidence than our
    reconstruction of it."""

    class _WithOrigin:
        originating_client_order_id = "broker-said-so"
        legs = (PositionLeg(instrument_key="SPY", signed_qty=10.0),)
        adapter_name = ADAPTER

    attributed = oms.attribute_positions(session, adapter_name=ADAPTER, positions=[_WithOrigin()])

    assert attributed[0].originating_client_order_id == "broker-said-so"


def test_a_combo_is_explained_leg_by_leg_at_one_scalar_size(session: Session) -> None:
    """§14: a combo's filled size is ONE scalar applied to every leg, so a
    proportional partial is still explainable and a by-leg one never is."""
    from signalforge.execution.intents import ComboOrderIntent

    legs = (
        OrderLeg(
            side=OrderSide.SELL_TO_OPEN, ratio=1, shares_per_contract=100, option_ticker=SHORT_PUT
        ),
        OrderLeg(
            side=OrderSide.BUY_TO_OPEN, ratio=1, shares_per_contract=100, option_ticker=LONG_PUT
        ),
    )
    intent = ComboOrderIntent(
        client_order_id="cid-combo",
        intent_kind=IntentKind.OPEN,
        legs=legs,
        contracts=4,
        net_limit_price=1.5,
        structure_type=StructureType.SHORT_VERTICAL,
        adapter_name=ADAPTER,
        created_at=NOW,
        expires_at=NOW + timedelta(minutes=15),
        cost_model=CostModelFeedback(modelled_fill_price=1.6, modelled_spread_bps=5.0),
        state=OrderState.VALIDATED,
    )
    oms.record_submitting(session, intent)
    _fill(session, "cid-combo", units=2, state=OrderState.PARTIAL)  # proportional

    proportional = oms.attribute_positions(
        session,
        adapter_name=ADAPTER,
        positions=[
            _snapshot(
                PositionLeg(instrument_key=LONG_PUT, signed_qty=2.0, shares_per_contract=100),
                PositionLeg(instrument_key=SHORT_PUT, signed_qty=-2.0, shares_per_contract=100),
            )
        ],
    )
    assert proportional[0].originating_client_order_id == "cid-combo"

    # A by-leg partial — the naked-short shape §14 exists to prevent — cannot be
    # explained by any single scalar and must not be attributed.
    by_leg = oms.attribute_positions(
        session,
        adapter_name=ADAPTER,
        positions=[
            _snapshot(
                PositionLeg(instrument_key=LONG_PUT, signed_qty=0.0, shares_per_contract=100),
                PositionLeg(instrument_key=SHORT_PUT, signed_qty=-2.0, shares_per_contract=100),
            )
        ],
    )
    assert by_leg[0].originating_client_order_id == ""


def test_attribution_is_scoped_to_the_adapter(session: Session) -> None:
    """A record written for another adapter cannot explain this adapter's book:
    two adapters are two accounts."""
    _submit(session, _equity_intent("cid-other-adapter"))
    _fill(session, "cid-other-adapter", units=10, state=OrderState.FILLED)

    attributed = oms.attribute_positions(
        session,
        adapter_name="some_other_adapter",
        positions=[_snapshot(PositionLeg(instrument_key="SPY", signed_qty=10.0))],
    )

    assert attributed[0].originating_client_order_id == ""


@pytest.mark.parametrize("repair_method", ["place", "place_combo", "cancel", "cancel_all"])
def test_attribution_never_touches_the_adapter(session: Session, repair_method: str) -> None:
    """It reads local records only. It has no adapter argument, so it cannot
    repair, cancel or close anything — which is the §10 rule, made structural."""
    import inspect

    assert "adapter" not in inspect.signature(oms.attribute_positions).parameters
    assert repair_method not in inspect.getsource(oms.attribute_positions)
