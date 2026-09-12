"""Automatic SIMULATED acceptance of options structures — a **sibling** of
``paper/auto_simulate.py``, which this module does not touch.

``paper/auto_simulate.py`` is byte-identical after this commit. That is the
strongest available guarantee that the live equity auto-simulation — running
since 2026-09-10 with its setting ON and a cap of 2/day — is unaffected by the
options work. This module **copies** its five structural guarantees rather than
sharing code with it:

* the kill switch (``ensure_not_engaged``) — nothing opens while engaged;
* a candidate that already has ANY options decision is never re-decided;
* at most one open structure per **UNDERLYING** (not per instrument: a multi-leg
  structure spans several contract rows, so an instrument-keyed check would not
  stop a second structure on the same name);
* a SEPARATE daily cap (``auto_simulate_options_max_per_day``, default **0**),
  never the equity cap of 2;
* one commit per candidate, so a later failure can never undo an earlier
  acceptance and a retried job can never double-accept.

Duplication is the right trade here: a shared helper is a shared blast radius,
and the equity path is live.

The substitution that matters is the guard. This module calls
``assert_options_auto_simulate_allowed`` — the SECOND guard, with its own
setting, its own cap, its own exception type and its own approval scope — and
never ``assert_auto_simulate_allowed``, which now refuses an options candidate
outright. **The options branch is reachable through no other door.**

A gate-PASSED options candidate the guard refuses becomes a REJECTED
``options_trade`` whose immutable snapshot carries the exact refusal reason and
the condition it failed. One held back only by the daily cap becomes WATCH.

There is deliberately **no scheduled caller**. Nothing in ``scheduler.py`` invokes
this module; wiring it into the EOD chain is a separate, operator-visible change
that must land with the mark / reconcile / expiry step in front of it, because
the guard's condition AA refuses without a dated, clean reconciliation report for
the fill session.

SIMULATED options structures only — no order was placed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from signalforge.db.models import (
    AuditLog,
    Candidate,
    CandidateOptionStructure,
    Instrument,
    OptionsPosition,
    OptionsTrade,
)
from signalforge.domain import Direction, PaperDecision, QualityGate
from signalforge.killswitch import ensure_not_engaged
from signalforge.observability import get_logger
from signalforge.paper.options_ledger import (
    OPTIONS_STRUCTURE_KIND,
    OptionsAutoSimulateForbidden,
    accept_options_candidate,
    assert_options_auto_simulate_allowed,
    options_auto_simulate_enabled,
    options_auto_simulate_max_per_day,
    record_options_decision,
    resolve_options_account,
)
from signalforge.paper.options_marks import PricingContextResolver, UnderlyingNotPriceable

_log = get_logger("paper.options_auto_simulate")

OPTIONS_AUTO_SIM_ACTOR = "options_auto_simulate"
AUDIT_ACTION = "paper.options_auto_simulated"
ACCEPT_NOTE = (
    "options auto-simulation: the SECOND setting ON, every quality gate PASSED, "
    "PAPER_APPROVED strategy, exact approved scope, every capital and shaping limit "
    "within bounds, a clean dated collateral reconciliation; SIMULATED fill at the "
    "modelled spread. SIMULATED options structure — no order was placed."
)


@dataclass(slots=True)
class OptionsAutoSimReport:
    enabled: bool
    considered: int = 0
    accepted: list[int] = field(default_factory=list)  # options_trade ids
    rejected: list[tuple[int, str]] = field(default_factory=list)  # (candidate_id, reason)
    watched: list[tuple[int, str]] = field(default_factory=list)
    skipped: list[tuple[int, str]] = field(default_factory=list)


def _already_decided(session: Session, candidate_id: int) -> bool:
    return (
        session.scalar(
            select(OptionsTrade.id).where(OptionsTrade.candidate_id == candidate_id).limit(1)
        )
        is not None
    )


def _has_open_structure_on_underlying(
    session: Session, account_id: int, underlying_instrument_id: int
) -> bool:
    """Keyed on the UNDERLYING (D3 §10.2 condition X), not on ``instrument_id``
    of a contract: a vertical spans two contract rows and a per-contract check
    would happily open a second structure on the same name."""
    return (
        session.scalar(
            select(OptionsPosition.id)
            .where(
                OptionsPosition.account_id == account_id,
                OptionsPosition.underlying_instrument_id == underlying_instrument_id,
                OptionsPosition.closed_at.is_(None),
            )
            .limit(1)
        )
        is not None
    )


def accepted_today(session: Session, account_id: int, now: datetime) -> int:
    from datetime import time

    from sqlalchemy import func

    day_start = datetime.combine(now.astimezone(UTC).date(), time.min, tzinfo=UTC)
    return int(
        session.scalar(
            select(func.count())
            .select_from(OptionsTrade)
            .where(
                OptionsTrade.account_id == account_id,
                OptionsTrade.decision == PaperDecision.ACCEPTED,
                OptionsTrade.options_position_id.is_not(None),
                OptionsTrade.created_at >= day_start,
            )
        )
        or 0
    )


def _candidate_underlying(session: Session, cand: Candidate) -> str | None:
    """The name this candidate's ``q`` must be sourced for.

    The STRUCTURE row is the authority — its ``underlying_symbol`` is what
    ``structure_from_candidate`` builds the legs against. ``Candidate.instrument``
    is the fallback for a candidate that carries no structure row: the guard
    refuses that on condition C, and refusing it with the candidate's own name
    priced is better than refusing it with nothing recorded.
    """
    symbol = session.scalar(
        select(CandidateOptionStructure.underlying_symbol).where(
            CandidateOptionStructure.candidate_id == cand.id
        )
    )
    if symbol:
        return symbol
    inst = session.get(Instrument, cand.instrument_id)
    return inst.symbol if inst is not None else None


def auto_simulate_options_scan_runs(
    session: Session,
    scan_run_ids: list[int],
    *,
    account_name: str,
    pricing: PricingContextResolver,
    signal_session: date,
    fill_session: date,
    now: datetime | None = None,
) -> OptionsAutoSimReport:
    """Offer every gate-PASSED **options** candidate of ``scan_run_ids`` to the
    second guard and open the ones it allows, within the options daily cap.

    Does nothing at all unless ``auto_simulate_options_enabled`` is ON — which it
    is not, on a fresh install or on the live database. Equity candidates are
    never considered here: the query filters on ``structure_kind``.

    ``pricing`` resolves PER UNDERLYING (decision 11, W5b): a scan carrying
    candidates on three names gets three contexts, each with its own ``q`` from
    its own recorded dividend series. A candidate whose underlying cannot be
    sourced is **skipped**, not rejected — a REJECTED ``options_trade`` is a
    permanent decision (``_already_decided`` never re-decides a candidate), and
    a gap in reference data is not a judgement about the candidate. Skipping
    opens nothing, which is the safe direction, and leaves the candidate
    decidable once the data exists.
    """
    if not options_auto_simulate_enabled(session):
        return OptionsAutoSimReport(enabled=False)
    ensure_not_engaged()
    now = now or datetime.now(UTC)
    report = OptionsAutoSimReport(enabled=True)
    if not scan_run_ids:
        return report

    account = resolve_options_account(session, account_name=account_name)
    cap = options_auto_simulate_max_per_day(session)
    taken = accepted_today(session, account.id, now)

    cands = session.scalars(
        select(Candidate)
        .where(
            Candidate.scan_run_id.in_(scan_run_ids),
            Candidate.structure_kind == OPTIONS_STRUCTURE_KIND,
            Candidate.quality_gate_status == QualityGate.PASSED,
            Candidate.direction != Direction.AVOID,
        )
        .order_by(Candidate.horizon, Candidate.rank_in_horizon.nulls_last(), Candidate.id)
    ).all()
    report.considered = len(cands)

    for cand in cands:
        try:
            if _already_decided(session, cand.id):
                report.skipped.append((cand.id, "candidate already has an options decision"))
                continue
            # Decision 11: this candidate's OWN underlying, at the FILL session.
            # Resolved before the guard, because the guard prices the entry.
            underlying = _candidate_underlying(session, cand)
            if underlying is None:
                report.skipped.append((cand.id, "candidate has no underlying to price"))
                continue
            try:
                ctx = pricing(underlying, fill_session)
            except UnderlyingNotPriceable as exc:
                report.skipped.append((cand.id, f"pricing unavailable — {exc}"))
                _log.error(
                    "paper.options_auto_simulate_unpriceable",
                    candidate=cand.id,
                    underlying=exc.underlying,
                    reason=exc.reason,
                )
                continue
            if _has_open_structure_on_underlying(session, account.id, cand.instrument_id):
                reason = (
                    "options auto-simulation refused: an open structure already exists on this "
                    "underlying"
                )
                record_options_decision(
                    session,
                    cand.id,
                    PaperDecision.REJECTED,
                    account_name=account_name,
                    note=reason,
                    actor=OPTIONS_AUTO_SIM_ACTOR,
                    refused_condition="X",
                )
                report.rejected.append((cand.id, reason))
                session.commit()
                continue
            if taken >= cap:
                reason = f"options auto-simulation daily cap ({cap}) reached — not taken"
                record_options_decision(
                    session,
                    cand.id,
                    PaperDecision.WATCH,
                    account_name=account_name,
                    note=reason,
                    actor=OPTIONS_AUTO_SIM_ACTOR,
                    refused_condition="Z",
                )
                report.watched.append((cand.id, reason))
                session.commit()
                continue
            try:
                plan = assert_options_auto_simulate_allowed(
                    session,
                    cand,
                    account_name=account_name,
                    pricing=ctx,
                    signal_session=signal_session,
                    fill_session=fill_session,
                    now=now,
                )
            except OptionsAutoSimulateForbidden as exc:
                reason = f"options auto-simulation refused: {exc}"
                record_options_decision(
                    session,
                    cand.id,
                    PaperDecision.REJECTED,
                    account_name=account_name,
                    note=reason,
                    actor=OPTIONS_AUTO_SIM_ACTOR,
                    refused_condition=exc.condition,
                    pricing=ctx,
                )
                report.rejected.append((cand.id, reason))
                session.commit()
                continue

            res = accept_options_candidate(
                session,
                cand.id,
                account_name=account_name,
                plan=plan,
                pricing=ctx,
                actor=OPTIONS_AUTO_SIM_ACTOR,
                note=ACCEPT_NOTE,
            )
            session.add(
                AuditLog(
                    ts=now,
                    actor=OPTIONS_AUTO_SIM_ACTOR,
                    action=AUDIT_ACTION,
                    entity=f"options_trade:{res.options_trade_id}",
                    before_json={},
                    after_json={
                        "candidate_id": cand.id,
                        "scan_run_id": cand.scan_run_id,
                        "underlying": plan.structure.underlying_symbol,
                        "structure_type": res.structure_type,
                        "contracts": res.contracts,
                        "net_premium": res.net_premium,
                        "max_loss_dollars_R": res.r_dollars,
                        "collateral_reserved": res.collateral_reserved,
                        "limits_evaluated": plan.limits.to_dict(),
                        "options_position_id": res.position_id,
                        "simulated": True,
                        "notice": "SIMULATED options structure — no order was placed.",
                    },
                )
            )
            session.commit()
            taken += 1
            report.accepted.append(res.options_trade_id)
            _log.info(
                "paper.options_auto_simulated",
                candidate=cand.id,
                options_trade=res.options_trade_id,
                underlying=plan.structure.underlying_symbol,
                r=res.r_dollars,
            )
        except Exception as exc:  # one bad candidate must not stop the rest
            session.rollback()
            report.skipped.append((cand.id, f"error: {type(exc).__name__}: {exc}"))
            _log.error("paper.options_auto_simulate_failed", candidate=cand.id, error=str(exc))
    return report


__all__ = [
    "ACCEPT_NOTE",
    "AUDIT_ACTION",
    "OPTIONS_AUTO_SIM_ACTOR",
    "OptionsAutoSimReport",
    "accepted_today",
    "auto_simulate_options_scan_runs",
]
