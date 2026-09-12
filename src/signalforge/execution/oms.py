"""The OMS state machine and the kill-switch branch, persisted (D6 §6, §8).

What is here: the durable state transitions, the ``SUBMITTING``-with-no-outcome
promotion to ``UNKNOWN``, the two-part ``UNKNOWN`` resolution, the query
``may_open``'s I2 check reads, and — added in I-E4 — the §8 apparatus: the
execution-local kill state (K2), the submission lock, the bounded drain, and
``execution_guarded``, the cycle wrapper that **branches instead of returning**
so that engaging the kill switch cannot stop the protective path.

What is deliberately NOT here, and not anywhere in this package yet:

* no adapter call of any kind — no ``place``, no ``cancel``, no network. The
  first adapter (``brokers/paper_reference.py``, local and deterministic) is
  I-E3 and is built on its own branch; nothing in I-E4 depends on it, and the
  cycle runs its whole local half with no adapter at all.

The SQLite discipline this module exists to make possible (§2, §8): the
``SUBMITTING`` record is written and **committed** BEFORE the network call, with
write intent then released, so the in-flight set is durable across a crash and
no transaction is ever held open across a broker round trip — on the same file
the live probation worker uses.
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

from signalforge.execution.events import ExecutionEventType, record_execution_event
from signalforge.execution.intents import ComboOrderIntent, IntentKind, OrderIntent
from signalforge.execution.states import (
    IllegalTransition,
    OrderState,
    UnknownResolution,
    is_terminal,
    next_state,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from sqlalchemy.orm import Session

    from signalforge.db.models import ExecutionEvent

__all__ = [
    "CycleBranch",
    "CyclePosture",
    "DrainResult",
    "ExecutionKillState",
    "SubmissionLock",
    "SubmissionsClosed",
    "assert_terminal",
    "current_state",
    "drain",
    "execution_guarded",
    "execution_kill_state_path",
    "has_outstanding_unknown",
    "in_flight_client_order_ids",
    "promote_stale_submitting",
    "read_cycle_posture",
    "read_execution_kill_state",
    "record_submitting",
    "refuse",
    "resolve_unknown",
    "transition",
    "write_execution_kill_state",
]

Intent = OrderIntent | ComboOrderIntent


def _event_type_for(state: OrderState) -> ExecutionEventType:
    return {
        OrderState.VALIDATED: ExecutionEventType.INTENT_VALIDATED,
        OrderState.SUBMITTING: ExecutionEventType.SUBMITTING,
        OrderState.FILLED: ExecutionEventType.FILL,
        OrderState.PARTIAL: ExecutionEventType.FILL,
        OrderState.REJECTED: ExecutionEventType.REJECTION,
        OrderState.CANCELLED: ExecutionEventType.CANCELLATION,
        OrderState.REFUSED: ExecutionEventType.INTENT_REFUSED,
        OrderState.UNKNOWN: ExecutionEventType.UNKNOWN_PROMOTED,
    }.get(state, ExecutionEventType.STATE_CHANGE)


def current_state(session: Session, client_order_id: str) -> OrderState | None:
    """The latest recorded state for an order id, or ``None`` if this OMS has
    never written one."""
    from sqlalchemy import select

    from signalforge.db.models import ExecutionEvent

    row = session.scalars(
        select(ExecutionEvent)
        .where(ExecutionEvent.client_order_id == client_order_id, ExecutionEvent.state_to != "")
        .order_by(ExecutionEvent.ts.desc(), ExecutionEvent.id.desc())
    ).first()
    if row is None:
        return None
    try:
        return OrderState(row.state_to)
    except ValueError:  # pragma: no cover - an unknown literal is not a state
        return None


def transition(
    session: Session,
    intent: Intent,
    target: OrderState,
    *,
    reason: str = "",
    resolution: UnknownResolution | None = None,
    raw_status_verbatim: str = "",
    error_verbatim: str = "",
    realized_fill_price: float | None = None,
    leg_index: int | None = None,
    actor: str = "system",
) -> Intent:
    """Move an intent to ``target``, writing the event, or raise.

    The legality table is ``execution.states`` and nothing here may bypass it —
    including the rule that an ``UNKNOWN`` is never cleared by a retry.
    """
    resolved = next_state(intent.state, target, resolution=resolution)
    record_execution_event(
        session,
        event_type=_event_type_for(resolved),
        adapter_name=intent.adapter_name,
        client_order_id=intent.client_order_id,
        intent_kind=intent.intent_kind.value,
        state_from=intent.state.value,
        state_to=resolved.value,
        reason=reason,
        source_paper_trade_id=intent.source_paper_trade_id,
        strategy_version_id=intent.strategy_version_id,
        armed_strategy_id=intent.armed_strategy_id,
        execution_limits_id=intent.execution_limits_id,
        config_hash=intent.config_hash,
        spec_json_hash=intent.spec_json_hash,
        raw_status_verbatim=raw_status_verbatim,
        error_verbatim=error_verbatim,
        modelled_fill_price=intent.cost_model.modelled_fill_price,
        modelled_spread_bps=intent.cost_model.modelled_spread_bps,
        realized_fill_price=realized_fill_price,
        leg_index=leg_index,
        actor=actor,
    )
    return intent.with_state(resolved)


def record_submitting(session: Session, intent: Intent, *, actor: str = "system") -> Intent:
    """Write and COMMIT the ``SUBMITTING`` record before any network call (§8).

    The commit is the point: the in-flight set is durable, not in memory, so a
    process killed between this line and the broker's response leaves a record
    the next cycle promotes to ``UNKNOWN`` rather than silently losing an order
    that may have reached the broker. The write intent is released afterwards so
    no SQLite write lock is held across the round trip.
    """
    from signalforge.db.session import set_write_intent

    moved = transition(
        session, intent, OrderState.SUBMITTING, reason="durable pre-submit record", actor=actor
    )
    session.commit()
    # Releasing write intent is best-effort: the durable record is already
    # committed, and a caller that left a transaction open must not turn that
    # into a lost submission record.
    with contextlib.suppress(RuntimeError):
        set_write_intent(session, False)
    return moved


def promote_stale_submitting(
    session: Session, *, now: datetime, adapter_name: str | None = None, actor: str = "system"
) -> list[str]:
    """Promote every ``SUBMITTING`` record with no terminal outcome to
    ``UNKNOWN`` (§6 rule 3) and return their ``client_order_id``s.

    Runs at the start of any cycle, **including the first cycle after a process
    restart**. A ``SUBMITTING`` with no outcome is NEVER assumed to have failed:
    the order may well have reached the broker, which is the entire reason this
    state exists.
    """
    from sqlalchemy import select

    from signalforge.db.models import ExecutionEvent

    stmt = select(ExecutionEvent.client_order_id).where(ExecutionEvent.client_order_id != "")
    if adapter_name is not None:
        stmt = stmt.where(ExecutionEvent.adapter_name == adapter_name)
    ids = sorted({cid for cid in session.scalars(stmt) if cid})

    promoted: list[str] = []
    for cid in ids:
        state = current_state(session, cid)
        if state is not OrderState.SUBMITTING:
            continue
        last = _last_event(session, cid)
        record_execution_event(
            session,
            event_type=ExecutionEventType.UNKNOWN_PROMOTED,
            adapter_name=last.adapter_name if last else (adapter_name or ""),
            client_order_id=cid,
            intent_kind=last.intent_kind if last else "",
            state_from=OrderState.SUBMITTING.value,
            state_to=OrderState.UNKNOWN.value,
            reason=(
                "a SUBMITTING record with no terminal outcome is UNKNOWN, never assumed failed; "
                f"observed at {now.isoformat()}"
            ),
            strategy_version_id=last.strategy_version_id if last else None,
            armed_strategy_id=last.armed_strategy_id if last else None,
            execution_limits_id=last.execution_limits_id if last else None,
            config_hash=last.config_hash if last else "",
            spec_json_hash=last.spec_json_hash if last else "",
            actor=actor,
        )
        promoted.append(cid)
    return promoted


def _last_event(session: Session, client_order_id: str) -> ExecutionEvent | None:
    from sqlalchemy import select

    from signalforge.db.models import ExecutionEvent

    return session.scalars(
        select(ExecutionEvent)
        .where(ExecutionEvent.client_order_id == client_order_id)
        .order_by(ExecutionEvent.ts.desc(), ExecutionEvent.id.desc())
    ).first()


def has_outstanding_unknown(session: Session, strategy_version_id: int) -> bool:
    """I2 / §12 step 7 — an outstanding ``UNKNOWN`` blocks every further
    ``may_open`` for this strategy AND blocks arming it. It does not block any
    close."""
    from sqlalchemy import select

    from signalforge.db.models import ExecutionEvent

    ids = sorted(
        {
            cid
            for cid in session.scalars(
                select(ExecutionEvent.client_order_id).where(
                    ExecutionEvent.strategy_version_id == strategy_version_id,
                    ExecutionEvent.client_order_id != "",
                )
            )
            if cid
        }
    )
    return any(current_state(session, cid) is OrderState.UNKNOWN for cid in ids)


def resolve_unknown(
    session: Session,
    client_order_id: str,
    *,
    resolution: UnknownResolution,
    actor: str,
) -> OrderState:
    """Clear an ``UNKNOWN`` — the ONLY way, and it requires both halves (§6
    rule 2): reconciliation resolving the id to a terminal broker state via
    ``order_status()``, AND an explicit operator acknowledgement.

    It requires no manual DB write, which is the point: rev 1's design could
    enter a state it could not leave without editing the database by hand, and
    the append-only discipline forbids that.
    """
    state = current_state(session, client_order_id)
    if state is not OrderState.UNKNOWN:
        raise IllegalTransition(
            state or OrderState.CREATED,
            resolution.broker_terminal_state,
            f"{client_order_id} is not in UNKNOWN",
        )
    target = next_state(OrderState.UNKNOWN, resolution.broker_terminal_state, resolution=resolution)
    last = _last_event(session, client_order_id)
    record_execution_event(
        session,
        event_type=ExecutionEventType.UNKNOWN_RESOLVED,
        adapter_name=last.adapter_name if last else "",
        client_order_id=client_order_id,
        intent_kind=last.intent_kind if last else "",
        state_from=OrderState.UNKNOWN.value,
        state_to=target.value,
        reason=(
            f"resolved by order_status() reconciliation and an operator acknowledgement "
            f"({resolution.acknowledged_by or actor}): {resolution.note}"
        ),
        strategy_version_id=last.strategy_version_id if last else None,
        armed_strategy_id=last.armed_strategy_id if last else None,
        execution_limits_id=last.execution_limits_id if last else None,
        config_hash=last.config_hash if last else "",
        spec_json_hash=last.spec_json_hash if last else "",
        actor=actor,
    )
    return target


def refuse(
    session: Session,
    *,
    adapter_name: str,
    reason: str,
    intent_kind: IntentKind = IntentKind.OPEN,
    client_order_id: str = "",
    source_paper_trade_id: int | None = None,
    strategy_version_id: int | None = None,
    actor: str = "system",
) -> None:
    """Record a refusal that never produced an intent object at all.

    Every ``may_open`` failure is written, not only the ones that happen to
    reach a constructed intent — otherwise the record of what the system
    refused would be shaped by where the refusal happened to occur.
    """
    record_execution_event(
        session,
        event_type=ExecutionEventType.INTENT_REFUSED,
        adapter_name=adapter_name,
        client_order_id=client_order_id,
        intent_kind=intent_kind.value,
        state_to=OrderState.REFUSED.value,
        reason=reason,
        source_paper_trade_id=source_paper_trade_id,
        strategy_version_id=strategy_version_id,
        actor=actor,
    )


def assert_terminal(state: OrderState) -> None:
    if not is_terminal(state):
        raise IllegalTransition(state, state, "expected a terminal state")


# ---------------------------------------------------------------------------
# §8 — the execution-local kill state (K2), the submission lock, the drain
# ---------------------------------------------------------------------------
#
# FACT: ``killswitch.py`` is deliberately fail-OPEN — its own docstring says a
# missing state file means *not engaged*, and an unreadable or corrupt file is
# ALSO treated as not engaged but logged at ERROR, "because silently freezing a
# research tool on a parse glitch is worse than the operator re-engaging
# explicitly". That is right for a research tool and wrong for order submission.
#
# It is not changed. There are 39 ``ensure_not_engaged()`` call sites and
# flipping fail-open to fail-closed would silently alter all of them. Instead a
# SEPARATE, execution-only kill state is added whose unreadable/corrupt case
# BLOCKS. Nothing else reads it. Missing evidence of safety is not evidence of
# safety — but a MISSING file is not an unreadable one: a fresh install has
# simply never engaged it, which is what ``killswitch.py`` means by a missing
# file too, and §8 names the unreadable/corrupt case specifically.


@dataclass(frozen=True, slots=True)
class ExecutionKillState:
    """K2. ``engaged`` is what the gate reads; ``readable`` is why.

    An unreadable state reports ``engaged=True`` AND ``readable=False``, so the
    audit line can distinguish "the operator engaged it" from "we could not tell
    and therefore refused to open". Both block opening. Neither blocks closing.
    """

    engaged: bool
    readable: bool
    reason: str = ""
    actor: str = ""
    changed_at: datetime | None = None
    path: str = ""


def execution_kill_state_path() -> Path:
    from signalforge.config import paths

    return paths.data_dir() / "execution_kill_state.json"


def read_execution_kill_state(path: Path | None = None) -> ExecutionKillState:
    """Read K2, fail-CLOSED on anything that is not a clean parse."""
    import json

    target = path or execution_kill_state_path()
    try:
        raw = target.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ExecutionKillState(
            engaged=False,
            readable=True,
            reason="no execution kill state has ever been written",
            path=str(target),
        )
    except OSError as exc:
        return ExecutionKillState(
            engaged=True,
            readable=False,
            reason=f"the execution kill state could not be read ({exc}) — opening blocked",
            path=str(target),
        )
    try:
        data = json.loads(raw)
        return ExecutionKillState(
            engaged=bool(data["engaged"]),
            readable=True,
            reason=str(data.get("reason", "")),
            actor=str(data.get("actor", "")),
            changed_at=(
                datetime.fromisoformat(data["changed_at"]) if data.get("changed_at") else None
            ),
            path=str(target),
        )
    except (ValueError, KeyError, TypeError) as exc:
        return ExecutionKillState(
            engaged=True,
            readable=False,
            reason=f"the execution kill state is corrupt ({exc}) — opening blocked",
            path=str(target),
        )


def write_execution_kill_state(
    *, engaged: bool, reason: str, actor: str, now: datetime, path: Path | None = None
) -> ExecutionKillState:
    """Engage or release K2. Atomic replace, in the shape ``killswitch.py`` uses."""
    import json
    import os
    import tempfile

    target = path or execution_kill_state_path()
    payload = {
        "engaged": engaged,
        "reason": reason,
        "actor": actor,
        "changed_at": now.isoformat(),
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=target.parent, prefix=".exk-", suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, indent=2) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        tmp.replace(target)
    finally:
        tmp.unlink(missing_ok=True)
    return ExecutionKillState(
        engaged=engaged, readable=True, reason=reason, actor=actor, changed_at=now, path=str(target)
    )


class SubmissionsClosed(RuntimeError):
    """No new submission may be admitted: a drain is in progress or has run."""


class SubmissionLock:
    """§8's "stop admitting new submissions" half of the drain sequence.

    The race this closes: the limit checks and the network ``place()`` are
    separate steps with a network call between them, so an order submitted
    microseconds before an engage will not appear in the broker's order list when
    ``cancel_all()`` runs. The durable half of the answer is the committed
    ``SUBMITTING`` record (:func:`record_submitting`); this is the in-process
    half — once admissions are closed nothing new is started, and what is already
    in flight is waited for, bounded.

    Process-local by design. The durable in-flight set lives in
    ``execution_event`` and survives a crash; this object governs only the
    submissions THIS process is about to start, and one worker per DB is the
    standing rule.
    """

    def __init__(self) -> None:
        self._admitting = True
        self._reason = ""

    @property
    def admitting(self) -> bool:
        return self._admitting

    @property
    def reason(self) -> str:
        return self._reason

    def close(self, reason: str) -> None:
        self._admitting = False
        self._reason = reason

    def reopen(self, reason: str = "") -> None:
        """Only a fresh cycle that observed a clean posture reopens admissions."""
        self._admitting = True
        self._reason = reason

    def admit(self) -> None:
        """Raise unless a new submission may be started right now."""
        if not self._admitting:
            raise SubmissionsClosed(
                f"submissions are closed: {self._reason or 'a drain is in progress'}"
            )


def in_flight_client_order_ids(session: Session, *, adapter_name: str | None = None) -> list[str]:
    """The DURABLE in-flight set: every order whose latest recorded state is
    ``SUBMITTING``. Not an in-memory set — a process killed between the commit
    and the broker's response must leave this visible to the next cycle."""
    from sqlalchemy import select

    from signalforge.db.models import ExecutionEvent

    stmt = select(ExecutionEvent.client_order_id).where(ExecutionEvent.client_order_id != "")
    if adapter_name is not None:
        stmt = stmt.where(ExecutionEvent.adapter_name == adapter_name)
    ids = sorted({cid for cid in session.scalars(stmt) if cid})
    return [cid for cid in ids if current_state(session, cid) is OrderState.SUBMITTING]


