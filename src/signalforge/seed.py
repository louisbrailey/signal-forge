"""Load clearly-labelled SIMULATED demo data.

Everything created here comes from the deterministic fixture adapter and is
marked ``is_simulated=True``. Safe to run repeatedly (idempotent).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select

from signalforge.config import get_settings
from signalforge.data.adapters.fixture import FixtureMarketDataAdapter
from signalforge.data.ingest import ingest_universe
from signalforge.data.repository import get_or_create_instrument
from signalforge.db.models import Instrument, PaperAccount, Watchlist, WatchlistMember
from signalforge.db.session import session_scope

DEFAULT_PAPER_CASH = Decimal("10000")
DEMO_WATCHLIST_NAME = "Default"


@dataclass
class SeedSummary:
    instruments: int
    bars_written: int
    paper_account: str
    watchlist: str
    simulated: bool = True


def seed_demo_data(years: int = 3) -> SeedSummary:
    settings = get_settings()
    cfg = settings.research
    etfs = set(cfg.etf_universe)
    symbols = list(cfg.universe)
    end = date.today()
    start = end - timedelta(days=365 * years + 10)

    with session_scope() as session:
        # Paper account
        acct = session.scalar(select(PaperAccount).where(PaperAccount.name == "default"))
        if acct is None:
            acct = PaperAccount(
                name="default", initial_cash=DEFAULT_PAPER_CASH, cash=DEFAULT_PAPER_CASH
            )
            session.add(acct)

        # Instruments + watchlist
        wl = session.scalar(select(Watchlist).where(Watchlist.name == DEMO_WATCHLIST_NAME))
        if wl is None:
            wl = Watchlist(name=DEMO_WATCHLIST_NAME)
            session.add(wl)
            session.flush()
        existing_members = {
            m.instrument_id
            for m in session.scalars(
                select(WatchlistMember).where(WatchlistMember.watchlist_id == wl.id)
            )
        }
        for sym in symbols:
            inst = get_or_create_instrument(
                session, sym, instrument_type="etf" if sym in etfs else "stock"
            )
            if inst.id not in existing_members:
                session.add(WatchlistMember(watchlist_id=wl.id, instrument_id=inst.id))

        # Bars (fixture, SIMULATED)
        report = ingest_universe(session, FixtureMarketDataAdapter(), symbols, start, end)
        instrument_count = int(session.scalar(select(func.count()).select_from(Instrument)) or 0)

    return SeedSummary(
        instruments=instrument_count,
        bars_written=report.bars_written,
        paper_account=f"default (${DEFAULT_PAPER_CASH})",
        watchlist=f"{DEMO_WATCHLIST_NAME} ({len(symbols)} symbols)",
    )
