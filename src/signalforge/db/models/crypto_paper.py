"""Crypto paper book (CRYPTO-PAPER-1) — a SIMULATED ledger, never a broker.

No order, adapter, account or credential exists here: positions are the
deterministic replay of the backtest engine over completed daily bars,
recorded prospectively from the book's fixed start date.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import JSON, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from signalforge.db.base import Base, CreatedAt, IntPK
from signalforge.db.types import UTCDateTime


class CryptoPaperBook(Base, IntPK, CreatedAt):
    """One prospective paper book per (strategy, version). ``start_date`` is
    fixed at creation: only trades ENTERED after it count, so the book can
    never include a trade that was visible when it was opened."""

    __tablename__ = "crypto_paper_book"
    __table_args__ = (UniqueConstraint("strategy_key", "version"),)

    strategy_key: Mapped[str] = mapped_column(String(64))
    version: Mapped[str] = mapped_column(String(32))
    sealed_test_id: Mapped[int] = mapped_column(
        ForeignKey("currency_sealed_test.id", ondelete="RESTRICT")
    )
    pairs: Mapped[list[str]] = mapped_column(JSON, default=list)
    start_date: Mapped[date] = mapped_column()
    observation_end: Mapped[date] = mapped_column()
    risk_usd_per_trade: Mapped[float] = mapped_column(Float)
    last_cycle_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    last_bar_date: Mapped[date | None] = mapped_column(default=None)


class CryptoPaperTrade(Base, IntPK, CreatedAt):
    """A simulated trade. CLOSED rows are immutable: a later replay that
    disagrees is recorded in ``divergence`` and never overwrites them."""

    __tablename__ = "crypto_paper_trade"
    __table_args__ = (UniqueConstraint("book_id", "pair", "entry_date"),)

    book_id: Mapped[int] = mapped_column(
        ForeignKey("crypto_paper_book.id", ondelete="CASCADE"), index=True
    )
    pair: Mapped[str] = mapped_column(String(16))
    direction: Mapped[str] = mapped_column(String(8))  # LONG | SHORT
    entry_date: Mapped[date] = mapped_column()
    entry_price: Mapped[float] = mapped_column(Float)
    stop_price: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(8), default="OPEN")  # OPEN | CLOSED
    exit_date: Mapped[date | None] = mapped_column(default=None)
    exit_price: Mapped[float | None] = mapped_column(Float, default=None)
    exit_reason: Mapped[str | None] = mapped_column(String(16), default=None)
    pnl_r: Mapped[float | None] = mapped_column(Float, default=None)
    mark_r: Mapped[float | None] = mapped_column(Float, default=None)
    marked_at: Mapped[date | None] = mapped_column(default=None)
    costs_bps: Mapped[float] = mapped_column(Float, default=0.0)
    divergence: Mapped[str] = mapped_column(String(300), default="")
    reason: Mapped[str] = mapped_column(String(64), default="")
    bars_held: Mapped[int] = mapped_column(Integer, default=0)