@dataclass(frozen=True, slots=True)
class DrainResult:
    drained: tuple[str, ...]
    timed_out: tuple[str, ...]
    waited_s: float
    detail: str


def drain(
    session: Session,
    *,
    adapter_name: str,
    timeout_s: float,
    now: datetime,
    monotonic: Callable[[], float] | None = None,
    sleep: Callable[[float], None] | None = None,
    poll_interval_s: float = 0.5,
    actor: str = "system",
) -> DrainResult:
    """§8 step 3: wait, BOUNDED, for the in-flight set to drain.

    On timeout the undrained entries become ``UNKNOWN`` — never "assumed
    failed", because the order may well have reached the broker, which is the
    entire reason that state exists. ``monotonic``/``sleep`` are injected so the
    bound is testable without spending it.

    The timeout is ``execution_limits.drain_timeout_s`` (grid centre 30s, §7b).
    Too short manufactures ``UNKNOWN``s; too long delays the kill switch. That is
    D6 open question Q7, and the answer is a pre-registered number rather than
    one chosen after seeing which drains were slow.
    """
    import time as _time

    clock = monotonic or _time.monotonic
    nap = sleep if sleep is not None else _time.sleep
    started = clock()
    outstanding = in_flight_client_order_ids(session, adapter_name=adapter_name)
    drained: list[str] = []
    while outstanding and (clock() - started) < timeout_s:
        nap(poll_interval_s)
        still = set(in_flight_client_order_ids(session, adapter_name=adapter_name))
        drained.extend(cid for cid in outstanding if cid not in still)
        outstanding = [cid for cid in outstanding if cid in still]
    waited = clock() - started
    if outstanding:
        promote_stale_submitting(session, now=now, adapter_name=adapter_name, actor=actor)
    return DrainResult(
        drained=tuple(drained),
        timed_out=tuple(outstanding),
        waited_s=waited,
        detail=(
            f"{len(drained)} drained, {len(outstanding)} promoted to UNKNOWN after "
            f"{waited:.1f}s (bound {timeout_s:.0f}s)"
        ),
    )


