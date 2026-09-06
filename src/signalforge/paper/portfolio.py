"""Paper-account portfolio snapshot: cash, positions, P&L, exposure, drawdown."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from signalforge.data.repository import get_daily_bars
from signalforge.db.models import Instrument, PaperAccount, PaperPosition
from signalforge.domain import PositionSide
from signalforge.risk.portfolio import Holding, exposure_report


def _last_close(session: Session, symbol: str, on: date) -> float | None:
    bars = get_daily_bars(session, symbol, on - timedelta(days=10), on)
    return float(bars[-1].close) if bars else None


def portfolio_snapshot(
    session: Session, *, account_name: str = "default", as_of: date | None = None
) -> dict[str, Any]:
    on = as_of or date.today()
    acct = session.scalar(select(PaperAccount).where(PaperAccount.name == account_name))
    if acct is None:
        return {"exists": False}

    open_positions = list(
        session.scalars(
            select(PaperPosition).where(
                PaperPosition.account_id == acct.id, PaperPosition.closed_at.is_(None)
            )
        )
    )
    closed_positions = list(
        session.scalars(
            select(PaperPosition).where(
                PaperPosition.account_id == acct.id, PaperPosition.closed_at.is_not(None)
            )
        )
    )

    positions_out: list[dict[str, Any]] = []
    holdings: list[Holding] = []
    unrealized = 0.0
    for pos in open_positions:
        inst = session.get(Instrument, pos.instrument_id)
        assert inst is not None
        px = _last_close(session, inst.symbol, on) or float(pos.avg_price)
        d = 1 if pos.side is PositionSide.LONG else -1
        mv = px * pos.qty * d
        pnl = d * (px - float(pos.avg_price)) * pos.qty
        unrealized += pnl
        holdings.append(
            Holding(symbol=inst.symbol, sector=inst.sector or "unknown", market_value=mv)
        )
        positions_out.append(
            {
                "symbol": inst.symbol,
                "side": pos.side.value,
                "qty": pos.qty,
                "avg_price": float(pos.avg_price),
                "last_price": round(px, 4),
                "unrealized_pnl": round(pnl, 2),
                "stop": pos.stop_level,
                "target": pos.target_level,
                "horizon": pos.horizon.value,
            }
        )

    realized = sum(float(p.realized_pnl) for p in closed_positions)
    cash = float(acct.cash)
    # Longs had their notional debited on open, so they add back market value;
    # shorts only paid costs on open, so they add their unrealised P&L.
    long_mv = sum(h.market_value for h in holdings if h.market_value > 0)
    short_pnl = sum(
        p["unrealized_pnl"] for p in positions_out if p["side"] == PositionSide.SHORT.value
    )
    equity = cash + long_mv + short_pnl
    exposure = exposure_report(holdings, account_equity=float(acct.initial_cash))

    return {
        "exists": True,
        "account": acct.name,
        "initial_cash": float(acct.initial_cash),
        "cash": round(cash, 2),
        "open_positions": positions_out,
        "n_open": len(open_positions),
        "n_closed": len(closed_positions),
        "unrealized_pnl": round(unrealized, 2),
        "realized_pnl": round(realized, 2),
        "equity_estimate": round(equity, 2),
        "return_pct": round((equity / float(acct.initial_cash) - 1.0) * 100.0, 2),
        "exposure": exposure.to_dict(),
    }
