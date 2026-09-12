"""Mechanical grid strategy: live (paper) state and trade log.

Two tables, both additive and independent of the research/promotion schema:

* ``grid_position`` — current per-symbol state (shares, cost basis, anchor). A
  row with ``qty == 0`` is a *tracking* row: the symbol is watched and carries an
  anchor but holds nothing.
* ``grid_trade`` — the append-only record of every simulated fill. Immutable
  after creation: no code path issues UPDATE or DELETE against it, and
  ``(symbol, session_date)`` is unique, which is what makes the daily job
  idempotent — a re-run for the same session can never double-trade a symbol.

Nothing here is a brokerage order. Every row is a SIMULATED fill on a dedicated
paper account.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import JSON, Date, ForeignKey, Index, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from signalforge.db.base import Base, CreatedAt, IntPK
from signalforge.db.types import UTCDateTime

__all__ = ["GridPosition", "GridTradeRow"]

_MONEY = Numeric(20, 6)
_QTY = Numeric(20, 6)  # fractional shares


class GridPosition(Base, IntPK):
    """Per-symbol grid state on the dedicated paper account."""

    __tablename__ = "grid_position"
    __table_args__ = (
        UniqueConstraint("account_id", "symbol", name="uq_grid_position_account_sym"),
    )

    account_id: Mapped[int] = mapped_column(ForeignKey("paper_account.id", ondelete="CASCADE"))
    symbol: Mapped[str] = mapped_column(String(20), index=True)
    qty: Mapped[Decimal] = mapped_column(_QTY, default=Decimal("0"))
    cost_basis: Mapped[Decimal] = mapped_column(_MONEY, default=Decimal("0"))
    anchor_price: Mapped[Decimal] = mapped_column(_MONEY)
    opened_at: Mapped[datetime] = mapped_column(UTCDateTime)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime)


class GridTradeRow(Base, IntPK, CreatedAt):
    """One simulated grid fill. Append-only; never updated, never deleted."""

    __tablename__ = "grid_trade"
    __table_args__ = (
        UniqueConstraint("account_id", "symbol", "session_date", name="uq_grid_trade_sym_session"),
        Index("ix_grid_trade_session_date", "session_date"),
    )

    account_id: Mapped[int] = mapped_column(ForeignKey("paper_account.id", ondelete="CASCADE"))
    symbol: Mapped[str] = mapped_column(String(20), index=True)
    side: Mapped[str] = mapped_column(String(4))  # "buy" | "sell"
    qty: Mapped[Decimal] = mapped_column(_QTY)
    price: Mapped[Decimal] = mapped_column(_MONEY)
    usd: Mapped[Decimal] = mapped_column(_MONEY)
    anchor_before: Mapped[Decimal] = mapped_column(_MONEY)
    anchor_after: Mapped[Decimal] = mapped_column(_MONEY)
    session_date: Mapped[date] = mapped_column(Date)
    evidence_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