# ---------------------------------------------------------------------------
# §2 / §8 — execution_guarded: the cycle wrapper that BRANCHES, never returns
# ---------------------------------------------------------------------------
#
# FACT (the defect this corrects): ``scheduler.guarded`` calls
# ``ensure_not_engaged()`` and, on ``KillSwitchEngaged``, logs, records a
# "skipped" ``JobRun``, and RETURNS — the job body never runs. If the execution
# cycle were registered through it then, with the kill switch engaged: §8's
# drain -> cancel_all -> reconcile sequence would never run, §7's may_close
# protective close could never be submitted by the system, §9's dead-man
# heartbeat would stop (so the dead man would lapse as a SIDE EFFECT of engaging
# the kill switch), and reconciliation would age past max_reconciliation_age_s.
#
# The kill switch would, in fact, block closing. So this wrapper reads the same
# state and BRANCHES instead.


class CycleBranch(StrEnum):
    FULL = "full"
    PROTECTIVE = "protective"


@dataclass(frozen=True, slots=True)
class CyclePosture:
    """What the cycle body is permitted to do, decided before it starts.

    ``may_open`` is False in the protective branch **by construction, not by a
    flag the body could ignore**: the protective branch takes a different code
    path with no opening step in it at all. This object records the decision for
    the audit line; it is not the enforcement.
    """

    branch: CycleBranch
    may_open: bool
    may_close: bool
    kill_switch_engaged: bool | None
    execution_kill: ExecutionKillState
    detail: str


