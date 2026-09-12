"""D6 §5.2b / §7 — the close lane, and the inversion of the fail direction.

The headline promise of this layer is that **the kill switch blocks opening and
never blocks closing**. Rev 1 of the ADR routed both lanes through one factory
requiring all seven opening preconditions, which made a protective close
unconstructible in exactly the disarmed / expired / kill-switched states the
close lane exists for. These tests prove the correction rather than assert it.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy.orm import Session

from signalforge.db.models import ArmedStrategy, ExecutionEvent, PaperTrade
from signalforge.execution.events import ExecutionEventType, record_execution_event
from signalforge.execution.intents import (
    CloseIntentRefused,
    CostModelFeedback,
    IntentKind,
    OrderLeg,
    OrderSide,
    PositionLeg,
    ReconciledPosition,
    StructureType,
    build_close_intent,
)
from signalforge.execution.limits import CloseGateContext, may_close
from tests.execution.conftest import ADAPTER, NOW

#: A synthetic client_order_id. Not a credential — detect-secrets cannot tell
#: a 32-hex order id from a key, so the pragma is inline rather than in the
#: baseline (the baseline is never rewritten to accommodate new code).
ORIGIN = "0123456789abcdef0123456789abcdef"  # pragma: allowlist secret


@pytest.fixture
def originating_event(session: Session) -> ExecutionEvent:
    """C-P2 — the OMS's own record that it opened this position."""
    return record_execution_event(
        session,
        event_type=ExecutionEventType.SUBMITTING,
        adapter_name=ADAPTER,
        client_order_id=ORIGIN,
        intent_kind=IntentKind.OPEN.value,
        state_from="VALIDATED",
        state_to="SUBMITTING",
    )


def _position(**kw: object) -> ReconciledPosition:
    base: dict[str, object] = {
        "adapter_name": ADAPTER,
        "legs": (PositionLeg(instrument_key="SPY", signed_qty=10.0),),
        "originating_client_order_id": ORIGIN,
        "reconciled": True,
        "adapter_reachable": True,
        "reconciliation_diverged": False,
    }
    base.update(kw)
    return ReconciledPosition(**base)  # type: ignore[arg-type]


def _close(session: Session, position: ReconciledPosition, **kw: object) -> object:
    defaults: dict[str, object] = {
        "position": position,
        "legs": (
            OrderLeg(side=OrderSide.SELL_TO_CLOSE, ratio=10, shares_per_contract=1, symbol="SPY"),
        ),
        "contracts": 1,
        "limit_price": 470.0,
        "cost_model": CostModelFeedback(modelled_fill_price=470.0, modelled_spread_bps=5.0),
        "now": NOW,
        "max_intent_age_minutes": 15,
    }
    defaults.update(kw)
    return build_close_intent(session, **defaults)  # type: ignore[arg-type]


@pytest.mark.usefixtures("originating_event")
def test_a_close_needs_no_armed_row_no_candidate_and_no_paper_trade(session: Session) -> None:
    """The states the close lane exists for: nothing of the research world is
    present, and the flatten still constructs."""
    assert session.query(ArmedStrategy).count() == 0
    assert session.query(PaperTrade).count() == 0

    intent = _close(session, _position())
    assert intent.intent_kind is IntentKind.PROTECTIVE_CLOSE  # type: ignore[union-attr]
    assert intent.qty == 10  # type: ignore[union-attr]
    assert intent.symbol == "SPY"  # type: ignore[union-attr]
    assert intent.armed_strategy_id is None  # type: ignore[union-attr]
    assert intent.source_paper_trade_id is None  # type: ignore[union-attr]


@pytest.mark.usefixtures("originating_event")
def test_a_close_is_still_constructible_while_disarmed_and_expired(
    session: Session, armed: ArmedStrategy
) -> None:
    armed.disarmed_at = NOW
    armed.expires_at = NOW - timedelta(days=1)
    armed.disarm_reason = "dead-man lapse"
    session.flush()
    assert _close(session, _position()) is not None


@pytest.mark.usefixtures("originating_event")
def test_the_close_id_is_stable_across_retries(session: Session) -> None:
    first = _close(session, _position())
    second = _close(session, _position())
    assert first.client_order_id == second.client_order_id  # type: ignore[union-attr]


@pytest.mark.usefixtures("originating_event")
def test_a_combo_close_produces_one_id_for_the_whole_structure(session: Session) -> None:
    position = _position(
        legs=(
            PositionLeg(
                instrument_key="O:SPY260918P00470000", signed_qty=-1, shares_per_contract=100
            ),
            PositionLeg(
                instrument_key="O:SPY260918P00465000", signed_qty=1, shares_per_contract=100
            ),
        )
    )
    legs = (
        OrderLeg(
            side=OrderSide.BUY_TO_CLOSE,
            ratio=1,
            shares_per_contract=100,
            option_ticker="O:SPY260918P00470000",
            strike=470.0,
        ),
        OrderLeg(
            side=OrderSide.SELL_TO_CLOSE,
            ratio=1,
            shares_per_contract=100,
            option_ticker="O:SPY260918P00465000",
            strike=465.0,
        ),
    )
    intent = _close(
        session,
        position,
        legs=legs,
        structure_type=StructureType.SHORT_VERTICAL,
        limit_price=-1.2,
    )
    assert len(intent.legs) == 2  # type: ignore[union-attr]
    assert intent.client_order_id  # one id for the whole structure  # type: ignore[union-attr]


# --- the five proofs, each removed in turn --------------------------------


@pytest.mark.usefixtures("originating_event")
def test_c_p1_an_unreconciled_position_is_refused(session: Session) -> None:
    with pytest.raises(CloseIntentRefused, match="C-P1"):
        _close(session, _position(reconciled=False))


