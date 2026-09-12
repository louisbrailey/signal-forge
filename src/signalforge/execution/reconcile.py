"""Reconciliation — broker truth against local truth (D6 §10).

Every cycle, ``adapter.positions()`` and ``adapter.open_orders()`` are compared
against local ``execution_event``-derived state. Any divergence **halts opening,
disarms, alerts, and requires operator acknowledgement. It is NEVER
auto-corrected**: an automatic reconciliation fix is an unreviewed order, and an
unreviewed order is the one thing this layer exists to prevent.

Four rules beyond "compare once a cycle", each closing a specific hole:

* **Maximum age.** "Clean as of the last cycle" is a stale-state check. Between
  cycles the broker side can diverge on its own — a manual trade in the same
  account, a broker-initiated liquidation, an assignment. An unreconciled window
  older than ``max_reconciliation_age_s`` blocks exactly like a dead-man lapse.
* **No shared account, DETECTED rather than assumed.** Any position or open order
  the OMS did not originate — no matching ``client_order_id`` in
  ``execution_event`` — is a divergence and halts. An acknowledgement is not
  enough, because the operator would have acknowledged a sentence rather than
  been stopped by a check.
* **Buying power is reconciled, never modelled authoritatively.** The local
  collateral model is a model; the broker's own figure is authoritative, and
  divergence beyond the pre-registered tolerance halts. The binding tolerance is
  the TIGHTER of ``min(tolerance_usd, tolerance_pct x buying power)``. Zero is
  not an option — it halts on rounding.
* **Assignment shows up here first.** A position the OMS did not open, appearing
  after an expiry-adjacent session, is the live signature of an early assignment
  — the exact tail the backtest approximates away. It halts as a divergence,
  which is correct: the system must not trade on in a book it does not
  understand.

``expected_account_id_for`` implements §13 rule 4b and §6 rule 5a: it reads the
most recent ``armed_strategy`` row for an adapter **including disarmed and
expired rows**. Disarming ends the authority to open; it does not erase the
record of which account this adapter was pointed at, and the reconciliation that
clears an ``UNKNOWN`` runs *after* an auto-disarm by construction. Without this
rule the system can enter a state it cannot leave without editing the database
by hand, which the append-only discipline forbids.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from signalforge.execution.events import ExecutionEventType, record_execution_event

if TYPE_CHECKING:  # pragma: no cover - typing only
    from sqlalchemy.orm import Session

    from signalforge.execution.limits import LimitSet
    from signalforge.execution.protocol import BrokerAdapter

__all__ = [
    "Divergence",
    "ReconciliationResult",
    "ReconciliationStatus",
    "binding_buying_power_tolerance",
    "expected_account_id_for",
    "last_clean_reconciliation_age_s",
    "reconcile",
]


class ReconciliationStatus(StrEnum):
    CLEAN = "CLEAN"
    #: The broker's book contains something local state cannot explain, or the
    #: buying-power figures disagree beyond tolerance. Blocks opening AND blocks
    #: closing (closing into an unknown book is not protective, §7 C-P5).
    DIVERGED = "DIVERGED"
    #: The adapter could not be reached at all. Blocks opening; blocks closing
    #: too, because there is nothing to close against.
    UNREACHABLE = "UNREACHABLE"


@dataclass(frozen=True, slots=True)
class Divergence:
    kind: str
    detail: str


@dataclass(frozen=True, slots=True)
class ReconciliationResult:
    adapter_name: str
    status: ReconciliationStatus
    checked_at: datetime
    divergences: tuple[Divergence, ...] = ()
    known_positions: int = 0
    known_open_orders: int = 0
    broker_buying_power: float | None = None
    local_buying_power: float | None = None
    observed_account_id: str = ""
    detail: str = ""

    @property
    def clean(self) -> bool:
        return self.status is ReconciliationStatus.CLEAN

    @property
    def diverged(self) -> bool:
        return self.status is ReconciliationStatus.DIVERGED

    @property
    def adapter_reachable(self) -> bool:
        return self.status is not ReconciliationStatus.UNREACHABLE

    @property
    def first_divergence(self) -> str:
        if not self.divergences:
            return ""
        return f"{self.divergences[0].kind}: {self.divergences[0].detail}"


def binding_buying_power_tolerance(
    *, tolerance_usd: float, tolerance_pct: float, buying_power: float | None
) -> float | None:
    """``min(usd, pct x buying power)`` — the TIGHTER of the two recorded forms.

    ``None`` buying power gives ``None``: an uncomputable tolerance is not a
    tolerance, and the caller must treat it as a divergence rather than as a
    pass. A tolerance of zero is refused at the ``execution_limits`` level, not
    here — zero halts on rounding, which is why both forms exist.
    """
    if buying_power is None:
        return None
    return min(tolerance_usd, (tolerance_pct / 100.0) * abs(buying_power))


def expected_account_id_for(
    session: Session, adapter_name: str, *, adapter_configured_account_id: str = ""
) -> str:
    """§13 rule 4b — the most recent ``armed_strategy`` row for this adapter,
    **including disarmed and expired rows**.

    The fallback order is exactly the ADR's and the last step is a refusal, not a
    default: if no row has ever existed for this adapter, the expected id comes
    from the adapter's own reviewed configuration, and failing that the caller
    **halts and alerts** rather than proceeding against an unproven account. An
    empty string is that refusal signal.
    """
    from sqlalchemy import select

    from signalforge.db.models import ArmedStrategy

    row = session.scalars(
        select(ArmedStrategy)
        .where(ArmedStrategy.adapter_name == adapter_name)
        .order_by(ArmedStrategy.armed_at.desc(), ArmedStrategy.id.desc())
    ).first()
    if row is not None and row.broker_account_id_expected:
        return row.broker_account_id_expected
    return adapter_configured_account_id


def last_clean_reconciliation_age_s(
    session: Session, *, adapter_name: str, now: datetime
) -> float | None:
    """Seconds since the last CLEAN reconciliation for this adapter, or ``None``.

    ``None`` blocks (R1 is tri-state), and so it must: "never reconciled" and
    "reconciled 3 seconds ago" are not the same fact and are never collapsed into
    one. Only ``RECONCILED`` events count — a ``RECONCILIATION_DIVERGED`` row is
    a reconciliation that *happened* and *failed*, and treating it as freshness
    would let a divergence reset the staleness clock.
    """
    from sqlalchemy import select

    from signalforge.db.models import ExecutionEvent

    ts = session.scalar(
        select(ExecutionEvent.ts)
        .where(
            ExecutionEvent.adapter_name == adapter_name,
            ExecutionEvent.event_type == ExecutionEventType.RECONCILED.value,
        )
        .order_by(ExecutionEvent.ts.desc(), ExecutionEvent.id.desc())
        .limit(1)
    )
    if ts is None:
        return None
    return (now - ts).total_seconds()


def _known_client_order_ids(session: Session, adapter_name: str) -> set[str]:
    from sqlalchemy import select

    from signalforge.db.models import ExecutionEvent

    return {
        cid
        for cid in session.scalars(
            select(ExecutionEvent.client_order_id).where(
                ExecutionEvent.adapter_name == adapter_name,
                ExecutionEvent.client_order_id != "",
            )
        )
        if cid
    }


def _position_origin(position: object) -> str:
    """The ``client_order_id`` an adapter attached to a position, or ``""``.

    Read defensively: a ``PositionSnapshot`` has no origin field (the broker does
    not owe us one), so an adapter that can supply it does, and one that cannot
    yields the empty string — which is a divergence, not a pass.
    """
    origin = getattr(position, "originating_client_order_id", "")
    return origin if isinstance(origin, str) else ""


def _position_label(position: object) -> str:
    legs = getattr(position, "legs", ()) or ()
    keys = [str(getattr(leg, "instrument_key", "?")) for leg in legs]
    return "+".join(keys) if keys else "<no legs>"


@dataclass
class _Collector:
    divergences: list[Divergence] = field(default_factory=list)

    def add(self, kind: str, detail: str) -> None:
        self.divergences.append(Divergence(kind=kind, detail=detail))


def reconcile(
    session: Session,
    adapter: BrokerAdapter,
    *,
    now: datetime,
    limits: LimitSet | None,
    local_buying_power: float | None = None,
    strategy_version_id: int | None = None,
    armed_strategy_id: int | None = None,
    actor: str = "system",
) -> ReconciliationResult:
    """Compare the broker's book against this OMS's own record, and write the
    result. **Never repairs anything.**

    Every exit writes an ``execution_event`` (``RECONCILED`` or
    ``RECONCILIATION_DIVERGED``) and therefore an audit line: a reconciliation
    whose result is not recorded is a reconciliation that did not happen, and
    R1's staleness check reads exactly those rows.
    """
    adapter_name = getattr(adapter, "name", "") or ""
    collector = _Collector()

    try:
        positions = list(adapter.positions())
        open_orders = list(adapter.open_orders())
        account = adapter.account()
    except Exception as exc:
        result = ReconciliationResult(
            adapter_name=adapter_name,
            status=ReconciliationStatus.UNREACHABLE,
            checked_at=now,
            detail=f"the adapter could not be reached ({type(exc).__name__}: {exc})",
        )
        _record(session, result, strategy_version_id, armed_strategy_id, actor)
        return result

    known = _known_client_order_ids(session, adapter_name)

    for position in positions:
        origin = _position_origin(position)
        if not origin or origin not in known:
            # A position this OMS never opened. After an expiry-adjacent session
            # this is the live signature of an early assignment — the exact tail
            # the backtest approximates away — and either way the system must not
            # trade on in a book it does not understand.
            collector.add(
                "FOREIGN_POSITION",
                f"the broker reports position {_position_label(position)} with "
                + (
                    f"originating client_order_id {origin!r}, which this OMS never wrote"
                    if origin
                    else "no originating client_order_id"
                )
                + " — not auto-corrected; opening halts and the arming is disarmed",
            )

    for order in open_orders:
        cid = getattr(order, "client_order_id", "") or ""
        if cid not in known:
            # §8's post-timeout rule 3, reached from the other direction: a broker
            # order id the local store has never seen is a divergence, not a retry.
            collector.add(
                "FOREIGN_ORDER",
                f"the broker reports open order {cid!r} with no local execution_event — "
                "a divergence, never a retry",
            )

    raw_bp = getattr(account, "buying_power", None)
    broker_bp: float | None
    try:
        broker_bp = None if raw_bp is None else float(raw_bp)
    except (TypeError, ValueError):
        broker_bp = None
    observed_account_id = getattr(account, "account_id", "") or ""
    if local_buying_power is None:
        # No local collateral claim was made this cycle, so there is nothing to
        # reconcile on this axis. "No limits row" still blocks OPENING — that is
        # may_open's L0 — but it is not, on its own, a divergence in the broker's
        # book, and conflating the two would make every adapter-only cycle look
        # like a halt.
        pass
    elif limits is None:
        collector.add(
            "NO_LIMITS_ROW",
            "no active, parseable execution_limits row — the buying-power tolerance is "
            "unknown, and an unknown tolerance is not a passed tolerance",
        )
    else:
        tolerance = binding_buying_power_tolerance(
            tolerance_usd=limits.buying_power_tolerance_usd,
            tolerance_pct=limits.buying_power_tolerance_pct,
            buying_power=broker_bp,
        )
        if tolerance is None:
            collector.add(
                "BUYING_POWER_UNREADABLE",
                "the broker reported no buying-power figure; the local collateral model is a "
                "model and is never authoritative",
            )
        elif broker_bp is None:
            collector.add(
                "BUYING_POWER_UNREADABLE",
                "the broker's buying-power figure was absent or unparseable",
            )
        elif abs(broker_bp - float(local_buying_power)) > tolerance:
            collector.add(
                "BUYING_POWER",
                f"broker buying power {broker_bp:.2f} differs from the local model "
                f"{float(local_buying_power):.2f} by more than the binding pre-registered "
                f"tolerance {tolerance:.2f}",
            )

    status = ReconciliationStatus.DIVERGED if collector.divergences else ReconciliationStatus.CLEAN
    result = ReconciliationResult(
        adapter_name=adapter_name,
        status=status,
        checked_at=now,
        divergences=tuple(collector.divergences),
        known_positions=len(positions),
        known_open_orders=len(open_orders),
        broker_buying_power=broker_bp,
        local_buying_power=local_buying_power,
        observed_account_id=observed_account_id,
        detail=(
            "; ".join(f"{d.kind}: {d.detail}" for d in collector.divergences)
            if collector.divergences
            else f"{len(positions)} positions, {len(open_orders)} open orders, all originated here"
        ),
    )
    _record(session, result, strategy_version_id, armed_strategy_id, actor)
    return result


def _record(
    session: Session,
    result: ReconciliationResult,
    strategy_version_id: int | None,
    armed_strategy_id: int | None,
    actor: str,
) -> None:
    record_execution_event(
        session,
        event_type=(
            ExecutionEventType.RECONCILED
            if result.status is ReconciliationStatus.CLEAN
            else ExecutionEventType.RECONCILIATION_DIVERGED
        ),
        adapter_name=result.adapter_name,
        reason=f"{result.status.value}: {result.detail}",
        strategy_version_id=strategy_version_id,
        armed_strategy_id=armed_strategy_id,
        payload={
            "status": result.status.value,
            "checked_at": result.checked_at.isoformat(),
            "positions": result.known_positions,
            "open_orders": result.known_open_orders,
            "broker_buying_power": result.broker_buying_power,
            "local_buying_power": result.local_buying_power,
            "divergences": [{"kind": d.kind, "detail": d.detail} for d in result.divergences],
        },
        actor=actor,
    )
