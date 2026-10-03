"""D6 §2 / §13 — how the adapter reaches the cycle, and the refusals it adds.

An adapter's audit sink writes ``execution_event`` rows through a session, and
the cycle opens its own session inside the job body. Until W4b the CLI therefore
had nowhere to build one: ``execution_job_specs(adapter=...)`` wanted an instance
at *registration* time, before any session existed, so the worker always ran the
cycle adapter-free and every adapter-dependent check reported "could not be
evaluated". ``adapter_factory`` is called with the cycle's own session instead.

Three properties are asserted here and nowhere else:

* with a factory, ``is_paper()`` is re-taken and PROVEN **every cycle** — §13's
  rule is "never cached from arm time", so the proof has to be a per-cycle event;
* with **no** factory, nothing about the cycle changes — the fail-closed
  adapter-free path is the shipped one and must stay byte-identical;
* two live armings naming two different broker accounts BLOCK opening for both.
  One adapter answers for one account, so a proof taken against one of them
  proves nothing about the other, and "the other one's proof passed" is not a
  proof about this one.
"""

from __future__ import annotations

import inspect
from datetime import datetime, timedelta

import pytest
from freezegun import freeze_time
from sqlalchemy import select
from sqlalchemy.orm import Session

from signalforge.db.models import ArmedStrategy, ExecutionEvent, JobRun
from signalforge.execution import arming
from signalforge.execution import cycle as cycle_mod
from signalforge.execution.brokers.paper_reference import (
    SIMULATED_ACCOUNT_PREFIX,
    ExecutionEventAudit,
    MarketClock,
    PaperReferenceBroker,
    PaperReferenceOrderStore,
    PreSubmissionInformation,
    SimulatedAccount,
)
from signalforge.execution.events import ExecutionEventType
from signalforge.execution.oms import CycleBranch, CyclePosture
from tests.execution.conftest import ADAPTER, NOW

ACCOUNT_ID = f"{SIMULATED_ACCOUNT_PREFIX}CYCLE-1"
OTHER_ACCOUNT_ID = f"{SIMULATED_ACCOUNT_PREFIX}CYCLE-2"


def _posture(branch: CycleBranch = CycleBranch.FULL) -> CyclePosture:
    from signalforge.execution.oms import ExecutionKillState

    return CyclePosture(
        branch=branch,
        may_open=branch is CycleBranch.FULL,
        may_close=True,
        kill_switch_engaged=False,
        execution_kill=ExecutionKillState(engaged=False, readable=True),
        detail="test posture",
    )


def _broker(session: Session, *, account_id: str = ACCOUNT_ID) -> PaperReferenceBroker:
    return PaperReferenceBroker(
        audit=ExecutionEventAudit(session),
        account=SimulatedAccount(account_id=account_id, initial_cash=25_000.0),
        expected_account_id=account_id,
        information=PreSubmissionInformation.of([]),
        clock=MarketClock(is_open=True, as_of=NOW),
        book=PaperReferenceOrderStore(session),
    )


def _armed(
    session: Session, strategy_version_id: int, *, account_id: str, at: datetime = NOW
) -> ArmedStrategy:
    """An armed row written directly — the ceremony has its own tests.

    ``at`` anchors the arming window. Tests that drive ``execution_cycle_job``
    run on the REAL clock (the job takes no ``now``), so they must arm relative
    to the wall clock: an arming pinned to the fixed ``NOW`` expires for real
    six days later and the cycle then — correctly — disarms it."""
    from signalforge.research.approval_scope import current_spec_json_hash
    from signalforge.settings_store import effective_research_config

    row = ArmedStrategy(
        strategy_version_id=strategy_version_id,
        structure_type="equity",
        armed_at=at - timedelta(days=1),
        armed_by="test",
        expires_at=at + timedelta(days=6),
        adapter_name=ADAPTER,
        broker_account_id_expected=account_id,
        max_notional_usd=1_000.0,
        max_orders_per_day=10,
        evidence_paper_trade_count=20,
        evidence_expectancy_r=0.5,
        sealed_look_prior_at_arm=1,
        preregistration_doc_id="PREREGISTRATION_execution_limits_v1",
        spec_json_hash=current_spec_json_hash(session, strategy_version_id) or "",
        config_hash=effective_research_config(session).config_hash,
    )
    session.add(row)
    session.flush()
    return row


