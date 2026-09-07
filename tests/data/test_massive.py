"""Offline provider contract tests; no paid credentials required."""

from datetime import date

import httpx
import pytest

from signalforge.data.adapters.base import AdapterError, LatencyCategory
from signalforge.data.adapters.massive import MassiveAdapter
from signalforge.killswitch import KillSwitchEngaged, get_kill_switch

START = date(2024, 1, 2)
PAYLOAD = {
    "status": "OK",
    "adjusted": True,
    "results": [{"t": 1704171600000, "o": 100, "h": 102, "l": 99, "c": 101, "v": 5000}],
}


def adapter(payload=PAYLOAD, status=200):
    def handler(request):
        assert request.url.host == "api.massive.com"
        assert "apiKey" not in request.url.params
        return httpx.Response(status, json=payload)

    transport = httpx.MockTransport(handler)
    return MassiveAdapter("test-placeholder", client=httpx.Client(transport=transport))


def test_completed_bars_and_cached_raw():
    a = adapter()
    bars = a.fetch_daily_bars("SPY", START, START)
    assert bars[0].close == 101
    assert bars[0].provenance.latency_category == LatencyCategory.END_OF_DAY
    assert a.raw_payload("SPY", START, START)
    assert len(a.capabilities) == 1


@pytest.mark.parametrize("status", [401, 403, 429, 500])
def test_errors(status):
    with pytest.raises(AdapterError) as exc:
        adapter(status=status).fetch_daily_bars("SPY", START, START)
    assert exc.value.rate_limited == (status == 429)
    assert "test-placeholder" not in str(exc.value)


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {**PAYLOAD, "next_url": "https://example.com"},
        {**PAYLOAD, "adjusted": False},
        {**PAYLOAD, "results": []},
    ],
)
def test_incomplete_data_rejected(payload):
    with pytest.raises(AdapterError):
        adapter(payload).fetch_daily_bars("SPY", START, START)


def test_no_key_and_kill_switch():
    with pytest.raises(AdapterError, match="key missing"):
        MassiveAdapter("").fetch_daily_bars("SPY", START, START)
    get_kill_switch().engage("test")
    with pytest.raises(KillSwitchEngaged):
        adapter().fetch_daily_bars("SPY", START, START)
