"""S4 — signals/config are deterministic and order-independent."""

from __future__ import annotations

from datetime import date

import pytest

from signalforge.config import config_hash
from signalforge.config.research import ResearchConfig
from signalforge.data.adapters.fixture import FixtureMarketDataAdapter

pytestmark = pytest.mark.safety


def test_config_hash_is_key_order_independent() -> None:
    a = {"universe": ["SPY", "QQQ"], "risk": {"per_trade": 0.5, "max_expo": 60}}
    b = {"risk": {"max_expo": 60, "per_trade": 0.5}, "universe": ["SPY", "QQQ"]}
    assert config_hash(a) == config_hash(b)


def test_config_hash_changes_when_a_value_changes() -> None:
    base = ResearchConfig()
    changed = base.model_copy(update={"commission_per_share": 0.01})
    assert base.config_hash != changed.config_hash


def test_default_research_config_hash_is_stable() -> None:
    assert ResearchConfig().config_hash == ResearchConfig().config_hash


def test_fixture_adapter_is_deterministic() -> None:
    adapter = FixtureMarketDataAdapter()
    span = (date(2024, 1, 1), date(2024, 3, 1))
    first = adapter.fetch_daily_bars("AAPL", *span)
    second = adapter.fetch_daily_bars("AAPL", *span)
    assert [(b.session_date, b.open, b.high, b.low, b.close, b.volume) for b in first] == [
        (b.session_date, b.open, b.high, b.low, b.close, b.volume) for b in second
    ]
    assert first[0].close != adapter.fetch_daily_bars("MSFT", *span)[0].close
