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
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from signalforge.execution import arming, calendarcheck, deadman
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

    from signalforge.execution.protocol import BrokerAdapter
    from signalforge.jobspec import JobSpec

__all__ = [
    "EXECUTION_CYCLE_JOB",
    "CycleReport",
    "active_limits_created_at",
    "execution_cycle_job",
    "execution_job_specs",
    "run_execution_cycle",
]

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
    report.may_open_possible = bool(
        remaining
        and posture.may_open
        and state.alive
        and recon is not None
        and recon.clean
        and not verdict.blocks_opening
        and limits is not None
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

    report.detail = report.note()
    return report


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
    *, adapter: BrokerAdapter | None = None, actor: str = "scheduler"
) -> Callable[[], None]:
    """The registered job: ``execution_guarded`` wrapping one database-scoped
    cycle. Returns a zero-argument callable, which is what a ``JobSpec`` holds.
    """

    def _body(posture: CyclePosture) -> str:
        from signalforge.db.session import session_scope

        with session_scope(write=True) as session:
            report = run_execution_cycle(session, posture, adapter=adapter, actor=actor)
        return report.note()

    return execution_guarded(EXECUTION_CYCLE_JOB, _body)


def execution_job_specs(*, adapter: BrokerAdapter | None = None) -> list[JobSpec]:
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
            execution_cycle_job(adapter=adapter),
            minutes,
            "Execution cycle: dead-man heartbeat, reconciliation, auto-disarm, protective "
            "drain (registered only while execution.enabled is True; nothing is armed by "
            "default)",
            self_guarded=True,
        )
    ]


def manual_job_entries(*, adapter: BrokerAdapter | None = None) -> dict[str, Callable[[], None]]:
    """The manual-job table for ``signalforge run-job``.

    Runnable by hand even while ``execution.enabled`` is False — it is then a
    cycle that finds nothing armed and says so, which is the point: the operator
    can prove what it would do without enabling anything.
    """
    return {EXECUTION_CYCLE_JOB: execution_cycle_job(adapter=adapter, actor="cli")}
