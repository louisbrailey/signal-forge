"""D6 §6 — every state transition, legal and illegal, including the full
terminal set and ``SUBMITTING -> UNKNOWN``."""

from __future__ import annotations

import pytest

from signalforge.execution.states import (
    LEGAL_TRANSITIONS,
    TERMINAL_STATES,
    UNKNOWN_RESOLUTION_STATES,
    IllegalTransition,
    OrderState,
    UnknownResolution,
    is_terminal,
    next_state,
)

LEGAL_PAIRS = [
    (OrderState.CREATED, OrderState.VALIDATED),
    (OrderState.CREATED, OrderState.REFUSED),
    (OrderState.VALIDATED, OrderState.SUBMITTING),
    (OrderState.VALIDATED, OrderState.EXPIRED),
    (OrderState.SUBMITTING, OrderState.FILLED),
    (OrderState.SUBMITTING, OrderState.PARTIAL),
    (OrderState.SUBMITTING, OrderState.REJECTED),
    (OrderState.SUBMITTING, OrderState.CANCELLED),
    (OrderState.SUBMITTING, OrderState.EXPIRED),
    (OrderState.SUBMITTING, OrderState.UNKNOWN),
]


@pytest.mark.parametrize(("src", "dst"), LEGAL_PAIRS)
def test_every_legal_transition_is_permitted(src: OrderState, dst: OrderState) -> None:
    assert next_state(src, dst) is dst


def test_the_legal_table_contains_exactly_these_pairs() -> None:
    """The table is the contract: an edge added without a test is a state
    machine nobody agreed to."""
    actual = {
        (src, dst)
        for src, targets in LEGAL_TRANSITIONS.items()
        for dst in targets
        if src is not OrderState.UNKNOWN
    }
    assert actual == set(LEGAL_PAIRS)


@pytest.mark.parametrize(
    ("src", "dst"),
    [
        (OrderState.CREATED, OrderState.SUBMITTING),  # validation cannot be skipped
        (OrderState.CREATED, OrderState.FILLED),
        (OrderState.VALIDATED, OrderState.FILLED),  # submission cannot be skipped
        (OrderState.VALIDATED, OrderState.REFUSED),
        (OrderState.SUBMITTING, OrderState.VALIDATED),  # no going back
        (OrderState.SUBMITTING, OrderState.SUBMITTING),  # no resubmission in place
        (OrderState.REFUSED, OrderState.VALIDATED),
        (OrderState.FILLED, OrderState.CANCELLED),
        (OrderState.EXPIRED, OrderState.SUBMITTING),
        (OrderState.CANCELLED, OrderState.FILLED),
    ],
)
def test_illegal_transitions_raise(src: OrderState, dst: OrderState) -> None:
    with pytest.raises(IllegalTransition):
        next_state(src, dst)


def _sufficient_resolution_to(target: OrderState) -> UnknownResolution | None:
    """A resolution good enough to clear an ``UNKNOWN`` *into ``target``*.

    Passed to the cross-product test so a pair is never refused merely because
    no resolution was supplied: the UNKNOWN row is then refused only where the
    table itself refuses it.
    """
    if target not in UNKNOWN_RESOLUTION_STATES:
        return None
    return UnknownResolution(
        reconciled_from_order_status=True,
        operator_acknowledged=True,
        broker_terminal_state=target,
        acknowledged_by="operator",
    )


@pytest.mark.parametrize("src", list(OrderState))
@pytest.mark.parametrize("dst", list(OrderState))
def test_every_pair_the_table_does_not_join_is_refused(src: OrderState, dst: OrderState) -> None:
    """The whole 10x10 cross product, not a hand-picked sample of it.

    The named cases above document *why* particular edges are absent; this one
    closes the gap between "these ten are refused" and "everything outside the
    table is refused", which is the property the machine actually promises.
    """
    if dst in LEGAL_TRANSITIONS.get(src, frozenset()):
        return
    with pytest.raises(IllegalTransition):
        next_state(src, dst, resolution=_sufficient_resolution_to(dst))


def test_the_terminal_set_is_complete() -> None:
    assert {
        OrderState.FILLED,
        OrderState.PARTIAL,
        OrderState.REJECTED,
        OrderState.CANCELLED,
        OrderState.EXPIRED,
        OrderState.REFUSED,
        OrderState.UNKNOWN,
    } == TERMINAL_STATES
    assert not is_terminal(OrderState.CREATED)
    assert not is_terminal(OrderState.VALIDATED)
    assert not is_terminal(OrderState.SUBMITTING)
    for state in TERMINAL_STATES:
        assert is_terminal(state)


def test_submitting_with_no_outcome_reaches_unknown() -> None:
    assert OrderState.UNKNOWN in LEGAL_TRANSITIONS[OrderState.SUBMITTING]


def _resolution(
    state: OrderState = OrderState.FILLED,
    *,
    reconciled: bool = True,
    acknowledged: bool = True,
) -> UnknownResolution:
    return UnknownResolution(
        reconciled_from_order_status=reconciled,
        operator_acknowledged=acknowledged,
        broker_terminal_state=state,
        acknowledged_by="local-user",
    )


def test_unknown_is_never_cleared_by_a_retry() -> None:
    """A bare transition out of UNKNOWN — the shape a retry would take — is
    refused. Both halves of §6 rule 2 are required."""
    with pytest.raises(IllegalTransition, match="never by a retry"):
        next_state(OrderState.UNKNOWN, OrderState.FILLED)


@pytest.mark.parametrize(
    "resolution",
    [
        _resolution(reconciled=False),  # no order_status() lookup
        _resolution(acknowledged=False),  # no operator acknowledgement
    ],
)
def test_unknown_needs_both_halves(resolution: UnknownResolution) -> None:
    with pytest.raises(IllegalTransition):
        next_state(OrderState.UNKNOWN, OrderState.FILLED, resolution=resolution)


def test_unknown_resolves_only_to_what_the_broker_reported() -> None:
    with pytest.raises(IllegalTransition, match="resolved the order to"):
        next_state(
            OrderState.UNKNOWN, OrderState.CANCELLED, resolution=_resolution(OrderState.FILLED)
        )
    assert (
        next_state(OrderState.UNKNOWN, OrderState.FILLED, resolution=_resolution(OrderState.FILLED))
        is OrderState.FILLED
    )


@pytest.mark.parametrize("target", sorted(UNKNOWN_RESOLUTION_STATES))
def test_unknown_resolves_to_every_broker_terminal_state(target: OrderState) -> None:
    assert next_state(OrderState.UNKNOWN, target, resolution=_resolution(target)) is target


@pytest.mark.parametrize(
    "target", [OrderState.CREATED, OrderState.VALIDATED, OrderState.SUBMITTING, OrderState.REFUSED]
)
def test_unknown_can_never_re_enter_the_submission_path(target: OrderState) -> None:
    with pytest.raises(IllegalTransition):
        next_state(OrderState.UNKNOWN, target, resolution=_resolution(target))
