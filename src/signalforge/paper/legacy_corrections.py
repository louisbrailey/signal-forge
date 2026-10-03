"""Append-only corrections for two defects of the pre-2026-10-02 paper ledger.

``signalforge paper correct-legacy --dry-run | --confirm``.

1. **Impossible exit chronology.** The old ``mark_to_market`` tested a position
   against the latest stored bar — including the ENTRY-day bar, whose low
   preceded the post-close fill — and stamped the close at 00:00 UTC of the
   mark date. A position could therefore be "stopped" on the day it was
   opened, before it was opened. Any closed position whose exit date is not
   after its entry date is such a row. The correction reverses the invalid
   exit (takes the exit proceeds back out of the book's cash, zeroes the
   realised P&L, re-opens the position) and then RE-RESOLVES it with the
   current ledger rules: only bars strictly after the entry date, in order,
   stop before target, bar-based time stop. It either stays open or closes on
   a later, valid bar.

2. **Double-counted entry costs.** The old ``accept_candidate`` embedded
   spread + slippage in the fill price AND debited ``spread_cost + slippage +
   commission`` from cash a second time. Every accepted long trade recorded by
   that code (recognisable because its immutable ``plan_json`` has no
   ``risk_decision``) had its book's cash over-debited by exactly the cost
   attribution on its fill. The correction credits that amount back.

What is and is not rewritten: ``paper_trade`` rows are immutable (S9) and are
never touched; every change is recorded as ``trade_correction`` rows that
reference the trade and carry the old and new values. The mutable state the
ledger actually runs on (``paper_position.closed_at`` / ``realized_pnl``,
``paper_account.cash``) is corrected, with its previous value preserved in
those rows. Idempotent: a corrected position no longer matches the finder, and
a cost credit is skipped when its correction row already exists.

Not decided here: an entry that only happened BECAUSE an earlier position was
wrongly closed (a second position in a symbol the book would still have held)
is re-opened like any other and reported as a duplicate. Voiding an ACCEPTED
decision is an operator judgement, not a chronology fix.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from signalforge.db.models import (
    Instrument,
    PaperAccount,
    PaperFill,
    PaperOrder,
    PaperPosition,
    PaperTrade,
    TradeCorrection,
)
from signalforge.domain import PaperDecision, PositionSide
from signalforge.observability import get_logger
from signalforge.paper import ledger as _ledger
from signalforge.paper.books import equity_books
from signalforge.paper.corrections import record_correction
from signalforge.paper.ledger import _mark_position, _money, migrate_time_stops_to_sessions

__all__ = [
    "ACTOR",
    "FIELD_CASH",
    "FIELD_CLOSED_AT",
    "FIELD_ENTRY_COST",
    "FIELD_REALIZED",
    "LegacyCorrectionReport",
    "correct_legacy",
    "find_invalid_exits",
]

_log = get_logger("paper.legacy_corrections")

ACTOR = "paper.correct_legacy"
FIELD_CLOSED_AT = "legacy_exit.position.closed_at"
FIELD_REALIZED = "legacy_exit.position.realized_pnl"
FIELD_CASH = "legacy_exit.account.cash"
FIELD_ENTRY_COST = "legacy_entry_cost_double_count"


@dataclass(slots=True)
class LegacyCorrectionReport:
    confirm: bool
    exits: list[dict[str, Any]] = field(default_factory=list)
    entry_costs: list[dict[str, Any]] = field(default_factory=list)
    books: list[dict[str, Any]] = field(default_factory=list)
    duplicates: list[dict[str, Any]] = field(default_factory=list)
    corrections_written: int = 0

    @property
    def changed(self) -> bool:
        return bool(self.exits or self.entry_costs)

    def lines(self) -> list[str]:
        mode = "CONFIRMED — written" if self.confirm else "DRY RUN — nothing written"
        out = [f"paper correct-legacy: {mode}"]
        if not self.changed:
            out.append("  nothing to correct (no invalid legacy exit, no uncredited legacy cost)")
            return out
        out.append(f"  invalid legacy exits reversed: {len(self.exits)}")
        for e in self.exits:
            out.append(
                f"    trade #{e['paper_trade_id']} position #{e['position_id']} {e['symbol']} "
                f"x{e['qty']} [{e['account']}]: entered {e['opened_at']}, legacy exit "
                f"{e['legacy_closed_at']} (not after entry), legacy realized "
                f"{e['legacy_realized_pnl']}; exit proceeds {e['proceeds_reversed']} taken back; "
                f"result: {e['outcome']}"
            )
        out.append(f"  legacy double-counted entry costs credited back: {len(self.entry_costs)}")
        for c in self.entry_costs:
            out.append(
                f"    trade #{c['paper_trade_id']} {c['symbol']} [{c['account']}]: +{c['amount']}"
            )
        for b in self.books:
            out.append(
                f"  book {b['account']}: cash {b['cash_before']} -> {b['cash_after']} "
                f"(delta {b['delta']})"
            )
        for d in self.duplicates:
            out.append(
                f"  WARNING duplicate open positions after correction: {d['symbol']} "
                f"[{d['account']}] positions {d['position_ids']} (total qty {d['qty']}). "
                "They are NOT merged or voided; they count toward this book's caps."
            )
        out.append(f"  trade_correction rows: {self.corrections_written}")
        return out


def _accepted_trade(session: Session, position_id: int) -> PaperTrade | None:
    return session.scalar(
        select(PaperTrade)
        .where(PaperTrade.position_id == position_id, PaperTrade.decision == PaperDecision.ACCEPTED)
        .order_by(PaperTrade.id)
    )


def find_invalid_exits(session: Session) -> list[tuple[PaperPosition, PaperTrade]]:
    """Closed equity-book positions whose exit is not after the entry bar,
    oldest entry first, each with the ACCEPTED trade that opened it."""
    account_ids = [a.id for a in equity_books(session)]
    if not account_ids:
        return []
    rows = session.scalars(
        select(PaperPosition)
        .where(PaperPosition.account_id.in_(account_ids), PaperPosition.closed_at.is_not(None))
        .order_by(PaperPosition.opened_at, PaperPosition.id)
        .execution_options(populate_existing=True)
    ).all()
    out: list[tuple[PaperPosition, PaperTrade]] = []
    for pos in rows:
        assert pos.closed_at is not None
        if pos.closed_at.date() > pos.opened_at.date():
            continue
        trade = _accepted_trade(session, pos.id)
        if trade is not None:  # corrections must reference a paper_trade
            out.append((pos, trade))
    return out


def _has_correction(session: Session, paper_trade_id: int, field_name: str) -> bool:
    return (
        session.scalar(
            select(TradeCorrection.id)
            .where(
                TradeCorrection.paper_trade_id == paper_trade_id,
                TradeCorrection.field == field_name,
            )
            .limit(1)
        )
        is not None
    )


def _reverse_exit(
    session: Session, pos: PaperPosition, trade: PaperTrade, rep: LegacyCorrectionReport
) -> None:
    acct = session.get(PaperAccount, pos.account_id)
    inst = session.get(Instrument, pos.instrument_id)
    assert acct is not None and inst is not None and pos.closed_at is not None
    legacy_closed = pos.closed_at
    legacy_realized = Decimal(pos.realized_pnl)
    cash_before = Decimal(acct.cash)
    # The old close credited a long its exit proceeds (= cost basis + realised
    # P&L) and a short its realised P&L. Take exactly that back.
    if pos.side is PositionSide.LONG:
        proceeds = _money(float(Decimal(pos.avg_price) * pos.qty + legacy_realized))
    else:
        proceeds = _money(float(legacy_realized))
    if cash_before - proceeds < 0:
        raise ValueError(
            f"reversing the legacy exit of position {pos.id} would make book "
            f"{acct.name!r} cash negative; refusing"
        )
    acct.cash = cash_before - proceeds
    pos.closed_at = None
    pos.realized_pnl = Decimal("0")
    session.flush()

    # Corrected chronology: bar-based time stop, then bars strictly after entry.
    migrate_time_stops_to_sessions(session, account_id=acct.id)
    closed, pnl = _mark_position(session, acct, pos, _ledger.utcnow().date(), None)
    session.flush()
    if closed:
        assert pos.closed_at is not None
        outcome = (
            f"re-resolved: closed {pos.closed_at.isoformat()} on a bar after entry, "
            f"realized {Decimal(pos.realized_pnl):.2f}"
        )
    else:
        outcome = f"re-opened (no exit on any bar after entry; unrealized {pnl:+.2f})"
    reason = (
        f"Legacy exit dated {legacy_closed.date().isoformat()} is not after the entry bar "
        f"({pos.opened_at.date().isoformat()}): the pre-2026-10-02 ledger tested the entry-day "
        f"bar, whose range preceded the fill. Exit reversed and position {outcome} under the "
        "corrected chronology (bars strictly after entry only). Original paper_trade untouched."
    )
    for field_name, old, new in (
        (
            FIELD_CLOSED_AT,
            legacy_closed.isoformat(),
            pos.closed_at.isoformat() if pos.closed_at is not None else "",
        ),
        (FIELD_REALIZED, f"{legacy_realized:.2f}", f"{Decimal(pos.realized_pnl):.2f}"),
        (FIELD_CASH, f"{cash_before:.2f}", f"{Decimal(acct.cash):.2f}"),
    ):
        record_correction(
            session,
            trade.id,
            field=field_name,
            old_value=old,
            new_value=new,
            reason=reason,
            actor=ACTOR,
        )
        rep.corrections_written += 1
    rep.exits.append(
        {
            "paper_trade_id": trade.id,
            "position_id": pos.id,
            "symbol": inst.symbol,
            "qty": pos.qty,
            "account": acct.name,
            "opened_at": pos.opened_at.isoformat(),
            "legacy_closed_at": legacy_closed.isoformat(),
            "legacy_realized_pnl": f"{legacy_realized:.2f}",
            "proceeds_reversed": f"{proceeds:.2f}",
            "outcome": outcome,
            "closed_at": pos.closed_at.isoformat() if pos.closed_at is not None else None,
            "realized_pnl": f"{Decimal(pos.realized_pnl):.2f}",
        }
    )


def _credit_entry_costs(session: Session, rep: LegacyCorrectionReport) -> None:
    account_ids = [a.id for a in equity_books(session)]
    trades = session.scalars(
        select(PaperTrade)
        .where(
            PaperTrade.account_id.in_(account_ids),
            PaperTrade.decision == PaperDecision.ACCEPTED,
            PaperTrade.position_id.is_not(None),
        )
        .order_by(PaperTrade.id)
    ).all()
    for trade in trades:
        # Only the pre-fix ledger omitted ``risk_decision``; only it double-debited.
        if "risk_decision" in (trade.plan_json or {}):
            continue
        if _has_correction(session, trade.id, FIELD_ENTRY_COST):
            continue
        if trade.candidate_id is None:
            continue  # the fill cannot be attributed to this trade; credit nothing
        assert trade.position_id is not None
        pos = session.get(PaperPosition, trade.position_id)
        if pos is None or pos.side is not PositionSide.LONG:
            continue
        fills = session.scalars(
            select(PaperFill)
            .join(PaperOrder, PaperFill.order_id == PaperOrder.id)
            .where(
                PaperOrder.account_id == trade.account_id,
                PaperOrder.candidate_id == trade.candidate_id,
                PaperOrder.instrument_id == pos.instrument_id,
            )
        ).all()
        amount = sum(
            (Decimal(f.spread_cost) + Decimal(f.slippage) + Decimal(f.commission) for f in fills),
            Decimal("0"),
        )
        if amount <= 0:
            continue
        acct = session.get(PaperAccount, trade.account_id)
        inst = session.get(Instrument, pos.instrument_id)
        assert acct is not None and inst is not None
        acct.cash = Decimal(acct.cash) + amount
        session.flush()
        record_correction(
            session,
            trade.id,
            field=FIELD_ENTRY_COST,
            old_value=f"{amount:.2f}",
            new_value="0.00",
            reason=(
                "The pre-2026-10-02 ledger embedded spread+slippage in the fill price and also "
                "debited the same cost from cash (notional + total_cost). The second debit of "
                f"{amount:.2f} is credited back to book {acct.name!r}. Fill and paper_trade "
                "rows are untouched."
            ),
            actor=ACTOR,
        )
        rep.corrections_written += 1
        rep.entry_costs.append(
            {
                "paper_trade_id": trade.id,
                "symbol": inst.symbol,
                "account": acct.name,
                "amount": f"{amount:.2f}",
            }
        )


def correct_legacy(session: Session, *, confirm: bool) -> LegacyCorrectionReport:
    """Find and correct the legacy defects. With ``confirm=False`` every change
    is computed through exactly the same code path inside a savepoint that is
    then rolled back, so the dry-run report is what ``--confirm`` will do and
    the database is left untouched. The caller owns commit."""
    rep = LegacyCorrectionReport(confirm=confirm)
    books = equity_books(session)
    before = {a.id: Decimal(a.cash) for a in books}
    savepoint = session.begin_nested()
    try:
        for pos, trade in find_invalid_exits(session):
            _reverse_exit(session, pos, trade, rep)
        _credit_entry_costs(session, rep)
        session.flush()
        for acct in books:
            session.refresh(acct)
            after = Decimal(acct.cash)
            if after != before[acct.id]:
                rep.books.append(
                    {
                        "account": acct.name,
                        "cash_before": f"{before[acct.id]:.2f}",
                        "cash_after": f"{after:.2f}",
                        "delta": f"{after - before[acct.id]:+.2f}",
                    }
                )
            open_by_inst: dict[int, list[PaperPosition]] = {}
            for p in session.scalars(
                select(PaperPosition)
                .where(PaperPosition.account_id == acct.id, PaperPosition.closed_at.is_(None))
                .order_by(PaperPosition.id)
            ):
                open_by_inst.setdefault(p.instrument_id, []).append(p)
            for inst_id, group in open_by_inst.items():
                if len(group) > 1 and rep.changed:
                    inst = session.get(Instrument, inst_id)
                    rep.duplicates.append(
                        {
                            "account": acct.name,
                            "symbol": inst.symbol if inst else str(inst_id),
                            "position_ids": [p.id for p in group],
                            "qty": sum(p.qty for p in group),
                        }
                    )
    except Exception:
        savepoint.rollback()
        raise
    if confirm:
        savepoint.commit()
        _log.info(
            "paper.correct_legacy",
            exits=len(rep.exits),
            entry_costs=len(rep.entry_costs),
            corrections=rep.corrections_written,
        )
    else:
        savepoint.rollback()
        session.expire_all()
    return rep
