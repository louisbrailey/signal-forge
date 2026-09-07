"""Resolve the configured market-data adapters from ``Settings``."""

from __future__ import annotations

from signalforge.config import Settings, get_settings
from signalforge.data.adapters.base import MarketDataAdapter
from signalforge.data.adapters.fixture import FixtureMarketDataAdapter
from signalforge.data.adapters.massive import MassiveAdapter
from signalforge.data.adapters.stooq import StooqAdapter

_BUILDERS = {
    "": FixtureMarketDataAdapter,
    "fixture": FixtureMarketDataAdapter,
    "stooq": StooqAdapter,
    "massive": MassiveAdapter,
}


def available_providers() -> list[str]:
    return sorted(p for p in _BUILDERS if p)


def build_adapter(name: str) -> MarketDataAdapter:
    key = name.strip().lower()
    try:
        return _BUILDERS[key]()
    except KeyError:
        raise ValueError(
            f"Unknown MARKET_DATA_PROVIDER {name!r}. Known: {available_providers()}"
        ) from None


def get_primary_adapter(settings: Settings | None = None) -> MarketDataAdapter:
    settings = settings or get_settings()
    return build_adapter(settings.market_data_provider)


def get_secondary_adapter(settings: Settings | None = None) -> MarketDataAdapter | None:
    settings = settings or get_settings()
    name = settings.market_data_provider_secondary.strip()
    if not name or name == settings.market_data_provider:
        return None
    return build_adapter(name)
