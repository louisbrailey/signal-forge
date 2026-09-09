"""Ticker discovery from the provider's reference data.

Upserts EVERY active ``market=stocks`` U.S. ticker into ``universe_ticker``
(so "discovered" is the honest all-types count) and marks which are in scope
(``security_type`` in the configured set). Active-only by construction —
this is NOT a survivorship-free membership history."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from signalforge.db.models import UniverseTicker
from signalforge.observability import get_logger
from signalforge.universe.bulk import GroupedDailyClient

_log = get_logger("universe.discovery")

_LIST_PATH = "/v3/reference/tickers?market=stocks&active=true&locale=us&limit=1000"
_MAX_PAGES = 40


@dataclass(slots=True)
class DiscoveryReport:
    discovered_all_types: int = 0
    in_scope: int = 0
    upserted: int = 0
    pages: int = 0


def _parse_date(s: object) -> date | None:
    try:
        return date.fromisoformat(str(s)) if s else None
    except ValueError:
        return None


def refresh_reference(
    session: Session,
    client: GroupedDailyClient,
    *,
    security_types: tuple[str, ...] = ("CS", "ETF"),
    today: date | None = None,
) -> DiscoveryReport:
    today = today or datetime.now(UTC).date()
    rep = DiscoveryReport()
    existing = {t.ticker: t for t in session.scalars(select(UniverseTicker))}
    seen: set[str] = set()
    path: str | None = _LIST_PATH
    while path and rep.pages < _MAX_PAGES:
        body = client.get_json(path)
        rep.pages += 1
        for r in body.get("results") or []:
            if not isinstance(r, dict):
                continue
            tk = str(r.get("ticker") or "").strip().upper()
            if not tk or tk in seen:
                continue
            seen.add(tk)
            sec_type = str(r.get("type") or "").upper()
            row = existing.get(tk)
            if row is None:
                row = UniverseTicker(
                    ticker=tk, first_seen=today, last_seen=today, refreshed_at=datetime.now(UTC)
                )
                session.add(row)
                existing[tk] = row
            row.name = str(r.get("name") or "")[:200]
            row.security_type = sec_type[:8]
            row.primary_exchange = str(r.get("primary_exchange") or "")[:12]
            row.locale = str(r.get("locale") or "us")[:4]
            row.active = bool(r.get("active", True))
            row.list_date = _parse_date(r.get("list_date")) or row.list_date
            row.last_seen = today
            row.refreshed_at = datetime.now(UTC)
            rep.upserted += 1
            if sec_type in security_types:
                rep.in_scope += 1
        nxt = body.get("next_url") or ""
        path = re.sub(r"^https?://[^/]+", "", nxt) if nxt else None
    # anything previously discovered but absent now is no longer active
    for tk, row in existing.items():
        if tk not in seen and row.active:
            row.active = False
    session.flush()
    rep.discovered_all_types = int(
        session.scalar(select(func.count()).select_from(UniverseTicker)) or 0
    )
    _log.info(
        "universe.discovery",
        discovered=rep.discovered_all_types,
        in_scope=rep.in_scope,
        pages=rep.pages,
    )
    return rep


def enrich_market_caps(
    session: Session,
    client: GroupedDailyClient,
    tickers: list[str],
    *,
    max_requests: int,
) -> int:
    """Fill ``market_cap`` (current value only) for up to ``max_requests``
    tickers that don't have one yet — resumable across runs. Returns the
    number of tickers updated."""
    done = 0
    for tk in tickers:
        if done >= max_requests:
            break
        row = session.scalar(select(UniverseTicker).where(UniverseTicker.ticker == tk))
        if row is None or row.market_cap is not None:
            continue
        try:
            body = client.get_json(f"/v3/reference/tickers/{tk}")
        except Exception as exc:  # one bad ticker must not stop the run
            _log.warning("universe.market_cap_failed", ticker=tk, error=str(exc)[:120])
            continue
        res = body.get("results") or {}
        cap = res.get("market_cap")
        row.market_cap = float(cap) if isinstance(cap, (int, float)) else None
        row.sic_code = str(res.get("sic_code") or "")[:8]
        row.sic_description = str(res.get("sic_description") or "")[:160]
        row.list_date = _parse_date(res.get("list_date")) or row.list_date
        row.refreshed_at = datetime.now(UTC)
        done += 1
    session.flush()
    return done
