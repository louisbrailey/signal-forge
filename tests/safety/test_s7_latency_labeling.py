"""S7 — "live" requires a real-time entitlement; simulated/delayed data cannot be live."""

from __future__ import annotations

import pytest

from signalforge.data.adapters.base import (
    AdapterCapability,
    FeedType,
    LatencyCategory,
)
from signalforge.data.adapters.fixture import FixtureMarketDataAdapter

pytestmark = pytest.mark.safety


def test_only_realtime_is_live() -> None:
    assert LatencyCategory.REALTIME.is_live is True
    assert LatencyCategory.DELAYED.is_live is False
    assert LatencyCategory.END_OF_DAY.is_live is False
    assert LatencyCategory.HISTORICAL.is_live is False


def test_simulated_capability_cannot_be_realtime() -> None:
    with pytest.raises(ValueError, match="REALTIME"):
        AdapterCapability(
            provider_name="fixture",
            feed_type=FeedType.BAR_DAILY,
            latency_category=LatencyCategory.REALTIME,
            supports_point_in_time=True,
            entitlement_note="",
            is_simulated=True,
        )


def test_fixture_adapter_is_historical_and_simulated() -> None:
    for cap in FixtureMarketDataAdapter().capabilities:
        assert cap.latency_category is LatencyCategory.HISTORICAL
        assert cap.is_simulated is True
        assert cap.latency_category.is_live is False


def test_fixture_bars_carry_simulated_provenance() -> None:
    from datetime import date

    bars = FixtureMarketDataAdapter().fetch_daily_bars("SPY", date(2024, 1, 2), date(2024, 1, 10))
    assert bars
    assert all(b.provenance.is_simulated for b in bars)
    assert all(b.provenance.latency_category.is_live is False for b in bars)
