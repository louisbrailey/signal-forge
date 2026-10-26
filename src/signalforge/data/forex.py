"""Forex daily-bar ingest (Massive Currencies) — research data only.

Fetches completed UTC-day aggregates for a configured list of currency pairs
into ``fx_bar_daily``. Nothing here creates a signal, candidate, alert, paper
position or order, and no equity path reads the table (import-linter keeps
this module off the decision path).

Calendar: FX trades roughly Sunday 17:00 to Friday 17:00 New York time. The
provider's daily bar is a UTC calendar day, so a Saturday/Sunday bar is a thin
partial session. Weekend bars are dropped and counted, never stored. A
weekday with no bar (e.g. 25 December, 1 January) is reported as a gap, never
filled.

Pacing: the Currencies key is the same key the equity ingest uses, so this
client paces at ``market_data_min_request_spacing_s`` and backs off a full
rolling minute on HTTP 429. Network I/O never runs inside a write transaction.
"""

from __future__ import annotations

import math
import re
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from signalforge.config import get_settings
from signalforge.data.adapters.base import AdapterCapability, AdapterError
from signalforge.data.ingest import record_feed_failure, record_feed_success
from signalforge.db.models import FxBarDaily
from signalforge.db.types import utcnow
from signalforge.domain import FeedType, LatencyCategory
from signalforge.killswitch import ensure_not_engaged
from signalforge.observability import get_logger

_log = get_logger("data.forex")

PROVIDER = "massive_fx"
_BASE_URL = "https://api.massive.com"
_PAIR_RE = re.compile(r"[A-Z]{6}")
_MAX_PAIRS = 40
_MAX_ATTEMPTS = 4
_RATE_LIMIT_BACKOFF_S = 61.0
_PAGE_LIMIT = 50000

CAPABILITY = AdapterCapability(
    provider_name=PROVIDER,
    feed_type=FeedType.BAR_DAILY,
    latency_category=LatencyCategory.END_OF_DAY,
    supports_point_in_time=True,
    entitlement_note=(
        "Currencies Starter: completed UTC-day forex aggregates. END-OF-DAY only; "
        "weekend partial bars dropped; volume is a tick count, not traded size. "
        "Research data only — no strategy, alert or paper path reads it."
    ),
    rate_limit_per_min=None,
    is_simulated=False,
)


def parse_pairs(raw: str | Sequence[str]) -> list[str]:
    """Normalise ``"EURUSD, usdjpy"`` / ``["C:EURUSD"]`` to unique 6-letter pairs."""
    items = raw.split(",") if isinstance(raw, str) else list(raw)
    out: list[str] = []
    for item in items:
        p = item.strip().upper().removeprefix("C:").replace("/", "")
        if not p:
            continue
        if not _PAIR_RE.fullmatch(p):
            raise ValueError(f"invalid currency pair {item!r}: expected six letters, e.g. EURUSD")
        if p not in out:
            out.append(p)
    if len(out) > _MAX_PAIRS:
        raise ValueError(f"at most {_MAX_PAIRS} currency pairs per run")
    return out


def last_completed_fx_day(now: datetime | None = None) -> date:
    """The most recent fully completed UTC weekday."""
    d = (now or datetime.now(UTC)).astimezone(UTC).date() - timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def fx_weekdays(start: date, end: date) -> list[date]:
    out, d = [], start
    while d <= end:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


@dataclass(slots=True)
class ParsedBars:
    bars: list[dict[str, Any]] = field(default_factory=list)
    weekend_dropped: int = 0


