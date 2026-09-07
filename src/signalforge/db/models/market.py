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


class OHLCVIntraday(Base, IntPK, CreatedAt):
    """Intraday bars (Phase 2). ``bar_start`` is the UTC start of the bar."""

    __tablename__ = "ohlcv_intraday"
    __table_args__ = (
        UniqueConstraint("instrument_id", "bar_start", "bar_size", "source"),
        Index("ix_ohlcv_intraday_instrument_start", "instrument_id", "bar_start"),
    )

    instrument_id: Mapped[int] = mapped_column(ForeignKey("instrument.id", ondelete="CASCADE"))
    bar_start: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    bar_size: Mapped[str] = mapped_column(String(8))  # e.g. "5m", "15m", "1h"
    session: Mapped[str] = mapped_column(String(6), default="rth")  # pre | rth | post
    open: Mapped[float] = mapped_column(Float)
    high: Mapped[float] = mapped_column(Float)
    low: Mapped[float] = mapped_column(Float)
    close: Mapped[float] = mapped_column(Float)
    volume: Mapped[float] = mapped_column(Float)

    source: Mapped[str] = mapped_column(String(40), index=True)
    latency_category: Mapped[LatencyCategory] = mapped_column(SAEnum(LatencyCategory, **_ENUM_KW))
    is_simulated: Mapped[bool] = mapped_column(default=False)
    ingested_at: Mapped[datetime] = mapped_column(UTCDateTime)
    quality_flags: Mapped[list[str]] = mapped_column(JSON, default=list)


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
    __table_args__ = (UniqueConstraint("dedupe_key"),)

    headline: Mapped[str] = mapped_column(String(400))
    body_ref: Mapped[str] = mapped_column(String(400), default="")  # path into raw cache
    url: Mapped[str] = mapped_column(String(600), default="")
    published_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    retrieved_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None, index=True)
    source: Mapped[str] = mapped_column(String(60))  # publisher name, e.g. "Benzinga"
    provider: Mapped[str] = mapped_column(String(40), default="")  # feed the item came through
    provider_id: Mapped[str] = mapped_column(String(120), default="")  # vendor article id
    dedupe_key: Mapped[str] = mapped_column(String(160), default="", index=True)
    author: Mapped[str] = mapped_column(String(160), default="")
    category: Mapped[str] = mapped_column(String(60), default="")
    image_url: Mapped[str] = mapped_column(String(600), default="")
    instrument_symbols: Mapped[list[str]] = mapped_column(JSON, default=list)
    sentiment_label: Mapped[str | None] = mapped_column(String(16), default=None)  # LLM, optional


class OptionContract(Base, IntPK, CreatedAt):
    """Reference metadata for one option contract (education/simulation only)."""

    __tablename__ = "option_contract"
    __table_args__ = (
        UniqueConstraint("option_ticker", "source"),
        Index("ix_option_contract_underlying_exp", "underlying_symbol", "expiration_date"),
    )

    option_ticker: Mapped[str] = mapped_column(String(40), index=True)  # e.g. O:SPY260116C00500000
    underlying_symbol: Mapped[str] = mapped_column(String(16), index=True)
    contract_type: Mapped[str] = mapped_column(String(4))  # call | put
    strike_price: Mapped[float] = mapped_column(Float)
    expiration_date: Mapped[date] = mapped_column(index=True)
    exercise_style: Mapped[str] = mapped_column(String(12), default="american")
    shares_per_contract: Mapped[int] = mapped_column(Integer, default=100)
    source: Mapped[str] = mapped_column(String(40), index=True)
    ingested_at: Mapped[datetime] = mapped_column(UTCDateTime)


