"""Stooq free end-of-day CSV adapter.

Stooq publishes a plain CSV daily-history endpoint for personal use. It is a
documented data URL (not an HTML scrape). There is **no API key**, and the data is
**end of day** — so ``latency_category = END_OF_DAY`` and live alerts stay
disabled for horizons that need intraday freshness.

Caveats surfaced in the UI: no corporate-action feed (the Close series is
split-adjusted but not dividend-adjusted), and free history carries survivorship
bias.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime

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

PROVIDER_NAME = "stooq"
_BASE = "https://stooq.com/q/d/l/"


def build_url(symbol: str, start: date, end: date) -> str:
    sym = symbol.strip().lower()
    if not sym.endswith(".us"):
        sym = f"{sym}.us"
    return (
        f"{_BASE}?s={sym}"
        f"&d1={start.strftime('%Y%m%d')}&d2={end.strftime('%Y%m%d')}&i=d"
    )


def parse_stooq_csv(text: str, symbol: str, provenance: Provenance) -> list[DailyBar]:
    text = text.strip()
    if not text or text.lower().startswith("<!doctype") or "no data" in text.lower():
        raise AdapterError(f"stooq returned no data for {symbol!r}")
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None or "Close" not in reader.fieldnames:
        raise AdapterError(f"unexpected stooq payload for {symbol!r}: {text[:120]!r}")

    bars: list[DailyBar] = []
    for row in reader:
        try:
            bars.append(
                DailyBar(
                    symbol=symbol.upper(),
                    session_date=date.fromisoformat(row["Date"]),
                    open=float(row["Open"]),
                    high=float(row["High"]),
                    low=float(row["Low"]),
                    close=float(row["Close"]),
                    volume=float(row.get("Volume") or 0.0),
                    adj_close=float(row["Close"]),  # stooq Close is split-adjusted
                    provenance=provenance,
                )
            )
        except (KeyError, ValueError) as exc:
            raise AdapterError(f"malformed stooq row for {symbol!r}: {row!r}") from exc
    return bars


class StooqAdapter:
    """Implements :class:`~signalforge.data.adapters.base.MarketDataAdapter`."""

    provider_name = PROVIDER_NAME

    def __init__(
        self,
        http_get: Callable[[str], str] | None = None,
        *,
        timeout: float = 15.0,
    ) -> None:
        self._http_get = http_get or self._default_get
        self._timeout = timeout

    def _default_get(self, url: str) -> str:  # pragma: no cover - exercised only online
        import httpx

        try:
            resp = httpx.get(url, timeout=self._timeout, follow_redirects=True)
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            rate_limited = exc.response.status_code == 429
            raise AdapterError(f"stooq HTTP {exc.response.status_code}", rate_limited=rate_limited)
        except httpx.HTTPError as exc:
            raise AdapterError(f"stooq request failed: {exc}") from exc
        return resp.text

    @property
    def capabilities(self) -> Sequence[AdapterCapability]:
        return (
            AdapterCapability(
                provider_name=PROVIDER_NAME,
                feed_type=FeedType.BAR_DAILY,
                latency_category=LatencyCategory.END_OF_DAY,
                supports_point_in_time=False,
                entitlement_note="Stooq free EOD CSV (personal use). Split-adjusted close; "
                "no dividend adjustment; survivorship bias in free history.",
                rate_limit_per_min=20,
                is_simulated=False,
            ),
        )

    def _provenance(self) -> Provenance:
        return Provenance(
            source=PROVIDER_NAME,
            latency_category=LatencyCategory.END_OF_DAY,
            retrieved_at=datetime.now(UTC),
            is_simulated=False,
        )

    def fetch_daily_bars(self, symbol: str, start: date, end: date) -> Sequence[DailyBar]:
        if end < start:
            raise ValueError("end must be >= start")
        text = self._http_get(build_url(symbol, start, end))
        bars = parse_stooq_csv(text, symbol, self._provenance())
        return [b for b in bars if start <= b.session_date <= end]

    def fetch_corporate_actions(
        self, symbol: str, start: date, end: date
    ) -> Sequence[CorporateActionRecord]:
        return ()  # not offered by this feed

    def fetch_earnings(
        self, symbol: str, start: date, end: date
    ) -> Sequence[EarningsRecord]:
        return ()  # not offered by this feed

    def raw_payload(self, symbol: str, start: date, end: date) -> str:
        return self._http_get(build_url(symbol, start, end))
