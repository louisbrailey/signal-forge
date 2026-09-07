"""In-memory price series for the backtest engine and feature builders.

Point-in-time discipline: a feature or signal at index ``t`` may only read
``series`` values at indices ``<= t``. ``PriceSeries.head(t)`` returns a view that
makes look-ahead a structural impossibility in tests.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

import numpy as np
from numpy.typing import NDArray
from sqlalchemy import select
from sqlalchemy.orm import Session

from signalforge.data.repository import get_daily_bars


@dataclass(frozen=True, slots=True)
class PriceSeries:
    symbol: str
    dates: tuple[date, ...]
    open: NDArray[np.float64]
    high: NDArray[np.float64]
    low: NDArray[np.float64]
    close: NDArray[np.float64]
    volume: NDArray[np.float64]

    def __post_init__(self) -> None:
        n = len(self.dates)
        for arr in (self.open, self.high, self.low, self.close, self.volume):
            if arr.shape != (n,):
                raise ValueError("PriceSeries arrays must all match len(dates)")

    def __len__(self) -> int:
        return len(self.dates)

    def head(self, t: int) -> PriceSeries:
        """Bars 0..t inclusive — the only data visible when acting at bar ``t``."""
        s = slice(0, t + 1)
        return PriceSeries(
            symbol=self.symbol,
            dates=self.dates[s],
            open=self.open[s],
            high=self.high[s],
            low=self.low[s],
            close=self.close[s],
            volume=self.volume[s],
        )

    def dollar_volume(self, lookback: int = 20) -> float:
        n = min(lookback, len(self))
        if n == 0:
            return 0.0
        return float(np.mean(self.close[-n:] * self.volume[-n:]))

    @classmethod
    def from_bars(
        cls,
        symbol: str,
        rows: list[tuple[date, float, float, float, float, float]],
    ) -> PriceSeries:
        rows = sorted(rows, key=lambda r: r[0])
        return cls(
            symbol=symbol,
            dates=tuple(r[0] for r in rows),
            open=np.array([r[1] for r in rows], dtype=np.float64),
            high=np.array([r[2] for r in rows], dtype=np.float64),
            low=np.array([r[3] for r in rows], dtype=np.float64),
            close=np.array([r[4] for r in rows], dtype=np.float64),
            volume=np.array([r[5] for r in rows], dtype=np.float64),
        )

    @classmethod
    def load(
        cls,
        session: Session,
        symbol: str,
        start: date,
        end: date,
        *,
        source: str | None = None,
        adjusted: bool = True,
    ) -> PriceSeries:
        bars = get_daily_bars(session, symbol, start, end, source=source)
        rows: list[tuple[date, float, float, float, float, float]] = []
        for b in bars:
            close = b.adj_close if (adjusted and b.adj_close is not None) else b.close
            scale = close / b.close if b.close else 1.0
            rows.append(
                (
                    b.session_date,
                    b.open * scale,
                    b.high * scale,
                    b.low * scale,
                    close,
                    b.volume,
                )
            )
        return cls.from_bars(symbol, rows)

    @classmethod
    def load_intraday(
        cls,
        session: Session,
        symbol: str,
        start: datetime,
        end: datetime,
        *,
        bar_size: str = "5m",
        source: str | None = None,
    ) -> PriceSeries:
        """Intraday bars as a ``PriceSeries`` whose ``dates`` are aware datetimes."""
        from signalforge.db.models import Instrument, OHLCVIntraday

        stmt = (
            select(OHLCVIntraday)
            .join(Instrument)
            .where(
                Instrument.symbol == symbol.strip().upper(),
                OHLCVIntraday.bar_size == bar_size,
                OHLCVIntraday.bar_start >= start,
                OHLCVIntraday.bar_start <= end,
            )
            .order_by(OHLCVIntraday.bar_start)
        )
        if source is not None:
            stmt = stmt.where(OHLCVIntraday.source == source)
        bars = list(session.scalars(stmt))
        rows = [(b.bar_start, b.open, b.high, b.low, b.close, b.volume) for b in bars]
        return cls.from_bars(symbol, rows)  # type: ignore[arg-type]