def read_cycle_posture(*, kill_state_path: Path | None = None) -> CyclePosture:
    """K1 + K2, read at the TOP of every cycle — the only observation point.

    FACT: ``KillSwitch.state()`` is an on-demand JSON file read, engaged from a
    different process, and there is no watcher, no signal and no callback
    anywhere in the repo. The OMS cannot be told; it can only look. The poll
    interval is ``execution_limits.cycle_interval_s`` (grid centre 30s), so the
    worst case between an engage and ``cancel_all()`` is cycle_interval_s +
    drain_timeout_s + one reconciliation round trip ~= 60-70s at the grid
    centres. If the worker is NOT running, nothing happens at the broker at all —
    which is why that is arming acknowledgement (iv).
    """
    from signalforge.killswitch import get_kill_switch

    try:
        k1_engaged: bool | None = get_kill_switch().state().active
    except Exception as exc:  # pragma: no cover - state() is total by design
        k1_engaged = None
        k1_detail = f"the kill switch could not be read ({type(exc).__name__}: {exc})"
    else:
        k1_detail = f"kill switch engaged={k1_engaged}"

    k2 = read_execution_kill_state(kill_state_path)
    protective = bool(k1_engaged) or k1_engaged is None or k2.engaged
    return CyclePosture(
        branch=CycleBranch.PROTECTIVE if protective else CycleBranch.FULL,
        may_open=not protective,
        # The one promise this layer makes above all others.
        may_close=True,
        kill_switch_engaged=k1_engaged,
        execution_kill=k2,
        detail=f"{k1_detail}; K2 {k2.reason or 'not engaged'}",
    )


