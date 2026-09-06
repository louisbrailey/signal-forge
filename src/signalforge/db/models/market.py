"""Reference & market-data tables (ARCHITECTURE.md §5.1) + data-health (§5.2)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from signalforge.db.base import Base, CreatedAt, IntPK, TimestampedMixin
from signalforge.db.types import UTCDateTime
from signalforge.domain import DataQualityFlag, FeedType, LatencyCategory

_ENUM_KW: dict[str, Any] = {"native_enum": False, "length": 32, "validate_strings": True}


class Instrument(Base, IntPK, TimestampedMixin):
    __tablename__ = "instrument"

    symbol: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160), default="")
    instrument_type: Mapped[str] = mapped_column(String(16), default="stock")  # stock | etf
    sector: Mapped[str] = mapped_column(String(64), default="")
    industry: Mapped[str] = mapped_column(String(96), default="")
    exchange: Mapped[str] = mapped_column(String(16), default="")
    is_active: Mapped[bool] = mapped_column(default=True)
    first_seen: Mapped[date | None] = mapped_column(default=None)
    delisted_on: Mapped[date | None] = mapped_column(default=None)

    bars: Mapped[list[OHLCVDaily]] = relationship(back_populates="instrument")


class Watchlist(Base, IntPK, CreatedAt):
    __tablename__ = "watchlist"

    name: Mapped[str] = mapped_column(String(64), unique=True)
    members: Mapped[list[WatchlistMember]] = relationship(
        back_populates="watchlist", cascade="all, delete-orphan"
    )


class WatchlistMember(Base, IntPK, CreatedAt):
    __tablename__ = "watchlist_member"
    __table_args__ = (UniqueConstraint("watchlist_id", "instrument_id"),)

    watchlist_id: Mapped[int] = mapped_column(ForeignKey("watchlist.id", ondelete="CASCADE"))
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instrument.id", ondelete="CASCADE"))

    watchlist: Mapped[Watchlist] = relationship(back_populates="members")


class UniverseConfigSnapshot(Base, IntPK, CreatedAt):
    """Point-in-time snapshot of the active universe filters, keyed by config hash."""

    __tablename__ = "universe_config_snapshot"

    config_hash: Mapped[str] = mapped_column(String(64), index=True)
    filters_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    effective_from: Mapped[datetime] = mapped_column(UTCDateTime)


class OHLCVDaily(Base, IntPK, CreatedAt):
    """Daily bars. Both raw and corporate-action-adjusted values are kept."""

    __tablename__ = "ohlcv_daily"
    __table_args__ = (
        UniqueConstraint("instrument_id", "session_date", "source"),
        Index("ix_ohlcv_daily_instrument_date", "instrument_id", "session_date"),
    )

    instrument_id: Mapped[int] = mapped_column(ForeignKey("instrument.id", ondelete="CASCADE"))
    session_date: Mapped[date] = mapped_column(index=True)
    open: Mapped[float] = mapped_column(Float)
    high: Mapped[float] = mapped_column(Float)
    low: Mapped[float] = mapped_column(Float)
    close: Mapped[float] = mapped_column(Float)
    volume: Mapped[float] = mapped_column(Float)
    adj_close: Mapped[float | None] = mapped_column(Float, default=None)
    split_factor: Mapped[float] = mapped_column(Float, default=1.0)
    div_cash: Mapped[float] = mapped_column(Float, default=0.0)
    is_adjusted: Mapped[bool] = mapped_column(default=False)

    source: Mapped[str] = mapped_column(String(40), index=True)
    latency_category: Mapped[LatencyCategory] = mapped_column(SAEnum(LatencyCategory, **_ENUM_KW))
    is_simulated: Mapped[bool] = mapped_column(default=False)
    ingested_at: Mapped[datetime] = mapped_column(UTCDateTime)
    quality_flags: Mapped[list[str]] = mapped_column(JSON, default=list)

    instrument: Mapped[Instrument] = relationship(back_populates="bars")


class QuoteSnapshot(Base, IntPK, CreatedAt):
    """The last quote used for a scan / candidate (spread & latency provenance)."""

    __tablename__ = "quote_snapshot"

    instrument_id: Mapped[int] = mapped_column(ForeignKey("instrument.id", ondelete="CASCADE"))
    bid: Mapped[float | None] = mapped_column(Float, default=None)
    ask: Mapped[float | None] = mapped_column(Float, default=None)
    mid: Mapped[float | None] = mapped_column(Float, default=None)
    spread_bps: Mapped[float | None] = mapped_column(Float, default=None)
    as_of: Mapped[datetime] = mapped_column(UTCDateTime)
    source: Mapped[str] = mapped_column(String(40))
    latency_category: Mapped[LatencyCategory] = mapped_column(SAEnum(LatencyCategory, **_ENUM_KW))
    is_simulated: Mapped[bool] = mapped_column(default=False)


class CorporateAction(Base, IntPK, CreatedAt):
    __tablename__ = "corporate_action"

    instrument_id: Mapped[int] = mapped_column(ForeignKey("instrument.id", ondelete="CASCADE"))
    action_type: Mapped[str] = mapped_column(String(24))  # split | dividend | symbol_change
    ex_date: Mapped[date] = mapped_column(index=True)
    ratio: Mapped[float | None] = mapped_column(Float, default=None)
    amount: Mapped[float | None] = mapped_column(Float, default=None)
    detail: Mapped[str] = mapped_column(String(160), default="")
    source: Mapped[str] = mapped_column(String(40))


class EarningsEvent(Base, IntPK, CreatedAt):
    __tablename__ = "earnings_event"
    __table_args__ = (UniqueConstraint("instrument_id", "scheduled_for", "source"),)

    instrument_id: Mapped[int] = mapped_column(ForeignKey("instrument.id", ondelete="CASCADE"))
    scheduled_for: Mapped[date] = mapped_column(index=True)
    time_of_day: Mapped[str] = mapped_column(String(8), default="unknown")  # bmo | amc | unknown
    confirmed: Mapped[bool] = mapped_column(default=False)
    source: Mapped[str] = mapped_column(String(40))
    fetched_at: Mapped[datetime] = mapped_column(UTCDateTime)


class EconomicEvent(Base, IntPK, CreatedAt):
    __tablename__ = "economic_event"

    name: Mapped[str] = mapped_column(String(120))
    country: Mapped[str] = mapped_column(String(8), default="US")
    scheduled_for: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    importance: Mapped[str] = mapped_column(String(8), default="medium")  # low | medium | high
    source: Mapped[str] = mapped_column(String(40))


class NewsItem(Base, IntPK, CreatedAt):
    __tablename__ = "news_item"

    headline: Mapped[str] = mapped_column(String(400))
    body_ref: Mapped[str] = mapped_column(String(400), default="")  # path into raw cache
    url: Mapped[str] = mapped_column(String(600), default="")
    published_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    source: Mapped[str] = mapped_column(String(60))
    instrument_symbols: Mapped[list[str]] = mapped_column(JSON, default=list)
    sentiment_label: Mapped[str | None] = mapped_column(String(16), default=None)  # LLM, optional


class FundamentalsSnapshot(Base, IntPK, CreatedAt):
    __tablename__ = "fundamentals_snapshot"
    __table_args__ = (UniqueConstraint("instrument_id", "as_of", "source"),)

    instrument_id: Mapped[int] = mapped_column(ForeignKey("instrument.id", ondelete="CASCADE"))
    as_of: Mapped[date] = mapped_column(index=True)
    metrics_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    source: Mapped[str] = mapped_column(String(40))


class ShortInterest(Base, IntPK, CreatedAt):
    __tablename__ = "short_interest"
    __table_args__ = (UniqueConstraint("instrument_id", "settlement_date", "source"),)

    instrument_id: Mapped[int] = mapped_column(ForeignKey("instrument.id", ondelete="CASCADE"))
    settlement_date: Mapped[date] = mapped_column(index=True)
    shares_short: Mapped[float | None] = mapped_column(Float, default=None)
    days_to_cover: Mapped[float | None] = mapped_column(Float, default=None)
    source: Mapped[str] = mapped_column(String(40))


class RawPayloadCache(Base, IntPK):
    """Verbatim provider responses, kept for audit + replay (ARCHITECTURE.md §8.2)."""

    __tablename__ = "raw_payload_cache"
    __table_args__ = (Index("ix_raw_payload_provider_endpoint", "provider", "endpoint"),)

    provider: Mapped[str] = mapped_column(String(40))
    endpoint: Mapped[str] = mapped_column(String(200))
    request_hash: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(16), default="ok")  # ok | error
    http_status: Mapped[int | None] = mapped_column(Integer, default=None)
    payload: Mapped[str] = mapped_column(Text)  # raw text (compression is a Phase 2 option)
    received_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)


# --------------------------------------------------------------------------- #
# Data health (§5.2)
# --------------------------------------------------------------------------- #
class DataFeedStatus(Base, IntPK):
    __tablename__ = "data_feed_status"
    __table_args__ = (UniqueConstraint("provider", "feed_type"),)

    provider: Mapped[str] = mapped_column(String(40))
    feed_type: Mapped[FeedType] = mapped_column(SAEnum(FeedType, **_ENUM_KW))
    latency_category: Mapped[LatencyCategory] = mapped_column(SAEnum(LatencyCategory, **_ENUM_KW))
    is_simulated: Mapped[bool] = mapped_column(default=False)
    entitlement_note: Mapped[str] = mapped_column(String(200), default="")
    last_success_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    last_error: Mapped[str] = mapped_column(String(300), default="")
    last_error_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    rate_limited_until: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime)


class DataQualityFlagRow(Base, IntPK, CreatedAt):
    __tablename__ = "data_quality_flag"

    flag: Mapped[DataQualityFlag] = mapped_column(SAEnum(DataQualityFlag, **_ENUM_KW))
    provider: Mapped[str] = mapped_column(String(40), default="")
    instrument_id: Mapped[int | None] = mapped_column(
        ForeignKey("instrument.id", ondelete="SET NULL"), default=None
    )
    session_date: Mapped[date | None] = mapped_column(default=None)
    detail: Mapped[str] = mapped_column(String(300), default="")


class ReconciliationCheck(Base, IntPK, CreatedAt):
    __tablename__ = "reconciliation_check"

    instrument_id: Mapped[int] = mapped_column(ForeignKey("instrument.id", ondelete="CASCADE"))
    field: Mapped[str] = mapped_column(String(24))  # e.g. "close"
    session_date: Mapped[date] = mapped_column(index=True)
    source_a: Mapped[str] = mapped_column(String(40))
    source_b: Mapped[str] = mapped_column(String(40))
    value_a: Mapped[float] = mapped_column(Float)
    value_b: Mapped[float] = mapped_column(Float)
    pct_diff: Mapped[float] = mapped_column(Float)
    verdict: Mapped[str] = mapped_column(String(12))  # ok | flagged
    checked_at: Mapped[datetime] = mapped_column(UTCDateTime)
