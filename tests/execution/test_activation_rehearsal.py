"""The arming sequence in `docs/PAPER_PROBATION_ACTIVATION.md`, rehearsed.

Before W4a that sequence could not be run at all: no supported interface set
``research.execution.enabled``, nothing constructed an ``execution_limits`` row,
and ``cli._execution_adapter()`` looked up a registry attribute that has never
existed — so ``execution arm`` failed check S8 ("no is_paper() proof was taken
this ceremony") every single time. Three separate reasons the documented
ceremony was prose.

This module runs the documented commands, in the documented order, against a
scratch database, and ends where the operator's day ends: an armed row, and then
a status change that takes the authority away again. If the documented sequence
and this test ever disagree, one of them is wrong and the suite says so.

Nothing here touches the live database (the ``session``/``db_url`` fixtures point
``DATABASE_URL`` and ``SIGNALFORGE_DATA_DIR`` at a tmp_path), and the only
adapter is ``paper_reference`` — local, deterministic, network-free, no
credential.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from typer.testing import CliRunner

from signalforge.cli import app
from signalforge.db.models import (
    ArmedStrategy,
    AuditLog,
    ExecutionEvent,
    ExecutionLimits,
    StrategyVersion,
)
from signalforge.domain import StrategyStatus
from signalforge.execution import arming
from signalforge.execution.brokers.paper_reference import SIMULATED_ACCOUNT_PREFIX
from tests.execution.conftest import add_closed_paper_positions

runner = CliRunner()

#: The account id an operator types OUT OF BAND. ``paper_reference`` refuses an
#: id without its simulated prefix, which is the point: a real-looking broker
#: account id cannot be typed at this adapter by accident.
ACCOUNT_ID = f"{SIMULATED_ACCOUNT_PREFIX}REHEARSAL-1"
PREREGISTRATION = "PREREGISTRATION_execution_limits_v1"


@pytest.fixture(autouse=True)
def _db(db_url: str) -> str:
    return db_url


@pytest.fixture
def rehearsal_version(
    session: Session,
    account: object,
    approved_evaluation: object,
    strategy_version: StrategyVersion,
) -> StrategyVersion:
    """§12 steps 1-2's research facts and NOTHING else.

    Deliberately not the suite's ``armable`` fixture: that one hands over a
    limits row created 30 days back and twenty closed trades under it, which is
    the two things this rehearsal has to create through the documented commands.
    """
    return strategy_version


def _invoke(*argv: str) -> object:
    result = runner.invoke(app, list(argv))
    assert result.exit_code == 0, f"{' '.join(argv)} exited {result.exit_code}\n{result.output}"
    return result


def _seed_evidence_under_the_active_row(session: Session, version: StrategyVersion) -> None:
    """§7b rule 3 in practice: decision-10 evidence counts only from the ACTIVE
    limits row's ``created_at``, so the twenty closed trades have to post-date
    the row. That ordering is a real constraint on the operator's calendar, and
    the rehearsal honours it rather than back-dating the row."""
    from signalforge.db.models import PaperAccount

    row = session.scalars(
        select(ExecutionLimits).where(ExecutionLimits.superseded_at.is_(None))
    ).one()
    account = session.scalars(select(PaperAccount)).first()
    assert account is not None
    add_closed_paper_positions(
        session,
        account=account,
        strategy_version=version,
        n=20,
        pnl_per_trade=0.5,
        closed_at=row.created_at + timedelta(seconds=1),
    )
    session.commit()


def test_the_documented_arming_sequence_runs_end_to_end(
    session: Session, rehearsal_version: StrategyVersion
) -> None:
    """enable → limits set → arm, exactly as documented, then auto-disarm."""
    version_id = rehearsal_version.id
    session.commit()

    # ---- step 0: the posture before anything is done --------------------
    before = runner.invoke(app, ["execution", "status"])
    assert "execution.enabled = False" in before.output
    assert "armed strategies: NONE" in before.output

    # ---- step 1: enable -------------------------------------------------
    refused = runner.invoke(app, ["execution", "enable"])
    assert refused.exit_code == 2, refused.output
    assert "--yes is required" in refused.output

    enabled = _invoke("execution", "enable", "--yes")
    assert "live: execution.enabled = True" in enabled.output
    assert "armed strategies: 0" in enabled.output

    # ---- step 2: the limits row, from the pre-registration document ------
    no_doc = runner.invoke(app, ["execution", "limits", "set", "--yes"])
    assert no_doc.exit_code == 2
    assert "--from-preregistration is required" in no_doc.output

    limits = _invoke(
        "execution", "limits", "set", "--from-preregistration", PREREGISTRATION, "--yes"
    )
    assert "is active, from PREREGISTRATION_execution_limits_v1" in limits.output
    assert "max_orders_per_day = 10" in limits.output

    shown = _invoke("execution", "limits", "show")
    assert "pre-registration: PREREGISTRATION_execution_limits_v1" in shown.output

    # A second row is refused rather than quietly written.
    again = runner.invoke(
        app, ["execution", "limits", "set", "--from-preregistration", PREREGISTRATION, "--yes"]
    )
    assert again.exit_code == 1
    assert "--supersede" in again.output

    session.commit()  # end this session's read transaction, so the CLI's writes are visible
    _seed_evidence_under_the_active_row(session, session.get(StrategyVersion, version_id))

    # ---- step 3: arm ----------------------------------------------------
    phrase = arming.confirmation_phrase(version_id, "paper_reference")
    armed = _invoke(
        "execution",
        "arm",
        str(version_id),
        "--account-id",
        ACCOUNT_ID,
        "--preregistration",
        PREREGISTRATION,
        "--yes",
        "--confirm",
        phrase,
    )
    # Every precondition PASSED, including the one that could never pass before.
    assert "[PASS] S8" in armed.output, armed.output
    assert f"account {ACCOUNT_ID}" in armed.output
    assert "[PASS] S9" in armed.output
    assert f"ARMED strategy_version_id={version_id}" in armed.output

    session.commit()  # end this session's read transaction, so the CLI's writes are visible
    live = arming.live_armings(session)
    assert len(live) == 1
    armed_id = live[0].id
    assert live[0].broker_account_id_expected == ACCOUNT_ID
    assert live[0].adapter_name == "paper_reference"
    assert live[0].preregistration_doc_id == PREREGISTRATION
    assert live[0].expires_at <= live[0].armed_at + timedelta(days=7)

    status = _invoke("execution", "status")
    assert "ARMED" in status.output
    assert "execution.enabled = True" in status.output

    # ---- step 4: a status change takes the authority away ----------------
    version = session.get(StrategyVersion, version_id)
    assert version is not None
    version.status = StrategyStatus.EXPERIMENTAL
    session.commit()

    _invoke("execution", "cycle")

    session.commit()  # end this session's read transaction, so the CLI's writes are visible
    assert arming.live_armings(session) == []
    row = session.get(ArmedStrategy, armed_id, populate_existing=True)
    assert row is not None
    assert row.disarmed_at is not None
    assert row.disarm_reason.startswith(arming.DisarmTrigger.STATUS_CHANGE.value)
    # The row itself survives: §13 rule 4b reads it to learn which account this
    # adapter was pointed at, disarmed or not.
    assert row.broker_account_id_expected == ACCOUNT_ID


def test_disable_turns_the_flag_off_and_ends_every_live_arming(
    session: Session, rehearsal_version: StrategyVersion
) -> None:
    """Disabling has to disarm: with the flag off the cycle is not registered,
    so nothing would run the per-cycle sweep and a live row would come back the
    moment the flag went on again."""
    version_id = rehearsal_version.id
    session.commit()

    _invoke("execution", "enable", "--yes")
    _invoke("execution", "limits", "set", "--from-preregistration", PREREGISTRATION, "--yes")
    session.commit()  # end this session's read transaction, so the CLI's writes are visible
    _seed_evidence_under_the_active_row(session, session.get(StrategyVersion, version_id))
    _invoke(
        "execution",
        "arm",
        str(version_id),
        "--account-id",
        ACCOUNT_ID,
        "--preregistration",
        PREREGISTRATION,
        "--yes",
        "--confirm",
        arming.confirmation_phrase(version_id, "paper_reference"),
    )
    session.commit()  # end this session's read transaction, so the CLI's writes are visible
    assert len(arming.live_armings(session)) == 1

    refused = runner.invoke(app, ["execution", "disable"])
    assert refused.exit_code == 2
    assert "--yes is required" in refused.output

    disabled = _invoke("execution", "disable", "--yes")
    assert "live: execution.enabled = False" in disabled.output
    assert "DISARMED armed_strategy" in disabled.output
    assert "NOT auto-liquidated" in disabled.output

    session.commit()  # end this session's read transaction, so the CLI's writes are visible
    assert arming.live_armings(session) == []

    actions = [
        row.action
        for row in session.scalars(select(AuditLog).order_by(AuditLog.id))
        if row.action.startswith("execution.")
    ]
    assert "execution.enabled" in actions
    assert "execution.limits_set" in actions
    assert "execution.disabled" in actions
    assert all(
        row.actor == "local-user"
        for row in session.scalars(select(AuditLog))
        if row.action.startswith("execution.")
    )


# ---------------------------------------------------------------------------
# W4b — the armed day, carried through to a fill and a clean book.
#
# READ THIS BEFORE EXTENDING IT. `run_execution_cycle` does not submit anything,
# and nothing in `src/signalforge/` calls `adapter.place()` or `place_combo()` at
# all: the cycle's open lane is not built. The cycle evaluates, reconciles,
# sweeps and reports `may_open_possible`; turning that into an order is a
# separate increment with its own drills.
#
# So the fill below is placed the way the drills place one — through the OMS's
# own durable path, `record_submitting` (written and COMMITTED first) then
# `adapter.place`, which is the §6/§8 order — and the REAL cycle then runs
# against the same adapter and has to come back CLEAN. That is what the W4b
# wiring can actually be held to: the cycle takes a proven `is_paper` proof every
# run, and it reconciles a HELD position CLEAN through the OMS-side attribution
# rather than diverging on it.
# ---------------------------------------------------------------------------


def _rehearsal_broker(session: Session, *, quote_at: object) -> object:
    """A `paper_reference` broker with a quote, so a marketable order can fill.

    The ceremony's own adapter is built with an EMPTY information set on purpose
    (it submits nothing), so a fill needs one that can price. Its book is held in
    MEMORY, which is why the cycle below is handed this instance rather than
    building its own: a `paper_reference` built fresh next cycle starts flat and
    would reconcile CLEAN for the wrong reason — because it holds nothing, not
    because the OMS explained what it holds.
    """
    from signalforge.execution.brokers.paper_reference import (
        ExecutionEventAudit,
        MarketClock,
        PaperReferenceBroker,
        PreSubmissionInformation,
        ReferenceQuote,
        SimulatedAccount,
    )

    return PaperReferenceBroker(
        audit=ExecutionEventAudit(session),
        account=SimulatedAccount(account_id=ACCOUNT_ID, initial_cash=25_000.0),
        expected_account_id=ACCOUNT_ID,
        information=PreSubmissionInformation.of(
            [ReferenceQuote("SPY", 470.0, quote_at, available_qty=None)]
        ),
        clock=MarketClock(is_open=True, as_of=quote_at + timedelta(minutes=1)),
    )


def test_the_armed_cycle_takes_a_proof_and_reconciles_a_held_position_clean(
    session: Session, rehearsal_version: StrategyVersion
) -> None:
    from signalforge.db.types import utcnow
    from signalforge.execution import deadman
    from signalforge.execution.cycle import run_execution_cycle
    from signalforge.execution.events import ExecutionEventType
    from signalforge.execution.intents import (
        CostModelFeedback,
        IntentKind,
        OrderIntent,
        OrderSide,
    )
    from signalforge.execution.oms import read_cycle_posture, record_submitting
    from signalforge.execution.states import OrderState

    version_id = rehearsal_version.id
    session.commit()

    _invoke("execution", "enable", "--yes")
    _invoke("execution", "limits", "set", "--from-preregistration", PREREGISTRATION, "--yes")
    session.commit()
    _seed_evidence_under_the_active_row(session, session.get(StrategyVersion, version_id))
    _invoke(
        "execution",
        "arm",
        str(version_id),
        "--account-id",
        ACCOUNT_ID,
        "--preregistration",
        PREREGISTRATION,
        "--yes",
        "--confirm",
        arming.confirmation_phrase(version_id, "paper_reference"),
    )
    session.commit()
    armed = arming.live_armings(session)
    assert len(armed) == 1

    now = utcnow()
    broker = _rehearsal_broker(session, quote_at=now - timedelta(minutes=5))

    # ---- one SIMULATED fill, through the OMS's durable path --------------
    intent = OrderIntent(
        client_order_id="rehearsal-open-1",
        intent_kind=IntentKind.OPEN,
        side=OrderSide.BUY_TO_OPEN,
        qty=1,
        limit_price=475.0,
        shares_per_contract=1,
        adapter_name="paper_reference",
        created_at=now,
        expires_at=now + timedelta(minutes=15),
        cost_model=CostModelFeedback(modelled_fill_price=470.0, modelled_spread_bps=5.0),
        symbol="SPY",
        strategy_version_id=version_id,
        armed_strategy_id=armed[0].id,
        state=OrderState.VALIDATED,
    )
    result = broker.place(record_submitting(session, intent, actor="test"))
    assert result.state is OrderState.FILLED, result.raw_status_verbatim
    assert list(broker.positions()), "the simulator is holding a position"

    # ---- the REAL cycle, against that book -------------------------------
    deadman.feed(session, now=now, detail="rehearsal: previous cycle")
    report = run_execution_cycle(
        session, read_cycle_posture(), now=now, adapter=broker, actor="test"
    )

    # §13: the proof is re-taken THIS cycle and it proves out.
    proofs = [
        e
        for e in session.scalars(
            select(ExecutionEvent).where(
                ExecutionEvent.event_type == ExecutionEventType.IS_PAPER_PROOF.value
            )
        )
        if e.reason.startswith("is_paper PROVEN") or e.reason.startswith("is_paper FAILED")
    ]
    assert proofs and proofs[-1].payload_json["proven"] is True, [p.reason for p in proofs]
    assert proofs[-1].payload_json["expected_account_id"] == ACCOUNT_ID

    # §10: a HELD position reconciles CLEAN, because the OMS explained it. This
    # is the check the W4a attribution gap made impossible — before it, any
    # adapter reconciled CLEAN only while flat.
    assert report.reconciliation_status == "CLEAN", report.blocked_reasons
    assert "R1: no adapter is configured" not in report.blocked_reasons
    assert report.disarms == (), report.disarms
    assert len(arming.live_armings(session)) == 1


def test_a_foreign_position_ends_the_same_rehearsal_in_a_halt(
    session: Session, rehearsal_version: StrategyVersion
) -> None:
    """The other half of the same promise: the cycle reconciles a held position
    CLEAN because it can EXPLAIN it, not because it stopped checking."""
    from signalforge.db.types import utcnow
    from signalforge.execution import deadman
    from signalforge.execution.cycle import run_execution_cycle
    from signalforge.execution.intents import (
        CostModelFeedback,
        IntentKind,
        OrderIntent,
        OrderSide,
    )
    from signalforge.execution.oms import read_cycle_posture
    from signalforge.execution.states import OrderState

    version_id = rehearsal_version.id
    session.commit()
    _invoke("execution", "enable", "--yes")
    _invoke("execution", "limits", "set", "--from-preregistration", PREREGISTRATION, "--yes")
    session.commit()
    _seed_evidence_under_the_active_row(session, session.get(StrategyVersion, version_id))
    _invoke(
        "execution",
        "arm",
        str(version_id),
        "--account-id",
        ACCOUNT_ID,
        "--preregistration",
        PREREGISTRATION,
        "--yes",
        "--confirm",
        arming.confirmation_phrase(version_id, "paper_reference"),
    )
    session.commit()

    now = utcnow()
    broker = _rehearsal_broker(session, quote_at=now - timedelta(minutes=5))
    # Straight at the broker: no OMS pre-submission record, so nothing local can
    # explain the position it creates.
    broker.place(
        OrderIntent(
            client_order_id="rehearsal-foreign",
            intent_kind=IntentKind.OPEN,
            side=OrderSide.BUY_TO_OPEN,
            qty=1,
            limit_price=475.0,
            shares_per_contract=1,
            adapter_name="paper_reference",
            created_at=now,
            expires_at=now + timedelta(minutes=15),
            cost_model=CostModelFeedback(modelled_fill_price=470.0, modelled_spread_bps=5.0),
            symbol="SPY",
            state=OrderState.SUBMITTING,
        )
    )

    deadman.feed(session, now=now, detail="rehearsal: previous cycle")
    report = run_execution_cycle(
        session, read_cycle_posture(), now=now, adapter=broker, actor="test"
    )

    assert report.reconciliation_status == "DIVERGED"
    assert report.may_open_possible is False
    assert any(
        d.endswith(arming.DisarmTrigger.RECONCILIATION.value) for d in report.disarms
    ), report.disarms
    assert arming.live_armings(session) == []
