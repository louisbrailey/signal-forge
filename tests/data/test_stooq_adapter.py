"""Stooq adapter: URL construction, CSV parsing, and error surfacing — all offline."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from signalforge.data.adapters.base import AdapterError, LatencyCategory, Provenance
from signalforge.data.adapters.stooq import StooqAdapter, build_url, parse_stooq_csv

_CSV = """Date,Open,High,Low,Close,Volume
2024-01-02,185.0,186.2,183.9,185.64,52000000
2024-01-03,184.1,184.5,182.0,182.68,58000000
2024-01-04,182.0,183.1,181.2,181.91,49000000
"""


def _prov() -> Provenance:
    return Provenance("stooq", LatencyCategory.END_OF_DAY, datetime.now(UTC), is_simulated=False)


def test_build_url_adds_us_suffix_and_dates() -> None:
    url = build_url("aapl", date(2024, 1, 1), date(2024, 2, 1))
    assert "s=aapl.us" in url and "d1=20240101" in url and "d2=20240201" in url


def test_parse_returns_bars() -> None:
    bars = parse_stooq_csv(_CSV, "aapl", _prov())
    assert [b.session_date for b in bars] == [date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4)]
    assert bars[0].close == 185.64
    assert bars[0].adj_close == 185.64
    assert bars[0].provenance.latency_category is LatencyCategory.END_OF_DAY
    assert bars[0].provenance.is_simulated is False


def test_parse_rejects_no_data_and_html() -> None:
    with pytest.raises(AdapterError):
        parse_stooq_csv("No data", "aapl", _prov())
    with pytest.raises(AdapterError):
        parse_stooq_csv("<!DOCTYPE html><html>...", "aapl", _prov())


def test_adapter_uses_injected_getter_and_filters_range() -> None:
    adapter = StooqAdapter(http_get=lambda _url: _CSV)
    bars = adapter.fetch_daily_bars("AAPL", date(2024, 1, 3), date(2024, 1, 4))
    assert [b.session_date for b in bars] == [date(2024, 1, 3), date(2024, 1, 4)]


def test_adapter_capability_is_end_of_day_not_live() -> None:
    (cap,) = StooqAdapter().capabilities
    assert cap.latency_category is LatencyCategory.END_OF_DAY
    assert cap.latency_category.is_live is False
    assert cap.is_simulated is False


def test_adapter_wraps_transport_error() -> None:
    def _boom(_url: str) -> str:
        raise AdapterError("network down")

    with pytest.raises(AdapterError, match="network down"):
        StooqAdapter(http_get=_boom).fetch_daily_bars("AAPL", date(2024, 1, 1), date(2024, 1, 2))
