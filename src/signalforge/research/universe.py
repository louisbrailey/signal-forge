"""Apply the conservative liquid-universe screen (ARCHITECTURE.md §9).

The configured watchlist + ETF set is the *candidate* pool; a symbol is only
scanned if it clears every active :class:`UniverseFilters` check that we have
local data for. Filters we cannot evaluate yet (market cap, quoted spread) are
reported as ``data_unavailable`` rather than silently passed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from signalforge.config.research import ResearchConfig, UniverseFilters
from signalforge.db.models import EarningsEvent, Instrument, OHLCVDaily


@dataclass(slots=True)
class UniverseScreen:
    kept: list[str] = field(default_factory=list)
    dropped: dict[str, list[str]] = field(default_factory=dict)  # symbol -> failed checks
    data_unavailable: list[str] = field(default_factory=list)  # filters we could not check

    def _drop(self, sym: str, reason: str) -> None:
        self.dropped.setdefault(sym, []).append(reason)


def screen_universe(
    session: Session,
    cfg: ResearchConfig,
    *,
    as_of: date | None = None,
) -> UniverseScreen:
    f: UniverseFilters = cfg.universe_filters
    end = as_of or date.today()
    scr = UniverseScreen()
    if f.min_market_cap:
        scr.data_unavailable.append("min_market_cap (no fundamentals feed ingested)")
    if f.max_avg_spread_bps:
        scr.data_unavailable.append("max_avg_spread_bps (no quote feed ingested)")

    for sym in cfg.universe:
        inst = session.scalar(select(Instrument).where(Instrument.symbol == sym))
        if inst is None:
            scr._drop(sym, "no instrument row / no data")
            continue

        n_bars = int(
            session.scalar(
                select(func.count(OHLCVDaily.id)).where(OHLCVDaily.instrument_id == inst.id)
            )
            or 0
        )
        if n_bars < f.min_history_days:
            scr._drop(sym, f"history {n_bars} < {f.min_history_days} sessions")
        close_row = session.scalar(
            select(OHLCVDaily.close)
            .where(OHLCVDaily.instrument_id == inst.id)
            .order_by(OHLCVDaily.session_date.desc())
            .limit(1)
        )
        if close_row is not None and close_row < f.min_price:
            scr._drop(sym, f"price {close_row:.2f} < {f.min_price}")

        # average dollar volume over the last ~20 sessions
        addv = session.scalar(
            select(func.avg(OHLCVDaily.close * OHLCVDaily.volume)).where(
                OHLCVDaily.instrument_id == inst.id,
                OHLCVDaily.session_date >= end - timedelta(days=40),
            )
        )
        if addv is not None and addv < f.min_avg_dollar_volume:
            scr._drop(sym, f"ADDV ${addv:,.0f} < ${f.min_avg_dollar_volume:,.0f}")

        if inst.sector and inst.sector in f.excluded_sectors:
            scr._drop(sym, f"excluded sector {inst.sector}")

        if f.exclude_within_days_of_earnings:
            near = session.scalar(
                select(func.count())
                .select_from(EarningsEvent)
                .where(
                    EarningsEvent.instrument_id == inst.id,
                    EarningsEvent.scheduled_for
                    >= end - timedelta(days=f.exclude_within_days_of_earnings),
                    EarningsEvent.scheduled_for
                    <= end + timedelta(days=f.exclude_within_days_of_earnings),
                )
            )
            if near:
                scr._drop(sym, f"within {f.exclude_within_days_of_earnings}d of earnings")

        if sym not in scr.dropped:
            scr.kept.append(sym)

    if len(scr.kept) > f.max_universe_size:
        for sym in scr.kept[f.max_universe_size :]:
            scr._drop(sym, f"universe cap {f.max_universe_size} reached")
        scr.kept = scr.kept[: f.max_universe_size]
    return scr
