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


class DividendEvent(Base, IntPK, CreatedAt):
    """One DECLARED cash dividend for an underlying, as published by the vendor.

    Additive and independent of ``CorporateAction`` (which the current feed
    never populates — ``fetch_corporate_actions`` returns ``()``). It exists for
    exactly one reason: the options pricing path takes a continuous dividend
    yield ``q`` and **may not leave it at its 0.0 default** — at ``q = 0`` puts
    are underpriced and calls overpriced on a dividend-paying underlying, which
    is a one-directional bias in a premium-SELLING strategy's favour (map §2.4a,
    gate 0.g). Decision 11 sources and records ``q`` rather than restricting the
    underlying set, and this is the rank-1 source it rests on.

    Declared amounts keyed on the ex-date are point-in-time safe: the trailing
    yield for session S sums only ex-dates on or before S.
    """

    __tablename__ = "dividend_event"
    __table_args__ = (
        UniqueConstraint("symbol", "ex_dividend_date", "source"),
        Index("ix_dividend_event_symbol_ex", "symbol", "ex_dividend_date"),
    )

    symbol: Mapped[str] = mapped_column(String(16), index=True)
    ex_dividend_date: Mapped[date] = mapped_column(index=True)
    cash_amount: Mapped[float] = mapped_column(Float)
    declaration_date: Mapped[date | None] = mapped_column(default=None)
    record_date: Mapped[date | None] = mapped_column(default=None)
    pay_date: Mapped[date | None] = mapped_column(default=None)
    frequency: Mapped[int | None] = mapped_column(Integer, default=None)  # payments per year
    dividend_type: Mapped[str] = mapped_column(String(8), default="")  # CD | SC | LT | ST
    currency: Mapped[str] = mapped_column(String(8), default="USD")
    source: Mapped[str] = mapped_column(String(40), index=True)
    ingested_at: Mapped[datetime] = mapped_column(UTCDateTime)


class DividendYieldDaily(Base, IntPK, CreatedAt):
    """One point-in-time trailing-twelve-month dividend yield ``q`` per
    (underlying, session).

    Derived, never fetched: ``q(S) = sum(cash dividends with ex-date in
    (S - 365d, S]) / close(S)`` over stored ``DividendEvent`` rows and the
    stored ``massive`` daily close.  A session with NO dividend history in its
    window gets NO row — never a 0.0 row — because ``q = 0`` is the assumption
    decision 11 and gate 0.g exist to refuse, not a measurement.  The
    short-vertical strategy's ``q_lookup`` reads this table by exact session
    match and treats a missing row as a non-entry.

    ``derived_from_run_id`` ties every row to the ``options_q_series``
    ``IngestionRun`` that wrote it, so a recorded ``q`` is traceable to the
    exact derivation that produced it (gate 8 provenance).
    """

    __tablename__ = "dividend_yield_daily"
    __table_args__ = (
        UniqueConstraint("symbol", "session_date", "source"),
        Index("ix_dividend_yield_daily_symbol_session", "symbol", "session_date"),
    )

    symbol: Mapped[str] = mapped_column(String(16), index=True)
    session_date: Mapped[date] = mapped_column(index=True)
    q: Mapped[float] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(40), default="vendor_dividends", index=True)
    payments: Mapped[int] = mapped_column(Integer)  # dividends summed in the window
    window_start: Mapped[date] = mapped_column()  # exclusive lower bound of the ex-date window
    reference_close: Mapped[float] = mapped_column(Float)
    derived_from_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("ingestion_run.id", ondelete="SET NULL"), default=None
    )


class SplitEvent(Base, IntPK, CreatedAt):
    """One EXECUTED share split for an underlying, as published by the vendor.

    The stored ``ohlcv_daily`` series is back-adjusted with no marker
    (``split_factor`` is 1.0 on every row, ``adj_close == close`` everywhere),
    while option **strikes are not** back-adjusted. A point-in-time reference
    price taken from the adjusted series for a pre-split cycle is therefore off
    by the split factor, and the strike band computed from it asks the vendor
    for strikes that never existed — a failure that looks exactly like "that
    cycle had no contracts" (D1 §2.3). This table is what lets a cycle crossing
    an adjustment be NAMED and excluded rather than silently mis-struck.
    """

    __tablename__ = "split_event"
    __table_args__ = (
        UniqueConstraint("symbol", "execution_date", "source"),
        Index("ix_split_event_symbol_exec", "symbol", "execution_date"),
    )

    symbol: Mapped[str] = mapped_column(String(16), index=True)
    execution_date: Mapped[date] = mapped_column(index=True)
    split_from: Mapped[float] = mapped_column(Float)  # shares before
    split_to: Mapped[float] = mapped_column(Float)  # shares after
    source: Mapped[str] = mapped_column(String(40), index=True)
    ingested_at: Mapped[datetime] = mapped_column(UTCDateTime)


