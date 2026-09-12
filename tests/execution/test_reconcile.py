"""D6 §10 — reconciliation: divergence, staleness, and never auto-repairing.

Drills V3 (a broker position with no matching ``client_order_id`` halts, disarms,
alerts, and is NOT auto-corrected) and V4 (no fresh reconciliation inside
``max_reconciliation_age_s`` blocks exactly as a dead-man lapse does).

The adapter here is a fake (``tests/execution/fakes.py``) and nothing in this
module depends on ``brokers/paper_reference.py``, which is being built on another
branch.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from signalforge.db.models import ExecutionEvent
from signalforge.execution import reconcile as reconcile_mod
from signalforge.execution.events import ExecutionEventType, record_execution_event
from signalforge.execution.intents import PositionLeg, PositionSnapshot
from signalforge.execution.limits import may_open
from signalforge.execution.states import OrderState
from tests.execution.conftest import ADAPTER, NOW, clean_open_context
from tests.execution.fakes import FakeAdapter, FakePosition

ORIGIN = "11112222333344445555666677778888"  # pragma: allowlist secret


@pytest.fixture
def originated(session: Session) -> str:
    """A position this OMS really did open — C-P2's positive proof."""
    record_execution_event(
        session,
        event_type=ExecutionEventType.SUBMITTING,
        adapter_name=ADAPTER,
        client_order_id=ORIGIN,
        state_from=OrderState.VALIDATED.value,
        state_to=OrderState.SUBMITTING.value,
    )
    return ORIGIN


def _position(origin: str, symbol: str = "SPY") -> FakePosition:
    return FakePosition(
        snapshot=PositionSnapshot(
            adapter_name=ADAPTER,
            legs=(PositionLeg(instrument_key=symbol, signed_qty=10.0),),
        ),
        originating_client_order_id=origin,
    )


def test_a_book_this_oms_opened_reconciles_clean(session: Session, originated: str) -> None:
    adapter = FakeAdapter(positions_=[_position(originated)])

    result = reconcile_mod.reconcile(session, adapter, now=NOW, limits=None)

    assert result.clean
    assert result.divergences == ()
    assert "all originated here" in result.detail
    events = session.scalars(
        select(ExecutionEvent).where(
            ExecutionEvent.event_type == ExecutionEventType.RECONCILED.value
        )
    ).all()
    assert len(events) == 1


def test_a_foreign_position_is_a_divergence_and_is_never_repaired(session: Session) -> None:
    """Drill V3. Also the live signature of an early assignment — the tail the
    backtest approximates away."""
    adapter = FakeAdapter(positions_=[_position("an-id-this-oms-never-wrote")])

    result = reconcile_mod.reconcile(session, adapter, now=NOW, limits=None)

    assert result.diverged
    assert result.divergences[0].kind == "FOREIGN_POSITION"
    assert "not auto-corrected" in result.divergences[0].detail
    # Nothing was cancelled, closed, or adjusted: the adapter was only read.
    assert adapter.cancel_all_calls == 0
    assert adapter.placed == []
    events = session.scalars(
        select(ExecutionEvent).where(
            ExecutionEvent.event_type == ExecutionEventType.RECONCILIATION_DIVERGED.value
        )
    ).all()
    assert len(events) == 1
    assert events[0].payload_json["divergences"][0]["kind"] == "FOREIGN_POSITION"


def test_a_position_with_no_originating_id_is_a_divergence(session: Session) -> None:
    """The broker does not owe us an originating id; its absence is a divergence,
    not a pass."""
    adapter = FakeAdapter(positions_=[_position("")])

    result = reconcile_mod.reconcile(session, adapter, now=NOW, limits=None)

    assert result.diverged
    assert "no originating client_order_id" in result.divergences[0].detail


def test_a_foreign_open_order_is_a_divergence_not_a_retry(session: Session) -> None:
    """§8 rule 3 from the other direction: a broker order id the local store has
    never seen halts."""
    from signalforge.execution.intents import OrderStatus

    adapter = FakeAdapter(
        open_orders_=[OrderStatus(client_order_id="unknown-to-us", state=OrderState.SUBMITTING)]
    )

    result = reconcile_mod.reconcile(session, adapter, now=NOW, limits=None)

    assert result.diverged
    assert result.divergences[0].kind == "FOREIGN_ORDER"
    assert "never a retry" in result.divergences[0].detail


def test_an_unreachable_adapter_is_its_own_status(session: Session) -> None:
    """UNREACHABLE is not DIVERGED and not CLEAN: "could not ask" is a third
    thing, and the close lane reads it as C-P5."""
    adapter = FakeAdapter(raise_on=frozenset({"positions"}))

    result = reconcile_mod.reconcile(session, adapter, now=NOW, limits=None)

    assert result.status is reconcile_mod.ReconciliationStatus.UNREACHABLE
    assert not result.clean
    assert not result.diverged
    assert result.adapter_reachable is False


