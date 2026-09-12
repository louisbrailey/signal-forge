"""Massive completed daily bars (END-OF-DAY) + historical intraday aggregates.

Read-only REST adapter. No quotes, no streaming, no earnings, no separate
corporate-action feed. The daily feed's ``latency_category`` is hard-wired to
``END_OF_DAY`` regardless of the account's plan, so live alerts stay disabled
for horizons that need intraday freshness until a separate, explicitly licensed
streaming integration proves a real-time entitlement.

``fetch_intraday_bars`` exists for one purpose: the **research backfill** of
``ohlcv_intraday``. Its capability is declared ``DELAYED`` (>= 15 min on this
plan), never ``REALTIME`` — at a 15m research bar the delay equals the bar
size, so the backtest's next-bar-open fill is permanently one bar earlier than
this entitlement can attain. That is a disclosed modelling limit, not something
this adapter can fix; see docs/INTRADAY_OPERATION.md.

Fails closed: without an API key every fetch raises ``AdapterError``.
"""

from __future__ import annotations

import json
import math
import re
import time
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx

from signalforge.config import get_settings
from signalforge.data.adapters.base import (
    AdapterCapability,
    AdapterError,
    CorporateActionRecord,
    DailyBar,
    EarningsRecord,
    FeedType,
    IntradayBar,
    LatencyCategory,
    Provenance,
)
from signalforge.data.calendar import BAR_MINUTES
from signalforge.killswitch import ensure_not_engaged

_BASE_URL = "https://api.massive.com"
_SYMBOL_RE = re.compile(r"[A-Z][A-Z0-9.-]{0,14}")
# Basic plan: 5 requests/minute. Pace conservatively, including between symbols.
# Overridable via MARKET_DATA_MIN_REQUEST_SPACING_S for higher-tier plans.
_MIN_REQUEST_SPACING_S = 12.1
_RETRY_STATUS = frozenset({429, 500, 502, 503, 504})
_MAX_ATTEMPTS = 5
_BACKOFF_BASE_S = 1.5
_BACKOFF_CAP_S = 30.0


# Daily bars for session D are requested only from this ET wall-clock time on
# D — the same time the scheduler's EOD job fires — so a run at 17:30 ET picks
# up D's closed bar and /ops "daily bars current" means what it says.
COMPLETED_SESSION_CUTOFF_ET = (17, 30)