@pytest.mark.usefixtures("originating_event")
def test_c_p5_an_unreachable_adapter_is_refused(session: Session) -> None:
    with pytest.raises(CloseIntentRefused, match="C-P5"):
        _close(session, _position(adapter_reachable=False))


@pytest.mark.usefixtures("originating_event")
def test_c_p5_a_diverged_reconciliation_is_refused(session: Session) -> None:
    """Closing into an unknown book is not protective."""
    with pytest.raises(CloseIntentRefused, match="C-P5"):
        _close(session, _position(reconciliation_diverged=True))


def test_c_p2_a_position_this_oms_never_opened_is_refused(session: Session) -> None:
    """A foreign position is a §10 divergence and a halt, not a close: the OMS
    will not flatten something it did not open."""
    with pytest.raises(CloseIntentRefused, match="C-P2"):
        _close(session, _position())


@pytest.mark.usefixtures("originating_event")
def test_c_p3_a_leg_that_increases_exposure_is_refused(session: Session) -> None:
    """A "close" cannot be used to roll into a new short leg."""
    with pytest.raises(CloseIntentRefused, match="C-P3"):
        _close(
            session,
            _position(),
            legs=(
                OrderLeg(side=OrderSide.BUY_TO_CLOSE, ratio=1, shares_per_contract=1, symbol="SPY"),
            ),
        )


@pytest.mark.usefixtures("originating_event")
def test_c_p3_is_asserted_per_leg_not_on_the_net(session: Session) -> None:
    """A net-reducing intent that increases ANY single leg is refused."""
    position = _position(
        legs=(
            PositionLeg(
                instrument_key="O:SPY260918P00470000", signed_qty=-2, shares_per_contract=100
            ),
            PositionLeg(
                instrument_key="O:SPY260918P00465000", signed_qty=2, shares_per_contract=100
            ),
        )
    )
    legs = (
        # reduces the short leg by 2 ...
        OrderLeg(
            side=OrderSide.BUY_TO_CLOSE,
            ratio=2,
            shares_per_contract=100,
            option_ticker="O:SPY260918P00470000",
        ),
        # ... while ADDING to the long leg: net-reducing, per-leg increasing.
        OrderLeg(
            side=OrderSide.BUY_TO_CLOSE,
            ratio=1,
            shares_per_contract=100,
            option_ticker="O:SPY260918P00465000",
        ),
    )
    with pytest.raises(CloseIntentRefused, match="C-P3"):
        _close(session, position, legs=legs, structure_type=StructureType.SHORT_VERTICAL)


@pytest.mark.usefixtures("originating_event")
def test_c_p3_an_opening_side_in_a_close_is_refused(session: Session) -> None:
    with pytest.raises(CloseIntentRefused, match="C-P3"):
        _close(
            session,
            _position(),
            legs=(
                OrderLeg(side=OrderSide.SELL_TO_OPEN, ratio=1, shares_per_contract=1, symbol="SPY"),
            ),
        )


@pytest.mark.usefixtures("originating_event")
def test_c_p3_a_close_cannot_flip_the_position(session: Session) -> None:
    with pytest.raises(CloseIntentRefused, match="C-P3"):
        _close(
            session,
            _position(),
            legs=(
                OrderLeg(
                    side=OrderSide.SELL_TO_CLOSE, ratio=99, shares_per_contract=1, symbol="SPY"
                ),
            ),
        )


@pytest.mark.usefixtures("originating_event")
def test_c_p3_a_leg_the_broker_does_not_report_is_refused(session: Session) -> None:
    with pytest.raises(CloseIntentRefused, match="C-P3"):
        _close(
            session,
            _position(),
            legs=(
                OrderLeg(
                    side=OrderSide.SELL_TO_CLOSE, ratio=1, shares_per_contract=1, symbol="QQQ"
                ),
            ),
        )


# --- may_close's gate, and what it deliberately does NOT consult -----------


def test_may_close_is_permitted_in_every_state_that_blocks_opening() -> None:
    """Kill switch engaged, dead man lapsed, disarmed, expired, scope drifted,
    an UNKNOWN outstanding elsewhere — ``may_close`` does not take any of them
    as an input, so none of them can block it."""
    decision = may_close(
        CloseGateContext(
            position_exists_and_reconciled=True,
            originating_event_exists=True,
            non_increasing_in_every_leg=True,
            intent_kind_is_protective_close=True,
            adapter_reachable=True,
            reconciliation_diverged=False,
        )
    )
    assert decision.allowed
    assert {c.name for c in decision.checks} == {"C-P1", "C-P2", "C-P3", "C-P4", "C-P5"}


def test_may_close_blocks_only_on_a_diverged_or_unreachable_book() -> None:
    for override, expected in [
        ({"adapter_reachable": False}, "C-P5"),
        ({"reconciliation_diverged": True}, "C-P5"),
        ({"position_exists_and_reconciled": False}, "C-P1"),
        ({"originating_event_exists": False}, "C-P2"),
        ({"non_increasing_in_every_leg": False}, "C-P3"),
        ({"intent_kind_is_protective_close": False}, "C-P4"),
    ]:
        fields: dict[str, bool] = {
            "position_exists_and_reconciled": True,
            "originating_event_exists": True,
            "non_increasing_in_every_leg": True,
            "intent_kind_is_protective_close": True,
            "adapter_reachable": True,
            "reconciliation_diverged": False,
        }
        fields.update(override)
        decision = may_close(CloseGateContext(**fields))
        assert not decision.allowed
        assert decision.first_failure is not None
        assert decision.first_failure.startswith(expected)
