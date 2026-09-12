"""OMS states and the ONLY legal transitions between them (D6 ADR §6).

```
CREATED ──validate()──▶ VALIDATED ──submit()──▶ SUBMITTING ──▶ FILLED
   │                        │                        │        ├▶ PARTIAL
   │                        │                        │        ├▶ REJECTED
   ├──▶ REFUSED             ├──▶ EXPIRED             │        ├▶ CANCELLED
   (precondition failed,    (expires_at passed       │        ├▶ EXPIRED
    §5; terminal)            before submission)      │        └▶ UNKNOWN
                                                     │
                     (no terminal outcome recorded) ─┘
```

``UNKNOWN`` is terminal-until-reconciled and it BLOCKS: it is where a timeout,
an ambiguous response, or a ``SUBMITTING`` record with no recorded outcome
lands. It is never cleared by a retry — only by reconciliation resolving the
``client_order_id`` to a terminal broker state AND an explicit operator
acknowledgement, both of which this module requires as evidence before it will
let an ``UNKNOWN`` move anywhere.

This module is pure: no session, no adapter, no I/O. Persisting a transition is
``execution.oms``'s job.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

__all__ = [
    "IllegalTransition",
    "LEGAL_TRANSITIONS",
    "OrderState",
    "TERMINAL_STATES",
    "UNKNOWN_RESOLUTION_STATES",
    "UnknownResolution",
    "is_terminal",
    "next_state",
]


class OrderState(StrEnum):
    CREATED = "CREATED"
    VALIDATED = "VALIDATED"
    SUBMITTING = "SUBMITTING"
    FILLED = "FILLED"
    PARTIAL = "PARTIAL"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"
    REFUSED = "REFUSED"
    UNKNOWN = "UNKNOWN"


#: Every state from which no further transition happens on its own. ``UNKNOWN``
#: is in this set deliberately: it is terminal *until reconciled*, and the only
#: way out of it carries proof (see :func:`next_state`).
TERMINAL_STATES: frozenset[OrderState] = frozenset(
    {
        OrderState.FILLED,
        OrderState.PARTIAL,
        OrderState.REJECTED,
        OrderState.CANCELLED,
        OrderState.EXPIRED,
        OrderState.REFUSED,
        OrderState.UNKNOWN,
    }
)

#: The outcomes a reconciliation may resolve an ``UNKNOWN`` into. It can never be
#: resolved into ``CREATED``/``VALIDATED``/``SUBMITTING`` — i.e. it can never be
#: "retried" back onto the submission path.
UNKNOWN_RESOLUTION_STATES: frozenset[OrderState] = frozenset(
    {
        OrderState.FILLED,
        OrderState.PARTIAL,
        OrderState.REJECTED,
        OrderState.CANCELLED,
        OrderState.EXPIRED,
    }
)

LEGAL_TRANSITIONS: Mapping[OrderState, frozenset[OrderState]] = {
    OrderState.CREATED: frozenset({OrderState.VALIDATED, OrderState.REFUSED}),
    OrderState.VALIDATED: frozenset({OrderState.SUBMITTING, OrderState.EXPIRED}),
    OrderState.SUBMITTING: frozenset(
        {
            OrderState.FILLED,
            OrderState.PARTIAL,
            OrderState.REJECTED,
            OrderState.CANCELLED,
            OrderState.EXPIRED,
            OrderState.UNKNOWN,
        }
    ),
    OrderState.FILLED: frozenset(),
    OrderState.PARTIAL: frozenset(),
    OrderState.REJECTED: frozenset(),
    OrderState.CANCELLED: frozenset(),
    OrderState.EXPIRED: frozenset(),
    OrderState.REFUSED: frozenset(),
    # Reachable only with an UnknownResolution — see next_state().
    OrderState.UNKNOWN: UNKNOWN_RESOLUTION_STATES,
}


class IllegalTransition(RuntimeError):
    """An attempt to move an order between two states the machine does not join."""

    def __init__(self, current: OrderState, target: OrderState, detail: str = "") -> None:
        msg = f"illegal OMS transition {current.value} -> {target.value}"
        super().__init__(f"{msg}: {detail}" if detail else msg)
        self.current = current
        self.target = target


@dataclass(frozen=True, slots=True)
class UnknownResolution:
    """The two-part evidence §6 rule 2 requires before an ``UNKNOWN`` moves.

    ``broker_terminal_state`` must come from ``order_status(client_order_id)``
    (the by-id lookup), never from ``open_orders()`` alone: a filled or rejected
    order is by definition not open, so ``open_orders()`` cannot distinguish
    "the broker never saw it" from "the broker filled it".
    """

    reconciled_from_order_status: bool
    operator_acknowledged: bool
    broker_terminal_state: OrderState
    acknowledged_by: str = ""
    note: str = ""

    @property
    def is_sufficient(self) -> bool:
        return (
            self.reconciled_from_order_status
            and self.operator_acknowledged
            and self.broker_terminal_state in UNKNOWN_RESOLUTION_STATES
        )


def is_terminal(state: OrderState) -> bool:
    return state in TERMINAL_STATES


def next_state(
    current: OrderState,
    target: OrderState,
    *,
    resolution: UnknownResolution | None = None,
) -> OrderState:
    """Return ``target`` if the machine joins these two states, else raise.

    Leaving ``UNKNOWN`` additionally requires a sufficient
    :class:`UnknownResolution` whose ``broker_terminal_state`` IS the target —
    so no code path can clear an ``UNKNOWN`` by asserting an outcome it did not
    read back from the broker, and a retry can never clear one.
    """
    allowed = LEGAL_TRANSITIONS.get(current, frozenset())
    if target not in allowed:
        raise IllegalTransition(current, target)
    if current is OrderState.UNKNOWN:
        if resolution is None or not resolution.is_sufficient:
            raise IllegalTransition(
                current,
                target,
                "an UNKNOWN is cleared only by order_status() reconciliation AND an "
                "explicit operator acknowledgement — never by a retry",
            )
        if resolution.broker_terminal_state is not target:
            raise IllegalTransition(
                current,
                target,
                f"reconciliation resolved the order to "
                f"{resolution.broker_terminal_state.value}, not {target.value}",
            )
    return target
