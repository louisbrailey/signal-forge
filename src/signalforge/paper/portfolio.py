"""Paper-account portfolio snapshot: cash, positions, P&L, exposure, drawdown.

Since 2026-10-03 the equity paper ledger is a set of BOOKS, one per
PAPER_APPROVED strategy version (``paper.books``). ``portfolio_snapshot`` with
no account name is the aggregate over every equity book; it also carries one
row per book (``books``) and the combined exposure per symbol across books
(``symbol_exposure``), because two books may hold the same symbol at once and
each book's own caps cannot see the other's position.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from signalforge.data.repository import get_daily_bars
from signalforge.db.models import Instrument, PaperAccount, PaperPosition
from signalforge.domain import PositionSide
from signalforge.paper.books import book_label, equity_books
from signalforge.paper.equity_guard import assert_equity_instrument
from signalforge.risk.portfolio import Holding, exposure_report


def _last_close(session: Session, symbol: str, on: date) -> float | None:
    bars = get_daily_bars(session, symbol, on - timedelta(days=10), on)
    return float(bars[-1].close) if bars else None


def _account_snapshot(
    session: Session, acct: PaperAccount, on: date
) -> tuple[dict[str, Any], list[Holding]]:
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
    label = book_label(session, acct)

    positions_out: list[dict[str, Any]] = []
    holdings: list[Holding] = []
    unrealized = 0.0
    for pos in open_positions:
        inst = session.get(Instrument, pos.instrument_id)
        assert inst is not None
        # The same defect as ``mark_to_market``'s, at the same place: every open
        # position is priced from the UNDERLYING's bars. map §3.3 names only
        # ``mark_to_market``; the assertion belongs here too, and is equally a
        # no-op today (D3 §7.2).
        assert_equity_instrument(inst, "portfolio_snapshot")
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
                "book": label,
                "account": acct.name,
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

    return (
        {
            "exists": True,
            "account": acct.name,
            "book": label,
            "strategy_version_id": acct.strategy_version_id,
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
        },
        holdings,
    )


def _symbol_exposure(books: list[dict[str, Any]], total_equity: float) -> list[dict[str, Any]]:
    """Combined exposure per symbol ACROSS books (largest first)."""
    by_symbol: dict[str, dict[str, Any]] = {}
    for book in books:
        for pos in book["open_positions"]:
            sign = 1.0 if pos["side"] == PositionSide.LONG.value else -1.0
            row = by_symbol.setdefault(
                pos["symbol"], {"symbol": pos["symbol"], "qty": 0, "market_value": 0.0, "books": []}
            )
            row["qty"] += pos["qty"]
            row["market_value"] += float(pos["last_price"]) * pos["qty"] * sign
            if book["book"] not in row["books"]:
                row["books"].append(book["book"])
    out = []
    for row in by_symbol.values():
        mv = row["market_value"]
        out.append(
            {
                **row,
                "market_value": round(mv, 2),
                "pct_of_combined_equity": (
                    round(abs(mv) / total_equity * 100.0, 2) if total_equity > 0 else 0.0
                ),
            }
        )
    return sorted(out, key=lambda r: (-abs(r["market_value"]), r["symbol"]))


def portfolio_snapshot(
    session: Session, *, account_name: str | None = None, as_of: date | None = None
) -> dict[str, Any]:
    """Snapshot of one named account, or — with no name — the aggregate of every
    equity book, with a per-book breakdown and cross-book symbol exposure."""
    on = as_of or date.today()
    if account_name is not None:
        named = session.scalar(select(PaperAccount).where(PaperAccount.name == account_name))
        accounts = [named] if named is not None else []
    else:
        accounts = equity_books(session)
    if not accounts:
        return {"exists": False}

    books: list[dict[str, Any]] = []
    holdings: list[Holding] = []
    for acct in accounts:
        snap, held = _account_snapshot(session, acct, on)
        books.append(snap)
        holdings.extend(held)

    initial = sum(b["initial_cash"] for b in books)
    equity = sum(b["equity_estimate"] for b in books)
    book_rows = [
        {k: v for k, v in b.items() if k not in ("open_positions", "exists")} for b in books
    ]
    return {
        "exists": True,
        "account": books[0]["account"] if len(books) == 1 else "all equity books",
        "initial_cash": initial,
        "cash": round(sum(b["cash"] for b in books), 2),
        "open_positions": [p for b in books for p in b["open_positions"]],
        "n_open": sum(b["n_open"] for b in books),
        "n_closed": sum(b["n_closed"] for b in books),
        "unrealized_pnl": round(sum(b["unrealized_pnl"] for b in books), 2),
        "realized_pnl": round(sum(b["realized_pnl"] for b in books), 2),
        "equity_estimate": round(equity, 2),
        "return_pct": round((equity / initial - 1.0) * 100.0, 2),
        "exposure": exposure_report(holdings, account_equity=initial).to_dict(),
        "books": book_rows,
        "symbol_exposure": _symbol_exposure(books, equity),
    }
