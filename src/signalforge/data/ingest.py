"""Ingestion: adapter output -> normalized rows + raw-payload cache + feed status.

Every bar row carries its ``source``, ``latency_category``, ``is_simulated`` flag,
``ingested_at`` timestamp, and any ``quality_flags`` (ARCHITECTURE.md §8.2).
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Collection
from dataclasses import dataclass, field
from datetime import UTC as _UTC
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
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

if TYPE_CHECKING:
    from signalforge.db.models import IngestionRun

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
    # True when ``should_stop`` ended the loop early; ``results`` then holds
    # only the symbols attempted before the stop.
    stopped: bool = False

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

    # Network FIRST, database SECOND. The fetch (with the adapter's rate-limit
    # pacing) must never happen inside an open write transaction: the SQLite
    # write lock would be held for the whole wait and every other writer
    # (worker heartbeat, API settings, a second job) would time out.
    bar_cap = _capability(adapter, FeedType.BAR_DAILY)
    try:
        bars = list(adapter.fetch_daily_bars(symbol, start, end))
    except AdapterError as exc:
        get_or_create_instrument(session, symbol)
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

    inst = get_or_create_instrument(session, symbol)
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
    *,
    skip: Collection[str] = (),
    should_stop: Callable[[], bool] | None = None,
) -> IngestReport:
    """Fetch-then-write every symbol, one committed transaction per symbol.

    ``skip`` names symbols a previous, interrupted run already completed (the
    resume contract ``ingest_daily_history`` has always had). ``should_stop``
    is polled BETWEEN symbols — after the previous symbol's commit and before
    the next symbol's network fetch — so a stop never interrupts a write
    transaction and everything attempted so far is durable.
    """
    report = IngestReport(provider=adapter.provider_name, started_at=utcnow().isoformat())
    done = {s.upper() for s in skip}
    for sym in symbols:
        if sym.upper() in done:
            continue
        if should_stop is not None and should_stop():
            report.stopped = True
            break
        report.results.append(ingest_symbol(session, adapter, sym, start, end))
        # One short write transaction per symbol: release the SQLite write
        # lock before the next symbol's paced network fetch (see
        # docs/SQLITE_CONCURRENCY.md). Also makes a partial run durable.
        session.commit()
    _log.info(
        "ingest.done",
        provider=adapter.provider_name,
        symbols=len(symbols),
        bars_written=report.bars_written,
        errors=len(report.errors),
    )
    return report


def _symbol_gaps(
    session: Session, instrument_id: int, source: str, start: date, end: date
) -> list[tuple[str, str]]:
    """Ranges of trading sessions with no bar for this symbol/source in [start, end]."""
    from signalforge.data.calendar import sessions as _sessions

    have = {
        d
        for (d,) in session.execute(
            select(OHLCVDaily.session_date).where(
                OHLCVDaily.instrument_id == instrument_id,
                OHLCVDaily.source == source,
                OHLCVDaily.session_date >= start,
                OHLCVDaily.session_date <= end,
            )
        )
    }
    expected = list(_sessions(start, min(end, date.today())))
    gaps: list[tuple[str, str]] = []
    run_start: date | None = None
    prev: date | None = None
    for d in expected:
        if d in have:
            if run_start is not None and prev is not None:
                gaps.append((run_start.isoformat(), prev.isoformat()))
            run_start = None
        else:
            if run_start is None:
                run_start = d
            prev = d
    if run_start is not None and prev is not None:
        gaps.append((run_start.isoformat(), prev.isoformat()))
    return gaps


def ingest_daily_history(
    session: Session,
    adapter: MarketDataAdapter,
    symbols: list[str],
    start: date,
    end: date,
    *,
    kind: str = "incremental",
    earliest_available: date | None = None,
    earliest_probe_at: datetime | None = None,
    resume_run_id: int | None = None,
) -> IngestionRun:
    """Incremental, idempotent, auditable daily-history ingest.

    Writes an ``IngestionRun`` recording the requested window, discovered earliest
    date, actual coverage, per-symbol gaps, and failures. Re-running (or resuming
    ``resume_run_id``) only fetches rows not already stored.
    """
    from signalforge.db.models import IngestionRun as _Run
    from signalforge.db.models import Instrument as _Inst

    run: _Run
    if resume_run_id is not None:
        found = session.get(_Run, resume_run_id)
        if found is None:
            raise ValueError(f"ingestion_run {resume_run_id} not found")
        run = found
    else:
        run = _Run(
            provider=adapter.provider_name,
            feed_type=FeedType.BAR_DAILY,
            kind=kind,
            requested_start=start,
            requested_end=end,
            adjusted=True,
            symbols_requested=list(symbols),
            earliest_available_date=earliest_available,
            earliest_probe_at=earliest_probe_at,
            status="running",
            started_at=utcnow(),
        )
        session.add(run)
        session.flush()

    ok: list[str] = list(run.symbols_ok or [])
    failed: dict[str, str] = dict(run.symbols_failed or {})
    gaps: dict[str, list[list[str]]] = {}
    written = int(run.bars_written or 0)
    skipped = int(run.bars_skipped or 0)

    for sym in symbols:
        if sym in ok:  # resume: already done cleanly
            continue
        r = ingest_symbol(session, adapter, sym, start, end)
        written += r.bars_written
        skipped += r.bars_skipped
        if r.error:
            failed[sym] = r.error[:200]
            ok = [s for s in ok if s != sym]
        else:
            failed.pop(sym, None)
            if sym not in ok:
                ok.append(sym)
        inst = session.scalar(select(_Inst).where(_Inst.symbol == sym))
        if inst is not None:
            g = _symbol_gaps(session, inst.id, adapter.provider_name, start, end)
            if g:
                gaps[sym] = [list(x) for x in g]
        # checkpoint after every symbol — COMMITTED, so each symbol is one
        # short write transaction (resumable) and the write lock is released
        # before the next symbol's paced network fetch.
        run.symbols_ok = list(ok)
        run.symbols_failed = failed
        run.gaps_json = gaps
        run.bars_written = written
        run.bars_skipped = skipped
        session.commit()

    cov = session.execute(
        select(func.min(OHLCVDaily.session_date), func.max(OHLCVDaily.session_date)).where(
            OHLCVDaily.source == adapter.provider_name
        )
    ).one()
    run.coverage_first, run.coverage_last = cov[0], cov[1]
    run.status = "ok" if not failed else ("partial" if ok else "failed")
    run.finished_at = utcnow()
    session.flush()
    _log.info(
        "ingest.history_done",
        provider=adapter.provider_name,
        kind=kind,
        written=written,
        skipped=skipped,
        ok=len(ok),
        failed=len(failed),
        gap_symbols=len(gaps),
    )
    return run


def ingest_intraday_symbol(
    session: Session,
    adapter: IntradayBarAdapter,
    symbol: str,
    start: datetime,
    end: datetime,
    *,
    bar_size: str = "5m",
    rth_only: bool = True,
    record_feed_status: bool = True,
) -> SymbolIngestResult:
    """Fetch and store one symbol's intraday bars for ``[start, end]``.

    ``rth_only`` (default True) drops pre/post bars at the door — the design's
    item B7. ``PriceSeries.load_intraday`` filters on ``session`` as well, so
    purity is enforced twice: once as ingest policy, once as code. Dropped bars
    are counted in ``bars_skipped``, never silently discarded.

    ``record_feed_status`` writes the ``DataFeedStatus`` row for
    ``BAR_INTRADAY``. A **historical backfill passes False** — see
    :func:`ingest_intraday_history` for why that is a live-system safety
    property and not a detail."""
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
        if rth_only and bar.session != "rth":
            # B7: an extended-hours bar is not tradeable by an RTH strategy, and
            # `features.intraday._session_date` groups by UTC date — an Eastern
            # post-market bar would land on the NEXT calendar date and corrupt
            # that session's opening range.
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

    if cap is not None and record_feed_status:
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
    rth_only: bool = True,
    record_feed_status: bool = True,
) -> IngestReport:
    report = IngestReport(provider=adapter.provider_name, started_at=utcnow().isoformat())
    for sym in symbols:
        report.results.append(
            ingest_intraday_symbol(
                session,
                adapter,
                sym,
                start,
                end,
                bar_size=bar_size,
                rth_only=rth_only,
                record_feed_status=record_feed_status,
            )
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


# --------------------------------------------------------------------------- #
# intraday history: calendar-chunked, resumable, costed before it runs
# --------------------------------------------------------------------------- #
# The provider caps one aggregates response at 50,000 rows and this adapter
# family REJECTS a paginated response outright rather than silently truncating
# it (massive.fetch_intraday_bars / fetch_daily_bars). A long backfill must
# therefore be split into requests that each fit under the cap, and the split
# must be decided up front so the API budget is a stated number rather than a
# surprise.
_NY = ZoneInfo("America/New_York")
PROVIDER_ROW_CAP = 50_000
# Extended-hours minutes per session (04:00-20:00 ET).
#
# Incident 2026-10-26 (ingestion_run 71): the provider's 50,000 cap counts the
# underlying ONE-MINUTE base aggregates, not the rows of the requested bar
# size. A full-year 15m request returned 5,077 bars plus a ``next_url`` (only
# 2017-01-03..05-09 of the year), the adapter correctly rejected the paginated
# answer, and every year-chunk failed. The cap is therefore checked against
# base minutes per session regardless of ``bar_size``: 50,000 / 960 = 52
# sessions, so a request must span about 2.5 months at most.
_EXTENDED_MINUTES_PER_SESSION = 16 * 60


@dataclass(frozen=True, slots=True)
class IntradayChunk:
    symbol: str
    start: date
    end: date
    sessions: int
    max_rows: int  # worst case the provider may return for this request


@dataclass(frozen=True, slots=True)
class IntradayRequestPlan:
    """What a backfill will cost BEFORE a single request is made."""

    symbols: list[str]
    bar_size: str
    start: date
    end: date
    chunk_months: int
    chunks: list[IntradayChunk]
    request_spacing_s: float
    sessions: int

    @property
    def n_requests(self) -> int:
        return len(self.chunks)

    @property
    def seconds(self) -> float:
        """Paced wall clock. The first request does not wait, so the pacing
        cost is (n-1) gaps, not n."""
        return max(0, self.n_requests - 1) * self.request_spacing_s

    @property
    def minutes(self) -> float:
        return self.seconds / 60.0

    @property
    def rth_rows(self) -> int:
        """Rows actually STORED (RTH only), from the exchange calendar — early
        closes included, so this is not sessions x 26."""
        from signalforge.data.intraday_coverage import expected_rth_bars

        per_symbol = sum(
            expected_rth_bars(d, self.bar_size) for d in _calendar_sessions(self.start, self.end)
        )
        return per_symbol * len(self.symbols)

    @property
    def max_rows_per_request(self) -> int:
        return max((c.max_rows for c in self.chunks), default=0)

    def summary(self) -> str:
        return (
            f"{len(self.symbols)} symbols x {self.bar_size} x {self.start}..{self.end} "
            f"({self.sessions} exchange sessions): {self.n_requests} paced provider requests "
            f"in {self.chunk_months}-month chunks, ~{self.minutes:.1f} min at "
            f"{self.request_spacing_s:.1f}s spacing, <= {self.max_rows_per_request:,} rows per "
            f"request (provider cap {PROVIDER_ROW_CAP:,}), ~{self.rth_rows:,} RTH rows stored"
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "symbols": len(self.symbols),
            "bar_size": self.bar_size,
            "span": f"{self.start}..{self.end}",
            "sessions": self.sessions,
            "chunk_months": self.chunk_months,
            "requests": self.n_requests,
            "minutes": round(self.minutes, 1),
            "request_spacing_s": self.request_spacing_s,
            "max_rows_per_request": self.max_rows_per_request,
            "provider_row_cap": PROVIDER_ROW_CAP,
            "rth_rows_stored": self.rth_rows,
        }


def _calendar_sessions(start: date, end: date) -> tuple[date, ...]:
    from signalforge.data.calendar import sessions as _sessions

    return _sessions(start, end)


def _month_chunks(start: date, end: date, chunk_months: int) -> list[tuple[date, date]]:
    """Split ``[start, end]`` on calendar-month boundaries, ``chunk_months`` at a
    time, aligned to January (2 -> Jan-Feb, Mar-Apr, ...). Fixed calendar
    boundaries (rather than a rolling N-day window) keep a resumed or re-run
    backfill asking for the IDENTICAL windows, so the provider's responses —
    and therefore the dedupe — are reproducible."""
    if chunk_months < 1 or 12 % chunk_months:
        raise ValueError("chunk_months must divide 12 (1, 2, 3, 4, 6 or 12)")
    out: list[tuple[date, date]] = []
    lo = start
    while lo <= end:
        block_start_month = ((lo.month - 1) // chunk_months) * chunk_months + 1
        last_month = block_start_month + chunk_months - 1
        nxt = date(
            lo.year + (1 if last_month == 12 else 0), 1 if last_month == 12 else last_month + 1, 1
        )
        hi = min(nxt - timedelta(days=1), end)
        out.append((lo, hi))
        lo = hi + timedelta(days=1)
    return out


def intraday_request_plan(
    symbols: list[str],
    start: date,
    end: date,
    *,
    bar_size: str = "15m",
    chunk_months: int = 2,
    request_spacing_s: float | None = None,
) -> IntradayRequestPlan:
    """Cost a backfill without making any request.

    Raises when a chunk could exceed the provider's row cap: the adapter
    rejects a paginated answer, so an over-large chunk would fail the whole
    symbol rather than quietly return a prefix."""
    from signalforge.config import get_settings
    from signalforge.data.calendar import bar_minutes

    if request_spacing_s is None:
        request_spacing_s = float(get_settings().market_data_min_request_spacing_s)
    bar_minutes(bar_size)  # validates the bar size
    syms = [s.strip().upper() for s in symbols]

    chunks: list[IntradayChunk] = []
    for lo, hi in _month_chunks(start, end, chunk_months):
        n_sessions = len(_calendar_sessions(lo, hi))
        # base one-minute aggregates the provider counts against its cap
        max_rows = n_sessions * _EXTENDED_MINUTES_PER_SESSION
        if max_rows > PROVIDER_ROW_CAP:
            raise ValueError(
                f"a {chunk_months}-month chunk could need up to {max_rows:,} one-minute base "
                f"aggregates, above the provider's {PROVIDER_ROW_CAP:,} cap — use a smaller "
                "--chunk-months"
            )
        for sym in syms:
            chunks.append(
                IntradayChunk(symbol=sym, start=lo, end=hi, sessions=n_sessions, max_rows=max_rows)
            )
    return IntradayRequestPlan(
        symbols=syms,
        bar_size=bar_size,
        start=start,
        end=end,
        chunk_months=chunk_months,
        chunks=chunks,
        request_spacing_s=request_spacing_s,
        sessions=len(_calendar_sessions(start, end)),
    )


def _intraday_symbol_gaps(
    session: Session,
    instrument_id: int,
    source: str,
    bar_size: str,
    start: date,
    end: date,
) -> list[list[str]]:
    """Runs of exchange sessions with no RTH bar for this symbol/source/size."""
    from zoneinfo import ZoneInfo

    rows = session.execute(
        select(OHLCVIntraday.bar_start)
        .where(
            OHLCVIntraday.instrument_id == instrument_id,
            OHLCVIntraday.source == source,
            OHLCVIntraday.bar_size == bar_size,
            OHLCVIntraday.session == "rth",
        )
        .order_by(OHLCVIntraday.bar_start)
    )
    et = ZoneInfo("America/New_York")
    # Session membership is an EASTERN-date question: a UTC date would file a
    # 16:00 ET bar under the following day for part of the year.
    have = {
        (b.astimezone(et) if b.tzinfo else b.replace(tzinfo=_UTC).astimezone(et)).date()
        for (b,) in rows
    }
    gaps: list[list[str]] = []
    run_start: date | None = None
    prev: date | None = None
    for d in _calendar_sessions(start, min(end, date.today())):
        if d in have:
            if run_start is not None and prev is not None:
                gaps.append([run_start.isoformat(), prev.isoformat()])
            run_start = None
        else:
            if run_start is None:
                run_start = d
            prev = d
    if run_start is not None and prev is not None:
        gaps.append([run_start.isoformat(), prev.isoformat()])
    return gaps


def ingest_intraday_history(
    session: Session,
    adapter: IntradayBarAdapter,
    symbols: list[str],
    start: date,
    end: date,
    *,
    bar_size: str = "15m",
    chunk_months: int = 2,
    kind: str = "full_history",
    resume_run_id: int | None = None,
    record_feed_status: bool = False,
) -> IngestionRun:
    """Incremental, idempotent, auditable intraday-history backfill.

    Mirrors :func:`ingest_daily_history`'s persistence and resume contract:
    one ``IngestionRun`` row records the requested window, per-symbol success,
    failures, coverage gaps and row counts; a symbol already recorded in
    ``symbols_ok`` is skipped on resume; and the run is COMMITTED after every
    symbol, so each symbol is one short write transaction and the SQLite write
    lock is released before the next symbol's paced network fetch
    (docs/SQLITE_CONCURRENCY.md).

    The span is split into calendar chunks that each fit under the provider's
    row cap (:func:`intraday_request_plan`) — the adapter rejects a paginated
    response, so the chunking is what makes a ten-year request possible at all.

    ``record_feed_status`` defaults to **False**, unlike the live paths, and
    that default is a safety property: ``alerts.dispatch`` blocks ALL candidate
    and briefing alerts while ANY ``DataFeedStatus`` row is stale, and a
    one-off historical backfill would register a ``BAR_INTRADAY`` feed that
    nothing afterwards refreshes. Thirty-six hours later it would go stale and
    silently switch off the live EOD paper probation's alerts. A backfill is
    not a feed; only a recurring intraday poll should claim to be one.
    """
    from signalforge.db.models import IngestionRun as _Run
    from signalforge.db.models import Instrument as _Inst

    plan = intraday_request_plan(symbols, start, end, bar_size=bar_size, chunk_months=chunk_months)

    run: _Run
    if resume_run_id is not None:
        found = session.get(_Run, resume_run_id)
        if found is None:
            raise ValueError(f"ingestion_run {resume_run_id} not found")
        run = found
    else:
        run = _Run(
            provider=adapter.provider_name,
            feed_type=FeedType.BAR_INTRADAY,
            kind=kind,
            requested_start=start,
            requested_end=end,
            adjusted=True,
            symbols_requested=list(plan.symbols),
            status="running",
            started_at=utcnow(),
            notes=f"intraday {bar_size} RTH-only backfill — {plan.summary()}",
        )
        session.add(run)
        session.flush()

    ok: list[str] = list(run.symbols_ok or [])
    failed: dict[str, str] = dict(run.symbols_failed or {})
    gaps: dict[str, list[list[str]]] = dict(run.gaps_json or {})
    written = int(run.bars_written or 0)
    skipped = int(run.bars_skipped or 0)

    for sym in plan.symbols:
        if sym in ok:  # resume: already done cleanly
            continue
        sym_error: str | None = None
        for chunk in (c for c in plan.chunks if c.symbol == sym):
            # The provider's date range is New York calendar days, and a day's
            # post-market bars run to 20:00 ET, i.e. into the NEXT UTC date.
            # A UTC end-of-day bound made the adapter reject every chunk that
            # ends on a trading day (incident 2026-10-26, ingestion_run 73).
            lo = datetime.combine(chunk.start, datetime.min.time(), tzinfo=_NY)
            hi = datetime.combine(chunk.end, datetime.max.time(), tzinfo=_NY)
            r = ingest_intraday_symbol(
                session,
                adapter,
                sym,
                lo,
                hi,
                bar_size=bar_size,
                rth_only=True,
                record_feed_status=record_feed_status,
            )
            written += r.bars_written
            skipped += r.bars_skipped
            if r.error:
                sym_error = f"{chunk.start}..{chunk.end}: {r.error}"
                break  # a hole mid-history is not repaired by fetching later years

        if sym_error:
            failed[sym] = sym_error[:200]
            ok = [s for s in ok if s != sym]
        else:
            failed.pop(sym, None)
            if sym not in ok:
                ok.append(sym)
        inst = session.scalar(select(_Inst).where(_Inst.symbol == sym))
        if inst is not None:
            g = _intraday_symbol_gaps(session, inst.id, adapter.provider_name, bar_size, start, end)
            if g:
                gaps[sym] = g
            else:
                gaps.pop(sym, None)
        run.symbols_ok = list(ok)
        run.symbols_failed = failed
        run.gaps_json = gaps
        run.bars_written = written
        run.bars_skipped = skipped
        session.commit()  # checkpoint: resumable, and the write lock is released

    cov = session.execute(
        select(func.min(OHLCVIntraday.bar_start), func.max(OHLCVIntraday.bar_start)).where(
            OHLCVIntraday.source == adapter.provider_name,
            OHLCVIntraday.bar_size == bar_size,
        )
    ).one()
    run.coverage_first = cov[0].date() if cov[0] is not None else None
    run.coverage_last = cov[1].date() if cov[1] is not None else None
    run.status = "ok" if not failed else ("partial" if ok else "failed")
    run.finished_at = utcnow()
    session.flush()
    _log.info(
        "ingest.intraday_history_done",
        provider=adapter.provider_name,
        bar_size=bar_size,
        requests_planned=plan.n_requests,
        written=written,
        skipped=skipped,
        ok=len(ok),
        failed=len(failed),
        gap_symbols=len(gaps),
    )
    return run
