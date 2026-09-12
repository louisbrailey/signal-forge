"""The ``signalforge execution`` command group (D6 §12 step 5).

``signalforge.cli`` is the one sanctioned inbound edge into the execution layer,
so the ceremony's refusals have to hold at the CLI surface too — not only in
``execution.arming``, which the CLI could in principle call wrongly.

The three properties asserted here that live nowhere else:

* ``arm`` prints the FULL preconditions table before it decides anything, so an
  operator sees every failure at once rather than fixing one per attempt;
* a **typed** confirmation is required — ``--yes`` alone is not a confirmation,
  and the phrase names the version and the adapter so one cannot be pasted into
  another;
* with no adapter in the tree there is no ``is_paper`` proof, so arming refuses.
  That is the current, correct posture: nothing can be armed until I-E3 lands.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session
from typer.testing import CliRunner

from signalforge.cli import app
from signalforge.execution import arming

runner = CliRunner()


@pytest.fixture(autouse=True)
def _db(db_url: str) -> str:
    """Every command below opens its own session_scope against this database."""
    return db_url


def test_status_reports_the_default_posture(session: Session) -> None:
    session.commit()
    result = runner.invoke(app, ["execution", "status"])

    assert result.exit_code == 0, result.output
    assert "EXECUTION_DISABLED_BY_DEFAULT = True" in result.output
    assert "execution.enabled = False" in result.output
    assert "armed strategies: NONE" in result.output
    assert "correct state" in result.output
    # The one promise, printed where the operator will look during an incident.
    assert "closing is never blocked" in result.output


def test_status_says_a_missing_limits_row_blocks(session: Session) -> None:
    session.commit()
    result = runner.invoke(app, ["execution", "status"])

    assert "'No limits row' is not 'no limits'" in result.output


def test_arm_prints_the_whole_preconditions_table_and_refuses(
    session: Session, armable: object
) -> None:
    """With no adapter there is no is_paper proof and no flat-account check, so
    the ceremony refuses — and the operator can still see every other row."""
    session.commit()
    result = runner.invoke(
        app,
        [
            "execution",
            "arm",
            "1",
            "--account-id",
            "PAPER-ACCOUNT-1",
            "--preregistration",
            "PREREGISTRATION_2026-09-11_snapshot11",
            "--yes",
        ],
    )

    assert result.exit_code == 1
    assert "ARMING PRECONDITIONS" in result.output
    # Every check is printed, not only the first failure.
    for name in ("S1", "S2", "S3", "S4", "S7", "S8", "S9"):
        assert f"] {name}:" in result.output
    assert "REFUSED" in result.output
    assert "[FAIL] S8" in result.output
    assert "YOU ARE ACKNOWLEDGING" in result.output
    assert "CANCELS NOTHING AT THE BROKER" in result.output


def test_arm_without_yes_is_refused(session: Session, armable: object) -> None:
    session.commit()
    result = runner.invoke(
        app,
        [
            "execution",
            "arm",
            "1",
            "--account-id",
            "PAPER-ACCOUNT-1",
            "--preregistration",
            "PREREGISTRATION_2026-09-11_snapshot11",
        ],
    )

    assert result.exit_code == 1
    assert "[FAIL] S6" in result.output


def test_disarm_of_something_not_armed_is_an_error(session: Session) -> None:
    session.commit()
    result = runner.invoke(app, ["execution", "disarm", "1", "--reason", "drill"])

    assert result.exit_code == 1
    assert "no live arming" in result.output


def test_disarm_ends_the_authority_and_says_what_it_did_not_do(
    session: Session, armable: object, limits_row: object
) -> None:
    from signalforge.execution.cycle import active_limits_created_at
    from signalforge.execution.limits import load_active_limits
    from tests.execution.conftest import NOW, arming_request, paper_proof

    limits = load_active_limits(session)
    row = arming.arm(
        session,
        arming_request(strategy_version_id=1),
        now=NOW,
        is_paper_proof=paper_proof(),
        account_is_flat=True,
        actor="test",
        limits_id=limits.id if limits else None,
        limits_created_at=active_limits_created_at(session),
    )
    session.commit()

    result = runner.invoke(app, ["execution", "disarm", "1", "--reason", "drill"])

    assert result.exit_code == 0, result.output
    assert f"DISARMED armed_strategy id={row.id}" in result.output
    # The sentence an operator needs to read at exactly this moment.
    assert "NOT auto-liquidated" in result.output


def test_the_execution_kill_state_round_trips_through_the_cli(session: Session) -> None:
    from signalforge.execution.oms import read_execution_kill_state

    session.commit()
    engaged = runner.invoke(app, ["execution", "kill", "--engage", "--reason", "drill"])
    assert engaged.exit_code == 0
    assert read_execution_kill_state().engaged is True

    released = runner.invoke(app, ["execution", "kill", "--release", "--reason", "over"])
    assert released.exit_code == 0
    assert read_execution_kill_state().engaged is False


def test_feeding_the_dead_man_by_hand_grants_no_authority(session: Session) -> None:
    from signalforge.db.types import utcnow
    from signalforge.execution import deadman

    session.commit()
    result = runner.invoke(app, ["execution", "feed-dead-man"])

    assert result.exit_code == 0
    session.expire_all()
    assert deadman.assess(session, now=utcnow(), stale_after_s=90).alive is True
    # Fed, and still nothing is armed: a live heartbeat is not an authority.
    assert arming.live_armings(session) == []


def test_the_manual_cycle_runs_while_the_layer_is_disabled(session: Session) -> None:
    """Runnable by hand with the flag off, which is the point: the operator can
    prove what it would do without enabling anything."""
    from sqlalchemy import select

    from signalforge.db.models import JobRun

    session.commit()
    result = runner.invoke(app, ["execution", "cycle"])

    assert result.exit_code == 0, result.output
    session.expire_all()
    runs = list(session.scalars(select(JobRun).where(JobRun.name == "execution_cycle")))
    assert len(runs) == 1
    assert runs[0].status == "ok"
    assert "[full]" in runs[0].detail


def test_run_job_routes_the_execution_cycle_to_its_own_wrapper(session: Session) -> None:
    from sqlalchemy import select

    from signalforge.db.models import JobRun

    session.commit()
    result = runner.invoke(app, ["run-job", "execution_cycle"])

    assert result.exit_code == 0, result.output
    assert "self-guarded" in result.output
    session.expire_all()
    assert list(session.scalars(select(JobRun).where(JobRun.name == "execution_cycle")))


def test_the_command_group_help_makes_no_unconditional_promise() -> None:
    """§18 / T9: the help string must not assert that no order is ever placed —
    it must state the SCOPE instead.

    Read off the Typer object rather than the rendered ``--help`` output, which
    rich re-wraps at the terminal width; T9's scanner reads the same source
    string this does.
    """
    from signalforge.cli import execution_app
    from tests.safety.test_s15_execution_boundary import find_unconditional_no_order_claims

    help_text = execution_app.info.help or ""
    assert find_unconditional_no_order_claims(help_text) == []
    assert "DISABLED by\ndefault" in help_text.replace(" ", "\n") or "DISABLED" in help_text
    assert "never blocks closing" in help_text
    assert "Nothing is armed" in help_text or "nothing is armed" in help_text


def test_the_execution_help_still_renders(session: Session) -> None:
    session.commit()
    result = runner.invoke(app, ["execution", "--help"])
    assert result.exit_code == 0
    for name in ("arm", "disarm", "status", "cycle"):
        assert name in result.output
