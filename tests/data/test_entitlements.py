"""Offline contract tests for the per-endpoint entitlement verifier.

No network. A MockTransport stands in for api.massive.com and returns a realistic
mix of 200 / 403 responses. Asserts: the report groups by subscription, maps HTTP
status to (available, error_category, latency), the Benzinga-news check is
*content + freshness* based (a lapsed feed still carrying old Benzinga items is
NOT "available"), endpoints are path templates only, and the API key never leaks
into any returned string.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest

from signalforge.data import entitlements as ent
from signalforge.data.entitlements import _classify, _scrub, verify_entitlements

_SECRET = "sk-live-DEADBEEF-must-never-appear"  # pragma: allowlist secret
_REAL_HTTPX_CLIENT = httpx.Client  # captured before any monkeypatch replaces it


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


def _generic_news_page() -> dict[str, object]:
    """~40 current Motley-Fool items on the unified /v2/reference/news feed.
    No Benzinga content mixed in here — Benzinga has its own dedicated
    endpoint (/benzinga/v2/news), probed separately below."""
    now = datetime.now(UTC)
    results: list[dict[str, object]] = []
    for i in range(40):
        results.append(
            {
                "id": f"mf-{i}",
                "publisher": {"name": "The Motley Fool"},
                "title": f"Fool piece {i}",
                "article_url": "https://www.fool.com/x",
                "published_utc": (now - timedelta(hours=i)).isoformat().replace("+00:00", "Z"),
                "tickers": ["AAPL"],
            }
        )
    return {"status": "OK", "count": len(results), "results": results}


def _benzinga_v2_page(benzinga_age_days: float | None) -> dict[str, object]:
    """The dedicated GET /benzinga/v2/news response shape. ``None`` means the
    add-on currently returns no content at all (e.g. not entitled) — an empty
    results page, distinct from "entitled but stale"."""
    if benzinga_age_days is None:
        return {"status": "OK", "request_id": "r1", "results": [], "next_url": None}
    now = datetime.now(UTC)
    results: list[dict[str, object]] = []
    for i in range(6):
        pub = (now - timedelta(days=benzinga_age_days, hours=i)).isoformat().replace("+00:00", "Z")
        results.append(
            {
                "benzinga_id": 1000 + i,
                "author": "test author",
                "published": pub,
                "last_updated": pub,
                "title": f"Benzinga piece {i}",
                "teaser": "teaser text",
                "body": "<p>body</p>",
                "url": "https://www.benzinga.com/x",
                "images": ["https://cdn.benzinga.com/img.jpg"],
                "channels": ["markets"],
                "tickers": ["AAPL"],
                "tags": ["markets"],
            }
        )
    return {"status": "OK", "request_id": "r1", "results": results, "next_url": None}


def _make_handler(benzinga_age_days: float | None):
    def handler(request: httpx.Request) -> httpx.Response:
        # the key must only ever be in the Authorization header
        assert request.headers["authorization"] == f"Bearer {_SECRET}"
        assert _SECRET not in str(request.url)
        url = str(request.url)
        if "/benzinga/v2/news" in url:
            return httpx.Response(200, json=_benzinga_v2_page(benzinga_age_days))
        if "/v2/reference/news" in url:
            return httpx.Response(200, json=_generic_news_page())
        if "/benzinga/v1/" in url:  # ratings, analyst-insights — separate entitlement
            return httpx.Response(
                403, json={"message": f"You are not entitled to this data (key {_SECRET})"}
            )
        if "/v3/quotes/" in url:  # NBBO not entitled for stocks or options
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

    return handler


def _mock(monkeypatch: pytest.MonkeyPatch, *, benzinga_age_days: float | None) -> None:
    handler = _make_handler(benzinga_age_days)

    def factory(**kw: object) -> httpx.Client:
        return _REAL_HTTPX_CLIENT(transport=httpx.MockTransport(handler))

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


def test_verify_entitlements_groups_and_classifies(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock(monkeypatch, benzinga_age_days=None)
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

    # licensed news feed reachable; Benzinga structured sub-products not entitled
    assert report.available("news_licensed_feed")
    assert not report.available("benzinga_ratings")
    assert not report.available("benzinga_analyst_insights")


def test_benzinga_news_available_only_when_feed_is_currently_delivering_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # fresh Benzinga items on the dedicated /benzinga/v2/news endpoint -> available, DELAYED
    _mock(monkeypatch, benzinga_age_days=1)
    report = verify_entitlements(_settings(monkeypatch))
    bz = next(c for c in report.checks if c.feed == "benzinga_news")
    assert bz.available is True
    assert bz.latency_category == "DELAYED"
    assert bz.endpoint == "/benzinga/v2/news"
    assert "live via /benzinga/v2/news" in bz.detail

    # Benzinga items present but 81 days stale -> NOT available
    _mock(monkeypatch, benzinga_age_days=81)
    report = verify_entitlements(_settings(monkeypatch))
    bz = next(c for c in report.checks if c.feed == "benzinga_news")
    assert bz.available is False
    assert bz.error_category == "empty"
    assert "STALE" in bz.detail
    assert "not currently delivering current content" in bz.detail

    # no Benzinga items at all -> NOT available, distinct "empty sample" message
    _mock(monkeypatch, benzinga_age_days=None)
    report = verify_entitlements(_settings(monkeypatch))
    bz = next(c for c in report.checks if c.feed == "benzinga_news")
    assert bz.available is False
    assert "returned no articles for the sample" in bz.detail


def test_benzinga_freshness_gate_is_not_fooled_by_days_truncation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """review finding: benzinga-freshness #10 — timedelta.days truncates, so an
    article 10 days 22 hours old must NOT pass a "<=10 day" freshness gate even
    though (now - article).days == 10."""
    _mock(monkeypatch, benzinga_age_days=10 + 22 / 24)  # ~10d22h old
    report = verify_entitlements(_settings(monkeypatch))
    bz = next(c for c in report.checks if c.feed == "benzinga_news")
    assert bz.available is False
    assert "STALE" in bz.detail

    # just inside the window (a few hours old) must still pass
    _mock(monkeypatch, benzinga_age_days=9.5)
    report = verify_entitlements(_settings(monkeypatch))
    bz = next(c for c in report.checks if c.feed == "benzinga_news")
    assert bz.available is True


def test_verify_entitlements_never_leaks_the_key(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock(monkeypatch, benzinga_age_days=1)
    report = verify_entitlements(_settings(monkeypatch))
    blob = repr(report.to_rows())
    assert _SECRET not in blob
    # the 403 body embedded the key; it must come back redacted
    ratings = next(c for c in report.checks if c.feed == "benzinga_ratings")
    assert _SECRET not in ratings.detail
    assert "[REDACTED]" in ratings.detail

    # endpoints are path templates only — no query string, no host with a secret
    for c in report.checks:
        assert "?" not in c.endpoint or "{" in c.endpoint or "publisher=" in c.endpoint
        assert _SECRET not in c.endpoint


def test_discord_is_presence_checked_not_contacted(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock(monkeypatch, benzinga_age_days=None)
    _settings(monkeypatch)
    monkeypatch.setenv(
        "DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/123456/abcdef-token_XYZ"
    )
    from signalforge.config import get_settings

    get_settings.cache_clear()
    report = verify_entitlements(get_settings())
    assert report.discord_configured is True
    assert "not contacted" in report.discord_note