def _intraday_span(bar_size: str) -> tuple[int, str]:
    """``"15m"`` -> ``(15, "minute")``. The provider's aggregates endpoint takes
    a multiplier and a unit; this is the only place the mapping lives."""
    try:
        minutes = BAR_MINUTES[bar_size]
    except KeyError:
        raise ValueError(
            f"unsupported bar_size {bar_size!r}; known: {sorted(BAR_MINUTES)}"
        ) from None
    return (minutes // 60, "hour") if minutes % 60 == 0 else (minutes, "minute")


def completed_session_cutoff(now: datetime | None = None) -> date:
    n = (now or datetime.now(ZoneInfo("America/New_York"))).astimezone(ZoneInfo("America/New_York"))
    if (n.hour, n.minute) >= COMPLETED_SESSION_CUTOFF_ET:
        return n.date()
    return n.date() - timedelta(days=1)


class MassiveAdapter:
    """Implements :class:`~signalforge.data.adapters.base.MarketDataAdapter`."""

    provider_name = "massive"

    def __init__(
        self,
        api_key: str | None = None,
        *,
        client: httpx.Client | None = None,
        min_request_spacing_s: float | None = None,
    ) -> None:
        settings = get_settings()
        self._key = settings.market_data_api_key.get_secret_value() if api_key is None else api_key
        self._client = client
        self._spacing_s = (
            min_request_spacing_s
            if min_request_spacing_s is not None
            else settings.market_data_min_request_spacing_s
        )
        self._last_request = 0.0
        self._raw: dict[tuple[str, date, date], str] = {}

    @property
    def capabilities(self) -> Sequence[AdapterCapability]:
        return (
            AdapterCapability(
                provider_name=self.provider_name,
                feed_type=FeedType.BAR_DAILY,
                latency_category=LatencyCategory.END_OF_DAY,
                supports_point_in_time=False,
                entitlement_note=(
                    "Completed daily bars only; split-adjusted, not dividend-adjusted. "
                    "No earnings feed. Real-time entitlement is not verified by this adapter."
                ),
                rate_limit_per_min=5,
                is_simulated=False,
            ),
            AdapterCapability(
                provider_name=self.provider_name,
                feed_type=FeedType.BAR_INTRADAY,
                # DELAYED, never REALTIME: the plan's intraday aggregates are
                # delayed by >= 15 minutes (data/entitlements.py, feed
                # `stocks_intraday_aggs_5m`; reports/SUBSCRIPTION_STATUS.md
                # "No real-time feed on this plan"). At a 15m research bar that
                # delay EQUALS the bar size, so the backtest's fill (the open of
                # bar t+1) precedes the earliest attainable action (the open of
                # bar t+2) by exactly one bar, permanently. Historical backfill
                # is unaffected; live intraday execution is not modelled.
                latency_category=LatencyCategory.DELAYED,
                supports_point_in_time=False,
                entitlement_note=(
                    "Historical intraday aggregates for RESEARCH BACKFILL. Delayed >= 15 min: "
                    "at a 15m bar the modelled next-bar-open fill is one bar earlier than this "
                    "entitlement can attain. Not a live feed."
                ),
                delay_estimate="15 min",
                rate_limit_per_min=5,
                is_simulated=False,
            ),
        )

    def _sleep(self, seconds: float) -> None:
        # break the wait into short chunks so the kill switch stays responsive
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            ensure_not_engaged()
            time.sleep(min(0.2, max(0.0, end - time.monotonic())))

    def _request(self, path: str) -> str:
        ensure_not_engaged()
        if not self._key:
            raise AdapterError("Massive API key missing; set MARKET_DATA_API_KEY locally")

        headers = {"Authorization": f"Bearer {self._key}"}
        last_status: int | None = None
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            # Pace to the provider rate limit (injected test clients skip the wait).
            while self._client is None:
                waited = time.monotonic() - self._last_request
                if waited >= self._spacing_s:
                    break
                ensure_not_engaged()
                time.sleep(0.1)
            ensure_not_engaged()
            self._last_request = time.monotonic()

            try:
                getter = httpx.get if self._client is None else self._client.get
                response = getter(
                    _BASE_URL + path, headers=headers, timeout=15.0, follow_redirects=False
                )
            except httpx.HTTPError:
                if attempt >= _MAX_ATTEMPTS:
                    raise AdapterError("Massive network request failed") from None
                self._sleep(min(_BACKOFF_CAP_S, _BACKOFF_BASE_S * 2 ** (attempt - 1)))
                continue
            ensure_not_engaged()

            if response.status_code == 200:
                # Never surface a provider body that might echo the credential back.
                return response.text.replace(self._key, "[REDACTED]")

            last_status = response.status_code
            if response.status_code in _RETRY_STATUS and attempt < _MAX_ATTEMPTS:
                retry_after = response.headers.get("retry-after", "")
                delay = (
                    float(retry_after)
                    if retry_after.replace(".", "", 1).isdigit()
                    else min(_BACKOFF_CAP_S, _BACKOFF_BASE_S * 2 ** (attempt - 1))
                )
                self._sleep(delay)
                continue
            break

        raise AdapterError(
            (
                f"Massive HTTP {last_status} after {_MAX_ATTEMPTS} attempts"
                if last_status in _RETRY_STATUS
                else f"Massive HTTP {last_status}"
            ),
            rate_limited=last_status == 429,
        )

    def fetch_daily_bars(self, symbol: str, start: date, end: date) -> Sequence[DailyBar]:
        symbol = symbol.upper().strip()
        if not _SYMBOL_RE.fullmatch(symbol) or end < start:
            raise ValueError("Invalid symbol or date range")
        self._raw.pop((symbol, start, end), None)

        # Never persist an incomplete current-session bar: today's bar is only
        # requested once the session has closed and settled (EOD cutoff, ET);
        # before that, cap at yesterday.
        stop = min(end, completed_session_cutoff())
        if stop < start:
            return ()

        text = self._request(
            f"/v2/aggs/ticker/{symbol}/range/1/day/{start}/{stop}"
            "?adjusted=true&sort=asc&limit=50000"
        )
        try:
            payload = json.loads(text)
            if (
                payload.get("status") not in {"OK", "DELAYED"}
                or payload.get("next_url")
                or payload.get("adjusted") is not True
            ):
                raise ValueError("Incomplete or unadjusted response")
            provenance = Provenance(
                source=self.provider_name,
                latency_category=LatencyCategory.END_OF_DAY,
                retrieved_at=datetime.now(UTC),
                is_simulated=False,
            )
            bars: list[DailyBar] = []
            seen: set[date] = set()
            for row in payload.get("results", []):
                day = datetime.fromtimestamp(row["t"] / 1000, ZoneInfo("America/New_York")).date()
                o, hi, lo, c, v = (float(row[k]) for k in ("o", "h", "l", "c", "v"))
                if (
                    not all(math.isfinite(x) for x in (o, hi, lo, c, v))
                    or min(o, hi, lo, c) <= 0
                    or v < 0
                    or lo > min(o, c)
                    or hi < max(o, c)
                    or day in seen
                    or not start <= day <= stop
                    or row.get("otc")
                ):
                    raise ValueError("Invalid bar")
                seen.add(day)
                bars.append(DailyBar(symbol, day, o, hi, lo, c, v, provenance, adj_close=c))
            if not bars:
                raise ValueError("No bars")
        except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
            raise AdapterError(
                "Massive returned unavailable, incomplete, or invalid daily data"
            ) from None
        self._raw[(symbol, start, end)] = text
        return sorted(bars, key=lambda bar: bar.session_date)

    def fetch_intraday_bars(
        self, symbol: str, start: datetime, end: datetime, *, bar_size: str = "15m"
    ) -> Sequence[IntradayBar]:
        """One aggregates request for ``[start, end]`` at ``bar_size``.

        Implements :class:`~signalforge.data.adapters.base.IntradayBarAdapter`.
        Deliberately NOT paginated: like the daily path, a response carrying
        ``next_url`` is rejected outright rather than silently truncated —
        chunking a long span into requests that each fit under the provider's
        50,000-row page cap is the caller's job
        (``data.ingest.intraday_request_plan``), so the number of provider
        calls a backfill costs is decided and reported up front instead of
        discovered mid-run.

        Every bar is classified against the exchange calendar
        (``calendar.session_of``) and bars outside a real session are dropped:
        a 'closed' stamp is not a tradeable bar. ``session`` is stored, so an
        extended-hours bar is labelled ``pre``/``post`` rather than passed off
        as regular hours."""
        from signalforge.data.calendar import session_of

        symbol = symbol.upper().strip()
        if not _SYMBOL_RE.fullmatch(symbol):
            raise ValueError("Invalid symbol")
        if start.tzinfo is None or end.tzinfo is None:
            raise ValueError("intraday start/end must be timezone-aware")
        if end < start:
            raise ValueError("end must be >= start")
        multiplier, unit = _intraday_span(bar_size)

        text = self._request(
            f"/v2/aggs/ticker/{symbol}/range/{multiplier}/{unit}"
            f"/{start.date()}/{end.date()}?adjusted=true&sort=asc&limit=50000"
        )
        try:
            payload = json.loads(text)
            if (
                payload.get("status") not in {"OK", "DELAYED"}
                or payload.get("next_url")
                or payload.get("adjusted") is not True
            ):
                raise ValueError("Incomplete or unadjusted response")
            provenance = Provenance(
                source=self.provider_name,
                latency_category=LatencyCategory.DELAYED,
                retrieved_at=datetime.now(UTC),
                is_simulated=False,
            )
            bars: list[IntradayBar] = []
            seen: set[datetime] = set()
            for row in payload.get("results", []):
                stamp = datetime.fromtimestamp(row["t"] / 1000, UTC)
                o, hi, lo, c, v = (float(row[k]) for k in ("o", "h", "l", "c", "v"))
                if (
                    not all(math.isfinite(x) for x in (o, hi, lo, c, v))
                    or min(o, hi, lo, c) <= 0
                    or v < 0
                    or lo > min(o, c)
                    or hi < max(o, c)
                    or stamp in seen
                    or not start <= stamp <= end
                    or row.get("otc")
                ):
                    raise ValueError("Invalid bar")
                seen.add(stamp)
                sess = session_of(stamp)
                if sess == "closed":
                    continue  # not a tradeable session bar; never stored
                bars.append(
                    IntradayBar(
                        symbol=symbol,
                        bar_start=stamp,
                        bar_size=bar_size,
                        session=sess,
                        open=o,
                        high=hi,
                        low=lo,
                        close=c,
                        volume=v,
                        provenance=provenance,
                    )
                )
            if not bars:
                raise ValueError("No bars")
        except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
            raise AdapterError(
                "Massive returned unavailable, incomplete, or invalid intraday data"
            ) from None
        return sorted(bars, key=lambda bar: bar.bar_start)

    def raw_payload(self, symbol: str, start: date, end: date) -> str:
        return self._raw.get((symbol.upper().strip(), start, end), "")

    def fetch_corporate_actions(
        self, symbol: str, start: date, end: date
    ) -> Sequence[CorporateActionRecord]:
        return ()  # not offered by this feed

    def fetch_earnings(self, symbol: str, start: date, end: date) -> Sequence[EarningsRecord]:
        return ()  # not offered by this feed
