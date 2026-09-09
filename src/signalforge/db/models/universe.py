"""Liquid U.S. research-universe pipeline tables.

Raw bulk files (one grouped-daily payload per session, archived verbatim on
disk with a checksum) are kept strictly separate from normalized screening
records. Every screening run persists its stage counts and every excluded
symbol's exact reasons. Nothing here is point-in-time adjusted or
survivorship-free, and every row says so via ``adjustment_basis`` /
``survivorship_note`` on the run.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import JSON, Float, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from signalforge.db.base import Base, IntPK
from signalforge.db.types import UTCDateTime


class UniverseTicker(Base, IntPK):
    """One discovered ticker from the provider's reference data (current
    values only — market cap / shares are as of ``refreshed_at``)."""

    __tablename__ = "universe_ticker"
    __table_args__ = (UniqueConstraint("ticker"),)

    ticker: Mapped[str] = mapped_column(String(16), index=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    security_type: Mapped[str] = mapped_column(String(8), index=True)  # CS | ETF | ...
    primary_exchange: Mapped[str] = mapped_column(String(12), default="")
    locale: Mapped[str] = mapped_column(String(4), default="us")
    active: Mapped[bool] = mapped_column(default=True, index=True)
    list_date: Mapped[date | None] = mapped_column(default=None)
    market_cap: Mapped[float | None] = mapped_column(Float, default=None)
    sic_code: Mapped[str] = mapped_column(String(8), default="")
    sic_description: Mapped[str] = mapped_column(String(160), default="")
    first_seen: Mapped[date] = mapped_column()
    last_seen: Mapped[date] = mapped_column(index=True)
    refreshed_at: Mapped[datetime] = mapped_column(UTCDateTime)


class BulkFile(Base, IntPK):
    """One archived grouped-daily payload (all U.S. stocks, one session)."""

    __tablename__ = "bulk_file"
    __table_args__ = (UniqueConstraint("source", "session_date"),)

    source: Mapped[str] = mapped_column(String(40), index=True)
    session_date: Mapped[date] = mapped_column(index=True)
    path: Mapped[str] = mapped_column(String(400))
    sha256: Mapped[str] = mapped_column(String(64))
    bytes_gz: Mapped[int] = mapped_column(Integer)
    bytes_raw: Mapped[int] = mapped_column(Integer)
    row_count: Mapped[int] = mapped_column(Integer)
    adjusted_as_of: Mapped[date] = mapped_column()  # split-adjusted AS OF this fetch date
    fetched_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    status: Mapped[str] = mapped_column(String(12), default="ok")  # ok | empty | failed
    detail: Mapped[str] = mapped_column(String(300), default="")


class UniverseScreenRun(Base, IntPK):
    """One eligibility screen over the bulk archive, with stage counts."""

    __tablename__ = "universe_screen_run"

    screen_date: Mapped[date] = mapped_column(index=True)  # newest session screened
    started_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    status: Mapped[str] = mapped_column(String(12), default="running")
    config_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    sessions_used: Mapped[int] = mapped_column(Integer, default=0)
    archive_first: Mapped[date | None] = mapped_column(default=None)
    archive_last: Mapped[date | None] = mapped_column(default=None)
    # stage counts: discovered -> in-scope -> excluded-by-reason -> eligible
    discovered: Mapped[int] = mapped_column(Integer, default=0)  # every reference ticker
    in_scope_types: Mapped[int] = mapped_column(Integer, default=0)  # CS + ETF, us, active
    excluded_by_reason: Mapped[dict[str, int]] = mapped_column(JSON, default=dict)
    eligible: Mapped[int] = mapped_column(Integer, default=0)
    dataset_snapshot_id: Mapped[int | None] = mapped_column(default=None)
    adjustment_basis: Mapped[str] = mapped_column(
        String(120), default="split-adjusted as of fetch date; NOT point-in-time"
    )
    survivorship_note: Mapped[str] = mapped_column(
        String(160), default="active tickers only at discovery; NOT survivorship-free"
    )
    storage_bytes: Mapped[int] = mapped_column(Integer, default=0)
    runtime_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    notes: Mapped[str] = mapped_column(Text, default="")


class UniverseMember(Base, IntPK):
    """Per-run, per-symbol screening record: metrics, verdict, exact reasons."""

    __tablename__ = "universe_member"
    __table_args__ = (
        UniqueConstraint("run_id", "ticker"),
        Index("ix_universe_member_run_eligible", "run_id", "eligible"),
    )

    run_id: Mapped[int] = mapped_column(Integer, index=True)
    ticker: Mapped[str] = mapped_column(String(16), index=True)
    security_type: Mapped[str] = mapped_column(String(8), default="")
    last_close: Mapped[float | None] = mapped_column(Float, default=None)
    avg_dollar_volume: Mapped[float | None] = mapped_column(Float, default=None)
    market_cap: Mapped[float | None] = mapped_column(Float, default=None)
    sessions_present: Mapped[int] = mapped_column(Integer, default=0)
    sic_group: Mapped[str] = mapped_column(String(4), default="")
    eligible: Mapped[bool] = mapped_column(default=False)
    exclusion_reasons: Mapped[list[str]] = mapped_column(JSON, default=list)
    flags: Mapped[list[str]] = mapped_column(JSON, default=list)  # non-excluding notes