def test_buying_power_divergence_beyond_the_binding_tolerance_halts(
    session: Session, limit_set: object
) -> None:
    """The local collateral model is a model; the broker's figure is
    authoritative."""
    adapter = FakeAdapter(buying_power=25_000.0)

    ok = reconcile_mod.reconcile(
        session, adapter, now=NOW, limits=limit_set, local_buying_power=24_999.80  # type: ignore[arg-type]
    )
    assert ok.clean

    bad = reconcile_mod.reconcile(
        session, adapter, now=NOW, limits=limit_set, local_buying_power=24_000.0  # type: ignore[arg-type]
    )
    assert bad.diverged
    assert bad.divergences[0].kind == "BUYING_POWER"


def test_the_binding_tolerance_is_the_tighter_of_the_two_forms() -> None:
    # $1.00 vs 0.1% of $25,000 = $25.00 -> the dollar figure binds.
    assert reconcile_mod.binding_buying_power_tolerance(
        tolerance_usd=1.0, tolerance_pct=0.1, buying_power=25_000.0
    ) == pytest.approx(1.0)
    # $1.00 vs 0.1% of $500 = $0.50 -> the percentage binds.
    assert reconcile_mod.binding_buying_power_tolerance(
        tolerance_usd=1.0, tolerance_pct=0.1, buying_power=500.0
    ) == pytest.approx(0.5)
    # An uncomputable tolerance is not a tolerance.
    assert (
        reconcile_mod.binding_buying_power_tolerance(
            tolerance_usd=1.0, tolerance_pct=0.1, buying_power=None
        )
        is None
    )


def test_no_limits_row_makes_the_tolerance_unknown_and_that_halts(session: Session) -> None:
    adapter = FakeAdapter()
    result = reconcile_mod.reconcile(session, adapter, now=NOW, limits=None, local_buying_power=1.0)
    assert result.diverged
    assert result.divergences[0].kind == "NO_LIMITS_ROW"


# ---------------------------------------------------------------------------
# Staleness — drill V4
# ---------------------------------------------------------------------------


def test_never_reconciled_is_not_reconciled_recently(session: Session) -> None:
    assert (
        reconcile_mod.last_clean_reconciliation_age_s(session, adapter_name=ADAPTER, now=NOW)
        is None
    )


def test_a_divergence_does_not_reset_the_staleness_clock(session: Session) -> None:
    """A RECONCILIATION_DIVERGED row is a reconciliation that happened and
    FAILED; counting it as freshness would let a divergence hide staleness."""
    adapter = FakeAdapter(positions_=[_position("foreign")])
    reconcile_mod.reconcile(session, adapter, now=NOW, limits=None)

    assert (
        reconcile_mod.last_clean_reconciliation_age_s(session, adapter_name=ADAPTER, now=NOW)
        is None
    )


def test_the_age_is_measured_from_the_last_clean_result(session: Session, originated: str) -> None:
    """Measured against the recorded event's own ``ts``, which
    ``record_execution_event`` stamps from the real clock — so the age is
    anchored to when the row was actually written, not to whatever ``now`` the
    caller passed in."""
    from signalforge.db.types import utcnow

    adapter = FakeAdapter(positions_=[_position(originated)])
    written_at = utcnow()
    reconcile_mod.reconcile(session, adapter, now=written_at, limits=None)

    age = reconcile_mod.last_clean_reconciliation_age_s(
        session, adapter_name=ADAPTER, now=written_at + timedelta(seconds=45)
    )
    assert age is not None
    assert 44.0 < age < 47.0


def test_stale_reconciliation_blocks_opening_exactly_as_a_dead_man_lapse_does(
    limit_set: object,
) -> None:
    stale = may_open(clean_open_context(reconciliation_age_s=121.0), limit_set)  # type: ignore[arg-type]
    lapsed = may_open(clean_open_context(dead_man_alive=False), limit_set)  # type: ignore[arg-type]

    assert not stale.allowed
    assert not lapsed.allowed
    assert "blocks exactly like a dead-man lapse" in {c.name: c.detail for c in stale.checks}["R1"]


def test_an_unevaluated_reconciliation_blocks_opening(limit_set: object) -> None:
    decision = may_open(
        clean_open_context(reconciliation_clean=None, reconciliation_age_s=None),
        limit_set,  # type: ignore[arg-type]
    )
    assert not decision.allowed


# ---------------------------------------------------------------------------
# §13 rule 4b — the expected account id survives disarming
# ---------------------------------------------------------------------------


def test_the_expected_account_id_reads_disarmed_and_expired_rows(
    session: Session, armed: object
) -> None:
    from signalforge.db.types import utcnow

    armed.disarmed_at = utcnow()  # type: ignore[attr-defined]
    armed.disarm_reason = "expired"  # type: ignore[attr-defined]
    session.flush()

    assert reconcile_mod.expected_account_id_for(session, ADAPTER) == "PAPER-ACCOUNT-1"


def test_with_no_row_ever_the_expected_account_id_is_a_refusal(session: Session) -> None:
    """An empty string is the refusal signal: reconciliation halts rather than
    proceeding against an unproven account."""
    assert reconcile_mod.expected_account_id_for(session, "never-armed") == ""
    assert (
        reconcile_mod.expected_account_id_for(
            session, "never-armed", adapter_configured_account_id="FROM-REVIEWED-CONFIG"
        )
        == "FROM-REVIEWED-CONFIG"
    )