class SymbolContinuityMapping(Base, IntPK, CreatedAt):
    """An explicit, versioned, auditable bridge from one symbol's price
    history to a successor symbol across a corporate action (ticker and/or
    name change) — e.g. FB -> META on 2022-06-09.

    Immutable once created: correcting or re-running validation NEVER edits
    an existing row — it inserts a new ``version`` for the same
    ``(old_symbol, new_symbol)`` pair, so every past evaluation stays
    traceable to the exact mapping (and its exact evidence) it used.

    A mapping by itself is *not* permission to blend two symbols' data. It
    only records what was found; ``data.symbol_continuity`` will materialize
    a derived, separately-labelled instrument (``derived_symbol``) from it
    *only* when ``validation_status == 'verified'``. The raw ``old_symbol``/
    ``new_symbol`` instruments and their already-ingested bars are never
    mutated by this mechanism."""

    __tablename__ = "symbol_continuity_mapping"
    __table_args__ = (UniqueConstraint("old_symbol", "new_symbol", "version"),)

    old_symbol: Mapped[str] = mapped_column(String(16), index=True)
    new_symbol: Mapped[str] = mapped_column(String(16), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    corporate_action_type: Mapped[str] = mapped_column(String(32))  # e.g. "ticker_and_name_change"
    effective_date: Mapped[date] = mapped_column()  # first session new_symbol is authoritative
    last_old_session: Mapped[date] = mapped_column()  # last verified session old_symbol traded
    ratio: Mapped[float] = mapped_column(Float, default=1.0)  # split/reverse-split ratio, if any
    source: Mapped[str] = mapped_column(String(40))  # data provider both legs were fetched from
    adjustment_status: Mapped[str] = mapped_column(String(80))  # human-readable treatment summary
    # verified | failed | unverified — only "verified" may ever be materialized
    validation_status: Mapped[str] = mapped_column(String(16), default="unverified")
    validation_evidence_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    derived_symbol: Mapped[str] = mapped_column(
        String(16), default=""
    )  # materialized bridge, if any
    notes: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[str] = mapped_column(String(40), default="")


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


class OptionAggregateDaily(Base, IntPK, CreatedAt):
    """Historical daily OHLCV bars for a single option contract (education /
    simulation only). Distinct from ``OptionQuoteSnapshot`` (point-in-time chain
    state): these are settled end-of-day bars fetched from the historical
    aggregates endpoint. ``latency_category`` is always ``HISTORICAL`` — never
    live, never delayed. Coverage is deliberately bounded: a small liquid
    underlying set, the nearest few expirations, a tight strike band, and a hard
    total-bar cap enforced by the backfill before any fetch."""

    __tablename__ = "option_aggregate_daily"
    __table_args__ = (
        UniqueConstraint("option_ticker", "session_date", "source"),
        Index("ix_option_agg_underlying_date", "underlying_symbol", "session_date"),
    )

    option_ticker: Mapped[str] = mapped_column(String(40), index=True)
    underlying_symbol: Mapped[str] = mapped_column(String(16), index=True)
    session_date: Mapped[date] = mapped_column(index=True)
    open: Mapped[float] = mapped_column(Float)
    high: Mapped[float] = mapped_column(Float)
    low: Mapped[float] = mapped_column(Float)
    close: Mapped[float] = mapped_column(Float)
    volume: Mapped[float] = mapped_column(Float, default=0.0)
    vwap: Mapped[float | None] = mapped_column(Float, default=None)
    transactions: Mapped[int | None] = mapped_column(Integer, default=None)
    source: Mapped[str] = mapped_column(String(40), index=True)
    latency_category: Mapped[LatencyCategory] = mapped_column(SAEnum(LatencyCategory, **_ENUM_KW))
    ingested_at: Mapped[datetime] = mapped_column(UTCDateTime)
    quality_flags: Mapped[list[str]] = mapped_column(JSON, default=list)


class FxBarDaily(Base, IntPK, CreatedAt):
    """Completed daily bars for one currency pair (Massive Currencies).

    Deliberately NOT ``ohlcv_daily``: every equity path (scans, universe,
    Kronos, paper) reads that table, and a currency pair is not an equity — it
    has no splits/dividends, trades 24/5, and its ``volume`` is a tick count,
    not shares. Keeping it in its own table means no equity strategy can read
    an FX bar by accident. ``session_date`` is the UTC calendar day the bar
    covers; weekend partial bars are dropped. Latency is END_OF_DAY: only
    completed UTC days are requested."""

    __tablename__ = "fx_bar_daily"
    __table_args__ = (
        UniqueConstraint("pair", "session_date", "source"),
        Index("ix_fx_bar_daily_pair_date", "pair", "session_date"),
    )

    pair: Mapped[str] = mapped_column(String(12), index=True)  # e.g. EURUSD
    session_date: Mapped[date] = mapped_column(index=True)
    open: Mapped[float] = mapped_column(Float)
    high: Mapped[float] = mapped_column(Float)
    low: Mapped[float] = mapped_column(Float)
    close: Mapped[float] = mapped_column(Float)
    tick_volume: Mapped[float | None] = mapped_column(Float, default=None)
    vwap: Mapped[float | None] = mapped_column(Float, default=None)
    transactions: Mapped[int | None] = mapped_column(Integer, default=None)
    source: Mapped[str] = mapped_column(String(40), index=True)
    latency_category: Mapped[LatencyCategory] = mapped_column(SAEnum(LatencyCategory, **_ENUM_KW))
    ingested_at: Mapped[datetime] = mapped_column(UTCDateTime)
    quality_flags: Mapped[list[str]] = mapped_column(JSON, default=list)


class CryptoBarIntraday(Base, IntPK, CreatedAt):
    """Completed hourly (or other intraday) bars for one crypto pair.

    Separate from every equity table for the same reason as the daily crypto
    table. ``bar_start`` is the UTC start of the bar. Crypto trades around the
    clock, so there are no sessions: every hour of every day is a bar."""

    __tablename__ = "crypto_bar_intraday"
    __table_args__ = (
        UniqueConstraint("pair", "bar_size", "bar_start", "source"),
        Index("ix_crypto_bar_intraday_pair_size_start", "pair", "bar_size", "bar_start"),
    )

    pair: Mapped[str] = mapped_column(String(16), index=True)
    bar_size: Mapped[str] = mapped_column(String(8))  # e.g. 1h
    bar_start: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    open: Mapped[float] = mapped_column(Float)
    high: Mapped[float] = mapped_column(Float)
    low: Mapped[float] = mapped_column(Float)
    close: Mapped[float] = mapped_column(Float)
    volume: Mapped[float | None] = mapped_column(Float, default=None)
    vwap: Mapped[float | None] = mapped_column(Float, default=None)
    transactions: Mapped[int | None] = mapped_column(Integer, default=None)
    source: Mapped[str] = mapped_column(String(40), index=True)
    latency_category: Mapped[LatencyCategory] = mapped_column(SAEnum(LatencyCategory, **_ENUM_KW))
    ingested_at: Mapped[datetime] = mapped_column(UTCDateTime)


class CryptoBarDaily(Base, IntPK, CreatedAt):
    """Completed daily bars for one crypto pair (Massive Currencies).

    Separate from ``ohlcv_daily`` and ``fx_bar_daily`` for the same reason as
    forex: no equity path may read it by accident. Crypto trades every day, so
    ``session_date`` covers all seven UTC days. ``volume`` is in base-asset
    units (e.g. BTC), not shares or ticks."""

    __tablename__ = "crypto_bar_daily"
    __table_args__ = (
        UniqueConstraint("pair", "session_date", "source"),
        Index("ix_crypto_bar_daily_pair_date", "pair", "session_date"),
    )

    pair: Mapped[str] = mapped_column(String(16), index=True)  # e.g. BTCUSD
    session_date: Mapped[date] = mapped_column(index=True)
    open: Mapped[float] = mapped_column(Float)
    high: Mapped[float] = mapped_column(Float)
    low: Mapped[float] = mapped_column(Float)
    close: Mapped[float] = mapped_column(Float)
    volume: Mapped[float | None] = mapped_column(Float, default=None)
    vwap: Mapped[float | None] = mapped_column(Float, default=None)
    transactions: Mapped[int | None] = mapped_column(Integer, default=None)
    source: Mapped[str] = mapped_column(String(40), index=True)
    latency_category: Mapped[LatencyCategory] = mapped_column(SAEnum(LatencyCategory, **_ENUM_KW))
    ingested_at: Mapped[datetime] = mapped_column(UTCDateTime)
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
    # 32, not 16: the options backfill writes 'options_agg_backfill' (20 chars)
    # and 'options_cycle_backfill' (22). SQLite does not enforce VARCHAR length
    # so the overflow was silent there; Postgres would truncate or error (D12).
    kind: Mapped[str] = mapped_column(
        String(32), default="incremental"
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


class EntitlementCheck(Base, IntPK):
    """One recorded provider-entitlement probe. Never stores a key or a URL with
    a secret — only status / endpoint / source / timestamp / latency / error."""

    __tablename__ = "entitlement_check"

    batch_id: Mapped[str] = mapped_column(String(36), index=True)  # groups one verify run
    subscription: Mapped[str] = mapped_column(String(32), index=True)
    feed: Mapped[str] = mapped_column(String(48), index=True)
    endpoint: Mapped[str] = mapped_column(String(120))
    source: Mapped[str] = mapped_column(String(40))
    checked_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    http_status: Mapped[int | None] = mapped_column(Integer, default=None)
    available: Mapped[bool] = mapped_column(default=False)
    latency_category: Mapped[str] = mapped_column(String(16), default="none")
    error_category: Mapped[str] = mapped_column(String(24), default="none")
    detail: Mapped[str] = mapped_column(String(300), default="")


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
