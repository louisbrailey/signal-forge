"""Offline contract tests for the per-endpoint entitlement verifier.

No network. A MockTransport stands in for api.massive.com and returns a realistic
mix of 200 / 403 / 404 responses. Asserts: the report groups by subscription,
maps HTTP status to (available, error_category, latency), records only path-level
endpoints, and never leaks the API key into any returned string.
"""

from __future__ import annotations

import httpx
import pytest

from signalforge.data import entitlements as ent
from signalforge.data.entitlements import _classify, _scrub, verify_entitlements

_SECRET = "sk-live-DEADBEEF-must-never-appear"


def test_classify_maps_status_codes() -> None:
    assert _classify(200, {"status": "OK", "results": [{"x": 1}]}) == (True, "none")
    assert _classify(200, {"status": "DELAYED", "results": [{"x": 1}]}) == (True, "none")
    assert _classify(403, {"message": "not entitled"}) == (False, "not_authorized")
    assert _classify(401, {}) == (False, "not_authorized")
    assert _classify(404, None) == (False, "not_found")
    assert _classify(429, {}) == (False, "rate_limited")
    assert _classify(None, None) == (False, "network")
    assert _classify(200, {"status": "OK", "results": []}) == (False, "empty")


def test_scrub_removes_key_and_querystring_secrets() -> None:
    dirty = f"GET https://api.massive.com/x?apiKey={_SECRET} -> Bearer {_SECRET}"
    clean = _scrub(dirty, _SECRET)
    assert _SECRET not in clean
    assert "[REDACTED]" in clean


def _handler(request: httpx.Request) -> httpx.Response:
    # the key must only ever be in the Authorization header
    assert request.headers["authorization"] == f"Bearer {_SECRET}"
    assert _SECRET not in str(request.url)
    url = str(request.url)
    if "/benzinga/v1/news" in url:
        return httpx.Response(404, json={"status": "NOT_FOUND"})
    if "/benzinga/v1/" in url:  # ratings, analyst-insights
        return httpx.Response(
            403, json={"message": f"You are not entitled to this data (key {_SECRET})"}
        )
    if "/v3/quotes/" in url:  # NBBO not entitled for stocks and options
        return httpx.Response(403, json={"message": "You are not entitled to this data."})
    if "/v3/snapshot/options/" in url:
        return httpx.Response(
            200,
            json={
                "status": "OK",
                "results": [
                    {
                        "details": {"ticker": "O:SPY_C1", "strike_price": 500},
                        "underlying_asset": {"price": 500.0},
                        "greeks": {"delta": 0.5},
                        "implied_volatility": 0.2,
                        "open_interest": 1234,
                        "break_even_price": 505.0,
                    }
                ],
            },
        )
    if "/v3/reference/options/contracts" in url:
        return httpx.Response(
            200,
            json={
                "status": "OK",
                "results": [{"ticker": "O:SPY_C1", "expiration_date": "2099-01-15"}],
            },
        )
    if "/v2/last/trade/" in url:
        return httpx.Response(200, json={"status": "OK", "results": {"p": 500.0}})
    # default: aggregate / trade endpoints -> entitled
    return httpx.Response(200, json={"status": "OK", "results": [{"c": 1.0, "t": 1}]})


@pytest.fixture
def _mock_client(monkeypatch: pytest.MonkeyPatch) -> None:
    real = httpx.Client

    def factory(**kw: object) -> httpx.Client:
        return real(transport=httpx.MockTransport(_handler))

    monkeypatch.setattr(ent.httpx, "Client", factory)


def _settings(monkeypatch: pytest.MonkeyPatch) -> object:
    monkeypatch.setenv("MARKET_DATA_PROVIDER", "massive")
    monkeypatch.setenv("MARKET_DATA_API_KEY", _SECRET)
    monkeypatch.setenv("OPTIONS_API_KEY", "")
    monkeypatch.setenv("NEWS_API_KEY", "")
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "")
    from signalforge.config import get_settings

    get_settings.cache_clear()
    return get_settings()


def test_verify_entitlements_groups_and_classifies(
    _mock_client: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    report = verify_entitlements(_settings(monkeypatch))

    subs = {c.subscription for c in report.checks}
    assert subs == {"stocks_developer", "options_developer", "benzinga_news"}

    # stocks: bars + history entitled, NBBO not
    assert report.available("stocks_daily_bars")
    assert report.available("stocks_history_10y")
    assert not report.available("stocks_nbbo_quotes")
    nbbo = next(c for c in report.checks if c.feed == "stocks_nbbo_quotes")
    assert nbbo.http_status == 403 and nbbo.error_category == "not_authorized"
    assert nbbo.latency_category == "none"

    # options: chain/greeks/iv/oi entitled, bid/ask quotes not
    assert report.available("options_chain_snapshot")
    assert report.available("options_greeks")
    assert report.available("options_implied_vol")
    assert report.available("options_open_interest")
    assert not report.available("options_quotes_bidask")
    oi = next(c for c in report.checks if c.feed == "options_open_interest")
    assert oi.latency_category == "END_OF_DAY"

    # benzinga: dedicated endpoint 404, ratings/insights 403, generic feed OK
    dedicated = next(c for c in report.checks if c.feed == "benzinga_news_dedicated")
    assert dedicated.http_status == 404 and dedicated.error_category == "not_found"
    assert not report.available("benzinga_news_dedicated")
    assert report.available("news_generic_multipublisher")


def test_verify_entitlements_never_leaks_the_key(
    _mock_client: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    report = verify_entitlements(_settings(monkeypatch))
    blob = repr(report.to_rows())
    assert _SECRET not in blob
    # the 403 body embedded the key; it must come back redacted
    ratings = next(c for c in report.checks if c.feed == "benzinga_ratings")
    assert _SECRET not in ratings.detail
    assert "[REDACTED]" in ratings.detail

    # endpoints are path templates only — no query string, no host with a secret
    for c in report.checks:
        assert "?" not in c.endpoint or "{" in c.endpoint
        assert _SECRET not in c.endpoint


def test_discord_is_presence_checked_not_contacted(
    _mock_client: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    _settings(monkeypatch)
    monkeypatch.setenv(
        "DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/123456/abcdef-token_XYZ"
    )
    from signalforge.config import get_settings

    get_settings.cache_clear()
    report = verify_entitlements(get_settings())
    assert report.discord_configured is True
    assert "not contacted" in report.discord_note
