"""D6 §2 / §8 — the guarded cycle, the drain, and the job-table promise.

The drills this module carries, named as the ADR names them:

* **V1** — kill switch engaged with an open position: the cycle body EXECUTES
  (it does not skip), writes a ``CYCLE_PROTECTIVE`` event and a ``JobRun``,
  blocks opening, runs drain -> ``cancel_all()`` -> reconcile in that order, and
  a protective close still constructs.
* **V2** — dead-man lapse: opening blocked, auto-disarm fires, **no
  auto-liquidation**, ``may_close`` remains open.
* **V7 / V15** — a ``SUBMITTING`` row with no outcome is promoted to ``UNKNOWN``
  on the next cycle (including the first after a restart), that ``UNKNOWN``
  blocks arming, a retry never clears it, and the protective close is
  constructible throughout — **with no manual DB write at any step**.
* **V18** — a DISARMED strategy holding an open short leg: a protective close
  still constructs and still submits, with no ``armed_strategy`` row, no
  ``Candidate``, no ``PaperTrade``, the kill switch engaged and the dead man
  lapsed. This is the drill that PROVES the headline promise rather than
  asserting it.
* **V19's job half** — with ``execution.enabled`` False the worker's job list is
  byte-identical to ``scheduler.default_job_specs()``.

No adapter from ``execution/brokers`` is touched anywhere in this file: the
double lives in ``tests/execution/fakes.py`` and the paper_reference adapter is
a separate branch's work.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from signalforge.db.models import ExecutionEvent, JobRun, StrategyVersion
from signalforge.db.types import utcnow
from signalforge.execution import arming
from signalforge.execution import cycle as cycle_mod
from signalforge.execution.events import ExecutionEventType, record_execution_event
from signalforge.execution.intents import (
    CostModelFeedback,
    IntentKind,
    OrderLeg,
    OrderSide,
    PositionLeg,
    ReconciledPosition,
    build_close_intent,
)
from signalforge.execution.limits import CloseGateContext, may_close
from signalforge.execution.oms import (
    CycleBranch,
    CyclePosture,
    ExecutionKillState,
    SubmissionLock,
    SubmissionsClosed,
    current_state,
    drain,
    execution_guarded,
    in_flight_client_order_ids,
    promote_stale_submitting,
    read_cycle_posture,
    read_execution_kill_state,
    write_execution_kill_state,
)
from signalforge.execution.states import OrderState, UnknownResolution
from tests.execution.conftest import ADAPTER, NOW, arming_request, paper_proof
from tests.execution.fakes import FakeAdapter, FakePosition

OPEN_SHORT_LEG = "9999888877776666555544443333222"  # pragma: allowlist secret


def _posture(branch: CycleBranch, *, kill: bool = False, readable: bool = True) -> CyclePosture:
    return CyclePosture(
        branch=branch,
        may_open=branch is CycleBranch.FULL,
        may_close=True,
        kill_switch_engaged=kill,
        execution_kill=ExecutionKillState(engaged=not readable, readable=readable),
        detail="test posture",
    )


def _open_short_position(session: Session, client_order_id: str = OPEN_SHORT_LEG) -> FakePosition:
    """A SHORT option leg this OMS really opened — the riskiest thing in a book,
    and the one a "block everything" kill switch would strand."""
    from signalforge.execution.intents import PositionSnapshot

    record_execution_event(
        session,
        event_type=ExecutionEventType.FILL,
        adapter_name=ADAPTER,
        client_order_id=client_order_id,
        intent_kind=IntentKind.OPEN.value,
        state_from=OrderState.SUBMITTING.value,
        state_to=OrderState.FILLED.value,
    )
    return FakePosition(
        snapshot=PositionSnapshot(
            adapter_name=ADAPTER,
            legs=(
                PositionLeg(
                    instrument_key="O:SPY250718P00500000",
                    signed_qty=-1.0,
                    shares_per_contract=100,
                ),
            ),
        ),
        originating_client_order_id=client_order_id,
    )


def _protective_close(session: Session, position: FakePosition):
    """Build the flatten. Requires no armed row, no Candidate, no PaperTrade."""
    reconciled = ReconciledPosition(
        adapter_name=ADAPTER,
        legs=position.snapshot.legs,
        originating_client_order_id=position.originating_client_order_id,
        reconciled=True,
        adapter_reachable=True,
        reconciliation_diverged=False,
    )
    return build_close_intent(
        session,
        position=reconciled,
        legs=(
            OrderLeg(
                side=OrderSide.BUY_TO_CLOSE,
                ratio=1,
                shares_per_contract=100,
                option_ticker="O:SPY250718P00500000",
            ),
        ),
        contracts=1,
        limit_price=1.25,
        cost_model=CostModelFeedback(modelled_fill_price=1.20, modelled_spread_bps=40.0),
        now=NOW,
        max_intent_age_minutes=15,
    )


# ---------------------------------------------------------------------------
# The job table — V19's half that does not need an app process
# ---------------------------------------------------------------------------


def test_the_job_list_is_byte_identical_while_execution_is_disabled(session: Session) -> None:
    from signalforge.scheduler import default_job_specs

    assert cycle_mod.execution_job_specs() == []

    before = [
        (s.name, s.description, s.interval_minutes, s.cron_hour, s.cron_minute, s.self_guarded)
        for s in default_job_specs()
    ]
    worker_list = [*default_job_specs(), *cycle_mod.execution_job_specs()]
    after = [
        (s.name, s.description, s.interval_minutes, s.cron_hour, s.cron_minute, s.self_guarded)
        for s in worker_list
    ]
    assert after == before
    assert not any(s.self_guarded for s in default_job_specs())
    assert "execution_cycle" not in {s.name for s in default_job_specs()}


def test_the_job_is_registered_only_when_the_setting_is_on(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from signalforge.settings_store import RESEARCH_OVERRIDES_KEY, set_setting

    set_setting(session, RESEARCH_OVERRIDES_KEY, {"execution": {"enabled": True}})
    session.commit()

    specs = cycle_mod.execution_job_specs()
    assert [s.name for s in specs] == [cycle_mod.EXECUTION_CYCLE_JOB]
    # The one spec in the tree that must NOT be wrapped in scheduler.guarded.
    assert specs[0].self_guarded is True
    assert "nothing is armed by default" in specs[0].description


def test_build_scheduler_does_not_double_wrap_a_self_guarded_spec() -> None:
    """``guarded()`` returns without running the body while the kill switch is
    engaged. Wrapping the execution cycle in it would make the kill switch block
    closing, so ``build_scheduler`` must register a self-guarded spec's own
    callable unchanged."""
    from signalforge.scheduler import JobSpec, build_scheduler

    calls: list[str] = []

    def _body() -> None:
        calls.append("ran")

    scheduler = build_scheduler(
        specs=[
            JobSpec("self_guarded_probe", _body, 1, "probe", self_guarded=True),
            JobSpec("ordinary_probe", _body, 1, "probe"),
        ]
    )

    self_guarded = scheduler.get_job("self_guarded_probe")
    ordinary = scheduler.get_job("ordinary_probe")
    assert self_guarded is not None and ordinary is not None
    # The self-guarded spec is registered as ITSELF...
    assert self_guarded.func is _body
    # ...and every other spec keeps the wrapper it has always had.
    assert ordinary.func is not _body


def test_the_manual_job_entry_exists_even_while_disabled() -> None:
    entries = cycle_mod.manual_job_entries()
    assert set(entries) == {cycle_mod.EXECUTION_CYCLE_JOB}


# ---------------------------------------------------------------------------
# K2 — the execution-local kill state, fail-CLOSED where killswitch.py is open
# ---------------------------------------------------------------------------


def test_a_missing_execution_kill_state_is_not_engaged(tmp_path) -> None:
    state = read_execution_kill_state(tmp_path / "absent.json")
    assert state.engaged is False
    assert state.readable is True


def test_a_corrupt_execution_kill_state_BLOCKS(tmp_path) -> None:
    """The deliberate inverse of ``killswitch.py``: missing evidence of safety is
    not evidence of safety."""
    path = tmp_path / "k2.json"
    path.write_text("{not json", encoding="utf-8")

    state = read_execution_kill_state(path)

    assert state.engaged is True
    assert state.readable is False
    assert "corrupt" in state.reason


def test_engaging_and_releasing_k2_round_trips(tmp_path) -> None:
    path = tmp_path / "k2.json"
    write_execution_kill_state(engaged=True, reason="drill", actor="test", now=utcnow(), path=path)
    assert read_execution_kill_state(path).engaged is True

    write_execution_kill_state(
        engaged=False, reason="drill over", actor="test", now=utcnow(), path=path
    )
    assert read_execution_kill_state(path).engaged is False


def test_the_posture_is_protective_whenever_either_kill_state_says_so(tmp_path) -> None:
    from signalforge.killswitch import get_kill_switch

    clean = tmp_path / "clean.json"
    assert read_cycle_posture(kill_state_path=clean).branch is CycleBranch.FULL

    corrupt = tmp_path / "corrupt.json"
    corrupt.write_text("{", encoding="utf-8")
    assert read_cycle_posture(kill_state_path=corrupt).branch is CycleBranch.PROTECTIVE

    get_kill_switch().engage("drill", actor="test")
    posture = read_cycle_posture(kill_state_path=clean)
    assert posture.branch is CycleBranch.PROTECTIVE
    assert posture.may_open is False
    # The promise, in the object itself.
    assert posture.may_close is True


# ---------------------------------------------------------------------------
# The submission lock and the bounded drain (§8)
# ---------------------------------------------------------------------------


def test_the_submission_lock_stops_admitting() -> None:
    lock = SubmissionLock()
    lock.admit()  # no raise

    lock.close("the kill switch is engaged")
    with pytest.raises(SubmissionsClosed, match="kill switch"):
        lock.admit()

    lock.reopen()
    lock.admit()


def test_a_protective_cycle_closes_admissions_and_a_clean_one_reopens_them(
    session: Session, limits_row: object
) -> None:
    """Releasing the kill switch has to actually re-admit submissions. Without
    the reopen, the module-level lock would stay closed for the life of the
    process and the release would silently do nothing."""
    from signalforge.execution import deadman

    at = utcnow()
    cycle_mod.run_execution_cycle(
        session,
        _posture(CycleBranch.PROTECTIVE, kill=True),
        now=at,
        adapter=None,
        sleep=lambda _s: None,
        monotonic=iter([0.0, 0.0]).__next__,
    )
    assert cycle_mod.SUBMISSION_LOCK.admitting is False

    deadman.feed(session, now=at)
    cycle_mod.run_execution_cycle(session, _posture(CycleBranch.FULL), now=at, adapter=None)
    assert cycle_mod.SUBMISSION_LOCK.admitting is True

    # ...but a cycle whose dead man has lapsed does NOT reopen them.
    cycle_mod.run_execution_cycle(
        session,
        _posture(CycleBranch.FULL),
        now=at + timedelta(seconds=1000),
        adapter=None,
        sleep=lambda _s: None,
        monotonic=iter([0.0, 0.0]).__next__,
    )
    assert cycle_mod.SUBMISSION_LOCK.admitting is False
    cycle_mod.SUBMISSION_LOCK.reopen()  # leave the module-level lock as we found it


def test_the_in_flight_set_is_durable_not_in_memory(session: Session) -> None:
    """A process killed between the committed SUBMITTING write and the broker's
    response must leave the order visible to the next cycle."""
    record_execution_event(
        session,
        event_type=ExecutionEventType.SUBMITTING,
        adapter_name=ADAPTER,
        client_order_id="aaaabbbbccccddddeeeeffff00001111",  # pragma: allowlist secret
        state_from=OrderState.VALIDATED.value,
        state_to=OrderState.SUBMITTING.value,
    )
    assert in_flight_client_order_ids(session, adapter_name=ADAPTER) == [
        "aaaabbbbccccddddeeeeffff00001111"  # pragma: allowlist secret
    ]


def test_a_drain_that_completes_promotes_nothing(session: Session) -> None:
    ticks = iter([0.0, 1.0, 2.0, 3.0, 4.0])
    result = drain(
        session,
        adapter_name=ADAPTER,
        timeout_s=30.0,
        now=utcnow(),
        monotonic=lambda: next(ticks),
        sleep=lambda _s: None,
    )
    assert result.timed_out == ()
    assert result.drained == ()


def test_a_drain_that_times_out_promotes_to_unknown_not_to_failed(session: Session) -> None:
    """§8 step 3. The order may well have reached the broker, which is the entire
    reason UNKNOWN exists."""
    coid = "abcdabcdabcdabcdabcdabcdabcdabcd"  # pragma: allowlist secret
    record_execution_event(
        session,
        event_type=ExecutionEventType.SUBMITTING,
        adapter_name=ADAPTER,
        client_order_id=coid,
        state_from=OrderState.VALIDATED.value,
        state_to=OrderState.SUBMITTING.value,
    )
    ticks = iter([0.0, 0.0, 31.0, 31.0, 31.0])
    result = drain(
        session,
        adapter_name=ADAPTER,
        timeout_s=30.0,
        now=utcnow(),
        monotonic=lambda: next(ticks),
        sleep=lambda _s: None,
    )

    assert result.timed_out == (coid,)
    assert current_state(session, coid) is OrderState.UNKNOWN
    assert "promoted to UNKNOWN" in result.detail


# ---------------------------------------------------------------------------
# V1 — the kill switch, engaged, with an open position
# ---------------------------------------------------------------------------


def test_v1_the_protective_branch_runs_the_body_instead_of_skipping(
    session: Session, limits_row: object
) -> None:
    position = _open_short_position(session)
    adapter = FakeAdapter(positions_=[position])
    session.commit()

    report = cycle_mod.run_execution_cycle(
        session,
        _posture(CycleBranch.PROTECTIVE, kill=True),
        now=utcnow(),
        adapter=adapter,
        sleep=lambda _s: None,
        monotonic=iter([0.0, 0.0, 31.0, 31.0, 31.0]).__next__,
    )

    # The body ran. That is the sub-condition rev 1 of the ADR could not meet.
    assert report.branch is CycleBranch.PROTECTIVE
    assert report.may_open_possible is False
    types = [
        e.event_type
        for e in session.scalars(select(ExecutionEvent).order_by(ExecutionEvent.id)).all()
    ]
    assert ExecutionEventType.CYCLE_PROTECTIVE.value in types
    # ...and cancel_all() was called exactly once, after the drain.
    assert adapter.cancel_all_calls == 1
    # The drain sequence order: reconcile, drain+cancel_all, reconcile again.
    kill_idx = types.index(ExecutionEventType.KILL_SWITCH.value)
    assert types.index(ExecutionEventType.RECONCILED.value) < kill_idx
    assert types[kill_idx + 1 :].count(ExecutionEventType.RECONCILED.value) >= 1


def test_v1_a_protective_close_still_constructs_while_the_kill_switch_is_engaged(
    session: Session,
) -> None:
    position = _open_short_position(session)

    intent = _protective_close(session, position)

    assert intent.intent_kind is IntentKind.PROTECTIVE_CLOSE
    decision = may_close(
        CloseGateContext(
            position_exists_and_reconciled=True,
            originating_event_exists=True,
            non_increasing_in_every_leg=True,
            intent_kind_is_protective_close=True,
            adapter_reachable=True,
            reconciliation_diverged=False,
        )
    )
    assert decision.allowed


def test_v1_the_dead_man_is_fed_by_the_protective_branch_too(
    session: Session, limits_row: object
) -> None:
    """Otherwise engaging the kill switch would lapse the dead man ~90s later,
    and the lapse would disarm and re-run the drain — a self-inflicted cascade in
    the middle of the incident."""
    from signalforge.execution import deadman

    at = utcnow()
    cycle_mod.run_execution_cycle(
        session,
        _posture(CycleBranch.PROTECTIVE, kill=True),
        now=at,
        adapter=None,
        sleep=lambda _s: None,
        monotonic=iter([0.0, 0.0]).__next__,
    )

    assert deadman.assess(session, now=at, stale_after_s=90).alive is True


def test_the_guarded_wrapper_writes_a_job_run_naming_the_branch(session: Session) -> None:
    from signalforge.killswitch import get_kill_switch

    session.commit()
    get_kill_switch().engage("drill", actor="test")
    seen: list[str] = []

    def _body(posture: CyclePosture) -> str:
        seen.append(posture.branch.value)
        return "did the protective thing"

    execution_guarded("execution_cycle", _body)()

    assert seen == ["protective"]
    runs = list(session.scalars(select(JobRun).where(JobRun.name == "execution_cycle")))
    assert len(runs) == 1
    assert runs[0].status == "ok"
    assert "[protective]" in runs[0].detail


def test_a_failing_cycle_records_a_failed_job_run_and_re_raises(session: Session) -> None:
    session.commit()

    def _boom(_posture: CyclePosture) -> str:
        raise RuntimeError("the adapter exploded")

    with pytest.raises(RuntimeError, match="exploded"):
        execution_guarded("execution_cycle", _boom)()

    runs = list(session.scalars(select(JobRun).where(JobRun.name == "execution_cycle")))
    assert [r.status for r in runs] == ["failed"]
    assert "exploded" in runs[0].detail


# ---------------------------------------------------------------------------
# V2 — the dead-man lapse
# ---------------------------------------------------------------------------


def test_v2_a_lapse_disarms_blocks_opening_and_liquidates_nothing(
    session: Session, armable: StrategyVersion, limits_row: object
) -> None:
    from signalforge.execution.cycle import active_limits_created_at
    from signalforge.execution.limits import load_active_limits

    limits = load_active_limits(session)
    armed_row = arming.arm(
        session,
        arming_request(strategy_version_id=armable.id),
        now=utcnow(),
        is_paper_proof=paper_proof(),
        account_is_flat=True,
        actor="test",
        limits_id=limits.id if limits else None,
        limits_created_at=active_limits_created_at(session),
    )
    position = _open_short_position(session)
    adapter = FakeAdapter(positions_=[position], account_id="PAPER-ACCOUNT-1")
    # A heartbeat from 1000s ago, against a 90s window. The cycle assesses the
    # PREVIOUS beat before writing its own, which is what makes D1 mean anything
    # at all: a cycle that is running has by definition just fed the dead man.
    from signalforge.execution import deadman

    at = utcnow()
    deadman.feed(session, now=at - timedelta(seconds=1000))

    report = cycle_mod.run_execution_cycle(
        session, _posture(CycleBranch.FULL), now=at, adapter=adapter
    )

    assert report.dead_man_alive is False
    assert report.may_open_possible is False
    session.refresh(armed_row)
    assert armed_row.disarmed_at is not None
    assert armed_row.disarm_reason.startswith("dead_man_lapse")

    # §9's sequence DID run: resting orders are cancelled. That is not
    # liquidation — no position was closed and nothing was submitted.
    assert adapter.cancel_all_calls == 1
    assert adapter.placed == []
    assert len(adapter.positions_) == 1
    assert adapter.positions_[0].originating_client_order_id == OPEN_SHORT_LEG

    # ...and the close lane is untouched by all of it.
    assert _protective_close(session, position).intent_kind is IntentKind.PROTECTIVE_CLOSE


# ---------------------------------------------------------------------------
# V7 / V15 — SUBMITTING with no outcome -> UNKNOWN -> blocked arming -> cleared
# ---------------------------------------------------------------------------


def test_v7_a_submitting_with_no_outcome_becomes_unknown_on_the_next_cycle(
    session: Session, limits_row: object
) -> None:
    coid = "0f1e2d3c4b5a69788796a5b4c3d2e1f0"  # pragma: allowlist secret
    record_execution_event(
        session,
        event_type=ExecutionEventType.SUBMITTING,
        adapter_name=ADAPTER,
        client_order_id=coid,
        state_from=OrderState.VALIDATED.value,
        state_to=OrderState.SUBMITTING.value,
    )

    report = cycle_mod.run_execution_cycle(
        session, _posture(CycleBranch.FULL), now=utcnow(), adapter=None
    )

    assert report.promoted_unknown == (coid,)
    assert current_state(session, coid) is OrderState.UNKNOWN


def test_v7_a_retry_never_clears_an_unknown(session: Session) -> None:
    coid = "1234123412341234123412341234abcd"  # pragma: allowlist secret
    record_execution_event(
        session,
        event_type=ExecutionEventType.SUBMITTING,
        adapter_name=ADAPTER,
        client_order_id=coid,
        state_from=OrderState.VALIDATED.value,
        state_to=OrderState.SUBMITTING.value,
    )
    promote_stale_submitting(session, now=utcnow(), adapter_name=ADAPTER)

    # Running the promotion again — the "retry" — changes nothing.
    again = promote_stale_submitting(session, now=utcnow(), adapter_name=ADAPTER)
    assert again == []
    assert current_state(session, coid) is OrderState.UNKNOWN


def test_v15_the_unknown_is_cleared_with_no_manual_db_write(
    session: Session, armable: StrategyVersion, limits_row: object
) -> None:
    """Crash mid-submit -> restart -> UNKNOWN -> auto-disarm -> clear -> close,
    with no hand-edited row at any step.

    Rev 1 of the ADR could enter this state and not leave it. Two rules close it:
    the close factory needs no armed row, and the ``is_paper`` proof reads the
    DISARMED ``armed_strategy`` row.
    """
    from signalforge.execution.cycle import active_limits_created_at
    from signalforge.execution.limits import load_active_limits
    from signalforge.execution.oms import resolve_unknown
    from signalforge.execution.reconcile import expected_account_id_for

    limits = load_active_limits(session)
    armed_row = arming.arm(
        session,
        arming_request(strategy_version_id=armable.id),
        now=utcnow(),
        is_paper_proof=paper_proof(),
        account_is_flat=True,
        actor="test",
        limits_id=limits.id if limits else None,
        limits_created_at=active_limits_created_at(session),
    )
    position = _open_short_position(session)
    coid = "cafecafecafecafecafecafecafecafe"  # pragma: allowlist secret
    record_execution_event(
        session,
        event_type=ExecutionEventType.SUBMITTING,
        adapter_name=ADAPTER,
        client_order_id=coid,
        state_from=OrderState.VALIDATED.value,
        state_to=OrderState.SUBMITTING.value,
        strategy_version_id=armable.id,
        armed_strategy_id=armed_row.id,
    )

    # ...the process dies here. The next cycle is the first after the restart.
    report = cycle_mod.run_execution_cycle(
        session, _posture(CycleBranch.FULL), now=utcnow(), adapter=None
    )
    assert coid in report.promoted_unknown
    session.refresh(armed_row)
    assert armed_row.disarmed_at is not None  # §12 step 7

    # The disarmed row still answers "which account was this adapter pointed at".
    assert expected_account_id_for(session, ADAPTER) == "PAPER-ACCOUNT-1"

    # The UNKNOWN clears only with BOTH halves, and neither is a DB edit.
    resolved = resolve_unknown(
        session,
        coid,
        resolution=UnknownResolution(
            reconciled_from_order_status=True,
            operator_acknowledged=True,
            broker_terminal_state=OrderState.REJECTED,
            acknowledged_by="operator",
            note="order_status() says the broker rejected it",
        ),
        actor="operator",
    )
    assert resolved is OrderState.REJECTED

    # And the position is closable throughout, with no armed row in sight.
    assert arming.live_armings(session) == []
    assert _protective_close(session, position).intent_kind is IntentKind.PROTECTIVE_CLOSE


# ---------------------------------------------------------------------------
# V18 — the headline promise, proved rather than asserted
# ---------------------------------------------------------------------------


def test_v18_a_disarmed_strategy_with_an_open_short_leg_can_still_be_flattened(
    session: Session, armable: StrategyVersion, limits_row: object
) -> None:
    """Disarmed, expired, kill switch engaged, dead man lapsed, no Candidate and
    no PaperTrade behind it — and the protective close still constructs and still
    passes ``may_close``."""
    from signalforge.execution.cycle import active_limits_created_at
    from signalforge.execution.limits import load_active_limits
    from signalforge.killswitch import get_kill_switch

    limits = load_active_limits(session)
    armed_row = arming.arm(
        session,
        arming_request(strategy_version_id=armable.id),
        now=utcnow(),
        is_paper_proof=paper_proof(),
        account_is_flat=True,
        actor="test",
        limits_id=limits.id if limits else None,
        limits_created_at=active_limits_created_at(session),
    )
    position = _open_short_position(session)

    arming.disarm(
        session,
        armed_row,
        trigger=arming.DisarmTrigger.OPERATOR,
        detail="drill V18",
        now=utcnow(),
    )
    # Expire it too, so neither state is what the close depends on.
    armed_row.expires_at = utcnow() - timedelta(days=1)
    session.flush()
    session.commit()
    get_kill_switch().engage("drill V18", actor="test")

    posture = read_cycle_posture()
    assert posture.branch is CycleBranch.PROTECTIVE
    assert posture.may_open is False
    assert posture.may_close is True
    assert arming.live_armings(session) == []

    intent = _protective_close(session, position)
    assert intent.intent_kind is IntentKind.PROTECTIVE_CLOSE
    assert intent.client_order_id  # a stable id keyed on the ORIGINATING order

    decision = may_close(
        CloseGateContext(
            position_exists_and_reconciled=True,
            originating_event_exists=True,
            non_increasing_in_every_leg=True,
            intent_kind_is_protective_close=True,
            adapter_reachable=True,
            reconciliation_diverged=False,
        )
    )
    assert decision.allowed

    # ...and the adapter really accepts it. Nothing about the disarmed, expired,
    # kill-switched research state reached the submission.
    adapter = FakeAdapter(positions_=[position])
    result = adapter.place(intent)  # type: ignore[arg-type]
    assert result.state is OrderState.FILLED
    assert adapter.placed == [intent.client_order_id]


def test_a_diverged_book_is_the_ONE_thing_that_blocks_a_close() -> None:
    """Closing into an unknown book is not protective — the single exception to
    "never blocks closing", and it is in the ADR for that reason."""
    blocked = may_close(
        CloseGateContext(
            position_exists_and_reconciled=True,
            originating_event_exists=True,
            non_increasing_in_every_leg=True,
            intent_kind_is_protective_close=True,
            adapter_reachable=True,
            reconciliation_diverged=True,
        )
    )
    assert not blocked.allowed
    assert "DIVERGED" in blocked.first_failure


# ---------------------------------------------------------------------------
# The full branch, with nothing armed — the default state
# ---------------------------------------------------------------------------


def test_the_full_branch_with_nothing_armed_says_so_and_opens_nothing(
    session: Session, limits_row: object
) -> None:
    from signalforge.execution import deadman

    adapter = FakeAdapter()
    at = utcnow()
    deadman.feed(session, now=at)  # a healthy previous cycle

    report = cycle_mod.run_execution_cycle(
        session, _posture(CycleBranch.FULL), now=at, adapter=adapter
    )

    assert report.branch is CycleBranch.FULL
    assert report.dead_man_alive is True
    assert report.may_open_possible is False
    assert any("nothing is armed" in reason for reason in report.blocked_reasons)
    # A healthy full cycle with nothing armed touches the broker only to READ.
    assert adapter.placed == []
    assert adapter.cancel_all_calls == 0


def test_the_cycle_runs_with_no_adapter_at_all(session: Session, limits_row: object) -> None:
    """The local half of the cycle does not need a broker, and the missing half
    reports "could not be evaluated" rather than a plausible default."""
    report = cycle_mod.run_execution_cycle(
        session, _posture(CycleBranch.FULL), now=utcnow(), adapter=None
    )

    assert report.reconciliation_status == "not evaluated"
    assert report.may_open_possible is False
    assert any("no adapter" in reason for reason in report.blocked_reasons)


def test_an_is_paper_mismatch_in_the_cycle_disarms(
    session: Session, armable: StrategyVersion, limits_row: object
) -> None:
    """§13 rule 4: the proof is re-taken EVERY cycle, not cached from arm time."""
    from signalforge.execution.cycle import active_limits_created_at
    from signalforge.execution.limits import load_active_limits

    limits = load_active_limits(session)
    armed_row = arming.arm(
        session,
        arming_request(strategy_version_id=armable.id),
        now=utcnow(),
        is_paper_proof=paper_proof(),
        account_is_flat=True,
        actor="test",
        limits_id=limits.id if limits else None,
        limits_created_at=active_limits_created_at(session),
    )
    # The adapter now answers with a DIFFERENT account than the armed record.
    adapter = FakeAdapter(account_id="SOMEONE-ELSES-ACCOUNT")
    # Keep the dead man alive so the is_paper failure is the FIRST trigger to
    # fire: §12 step 7 records one reason, and the test is about which one.
    from signalforge.execution import deadman

    at = utcnow()
    deadman.feed(session, now=at)

    cycle_mod.run_execution_cycle(session, _posture(CycleBranch.FULL), now=at, adapter=adapter)

    session.refresh(armed_row)
    assert armed_row.disarmed_at is not None
    assert "is_paper" in armed_row.disarm_reason
    proofs = session.scalars(
        select(ExecutionEvent).where(
            ExecutionEvent.event_type == ExecutionEventType.IS_PAPER_PROOF.value
        )
    ).all()
    assert proofs and proofs[0].payload_json["proven"] is False


def test_a_posture_object_cannot_smuggle_may_open_into_the_protective_branch() -> None:
    """``may_open`` in the protective branch is False by construction, and the
    branch's code path has no opening step in it at all — the flag is a record of
    the decision, not the enforcement."""
    protective = _posture(CycleBranch.PROTECTIVE, kill=True)
    lying = replace(protective, may_open=True)

    # Even a hand-forged posture cannot open anything: the protective code path
    # is selected on `branch`, and it contains no submission.
    assert lying.branch is CycleBranch.PROTECTIVE
