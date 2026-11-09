"""Normalize archived bulk rows into ``ohlcv_daily`` for ELIGIBLE symbols only,
under a distinct ``source`` label so the research/promotion path (which
selects bars by the configured research provider) can never silently read
them. Rows are marked ``is_adjusted=True`` with the quality flag
``asof_adjusted_not_pit``: split-adjusted as of the fetch date, not
point-in-time — usable for screening/scanning, not for promotion."""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, date, datetime

from sqlalchemy import insert, select
from sqlalchemy.orm import Session

from signalforge.config.research import UniversePipelineConfig
from signalforge.data.adapters.base import AdapterCapability
from signalforge.data.ingest import record_feed_success
from signalforge.data.repository import get_or_create_instrument
from signalforge.db.models import BulkFile, Instrument, OHLCVDaily, UniverseTicker
from signalforge.db.session import read_phase
from signalforge.domain import FeedType, LatencyCategory
from signalforge.observability import get_logger
from signalforge.universe.bulk import load_bulk_rows

_log = get_logger("universe.normalize")

ASOF_FLAG = "asof_adjusted_not_pit"
_CHUNK = 5000


def bulk_capability(source: str) -> AdapterCapability:
    return AdapterCapability(
        provider_name=source,
        feed_type=FeedType.BAR_DAILY,
        latency_category=LatencyCategory.END_OF_DAY,
        supports_point_in_time=False,
        entitlement_note=(
            "Grouped-daily bulk bars (Stocks Developer). END-OF-DAY only; split-adjusted as of "
            "fetch date, NOT point-in-time; discovery is active-only, NOT survivorship-free."
        ),
        rate_limit_per_min=None,
        is_simulated=False,
    )


@dataclass(slots=True)
class NormalizeReport:
    symbols: int = 0
    rows_written: int = 0
    rows_skipped: int = 0
    sessions: int = 0
    seconds: float = 0.0


def normalize_symbols(
    session: Session,
    symbols: list[str],
    cfg: UniversePipelineConfig,
    *,
    source: str | None = None,
    extra: tuple[str, ...] = ("SPY",),
    deadline: float | None = None,
) -> NormalizeReport:
    """Write missing (instrument, session_date) bars for ``symbols`` (+ the
    scan's market proxy) from every archived session. Idempotent.

    Lock discipline (incident 2026-11-08): the reads run as a plain reader,
    the archive is parsed with no transaction open, and each archived SESSION
    (one ``BulkFile``) is written in its own short write transaction —
    inserted in ``_CHUNK``-row statements, committed once at the file
    boundary — never one write transaction across the whole archive.

    A session is therefore all-or-nothing for a concurrent reader: the grid
    (or any other reader of this source) sees either every new bar of
    session D or none of them, never a timing-dependent half. A run cut short
    (deadline, crash) keeps every committed session, and the next run skips
    them as ``existing``."""
    t0 = time.monotonic()
    source = source or cfg.normalized_source
    rep = NormalizeReport()
    wanted = sorted(set(symbols) | set(extra))
    if not wanted:
        return rep

    with read_phase(session):
        types: dict[str, str] = {
            str(tk): str(st)
            for tk, st in session.execute(
                select(UniverseTicker.ticker, UniverseTicker.security_type).where(
                    UniverseTicker.ticker.in_(wanted)
                )
            ).all()
        }
        known: dict[str, int] = {
            str(sym): int(iid)
            for sym, iid in session.execute(
                select(Instrument.symbol, Instrument.id).where(Instrument.symbol.in_(wanted))
            ).all()
        }
        existing: set[tuple[int, date]] = set(
            session.execute(
                select(OHLCVDaily.instrument_id, OHLCVDaily.session_date)
                .join(Instrument, Instrument.id == OHLCVDaily.instrument_id)
                .where(OHLCVDaily.source == source, Instrument.symbol.in_(wanted))
            ).all()  # type: ignore[arg-type]
        )
        files = list(
            session.scalars(
                select(BulkFile)
                .where(BulkFile.source == cfg.normalized_source, BulkFile.status == "ok")
                .order_by(BulkFile.session_date)
            )
        )

    # One short write transaction creates only the instruments that are missing.
    inst_ids: dict[str, int] = {}
    for sym in wanted:
        iid = known.get(sym)
        if iid is None:
            inst = get_or_create_instrument(
                session, sym, instrument_type="etf" if types.get(sym) == "ETF" else "stock"
            )
            iid = inst.id
        inst_ids[sym] = iid
    session.commit()
    rep.symbols = len(inst_ids)

    now = datetime.now(UTC)
    batch: list[dict[str, object]] = []

    def _commit_session() -> None:
        # The file is already parsed and its rows built with no transaction
        # open; now ONE short write transaction inserts them in _CHUNK-row
        # statements and commits at the file boundary, so a concurrent reader
        # never sees part of a session.
        if not batch:
            return
        for i in range(0, len(batch), _CHUNK):
            session.execute(insert(OHLCVDaily), batch[i : i + _CHUNK])
        batch.clear()
        session.commit()

    for bf in files:
        if deadline is not None and time.monotonic() > deadline:
            _log.warning("universe.normalize.runtime_budget", sessions_done=rep.sessions)
            break
        rep.sessions += 1
        for r in load_bulk_rows(bf):
            tk = str(r.get("T") or "").upper()
            iid = inst_ids.get(tk)
            if iid is None:
                continue
            key = (iid, bf.session_date)
            if key in existing:
                rep.rows_skipped += 1
                continue
            vals = [r.get(k) for k in ("o", "h", "l", "c", "v")]
            if not all(isinstance(x, (int, float)) for x in vals):
                continue
            o, h, lo, c, v = (float(x) for x in vals)  # type: ignore[arg-type]
            existing.add(key)
            batch.append(
                {
                    "instrument_id": iid,
                    "session_date": bf.session_date,
                    "open": o,
                    "high": h,
                    "low": lo,
                    "close": c,
                    "volume": v,
                    "adj_close": c,
                    "split_factor": 1.0,
                    "div_cash": 0.0,
                    "is_adjusted": True,
                    "source": source,
                    "latency_category": LatencyCategory.END_OF_DAY,
                    "is_simulated": False,
                    "ingested_at": now,
                    "quality_flags": [ASOF_FLAG] + (["missing_values"] if v <= 0 else []),
                    "created_at": now,
                }
            )
            rep.rows_written += 1
        _commit_session()
    if rep.sessions:
        record_feed_success(session, bulk_capability(source))
    session.flush()
    rep.seconds = round(time.monotonic() - t0, 1)
    _log.info(
        "universe.normalize",
        symbols=rep.symbols,
        written=rep.rows_written,
        skipped=rep.rows_skipped,
    )
    return rep