def execution_guarded(
    name: str,
    fn: Callable[[CyclePosture], str],
    *,
    kill_state_path: Path | None = None,
) -> Callable[[], None]:
    """Wrap the execution cycle. **This is NOT ``scheduler.guarded``.**

    It records a ``JobRun`` row of the same shape so the Operational Status page
    still sees the job, reads K1 and K2 itself, and **branches** rather than
    returning:

    * not engaged -> the full cycle (heartbeat, reconcile, calendar, limits,
      open, close);
    * engaged, or K2 unreadable -> a protective-only cycle: heartbeat ->
      reconcile -> bounded drain -> ``cancel_all()`` -> reconcile again ->
      ``may_close`` only. No ``may_open`` path is reachable in that branch, by
      construction, not by a flag.

    The branch is never swallowed: the ``JobRun`` note records which one ran, and
    a ``CYCLE_PROTECTIVE`` ``execution_event`` is written whenever the protective
    branch runs.

    No job-level ``retry_on_lock``: the cycle persists per-unit records (events,
    disarms, reconciliations) and re-running the whole body would duplicate the
    ones already written — the same reason ``scheduler.NO_JOB_LEVEL_LOCK_RETRY``
    exists. Lock contention is retried per write, inside.
    """
    from signalforge.observability import get_logger

    log = get_logger("execution.cycle")

    def _run() -> None:
        started = datetime.now(UTC)
        posture = read_cycle_posture(kill_state_path=kill_state_path)
        log.info("execution_cycle.start", job=name, branch=posture.branch.value)
        try:
            note = fn(posture)
        except Exception as exc:
            log.exception("execution_cycle.failed", job=name, branch=posture.branch.value)
            _record_cycle_job_run(name, started, "failed", f"[{posture.branch.value}] {exc!r}")
            raise
        _record_cycle_job_run(name, started, "ok", f"[{posture.branch.value}] {note}")
        log.info("execution_cycle.done", job=name, branch=posture.branch.value)

    return _run


def _record_cycle_job_run(name: str, started: datetime, status: str, detail: str) -> None:
    """One ``JobRun`` row, the same shape as the scheduler's. Best-effort: a DB
    problem here must never mask the cycle's own outcome."""
    from signalforge.observability import get_logger

    try:
        from signalforge.db.models import JobRun
        from signalforge.db.retry import retry_on_lock
        from signalforge.db.session import session_scope

        def _write() -> None:
            with session_scope(write=True) as session:
                session.add(
                    JobRun(
                        name=name,
                        started_at=started,
                        finished_at=datetime.now(UTC),
                        status=status,
                        detail=detail[:300],
                    )
                )

        retry_on_lock(_write, attempts=4, backoff_s=(0.2, 0.5, 1.0), label="execution_job_run")
    except Exception as exc:  # pragma: no cover - never masks the cycle outcome
        get_logger("execution.cycle").warning(
            "execution_cycle.job_run_record_failed", job=name, error=repr(exc)[:160]
        )