def parse_bars(body: dict[str, Any], *, start: date, end: date) -> ParsedBars:
    """Validate a ``/v2/aggs`` forex response. Any malformed bar rejects the
    whole response — a pair is either stored whole or not at all."""
    rows = body.get("results") or []
    if not isinstance(rows, list):
        raise ValueError("results is not a list")
    out = ParsedBars()
    previous: date | None = None
    for r in rows:
        if not isinstance(r, dict):
            raise ValueError("bar is not an object")
        t = float(r["t"])
        o, h, lo, c = (float(r[k]) for k in ("o", "h", "l", "c"))
        if not all(math.isfinite(x) for x in (t, o, h, lo, c)):
            raise ValueError("non-finite bar value")
        stamp = datetime.fromtimestamp(t / 1000, UTC)
        if (stamp.hour, stamp.minute, stamp.second) != (0, 0, 0):
            raise ValueError("bar timestamp is not a UTC day boundary")
        d = stamp.date()
        if previous is not None and d <= previous:
            raise ValueError("bars out of order or duplicated")
        previous = d
        if min(o, h, lo, c) <= 0 or not lo <= min(o, c) <= max(o, c) <= h:
            raise ValueError("inconsistent OHLC")
        if not start <= d <= end:
            raise ValueError("bar outside the requested window")
        if d.weekday() >= 5:
            out.weekend_dropped += 1
            continue
        v = r.get("v")
        vw = r.get("vw")
        n = r.get("n")
        out.bars.append(
            {
                "session_date": d,
                "open": o,
                "high": h,
                "low": lo,
                "close": c,
                "tick_volume": float(v) if v is not None and math.isfinite(float(v)) else None,
                "vwap": float(vw) if vw is not None and math.isfinite(float(vw)) else None,
                "transactions": int(n) if n is not None else None,
            }
        )
    return out


