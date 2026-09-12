"""Execution audit records (D6 ADR §15).

Every intent, validation refusal, submission, fill, rejection, cancellation,
reconciliation result, divergence, arm, disarm, kill-switch interaction,
dead-man lapse and ``is_paper`` proof writes **both** an ``execution_event`` row
and an ``audit.record(...)`` call. The existing sink is reused verbatim: there
is no second redaction implementation in this package, because two redaction
implementations means one of them is out of date.

Every event carries ``config_hash`` and ``spec_json_hash``. That is not
ceremony: the 2026-09-11 config-hash incident — an ``agents`` section silently
moving the hash used in the five-part scope match, so live scans matched no
approved scope — was detectable only because the scope match was recorded, and
was masked further only because those scans produced zero qualified candidates.

``execution_event`` is append-only, enforced by the SQLite triggers created in
this feature's migration. Corrections are new rows, never edits.
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING, Any

from signalforge import audit
from signalforge.db.models import ExecutionEvent
from signalforge.db.types import utcnow
from signalforge.observability import redact

if TYPE_CHECKING:  # pragma: no cover - typing only
    from sqlalchemy.orm import Session

__all__ = ["ExecutionEventType", "record_execution_event"]


class ExecutionEventType(StrEnum):
    """The event vocabulary. Anything the OMS does that a reviewer would want to
    see afterwards has a name here rather than a free-form string."""

    # Added in I-E3. §15 requires an audit record for EVERY adapter call, and
    # the read-only ones (account, positions, open_orders, order_status, clock)
    # are not state transitions — reusing STATE_CHANGE or RECONCILED for them
    # would make the vocabulary lie about what happened. One name, used only
    # for "the adapter was called", keeps the state-transition types honest.
    ADAPTER_CALL = "ADAPTER_CALL"
    INTENT_CREATED = "INTENT_CREATED"
    INTENT_REFUSED = "INTENT_REFUSED"
    INTENT_VALIDATED = "INTENT_VALIDATED"
    LIMIT_BLOCKED = "LIMIT_BLOCKED"
    STATE_CHANGE = "STATE_CHANGE"
    SUBMITTING = "SUBMITTING"
    FILL = "FILL"
    REJECTION = "REJECTION"
    CANCELLATION = "CANCELLATION"
    UNKNOWN_PROMOTED = "UNKNOWN_PROMOTED"
    UNKNOWN_RESOLVED = "UNKNOWN_RESOLVED"
    OPERATOR_ACK = "OPERATOR_ACK"
    RECONCILED = "RECONCILED"
    RECONCILIATION_DIVERGED = "RECONCILIATION_DIVERGED"
    IS_PAPER_PROOF = "IS_PAPER_PROOF"
    KILL_SWITCH = "KILL_SWITCH"
    DEAD_MAN_LAPSE = "DEAD_MAN_LAPSE"
    CYCLE_PROTECTIVE = "CYCLE_PROTECTIVE"
    ARMED = "ARMED"
    DISARMED = "DISARMED"


def record_execution_event(
    session: Session,
    *,
    event_type: ExecutionEventType,
    adapter_name: str = "",
    client_order_id: str = "",
    intent_kind: str = "",
    state_from: str = "",
    state_to: str = "",
    reason: str = "",
    source_paper_trade_id: int | None = None,
    source_options_trade_id: int | None = None,
    strategy_version_id: int | None = None,
    armed_strategy_id: int | None = None,
    execution_limits_id: int | None = None,
    config_hash: str = "",
    spec_json_hash: str = "",
    payload: dict[str, Any] | None = None,
    raw_status_verbatim: str = "",
    error_verbatim: str = "",
    modelled_fill_price: float | None = None,
    modelled_spread_bps: float | None = None,
    realized_fill_price: float | None = None,
    leg_index: int | None = None,
    actor: str = "system",
) -> ExecutionEvent:
    """Append one execution event and mirror it into the audit log.

    ``payload`` is redacted before storage with the SAME ``redact()`` the log
    pipeline uses — by type (``SecretStr`` always) and by sensitive key name.
    A credential must never reach this table, and §16's rule is stronger still:
    a credential value never leaves ``credentials.py``'s call boundary, so
    redaction here is the second line of defence and not the first.
    """
    realized_minus_modelled_bps: float | None = None
    if (
        realized_fill_price is not None
        and modelled_fill_price is not None
        and modelled_fill_price != 0
    ):
        realized_minus_modelled_bps = (
            (realized_fill_price - modelled_fill_price) / abs(modelled_fill_price)
        ) * 10_000.0

    safe_payload: dict[str, Any] = redact(dict(payload or {}))
    row = ExecutionEvent(
        ts=utcnow(),
        event_type=event_type.value,
        client_order_id=client_order_id,
        source_paper_trade_id=source_paper_trade_id,
        source_options_trade_id=source_options_trade_id,
        strategy_version_id=strategy_version_id,
        armed_strategy_id=armed_strategy_id,
        adapter_name=adapter_name,
        state_from=state_from,
        state_to=state_to,
        execution_limits_id=execution_limits_id,
        intent_kind=intent_kind,
        reason=reason[:300],
        config_hash=config_hash,
        spec_json_hash=spec_json_hash,
        payload_json=safe_payload,
        raw_status_verbatim=raw_status_verbatim,
        error_verbatim=error_verbatim,
        modelled_fill_price=modelled_fill_price,
        modelled_spread_bps=modelled_spread_bps,
        realized_fill_price=realized_fill_price,
        realized_minus_modelled_bps=realized_minus_modelled_bps,
        leg_index=leg_index,
    )
    session.add(row)
    session.flush()

    audit.record(
        f"execution.{event_type.value.lower()}",
        actor=actor,
        entity=client_order_id or adapter_name,
        event_type=event_type.value,
        adapter_name=adapter_name,
        intent_kind=intent_kind,
        state_from=state_from,
        state_to=state_to,
        reason=reason,
        config_hash=config_hash,
        spec_json_hash=spec_json_hash,
        execution_limits_id=execution_limits_id,
        payload=safe_payload,
    )
    return row