def _approve(session: Session, strategy_version_id: int) -> None:
    """A passing sealed test + a passing evaluation whose scope hashes equal the
    LIVE ones. Without it the very first auto-disarm sweep fires on
    ``approved_scope_mismatch`` and every assertion below would pass or fail for
    the wrong reason."""
    from datetime import date

    from signalforge.db.models import (
        DataSnapshot,
        StrategyPromotionEvaluation,
        StrategySealedTest,
    )
    from signalforge.research.approval_scope import current_spec_json_hash
    from signalforge.settings_store import effective_research_config

    snapshot = DataSnapshot(key=f"cycle_snapshot_{strategy_version_id}", symbols_json=["SPY"])
    session.add(snapshot)
    session.flush()
    sealed = StrategySealedTest(
        strategy_version_id=strategy_version_id,
        dataset_snapshot_id=snapshot.id,
        window_start=date(2024, 1, 2),
        window_end=date(2025, 1, 2),
        universe_json=["SPY"],
        passed=True,
        evaluated_at=NOW - timedelta(days=30),
    )
    session.add(sealed)
    session.flush()
    session.add(
        StrategyPromotionEvaluation(
            strategy_version_id=strategy_version_id,
            dataset_snapshot_id=snapshot.id,
            evaluated_at=NOW - timedelta(days=29),
            config_hash=effective_research_config(session).config_hash,
            spec_json_hash=current_spec_json_hash(session, strategy_version_id) or "",
            universe_json=["SPY"],
            window_start=date(2024, 1, 2),
            window_end=date(2025, 1, 2),
            data_provenance_json={"sources": ["massive"]},
            passed=True,
            verdict="PAPER_APPROVED",
            sealed_test_id=sealed.id,
        )
    )
    session.flush()


def _feed_dead_man(session: Session, *, at: object = None) -> None:
    """The first cycle on a fresh database always finds a LAPSED dead man — no
    heartbeat row has ever been written — and a lapse disarms everything. These
    tests are about a different refusal, so the previous beat is supplied."""
    from signalforge.db.types import utcnow
    from signalforge.execution import deadman

    deadman.feed(session, now=at or utcnow(), detail="test: previous cycle")
    session.flush()


def _cycle_proofs(session: Session) -> list[ExecutionEvent]:
    """Only the CYCLE's own §13 proof rows.

    The adapter records an ``IS_PAPER_PROOF`` of its own on every ``is_paper()``
    call; the cycle records the comparison against the ARMED account id. Both are
    wanted in the audit trail and only the second is what §13's per-cycle rule is
    about, so they are told apart by the field only the cycle writes.
    """
    return [
        e
        for e in _events(session, ExecutionEventType.IS_PAPER_PROOF)
        if e.reason.startswith(("is_paper PROVEN", "is_paper FAILED"))
    ]


def _events(session: Session, event_type: ExecutionEventType) -> list[ExecutionEvent]:
    return list(
        session.scalars(
            select(ExecutionEvent)
            .where(ExecutionEvent.event_type == event_type.value)
            .order_by(ExecutionEvent.id)
        )
    )


# ---------------------------------------------------------------------------
# The factory reaches the cycle, with the cycle's own session
# ---------------------------------------------------------------------------


def test_the_factory_is_called_with_the_cycles_own_session(db_url: str) -> None:
    seen: list[Session] = []

    def factory(session: Session) -> None:
        seen.append(session)
        return None

    cycle_mod.execution_cycle_job(adapter_factory=factory, actor="test")()

    assert len(seen) == 1, "the factory is called once per cycle, not once per registration"
    # It is a live, usable session — the whole reason a factory exists.
    assert seen[0].is_active


@freeze_time(NOW)
def test_the_cycle_proves_is_paper_every_cycle_through_the_factory(
    session: Session, strategy_version: object, limits_row: object
) -> None:
    """§13 — re-taken EVERY cycle, never cached from arm time. Two cycles, two
    proofs, each one an ``execution_event`` a reviewer can read."""
    from signalforge.db.types import utcnow

    _approve(session, strategy_version.id)
    _armed(session, strategy_version.id, account_id=ACCOUNT_ID, at=utcnow())
    _feed_dead_man(session)
    session.commit()

    for _ in range(2):
        cycle_mod.execution_cycle_job(
            adapter_factory=lambda s: _broker(s, account_id=ACCOUNT_ID), actor="test"
        )()

    session.commit()
    proofs = _cycle_proofs(session)
    assert len(proofs) == 2, [p.reason for p in proofs]
    for proof in proofs:
        assert proof.payload_json["proven"] is True, proof.reason
        assert proof.payload_json["observed_account_id"] == ACCOUNT_ID
        assert proof.payload_json["expected_account_id"] == ACCOUNT_ID
    # And the arming survived: a proven proof is not a disarm trigger.
    assert len(arming.live_armings(session)) == 1


