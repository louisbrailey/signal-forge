"""Ingestion: adapter output -> normalized rows + raw-payload cache + feed status.

Every bar row carries its ``source``, ``latency_category``, ``is_simulated`` flag,
``ingested_at`` timestamp, and any ``quality_flags`` (ARCHITECTURE.md §8.2).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from signalforge.data.adapters.base import (
    AdapterCapability,
    AdapterError,
    DailyBar,
    FeedType,
    IntradayBarAdapter,
    LatencyCategory,
    MarketDataAdapter,
)
from signalforge.data.repository import get_or_create_instrument
from signalforge.db.models import (
    CorporateAction,
    DataFeedStatus,
    EarningsEvent,
    OHLCVDaily,
    OHLCVIntraday,
    RawPayloadCache,
)
from signalforge.db.types import utcnow
from signalforge.domain import DataQualityFlag
from signalforge.observability import get_logger

_log = get_logger("ingest")


@dataclass
class SymbolIngestResult:
    symbol: str
    bars_written: int = 0
    bars_skipped: int = 0
    actions_written: int = 0
    earnings_written: int = 0
    error: str | None = None


@dataclass
class IngestReport:
    provider: str
    started_at: str
    results: list[SymbolIngestResult] = field(default_factory=list)

    @property
    def bars_written(self) -> int:
        return sum(r.bars_written for r in self.results)

    @property
    def errors(self) -> list[str]:
        return [f"{r.symbol}: {r.error}" for r in self.results if r.error]


def _bar_quality_flags(bar: DailyBar) -> list[str]:
    flags: list[str] = []
    if min(bar.open, bar.high, bar.low, bar.close) <= 0:
        flags.append(DataQualityFlag.MISSING_VALUES.value)
    if bar.volume <= 0:
        flags.append(DataQualityFlag.MISSING_VALUES.value)
    if bar.high < bar.low or bar.high < bar.open or bar.high < bar.close:
        flags.append(DataQualityFlag.VENDOR_MISMATCH.value)
    return flags


def _cache_raw(session: Session, provider: str, endpoint: str, text: str) -> None:
    req_hash = hashlib.sha256(f"{provider}|{endpoint}".encode()).hexdigest()
    session.add(
        RawPayloadCache(
            provider=provider,
            endpoint=endpoint,
            request_hash=req_hash,
            status="ok",
            payload=text,
            received_at=utcnow(),
        )
    )


def _capability(
    adapter: MarketDataAdapter | IntradayBarAdapter, feed_type: FeedType
) -> AdapterCapability | None:
    for cap in adapter.capabilities:
        if cap.feed_type is feed_type:
            return cap
    return None


def record_feed_success(session: Session, cap: AdapterCapability) -> None:
    row = session.scalar(
        select(DataFeedStatus).where(
            DataFeedStatus.provider == cap.provider_name,
            DataFeedStatus.feed_type == cap.feed_type,
        )
    )
    now = utcnow()
    if row is None:
        row = DataFeedStatus(
            provider=cap.provider_name,
            feed_type=cap.feed_type,
            latency_category=cap.latency_category,
            is_simulated=cap.is_simulated,
            entitlement_note=cap.entitlement_note,
            updated_at=now,
        )
        session.add(row)
        session.flush()  # so a later lookup in the same transaction finds it
    row.latency_category = cap.latency_category
    row.is_simulated = cap.is_simulated
    row.entitlement_note = cap.entitlement_note
    row.last_success_at = now
    row.last_error = ""
    row.consecutive_failures = 0
    row.rate_limited_until = None
    row.updated_at = now


def record_feed_failure(
    session: Session,
    provider: str,
    feed_type: FeedType,
    error: str,
    *,
    rate_limited: bool = False,
    capability: AdapterCapability | None = None,
) -> None:
    row = session.scalar(
        select(DataFeedStatus).where(
            DataFeedStatus.provider == provider, DataFeedStatus.feed_type == feed_type
        )
    )
    now = utcnow()
    if row is None:
        # A failure before any success: seed the row from the (static) capability
        # descriptor if we have it, else a conservative non-live default.
        row = DataFeedStatus(
            provider=provider,
            feed_type=feed_type,
            latency_category=(
                capability.latency_category if capability else LatencyCategory.END_OF_DAY
            ),
            is_simulated=capability.is_simulated if capability else False,
            entitlement_note=capability.entitlement_note if capability else "",
            updated_at=now,
        )
        session.add(row)
        session.flush()
    row.last_error = error[:300]
    row.last_error_at = now
    row.consecutive_failures = (row.consecutive_failures or 0) + 1
    if rate_limited:
        row.rate_limited_until = now + timedelta(minutes=15)
    row.updated_at = now


def ingest_symbol(
    session: Session,
    adapter: MarketDataAdapter,
    symbol: str,
    start: date,
    end: date,
) -> SymbolIngestResult:
    result = SymbolIngestResult(symbol=symbol.upper())
    inst = get_or_create_instrument(session, symbol)

    bar_cap = _capability(adapter, FeedType.BAR_DAILY)
    try:
        bars = list(adapter.fetch_daily_bars(symbol, start, end))
    except AdapterError as exc:
        result.error = str(exc)
        record_feed_failure(
            session,
            adapter.provider_name,
            FeedType.BAR_DAILY,
            str(exc),
            rate_limited=exc.rate_limited,
            capability=bar_cap,
        )
        _log.warning("ingest.bar_fetch_failed", symbol=symbol, error=str(exc))
        return result

    raw = getattr(adapter, "raw_payload", None)
    if callable(raw):
        _cache_raw(
            session,
            adapter.provider_name,
            f"daily_bars/{symbol.upper()}",
            raw(symbol, start, end),
        )

    existing = {
        d
        for (d,) in session.execute(
            select(OHLCVDaily.session_date).where(
                OHLCVDaily.instrument_id == inst.id,
                OHLCVDaily.source == adapter.provider_name,
                OHLCVDaily.session_date >= start,
                OHLCVDaily.session_date <= end,
            )
        )
    }
    now = utcnow()
    for bar in bars:
        if bar.session_date in existing:
            result.bars_skipped += 1
            continue
        session.add(
            OHLCVDaily(
                instrument_id=inst.id,
                session_date=bar.session_date,
                open=bar.open,
                high=bar.high,
                low=bar.low,
                close=bar.close,
                volume=bar.volume,
                adj_close=bar.adj_close,
                split_factor=bar.split_factor,
                div_cash=bar.div_cash,
                is_adjusted=bar.adj_close is not None,
                source=adapter.provider_name,
                latency_category=bar.provenance.latency_category,
                is_simulated=bar.provenance.is_simulated,
                ingested_at=now,
                quality_flags=_bar_quality_flags(bar),
            )
        )
        result.bars_written += 1

    for ca in adapter.fetch_corporate_actions(symbol, start, end):
        session.add(
            CorporateAction(
                instrument_id=inst.id,
                action_type=ca.action_type,
                ex_date=ca.ex_date,
                ratio=ca.ratio,
                amount=ca.amount,
                detail=ca.detail,
                source=adapter.provider_name,
            )
        )
        result.actions_written += 1

    for ev in adapter.fetch_earnings(symbol, start, end):
        dupe = session.scalar(
            select(EarningsEvent.id).where(
                EarningsEvent.instrument_id == inst.id,
                EarningsEvent.scheduled_for == ev.scheduled_for,
                EarningsEvent.source == adapter.provider_name,
            )
        )
        if dupe:
            continue
        session.add(
            EarningsEvent(
                instrument_id=inst.id,
                scheduled_for=ev.scheduled_for,
                time_of_day=ev.time_of_day,
                confirmed=ev.confirmed,
                source=adapter.provider_name,
                fetched_at=now,
            )
        )
        result.earnings_written += 1

    if bar_cap is not None:
        record_feed_success(session, bar_cap)
    for ft in (FeedType.CORP_ACTION, FeedType.EARNINGS_CAL):
        cap = _capability(adapter, ft)
        if cap is not None:
            record_feed_success(session, cap)

    session.flush()  # so a later dedupe query in the same transaction sees these rows
    return result


def ingest_universe(
    session: Session,
    adapter: MarketDataAdapter,
    symbols: list[str],
    start: date,
    end: date,
) -> IngestReport:
    report = IngestReport(provider=adapter.provider_name, started_at=utcnow().isoformat())
    for sym in symbols:
        report.results.append(ingest_symbol(session, adapter, sym, start, end))
    _log.info(
        "ingest.done",
        provider=adapter.provider_name,
        symbols=len(symbols),
        bars_written=report.bars_written,
        errors=len(report.errors),
    )
    return report


def ingest_intraday_symbol(
    session: Session,
    adapter: IntradayBarAdapter,
    symbol: str,
    start: datetime,
    end: datetime,
    *,
    bar_size: str = "5m",
) -> SymbolIngestResult:
    result = SymbolIngestResult(symbol=symbol.upper())
    inst = get_or_create_instrument(session, symbol)
    cap = _capability(adapter, FeedType.BAR_INTRADAY)
    try:
        bars = list(adapter.fetch_intraday_bars(symbol, start, end, bar_size=bar_size))
    except AdapterError as exc:
        result.error = str(exc)
        record_feed_failure(
            session,
            adapter.provider_name,
            FeedType.BAR_INTRADAY,
            str(exc),
            rate_limited=exc.rate_limited,
            capability=cap,
        )
        return result

    existing = {
        d
        for (d,) in session.execute(
            select(OHLCVIntraday.bar_start).where(
                OHLCVIntraday.instrument_id == inst.id,
                OHLCVIntraday.source == adapter.provider_name,
                OHLCVIntraday.bar_size == bar_size,
                OHLCVIntraday.bar_start >= start,
                OHLCVIntraday.bar_start <= end,
            )
        )
    }
    now = utcnow()
    for bar in bars:
        if bar.bar_start in existing:
            result.bars_skipped += 1
            continue
        flags: list[str] = []
        if min(bar.open, bar.high, bar.low, bar.close) <= 0:
            flags.append(DataQualityFlag.MISSING_VALUES.value)
        session.add(
            OHLCVIntraday(
                instrument_id=inst.id,
                bar_start=bar.bar_start,
                bar_size=bar.bar_size,
                session=bar.session,
                open=bar.open,
                high=bar.high,
                low=bar.low,
                close=bar.close,
                volume=bar.volume,
                source=adapter.provider_name,
                latency_category=bar.provenance.latency_category,
                is_simulated=bar.provenance.is_simulated,
                ingested_at=now,
                quality_flags=flags,
            )
        )
        result.bars_written += 1

    if cap is not None:
        record_feed_success(session, cap)
    session.flush()  # so a later dedupe query in the same transaction sees these rows
    return result


def ingest_intraday_universe(
    session: Session,
    adapter: IntradayBarAdapter,
    symbols: list[str],
    start: datetime,
    end: datetime,
    *,
    bar_size: str = "5m",
) -> IngestReport:
    report = IngestReport(provider=adapter.provider_name, started_at=utcnow().isoformat())
    for sym in symbols:
        report.results.append(
            ingest_intraday_symbol(session, adapter, sym, start, end, bar_size=bar_size)
        )
    _log.info(
        "ingest.intraday_done",
        provider=adapter.provider_name,
        symbols=len(symbols),
        bar_size=bar_size,
        bars_written=report.bars_written,
        errors=len(report.errors),
    )
    return report
