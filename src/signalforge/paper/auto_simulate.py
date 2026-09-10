"""Automatic SIMULATED paper acceptance of qualified candidates ("auto-simulation").

Operator-authorized on 2026-09-10. Deterministic and paper-only: this module
never contacts a broker, never places an order, and never lets an LLM near a
decision. It runs ONLY right after the approved-scope scan, on that scan's own
candidates, and every acceptance goes through exactly the same ledger call as a
manual acceptance (``paper.ledger.accept_candidate`` — same evidence snapshot,
same fill/slippage model, same immutability triggers) after the same guard
(``assert_auto_simulate_allowed``: setting ON, every quality gate PASSED, U.S.
stock/ETF only, PAPER_APPROVED strategy version, exact five-part approved scope).

Additional guards owned here:

* the kill switch (``ensure_not_engaged``) — nothing runs while engaged;
* a candidate that already has ANY PaperTrade decision is never re-decided;
* at most one open paper position per instrument;
* a daily cap (``auto_simulate_max_per_day`` setting, default 2) counted over
  every ACCEPTED trade today — manual ones included;
* each decision is committed on its own, so a later failure can never undo an
  earlier acceptance and a retried job can never double-accept.

A gate-PASSED candidate that the guard refuses is recorded as a REJECTED
PaperTrade whose evidence snapshot carries the exact refusal reason, so the
failure rationale is as immutable as the trade itself. A candidate held back
only by the daily cap is recorded as WATCH (still valid, not taken).

Research signal only — no order was placed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, time

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from signalforge.db.models import AuditLog, Candidate, Instrument, PaperPosition, PaperTrade
from signalforge.domain import Direction, PaperDecision, QualityGate
from signalforge.killswitch import ensure_not_engaged
from signalforge.observability import get_logger
from signalforge.paper.ledger import (
    AutoSimulateForbidden,
    _account,
    accept_candidate,
    assert_auto_simulate_allowed,
    auto_simulate_enabled,
    record_decision,
)
from signalforge.settings_store import get_setting

_log = get_logger("paper.auto_simulate")

AUTO_SIM_ACTOR = "auto_simulate"
AUTO_SIM_CAP_KEY = "auto_simulate_max_per_day"
DEFAULT_MAX_PER_DAY = 2
AUDIT_ACTION = "paper.auto_simulated"
ACCEPT_NOTE = (
    "auto-simulation: setting ON, every quality gate PASSED, PAPER_APPROVED strategy, "
    "exact approved scope; SIMULATED fill. Research signal only — no order was placed."
)


@dataclass(slots=True)
class AutoSimReport:
    enabled: bool
    considered: int = 0
    accepted: list[int] = field(default_factory=list)  # paper_trade ids
    rejected: list[tuple[int, str]] = field(default_factory=list)  # (candidate_id, reason)
    watched: list[tuple[int, str]] = field(default_factory=list)
    skipped: list[tuple[int, str]] = field(default_factory=list)


def max_per_day(session: Session) -> int:
    raw = get_setting(session, AUTO_SIM_CAP_KEY, DEFAULT_MAX_PER_DAY)
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return DEFAULT_MAX_PER_DAY


def accepted_today(session: Session, account_id: int, now: datetime) -> int:
    """ACCEPTED paper trades on this account since 00:00 UTC today (manual ones count)."""
    day_start = datetime.combine(now.astimezone(UTC).date(), time.min, tzinfo=UTC)
    return int(
        session.scalar(
            select(func.count())
            .select_from(PaperTrade)
            .where(
                PaperTrade.account_id == account_id,
                PaperTrade.decision == PaperDecision.ACCEPTED,
                PaperTrade.created_at >= day_start,
            )
        )
        or 0
    )


def _already_decided(session: Session, candidate_id: int) -> bool:
    return (
        session.scalar(
            select(PaperTrade.id).where(PaperTrade.candidate_id == candidate_id).limit(1)
        )
        is not None
    )


def _has_open_position(session: Session, account_id: int, instrument_id: int) -> bool:
    return (
        session.scalar(
            select(PaperPosition.id)
            .where(
                PaperPosition.account_id == account_id,
                PaperPosition.instrument_id == instrument_id,
                PaperPosition.closed_at.is_(None),
            )
            .limit(1)
        )
        is not None
    )


def auto_simulate_scan_runs(
    session: Session,
    scan_run_ids: list[int],
    *,
    account_name: str = "default",
    now: datetime | None = None,
) -> AutoSimReport:
    """Offer every gate-PASSED candidate of ``scan_run_ids`` to the auto-simulation
    guard and paper-accept (SIMULATED) the ones it allows, within the daily cap.

    Returns a report of what was accepted / rejected (with reasons) / watched /
    skipped. Does nothing at all unless ``auto_simulate_qualified_signals`` is ON.
    """
    if not auto_simulate_enabled(session):
        return AutoSimReport(enabled=False)
    ensure_not_engaged()
    now = now or datetime.now(UTC)
    report = AutoSimReport(enabled=True)
    if not scan_run_ids:
        return report

    acct = _account(session, account_name)
    cap = max_per_day(session)
    taken = accepted_today(session, acct.id, now)

    cands = session.scalars(
        select(Candidate)
        .where(
            Candidate.scan_run_id.in_(scan_run_ids),
            Candidate.quality_gate_status == QualityGate.PASSED,
            Candidate.direction != Direction.AVOID,
        )
        .order_by(Candidate.horizon, Candidate.rank_in_horizon.nulls_last(), Candidate.id)
    ).all()
    report.considered = len(cands)

    for cand in cands:
        try:
            if _already_decided(session, cand.id):
                report.skipped.append((cand.id, "candidate already has a paper decision"))
                continue
            if _has_open_position(session, acct.id, cand.instrument_id):
                reason = "auto-simulation refused: an open paper position already exists"
                record_decision(
                    session, cand.id, PaperDecision.REJECTED, note=reason, actor=AUTO_SIM_ACTOR
                )
                report.rejected.append((cand.id, reason))
                session.commit()
                continue
            if taken >= cap:
                reason = f"auto-simulation daily cap ({cap}) reached — not taken"
                record_decision(
                    session, cand.id, PaperDecision.WATCH, note=reason, actor=AUTO_SIM_ACTOR
                )
                report.watched.append((cand.id, reason))
                session.commit()
                continue
            try:
                assert_auto_simulate_allowed(session, cand)
            except AutoSimulateForbidden as exc:
                reason = f"auto-simulation refused: {exc}"
                record_decision(
                    session, cand.id, PaperDecision.REJECTED, note=reason, actor=AUTO_SIM_ACTOR
                )
                report.rejected.append((cand.id, reason))
                session.commit()
                continue

            res = accept_candidate(session, cand.id, actor=AUTO_SIM_ACTOR, note=ACCEPT_NOTE)
            inst = session.get(Instrument, cand.instrument_id)
            session.add(
                AuditLog(
                    ts=now,
                    actor=AUTO_SIM_ACTOR,
                    action=AUDIT_ACTION,
                    entity=f"paper_trade:{res.paper_trade_id}",
                    before_json={},
                    after_json={
                        "candidate_id": cand.id,
                        "scan_run_id": cand.scan_run_id,
                        "symbol": inst.symbol if inst else None,
                        "side": res.side.value,
                        "shares": res.shares,
                        "fill_price": res.fill_price,
                        "position_id": res.position_id,
                        "simulated": True,
                        "notice": "Research signal only — no order was placed.",
                    },
                )
            )
            session.commit()
            taken += 1
            report.accepted.append(res.paper_trade_id)
            _log.info(
                "paper.auto_simulated",
                candidate=cand.id,
                paper_trade=res.paper_trade_id,
                symbol=inst.symbol if inst else None,
                shares=res.shares,
            )
        except Exception as exc:  # one bad candidate must not stop the rest
            session.rollback()
            report.skipped.append((cand.id, f"error: {type(exc).__name__}: {exc}"))
            _log.error("paper.auto_simulate_failed", candidate=cand.id, error=str(exc))
    return report


__all__ = [
    "ACCEPT_NOTE",
    "AUDIT_ACTION",
    "AUTO_SIM_ACTOR",
    "AUTO_SIM_CAP_KEY",
    "DEFAULT_MAX_PER_DAY",
    "AutoSimReport",
    "accepted_today",
    "auto_simulate_scan_runs",
    "max_per_day",
]
