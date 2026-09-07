"""Typed persistence reads/writes for market data."""

from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from signalforge.data.adapters.base import FeedType
from signalforge.db.models import DataFeedStatus, Instrument, OHLCVDaily


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
    source: str | None = None,
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
    if source is not None:
        stmt = stmt.where(OHLCVDaily.source == source)
    return list(session.scalars(stmt))


def latest_bar_date(session: Session, symbol: str, *, source: str | None = None) -> date | None:
    stmt = (
        select(OHLCVDaily.session_date)
        .join(Instrument)
        .where(Instrument.symbol == symbol.strip().upper())
        .order_by(OHLCVDaily.session_date.desc())
        .limit(1)
    )
    if source is not None:
        stmt = stmt.where(OHLCVDaily.source == source)
    return session.scalar(stmt)


def get_feed_status(session: Session, provider: str, feed_type: FeedType) -> DataFeedStatus | None:
    return session.scalar(
        select(DataFeedStatus).where(
            DataFeedStatus.provider == provider, DataFeedStatus.feed_type == feed_type
        )
    )
