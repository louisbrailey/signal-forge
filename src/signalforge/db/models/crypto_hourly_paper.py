"""Hourly crypto paper book (CRYPTO-PAPER-H1) — a SIMULATED ledger, never a broker.

The hourly twin of ``crypto_paper``: positions are the deterministic replay of
the backtest engine over completed HOURLY bars, recorded prospectively from the
book's fixed start hour. Separate tables because the daily book keys trades by
calendar date (unique per book/pair/day), which hourly entries would collide on.
No order, adapter, account or credential exists here.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from signalforge.db.base import Base, CreatedAt, IntPK
from signalforge.db.types import UTCDateTime


class CryptoHourlyPaperBook(Base, IntPK, CreatedAt):
    """One prospective hourly paper book per (strategy, version). ``start_at`` is
    fixed at creation (the first completed hour after the book was opened): only
    trades ENTERED at or after it count."""

    __tablename__ = "crypto_hourly_paper_book"
    __table_args__ = (UniqueConstraint("strategy_key", "version"),)

    strategy_key: Mapped[str] = mapped_column(String(64))
    version: Mapped[str] = mapped_column(String(32))
    sealed_test_id: Mapped[int] = mapped_column(
        ForeignKey("currency_sealed_test.id", ondelete="RESTRICT")
    )
    pairs: Mapped[list[str]] = mapped_column(JSON, default=list)
    start_at: Mapped[datetime] = mapped_column(UTCDateTime)
    observation_end: Mapped[datetime] = mapped_column(UTCDateTime)
    risk_usd_per_trade: Mapped[float] = mapped_column(Float)
    last_cycle_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    last_bar_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)


class CryptoHourlyPaperTrade(Base, IntPK, CreatedAt):
    """A simulated hourly trade. CLOSED rows are immutable: a later replay that
    disagrees is recorded in ``divergence`` and never overwrites them."""

    __tablename__ = "crypto_hourly_paper_trade"
    __table_args__ = (UniqueConstraint("book_id", "pair", "entry_at"),)

    book_id: Mapped[int] = mapped_column(
        ForeignKey("crypto_hourly_paper_book.id", ondelete="CASCADE"), index=True
    )
    pair: Mapped[str] = mapped_column(String(16))
    direction: Mapped[str] = mapped_column(String(8))  # LONG | SHORT
    entry_at: Mapped[datetime] = mapped_column(UTCDateTime)
    entry_price: Mapped[float] = mapped_column(Float)
    stop_price: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(8), default="OPEN")  # OPEN | CLOSED | SKIPPED
    exit_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    exit_price: Mapped[float | None] = mapped_column(Float, default=None)
    exit_reason: Mapped[str | None] = mapped_column(String(16), default=None)
    pnl_r: Mapped[float | None] = mapped_column(Float, default=None)
    mark_r: Mapped[float | None] = mapped_column(Float, default=None)
    marked_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    costs_bps: Mapped[float] = mapped_column(Float, default=0.0)
    divergence: Mapped[str] = mapped_column(String(300), default="")
    reason: Mapped[str] = mapped_column(String(64), default="")
    bars_held: Mapped[int] = mapped_column(Integer, default=0)
