"""Hourly crypto bars (Massive Currencies) — research data only.

Fetches completed hourly aggregates for BTC/ETH/SOL-style pairs into
``crypto_bar_intraday``. Crypto trades around the clock, so there are no
sessions or holidays: every UTC hour is expected to have a bar, and a missing
hour is reported as a gap, never filled.

Request sizing: the provider's 50,000 cap counts ONE-MINUTE base aggregates
(see ``data.ingest`` incident note, 2026-10-26). A crypto day has 1,440
minutes, so a request may span at most ~34 days; requests are split on fixed
calendar months (31 x 1,440 = 44,640). Bars the provider returns just outside a
requested window (its date range may be read in a different time zone) are
dropped and counted rather than rejecting the whole month, because adjacent
months cover them and the unique key de-duplicates.

Nothing here creates a signal, candidate, alert, paper position or order.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from signalforge.data.adapters.base import AdapterError
from signalforge.data.forex import CRYPTO, ForexClient, parse_pairs
from signalforge.db.models import CryptoBarIntraday
from signalforge.db.types import utcnow
from signalforge.domain import LatencyCategory
from signalforge.killswitch import ensure_not_engaged
from signalforge.observability import get_logger

_log = get_logger("data.crypto_intraday")

SOURCE = "massive_crypto"
BAR_SIZE = "1h"
PROVIDER_ROW_CAP = 50_000
_BASE_MINUTES_PER_DAY = 24 * 60


def month_chunks(start: date, end: date) -> list[tuple[date, date]]:
    """Fixed calendar-month windows covering ``[start, end]``."""
    out: list[tuple[date, date]] = []
    lo = start
    while lo <= end:
        nxt = date(lo.year + (lo.month == 12), 1 if lo.month == 12 else lo.month + 1, 1)
        hi = min(nxt - timedelta(days=1), end)
        if ((hi - lo).days + 1) * _BASE_MINUTES_PER_DAY > PROVIDER_ROW_CAP:  # pragma: no cover
            raise ValueError("a month chunk exceeds the provider's base-aggregate cap")
        out.append((lo, hi))
        lo = hi + timedelta(days=1)
    return out


@dataclass(slots=True)
class ParsedHours:
    bars: list[dict[str, Any]] = field(default_factory=list)
    outside_window: int = 0


def parse_hours(body: dict[str, Any], *, start: date, end: date) -> ParsedHours:
    """Validate an hourly aggregates response; any malformed bar rejects it."""
    rows = body.get("results") or []
    if not isinstance(rows, list):
        raise ValueError("results is not a list")
    lo = datetime(start.year, start.month, start.day, tzinfo=UTC)
    hi = datetime(end.year, end.month, end.day, tzinfo=UTC) + timedelta(days=1)
    out = ParsedHours()
    previous: datetime | None = None
    for r in rows:
        if not isinstance(r, dict):
            raise ValueError("bar is not an object")
        t = float(r["t"])
        o, h, low, c = (float(r[k]) for k in ("o", "h", "l", "c"))
        if not all(math.isfinite(x) for x in (t, o, h, low, c)):
            raise ValueError("non-finite bar value")
        stamp = datetime.fromtimestamp(t / 1000, UTC)
        if (stamp.minute, stamp.second) != (0, 0):
            raise ValueError("bar timestamp is not on the hour")
        if previous is not None and stamp <= previous:
            raise ValueError("bars out of order or duplicated")
        previous = stamp
        if min(o, h, low, c) <= 0 or not low <= min(o, c) <= max(o, c) <= h:
            raise ValueError("inconsistent OHLC")
        if not lo <= stamp < hi:
            out.outside_window += 1
            continue
        v, vw, n = r.get("v"), r.get("vw"), r.get("n")
        out.bars.append(
            {
                "bar_start": stamp,
                "open": o,
                "high": h,
                "low": low,
                "close": c,
                "volume": float(v) if v is not None and math.isfinite(float(v)) else None,
                "vwap": float(vw) if vw is not None and math.isfinite(float(vw)) else None,
                "transactions": int(n) if n is not None else None,
            }
        )
    return out


@dataclass(slots=True)
class HourlyPairReport:
    pair: str
    requests: int = 0
    written: int = 0
    skipped_existing: int = 0
    outside_window: int = 0
    failed_months: list[str] = field(default_factory=list)
    missing_hours: int = 0


@dataclass(slots=True)
class HourlyIngestReport:
    start: str
    end: str
    pairs: list[HourlyPairReport] = field(default_factory=list)

    @property
    def written(self) -> int:
        return sum(p.written for p in self.pairs)


def last_complete_hour(now: datetime | None = None) -> datetime:
    n = (now or datetime.now(UTC)).astimezone(UTC).replace(minute=0, second=0, microsecond=0)
    return n - timedelta(hours=1)


def ingest_crypto_hourly(
    session: Session,
    pairs: Sequence[str],
    *,
    start: date,
    end: date | None = None,
    client: ForexClient | None = None,
    now: datetime | None = None,
) -> HourlyIngestReport:
    """Backfill / top up hourly bars for ``[start, end]`` (UTC days). Months
    already fully stored are skipped without a request; an incomplete or
    in-progress month is re-requested and de-duplicated. Only bars that have
    fully completed (start <= last complete hour) are stored."""
    chosen = parse_pairs(pairs, CRYPTO)
    client = client or ForexClient(prefix=CRYPTO.prefix)
    cutoff = last_complete_hour(now)
    end = min(end or cutoff.date(), cutoff.date())
    rep = HourlyIngestReport(start=start.isoformat(), end=end.isoformat())
    for pair in chosen:
        pr = HourlyPairReport(pair=pair)
        rep.pairs.append(pr)
        for lo, hi in month_chunks(start, end):
            ensure_not_engaged()
            w_lo = datetime(lo.year, lo.month, lo.day, tzinfo=UTC)
            w_hi = min(
                datetime(hi.year, hi.month, hi.day, tzinfo=UTC) + timedelta(days=1),
                cutoff + timedelta(hours=1),
            )
            expected = int((w_hi - w_lo).total_seconds() // 3600)
            have = (
                session.scalar(
                    select(func.count())
                    .select_from(CryptoBarIntraday)
                    .where(
                        CryptoBarIntraday.pair == pair,
                        CryptoBarIntraday.bar_size == BAR_SIZE,
                        CryptoBarIntraday.source == SOURCE,
                        CryptoBarIntraday.bar_start >= w_lo,
                        CryptoBarIntraday.bar_start < w_hi,
                    )
                )
                or 0
            )
            session.commit()  # no transaction held across the network call
            if have >= expected:
                continue
            pr.requests += 1
            try:
                parsed = parse_hours(
                    client.aggregates(pair, lo, hi, multiplier=1, timespan="hour"),
                    start=lo,
                    end=hi,
                )
            except (AdapterError, ValueError, KeyError, TypeError, OverflowError) as exc:
                pr.failed_months.append(f"{lo:%Y-%m}: {str(exc)[:120]}")
                _log.warning("crypto_hourly.month_failed", pair=pair, month=f"{lo:%Y-%m}")
                continue
            pr.outside_window += parsed.outside_window
            existing = set(
                session.scalars(
                    select(CryptoBarIntraday.bar_start).where(
                        CryptoBarIntraday.pair == pair,
                        CryptoBarIntraday.bar_size == BAR_SIZE,
                        CryptoBarIntraday.source == SOURCE,
                        CryptoBarIntraday.bar_start >= w_lo,
                        CryptoBarIntraday.bar_start < w_hi,
                    )
                )
            )
            existing = {e if e.tzinfo else e.replace(tzinfo=UTC) for e in existing}
            stamp = utcnow()
            for bar in parsed.bars:
                if bar["bar_start"] > cutoff:
                    continue  # not yet complete
                if bar["bar_start"] in existing:
                    pr.skipped_existing += 1
                    continue
                session.add(
                    CryptoBarIntraday(
                        pair=pair,
                        bar_size=BAR_SIZE,
                        source=SOURCE,
                        latency_category=LatencyCategory.HISTORICAL,
                        ingested_at=stamp,
                        **bar,
                    )
                )
                pr.written += 1
            session.commit()
        total = (
            session.scalar(
                select(func.count())
                .select_from(CryptoBarIntraday)
                .where(
                    CryptoBarIntraday.pair == pair,
                    CryptoBarIntraday.bar_size == BAR_SIZE,
                    CryptoBarIntraday.source == SOURCE,
                )
            )
            or 0
        )
        first = session.scalar(
            select(func.min(CryptoBarIntraday.bar_start)).where(
                CryptoBarIntraday.pair == pair, CryptoBarIntraday.bar_size == BAR_SIZE
            )
        )
        if first is not None:
            first = first if first.tzinfo else first.replace(tzinfo=UTC)
            span = int((cutoff - first).total_seconds() // 3600) + 1
            pr.missing_hours = max(0, span - total)
        session.commit()
        _log.info(
            "crypto_hourly.pair",
            pair=pair,
            requests=pr.requests,
            written=pr.written,
            failed=len(pr.failed_months),
            missing_hours=pr.missing_hours,
        )
    return rep
