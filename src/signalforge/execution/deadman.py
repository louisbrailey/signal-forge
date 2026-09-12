"""The execution dead man — the deliberate INVERSE of the kill switch (D6 §9).

``killswitch.py`` is fail-OPEN by design and says so in its own docstring: a
missing or corrupt state file means *not engaged*, because silently freezing a
research tool on a parse glitch is worse than the operator re-engaging. That is
right for a research tool and wrong for order submission, so the dead man is
built the other way round and the kill switch is left untouched.

**Missing evidence of health is evidence of ill health.** A heartbeat older than
``execution_stale_after_s``, unreadable, ambiguous, or absent entirely, means the
dead man has LAPSED: opening is blocked, the §8 drain-and-cancel sequence runs,
and every live arming is auto-disarmed. It does **not** auto-liquidate — an
automatic liquidation is an unreviewed order, which §10 forbids — so the
operator must close any open position by hand at the broker, which is what the
arming ceremony's acknowledgement (ii) says in those words.

The lapse does **not** make a protective close unconstructible: ``may_close``
stays open, and ``build_close_intent`` requires no armed row (§5.2b). That is
the whole point of feeding the dead man from the top of **every** cycle
*including the protective-only branch* — otherwise engaging the kill switch
would lapse the dead man as a side effect, and the lapse would then disarm and
block, which is the system attacking itself during an incident.

FACT (the pattern this copies rather than invents): ``WorkerHeartbeat``
(``db/models/system.py``) is one upserted row per worker with ``last_beat_at``
indexed, and ``scheduler.WORKER_STALE_AFTER_S`` is ``3 * HEARTBEAT_INTERVAL_S``.
The execution dead man is a row in that same table under its own worker name, so
it needs no migration and shows up on the Operational Status page beside the
research worker's own liveness.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    from sqlalchemy.orm import Session

__all__ = [
    "DEAD_MAN_WORKER",
    "DeadManState",
    "assess",
    "feed",
    "min_stale_after_s",
]

#: The ``WorkerHeartbeat.worker`` value the execution cycle beats under. Distinct
#: from ``scheduler.WORKER_NAME`` ("scheduler"): the research worker being alive
#: is not evidence that the execution cycle ran, and conflating the two would let
#: a live scheduler mask a dead OMS.
DEAD_MAN_WORKER = "execution"


def min_stale_after_s(cycle_interval_s: int) -> int:
    """``3 x cycle_interval_s`` — the dead man must tolerate two missed cycles.

    ``LimitSet.__post_init__`` refuses a row that violates this, so the two
    numbers cannot be set into contradiction (§7b). Exposed here so the
    constraint is stated where the dead man is, not only where limits are.
    """
    return 3 * cycle_interval_s


@dataclass(frozen=True, slots=True)
class DeadManState:
    """The verdict, with the evidence that produced it.

    ``alive`` is the ONLY field a gate should branch on, and it is ``False``
    whenever the state could not be established. ``age_s`` is ``None`` in
    exactly that case, which is why ``OpenGateContext.dead_man_alive`` is fed
    from ``alive`` rather than from an age comparison at the call site.
    """

    alive: bool
    age_s: float | None
    last_beat_at: datetime | None
    stale_after_s: int
    detail: str

    @property
    def lapsed(self) -> bool:
        return not self.alive


def feed(
    session: Session,
    *,
    now: datetime,
    detail: str = "",
    worker: str = DEAD_MAN_WORKER,
) -> DeadManState:
    """Write the execution heartbeat. Called at the top of EVERY cycle.

    Including the protective-only branch: if the protective branch did not feed
    the dead man, engaging the kill switch would lapse it, the lapse would run
    the drain sequence and auto-disarm, and the operator would be debugging a
    self-inflicted cascade during the incident they engaged the switch for.

    The caller owns the transaction. This is a small upsert on a table the
    scheduler already writes every 30s; it never spans a network call.
    """
    import os
    import platform

    from sqlalchemy import select

    from signalforge.db.models import WorkerHeartbeat

    row = session.scalar(select(WorkerHeartbeat).where(WorkerHeartbeat.worker == worker))
    if row is None:
        row = WorkerHeartbeat(worker=worker, started_at=now, last_beat_at=now)
        session.add(row)
    # platform.node(), not socket.gethostname(): the execution package imports no
    # socket module anywhere, and a test asserts that. The two return the same
    # thing on every platform this runs on.
    row.host = platform.node()[:120]
    row.pid = os.getpid()
    row.last_beat_at = now
    row.detail = detail[:300]
    session.flush()
    return DeadManState(
        alive=True,
        age_s=0.0,
        last_beat_at=now,
        stale_after_s=0,
        detail=f"fed at {now.isoformat()}",
    )


def assess(
    session: Session,
    *,
    now: datetime,
    stale_after_s: int,
    worker: str = DEAD_MAN_WORKER,
) -> DeadManState:
    """Evaluate the dead man, fail-CLOSED in every direction.

    Four ways to be lapsed, and all four are the same verdict:

    * no heartbeat row at all — the cycle has never run, so nothing is proven;
    * a heartbeat older than ``stale_after_s``;
    * a heartbeat in the FUTURE by more than one stale window — an ambiguous
      clock is not evidence of health (a clock that jumped backwards would
      otherwise make a stale beat look fresh forever);
    * any exception reading it.
    """
    from sqlalchemy import select

    from signalforge.db.models import WorkerHeartbeat

    if stale_after_s <= 0:
        return DeadManState(
            alive=False,
            age_s=None,
            last_beat_at=None,
            stale_after_s=stale_after_s,
            detail=f"execution_stale_after_s={stale_after_s} is not a window",
        )
    try:
        row = session.scalar(select(WorkerHeartbeat).where(WorkerHeartbeat.worker == worker))
    except Exception as exc:  # pragma: no cover - a DB failure is still a lapse
        return DeadManState(
            alive=False,
            age_s=None,
            last_beat_at=None,
            stale_after_s=stale_after_s,
            detail=f"the heartbeat could not be read ({type(exc).__name__}: {exc})",
        )
    if row is None or row.last_beat_at is None:
        return DeadManState(
            alive=False,
            age_s=None,
            last_beat_at=None,
            stale_after_s=stale_after_s,
            detail=(
                f"no {worker!r} heartbeat row exists — the execution cycle has never run, "
                "which is not evidence that it is healthy"
            ),
        )
    age_s = (now - row.last_beat_at).total_seconds()
    if age_s < -float(stale_after_s):
        return DeadManState(
            alive=False,
            age_s=age_s,
            last_beat_at=row.last_beat_at,
            stale_after_s=stale_after_s,
            detail=(
                f"the heartbeat is {abs(age_s):.0f}s in the FUTURE — an ambiguous clock is "
                "not evidence of health"
            ),
        )
    if age_s > stale_after_s:
        return DeadManState(
            alive=False,
            age_s=age_s,
            last_beat_at=row.last_beat_at,
            stale_after_s=stale_after_s,
            detail=(
                f"the execution heartbeat is {age_s:.0f}s old > {stale_after_s}s — opening is "
                "blocked and every live arming is disarmed; closing is NOT blocked, and nothing "
                "is auto-liquidated (the operator closes by hand, at the broker)"
            ),
        )
    return DeadManState(
        alive=True,
        age_s=age_s,
        last_beat_at=row.last_beat_at,
        stale_after_s=stale_after_s,
        detail=f"heartbeat {age_s:.0f}s old (window {stale_after_s}s)",
    )
