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

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from signalforge.data.calendar import rth_bounds_utc, sessions
from signalforge.data.repository import get_daily_bars
from signalforge.db.models import (
    AppSetting,
    AuditLog,
    Candidate,
    Instrument,
    OHLCVDaily,
    OptionsPosition,
    PaperAccount,
    PaperFill,
    PaperOrder,
    PaperPosition,
    PaperTrade,
    ScanRun,
)
from signalforge.db.types import utcnow
from signalforge.domain import Direction, Horizon, PaperDecision, PositionSide, QualityGate
from signalforge.killswitch import ensure_not_engaged
from signalforge.observability import get_logger
from signalforge.paper.equity_guard import NotAnEquityPosition, assert_equity_instrument
from signalforge.settings_store import effective_research_config

__all__ = [
    "Decision",
    "ImmutablePaperTradeError",
    "NotAnEquityPosition",
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


def _completed_market_date(now: datetime) -> date:
    completed = [
        d
        for d in sessions(now.date() - timedelta(days=14), now.date())
        if (bounds := rth_bounds_utc(d)) is not None and bounds[1] <= now
    ]
    if not completed:
        raise ValueError("no completed market session")
    return completed[-1]


def _mark_quality_ok(bar: OHLCVDaily) -> bool:
    return (
        not bar.quality_flags
        and bar.is_adjusted
        and (not bar.is_simulated or bar.source.startswith("fixture"))
        and _finite_decimal(bar.close, "mark") > 0
    )


def _exit_slippage(session: Session, pos: PaperPosition) -> float:
    trade = session.scalar(
        select(PaperTrade).where(PaperTrade.position_id == pos.id).order_by(PaperTrade.id)
    )
    evidence = trade.plan_json.get("risk_decision", {}) if trade else {}
    return max(3.0, float(evidence.get("exit_slippage_bps", 3.0)))


def _acceptance_freshness(session: Session, cand: Candidate, now: datetime) -> dict[str, object]:
    """Live daily acceptance requires a fresh scan and the last completed XNYS bar.

    Scan age uses the effective horizon budget. Source-specific market dates,
    not a frozen PASSED/fresh flag or a fetch-success timestamp, authorize entry.
    Intraday acceptance needs a separate intraday execution-price model.
    """
    run = session.get(ScanRun, cand.scan_run_id)
    if run is None or not run.source or run.finished_at is None:
        raise AutoSimulateForbidden("freshness: missing completed, source-qualified scan")
    if run.started_at > run.finished_at:
        raise AutoSimulateForbidden("freshness: invalid scan timestamp chronology")
    if cand.horizon is Horizon.INTRADAY:
        raise AutoSimulateForbidden("freshness: daily ledger cannot validate intraday execution")
    budget = timedelta(
        minutes=effective_research_config(session).data_quality.freshness_budget_minutes[
            cand.horizon
        ]
    )
    for timestamp in (run.started_at, run.finished_at, cand.created_at):
        if timestamp > now or now - timestamp > budget:
            raise AutoSimulateForbidden("freshness: future or stale candidate/scan timestamp")
    market_date = _completed_market_date(now)
    inst = session.get(Instrument, cand.instrument_id)
    assert inst is not None
    bars = get_daily_bars(session, inst.symbol, market_date, market_date, source=run.source)
    bounds = rth_bounds_utc(market_date)
    assert bounds is not None
    if len(bars) != 1 or not bounds[1] <= bars[0].ingested_at <= now:
        raise AutoSimulateForbidden("freshness: missing current source-qualified completed bar")
    if not _mark_quality_ok(bars[0]):
        raise AutoSimulateForbidden("freshness: flagged, unadjusted or simulated source bar")
    return {
        "mode": "current",
        "checked_at": now.isoformat(),
        "source": run.source,
        "market_date": market_date.isoformat(),
        "scan_run_id": run.id,
        "scan_age_budget_seconds": budget.total_seconds(),
    }


def _position_bars(
    session: Session, pos: PaperPosition, symbol: str, start: date, end: date
) -> list[OHLCVDaily]:
    """Use frozen acceptance provenance; ambiguous legacy data fails closed."""
    trade = session.scalar(
        select(PaperTrade)
        .where(PaperTrade.position_id == pos.id, PaperTrade.decision == PaperDecision.ACCEPTED)
        .order_by(PaperTrade.id)
    )
    source = None
    if trade is not None:
        source = (trade.signal_snapshot_json.get("scan") or {}).get("source") or None
    bars = get_daily_bars(session, symbol, start, end, source=source)
    if len({bar.session_date for bar in bars}) != len(bars):
        raise ValueError("ambiguous paper mark sources; explicit provenance required")
    return bars


def _finite_decimal(value: object, label: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except ArithmeticError as exc:
        raise ValueError(f"invalid {label}") from exc
    if not result.is_finite():
        raise ValueError(f"nonfinite {label}")
    return result


def _safe_shares(
    session: Session,
    acct: PaperAccount,
    inst: Instrument,
    price: Decimal,
    stop: Decimal,
    candidate_risk: Decimal,
    on: date,
    valuation_at: datetime,
    exit_slippage_bps: float,
) -> tuple[int, dict[str, object]]:
    """Recheck account exposure under a write lock, never scan-time estimates.

    The no-op update serializes SQLite writers too. The caller owns the
    transaction; immutable historical trades are never updated.
    """
    session.flush()
    session.execute(
        update(PaperAccount).where(PaperAccount.id == acct.id).values(cash=PaperAccount.cash)
    )
    session.refresh(acct)
    cash = _finite_decimal(acct.cash, "cash")
    reserved = _finite_decimal(acct.collateral_reserved, "reserved collateral")
    if cash < 0 or reserved < 0 or reserved > cash:
        raise ValueError("invalid paper account buying power")
    if (
        session.scalar(
            select(OptionsPosition.id).where(
                OptionsPosition.account_id == acct.id, OptionsPosition.closed_at.is_(None)
            )
        )
        is not None
    ):
        raise ValueError("cannot safely size equity in an account with open options")
    positions = list(
        session.scalars(
            select(PaperPosition)
            .where(PaperPosition.account_id == acct.id, PaperPosition.closed_at.is_(None))
            .execution_options(populate_existing=True)
        )
    )
    gross = Decimal(0)
    open_risk = Decimal(0)
    symbol_value = Decimal(0)
    sector_value = Decimal(0)
    sector = (inst.sector or "").strip().casefold()
    market_date = _completed_market_date(valuation_at)
    for pos in positions:
        held = session.get(Instrument, pos.instrument_id)
        if held is None or pos.side is not PositionSide.LONG or pos.qty <= 0:
            raise ValueError("unsupported existing paper exposure")
        assert_equity_instrument(held, "accept_candidate")
        bars = _position_bars(session, pos, held.symbol, market_date, market_date)
        if pos.opened_at.date() > on:
            raise ValueError("account contains positions opened after valuation date")
        if not bars or not _mark_quality_ok(bars[-1]):
            raise ValueError("paper account limits: missing current, clean adjusted exposure mark")
        if bars[-1].ingested_at > valuation_at:
            raise ValueError("paper account limits: future exposure mark")
        mark = _finite_decimal(bars[-1].close, "mark")
        held_stop = _finite_decimal(pos.stop_level, "existing stop")
        if mark <= 0 or held_stop <= 0:
            raise ValueError("invalid existing paper exposure")
        value = mark * pos.qty
        gross += value
        open_risk += (
            max(
                Decimal(0),
                mark
                - _money(
                    float(held_stop)
                    * (1 - _slippage_frac(_exit_slippage(session, pos), _NOMINAL_SPREAD_BPS))
                ),
            )
            * pos.qty
        )
        if pos.instrument_id == inst.id:
            symbol_value += value
        if sector and (held.sector or "").strip().casefold() == sector:
            sector_value += value
    equity = cash + gross
    limits = effective_research_config(session).risk

    def cap(pct: float) -> Decimal:
        return equity * _finite_decimal(pct, "risk limit") / 100

    # Budget the adverse rounded stop fill too (gaps can still exceed stop risk).
    risk_per_share = price - _money(
        float(stop) * (1 - _slippage_frac(exit_slippage_bps, _NOMINAL_SPREAD_BPS))
    )
    effective_limits = {
        "per_trade_risk_pct": min(0.5, limits.per_trade_risk_pct),
        "max_daily_portfolio_risk_pct": min(1.5, limits.max_daily_portfolio_risk_pct),
        "max_position_concentration_pct": min(5.0, limits.max_position_concentration_pct),
        "max_portfolio_exposure_pct": min(100.0, limits.max_portfolio_exposure_pct),
        "max_correlated_exposure_pct": min(20.0, limits.max_correlated_exposure_pct),
    }
    budgets = {
        "candidate_risk": (candidate_risk, risk_per_share),
        "per_trade_risk": (cap(effective_limits["per_trade_risk_pct"]), risk_per_share),
        "open_risk": (
            cap(effective_limits["max_daily_portfolio_risk_pct"]) - open_risk,
            risk_per_share,
        ),
        "cash": (cash - reserved, price),
        "symbol": (cap(effective_limits["max_position_concentration_pct"]) - symbol_value, price),
        "gross": (cap(effective_limits["max_portfolio_exposure_pct"]) - gross, price),
    }
    if sector and sector not in {"unknown", "unknown_sector"}:
        budgets["sector"] = (
            cap(effective_limits["max_correlated_exposure_pct"]) - sector_value,
            price,
        )
    share_caps = {
        name: int(budget // unit) if budget > 0 else 0 for name, (budget, unit) in budgets.items()
    }
    shares = min(share_caps.values())
    if shares < 1:
        raise ValueError("paper account risk/cash/concentration limits allow no whole share")
    return shares, {
        "policy": "conservative-long-only-v1",
        "equity": str(equity),
        "cash": str(cash),
        "reserved_collateral": str(reserved),
        "gross_before": str(gross),
        "open_risk_before": str(open_risk),
        "symbol_before": str(symbol_value),
        "sector_before": str(sector_value),
        "sector": sector or None,
        "configured_limits": limits.model_dump(mode="json"),
        "effective_limits": effective_limits,
        "candidate_risk_dollars": str(candidate_risk),
        "risk_per_share": str(risk_per_share),
        "exit_slippage_bps": exit_slippage_bps,
        "accepted_risk_dollars": str(risk_per_share * shares),
        "share_caps": share_caps,
        "shares": shares,
        "reduced": shares < share_caps["candidate_risk"],
        "reductions": [
            name for name, count in share_caps.items() if count < share_caps["candidate_risk"]
        ],
        "binding_caps": [name for name, count in share_caps.items() if count == shares],
        "limit_overrides_narrowed": [
            key for key, value in effective_limits.items() if value < getattr(limits, key)
        ],
    }


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
    # NARROWING refusal (D3 §10.1(3)), and it belongs on the LEDGER function, not
    # only on the automatic path: accept_candidate is reachable from cli.py and
    # from app/routers/dashboard.py with no guard at all, so without it a single
    # CLI invocation would put an options structure through the equity ledger —
    # equity sizing, equity cash, an underlying-priced mark. It refuses a class of
    # candidate that did not exist before this commit (structure_kind is NULL on
    # every pre-existing row by the column default) and refuses nothing the
    # function previously accepted.
    if cand.structure_kind is not None:
        raise AutoSimulateForbidden(
            "candidate carries an options structure; the equity ledger cannot size, "
            "fill, or mark it. Use paper.options_ledger.accept_options_candidate."
        )
    if cand.direction is Direction.AVOID:
        raise ValueError("cannot paper-accept an AVOID candidate")

    inst = session.get(Instrument, cand.instrument_id)
    assert inst is not None
    acct = _account(session, account_name)
    if actor == "auto_simulate":
        # Direct calls cannot bypass the automatic strategy/scope/freshness guard.
        assert_auto_simulate_allowed(session, cand)
        if as_of is not None:
            raise AutoSimulateForbidden("automatic acceptance cannot backdate its fill")
    acceptance_context = (
        _acceptance_freshness(session, cand, utcnow())
        if as_of is None
        else {"mode": "historical_replay", "as_of": as_of.isoformat()}
    )

    assert_equity_instrument(inst, "accept_candidate")
    if cand.direction is not Direction.LONG:
        raise ValueError("paper acceptance is long-only")
    entry_ref = (cand.entry_zone_low + cand.entry_zone_high) / 2.0
    stop = _finite_decimal(cand.invalidation_level, "stop")
    entry = _finite_decimal(entry_ref, "entry")
    risk_budget = _finite_decimal(cand.risk_dollars, "candidate risk")
    slip_bps = _finite_decimal(slippage_bps if slippage_bps is not None else 3.0, "slippage")
    if entry <= 0 or stop <= 0 or stop >= entry:
        raise ValueError("long entry must be positive and above a positive stop")
    if risk_budget <= 0 or slip_bps < 0:
        raise ValueError("candidate risk must be positive and slippage nonnegative")
    side = PositionSide.LONG
    slip = _slippage_frac(float(slip_bps), _NOMINAL_SPREAD_BPS)
    # Size, debit and report the SAME cents-denominated execution price.
    fill_price = float(_money(entry_ref * (1 + slip)))
    if Decimal(str(fill_price)) <= stop:
        raise ValueError("rounded fill must be above stop")
    shares, risk_decision = _safe_shares(
        session,
        acct,
        inst,
        Decimal(str(fill_price)),
        stop,
        risk_budget,
        as_of or utcnow().date(),
        _as_dt(as_of) + timedelta(days=1, microseconds=-1) if as_of else utcnow(),
        max(3.0, float(slip_bps)),
    )

    spread_cost = _money(abs(entry_ref) * shares * (_NOMINAL_SPREAD_BPS / 10_000.0) / 2.0)
    # Include cents rounding in attribution so components reconcile to cash.
    slippage_cost = _money((fill_price - entry_ref) * shares) - spread_cost
    if slippage_cost < 0:
        slippage_cost = Decimal("0")
    commission = Decimal("0")
    notional = _money(fill_price * shares)
    total_cost = spread_cost + slippage_cost + commission

    now = utcnow()
    execution_at = _as_dt(as_of) if as_of is not None else now
    order = PaperOrder(
        account_id=acct.id,
        candidate_id=cand.id,
        instrument_id=inst.id,
        side=side,
        qty=shares,
        order_type="market",
        submitted_at=execution_at,
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
        filled_at=execution_at,
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
        stop_level=float(stop),
        target_level=cand.target_level,
        time_stop_date=_time_stop_date(as_of or now.date(), cand.time_stop_days),
        opened_at=execution_at,
    )
    session.add(position)
    session.flush()

    # Spread/slippage are embedded in the fill; these fields are attribution.
    acct.cash = acct.cash - notional - commission

    trade = PaperTrade(
        account_id=acct.id,
        candidate_id=cand.id,
        position_id=position.id,
        decision=PaperDecision.ACCEPTED,
        signal_snapshot_json=_candidate_snapshot(session, cand)
        | {"decision": {"actor": actor, "note": note, "automatic": actor == "auto_simulate"}},
        plan_json=_plan(cand)
        | {
            "shares": shares,
            "fill_price": round(fill_price, 4),
            "acceptance_context": acceptance_context,
            "risk_decision": risk_decision,
        },
        why_qualified="; ".join(cand.reasons_qualify),
        why_might_fail="; ".join(cand.reasons_fail),
        # The same ``actor`` that is frozen into the snapshot JSON, also written
        # to the indexed column an order-authorisation predicate reads (D6 §5.3).
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
    # Serialize closing with acceptance and refresh stale identity-map cash.
    session.flush()
    session.execute(
        update(PaperAccount).where(PaperAccount.id == acct.id).values(cash=PaperAccount.cash)
    )
    session.refresh(acct)
    on = as_of or utcnow().date()
    open_positions = list(
        session.scalars(
            select(PaperPosition)
            .where(PaperPosition.account_id == acct.id, PaperPosition.closed_at.is_(None))
            .execution_options(populate_existing=True)
        )
    )
    realized = 0.0
    unrealized = 0.0
    closed = 0
    for pos in open_positions:
        inst = session.get(Instrument, pos.instrument_id)
        assert inst is not None
        # NARROWS, never widens (map §3.3, D3 §7.1): the same predicate
        # ``assert_auto_simulate_allowed`` already applies, applied at the second
        # place it matters. Provably a no-op against current data.
        assert_equity_instrument(inst, "mark_to_market")
        bars = _position_bars(
            session, pos, inst.symbol, pos.opened_at.date() + timedelta(days=1), on
        )
        bars = [
            bar
            for bar in bars
            if (bounds := rth_bounds_utc(bar.session_date)) is not None
            and (as_of is not None or bounds[1] <= utcnow())
        ]
        if not bars:
            continue
        # Do not skip suspect history: an unknown earlier stop cannot be
        # reconstructed from a later clean bar. Refuse before changing cash.
        for bar in bars:
            if not _mark_quality_ok(bar):
                raise ValueError("untrusted source bar in paper exit history")
            o, h, low, close, volume = (
                _finite_decimal(value, "exit OHLCV")
                for value in (bar.open, bar.high, bar.low, bar.close, bar.volume)
            )
            if not (0 < low <= min(o, close) <= max(o, close) <= h and volume >= 0):
                raise ValueError("inconsistent OHLCV in paper exit history")
        last = bars[-1]
        d = 1 if pos.side is PositionSide.LONG else -1
        # Daily OHLC cannot order entry-day events. Use only subsequent bars,
        # chronologically, so missed polling days cannot hide an earlier exit.
        exit_reason = None
        for bar in bars:
            exit_reason = _exit_reason(pos, bar, bar.session_date)
            if exit_reason:
                last = bar
                break
        if exit_reason:
            exit_px = _exit_price(pos, last, exit_reason)
            if exit_reason == "stop":
                exit_px = (
                    min(exit_px, float(last.open)) if d == 1 else max(exit_px, float(last.open))
                )
            exit_slippage = _exit_slippage(session, pos)
            exit_px = float(
                _money(exit_px * (1 - d * _slippage_frac(exit_slippage, _NOMINAL_SPREAD_BPS)))
            )
            pnl = d * (exit_px - float(pos.avg_price)) * pos.qty
            bounds = rth_bounds_utc(last.session_date)
            assert bounds is not None
            pos.closed_at = bounds[1]
            pos.realized_pnl = _money(pnl)
            # Cash model: a long tied up notional on open, so it gets exit proceeds
            # back; a short only paid costs on open, so it gets the realised P&L.
            if pos.side is PositionSide.LONG:
                acct.cash = acct.cash + _money(exit_px * pos.qty)
            else:
                acct.cash = acct.cash + _money(pnl)
            session.add(
                AuditLog(
                    ts=utcnow(),
                    actor="paper.ledger",
                    action="paper.position_closed",
                    entity=f"paper_position:{pos.id}",
                    before_json={},
                    after_json={
                        "source": last.source,
                        "market_date": last.session_date.isoformat(),
                        "exit_reason": exit_reason,
                        "fill_price": exit_px,
                        "slippage_bps": exit_slippage,
                        "spread_bps": _NOMINAL_SPREAD_BPS,
                        "time_semantics": "daily bar close; intrabar fill time unknown",
                    },
                )
            )
            realized += pnl
            closed += 1
            _log.info("paper.close", symbol=inst.symbol, reason=exit_reason, pnl=round(pnl, 2))
        else:
            unrealized += d * (float(last.close) - float(pos.avg_price)) * pos.qty
    session.flush()  # A repeated call in this transaction must not close/credit twice.
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
    """Every condition an automatic (non-manual) EQUITY paper acceptance needs:

    * the candidate carries NO options structure (``structure_kind is None``) —
      an options structure is refused here and handled by the SECOND guard,
      ``paper.options_ledger.assert_options_auto_simulate_allowed``;
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

    # NARROWING refusal, FIRST, before every existing check (D3 §10.1(2)). An
    # options candidate points its ``instrument_id`` at the UNDERLYING — SPY's
    # instrument_type is 'etf' — so it would PASS the instrument-type check below
    # and be accepted through the equity ledger. This closes that route; it
    # refuses nothing the guard previously accepted.
    if cand.structure_kind is not None:
        raise AutoSimulateForbidden(
            "candidate carries an options structure; the equity auto-simulate path "
            "cannot size, fill, or mark it. "
            "Use paper.options_ledger.assert_options_auto_simulate_allowed."
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
    _acceptance_freshness(session, cand, utcnow())
