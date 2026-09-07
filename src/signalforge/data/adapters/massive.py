"""Massive completed daily bars — always treated as END-OF-DAY.

Read-only REST adapter. It fetches *completed* split-adjusted daily bars and
nothing else: no quotes, no streaming, no earnings, no separate corporate-action
feed. ``latency_category`` is hard-wired to ``END_OF_DAY`` regardless of the
account's plan, so live alerts stay disabled for horizons that need intraday
freshness until a separate, explicitly licensed streaming integration proves a
real-time entitlement.

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
    LatencyCategory,
    Provenance,
)
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

        # Never persist an incomplete current-session bar: cap at yesterday (ET).
        cutoff = datetime.now(ZoneInfo("America/New_York")).date() - timedelta(days=1)
        stop = min(end, cutoff)
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

    def raw_payload(self, symbol: str, start: date, end: date) -> str:
        return self._raw.get((symbol.upper().strip(), start, end), "")

    def fetch_corporate_actions(
        self, symbol: str, start: date, end: date
    ) -> Sequence[CorporateActionRecord]:
        return ()  # not offered by this feed

    def fetch_earnings(self, symbol: str, start: date, end: date) -> Sequence[EarningsRecord]:
        return ()  # not offered by this feed
