"""The execution cycle and its scheduler registration (D6 §2, §8).

One job, ``execution_cycle``, registered **only when ``execution.enabled`` is
True** — which ships False. On today's deployment the worker's job list is
byte-identical to what it was before this module existed, and
``tests/execution/test_cycle.py`` asserts exactly that against
``scheduler.default_job_specs()``.

**Two branches, and which one runs is decided before the body starts.**

* **Full** — dead-man heartbeat, promote stale ``SUBMITTING`` records,
  auto-disarm sweep, reconcile, calendar cross-check, then the open lane and the
  close lane.
* **Protective** (kill switch engaged, or the execution-local kill state
  unreadable) — dead-man heartbeat, reconcile, bounded drain, ``cancel_all()``,
  reconcile **again**, then the close lane only. There is no opening step in
  this code path at all; ``may_open`` is unreachable by construction rather than
  by a flag, and a ``CYCLE_PROTECTIVE`` event records that it ran.

The heartbeat is written FIRST in **both** branches. If the protective branch
did not feed the dead man, engaging the kill switch would lapse it ~90 seconds
later, the lapse would disarm everything and run the drain sequence again, and
the operator would be debugging a self-inflicted cascade in the middle of the
incident they engaged the switch for.

**The registration rule (§2, and it is the one place this ADR changes a running
process).** ``signalforge.scheduler`` must not import ``signalforge.execution``,
because ``signalforge.app`` imports the scheduler and S15b reports indirect
chains. ``signalforge/app/**`` must not resolve it either. So the spec is
injected from **exactly one place — ``signalforge.cli``** — which passes it to
``build_scheduler(specs=...)``. The operator-visible consequence, stated rather
than discovered later: the execution cycle exists **only in the CLI-launched
worker**. Started from the app process there is no execution job at all — no
submissions, and equally no heartbeat, no reconciliation, no drain and no
protective cycle.

**No adapter is required.** Every local half of the cycle — heartbeat, stale
promotion, auto-disarm, the limits evaluation — runs with ``adapter=None``, and
the adapter-dependent half (reconciliation, the clock cross-check, the drain's
``cancel_all()``) reports "could not be evaluated", which BLOCKS opening and is
the correct answer rather than a degraded one.

**How the adapter gets here (``adapter_factory``).** An adapter's audit sink
writes ``execution_event`` rows through a session, and the cycle opens its own
session inside the job body — so an adapter constructed by the caller, before
that session exists, would be writing through a session that is no longer open.
``execution_cycle_job`` therefore accepts an ``adapter_factory`` that is called
**with the cycle's own session**, once per cycle. ``adapter=`` is still accepted
for tests and drills that own their session, and with neither the cycle runs
adapter-free exactly as before. A factory that returns ``None`` or raises does
not stop the cycle: the local half still runs, the failure is recorded, and
opening blocks — which is the whole reason the two halves are separate.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from signalforge.execution import arming, calendarcheck, deadman, open_lane
from signalforge.execution import reconcile as reconcile_mod
from signalforge.execution.events import ExecutionEventType, record_execution_event
from signalforge.execution.limits import LimitSet, load_active_limits
from signalforge.execution.oms import (
    CycleBranch,
    CyclePosture,
    SubmissionLock,
    drain,
    execution_guarded,
    promote_stale_submitting,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from sqlalchemy.orm import Session

    from signalforge.db.models import ArmedStrategy
    from signalforge.execution.protocol import BrokerAdapter
    from signalforge.jobspec import JobSpec

__all__ = [
    "EXECUTION_CYCLE_JOB",
    "AdapterFactory",
    "CycleReport",
    "active_limits_created_at",
    "execution_cycle_job",
    "execution_job_specs",
    "manual_job_entries",
    "run_execution_cycle",
]

#: Called with the CYCLE's own session, once per cycle, to build the adapter it
#: will use. ``None`` back is not an error — it is the fail-closed answer, and
#: every adapter-dependent check then reports "could not be evaluated".
AdapterFactory = Callable[["Session"], "BrokerAdapter | None"]

#: The one job name. Kept as a constant so the CLI's manual-job entry, the spec
#: and the ``JobRun`` rows cannot drift apart.
EXECUTION_CYCLE_JOB = "execution_cycle"

#: Process-local submission admission control (§8). One worker per DB is the
#: standing rule, so one module-level lock is the whole in-process story; the
#: durable in-flight set lives in ``execution_event`` and survives a crash.
SUBMISSION_LOCK = SubmissionLock()


@dataclass
class CycleReport:
    """What the cycle did, for the ``JobRun`` note and for tests.

    Deliberately a plain record of observations rather than a verdict: the gates
    decide, this reports. ``blocked_reasons`` accumulates every reason opening
    was blocked, not just the first, because every one of them is written to
    ``execution_event``.
    """

    branch: CycleBranch
    dead_man_alive: bool | None = None
    disarms: tuple[str, ...] = ()
    promoted_unknown: tuple[str, ...] = ()
    reconciliation_status: str = "not evaluated"
    reconciliation_age_s: float | None = None
    calendar_detail: str = ""
    drained: int = 0
    drain_timed_out: int = 0
    cancelled: int | None = None
    may_open_possible: bool = False
    #: What the OPEN lane did, when it ran at all. Empty is the default state
    #: and the shipped one: with nothing armed the lane is not entered.
    open_lane: str = ""
    submitted: tuple[str, ...] = ()
    filled: tuple[str, ...] = ()
    blocked_reasons: list[str] = field(default_factory=list)
    detail: str = ""

    def note(self) -> str:
        bits = [
            f"branch={self.branch.value}",
            f"dead_man={'alive' if self.dead_man_alive else 'LAPSED'}",
            f"reconciliation={self.reconciliation_status}",
        ]
        if self.disarms:
            bits.append(f"disarmed={len(self.disarms)}")
        if self.promoted_unknown:
            bits.append(f"unknown={len(self.promoted_unknown)}")
        if self.branch is CycleBranch.PROTECTIVE:
            bits.append(f"drained={self.drained}/timed_out={self.drain_timed_out}")
            if self.cancelled is not None:
                bits.append(f"cancelled={self.cancelled}")
        if self.open_lane:
            bits.append(f"open_lane[{self.open_lane}]")
        if self.blocked_reasons:
            bits.append(f"open_blocked={self.blocked_reasons[0]}")
        return "; ".join(bits)


def _limits_or_none(session: Session) -> LimitSet | None:
    return load_active_limits(session)


def active_limits_created_at(session: Session) -> datetime | None:
    """When the active ``execution_limits`` row was created — §7b rule 3's reset
    point for the decision-10 evidence counter."""
    from sqlalchemy import select

    from signalforge.db.models import ExecutionLimits

    return session.scalar(
        select(ExecutionLimits.created_at)
        .where(ExecutionLimits.superseded_at.is_(None))
        .order_by(ExecutionLimits.created_at.desc(), ExecutionLimits.id.desc())
        .limit(1)
    )


def run_execution_cycle(
    session: Session,
    posture: CyclePosture,
    *,
    now: datetime | None = None,
    adapter: BrokerAdapter | None = None,
    sleep: Callable[[float], None] | None = None,
    monotonic: Callable[[], float] | None = None,
    actor: str = "system",
) -> CycleReport:
    """One cycle, in the order §8 and §9 fix. Returns what it observed.

    The caller owns the transaction and the branch: ``execution_guarded`` has
    already read K1/K2 and decided, so this function never re-reads the kill
    switch to second-guess its own posture.
    """
    at = now or datetime.now(UTC)
    report = CycleReport(branch=posture.branch)
    limits = _limits_or_none(session)
    adapter_name = getattr(adapter, "name", "") if adapter is not None else ""

    # -- 1. the dead man: ASSESS the previous beat, THEN feed this one (§9) --
    #
    # The order is load-bearing and the obvious order is wrong. Feeding first and
    # assessing afterwards would make D1 vacuous — a cycle that is running has by
    # definition just written a fresh heartbeat, so the check would pass in every
    # cycle including the first one after an hour-long gap. What the dead man
    # protects against is the cycle NOT running, so what it must read is the
    # PREVIOUS cycle's beat.
    #
    # The feed then happens unconditionally, in BOTH branches. If the protective
    # branch did not feed it, engaging the kill switch would lapse the dead man
    # ~90s later, the lapse would disarm and re-run the drain, and the operator
    # would be debugging a self-inflicted cascade in the middle of the incident
    # they engaged the switch for.
    stale_after = limits.execution_stale_after_s if limits is not None else 0
    state = deadman.assess(session, now=at, stale_after_s=stale_after)
    deadman.feed(session, now=at, detail=f"cycle {posture.branch.value}")
    report.dead_man_alive = state.alive
    if not state.alive:
        record_execution_event(
            session,
            event_type=ExecutionEventType.DEAD_MAN_LAPSE,
            adapter_name=adapter_name,
            reason=state.detail,
            actor=actor,
        )
        report.blocked_reasons.append(f"D1: {state.detail}")

    # -- 2. a SUBMITTING with no outcome is an UNKNOWN, always (§6 rule 3) ---
    report.promoted_unknown = tuple(
        promote_stale_submitting(session, now=at, adapter_name=adapter_name or None, actor=actor)
    )

    if posture.branch is CycleBranch.FULL and not state.lapsed:
        # A fresh cycle that observed a clean posture is the ONLY thing that
        # reopens admissions. Without this the module-level lock, once closed by
        # a protective cycle, would stay closed for the life of the process and
        # releasing the kill switch would silently do nothing.
        SUBMISSION_LOCK.reopen(f"clean posture observed at {at.isoformat()}")

    if state.lapsed and posture.branch is CycleBranch.FULL:
        # §9: a lapse "blocks all opening, triggers the §8 drain-and-cancel
        # sequence, and auto-disarms — while leaving may_close open". Cancelling
        # RESTING ORDERS is not liquidation: no position is closed here, and
        # nothing is submitted. The operator still closes any open position by
        # hand, at the broker (arming acknowledgement (ii)).
        _protective_branch(
            session,
            report,
            at=at,
            adapter=adapter,
            adapter_name=adapter_name,
            limits=limits,
            sleep=sleep,
            monotonic=monotonic,
            actor=actor,
        )

    if posture.branch is CycleBranch.PROTECTIVE:
        record_execution_event(
            session,
            event_type=ExecutionEventType.CYCLE_PROTECTIVE,
            adapter_name=adapter_name,
            reason=(
                "protective-only cycle: heartbeat, reconcile, bounded drain, cancel_all, "
                f"reconcile again, may_close only — {posture.detail}"
            ),
            payload={
                "kill_switch_engaged": posture.kill_switch_engaged,
                "execution_kill_engaged": posture.execution_kill.engaged,
                "execution_kill_readable": posture.execution_kill.readable,
            },
            actor=actor,
        )
        _protective_branch(
            session,
            report,
            at=at,
            adapter=adapter,
            adapter_name=adapter_name,
            limits=limits,
            sleep=sleep,
            monotonic=monotonic,
            actor=actor,
        )

    # -- 3. reconciliation (both branches; the protective one has already run
    #       its pre-cancel round and this is the post-cancel one) ------------
    recon = None
    if adapter is not None:
        recon = reconcile_mod.reconcile(session, adapter, now=at, limits=limits, actor=actor)
        report.reconciliation_status = recon.status.value
    else:
        report.blocked_reasons.append("R1: no adapter is configured, so nothing is reconciled")
    report.reconciliation_age_s = reconcile_mod.last_clean_reconciliation_age_s(
        session, adapter_name=adapter_name, now=at
    )

    # -- 4. the clock / calendar cross-check (§11) ---------------------------
    clock = None
    if adapter is not None:
        try:
            clock = adapter.clock()
        except Exception as exc:
            report.blocked_reasons.append(f"C1: the adapter clock could not be read ({exc})")
    verdict = calendarcheck.evaluate(at, clock)
    report.calendar_detail = verdict.detail
    if verdict.blocks_opening:
        report.blocked_reasons.append(f"C1/C2: {verdict.detail}")

    # -- 4b. §10 rule 2 / §13 — ONE adapter answers for ONE account ----------
    #
    # Evaluated on the armings as they stand BEFORE the sweep, and that placement
    # is the point. ``expected_account_id_for`` resolves a single expected id —
    # the most recent armed row's (§13 rule 4b) — so when two live armings name
    # two different accounts the proof necessarily fails for the other one and
    # the sweep disarms EVERYTHING on ``is_paper_failed_to_reprove``. Checked
    # only after the sweep, this refusal would never be reachable, and the
    # operator would be told "the broker answered for the wrong account" when
    # what actually happened is "you armed two accounts on one adapter". Those
    # are different mistakes with different fixes, and the record has to say
    # which one it was.
    account_scope_ok = _account_scope_ok(
        session,
        report,
        arming.live_armings(session, adapter_name=adapter_name or None),
        adapter_name=adapter_name,
        actor=actor,
    )

    # -- 5. the auto-disarm sweep (§12 step 7, decision 9) -------------------
    facts = arming.CycleFacts(
        kill_switch_engaged=posture.kill_switch_engaged,
        execution_kill_engaged=(
            posture.execution_kill.engaged if posture.execution_kill.readable else True
        ),
        dead_man_alive=state.alive,
        reconciliation_diverged=(recon.diverged if recon is not None else None),
        reconciliation_age_s=report.reconciliation_age_s,
        max_reconciliation_age_s=(limits.max_reconciliation_age_s if limits else None),
        is_paper_proven=_is_paper_proven(session, adapter, adapter_name),
        orders_today=None,
    )
    disarms = arming.auto_disarm_sweep(
        session, now=at, facts=facts, adapter_name=adapter_name or None, actor=actor
    )
    report.disarms = tuple(f"{d.armed_strategy_id}:{d.trigger.value}" for d in disarms)

    # -- 6. what remains armed after the sweep is what MIGHT open ------------
    remaining = arming.live_armings(session, adapter_name=adapter_name or None)

    # §13 — the proof is re-taken EVERY cycle and never cached from arm time.
    # The sweep above already disarms on a FAILED proof; this states the refusal
    # in the cycle's own report as well, so "why did nothing open" is answered
    # from the JobRun note rather than inferred from a disarm.
    if adapter is not None and facts.is_paper_proven is not True:
        report.blocked_reasons.append(
            "A2: is_paper() did not prove out against the armed account id this cycle"
            if facts.is_paper_proven is False
            else "A2: is_paper() could not be evaluated this cycle — not proved, and not disproved"
        )

    report.may_open_possible = bool(
        remaining
        and posture.may_open
        and state.alive
        and recon is not None
        and recon.clean
        and not verdict.blocks_opening
        and limits is not None
        and facts.is_paper_proven is True
        and account_scope_ok
    )
    if not remaining:
        report.blocked_reasons.append(
            "A1: nothing is armed — the default state, and the one two independent gates exist "
            "to preserve"
        )
    if not report.may_open_possible and posture.may_open:
        record_execution_event(
            session,
            event_type=ExecutionEventType.LIMIT_BLOCKED,
            adapter_name=adapter_name,
            reason=("; ".join(report.blocked_reasons) or "no opening candidate this cycle")[:300],
            actor=actor,
        )

    # -- 7. the OPEN lane (§2 cycle body, §5, §6/§8) -------------------------
    #
    # Reached only when EVERY condition above held in THIS cycle, and it is a
    # conjunction of independent gates rather than one flag: something armed and
    # un-swept, the FULL branch, a live dead man, a CLEAN reconciliation, an
    # open market both sources agree on, a parseable limits row, a proven
    # is_paper, and one account across every arming. With nothing armed —
    # the default and the shipped state — `remaining` is empty, this is False,
    # and `run_open_lane` is never called at all.
    #
    # `may_open_possible` is necessary and still not sufficient: the lane
    # re-evaluates every `may_open` limit PER ORDER (the notional and daily-count
    # caps cannot be evaluated without an order) and `build_open_intent`
    # re-verifies all seven §5 preconditions against the database again.
    if report.may_open_possible and adapter is not None and limits is not None:
        # Read ONLY here, so a cycle with nothing armed makes no extra adapter
        # call and the "absent when nothing is armed" promise stays strict.
        account_equity, account_exposure = _account_facts(adapter)
        lane = open_lane.run_open_lane(
            session,
            open_lane.OpenLaneContext(
                now=at,
                adapter_name=adapter_name,
                limits=limits,
                verdict=verdict,
                armed=remaining,
                kill_switch_engaged=posture.kill_switch_engaged,
                execution_kill_engaged=(
                    posture.execution_kill.engaged if posture.execution_kill.readable else True
                ),
                dead_man_alive=state.alive,
                reconciliation_clean=(recon.clean if recon is not None else None),
                reconciliation_age_s=report.reconciliation_age_s,
                is_paper_proven=facts.is_paper_proven,
                account_equity_usd=account_equity,
                account_exposure_usd=account_exposure,
            ),
            adapter=adapter,
            actor=actor,
        )
        report.open_lane = lane.note
        report.submitted = tuple(lane.submitted)
        report.filled = tuple(lane.filled)

    report.detail = report.note()
    return report


def _account_facts(adapter: BrokerAdapter) -> tuple[float | None, float | None]:
    """``(equity, exposure)`` from the broker's OWN book, or ``(None, None)``.

    ``None`` blocks L2 — an uncomputable cap is not a cap — so an unreachable
    adapter refuses the order rather than sizing it against a guess. Exposure is
    the absolute market value the broker reports, not a local model: §10's rule
    is that the broker's figure is authoritative and the local model is a model.
    """
    try:
        account = adapter.account()
        positions = list(adapter.positions())
    except Exception:
        return None, None
    try:
        equity = float(account.equity)
    except (TypeError, ValueError):
        return None, None
    exposure = 0.0
    for position in positions:
        try:
            exposure += abs(float(getattr(position, "market_value", 0.0) or 0.0))
        except (TypeError, ValueError):
            return equity, None
    return equity, exposure


def _account_scope_ok(
    session: Session,
    report: CycleReport,
    remaining: Sequence[ArmedStrategy],
    *,
    adapter_name: str,
    actor: str,
) -> bool:
    """Do the live armings agree on ONE broker account? (§10 rule 2, §13.)

    An adapter is pointed at exactly one account, and ``is_paper()`` proves the
    account in the broker's own response against ONE expected id — the most
    recent armed row's (§13 rule 4b). Two live armings naming different accounts
    therefore leave at least one of them armed against an account nothing proved
    anything about, and "the other arming's proof passed" is not a proof about
    this one.

    Fail-closed and audited: opening blocks for **all** of them, and an
    ``execution_event`` records which ids disagreed. It does NOT disarm — that is
    §12 step 7's job and its triggers are the ADR's list, not this function's —
    and it does not touch the close lane, which needs no armed row at all.
    """
    ids = sorted(
        {row.broker_account_id_expected for row in remaining if row.broker_account_id_expected}
    )
    if len(ids) <= 1:
        return True
    detail = (
        f"§10 rule 2: {len(remaining)} live armings name {len(ids)} different broker accounts "
        f"({', '.join(ids)}) — one adapter answers for ONE account, so the is_paper proof taken "
        "this cycle proves nothing about the others; opening blocks for all of them"
    )
    report.blocked_reasons.append(f"A1/A2: {detail}")
    record_execution_event(
        session,
        event_type=ExecutionEventType.LIMIT_BLOCKED,
        adapter_name=adapter_name,
        reason=detail[:300],
        payload={
            "expected_account_ids": ids,
            "armed_strategy_ids": [row.id for row in remaining],
        },
        actor=actor,
    )
    return False


def _is_paper_proven(
    session: Session, adapter: BrokerAdapter | None, adapter_name: str
) -> bool | None:
    """§13 — re-taken EVERY cycle, never cached from arm time.

    ``None`` when there is no adapter to ask: "could not prove" is not "proved",
    and it is also not "disproved" — it blocks opening (A2 is tri-state) without
    disarming, because disarming the whole book on a transient read failure would
    make an outage indistinguishable from a misconfiguration.
    """
    if adapter is None:
        return None
    expected = reconcile_mod.expected_account_id_for(session, adapter_name)
    try:
        proof = adapter.is_paper()
    except Exception:
        return None
    if not expected:
        # §13 rule 4b's last step is a refusal, not a default: with no armed row
        # ever written for this adapter and no reviewed configuration, there is
        # nothing to prove the account against.
        return False
    ok = bool(proof.proven and proof.observed_account_id == expected)
    record_execution_event(
        session,
        event_type=ExecutionEventType.IS_PAPER_PROOF,
        adapter_name=adapter_name,
        reason=(
            f"is_paper {'PROVEN' if ok else 'FAILED'}: observed "
            f"{proof.observed_account_id!r} on {proof.observed_host!r}, expected {expected!r}"
        ),
        payload={
            "proven": ok,
            "observed_account_id": proof.observed_account_id,
            "observed_host": proof.observed_host,
            "expected_account_id": expected,
            "failure_reason": proof.failure_reason,
        },
    )
    return ok


def _protective_branch(
    session: Session,
    report: CycleReport,
    *,
    at: datetime,
    adapter: BrokerAdapter | None,
    adapter_name: str,
    limits: LimitSet | None,
    sleep: Callable[[float], None] | None,
    monotonic: Callable[[], float] | None,
    actor: str,
) -> None:
    """§8 steps 3-4, in order: stop admitting, drain (bounded), reconcile,
    ``cancel_all()``, reconcile again. Both reconciliation results are recorded.

    ``may_close`` is untouched throughout. Closing an existing position is
    allowed while the kill switch is engaged — it is protective — and the close
    factory requires no armed row, so a protective close remains constructible
    for the whole of this branch.
    """
    SUBMISSION_LOCK.close("the kill switch or the execution-local kill state is engaged")

    if adapter is not None:
        pre = reconcile_mod.reconcile(session, adapter, now=at, limits=limits, actor=actor)
        report.reconciliation_status = f"pre-cancel {pre.status.value}"

    timeout_s = float(limits.drain_timeout_s) if limits is not None else 30.0
    result = drain(
        session,
        adapter_name=adapter_name,
        timeout_s=timeout_s,
        now=at,
        monotonic=monotonic,
        sleep=sleep,
        actor=actor,
    )
    report.drained = len(result.drained)
    report.drain_timed_out = len(result.timed_out)

    if adapter is not None:
        try:
            cancelled = list(adapter.cancel_all())
            report.cancelled = len(cancelled)
        except Exception as exc:
            report.cancelled = None
            record_execution_event(
                session,
                event_type=ExecutionEventType.KILL_SWITCH,
                adapter_name=adapter_name,
                reason=f"cancel_all() failed during the drain sequence: {exc!r}"[:300],
                actor=actor,
            )
    record_execution_event(
        session,
        event_type=ExecutionEventType.KILL_SWITCH,
        adapter_name=adapter_name,
        reason=(
            f"drain sequence: {result.detail}; cancel_all -> "
            f"{report.cancelled if report.cancelled is not None else 'UNAVAILABLE'}"
        )[:300],
        payload={
            "drained": list(result.drained),
            "timed_out_to_unknown": list(result.timed_out),
            "waited_s": result.waited_s,
        },
        actor=actor,
    )


# ---------------------------------------------------------------------------
# Scheduler + manual-job registration
# ---------------------------------------------------------------------------


def execution_cycle_job(
    *,
    adapter: BrokerAdapter | None = None,
    adapter_factory: AdapterFactory | None = None,
    actor: str = "scheduler",
) -> Callable[[], None]:
    """The registered job: ``execution_guarded`` wrapping one database-scoped
    cycle. Returns a zero-argument callable, which is what a ``JobSpec`` holds.

    ``adapter_factory`` is called with the cycle's OWN session, once per cycle,
    because an adapter's audit sink writes ``execution_event`` rows through a
    session and the caller has none at registration time. ``adapter=`` still
    wins when both are given — a caller that already owns the session (a test, a
    drill) has said so explicitly. With neither, the cycle runs adapter-free and
    every adapter-dependent check reports "could not be evaluated", which blocks
    opening: byte-identical to the behaviour before factories existed.
    """

    def _body(posture: CyclePosture) -> str:
        from signalforge.db.session import session_scope

        with session_scope(write=True) as session:
            live = adapter if adapter is not None else _build(session, adapter_factory, actor)
            report = run_execution_cycle(session, posture, adapter=live, actor=actor)
        return report.note()

    return execution_guarded(EXECUTION_CYCLE_JOB, _body)


def _build(
    session: Session, adapter_factory: AdapterFactory | None, actor: str
) -> BrokerAdapter | None:
    """Build this cycle's adapter, or ``None`` — never raising out of the cycle.

    A factory that fails must not take the cycle down with it. The local half —
    the dead-man heartbeat above all — is exactly what must keep running when the
    broker side is unavailable: a cycle that aborted here would stop feeding the
    dead man, the dead man would lapse ~90 seconds later, and the lapse would
    disarm the whole book and run the drain sequence. An unbuildable adapter is a
    blocked open, not a cascade.
    """
    if adapter_factory is None:
        return None
    try:
        return adapter_factory(session)
    except Exception as exc:
        record_execution_event(
            session,
            event_type=ExecutionEventType.LIMIT_BLOCKED,
            reason=f"the broker adapter could not be built this cycle: {exc!r}"[:300],
            actor=actor,
        )
        return None


def execution_job_specs(
    *,
    adapter: BrokerAdapter | None = None,
    adapter_factory: AdapterFactory | None = None,
) -> list[JobSpec]:
    """The execution job, or **an empty list** when the layer is disabled.

    Deliberately the ``_intraday_scan_spec`` shape rather than an
    always-registered job that returns early: at a 30-second cadence an
    always-registered job would write ~780 ``JobRun`` rows per session for a
    deployment that has not opted in, changing what the Operational Status page
    shows. With ``execution.enabled`` False the job list is byte-identical to
    ``default_job_specs()``.

    ``self_guarded=True`` is load-bearing, not decoration: ``build_scheduler``
    wraps every other spec in ``scheduler.guarded``, which RETURNS without
    running the body when the kill switch is engaged. This job supplies its own
    wrapper that branches instead, because a cycle that does not run while the
    kill switch is engaged is a kill switch that blocks closing.

    Best-effort config read, matching ``_intraday_scan_spec``: the scheduler must
    still start if the database is momentarily unavailable, and the safe answer
    there is "not scheduled".
    """
    from signalforge.jobspec import JobSpec
    from signalforge.observability import get_logger

    try:
        from signalforge.db.session import session_scope
        from signalforge.settings_store import effective_research_config

        with session_scope() as session:
            cfg = effective_research_config(session)
            if not cfg.execution.enabled:
                return []
            limits = load_active_limits(session)
        cadence_s = limits.cycle_interval_s if limits is not None else 60
    except Exception as exc:  # pragma: no cover - DB unavailable at startup
        get_logger("execution.cycle").warning(
            "execution_cycle.spec_unavailable", error=repr(exc)[:160]
        )
        return []

    # APScheduler's interval trigger here is in MINUTES (JobSpec's unit). A
    # sub-minute cadence is expressed as 1 and the cycle's own freshness checks
    # do the rest; the grid centre is 30s and Q6 reframes the cadence against the
    # broker's documented rate limit before I-E5, which no call has verified.
    minutes = max(1, round(cadence_s / 60))
    return [
        JobSpec(
            EXECUTION_CYCLE_JOB,
            execution_cycle_job(adapter=adapter, adapter_factory=adapter_factory),
            minutes,
            "Execution cycle: dead-man heartbeat, reconciliation, auto-disarm, protective "
            "drain (registered only while execution.enabled is True; nothing is armed by "
            "default)",
            self_guarded=True,
        )
    ]


def manual_job_entries(
    *,
    adapter: BrokerAdapter | None = None,
    adapter_factory: AdapterFactory | None = None,
) -> dict[str, Callable[[], None]]:
    """The manual-job table for ``signalforge run-job``.

    Runnable by hand even while ``execution.enabled`` is False — it is then a
    cycle that finds nothing armed and says so, which is the point: the operator
    can prove what it would do without enabling anything.
    """
    return {
        EXECUTION_CYCLE_JOB: execution_cycle_job(
            adapter=adapter, adapter_factory=adapter_factory, actor="cli"
        )
    }