def test_with_an_adapter_the_cycle_reconciles_instead_of_reporting_no_adapter(
    session: Session, strategy_version: object, limits_row: object
) -> None:
    _approve(session, strategy_version.id)
    _armed(session, strategy_version.id, account_id=ACCOUNT_ID)
    _feed_dead_man(session)
    session.commit()

    cycle_mod.execution_cycle_job(
        adapter_factory=lambda s: _broker(s, account_id=ACCOUNT_ID), actor="test"
    )()

    session.commit()
    run = session.scalars(select(JobRun).where(JobRun.name == "execution_cycle")).one()
    assert "reconciliation=CLEAN" in run.detail, run.detail
    assert "no adapter is configured" not in run.detail


# ---------------------------------------------------------------------------
# No factory: nothing changes
# ---------------------------------------------------------------------------


def test_no_factory_is_byte_identical_to_the_adapter_free_cycle(session: Session) -> None:
    """The shipped path. ``execution_cycle_job()`` with no adapter and no factory
    must produce exactly what ``run_execution_cycle(adapter=None)`` produces —
    the fail-closed answer, unchanged by the existence of factories."""
    reference = cycle_mod.run_execution_cycle(session, _posture(), adapter=None, actor="test")
    assert "R1: no adapter is configured, so nothing is reconciled" in reference.blocked_reasons
    expected = reference.note()
    session.rollback()

    cycle_mod.execution_cycle_job(actor="test")()

    session.commit()
    run = session.scalars(select(JobRun).where(JobRun.name == "execution_cycle")).one()
    assert run.detail == f"[full] {expected}"
    assert run.status == "ok"


def test_a_factory_returning_none_is_the_same_fail_closed_answer(session: Session) -> None:
    session.commit()
    cycle_mod.execution_cycle_job(adapter_factory=lambda s: None, actor="test")()

    session.commit()
    run = session.scalars(select(JobRun).where(JobRun.name == "execution_cycle")).one()
    assert "reconciliation=not evaluated" in run.detail
    assert run.status == "ok"


def test_an_explicit_adapter_still_wins_over_a_factory(session: Session) -> None:
    """A caller that owns its session — a test, a drill — has said so."""
    called: list[bool] = []

    def factory(_session: Session) -> None:
        called.append(True)
        return None

    session.commit()
    cycle_mod.execution_cycle_job(adapter=_broker(session), adapter_factory=factory, actor="test")()

    assert called == []


# ---------------------------------------------------------------------------
# A factory that fails does not take the cycle down
# ---------------------------------------------------------------------------


def test_a_raising_factory_still_leaves_a_fed_dead_man_and_a_recorded_reason(
    session: Session,
) -> None:
    """The cascade this prevents: a cycle that aborted here would stop feeding
    the dead man, the dead man would lapse ~90s later, and the lapse would disarm
    the whole book and run the drain sequence — over an unreachable broker."""
    from signalforge.db.types import utcnow
    from signalforge.execution import deadman

    def factory(_session: Session) -> None:
        raise ConnectionError("the broker is unreachable")

    session.commit()
    cycle_mod.execution_cycle_job(adapter_factory=factory, actor="test")()

    session.commit()
    run = session.scalars(select(JobRun).where(JobRun.name == "execution_cycle")).one()
    assert run.status == "ok", run.detail
    assert deadman.assess(session, now=utcnow(), stale_after_s=90).alive is True
    blocked = _events(session, ExecutionEventType.LIMIT_BLOCKED)
    assert any("could not be built this cycle" in e.reason for e in blocked), [
        e.reason for e in blocked
    ]
    assert any("ConnectionError" in e.reason for e in blocked)


# ---------------------------------------------------------------------------
# §10 rule 2 / §13 — one adapter answers for ONE account
# ---------------------------------------------------------------------------


