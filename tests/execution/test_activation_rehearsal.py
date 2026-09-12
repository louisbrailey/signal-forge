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
from signalforge.db.models import ArmedStrategy, AuditLog, ExecutionLimits, StrategyVersion
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
