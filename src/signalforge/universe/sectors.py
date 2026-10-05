"""Populate ``instrument.sector`` so the paper ledger's sector cap can operate.

Until 2026-10-03 ``instrument.sector`` was blank on every row, so the 20%
per-sector budget in ``paper.ledger`` never applied. This module derives a
STABLE sector label for each instrument:

* **Stocks** — from the provider's SIC code (Massive ticker details,
  ``sic_code`` / ``sic_description``, already stored on ``universe_ticker`` by
  ``universe.discovery.enrich_market_caps``). The grouping key is the same
  2-digit SIC major group the universe screen's ``max_sector_share`` uses
  (``universe.screen``: ``sic_code[:2]``); :data:`SIC2_SECTOR` names each group,
  and :data:`SIC_PREFIX_SECTOR` refines the few major groups that straddle two
  sectors (e.g. 73 "business services" contains 737 "computer programming").
* **ETFs** — a sector SPDR maps to its sector (:data:`SECTOR_ETF`), so XLK and
  a software stock share one bucket; every other ETF is its own bucket
  ``ETF:<symbol>`` (a broad-market fund is not "a sector", and must not be
  lumped with an unrelated one).

An instrument whose sector cannot be derived is left blank; the ledger then
puts it in the single capped ``UNKNOWN`` bucket — unknown never means unlimited.

The labels are approximate (SIC is not GICS). They exist to bound correlated
paper exposure, not to classify companies; they are not used by any signal.

SQLite discipline (``db/session.py``): every network call runs with NO
transaction open, and each instrument is applied in its own short write
transaction, retried on transient lock contention.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from signalforge.db.models import Instrument, UniverseTicker
from signalforge.db.retry import retry_on_lock
from signalforge.observability import get_logger
from signalforge.universe.bulk import GroupedDailyClient

__all__ = [
    "SECTOR_ETF",
    "SIC2_SECTOR",
    "SIC_PREFIX_SECTOR",
    "SectorReport",
    "etf_sector",
    "refresh_sectors",
    "sector_from_sic",
    "sector_status",
]

_log = get_logger("universe.sectors")

TECHNOLOGY = "Technology"
FINANCIALS = "Financials"
HEALTH_CARE = "Health Care"
ENERGY = "Energy"
UTILITIES = "Utilities"
INDUSTRIALS = "Industrials"
MATERIALS = "Materials"
CONSUMER_DISCRETIONARY = "Consumer Discretionary"
CONSUMER_STAPLES = "Consumer Staples"
REAL_ESTATE = "Real Estate"
COMMUNICATION_SERVICES = "Communication Services"
PUBLIC_SECTOR = "Public Sector"

#: The one table mapping a sector ETF to the sector it holds.
SECTOR_ETF: dict[str, str] = {
    "XLK": TECHNOLOGY,
    "XLF": FINANCIALS,
    "XLV": HEALTH_CARE,
    "XLE": ENERGY,
    "XLU": UTILITIES,
    "XLI": INDUSTRIALS,
    "XLB": MATERIALS,
    "XLY": CONSUMER_DISCRETIONARY,
    "XLP": CONSUMER_STAPLES,
    "XLRE": REAL_ESTATE,
    "XLC": COMMUNICATION_SERVICES,
}

#: 2-digit SIC major group -> sector label. Same key as ``universe.screen``.
SIC2_SECTOR: dict[str, str] = {
    **dict.fromkeys(("01", "02", "07", "08", "09"), CONSUMER_STAPLES),  # agriculture
    **dict.fromkeys(("10", "12", "14"), MATERIALS),  # metal/coal/nonmetal mining
    "13": ENERGY,  # oil & gas extraction
    **dict.fromkeys(("15", "16", "17"), INDUSTRIALS),  # construction
    **dict.fromkeys(("20", "21"), CONSUMER_STAPLES),  # food, tobacco
    **dict.fromkeys(("22", "23", "25", "31", "39"), CONSUMER_DISCRETIONARY),
    **dict.fromkeys(("24", "26", "28", "30", "32", "33"), MATERIALS),
    "27": COMMUNICATION_SERVICES,  # printing & publishing
    "29": ENERGY,  # petroleum refining
    **dict.fromkeys(("34", "35", "37"), INDUSTRIALS),
    **dict.fromkeys(("36", "38"), TECHNOLOGY),  # electronic equipment, instruments
    **dict.fromkeys(("40", "41", "42", "43", "44", "45", "46", "47"), INDUSTRIALS),
    "48": COMMUNICATION_SERVICES,
    "49": UTILITIES,
    **dict.fromkeys(("50", "51"), INDUSTRIALS),  # wholesale trade
    **dict.fromkeys(("52", "55", "56", "57", "58", "59"), CONSUMER_DISCRETIONARY),
    **dict.fromkeys(("53", "54"), CONSUMER_STAPLES),  # general merchandise, food stores
    **dict.fromkeys(("60", "61", "62", "63", "64", "67"), FINANCIALS),
    "65": REAL_ESTATE,
    **dict.fromkeys(("70", "72", "75", "76", "79", "82"), CONSUMER_DISCRETIONARY),
    **dict.fromkeys(("73", "81", "87", "89"), INDUSTRIALS),  # business/professional services
    "78": COMMUNICATION_SERVICES,  # motion pictures
    **dict.fromkeys(("80", "83"), HEALTH_CARE),
    **dict.fromkeys(("91", "92", "93", "94", "95", "96", "97", "99"), PUBLIC_SECTOR),
}

#: Longer SIC prefixes that override their 2-digit group (longest prefix wins).
SIC_PREFIX_SECTOR: dict[str, str] = {
    "283": HEALTH_CARE,  # drugs
    "284": CONSUMER_STAPLES,  # soap, cosmetics
    "357": TECHNOLOGY,  # computer & office equipment
    "363": CONSUMER_DISCRETIONARY,  # household appliances
    "365": CONSUMER_DISCRETIONARY,  # household audio & video
    "371": CONSUMER_DISCRETIONARY,  # motor vehicles
    "384": HEALTH_CARE,  # medical instruments
    "385": HEALTH_CARE,  # ophthalmic goods
    "6798": REAL_ESTATE,  # real estate investment trusts
    "737": TECHNOLOGY,  # computer programming, software, data processing
    "8731": HEALTH_CARE,  # commercial physical & biological research
}

_ETF_TYPES = frozenset({"ETF", "ETN", "ETV", "ETS"})


def sector_from_sic(sic_code: str | None) -> str:
    """Sector label for a SIC code, or ``""`` when it cannot be derived."""
    code = "".join(ch for ch in str(sic_code or "") if ch.isdigit())
    if len(code) < 2:
        return ""
    if len(code) == 3:  # a 4-digit code that lost its leading zero
        code = "0" + code
    for width in (4, 3):
        hit = SIC_PREFIX_SECTOR.get(code[:width])
        if hit and len(code) >= width:
            return hit
    return SIC2_SECTOR.get(code[:2], "")


def etf_sector(symbol: str) -> str:
    sym = symbol.strip().upper()
    return SECTOR_ETF.get(sym, f"ETF:{sym}")


@dataclass(slots=True)
class SectorReport:
    instruments: int = 0
    updated: int = 0
    unchanged: int = 0
    unknown: int = 0
    requests: int = 0
    failed: int = 0
    skipped_budget: int = 0
    by_sector: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "instruments": self.instruments,
            "updated": self.updated,
            "unchanged": self.unchanged,
            "unknown": self.unknown,
            "requests": self.requests,
            "failed": self.failed,
            "skipped_budget": self.skipped_budget,
            "by_sector": dict(sorted(self.by_sector.items())),
        }


def sector_status(session: Session) -> dict[str, int]:
    """Instrument count per stored sector label (blank shown as ``UNKNOWN``)."""
    out: dict[str, int] = {}
    for sector in session.scalars(select(Instrument.sector)):
        key = (sector or "").strip() or "UNKNOWN"
        out[key] = out.get(key, 0) + 1
    return dict(sorted(out.items()))


def _apply(
    session: Session,
    instrument_id: int,
    sector: str,
    industry: str,
    sic: tuple[str, str] | None,
) -> bool:
    """One instrument, one short write transaction. Returns True if a row changed."""

    def unit() -> bool:
        try:
            inst = session.get(Instrument, instrument_id, populate_existing=True)
            if inst is None:
                session.rollback()
                return False
            changed = False
            if sector and inst.sector != sector:
                inst.sector = sector[:64]
                changed = True
            if industry and inst.industry != industry[:96]:
                inst.industry = industry[:96]
                changed = True
            if sic is not None:
                row = session.scalar(
                    select(UniverseTicker).where(UniverseTicker.ticker == inst.symbol)
                )
                if row is not None and (row.sic_code, row.sic_description) != sic:
                    row.sic_code, row.sic_description = sic
                    row.refreshed_at = datetime.now(UTC)
                    changed = True
            session.commit()
            return changed
        except Exception:
            session.rollback()
            raise

    return retry_on_lock(unit, label=f"sectors:{instrument_id}")


def refresh_sectors(
    session: Session,
    client: GroupedDailyClient | None,
    *,
    max_requests: int = 500,
    only_missing: bool = False,
) -> SectorReport:
    """Derive and store a sector for every instrument.

    ETFs and stocks whose SIC code is already stored need no network. A stock
    with no stored SIC code costs one reference request (at most
    ``max_requests`` per run — resumable: re-run to continue). ``client=None``
    forbids the network entirely. ``only_missing`` leaves instruments that
    already have a sector untouched. An existing label is never blanked.
    """
    rep = SectorReport()
    # Read phase: plain values only, then end the transaction before any I/O.
    instruments = [
        (i.id, i.symbol, (i.instrument_type or "").lower(), (i.sector or "").strip())
        for i in session.scalars(select(Instrument).order_by(Instrument.symbol))
    ]
    tickers = {
        t.ticker: (t.security_type or "", t.sic_code or "", t.sic_description or "")
        for t in session.scalars(select(UniverseTicker))
    }
    session.commit()

    rep.instruments = len(instruments)
    for inst_id, symbol, inst_type, current in instruments:
        if only_missing and current:
            rep.unchanged += 1
            rep.by_sector[current] = rep.by_sector.get(current, 0) + 1
            continue
        sec_type, sic_code, sic_desc = tickers.get(symbol, ("", "", ""))
        fetched: tuple[str, str] | None = None
        if inst_type == "etf" or sec_type.upper() in _ETF_TYPES:
            sector, industry = etf_sector(symbol), ""
        else:
            if not sic_code:
                if client is None or rep.requests >= max_requests:
                    rep.skipped_budget += 1
                else:
                    rep.requests += 1
                    try:
                        # No transaction is open here (committed above / by _apply).
                        body = client.get_json(f"/v3/reference/tickers/{symbol}")
                    except Exception as exc:  # one bad ticker must not stop the run
                        rep.failed += 1
                        _log.warning("universe.sector_failed", ticker=symbol, error=str(exc)[:120])
                    else:
                        res = body.get("results") or {}
                        if not isinstance(res, dict):
                            res = {}
                        if str(res.get("type") or "").upper() in _ETF_TYPES:
                            sec_type = "ETF"
                        sic_code = str(res.get("sic_code") or "")[:8]
                        sic_desc = str(res.get("sic_description") or "")[:160]
                        fetched = (sic_code, sic_desc)
            if sec_type.upper() in _ETF_TYPES:
                sector, industry = etf_sector(symbol), ""
            else:
                sector, industry = sector_from_sic(sic_code), sic_desc
        if _apply(session, inst_id, sector, industry, fetched):
            rep.updated += 1
        else:
            rep.unchanged += 1
        final = sector or current
        if final:
            rep.by_sector[final] = rep.by_sector.get(final, 0) + 1
        else:
            rep.unknown += 1
    _log.info("universe.sectors", **{k: v for k, v in rep.to_dict().items() if k != "by_sector"})
    return rep