def test_armings_disagreeing_on_the_account_block_opening_for_all_of_them(
    session: Session, strategy_version: object, limits_row: object
) -> None:
    from signalforge.db.models import Strategy, StrategyVersion
    from signalforge.domain import StrategyStatus

    second = StrategyVersion(
        strategy_id=strategy_version.strategy_id,
        version="0.2.0",
        git_sha="cafe",
        spec_json={},
        status=StrategyStatus.PAPER_APPROVED,
    )
    session.add(second)
    session.flush()
    _approve(session, strategy_version.id)
    _approve(session, second.id)
    _armed(session, strategy_version.id, account_id=ACCOUNT_ID)
    _armed(session, second.id, account_id=OTHER_ACCOUNT_ID)
    _feed_dead_man(session, at=NOW)
    assert session.get(Strategy, strategy_version.strategy_id) is not None

    report = cycle_mod.run_execution_cycle(
        session,
        _posture(),
        now=NOW,
        adapter=_broker(session, account_id=ACCOUNT_ID),
        actor="test",
    )

    assert report.may_open_possible is False
    assert any("§10 rule 2" in r for r in report.blocked_reasons), report.blocked_reasons
    blocked = _events(session, ExecutionEventType.LIMIT_BLOCKED)
    scoped = [e for e in blocked if "different broker accounts" in e.reason]
    assert scoped, [e.reason for e in blocked]
    assert sorted(scoped[0].payload_json["expected_account_ids"]) == sorted(
        [ACCOUNT_ID, OTHER_ACCOUNT_ID]
    )
    assert scoped[0].payload_json["armed_strategy_ids"] == [1, 2]

    # This check itself disarms nothing — the §12 step 7 triggers are the ADR's
    # list and "the operator armed two accounts" is not on it. The sweep then
    # disarms both anyway, under its OWN trigger, because the single expected id
    # §13 rule 4b resolves cannot match both accounts. Both facts are on the
    # record, and that is the whole reason this check runs BEFORE the sweep:
    # afterwards there would be nothing left to report it about, and the operator
    # would read only "the broker answered for the wrong account".
    assert all(
        d.endswith(arming.DisarmTrigger.IS_PAPER.value) for d in report.disarms
    ), report.disarms
    # The BODY, not the docstring — which names the rule on purpose.
    assert "disarm" not in inspect.getsource(cycle_mod._account_scope_ok).split('"""', 2)[-1]


def test_one_account_across_every_live_arming_does_not_block(
    session: Session, strategy_version: object, limits_row: object
) -> None:
    _approve(session, strategy_version.id)
    _armed(session, strategy_version.id, account_id=ACCOUNT_ID)
    _feed_dead_man(session, at=NOW)

    report = cycle_mod.run_execution_cycle(
        session,
        _posture(),
        now=NOW,
        adapter=_broker(session, account_id=ACCOUNT_ID),
        actor="test",
    )

    assert not any("different broker accounts" in r for r in report.blocked_reasons)


def test_a_proof_against_the_wrong_account_blocks_and_disarms(
    session: Session, strategy_version: object, limits_row: object
) -> None:
    """§13 — the single most likely way real money gets touched is a
    misconfigured account, so a proof that names a different account is a
    failure, not a warning."""
    _approve(session, strategy_version.id)
    _armed(session, strategy_version.id, account_id=ACCOUNT_ID)
    _feed_dead_man(session, at=NOW)

    report = cycle_mod.run_execution_cycle(
        session,
        _posture(),
        now=NOW,
        # The broker answers for an account nobody armed.
        adapter=_broker(session, account_id=OTHER_ACCOUNT_ID),
        actor="test",
    )

    assert report.may_open_possible is False
    assert any(
        "is_paper() did not prove out" in r for r in report.blocked_reasons
    ), report.blocked_reasons
    assert any(
        d.endswith(arming.DisarmTrigger.IS_PAPER.value) for d in report.disarms
    ), report.disarms
    proofs = _cycle_proofs(session)
    assert proofs and proofs[-1].payload_json["proven"] is False


@pytest.mark.parametrize("branch", [CycleBranch.FULL, CycleBranch.PROTECTIVE])
def test_the_close_lane_is_never_what_these_refusals_touch(
    session: Session, strategy_version: object, limits_row: object, branch: CycleBranch
) -> None:
    """Both refusals block OPENING. ``build_close_intent`` requires no armed row
    at all, so neither of them can reach the protective close lane."""
    source = inspect.getsource(cycle_mod._account_scope_ok)
    assert "close" not in source.replace("close lane", "").replace("closed", "")
    _approve(session, strategy_version.id)
    _armed(session, strategy_version.id, account_id=ACCOUNT_ID)
    _feed_dead_man(session, at=NOW)

    report = cycle_mod.run_execution_cycle(
        session,
        _posture(branch),
        now=NOW,
        adapter=_broker(session, account_id=OTHER_ACCOUNT_ID),
        actor="test",
    )

    assert report.may_open_possible is False
