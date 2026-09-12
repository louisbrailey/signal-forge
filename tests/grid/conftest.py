"""Fixtures for the grid tests: a migrated DB with hand-built daily bars."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, timedelta

import pytest
from sqlalchemy.orm import Session

from signalforge.db.types import utcnow
from signalforge.domain import LatencyCategory

BarWriter = Callable[[str, list[float], list[float], date], None]

GRID_SOURCE = "test_grid"


@pytest.fixture
def write_bars(session: Session) -> BarWriter:
    """Write consecutive daily bars for a symbol (weekends included — the grid
    only ever consumes the sessions a symbol actually has)."""
    from signalforge.data.repository import get_or_create_instrument
    from signalforge.db.models import OHLCVDaily

    def _write(
        symbol: str,
        closes: list[float],
        opens: list[float] | None = None,
        start: date = date(2024, 1, 2),
    ) -> None:
        inst = get_or_create_instrument(session, symbol)
        op = opens if opens is not None else closes
        for i, (o, c) in enumerate(zip(op, closes, strict=True)):
            session.add(
                OHLCVDaily(
                    instrument_id=inst.id,
                    session_date=start + timedelta(days=i),
                    open=o,
                    high=max(o, c),
                    low=min(o, c),
                    close=c,
                    volume=1_000_000.0,
                    adj_close=c,
                    source=GRID_SOURCE,
                    latency_category=LatencyCategory.END_OF_DAY,
                    is_simulated=True,
                    ingested_at=utcnow(),
                )
            )
        session.flush()

    return _write
