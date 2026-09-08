"""Typed persistence reads/writes for market data."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from signalforge.data.adapters.base import FeedType
from signalforge.db.models import DataFeedStatus, Instrument, OHLCVDaily

SourceFilter = str | Sequence[str] | None


def _source_clause(source: SourceFilter):  # type: ignore[no-untyped-def]
    """A single source string filters by equality; a sequence (e.g. the real
    provider name plus a specific symbol-continuity bridge tag) filters by
    membership — used when a dataset snapshot deliberately mixes one symbol's
    derived/bridged bars with every other symbol's raw provider bars. ``None``
    applies no filter at all."""
    if source is None:
        return None
    if isinstance(source, str):
        return OHLCVDaily.source == source
    return OHLCVDaily.source.in_(list(source))


def get_or_create_instrument(
    session: Session,
    symbol: str,
    *,
    name: str = "",
    instrument_type: str = "stock",
    sector: str = "",
) -> Instrument:
    symbol = symbol.strip().upper()
    inst = session.scalar(select(Instrument).where(Instrument.symbol == symbol))
    if inst is None:
        inst = Instrument(symbol=symbol, name=name, instrument_type=instrument_type, sector=sector)
        session.add(inst)
        session.flush()
    return inst


def get_daily_bars(
    session: Session,
    symbol: str,
    start: date,
    end: date,
    *,
    source: SourceFilter = None,
) -> list[OHLCVDaily]:
    stmt = (
        select(OHLCVDaily)
        .join(Instrument)
        .where(
            Instrument.symbol == symbol.strip().upper(),
            OHLCVDaily.session_date >= start,
            OHLCVDaily.session_date <= end,
        )
        .order_by(OHLCVDaily.session_date)
    )
    clause = _source_clause(source)
    if clause is not None:
        stmt = stmt.where(clause)
    return list(session.scalars(stmt))


def latest_bar_date(session: Session, symbol: str, *, source: SourceFilter = None) -> date | None:
    stmt = (
        select(OHLCVDaily.session_date)
        .join(Instrument)
        .where(Instrument.symbol == symbol.strip().upper())
        .order_by(OHLCVDaily.session_date.desc())
        .limit(1)
    )
    clause = _source_clause(source)
    if clause is not None:
        stmt = stmt.where(clause)
    return session.scalar(stmt)


def get_feed_status(session: Session, provider: str, feed_type: FeedType) -> DataFeedStatus | None:
    return session.scalar(
        select(DataFeedStatus).where(
            DataFeedStatus.provider == provider, DataFeedStatus.feed_type == feed_type
        )
    )
