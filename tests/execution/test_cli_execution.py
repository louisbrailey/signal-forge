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
* with the layer DISABLED no adapter is built, so there is no ``is_paper`` proof
  and arming refuses on S8 — the shipped posture, and the correct one.

The W4a block at the bottom covers the three blockers that made the documented
ceremony unrunnable (no way to enable the layer, no way to create the limits row,
and a registry lookup that never resolved), plus the refusals each fix has to keep.
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
    """With the layer disabled no adapter is built, so there is no is_paper proof
    and no flat-account check, and the ceremony refuses — while the operator can
    still see every other row."""
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


# ---------------------------------------------------------------------------
# W4a — the three blockers that made the documented ceremony unrunnable.
# ---------------------------------------------------------------------------


def test_the_cli_builds_a_paper_reference_adapter_and_proves_is_paper(session: Session) -> None:
    """B3. ``_execution_adapter`` used to look up ``brokers.resolve_adapter``,
    which has never existed, and swallowed the ``AttributeError`` — so no adapter
    was ever built and `execution arm` failed S8 every run. It now calls the real
    registry, and the proof it takes is read out of the broker's OWN response.
    """
    from signalforge.cli import _execution_adapter
    from signalforge.execution.brokers.paper_reference import SIMULATED_ACCOUNT_PREFIX
    from signalforge.settings_store import RESEARCH_OVERRIDES_KEY, set_setting

    account_id = f"{SIMULATED_ACCOUNT_PREFIX}CLI-1"

    # Disabled — the shipped default — builds nothing. Not a degraded mode.
    assert _execution_adapter(session, expected_account_id=account_id) is None

    set_setting(session, RESEARCH_OVERRIDES_KEY, {"execution": {"enabled": True}})
    session.flush()

    adapter = _execution_adapter(session, expected_account_id=account_id)
    assert adapter is not None
    assert adapter.name == "paper_reference"

    proof = adapter.is_paper()
    assert proof.proven, proof.failure_reason
    assert proof.observed_account_id == account_id
    assert proof.expected_account_id == account_id


def test_the_adapter_refuses_an_account_id_that_is_not_the_simulators(session: Session) -> None:
    """A real-looking broker account id cannot be typed at this adapter by
    accident: the simulated account refuses it, and no adapter is built."""
    from signalforge.cli import _execution_adapter
    from signalforge.settings_store import RESEARCH_OVERRIDES_KEY, set_setting

    set_setting(session, RESEARCH_OVERRIDES_KEY, {"execution": {"enabled": True}})
    session.flush()

    assert _execution_adapter(session, expected_account_id="PA3XYZREAL") is None


def test_no_session_means_no_adapter_and_no_swallowed_attribute_error() -> None:
    """The cycle paths build their session inside the job body, so there is none
    to bind an audit sink to. That returns ``None`` — which BLOCKS opening —
    rather than raising, and nothing is caught blindly on the way."""
    import inspect

    from signalforge.cli import _execution_adapter

    assert _execution_adapter() is None
    # The BODY, not the docstring — which names the old bug on purpose.
    body = inspect.getsource(_execution_adapter).split('"""', 2)[-1]
    assert "AttributeError" not in body
    assert "except Exception" not in body
    assert "resolve_adapter" not in body


def test_enable_writes_the_research_override_and_an_audit_row(session: Session) -> None:
    """B1. The same mechanism every other research override uses, so `execution
    status` and the scheduler read it through ``effective_research_config``."""
    from sqlalchemy import select

    from signalforge.db.models import AuditLog
    from signalforge.settings_store import RESEARCH_OVERRIDES_KEY, get_setting

    session.commit()
    result = runner.invoke(app, ["execution", "enable", "--yes"])

    assert result.exit_code == 0, result.output
    session.commit()
    assert get_setting(session, RESEARCH_OVERRIDES_KEY)["execution"]["enabled"] is True
    row = session.scalars(select(AuditLog).where(AuditLog.action == "execution.enabled")).one()
    assert row.actor == "local-user"
    assert row.after_json == {"enabled": True}

    # And `execution status` — a different code path — now reports it live.
    status = runner.invoke(app, ["execution", "status"])
    assert "execution.enabled = True" in status.output


