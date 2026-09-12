"""READ-ONLY series loading for the grid backtest.

Uses the project's existing data access (``data.series.PriceSeries.load``, which
goes through ``data.repository.get_daily_bars``). Nothing here writes a row.

``source`` is always passed explicitly — the database mixes a 10-year
single-symbol research feed (``massive``) with a ~2-year bulk grouped-daily
archive (``massive_grouped``), and silently blending them would produce a
universe whose symbols cover different spans.

Bars are **adjusted as of the fetch date**, not point-in-time: a split or
dividend that happened after a bar was written is already reflected in it. The
grid therefore behaves as if every historical price had always been quoted on
today's share-count basis, and dividends are embedded in the adjusted series
rather than paid as cash.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from sqlalchemy.orm import Session

from signalforge.data.repository import SourceFilter
from signalforge.data.series import PriceSeries
from signalforge.grid.engine import GridSeries

__all__ = ["load_grid_series", "ADJUSTMENT_NOTE"]

ADJUSTMENT_NOTE = (
    "Daily bars are split/dividend adjusted AS OF THE FETCH DATE (not "
    "point-in-time). Dividends are embedded in the adjusted series, not paid "
    "as cash into the account."
)


def load_grid_series(
    session: Session,
    symbols: Sequence[str],
    start: date,
    end: date,
    *,
    source: SourceFilter = None,
    min_bars: int = 2,
) -> tuple[dict[str, GridSeries], list[str]]:
    """Load opens/closes for ``symbols``. Returns (series, symbols_with_no_bars).

    A symbol needs at least ``min_bars`` sessions to be usable at all (one to
    set the anchor, one to decide on) — anything less is reported as skipped
    rather than silently dropped.
    """
    out: dict[str, GridSeries] = {}
    missing: list[str] = []
    for sym in symbols:
        ps = PriceSeries.load(session, sym, start, end, source=source)
        if len(ps) < min_bars:
            missing.append(sym)
            continue
        out[sym] = GridSeries.from_price_series(ps)
    return out, missing
