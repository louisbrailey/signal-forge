"""Adapter interfaces + capability descriptors (ARCHITECTURE.md §8.1)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Protocol, runtime_checkable

from signalforge.domain import FeedType, LatencyCategory

__all__ = [
    "FeedType",
    "LatencyCategory",
    "AdapterCapability",
    "Provenance",
    "DailyBar",
    "IntradayBar",
    "IntradayBarAdapter",
    "CorporateActionRecord",
    "EarningsRecord",
    "FetchResult",
    "AdapterError",
    "MarketDataAdapter",
]


class AdapterError(RuntimeError):
    """Raised by an adapter when a fetch fails (network, auth, rate limit, parse)."""

    def __init__(self, message: str, *, rate_limited: bool = False) -> None:
        super().__init__(message)
        self.rate_limited = rate_limited


@dataclass(frozen=True, slots=True)
class AdapterCapability:
    provider_name: str
    feed_type: FeedType
    latency_category: LatencyCategory
    supports_point_in_time: bool
    entitlement_note: str
    delay_estimate: str = ""              # e.g. "15 min" when DELAYED
    rate_limit_per_min: int | None = None
    is_simulated: bool = False            # fixture/demo data — always shown as SIMULATED

    def __post_init__(self) -> None:
        if self.latency_category is LatencyCategory.REALTIME and self.is_simulated:
            raise ValueError("Simulated data can never be REALTIME (invariant S7).")


@dataclass(frozen=True, slots=True)
class Provenance:
    """Attached to every stored datum for audit + UI labelling."""

    source: str
    latency_category: LatencyCategory
    retrieved_at: datetime
    is_simulated: bool = False


@dataclass(frozen=True, slots=True)
class DailyBar:
    symbol: str
    session_date: date
    open: float
    high: float
    low: float
    close: float
    volume: float
    provenance: Provenance
    adj_close: float | None = None
    split_factor: float = 1.0
    div_cash: float = 0.0


@dataclass(frozen=True, slots=True)
class IntradayBar:
    symbol: str
    bar_start: datetime  # UTC, start of the bar
    bar_size: str        # "5m" | "15m" | "1h" ...
    session: str         # pre | rth | post
    open: float
    high: float
    low: float
    close: float
    volume: float
    provenance: Provenance


@dataclass(frozen=True, slots=True)
class CorporateActionRecord:
    symbol: str
    action_type: str  # split | dividend | symbol_change
    ex_date: date
    ratio: float | None = None
    amount: float | None = None
    detail: str = ""


@dataclass(frozen=True, slots=True)
class EarningsRecord:
    symbol: str
    scheduled_for: date
    time_of_day: str = "unknown"  # bmo | amc | unknown
    confirmed: bool = False


@dataclass(frozen=True, slots=True)
class FetchResult:
    """What an adapter returns from a fetch: the data + the raw payload for audit."""

    bars: tuple[DailyBar, ...] = ()
    corporate_actions: tuple[CorporateActionRecord, ...] = ()
    earnings: tuple[EarningsRecord, ...] = ()
    raw_payloads: tuple[tuple[str, str], ...] = field(default_factory=tuple)  # (endpoint, text)


@runtime_checkable
class MarketDataAdapter(Protocol):
    """Daily-bar + corporate-action + earnings provider contract (Phase 1)."""

    provider_name: str

    @property
    def capabilities(self) -> Sequence[AdapterCapability]: ...

    def fetch_daily_bars(self, symbol: str, start: date, end: date) -> Sequence[DailyBar]: ...

    def fetch_corporate_actions(
        self, symbol: str, start: date, end: date
    ) -> Sequence[CorporateActionRecord]: ...

    def fetch_earnings(self, symbol: str, start: date, end: date) -> Sequence[EarningsRecord]: ...


@runtime_checkable
class IntradayBarAdapter(Protocol):
    """Optional intraday-bar contract (Phase 2). Not every provider offers this."""

    provider_name: str

    @property
    def capabilities(self) -> Sequence[AdapterCapability]: ...

    def fetch_intraday_bars(
        self, symbol: str, start: datetime, end: datetime, *, bar_size: str = "5m"
    ) -> Sequence[IntradayBar]: ...
