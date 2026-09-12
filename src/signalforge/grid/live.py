"""The live (paper) daily grid job.

What it does, once per day, after ``daily_eod_update`` has ingested the day's
completed bars:

* evaluate the grid rule on each symbol's **previous** session close — the same
  :func:`signalforge.grid.engine.decide` the backtest uses, not a copy;
* fill any triggered order at **today's open**, through the same
  :func:`signalforge.grid.engine.execute_fill` the backtest uses;
* write one immutable ``grid_trade`` row plus an ``AuditLog('grid.trade')``
  entry per fill, and update ``grid_position`` and the dedicated paper account's
  cash.

Safety:

* the kill switch is checked first (invariant S6) — engaged means no-op;
* ``research.grid.enabled`` is False by default — disabled means no-op;
* idempotent per ``(account, symbol, session_date)``: a re-run for a session
  already traded skips the symbol, and the unique constraint on ``grid_trade``
  is the backstop;
* a dedicated ``PaperAccount`` (default name ``grid``) with its own cash — the
  grid can never touch the research paper account;
* long reads happen with write intent dropped, so the SQLite write lock is only
  held for the short write phase (see ``docs/SQLITE_CONCURRENCY.md`` rule 4).

Every fill is SIMULATED. This module contacts no brokerage; orders exist only in the
execution layer, which is off by default and never armed without the operator.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from signalforge import RESEARCH_ONLY_NOTICE
from signalforge.config.research import GridConfig
from signalforge.data.repository import get_daily_bars
from signalforge.db.models import AuditLog, GridPosition, GridTradeRow, PaperAccount
from signalforge.db.session import set_write_intent
from signalforge.db.types import utcnow
from signalforge.grid.config import GridParams
from signalforge.grid.engine import BUY, NONE, GridState, GridTrade, decide, execute_fill
from signalforge.grid.universe import load_universe
from signalforge.killswitch import ensure_not_engaged
from signalforge.observability import get_logger

__all__ = [
    "GridDailyResult",
    "MAX_BAR_STALENESS_DAYS",
    "params_from_config",
    "ensure_grid_account",
    "run_grid_daily",
]

_log = get_logger("grid.live")

# A symbol whose most recent bar is older than this (calendar days before the
# run date) is skipped rather than filled at a stale open.
MAX_BAR_STALENESS_DAYS = 5
# How far back to look for the two bars the rule needs (previous close + today's open).
_LOOKBACK_DAYS = 20
_QUANT = Decimal("0.000001")


def _dec(x: float) -> Decimal:
    return Decimal(str(round(float(x), 6))).quantize(_QUANT)


@dataclass(slots=True)
class GridDailyResult:
    ran: bool
    reason: str
    account: str = ""
    universe_size: int = 0
    evaluated: int = 0
    buys: int = 0
    sells: int = 0
    tracking_started: int = 0
    reanchored: int = 0
    already_done: int = 0
    no_data: int = 0
    stale: int = 0
    skipped_triggers: dict[str, int] = field(default_factory=dict)
    cash_after: float = 0.0
    sessions: dict[str, int] = field(default_factory=dict)

    @property
    def trades(self) -> int:
        return self.buys + self.sells

    def to_dict(self) -> dict[str, Any]:
        return {
            "ran": self.ran,
            "reason": self.reason,
            "account": self.account,
            "universe_size": self.universe_size,
            "evaluated": self.evaluated,
            "buys": self.buys,
            "sells": self.sells,
            "trades": self.trades,
            "tracking_started": self.tracking_started,
            "reanchored": self.reanchored,
            "already_done": self.already_done,
            "no_data": self.no_data,
            "stale": self.stale,
            "skipped_triggers": dict(self.skipped_triggers),
            "cash_after": round(self.cash_after, 2),
            "sessions": dict(self.sessions),
        }


def params_from_config(
    cfg: GridConfig, *, slippage_bps: float = 3.0, spread_bps: float = 5.0
) -> GridParams:
    """The live ``GridConfig`` as engine ``GridParams`` (identical arithmetic)."""
    return GridParams(
        starting_cash=float(cfg.starting_cash),
        per_symbol_cap=float(cfg.per_symbol_cap),
        buy_usd=float(cfg.buy_usd),
        sell_usd=float(cfg.sell_usd),
        drop_pct=float(cfg.drop_pct),
        rise_pct=float(cfg.rise_pct),
        min_order_usd=float(cfg.min_order_usd),
        reanchor_on_untradeable_rise=bool(cfg.reanchor_on_untradeable_rise),
        slippage_bps=slippage_bps,
        spread_bps=spread_bps,
        universe_name=cfg.universe_name,
        universe_size=int(cfg.universe_size),
    )


def ensure_grid_account(session: Session, cfg: GridConfig) -> PaperAccount:
    """The dedicated grid paper account, created with its own cash if absent."""
    acct = session.scalar(select(PaperAccount).where(PaperAccount.name == cfg.account_name))
    if acct is None:
        acct = PaperAccount(
            name=cfg.account_name,
            initial_cash=_dec(float(cfg.starting_cash)),
            cash=_dec(float(cfg.starting_cash)),
        )
        session.add(acct)
        session.flush()
        _log.info("grid.account_created", name=cfg.account_name, cash=float(cfg.starting_cash))
    return acct


@dataclass(slots=True)
class _Bars:
    """The two bars one evaluation needs."""

    decision_date: date
    decision_close: float
    session_date: date
    session_open: float


def _load_bars(session: Session, symbol: str, as_of: date, source: str) -> tuple[_Bars | None, str]:
    rows = get_daily_bars(
        session, symbol, as_of - timedelta(days=_LOOKBACK_DAYS), as_of, source=source or None
    )
    if len(rows) < 2:
        return None, "no_data"
    prev, last = rows[-2], rows[-1]
    if (as_of - last.session_date).days > MAX_BAR_STALENESS_DAYS:
        return None, "stale"
    if last.open is None or last.open <= 0 or prev.close is None or prev.close <= 0:
        return None, "no_data"
    return (
        _Bars(
            decision_date=prev.session_date,
            decision_close=float(prev.close),
            session_date=last.session_date,
            session_open=float(last.open),
        ),
        "",
    )


def run_grid_daily(
    session: Session,
    *,
    cfg: GridConfig | None = None,
    as_of: date | None = None,
    symbols: list[str] | None = None,
) -> GridDailyResult:
    """Run one day of the grid on the dedicated paper account.

    ``session`` should be a write-intent scope; the long read phase runs with
    write intent dropped so the SQLite write lock is held only while writing.
    """
    ensure_not_engaged()

    if cfg is None:
        from signalforge.settings_store import effective_research_config

        cfg = effective_research_config(session).grid
    if not cfg.enabled:
        _log.info("grid.skipped_disabled")
        return GridDailyResult(ran=False, reason="research.grid.enabled is False")

    params = params_from_config(cfg)
    on = as_of or date.today()

    if symbols is None:
        try:
            uni = load_universe(cfg.universe_name, top=int(cfg.universe_size))
        except (FileNotFoundError, ValueError) as exc:
            _log.warning("grid.universe_unavailable", error=repr(exc)[:200])
            return GridDailyResult(ran=False, reason=f"universe unavailable: {exc}")
        order = list(uni.symbols)
    else:
        order = [s.strip().upper() for s in symbols if s.strip()]

    result = GridDailyResult(
        ran=True, reason="ok", account=cfg.account_name, universe_size=len(order)
    )
    if not order:
        result.ran = False
        result.reason = "empty universe"
        return result

    # ---- phase A: reads only, write lock NOT held -------------------------- #
    if session.in_transaction():
        session.commit()
    set_write_intent(session, False)
    bars: dict[str, _Bars] = {}
    for sym in order:
        b, why = _load_bars(session, sym, on, cfg.source)
        if b is None:
            if why == "stale":
                result.stale += 1
            else:
                result.no_data += 1
            continue
        bars[sym] = b
        result.sessions[b.session_date.isoformat()] = (
            result.sessions.get(b.session_date.isoformat(), 0) + 1
        )

    # ---- phase B: the short write phase ------------------------------------ #
    if session.in_transaction():
        session.commit()
    set_write_intent(session, True)

    acct = ensure_grid_account(session, cfg)
    positions = {
        row.symbol: row
        for row in session.scalars(select(GridPosition).where(GridPosition.account_id == acct.id))
    }
    # Idempotency: a (symbol, session_date) already traded is skipped entirely.
    session_dates = {b.session_date for b in bars.values()}
    done = {
        sym
        for sym, sd in session.execute(
            select(GridTradeRow.symbol, GridTradeRow.session_date).where(
                GridTradeRow.account_id == acct.id,
                GridTradeRow.session_date.in_(sorted(session_dates)),
            )
        )
        if sym in bars and sd == bars[sym].session_date
    }
    cash = float(acct.cash)
    now = utcnow()

    for sym in order:
        b = bars.get(sym)
        if b is None:
            continue
        if sym in done:
            result.already_done += 1
            continue

        pos = positions.get(sym)
        if pos is None:
            # First session tracked: establish the anchor, never trade.
            session.add(
                GridPosition(
                    account_id=acct.id,
                    symbol=sym,
                    qty=Decimal("0"),
                    cost_basis=Decimal("0"),
                    anchor_price=_dec(b.decision_close),
                    opened_at=now,
                    updated_at=now,
                )
            )
            result.tracking_started += 1
            continue

        result.evaluated += 1
        state = GridState(
            symbol=sym,
            qty=float(pos.qty),
            cost_basis=float(pos.cost_basis),
            anchor=float(pos.anchor_price),
            tracking=True,
            last_close=b.decision_close,
        )
        dec = decide(
            close=b.decision_close,
            anchor=state.anchor,
            qty=state.qty,
            cost_basis=state.cost_basis,
            cash=cash,
            params=params,
        )
        if dec.action == NONE:
            if dec.reason != "no_trigger":
                result.skipped_triggers[dec.reason] = result.skipped_triggers.get(dec.reason, 0) + 1
            if dec.reanchor:
                # No order, but the grid ratchets up with price. Re-applying this
                # on a re-run is a no-op (the new anchor no longer triggers), so
                # the job stays idempotent per (symbol, session).
                pos.anchor_price = _dec(b.decision_close)
                pos.updated_at = now
                result.reanchored += 1
            continue

        qty_before, cash_before = state.qty, cash
        trade, cash = execute_fill(
            state, dec, b.decision_date, b.session_date, b.session_open, cash, params
        )
        if trade is None:
            result.skipped_triggers["skip_at_fill"] = (
                result.skipped_triggers.get("skip_at_fill", 0) + 1
            )
            continue

        pos.qty = _dec(state.qty)
        pos.cost_basis = _dec(state.cost_basis)
        pos.anchor_price = _dec(state.anchor)
        pos.updated_at = now
        evidence = _evidence(trade, dec, b, params, cfg)
        session.add(
            GridTradeRow(
                account_id=acct.id,
                symbol=sym,
                side=trade.side,
                qty=_dec(trade.qty),
                price=_dec(trade.price),
                usd=_dec(trade.usd),
                anchor_before=_dec(trade.anchor_before),
                anchor_after=_dec(trade.anchor_after),
                session_date=trade.session_date,
                evidence_json=evidence,
                created_at=now,
            )
        )
        session.add(
            AuditLog(
                ts=datetime.now(UTC),
                actor="grid_daily",
                action="grid.trade",
                entity=f"{cfg.account_name}:{sym}:{trade.session_date.isoformat()}",
                before_json={
                    "qty": round(qty_before, 6),
                    "anchor": round(trade.anchor_before, 6),
                    "cash": round(cash_before, 2),
                },
                after_json={
                    "side": trade.side,
                    "qty": round(trade.qty, 6),
                    "price": round(trade.price, 6),
                    "usd": round(trade.usd, 6),
                    "anchor": round(trade.anchor_after, 6),
                    "cash": round(cash, 2),
                    "notice": RESEARCH_ONLY_NOTICE,
                },
            )
        )
        if trade.side == BUY:
            result.buys += 1
        else:
            result.sells += 1

    acct.cash = _dec(cash)
    result.cash_after = cash
    session.flush()
    _log.info("grid.daily_done", **{k: v for k, v in result.to_dict().items() if k != "sessions"})
    return result


def _evidence(
    trade: GridTrade, dec: Any, bars: _Bars, params: GridParams, cfg: GridConfig
) -> dict[str, Any]:
    """The complete, immutable evidence snapshot stored on every grid trade."""
    from signalforge.gitinfo import git_sha

    return {
        "decision": dec.to_dict(),
        "bars": {
            "decision_date": bars.decision_date.isoformat(),
            "decision_close": round(bars.decision_close, 6),
            "session_date": bars.session_date.isoformat(),
            "session_open": round(bars.session_open, 6),
            "source": cfg.source,
        },
        "fill": {
            "side": trade.side,
            "qty": round(trade.qty, 6),
            "price": round(trade.price, 6),
            "usd": round(trade.usd, 6),
            "raw_open": round(trade.raw_open, 6),
            "realized_pnl": round(trade.realized_pnl, 6),
        },
        "cost": {
            "slippage_bps": params.slippage_bps,
            "spread_bps": params.spread_bps,
            "commission": round(trade.commission, 6),
            "slippage_frac_applied": params.slippage_frac,
            "label": params.costs_label,
        },
        "params": params.to_dict(),
        "code_version": git_sha(),
        "notice": RESEARCH_ONLY_NOTICE,
        "not_promotion_gated": (
            "The grid is a mechanical rebalancing rule, not a registered, "
            "promotion-gated strategy. It has no walk-forward or sealed-test evidence."
        ),
    }