def test_enabling_does_not_move_the_approval_scope_config_hash(session: Session) -> None:
    """The 2026-09-11 incident, in the one place it would matter most: the
    execution section is excluded from ``SCOPE_HASH_FIELDS``, so turning the
    layer on must not put every live PAPER_APPROVED approval out of scope."""
    from signalforge.settings_store import effective_research_config

    before = effective_research_config(session).config_hash
    session.commit()

    assert runner.invoke(app, ["execution", "enable", "--yes"]).exit_code == 0

    session.commit()
    after = effective_research_config(session)
    assert after.execution.enabled is True
    assert after.config_hash == before


def test_enable_does_not_disturb_other_research_overrides(session: Session) -> None:
    """Deep-merged, not replaced: the flag must not silently drop the operator's
    watchlist or risk settings."""
    from signalforge.settings_store import RESEARCH_OVERRIDES_KEY, get_setting, set_setting

    set_setting(
        session,
        RESEARCH_OVERRIDES_KEY,
        {"watchlist": ["SPY"], "allow_short_candidates": True},
    )
    session.commit()

    assert runner.invoke(app, ["execution", "enable", "--yes"]).exit_code == 0

    session.commit()
    overrides = get_setting(session, RESEARCH_OVERRIDES_KEY)
    assert overrides["watchlist"] == ["SPY"]
    assert overrides["allow_short_candidates"] is True
    assert overrides["execution"]["enabled"] is True


def test_enable_and_disable_both_refuse_without_yes(session: Session) -> None:
    from signalforge.settings_store import RESEARCH_OVERRIDES_KEY, get_setting

    session.commit()
    for command in ("enable", "disable"):
        result = runner.invoke(app, ["execution", command])
        assert result.exit_code == 2, result.output
        assert "--yes is required" in result.output
    session.commit()
    assert get_setting(session, RESEARCH_OVERRIDES_KEY, {}) in ({}, None)


def test_the_enable_and_disable_commands_are_not_on_the_settings_form() -> None:
    """D6 §12 / S15b: enabling and arming stay on the human-typed CLI. The web
    form must gain no execution field and no import edge into the package."""
    import inspect

    from signalforge.app.routers import dashboard

    source = inspect.getsource(dashboard)
    assert "signalforge.execution" not in source
    assert "execution" not in inspect.signature(dashboard.act_settings).parameters


def test_limits_show_says_a_missing_row_blocks(session: Session) -> None:
    session.commit()
    result = runner.invoke(app, ["execution", "limits", "show"])

    assert result.exit_code == 1
    assert "NO active row" in result.output
    assert "'no limits row' is not 'no limits'" in result.output


def test_limits_set_refuses_a_document_that_does_not_exist(session: Session) -> None:
    """B2 / §7b rule 1 — the document is a hard precondition, not a label."""
    session.commit()
    result = runner.invoke(
        app,
        [
            "execution",
            "limits",
            "set",
            "--from-preregistration",
            "PREREGISTRATION_execution_limits_v9",
            "--yes",
        ],
    )

    assert result.exit_code == 1
    assert "REFUSED" in result.output
    assert "no pre-registered execution_limits row is registered" in result.output


def test_limits_set_writes_exactly_the_pre_registered_values(session: Session) -> None:
    from sqlalchemy import select

    from signalforge.db.models import AuditLog, ExecutionLimits
    from tests.execution.conftest import LIMIT_GRID_CENTRES

    session.commit()
    result = runner.invoke(
        app,
        [
            "execution",
            "limits",
            "set",
            "--from-preregistration",
            "PREREGISTRATION_execution_limits_v1",
            "--yes",
        ],
    )

    assert result.exit_code == 0, result.output
    session.commit()
    row = session.scalars(select(ExecutionLimits)).one()
    for column, expected in LIMIT_GRID_CENTRES.items():
        assert getattr(row, column) == expected, column
    assert row.created_by == "local-user"
    audit = session.scalars(select(AuditLog).where(AuditLog.action == "execution.limits_set")).one()
    assert audit.after_json["execution_limits_id"] == row.id


def test_superseding_says_what_it_costs(session: Session) -> None:
    session.commit()
    argv = [
        "execution",
        "limits",
        "set",
        "--from-preregistration",
        "PREREGISTRATION_execution_limits_v1",
        "--yes",
    ]
    assert runner.invoke(app, argv).exit_code == 0

    result = runner.invoke(app, [*argv, "--supersede"])

    assert result.exit_code == 0, result.output
    assert "superseded execution_limits id=1" in result.output
    assert "RESETS the decision-10 evidence counter" in result.output
