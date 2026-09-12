"""D6 §6 / §8 — the persisted state machine: the durable ``SUBMITTING`` record,
the automatic promotion to ``UNKNOWN``, and the two-part exit that requires no
manual database write."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from signalforge.db.models import ExecutionEvent
from signalforge.execution import oms
from signalforge.execution.events import ExecutionEventType
from signalforge.execution.intents import (
    CostModelFeedback,
    IntentKind,
    OrderIntent,
    OrderSide,
)
from signalforge.execution.states import IllegalTransition, OrderState, UnknownResolution
from tests.execution.conftest import ADAPTER, NOW


def _intent(client_order_id: str = "a" * 32, **kw: object) -> OrderIntent:
    defaults: dict[str, object] = {
        "client_order_id": client_order_id,
        "intent_kind": IntentKind.OPEN,
        "side": OrderSide.BUY_TO_OPEN,
        "qty": 1,
        "limit_price": 471.0,
        "shares_per_contract": 1,
        "adapter_name": ADAPTER,
        "created_at": NOW,
        "expires_at": NOW + timedelta(minutes=15),
        "cost_model": CostModelFeedback(modelled_fill_price=471.0, modelled_spread_bps=5.0),
        "symbol": "SPY",
        "strategy_version_id": None,
        "config_hash": "cfg",
        "spec_json_hash": "spec",
    }
    defaults.update(kw)
    return OrderIntent(**defaults)  # type: ignore[arg-type]


def _events(session: Session) -> list[ExecutionEvent]:
    return list(session.scalars(select(ExecutionEvent).order_by(ExecutionEvent.id)))


def test_a_transition_writes_an_event_carrying_both_hashes(session: Session) -> None:
    intent = _intent()
    moved = oms.transition(session, intent, OrderState.VALIDATED, reason="all checks passed")
    assert moved.state is OrderState.VALIDATED
    (event,) = _events(session)
    assert event.state_from == "CREATED"
    assert event.state_to == "VALIDATED"
    assert event.config_hash == "cfg"
    assert event.spec_json_hash == "spec"
    assert event.event_type == ExecutionEventType.INTENT_VALIDATED.value
    assert oms.current_state(session, intent.client_order_id) is OrderState.VALIDATED


def test_an_illegal_transition_writes_nothing(session: Session) -> None:
    with pytest.raises(IllegalTransition):
        oms.transition(session, _intent(), OrderState.FILLED)
    assert _events(session) == []


def test_the_submitting_record_is_durable_before_any_network_call(session: Session) -> None:
    """§8 step 1: written and COMMITTED before ``place()``, so the in-flight set
    survives a crash instead of living in memory."""
    intent = oms.transition(session, _intent(), OrderState.VALIDATED)
    oms.record_submitting(session, intent)
    session.rollback()  # nothing after the commit could take it back
    assert oms.current_state(session, intent.client_order_id) is OrderState.SUBMITTING


def test_a_submitting_with_no_outcome_is_promoted_to_unknown(session: Session) -> None:
    intent = oms.transition(session, _intent(), OrderState.VALIDATED)
    oms.record_submitting(session, intent)

    promoted = oms.promote_stale_submitting(session, now=NOW)
    assert promoted == [intent.client_order_id]
    assert oms.current_state(session, intent.client_order_id) is OrderState.UNKNOWN
    last = _events(session)[-1]
    assert last.event_type == ExecutionEventType.UNKNOWN_PROMOTED.value
    assert "never assumed failed" in last.reason


def test_a_completed_order_is_not_promoted(session: Session) -> None:
    intent = oms.transition(session, _intent(), OrderState.VALIDATED)
    intent = oms.record_submitting(session, intent)
    oms.transition(session, intent, OrderState.FILLED, realized_fill_price=471.5)
    assert oms.promote_stale_submitting(session, now=NOW) == []
    assert oms.current_state(session, intent.client_order_id) is OrderState.FILLED


def test_a_fill_records_the_realized_minus_modelled_difference(session: Session) -> None:
    """§4.2 — the execution layer is the first place a REALIZED spread is
    observable; the audit trail must make it computable."""
    intent = oms.transition(session, _intent(), OrderState.VALIDATED)
    intent = oms.record_submitting(session, intent)
    oms.transition(session, intent, OrderState.FILLED, realized_fill_price=471.471)
    fill = _events(session)[-1]
    assert fill.modelled_fill_price == pytest.approx(471.0)
    assert fill.modelled_spread_bps == pytest.approx(5.0)
    assert fill.realized_fill_price == pytest.approx(471.471)
    assert fill.realized_minus_modelled_bps == pytest.approx(10.0, abs=0.01)


def test_an_unknown_blocks_further_opening_for_that_strategy(
    session: Session, strategy_version: object
) -> None:
    version_id = strategy_version.id  # type: ignore[attr-defined]
    intent = oms.transition(session, _intent(strategy_version_id=version_id), OrderState.VALIDATED)
    oms.record_submitting(session, intent)
    assert oms.has_outstanding_unknown(session, version_id) is False
    oms.promote_stale_submitting(session, now=NOW)
    assert oms.has_outstanding_unknown(session, version_id) is True


def _resolution(**kw: object) -> UnknownResolution:
    defaults: dict[str, object] = {
        "reconciled_from_order_status": True,
        "operator_acknowledged": True,
        "broker_terminal_state": OrderState.FILLED,
        "acknowledged_by": "local-user",
        "note": "broker reports a fill",
    }
    defaults.update(kw)
    return UnknownResolution(**defaults)  # type: ignore[arg-type]


def _to_unknown(session: Session) -> OrderIntent:
    intent = oms.transition(session, _intent(), OrderState.VALIDATED)
    intent = oms.record_submitting(session, intent)
    oms.promote_stale_submitting(session, now=NOW)
    return intent


def test_an_unknown_is_cleared_only_by_reconciliation_and_an_acknowledgement(
    session: Session,
) -> None:
    intent = _to_unknown(session)
    with pytest.raises(IllegalTransition):
        oms.resolve_unknown(
            session,
            intent.client_order_id,
            resolution=_resolution(reconciled_from_order_status=False),
            actor="local-user",
        )
    with pytest.raises(IllegalTransition):
        oms.resolve_unknown(
            session,
            intent.client_order_id,
            resolution=_resolution(operator_acknowledged=False),
            actor="local-user",
        )
    assert oms.current_state(session, intent.client_order_id) is OrderState.UNKNOWN

    resolved = oms.resolve_unknown(
        session, intent.client_order_id, resolution=_resolution(), actor="local-user"
    )
    assert resolved is OrderState.FILLED
    assert oms.current_state(session, intent.client_order_id) is OrderState.FILLED


def test_clearing_an_unknown_needs_no_manual_database_write(session: Session) -> None:
    """The rev-1 deadlock, closed: the exit is an append, like everything else."""
    intent = _to_unknown(session)
    before = len(_events(session))
    oms.resolve_unknown(
        session, intent.client_order_id, resolution=_resolution(), actor="local-user"
    )
    after = _events(session)
    assert len(after) == before + 1
    assert after[-1].event_type == ExecutionEventType.UNKNOWN_RESOLVED.value


def test_resolving_something_that_is_not_unknown_is_refused(session: Session) -> None:
    intent = oms.transition(session, _intent(), OrderState.VALIDATED)
    with pytest.raises(IllegalTransition):
        oms.resolve_unknown(
            session, intent.client_order_id, resolution=_resolution(), actor="local-user"
        )


def test_a_refusal_is_recorded_even_when_no_intent_was_ever_built(session: Session) -> None:
    oms.refuse(
        session,
        adapter_name=ADAPTER,
        reason="P6: manually accepted paper trade",
        source_paper_trade_id=None,
    )
    (event,) = _events(session)
    assert event.event_type == ExecutionEventType.INTENT_REFUSED.value
    assert event.state_to == OrderState.REFUSED.value
    assert "P6" in event.reason