class OptionQuoteSnapshot(Base, IntPK, CreatedAt):
    """A point-in-time chain snapshot row. Per-field latency is explicit:
    ``day_*`` / ``last_trade_*`` are DELAYED (>=15 min); ``open_interest`` is
    end-of-day; ``iv`` / ``greeks_json`` are the *vendor* values and are usually
    absent on this entitlement (None). Never labelled live."""

    __tablename__ = "option_quote_snapshot"
    __table_args__ = (Index("ix_option_quote_ticker_asof", "option_ticker", "as_of"),)

    option_ticker: Mapped[str] = mapped_column(String(40), index=True)
    underlying_symbol: Mapped[str] = mapped_column(String(16), index=True)
    as_of: Mapped[datetime] = mapped_column(UTCDateTime, index=True)  # our retrieval time (UTC)
    source: Mapped[str] = mapped_column(String(40), index=True)
    latency_category: Mapped[LatencyCategory] = mapped_column(SAEnum(LatencyCategory, **_ENUM_KW))

    underlying_price: Mapped[float | None] = mapped_column(Float, default=None)
    day_close: Mapped[float | None] = mapped_column(Float, default=None)
    day_volume: Mapped[float | None] = mapped_column(Float, default=None)
    day_vwap: Mapped[float | None] = mapped_column(Float, default=None)
    day_last_updated: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    last_trade_price: Mapped[float | None] = mapped_column(Float, default=None)
    last_trade_size: Mapped[float | None] = mapped_column(Float, default=None)
    last_trade_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    open_interest: Mapped[int | None] = mapped_column(Integer, default=None)
    break_even_price: Mapped[float | None] = mapped_column(Float, default=None)
    vendor_iv: Mapped[float | None] = mapped_column(Float, default=None)  # None if not entitled
    vendor_greeks_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    quality_flags: Mapped[list[str]] = mapped_column(JSON, default=list)


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


class IngestionRun(Base, IntPK):
    """One auditable historical-data ingestion. Records what was *requested* and
    what was *actually* obtained, plus gaps / failures — so coverage can never be
    silently over- or under-stated. Resumable: a run in ``running`` state can be
    re-entered and only missing symbols/rows are fetched."""

    __tablename__ = "ingestion_run"

    provider: Mapped[str] = mapped_column(String(40), index=True)
    feed_type: Mapped[FeedType] = mapped_column(SAEnum(FeedType, **_ENUM_KW))
    kind: Mapped[str] = mapped_column(
        String(16), default="incremental"
    )  # incremental | full_history
    requested_start: Mapped[date] = mapped_column()
    requested_end: Mapped[date] = mapped_column()
    adjusted: Mapped[bool] = mapped_column(default=True)  # split-adjusted request
    symbols_requested: Mapped[list[str]] = mapped_column(JSON, default=list)
    # discovered provider limit (never hard-coded): earliest 'from' that returns data
    earliest_available_date: Mapped[date | None] = mapped_column(default=None)
    earliest_probe_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    # actual coverage after the run
    coverage_first: Mapped[date | None] = mapped_column(default=None)
    coverage_last: Mapped[date | None] = mapped_column(default=None)
    bars_written: Mapped[int] = mapped_column(Integer, default=0)
    bars_skipped: Mapped[int] = mapped_column(Integer, default=0)
    symbols_ok: Mapped[list[str]] = mapped_column(JSON, default=list)
    symbols_failed: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)  # symbol -> error
    gaps_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)  # symbol -> [ranges]
    status: Mapped[str] = mapped_column(
        String(12), default="running"
    )  # running | ok | partial | failed
    started_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    notes: Mapped[str] = mapped_column(Text, default="")


class DataValidationReport(Base, IntPK):
    """Result of a data-quality validation pass over the daily store."""

    __tablename__ = "data_validation_report"

    provider: Mapped[str] = mapped_column(String(40), index=True)
    symbols: Mapped[list[str]] = mapped_column(JSON, default=list)
    ran_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    passed: Mapped[bool] = mapped_column(default=False)
    checks_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict
    )  # check -> {passed, detail}
    findings_json: Mapped[list[str]] = mapped_column(JSON, default=list)


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
