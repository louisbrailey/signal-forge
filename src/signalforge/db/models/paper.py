"""Paper-trading ledger, journal, and corrections (ARCHITECTURE.md §5.4).

``paper_trade`` rows are immutable after creation (invariant S9): the repository
never issues UPDATE/DELETE, and the Alembic migration adds BEFORE UPDATE/DELETE
triggers that RAISE. Corrections are recorded as separate ``trade_correction``
rows.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from signalforge.db.base import Base, CreatedAt, IntPK
from signalforge.db.types import UTCDateTime
from signalforge.domain import Horizon, PaperDecision, PositionSide

_ENUM_KW: dict[str, Any] = {"native_enum": False, "length": 32, "validate_strings": True}
_MONEY = Numeric(20, 6)


class PaperAccount(Base, IntPK, CreatedAt):
    __tablename__ = "paper_account"

    name: Mapped[str] = mapped_column(String(64), unique=True, default="default")
    initial_cash: Mapped[Decimal] = mapped_column(_MONEY)
    cash: Mapped[Decimal] = mapped_column(_MONEY)
    # Buying power held by open options structures (D3 §3.1). ADDITIVE, server
    # default 0: on every existing account — including the live equity one — this
    # is 0 and ``spendable_cash == cash``, so no equity arithmetic moves. Only
    # ``paper.options_ledger`` ever writes it, and only for the options account.
    collateral_reserved: Mapped[Decimal] = mapped_column(_MONEY, default=Decimal("0"))

    positions: Mapped[list[PaperPosition]] = relationship(back_populates="account")

    @property
    def spendable_cash(self) -> Decimal:
        """``cash - collateral_reserved`` (D3 §3.2). Equal to ``cash`` on every
        account that holds no options collateral, which is every account today."""
        return self.cash - self.collateral_reserved


class PaperOrder(Base, IntPK, CreatedAt):
    __tablename__ = "paper_order"

    account_id: Mapped[int] = mapped_column(ForeignKey("paper_account.id", ondelete="CASCADE"))
    candidate_id: Mapped[int | None] = mapped_column(
        ForeignKey("candidate.id", ondelete="SET NULL"), default=None
    )
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instrument.id", ondelete="CASCADE"))
    side: Mapped[PositionSide] = mapped_column(SAEnum(PositionSide, **_ENUM_KW))
    qty: Mapped[int] = mapped_column(Integer)
    order_type: Mapped[str] = mapped_column(String(12), default="market")
    submitted_at: Mapped[datetime] = mapped_column(UTCDateTime)
    assumptions_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    fills: Mapped[list[PaperFill]] = relationship(back_populates="order")


class PaperFill(Base, IntPK, CreatedAt):
    __tablename__ = "paper_fill"

    order_id: Mapped[int] = mapped_column(ForeignKey("paper_order.id", ondelete="CASCADE"))
    price: Mapped[Decimal] = mapped_column(_MONEY)
    qty: Mapped[int] = mapped_column(Integer)
    spread_cost: Mapped[Decimal] = mapped_column(_MONEY, default=Decimal("0"))
    slippage: Mapped[Decimal] = mapped_column(_MONEY, default=Decimal("0"))
    commission: Mapped[Decimal] = mapped_column(_MONEY, default=Decimal("0"))
    filled_at: Mapped[datetime] = mapped_column(UTCDateTime)

    order: Mapped[PaperOrder] = relationship(back_populates="fills")


class PaperPosition(Base, IntPK, CreatedAt):
    __tablename__ = "paper_position"

    account_id: Mapped[int] = mapped_column(ForeignKey("paper_account.id", ondelete="CASCADE"))
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instrument.id", ondelete="CASCADE"))
    strategy_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("strategy_version.id", ondelete="SET NULL"), default=None
    )
    horizon: Mapped[Horizon] = mapped_column(SAEnum(Horizon, **_ENUM_KW))
    side: Mapped[PositionSide] = mapped_column(SAEnum(PositionSide, **_ENUM_KW))
    qty: Mapped[int] = mapped_column(Integer)
    avg_price: Mapped[Decimal] = mapped_column(_MONEY)
    stop_level: Mapped[float | None] = mapped_column(Float, default=None)
    target_level: Mapped[float | None] = mapped_column(Float, default=None)
    time_stop_date: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    opened_at: Mapped[datetime] = mapped_column(UTCDateTime)
    closed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    realized_pnl: Mapped[Decimal] = mapped_column(_MONEY, default=Decimal("0"))

    account: Mapped[PaperAccount] = relationship(back_populates="positions")


class PaperTrade(Base, IntPK):
    """Immutable audit record of a decision on a candidate (append-only, S9)."""

    __tablename__ = "paper_trade"

    account_id: Mapped[int] = mapped_column(ForeignKey("paper_account.id", ondelete="CASCADE"))
    candidate_id: Mapped[int | None] = mapped_column(
        ForeignKey("candidate.id", ondelete="SET NULL"), default=None
    )
    position_id: Mapped[int | None] = mapped_column(
        ForeignKey("paper_position.id", ondelete="SET NULL"), default=None
    )
    decision: Mapped[PaperDecision] = mapped_column(SAEnum(PaperDecision, **_ENUM_KW))
    signal_snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    plan_json: Mapped[dict[str, Any]] = mapped_column(JSON)  # entry/exit/stop/time-stop
    why_qualified: Mapped[str] = mapped_column(Text, default="")
    why_might_fail: Mapped[str] = mapped_column(Text, default="")
    # First-class, indexed record of WHO decided (D6 ADR §5.3). The same value
    # is still frozen into ``signal_snapshot_json["decision"]["actor"]``; this
    # column exists because an order-authorisation predicate (§5 P6) must not
    # depend on the shape of a free-form JSON blob a future writer could change
    # without breaking anything visible. Same type/default as
    # ``TradeCorrection.actor``.
    actor: Mapped[str] = mapped_column(String(60), default="local-user", index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)


class TradeCorrection(Base, IntPK, CreatedAt):
    """Append-only correction event referencing an immutable ``paper_trade``."""

    __tablename__ = "trade_correction"

    paper_trade_id: Mapped[int] = mapped_column(ForeignKey("paper_trade.id", ondelete="CASCADE"))
    field: Mapped[str] = mapped_column(String(48))
    old_value: Mapped[str] = mapped_column(Text, default="")
    new_value: Mapped[str] = mapped_column(Text, default="")
    reason: Mapped[str] = mapped_column(Text)
    actor: Mapped[str] = mapped_column(String(60), default="local-user")


class JournalEntry(Base, IntPK, CreatedAt):
    __tablename__ = "journal_entry"

    paper_trade_id: Mapped[int | None] = mapped_column(
        ForeignKey("paper_trade.id", ondelete="SET NULL"), default=None
    )
    candidate_id: Mapped[int | None] = mapped_column(
        ForeignKey("candidate.id", ondelete="SET NULL"), default=None
    )
    signal_snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    why_qualified: Mapped[str] = mapped_column(Text, default="")
    why_might_fail: Mapped[str] = mapped_column(Text, default="")
    plan_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    notes: Mapped[str] = mapped_column(Text, default="")
    outcome: Mapped[str] = mapped_column(Text, default="")
    rule_adherence_score: Mapped[int | None] = mapped_column(Integer, default=None)  # 0-100
    lessons: Mapped[str] = mapped_column(Text, default="")
