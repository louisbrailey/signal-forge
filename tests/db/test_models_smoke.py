"""Round-trip a few core models through a migrated SQLite DB."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from signalforge.db.models import Instrument, OHLCVDaily, PaperAccount
from signalforge.domain import LatencyCategory


def _spy(session: Session) -> Instrument:
    inst = Instrument(symbol="SPY", name="SPDR S&P 500", instrument_type="etf", sector="Broad")
    session.add(inst)
    session.flush()
    return inst


def test_instrument_and_bar_roundtrip(session: Session) -> None:
    inst = _spy(session)
    session.add(
        OHLCVDaily(
            instrument_id=inst.id,
            session_date=date(2024, 1, 2),
            open=470.0,
            high=472.5,
            low=469.1,
            close=471.8,
            volume=8_000_000,
            adj_close=471.8,
            source="fixture",
            latency_category=LatencyCategory.HISTORICAL,
            is_simulated=True,
            ingested_at=datetime.now(UTC),
            quality_flags=[],
        )
    )
    session.commit()

    bar = session.scalars(select(OHLCVDaily)).one()
    assert bar.instrument.symbol == "SPY"
    assert bar.latency_category is LatencyCategory.HISTORICAL
    assert bar.ingested_at.tzinfo is not None  # UTCDateTime returns aware


def test_symbol_is_unique(session: Session) -> None:
    _spy(session)
    session.add(Instrument(symbol="SPY"))
    with pytest.raises(IntegrityError):
        session.flush()


def test_money_columns_use_decimal(session: Session) -> None:
    acct = PaperAccount(name="default", initial_cash=Decimal("10000.00"), cash=Decimal("10000.00"))
    session.add(acct)
    session.commit()
    got = session.scalars(select(PaperAccount)).one()
    assert got.cash == Decimal("10000.00")
    assert isinstance(got.cash, Decimal)