class ForexClient:
    """Read-only client for ``/v2/aggs/ticker/C:{pair}/range/1/day/{from}/{to}``.
    The key travels only in the Authorization header and never leaves this class."""

    def __init__(
        self,
        api_key: str | None = None,
        *,
        client: httpx.Client | None = None,
        spacing_s: float | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        settings = get_settings()
        self._key = settings.market_data_api_key.get_secret_value() if api_key is None else api_key
        self._client = client
        self._spacing = (
            settings.market_data_min_request_spacing_s if spacing_s is None else spacing_s
        )
        self._sleep = sleep
        self._last: float | None = None

    def daily(self, pair: str, start: date, end: date) -> dict[str, Any]:
        if not self._key:
            raise AdapterError("forex: MARKET_DATA_API_KEY missing")
        path = (
            f"/v2/aggs/ticker/C:{pair}/range/1/day/{start.isoformat()}/{end.isoformat()}"
            f"?adjusted=true&sort=asc&limit={_PAGE_LIMIT}"
        )
        last_status: int | None = None
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            self._pace()
            ensure_not_engaged()
            self._last = time.monotonic()
            getter = self._client.get if self._client is not None else httpx.get
            try:
                resp = getter(
                    _BASE_URL + path,
                    headers={"Authorization": f"Bearer {self._key}"},
                    timeout=60.0,
                    follow_redirects=False,
                )
            except httpx.HTTPError:
                if attempt >= _MAX_ATTEMPTS:
                    raise AdapterError("forex: network request failed") from None
                self._sleep(min(30.0, 1.5 * 2 ** (attempt - 1)))
                continue
            if resp.status_code == 200:
                try:
                    body = resp.json()
                except ValueError:
                    raise AdapterError("forex: response was not JSON") from None
                if not isinstance(body, dict):
                    raise AdapterError("forex: unexpected response shape")
                if body.get("next_url"):
                    raise AdapterError("forex: paginated response; narrow the window")
                return body
            last_status = resp.status_code
            if resp.status_code in (401, 403):
                raise AdapterError(f"forex: HTTP {resp.status_code} (not entitled)")
            if resp.status_code in (429, 500, 502, 503, 504) and attempt < _MAX_ATTEMPTS:
                retry_after = resp.headers.get("retry-after", "")
                if retry_after.replace(".", "", 1).isdigit():
                    self._sleep(float(retry_after))
                elif resp.status_code == 429:
                    self._sleep(_RATE_LIMIT_BACKOFF_S)
                else:
                    self._sleep(min(30.0, 1.5 * 2 ** (attempt - 1)))
                continue
            break
        raise AdapterError(f"forex: HTTP {last_status}", rate_limited=last_status == 429)

    def _pace(self) -> None:
        if self._last is None or self._spacing <= 0:
            return
        wait = self._spacing - (time.monotonic() - self._last)
        while wait > 0:
            ensure_not_engaged()
            self._sleep(min(0.2, wait))
            wait = self._spacing - (time.monotonic() - self._last)


@dataclass(slots=True)
class PairReport:
    pair: str
    requested_from: str | None = None
    requested_to: str | None = None
    written: int = 0
    skipped_existing: int = 0
    weekend_dropped: int = 0
    gaps: list[str] = field(default_factory=list)
    status: str = "ok"  # ok | up_to_date | failed
    error: str = ""


@dataclass(slots=True)
class ForexIngestReport:
    end: str = ""
    pairs: list[PairReport] = field(default_factory=list)

    @property
    def written(self) -> int:
        return sum(p.written for p in self.pairs)

    @property
    def failed(self) -> list[str]:
        return [p.pair for p in self.pairs if p.status == "failed"]


def _latest_stored(session: Session, pair: str) -> date | None:
    return session.scalar(
        select(func.max(FxBarDaily.session_date)).where(
            FxBarDaily.pair == pair, FxBarDaily.source == PROVIDER
        )
    )


def ingest_forex(
    session: Session,
    pairs: Sequence[str],
    *,
    lookback_days: int,
    client: ForexClient | None = None,
    now: datetime | None = None,
) -> ForexIngestReport:
    """Top up each pair from its newest stored bar (or ``lookback_days`` back)
    to the last completed UTC weekday. Idempotent: an existing
    (pair, date, source) row is never rewritten."""
    if lookback_days <= 0:
        raise ValueError("lookback_days must be positive")
    pairs = parse_pairs(pairs)
    client = client or ForexClient()
    end = last_completed_fx_day(now)
    rep = ForexIngestReport(end=end.isoformat())
    for pair in pairs:
        ensure_not_engaged()
        pr = PairReport(pair=pair)
        rep.pairs.append(pr)
        latest = _latest_stored(session, pair)
        start = (latest + timedelta(days=1)) if latest else end - timedelta(days=lookback_days)
        session.commit()  # release any read transaction before network I/O
        if start > end:
            pr.status = "up_to_date"
            continue
        pr.requested_from, pr.requested_to = start.isoformat(), end.isoformat()
        try:
            body = client.daily(pair, start, end)
            parsed = parse_bars(body, start=start, end=end)
        except (AdapterError, ValueError, KeyError, TypeError, OverflowError) as exc:
            pr.status = "failed"
            pr.error = str(exc)[:200]
            record_feed_failure(
                session,
                PROVIDER,
                FeedType.BAR_DAILY,
                pr.error,
                rate_limited=bool(getattr(exc, "rate_limited", False)),
                capability=CAPABILITY,
            )
            session.commit()
            _log.warning("forex.pair_failed", pair=pair, error=pr.error)
            continue
        pr.weekend_dropped = parsed.weekend_dropped
        existing = set(
            session.scalars(
                select(FxBarDaily.session_date).where(
                    FxBarDaily.pair == pair,
                    FxBarDaily.source == PROVIDER,
                    FxBarDaily.session_date >= start,
                    FxBarDaily.session_date <= end,
                )
            )
        )
        stamp = utcnow()
        for bar in parsed.bars:
            if bar["session_date"] in existing:
                pr.skipped_existing += 1
                continue
            session.add(
                FxBarDaily(
                    pair=pair,
                    source=PROVIDER,
                    latency_category=LatencyCategory.END_OF_DAY,
                    ingested_at=stamp,
                    quality_flags=[],
                    **bar,
                )
            )
            pr.written += 1
        have = existing | {b["session_date"] for b in parsed.bars}
        pr.gaps = [d.isoformat() for d in fx_weekdays(start, end) if d not in have]
        record_feed_success(session, CAPABILITY)
        session.commit()
        _log.info(
            "forex.pair",
            pair=pair,
            written=pr.written,
            skipped=pr.skipped_existing,
            weekend_dropped=pr.weekend_dropped,
            gaps=len(pr.gaps),
        )
    return rep
