"""Paper-trading ledger (ARCHITECTURE.md §1.7).

No real orders. Simulated fills apply half-spread + slippage against the trade.
``paper_trade`` rows are immutable after creation (invariant S9) — the repository
never issues UPDATE/DELETE and the migration adds BEFORE UPDATE/DELETE triggers.
Creating a paper trade is guarded by the kill switch (invariant S6). Auto-
simulation is OFF unless the user explicitly enables it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from signalforge.data.repository import get_daily_bars
from signalforge.db.models import (
    AppSetting,
    Candidate,
    Instrument,
    OHLCVDaily,
    PaperAccount,
    PaperFill,
    PaperOrder,
    PaperPosition,
    PaperTrade,
)
from signalforge.db.types import utcnow
from signalforge.domain import Direction, PaperDecision, PositionSide, QualityGate
from signalforge.killswitch import ensure_not_engaged
from signalforge.observability import get_logger

__all__ = [
    "Decision",
    "ImmutablePaperTradeError",
    "AcceptResult",
    "auto_simulate_enabled",
    "assert_auto_simulate_allowed",
    "AutoSimulateForbidden",
    "accept_candidate",
    "record_decision",
    "mark_to_market",
]

Decision = PaperDecision
_log = get_logger("paper.ledger")
_NOMINAL_SPREAD_BPS = 5.0
_CENTS = Decimal("0.01")


class ImmutablePaperTradeError(RuntimeError):
    """Raised on any attempt to mutate an existing ``paper_trade`` row (S9)."""


@dataclass(frozen=True, slots=True)
class AcceptResult:
    paper_trade_id: int
    order_id: int
    fill_id: int
    position_id: int
    side: PositionSide
    shares: int
    fill_price: float
    total_cost: float


def _money(x: float) -> Decimal:
    return Decimal(str(x)).quantize(_CENTS, rounding=ROUND_HALF_UP)


def auto_simulate_enabled(session: Session) -> bool:
    row = session.scalar(
        select(AppSetting).where(AppSetting.key == "auto_simulate_qualified_signals")
    )
    return bool(row and row.value_json is True)


def _account(session: Session, name: str) -> PaperAccount:
    acct = session.scalar(select(PaperAccount).where(PaperAccount.name == name))
    if acct is None:
        raise ValueError(f"paper account {name!r} does not exist — run `signalforge seed`")
    return acct


def _slippage_frac(slippage_bps: float, spread_bps: float) -> float:
    return (slippage_bps + spread_bps / 2.0) / 10_000.0


def record_decision(
    session: Session,
    candidate_id: int,
    decision: PaperDecision,
    *,
    account_name: str = "default",
    note: str = "",
    actor: str = "local-user",
) -> int:
    """Record REJECTED / IGNORED / WATCH against a candidate (no position).

    ``note``/``actor`` are frozen into the evidence snapshot (``decision`` key)
    so the failure rationale is as immutable as the rest of the trade."""
    ensure_not_engaged()
    if decision is PaperDecision.ACCEPTED:
        raise ValueError("use accept_candidate() for ACCEPTED")
    cand = session.get(Candidate, candidate_id)
    if cand is None:
        raise ValueError(f"candidate {candidate_id} not found")
    acct = _account(session, account_name)
    trade = PaperTrade(
        account_id=acct.id,
        candidate_id=cand.id,
        decision=decision,
        signal_snapshot_json=_candidate_snapshot(session, cand)
        | {"decision": {"actor": actor, "note": note, "automatic": actor == "auto_simulate"}},
        plan_json=_plan(cand),
        why_qualified="; ".join(cand.reasons_qualify),
        why_might_fail="; ".join(cand.reasons_fail),
        actor=actor,
        created_at=utcnow(),
    )
    session.add(trade)
    session.flush()
    _log.info("paper.decision", candidate=candidate_id, decision=decision.value, note=note)
    return trade.id


def accept_candidate(
    session: Session,
    candidate_id: int,
    *,
    account_name: str = "default",
    slippage_bps: float | None = None,
    as_of: date | None = None,
    actor: str = "local-user",
    note: str = "",
) -> AcceptResult:
    ensure_not_engaged()
    cand = session.get(Candidate, candidate_id)
    if cand is None:
        raise ValueError(f"candidate {candidate_id} not found")
    if cand.direction is Direction.AVOID:
        raise ValueError("cannot paper-accept an AVOID candidate")

    inst = session.get(Instrument, cand.instrument_id)
    assert inst is not None
    acct = _account(session, account_name)

    entry_ref = (cand.entry_zone_low + cand.entry_zone_high) / 2.0
    stop = cand.invalidation_level
    per_share_risk = abs(entry_ref - stop)
    if per_share_risk <= 0:
        raise ValueError("candidate has a zero-width risk (entry == stop)")

    shares = round((cand.risk_dollars or 0.0) / per_share_risk) if cand.risk_dollars else 0
    if shares < 1:
        # fall back to a nominal 0.5% of equity if the candidate carried no sizing
        shares = max(1, int((float(acct.cash) * 0.005) // per_share_risk))

    side = PositionSide.LONG if cand.direction is Direction.LONG else PositionSide.SHORT
    d = 1 if side is PositionSide.LONG else -1
    slip = _slippage_frac(slippage_bps if slippage_bps is not None else 3.0, _NOMINAL_SPREAD_BPS)
    fill_price = entry_ref * (1 + d * slip)

    spread_cost = _money(abs(entry_ref) * shares * (_NOMINAL_SPREAD_BPS / 10_000.0) / 2.0)
    slippage_cost = _money(abs(entry_ref) * shares * slip - float(spread_cost))
    if slippage_cost < 0:
        slippage_cost = Decimal("0")
    commission = Decimal("0")
    notional = _money(fill_price * shares)
    total_cost = spread_cost + slippage_cost + commission

    now = utcnow()
    order = PaperOrder(
        account_id=acct.id,
        candidate_id=cand.id,
        instrument_id=inst.id,
        side=side,
        qty=shares,
        order_type="market",
        submitted_at=now,
        assumptions_json={
            "reference_price": round(entry_ref, 4),
            "spread_bps": _NOMINAL_SPREAD_BPS,
            "slippage_frac": slip,
            "note": "SIMULATED fill — no order was placed",
        },
    )
    session.add(order)
    session.flush()

    fill = PaperFill(
        order_id=order.id,
        price=_money(fill_price),
        qty=shares,
        spread_cost=spread_cost,
        slippage=slippage_cost,
        commission=commission,
        filled_at=now,
    )
    session.add(fill)

    position = PaperPosition(
        account_id=acct.id,
        instrument_id=inst.id,
        strategy_version_id=cand.strategy_version_id,
        horizon=cand.horizon,
        side=side,
        qty=shares,
        avg_price=_money(fill_price),
        stop_level=stop,
        target_level=cand.target_level,
        time_stop_date=_time_stop_date(as_of or date.today(), cand.time_stop_days),
        opened_at=now,
    )
    session.add(position)
    session.flush()

    # Cash: longs tie up notional; shorts tie up costs only (proceeds held as credit).
    acct.cash = acct.cash - (notional + total_cost if side is PositionSide.LONG else total_cost)

    trade = PaperTrade(
        account_id=acct.id,
        candidate_id=cand.id,
        position_id=position.id,
        decision=PaperDecision.ACCEPTED,
        signal_snapshot_json=_candidate_snapshot(session, cand)
        | {"decision": {"actor": actor, "note": note, "automatic": actor == "auto_simulate"}},
        plan_json=_plan(cand) | {"shares": shares, "fill_price": round(fill_price, 4)},
        why_qualified="; ".join(cand.reasons_qualify),
        why_might_fail="; ".join(cand.reasons_fail),
        # The same ``actor`` that is frozen into the snapshot JSON, also written
        # to the indexed column an order-authorisation predicate reads (D6 §5.3).
        # Nothing else about this path changes: the same order, fill, position,
        # cash movement, and snapshot payload are produced as before.
        actor=actor,
        created_at=now,
    )
    session.add(trade)
    session.flush()

    _log.info(
        "paper.accept",
        candidate=candidate_id,
        symbol=inst.symbol,
        side=side.value,
        shares=shares,
        fill=round(fill_price, 4),
    )
    return AcceptResult(
        paper_trade_id=trade.id,
        order_id=order.id,
        fill_id=fill.id,
        position_id=position.id,
        side=side,
        shares=shares,
        fill_price=round(fill_price, 4),
        total_cost=float(total_cost),
    )


@dataclass(frozen=True, slots=True)
class MarkToMarketResult:
    checked: int
    closed: int
    realized_pnl: float
    unrealized_pnl: float


def mark_to_market(
    session: Session,
    *,
    account_name: str = "default",
    as_of: date | None = None,
) -> MarkToMarketResult:
    """Value open positions; close any that hit their stop / target / time stop.

    Closing an existing position is allowed while the kill switch is engaged
    (it is protective); only *opening* new positions is blocked.
    """
    acct = _account(session, account_name)
    on = as_of or date.today()
    open_positions = list(
        session.scalars(
            select(PaperPosition).where(
                PaperPosition.account_id == acct.id, PaperPosition.closed_at.is_(None)
            )
        )
    )
    realized = 0.0
    unrealized = 0.0
    closed = 0
    for pos in open_positions:
        inst = session.get(Instrument, pos.instrument_id)
        assert inst is not None
        bars = get_daily_bars(session, inst.symbol, on - _lookback(), on)
        if not bars:
            continue
        last = bars[-1]
        d = 1 if pos.side is PositionSide.LONG else -1
        exit_reason = _exit_reason(pos, last, on)
        if exit_reason:
            exit_px = _exit_price(pos, last, exit_reason)
            pnl = d * (exit_px - float(pos.avg_price)) * pos.qty
            pos.closed_at = _as_dt(on)
            pos.realized_pnl = _money(pnl)
            # Cash model: a long tied up notional on open, so it gets exit proceeds
            # back; a short only paid costs on open, so it gets the realised P&L.
            if pos.side is PositionSide.LONG:
                acct.cash = acct.cash + _money(exit_px * pos.qty)
            else:
                acct.cash = acct.cash + _money(pnl)
            realized += pnl
            closed += 1
            _log.info("paper.close", symbol=inst.symbol, reason=exit_reason, pnl=round(pnl, 2))
        else:
            unrealized += d * (float(last.close) - float(pos.avg_price)) * pos.qty
    return MarkToMarketResult(
        checked=len(open_positions),
        closed=closed,
        realized_pnl=round(realized, 2),
        unrealized_pnl=round(unrealized, 2),
    )


# --------------------------------------------------------------------------- #
def _lookback() -> timedelta:
    return timedelta(days=10)


def _as_dt(d: date) -> datetime:
    return datetime.combine(d, datetime.min.time()).replace(tzinfo=utcnow().tzinfo)


def _time_stop_date(start: date, days: int) -> datetime:
    return _as_dt(start + timedelta(days=days))


def _exit_reason(pos: PaperPosition, bar: OHLCVDaily, on: date) -> str | None:
    if pos.side is PositionSide.LONG:
        if pos.stop_level is not None and bar.low <= pos.stop_level:
            return "stop"
        if pos.target_level is not None and bar.high >= pos.target_level:
            return "target"
    else:
        if pos.stop_level is not None and bar.high >= pos.stop_level:
            return "stop"
        if pos.target_level is not None and bar.low <= pos.target_level:
            return "target"
    if pos.time_stop_date is not None and on >= pos.time_stop_date.date():
        return "time_stop"
    return None


def _exit_price(pos: PaperPosition, bar: OHLCVDaily, reason: str) -> float:
    if reason == "stop" and pos.stop_level is not None:
        return float(pos.stop_level)
    if reason == "target" and pos.target_level is not None:
        return float(pos.target_level)
    return float(bar.close)


def _plan(cand: Candidate) -> dict[str, object]:
    return {
        "direction": cand.direction.value,
        "entry_zone": [cand.entry_zone_low, cand.entry_zone_high],
        "invalidation": cand.invalidation_level,
        "target": cand.target_level,
        "time_stop_days": cand.time_stop_days,
    }


def _candidate_snapshot(session: Session, cand: Candidate) -> dict[str, object]:
    """The COMPLETE, immutable evidence snapshot stored on every paper trade
    (``paper_trade`` rows cannot be updated or deleted — invariant S9): the
    candidate's full deterministic record, its failure rationale, the exact
    scan scope it came from, whether that scope matched the strategy's
    approval, the strategy version/parameter hash, and the code version."""
    from signalforge.db.models import ScanRun, StrategyVersion
    from signalforge.gitinfo import git_sha
    from signalforge.research.approval_scope import (
        approved_scopes,
        current_spec_json_hash,
        scan_scope_matches,
    )

    inst = session.get(Instrument, cand.instrument_id)
    run = session.get(ScanRun, cand.scan_run_id)
    ver = session.get(StrategyVersion, cand.strategy_version_id)
    scopes = approved_scopes(session, cand.strategy_version_id)
    spec_hash = current_spec_json_hash(session, cand.strategy_version_id)
    scope_ok = bool(
        run is not None
        and scan_scope_matches(
            scopes,
            dataset_snapshot_id=run.dataset_snapshot_id,
            config_hash=run.config_hash,
            spec_json_hash=spec_hash or "",
            source=run.source,
            universe=frozenset(x.upper() for x in (run.universe_json or ())),
        )
    )
    return {
        "candidate_id": cand.id,
        "symbol": inst.symbol if inst else None,
        "instrument_type": inst.instrument_type if inst else None,
        "horizon": cand.horizon.value,
        "direction": cand.direction.value,
        "entry_zone": [cand.entry_zone_low, cand.entry_zone_high],
        "invalidation_level": cand.invalidation_level,
        "target_level": cand.target_level,
        "target_logic": cand.target_logic,
        "time_stop_days": cand.time_stop_days,
        "reward_risk_estimate": cand.reward_risk_estimate,
        "probability_calibrated": cand.probability_calibrated,
        "calibration_ref": cand.calibration_ref,
        "risk_dollars": cand.risk_dollars,
        "risk_pct_of_account": cand.risk_pct_of_account,
        "liquidity": cand.liquidity_json,
        "slippage_assumption": cand.slippage_assumption_json,
        "event_risk": cand.event_risk_json,
        "portfolio_context": cand.portfolio_context_json,
        "data_freshness": cand.data_freshness_json,
        "ranking": cand.ranking_json,
        "rank_in_horizon": cand.rank_in_horizon,
        "quality_gate_status": cand.quality_gate_status.value,
        "failed_gates": cand.failed_gates,
        "reasons_qualify": cand.reasons_qualify,
        "reasons_fail": cand.reasons_fail,
        "was_no_trade": cand.quality_gate_status is not QualityGate.PASSED,
        "scan": (
            {
                "scan_run_id": run.id,
                "started_at": run.started_at.isoformat(),
                "source": run.source,
                "dataset_snapshot_id": run.dataset_snapshot_id,
                "config_hash": run.config_hash,
                "universe_size": len(run.universe_json or []),
            }
            if run is not None
            else None
        ),
        "strategy": (
            {
                "strategy_version_id": ver.id,
                "version": ver.version,
                "status": ver.status.value,
                "spec_json_hash": spec_hash,
            }
            if ver is not None
            else None
        ),
        "approval_scope": {
            "matched": scope_ok,
            "approved_scopes": [
                {
                    "evaluation_id": sc.evaluation_id,
                    "dataset_snapshot_id": sc.dataset_snapshot_id,
                    "config_hash": sc.config_hash,
                    "spec_json_hash": sc.spec_json_hash,
                    "sources": sorted(sc.sources),
                }
                for sc in scopes
            ],
        },
        "code_version": git_sha(),
        "notice": "Research signal only — no order was placed.",
    }


class AutoSimulateForbidden(RuntimeError):
    """Automatic paper acceptance was requested for a candidate that is not
    eligible. There is deliberately NO scheduled caller of automatic
    acceptance; this guard exists so any future caller cannot bypass the
    rules below."""


def assert_auto_simulate_allowed(session: Session, cand: Candidate) -> None:
    """Every condition an automatic (non-manual) paper acceptance would need:

    * the setting ``auto_simulate_qualified_signals`` is ON;
    * the candidate PASSED every quality gate;
    * the instrument is a U.S. stock/ETF (never an option, future, or currency);
    * the strategy version is PAPER_APPROVED;
    * the candidate's scan matches the strategy's exact approved scope (dataset
      snapshot, source, config hash, live parameter hash).
    Raises :class:`AutoSimulateForbidden` naming the first failed condition."""
    from signalforge.db.models import ScanRun, StrategyVersion
    from signalforge.domain import StrategyStatus
    from signalforge.research.approval_scope import (
        approved_scopes,
        current_spec_json_hash,
        scan_scope_matches,
    )

    if not auto_simulate_enabled(session):
        raise AutoSimulateForbidden("auto_simulate_qualified_signals is off")
    if cand.quality_gate_status is not QualityGate.PASSED:
        raise AutoSimulateForbidden("candidate did not pass every quality gate")
    inst = session.get(Instrument, cand.instrument_id)
    if inst is None or inst.instrument_type not in ("stock", "etf"):
        raise AutoSimulateForbidden(
            f"instrument type {inst.instrument_type if inst else None!r} is not a U.S. stock/ETF"
        )
    ver = session.get(StrategyVersion, cand.strategy_version_id)
    if ver is None or ver.status is not StrategyStatus.PAPER_APPROVED:
        raise AutoSimulateForbidden("strategy version is not PAPER_APPROVED")
    run = session.get(ScanRun, cand.scan_run_id)
    scopes = approved_scopes(session, ver.id)
    if run is None or not scan_scope_matches(
        scopes,
        dataset_snapshot_id=run.dataset_snapshot_id,
        config_hash=run.config_hash,
        spec_json_hash=current_spec_json_hash(session, ver.id) or "",
        source=run.source,
        universe=frozenset(x.upper() for x in (run.universe_json or ())),
    ):
        raise AutoSimulateForbidden("scan scope does not match the strategy's approved scope")
