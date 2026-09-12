"""The OMS state machine, persisted (D6 ADR §6, §8).

What is here: the durable state transitions, the ``SUBMITTING``-with-no-outcome
promotion to ``UNKNOWN``, the two-part ``UNKNOWN`` resolution, and the query
``may_open``'s I2 check reads.

What is deliberately NOT here, in this phase:

* no adapter call of any kind — no ``place``, no ``cancel``, no network;
* no arming ceremony (I-E4) and no scheduler registration (§2);
* no cycle loop, no dead man, no reconciliation.

The SQLite discipline this module exists to make possible (§2, §8): the
``SUBMITTING`` record is written and **committed** BEFORE the network call, with
write intent then released, so the in-flight set is durable across a crash and
no transaction is ever held open across a broker round trip — on the same file
the live probation worker uses.
"""

from __future__ import annotations

import contextlib
from datetime import datetime
from typing import TYPE_CHECKING

from signalforge.execution.events import ExecutionEventType, record_execution_event
from signalforge.execution.intents import ComboOrderIntent, IntentKind, OrderIntent
from signalforge.execution.states import (
    IllegalTransition,
    OrderState,
    UnknownResolution,
    is_terminal,
    next_state,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from sqlalchemy.orm import Session

    from signalforge.db.models import ExecutionEvent

__all__ = [
    "assert_terminal",
    "current_state",
    "has_outstanding_unknown",
    "promote_stale_submitting",
    "record_submitting",
    "refuse",
    "resolve_unknown",
    "transition",
]

Intent = OrderIntent | ComboOrderIntent


def _event_type_for(state: OrderState) -> ExecutionEventType:
    return {
        OrderState.VALIDATED: ExecutionEventType.INTENT_VALIDATED,
        OrderState.SUBMITTING: ExecutionEventType.SUBMITTING,
        OrderState.FILLED: ExecutionEventType.FILL,
        OrderState.PARTIAL: ExecutionEventType.FILL,
        OrderState.REJECTED: ExecutionEventType.REJECTION,
        OrderState.CANCELLED: ExecutionEventType.CANCELLATION,
        OrderState.REFUSED: ExecutionEventType.INTENT_REFUSED,
        OrderState.UNKNOWN: ExecutionEventType.UNKNOWN_PROMOTED,
    }.get(state, ExecutionEventType.STATE_CHANGE)


def current_state(session: Session, client_order_id: str) -> OrderState | None:
    """The latest recorded state for an order id, or ``None`` if this OMS has
    never written one."""
    from sqlalchemy import select

    from signalforge.db.models import ExecutionEvent

    row = session.scalars(
        select(ExecutionEvent)
        .where(ExecutionEvent.client_order_id == client_order_id, ExecutionEvent.state_to != "")
        .order_by(ExecutionEvent.ts.desc(), ExecutionEvent.id.desc())
    ).first()
    if row is None:
        return None
    try:
        return OrderState(row.state_to)
    except ValueError:  # pragma: no cover - an unknown literal is not a state
        return None


def transition(
    session: Session,
    intent: Intent,
    target: OrderState,
    *,
    reason: str = "",
    resolution: UnknownResolution | None = None,
    raw_status_verbatim: str = "",
    error_verbatim: str = "",
    realized_fill_price: float | None = None,
    leg_index: int | None = None,
    actor: str = "system",
) -> Intent:
    """Move an intent to ``target``, writing the event, or raise.

    The legality table is ``execution.states`` and nothing here may bypass it —
    including the rule that an ``UNKNOWN`` is never cleared by a retry.
    """
    resolved = next_state(intent.state, target, resolution=resolution)
    record_execution_event(
        session,
        event_type=_event_type_for(resolved),
        adapter_name=intent.adapter_name,
        client_order_id=intent.client_order_id,
        intent_kind=intent.intent_kind.value,
        state_from=intent.state.value,
        state_to=resolved.value,
        reason=reason,
        source_paper_trade_id=intent.source_paper_trade_id,
        strategy_version_id=intent.strategy_version_id,
        armed_strategy_id=intent.armed_strategy_id,
        execution_limits_id=intent.execution_limits_id,
        config_hash=intent.config_hash,
        spec_json_hash=intent.spec_json_hash,
        raw_status_verbatim=raw_status_verbatim,
        error_verbatim=error_verbatim,
        modelled_fill_price=intent.cost_model.modelled_fill_price,
        modelled_spread_bps=intent.cost_model.modelled_spread_bps,
        realized_fill_price=realized_fill_price,
        leg_index=leg_index,
        actor=actor,
    )
    return intent.with_state(resolved)


def record_submitting(session: Session, intent: Intent, *, actor: str = "system") -> Intent:
    """Write and COMMIT the ``SUBMITTING`` record before any network call (§8).

    The commit is the point: the in-flight set is durable, not in memory, so a
    process killed between this line and the broker's response leaves a record
    the next cycle promotes to ``UNKNOWN`` rather than silently losing an order
    that may have reached the broker. The write intent is released afterwards so
    no SQLite write lock is held across the round trip.
    """
    from signalforge.db.session import set_write_intent

    moved = transition(
        session, intent, OrderState.SUBMITTING, reason="durable pre-submit record", actor=actor
    )
    session.commit()
    # Releasing write intent is best-effort: the durable record is already
    # committed, and a caller that left a transaction open must not turn that
    # into a lost submission record.
    with contextlib.suppress(RuntimeError):
        set_write_intent(session, False)
    return moved


def promote_stale_submitting(
    session: Session, *, now: datetime, adapter_name: str | None = None, actor: str = "system"
) -> list[str]:
    """Promote every ``SUBMITTING`` record with no terminal outcome to
    ``UNKNOWN`` (§6 rule 3) and return their ``client_order_id``s.

    Runs at the start of any cycle, **including the first cycle after a process
    restart**. A ``SUBMITTING`` with no outcome is NEVER assumed to have failed:
    the order may well have reached the broker, which is the entire reason this
    state exists.
    """
    from sqlalchemy import select

    from signalforge.db.models import ExecutionEvent

    stmt = select(ExecutionEvent.client_order_id).where(ExecutionEvent.client_order_id != "")
    if adapter_name is not None:
        stmt = stmt.where(ExecutionEvent.adapter_name == adapter_name)
    ids = sorted({cid for cid in session.scalars(stmt) if cid})

    promoted: list[str] = []
    for cid in ids:
        state = current_state(session, cid)
        if state is not OrderState.SUBMITTING:
            continue
        last = _last_event(session, cid)
        record_execution_event(
            session,
            event_type=ExecutionEventType.UNKNOWN_PROMOTED,
            adapter_name=last.adapter_name if last else (adapter_name or ""),
            client_order_id=cid,
            intent_kind=last.intent_kind if last else "",
            state_from=OrderState.SUBMITTING.value,
            state_to=OrderState.UNKNOWN.value,
            reason=(
                "a SUBMITTING record with no terminal outcome is UNKNOWN, never assumed failed; "
                f"observed at {now.isoformat()}"
            ),
            strategy_version_id=last.strategy_version_id if last else None,
            armed_strategy_id=last.armed_strategy_id if last else None,
            execution_limits_id=last.execution_limits_id if last else None,
            config_hash=last.config_hash if last else "",
            spec_json_hash=last.spec_json_hash if last else "",
            actor=actor,
        )
        promoted.append(cid)
    return promoted


def _last_event(session: Session, client_order_id: str) -> ExecutionEvent | None:
    from sqlalchemy import select

    from signalforge.db.models import ExecutionEvent

    return session.scalars(
        select(ExecutionEvent)
        .where(ExecutionEvent.client_order_id == client_order_id)
        .order_by(ExecutionEvent.ts.desc(), ExecutionEvent.id.desc())
    ).first()


def has_outstanding_unknown(session: Session, strategy_version_id: int) -> bool:
    """I2 / §12 step 7 — an outstanding ``UNKNOWN`` blocks every further
    ``may_open`` for this strategy AND blocks arming it. It does not block any
    close."""
    from sqlalchemy import select

    from signalforge.db.models import ExecutionEvent

    ids = sorted(
        {
            cid
            for cid in session.scalars(
                select(ExecutionEvent.client_order_id).where(
                    ExecutionEvent.strategy_version_id == strategy_version_id,
                    ExecutionEvent.client_order_id != "",
                )
            )
            if cid
        }
    )
    return any(current_state(session, cid) is OrderState.UNKNOWN for cid in ids)


def resolve_unknown(
    session: Session,
    client_order_id: str,
    *,
    resolution: UnknownResolution,
    actor: str,
) -> OrderState:
    """Clear an ``UNKNOWN`` — the ONLY way, and it requires both halves (§6
    rule 2): reconciliation resolving the id to a terminal broker state via
    ``order_status()``, AND an explicit operator acknowledgement.

    It requires no manual DB write, which is the point: rev 1's design could
    enter a state it could not leave without editing the database by hand, and
    the append-only discipline forbids that.
    """
    state = current_state(session, client_order_id)
    if state is not OrderState.UNKNOWN:
        raise IllegalTransition(
            state or OrderState.CREATED,
            resolution.broker_terminal_state,
            f"{client_order_id} is not in UNKNOWN",
        )
    target = next_state(OrderState.UNKNOWN, resolution.broker_terminal_state, resolution=resolution)
    last = _last_event(session, client_order_id)
    record_execution_event(
        session,
        event_type=ExecutionEventType.UNKNOWN_RESOLVED,
        adapter_name=last.adapter_name if last else "",
        client_order_id=client_order_id,
        intent_kind=last.intent_kind if last else "",
        state_from=OrderState.UNKNOWN.value,
        state_to=target.value,
        reason=(
            f"resolved by order_status() reconciliation and an operator acknowledgement "
            f"({resolution.acknowledged_by or actor}): {resolution.note}"
        ),
        strategy_version_id=last.strategy_version_id if last else None,
        armed_strategy_id=last.armed_strategy_id if last else None,
        execution_limits_id=last.execution_limits_id if last else None,
        config_hash=last.config_hash if last else "",
        spec_json_hash=last.spec_json_hash if last else "",
        actor=actor,
    )
    return target


def refuse(
    session: Session,
    *,
    adapter_name: str,
    reason: str,
    intent_kind: IntentKind = IntentKind.OPEN,
    client_order_id: str = "",
    source_paper_trade_id: int | None = None,
    strategy_version_id: int | None = None,
    actor: str = "system",
) -> None:
    """Record a refusal that never produced an intent object at all.

    Every ``may_open`` failure is written, not only the ones that happen to
    reach a constructed intent — otherwise the record of what the system
    refused would be shaped by where the refusal happened to occur.
    """
    record_execution_event(
        session,
        event_type=ExecutionEventType.INTENT_REFUSED,
        adapter_name=adapter_name,
        client_order_id=client_order_id,
        intent_kind=intent_kind.value,
        state_to=OrderState.REFUSED.value,
        reason=reason,
        source_paper_trade_id=source_paper_trade_id,
        strategy_version_id=strategy_version_id,
        actor=actor,
    )


def assert_terminal(state: OrderState) -> None:
    if not is_terminal(state):
        raise IllegalTransition(state, state, "expected a terminal state")
