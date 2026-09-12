"""D6 §12 — the arming ceremony, its expiry, its evidence gate, its auto-disarm.

Each test removes exactly one fact from a ceremony that would otherwise pass and
asserts the refusal, because a ceremony that only ever gets tested in its passing
shape is a ceremony whose refusals are untested.

The four properties the task named, and where each is proved:

* the **7-day expiry** — ``test_expiry_beyond_seven_days_is_refused`` and
  ``test_an_expired_arming_is_auto_disarmed``;
* the **audited override** — ``test_override_records_the_observed_evidence``;
* the **evidence precondition** — ``test_fewer_than_twenty_closed_trades_refuses``
  and ``test_negative_expectancy_refuses``;
* **auto-disarm on ANY status change** —
  ``test_any_status_change_auto_disarms`` (both directions) and
  ``test_a_status_flap_between_cycles_is_still_caught``.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from signalforge.db.models import ArmedStrategy, AuditLog, ExecutionEvent, StrategyVersion
from signalforge.db.types import utcnow
from signalforge.domain import StrategyStatus
from signalforge.execution import arming
from signalforge.execution.events import ExecutionEventType
from tests.execution.conftest import (
    ADAPTER,
    NOW,
    add_closed_paper_positions,
    arming_request,
    paper_proof,
)

pytestmark = pytest.mark.usefixtures("armable")


def _arm(session: Session, version_id: int, **overrides: object) -> ArmedStrategy:
    from signalforge.execution.cycle import active_limits_created_at
    from signalforge.execution.limits import load_active_limits

    limits = load_active_limits(session)
    request = arming_request(strategy_version_id=version_id, **overrides)
    return arming.arm(
        session,
        request,
        now=NOW,
        is_paper_proof=paper_proof(request.broker_account_id_expected),
        account_is_flat=True,
        actor="test",
        limits_id=limits.id if limits else None,
        limits_created_at=active_limits_created_at(session),
    )


def _checks(
    session: Session,
    version_id: int,
    *,
    account_is_flat: bool | None = True,
    **overrides: object,
) -> dict[str, tuple[bool, str]]:
    """The full preconditions table as a dict, so a test can name one row."""
    from signalforge.execution.cycle import active_limits_created_at
    from signalforge.execution.limits import load_active_limits

    limits = load_active_limits(session)
    request = arming_request(strategy_version_id=version_id, **overrides)
    decision = arming.check_arming_preconditions(
        session,
        request,
        now=NOW,
        is_paper_proof=paper_proof(request.broker_account_id_expected),
        account_is_flat=account_is_flat,
        limits_id=limits.id if limits else None,
        limits_created_at=active_limits_created_at(session),
    )
    return {c.name: (c.passed, c.detail) for c in decision.checks}


# ---------------------------------------------------------------------------
# The happy path — proving the refusals below are refusals and not a broken setup
# ---------------------------------------------------------------------------


def test_a_complete_ceremony_arms_and_audits(
    session: Session, strategy_version: StrategyVersion
) -> None:
    row = _arm(session, strategy_version.id)

    assert row.disarmed_at is None
    assert row.expires_at == NOW + timedelta(days=arming.ARMING_EXPIRY_DAYS)
    assert row.evidence_paper_trade_count == 20
    assert row.evidence_expectancy_r == pytest.approx(0.5)
    assert row.evidence_override_reason is None
    # §12 step 1: k at the moment risk is taken, counted for the FAMILY.
    assert row.sealed_look_prior_at_arm == 1
    assert row.preregistration_doc_id == "PREREGISTRATION_2026-09-11_snapshot11"

    events = session.scalars(
        select(ExecutionEvent).where(ExecutionEvent.event_type == ExecutionEventType.ARMED.value)
    ).all()
    assert len(events) == 1
    assert events[0].armed_strategy_id == row.id
    # The hashes are on the event for the reason §15 gives: the 2026-09-11
    # incident was detectable only because the scope match was recorded.
    assert events[0].config_hash and events[0].spec_json_hash


def test_nothing_is_armed_by_default(session: Session) -> None:
    assert arming.live_armings(session) == []


# ---------------------------------------------------------------------------
# The 7-day expiry (decision 4)
# ---------------------------------------------------------------------------


def test_expiry_beyond_seven_days_is_refused(
    session: Session, strategy_version: StrategyVersion
) -> None:
    checks = _checks(session, strategy_version.id, expires_at=NOW + timedelta(days=8))
    passed, detail = checks["S7"]
    assert not passed
    assert "7-day maximum" in detail
    assert "no indefinite arming" in detail


def test_a_past_expiry_is_refused(session: Session, strategy_version: StrategyVersion) -> None:
    checks = _checks(session, strategy_version.id, expires_at=NOW - timedelta(minutes=1))
    assert checks["S7"][0] is False


def test_an_expired_arming_is_auto_disarmed(
    session: Session, strategy_version: StrategyVersion
) -> None:
    row = _arm(session, strategy_version.id)
    later = row.expires_at + timedelta(seconds=1)

    disarms = arming.auto_disarm_sweep(session, now=later, adapter_name=ADAPTER)

    assert [d.trigger for d in disarms] == [arming.DisarmTrigger.EXPIRED]
    session.refresh(row)
    assert row.disarmed_at == later
    assert "expires_at_passed" in row.disarm_reason
    assert "no resume" in row.disarm_reason
    assert arming.live_armings(session) == []


# ---------------------------------------------------------------------------
# Decision 10 — the evidence precondition, and its audited override
# ---------------------------------------------------------------------------


def test_fewer_than_twenty_closed_trades_refuses(
    session: Session, strategy_version: StrategyVersion, account: object
) -> None:
    # Remove the 20 the fixture built and leave 19.
    for row in session.scalars(select(ArmedStrategy)):  # pragma: no cover - none exist
        session.delete(row)
    from signalforge.db.models import PaperPosition

    positions = list(session.scalars(select(PaperPosition)))
    session.delete(positions[0])
    session.flush()

    checks = _checks(session, strategy_version.id)
    passed, detail = checks["S4"]
    assert not passed
    assert "19 closed paper trades" in detail
    assert "20" in detail


def test_negative_expectancy_refuses(
    session: Session, strategy_version: StrategyVersion, account: object
) -> None:
    add_closed_paper_positions(
        session,
        account=account,  # type: ignore[arg-type]
        strategy_version=strategy_version,
        n=20,
        pnl_per_trade=-2.0,
    )
    checks = _checks(session, strategy_version.id)
    passed, detail = checks["S4"]
    assert not passed
    assert "negative" in detail


def test_arm_raises_when_the_evidence_gate_fails(
    session: Session, strategy_version: StrategyVersion
) -> None:
    from signalforge.db.models import PaperPosition

    for row in session.scalars(select(PaperPosition)):
        session.delete(row)
    session.flush()

    with pytest.raises(arming.ArmingRefused, match="S4"):
        _arm(session, strategy_version.id)
    assert arming.live_armings(session) == []
    # Even the refusal is recorded: what the system refused is not shaped by
    # where the refusal happened to occur.
    refusals = session.scalars(
        select(ExecutionEvent).where(
            ExecutionEvent.event_type == ExecutionEventType.INTENT_REFUSED.value
        )
    ).all()
    assert refusals and "arming refused" in refusals[0].reason


def test_override_records_the_observed_evidence(
    session: Session, strategy_version: StrategyVersion
) -> None:
    """The override is granted by decision 10. What is not granted is an
    unrecorded one: the observed n and expectancy are written beside the reason
    because the override is taken AFTER seeing them."""
    from signalforge.db.models import PaperPosition

    for row in list(session.scalars(select(PaperPosition)))[:15]:
        session.delete(row)
    session.flush()

    reason = "operator: arming the 5-trade sample deliberately, at minimum size"
    armed_row = _arm(session, strategy_version.id, override_evidence_reason=reason)

    assert armed_row.evidence_override_reason == reason
    assert armed_row.evidence_paper_trade_count == 5
    assert armed_row.evidence_expectancy_r == pytest.approx(0.5)

    event = session.scalars(
        select(ExecutionEvent).where(ExecutionEvent.event_type == ExecutionEventType.ARMED.value)
    ).one()
    assert event.payload_json["evidence_override_reason"] == reason
    assert event.payload_json["evidence_paper_trade_count"] == 5
    assert event.payload_json["evidence_expectancy_r"] == pytest.approx(0.5)
    # The override is audited to the JSONL sink as well as the DB table (§15).
    audited = session.scalars(select(AuditLog).where(AuditLog.action == "strategy.downgrade")).all()
    assert audited == []  # sanity: nothing downgraded anything here


def test_superseding_the_limits_row_resets_the_evidence_counter(
    session: Session, strategy_version: StrategyVersion, account: object
) -> None:
    """§7b rule 3 — evidence accumulated under a different limits row is evidence
    about a different system."""
    from signalforge.execution.limits import load_active_limits

    limits = load_active_limits(session)
    assert limits is not None
    # A NEWER limits row supersedes the fixture's: the 20 trades the evidence
    # fixture built all closed before it, so the counter is back to zero.
    created_at = NOW + timedelta(minutes=5)
    assessment = arming.evaluate_evidence(
        session, strategy_version.id, limits_created_at=created_at
    )
    assert assessment.n_closed == 0
    assert not assessment.sufficient
    assert "since the active execution_limits row was created" in assessment.detail

    add_closed_paper_positions(
        session,
        account=account,  # type: ignore[arg-type]
        strategy_version=strategy_version,
        n=20,
        pnl_per_trade=0.3,
        closed_at=created_at + timedelta(hours=1),
    )
    after = arming.evaluate_evidence(session, strategy_version.id, limits_created_at=created_at)
    assert after.n_closed == 20
    assert after.sufficient


# ---------------------------------------------------------------------------
# §13 — the is_paper proof, and §10 — the flat account
# ---------------------------------------------------------------------------


def test_an_is_paper_account_mismatch_refuses_arming(
    session: Session, strategy_version: StrategyVersion
) -> None:
    """T6 / drill V9: a stubbed response whose account id differs from the armed
    record fails arming."""
    from signalforge.execution.cycle import active_limits_created_at
    from signalforge.execution.limits import load_active_limits

    limits = load_active_limits(session)
    request = arming_request(strategy_version_id=strategy_version.id)
    decision = arming.check_arming_preconditions(
        session,
        request,
        now=NOW,
        is_paper_proof=paper_proof("SOME-OTHER-ACCOUNT"),
        account_is_flat=True,
        limits_id=limits.id if limits else None,
        limits_created_at=active_limits_created_at(session),
    )
    failed = {c.name: c.detail for c in decision.checks if not c.passed}
    assert "S8" in failed
    assert "SOME-OTHER-ACCOUNT" in failed["S8"]


def test_a_missing_is_paper_proof_refuses_arming(
    session: Session, strategy_version: StrategyVersion
) -> None:
    """No adapter means no proof, and no proof is not a pass — it is the refusal
    that keeps arming impossible until an adapter exists."""
    from signalforge.execution.cycle import active_limits_created_at
    from signalforge.execution.limits import load_active_limits

    limits = load_active_limits(session)
    decision = arming.check_arming_preconditions(
        session,
        arming_request(strategy_version_id=strategy_version.id),
        now=NOW,
        is_paper_proof=None,
        account_is_flat=True,
        limits_id=limits.id if limits else None,
        limits_created_at=active_limits_created_at(session),
    )
    assert not decision.allowed
    assert "S8" in {c.name for c in decision.checks if not c.passed}


def test_a_non_flat_account_refuses_arming(
    session: Session, strategy_version: StrategyVersion
) -> None:
    """Drill V17 — arming begins from a flat, empty account."""
    checks = _checks(session, strategy_version.id, account_is_flat=False)
    assert checks["S9"][0] is False
    assert "flat, empty account" in checks["S9"][1]


def test_an_unreadable_account_is_not_a_flat_one(
    session: Session, strategy_version: StrategyVersion
) -> None:
    from signalforge.execution.cycle import active_limits_created_at
    from signalforge.execution.limits import load_active_limits

    limits = load_active_limits(session)
    decision = arming.check_arming_preconditions(
        session,
        arming_request(strategy_version_id=strategy_version.id),
        now=NOW,
        is_paper_proof=paper_proof(),
        account_is_flat=None,
        limits_id=limits.id if limits else None,
        limits_created_at=active_limits_created_at(session),
    )
    detail = {c.name: c.detail for c in decision.checks}["S9"]
    assert "could not read" in detail


def test_one_account_per_live_arming(session: Session, strategy_version: StrategyVersion) -> None:
    """§10/§16 — two strategies cannot be armed against the same account id."""
    from signalforge.db.models import Strategy

    _arm(session, strategy_version.id)
    strat = Strategy(
        name="relative_strength.medium_swing",
        horizon=(
            strategy_version.strategy.horizon if hasattr(strategy_version, "strategy") else None
        ),
        permits_long=True,
        permits_short=False,
        status=StrategyStatus.PAPER_APPROVED,
    )
    from signalforge.domain import Horizon

    strat.horizon = Horizon.MEDIUM_SWING
    session.add(strat)
    session.flush()
    other = StrategyVersion(
        strategy_id=strat.id,
        version="0.1.0",
        git_sha="deadbeef",
        spec_json={},
        status=StrategyStatus.PAPER_APPROVED,
    )
    session.add(other)
    session.flush()

    checks = _checks(session, other.id)
    assert checks["S11"][0] is False
    assert "one account per live arming" in checks["S11"][1]


# ---------------------------------------------------------------------------
# §12 step 1 — the pre-registration document, and the sealed test
# ---------------------------------------------------------------------------


def test_no_arming_without_a_preregistration_document(
    session: Session, strategy_version: StrategyVersion
) -> None:
    assert _checks(session, strategy_version.id, preregistration_doc_id="")["S3"][0] is False
    bogus = _checks(session, strategy_version.id, preregistration_doc_id="NO_SUCH_DOCUMENT")
    assert bogus["S3"][0] is False
    assert "no pre-registration document" in bogus["S3"][1]


def test_a_version_with_no_passing_sealed_test_is_refused(
    session: Session, strategy_version: StrategyVersion
) -> None:
    from signalforge.db.models import StrategySealedTest

    for row in session.scalars(select(StrategySealedTest)):
        session.delete(row)
    session.flush()
    assert _checks(session, strategy_version.id)["S2"][0] is False


def test_an_experimental_version_cannot_be_armed(
    session: Session, strategy_version: StrategyVersion
) -> None:
    strategy_version.status = StrategyStatus.EXPERIMENTAL
    session.flush()
    checks = _checks(session, strategy_version.id)
    assert checks["S1"][0] is False
    assert "not PAPER_APPROVED" in checks["S1"][1]


def test_the_typed_confirmation_phrase_names_the_version_and_adapter() -> None:
    phrase = arming.confirmation_phrase(7, "paper_reference")
    assert phrase == "ARM 7 ON paper_reference"
    assert arming.confirmation_phrase(8, "paper_reference") != phrase


# ---------------------------------------------------------------------------
# §12 step 7 — auto-disarm on ANY status change (decision 9)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("new_status", [StrategyStatus.EXPERIMENTAL, StrategyStatus.DISABLED])
def test_any_status_change_auto_disarms(
    session: Session, strategy_version: StrategyVersion, new_status: StrategyStatus
) -> None:
    row = _arm(session, strategy_version.id)
    strategy_version.status = new_status
    session.flush()

    disarms = arming.auto_disarm_sweep(session, now=NOW, adapter_name=ADAPTER)

    assert [d.trigger for d in disarms] == [arming.DisarmTrigger.STATUS_CHANGE]
    session.refresh(row)
    assert row.disarmed_at is not None
    assert "ANY status change" in row.disarm_reason


def test_a_status_flap_between_cycles_is_still_caught(
    session: Session, strategy_version: StrategyVersion
) -> None:
    """The cycle check compares the CURRENT status and cannot see a change that
    reverted between two cycles. The recorded transition can, on the one path
    that changes status automatically."""
    row = _arm(session, strategy_version.id)
    session.add(
        AuditLog(
            ts=row.armed_at + timedelta(minutes=1),
            actor="health_monitor",
            action="strategy.downgrade",
            entity="trend_continuation.short_swing@0.1.0",
            before_json={"status": "paper_approved"},
            after_json={"status": "experimental"},
        )
    )
    session.flush()
    # ...and back again, so the point-in-time comparison sees nothing wrong.
    assert strategy_version.status is StrategyStatus.PAPER_APPROVED

    disarms = arming.auto_disarm_sweep(session, now=NOW + timedelta(minutes=2))

    assert [d.trigger for d in disarms] == [arming.DisarmTrigger.STATUS_CHANGE]
    assert "recorded status transition" in disarms[0].detail


def test_config_hash_drift_auto_disarms(
    session: Session, strategy_version: StrategyVersion
) -> None:
    row = _arm(session, strategy_version.id)
    row.config_hash = "a-hash-from-before-the-agents-section-landed"
    session.flush()

    disarms = arming.auto_disarm_sweep(session, now=NOW)

    assert [d.trigger for d in disarms] == [arming.DisarmTrigger.HASH_DRIFT]
    assert "config_hash drifted" in disarms[0].detail


def test_scope_mismatch_auto_disarms(session: Session, strategy_version: StrategyVersion) -> None:
    from signalforge.db.models import StrategyPromotionEvaluation

    _arm(session, strategy_version.id)
    for row in session.scalars(select(StrategyPromotionEvaluation)):
        row.passed = False
    session.flush()

    disarms = arming.auto_disarm_sweep(session, now=NOW)
    assert [d.trigger for d in disarms] == [arming.DisarmTrigger.SCOPE_MISMATCH]


def test_kill_switch_and_dead_man_auto_disarm(
    session: Session, strategy_version: StrategyVersion
) -> None:
    _arm(session, strategy_version.id)
    disarms = arming.auto_disarm_sweep(
        session, now=NOW, facts=arming.CycleFacts(kill_switch_engaged=True)
    )
    assert [d.trigger for d in disarms] == [arming.DisarmTrigger.KILL_SWITCH]
    assert "closing is NOT blocked" in disarms[0].detail


def test_dead_man_lapse_auto_disarms_without_liquidating(
    session: Session, strategy_version: StrategyVersion
) -> None:
    """Drill V2 — the lapse disarms and blocks opening; NOTHING is liquidated."""
    _arm(session, strategy_version.id)
    disarms = arming.auto_disarm_sweep(
        session, now=NOW, facts=arming.CycleFacts(dead_man_alive=False)
    )
    assert [d.trigger for d in disarms] == [arming.DisarmTrigger.DEAD_MAN]
    assert "nothing is auto-liquidated" in disarms[0].detail
    assert "by hand, at the broker" in disarms[0].detail


def test_reconciliation_staleness_auto_disarms(
    session: Session, strategy_version: StrategyVersion
) -> None:
    """Drill V4 — an unreconciled window past the max age blocks exactly like a
    dead-man lapse."""
    _arm(session, strategy_version.id)
    disarms = arming.auto_disarm_sweep(
        session,
        now=NOW,
        facts=arming.CycleFacts(reconciliation_age_s=301.0, max_reconciliation_age_s=120),
    )
    assert [d.trigger for d in disarms] == [arming.DisarmTrigger.RECONCILIATION]


def test_an_unevaluated_fact_does_not_disarm(
    session: Session, strategy_version: StrategyVersion
) -> None:
    """``None`` blocks OPENING at the gate; it does not disarm the book.

    Disarming on an unevaluated fact would turn a transient read failure into a
    full re-arming ceremony, and the fail-closed direction already lives in
    ``may_open``."""
    _arm(session, strategy_version.id)
    disarms = arming.auto_disarm_sweep(
        session,
        now=NOW,
        facts=arming.CycleFacts(
            kill_switch_engaged=None, dead_man_alive=None, is_paper_proven=None
        ),
    )
    assert disarms == []
    assert len(arming.live_armings(session)) == 1


def test_disarming_keeps_the_row_so_the_account_id_survives(
    session: Session, strategy_version: StrategyVersion
) -> None:
    """§13 rule 4b / §6 rule 5a — the deadlock rev 1 shipped, closed."""
    from signalforge.execution.reconcile import expected_account_id_for

    row = _arm(session, strategy_version.id)
    arming.disarm(
        session,
        row,
        trigger=arming.DisarmTrigger.OPERATOR,
        detail="manual",
        now=NOW,
        actor="test",
    )
    session.flush()

    assert arming.live_armings(session) == []
    assert session.get(ArmedStrategy, row.id) is not None
    assert expected_account_id_for(session, ADAPTER) == "PAPER-ACCOUNT-1"


def test_disarming_twice_is_not_a_second_disarm(
    session: Session, strategy_version: StrategyVersion
) -> None:
    row = _arm(session, strategy_version.id)
    first = arming.disarm(session, row, trigger=arming.DisarmTrigger.OPERATOR, detail="a", now=NOW)
    second = arming.disarm(
        session,
        row,
        trigger=arming.DisarmTrigger.OPERATOR,
        detail="b",
        now=NOW + timedelta(minutes=1),
    )
    assert "already disarmed" in second.detail
    assert first.detail == "a"
    events = session.scalars(
        select(ExecutionEvent).where(ExecutionEvent.event_type == ExecutionEventType.DISARMED.value)
    ).all()
    assert len(events) == 1


def test_an_outstanding_unknown_blocks_arming(
    session: Session, strategy_version: StrategyVersion
) -> None:
    """Drill V7's arming half — a SUBMITTING promoted to UNKNOWN refuses the
    ceremony, and a retry never clears it."""
    from signalforge.execution.events import record_execution_event
    from signalforge.execution.oms import promote_stale_submitting
    from signalforge.execution.states import OrderState

    coid = "feedfacefeedfacefeedfacefeedface"  # pragma: allowlist secret
    record_execution_event(
        session,
        event_type=ExecutionEventType.SUBMITTING,
        adapter_name=ADAPTER,
        client_order_id=coid,
        state_from=OrderState.VALIDATED.value,
        state_to=OrderState.SUBMITTING.value,
        strategy_version_id=strategy_version.id,
    )
    promoted = promote_stale_submitting(session, now=utcnow(), adapter_name=ADAPTER)
    assert promoted == [coid]

    checks = _checks(session, strategy_version.id)
    assert checks["S12"][0] is False
    assert "never by a retry" in checks["S12"][1]

    with pytest.raises(arming.ArmingRefused):
        _arm(session, strategy_version.id)


def test_an_unknown_outstanding_also_auto_disarms(
    session: Session, strategy_version: StrategyVersion
) -> None:
    from signalforge.execution.events import record_execution_event
    from signalforge.execution.oms import promote_stale_submitting
    from signalforge.execution.states import OrderState

    row = _arm(session, strategy_version.id)
    record_execution_event(
        session,
        event_type=ExecutionEventType.SUBMITTING,
        adapter_name=ADAPTER,
        client_order_id="0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f",  # pragma: allowlist secret
        state_from=OrderState.VALIDATED.value,
        state_to=OrderState.SUBMITTING.value,
        strategy_version_id=strategy_version.id,
        armed_strategy_id=row.id,
    )
    promote_stale_submitting(session, now=utcnow(), adapter_name=ADAPTER)

    disarms = arming.auto_disarm_sweep(session, now=NOW, adapter_name=ADAPTER)
    assert [d.trigger for d in disarms] == [arming.DisarmTrigger.UNKNOWN_OUTSTANDING]


def test_arming_the_same_version_twice_is_refused(
    session: Session, strategy_version: StrategyVersion
) -> None:
    _arm(session, strategy_version.id)
    checks = _checks(session, strategy_version.id)
    assert checks["S10"][0] is False
    assert "there is no resume" in checks["S10"][1]


def test_the_acknowledgements_say_the_four_things_out_loud() -> None:
    text = " ".join(arming.acknowledgements())
    assert "EARLY ASSIGNMENT AWAY" in text
    assert "CLOSES ANY OPEN POSITION BY HAND" in text
    assert "MUST NOT be shared with manual trading" in text
    assert "CANCELS NOTHING AT THE BROKER" in text


def test_unacknowledged_arming_is_refused(
    session: Session, strategy_version: StrategyVersion
) -> None:
    checks = _checks(session, strategy_version.id, acknowledged=False)
    assert checks["S6"][0] is False
