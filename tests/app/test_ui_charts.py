"""New UI: chart APIs, status strip, Markets and Crypto paper pages."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from signalforge.db.models import CryptoBarDaily, FxBarDaily
from signalforge.db.session import session_scope
from signalforge.domain import LatencyCategory

CHART_URLS = (
    "/api/charts/equity/SPY",
    "/api/charts/fx/EURUSD",
    "/api/charts/crypto/BTCUSD",
    "/api/charts/paper/equity",
    "/api/charts/paper/crypto/crypto_donchian_55",
    "/api/charts/snapshot/fx",
)


def test_chart_apis_require_a_signed_in_user(client: TestClient) -> None:
    for url in CHART_URLS:
        assert client.get(url).status_code == 401, url
    assert client.get("/ui/status-strip").status_code == 401


def test_chart_payloads_carry_honest_freshness_labels(registered_client: TestClient) -> None:
    for url in CHART_URLS[:5]:
        r = registered_client.get(url)
        assert r.status_code == 200, url
        p = r.json()
        assert p["latency"] == "END_OF_DAY"  # never labelled live
        assert {"as_of", "stale", "series", "generated_at", "empty"} <= set(p)


def test_fx_and_crypto_charts_return_stored_bars(registered_client: TestClient) -> None:
    now = datetime.now(UTC)
    today = now.date()
    with session_scope(write=True) as s:
        for i in range(5):
            d = today - timedelta(days=5 - i)
            kw = {
                "session_date": d,
                "open": 1.0,
                "high": 1.1,
                "low": 0.9,
                "close": 1.0 + i / 100,
                "latency_category": LatencyCategory.END_OF_DAY,
                "ingested_at": now,
                "quality_flags": [],
            }
            if d.weekday() < 5:
                s.add(FxBarDaily(pair="EURUSD", source="massive_fx", **kw))  # type: ignore[arg-type]
            s.add(CryptoBarDaily(pair="BTCUSD", source="massive_crypto", **kw))  # type: ignore[arg-type]
    fx = registered_client.get("/api/charts/fx/eurusd?days=30").json()
    cr = registered_client.get("/api/charts/crypto/BTC-USD?days=30").json()
    assert fx["series"][0]["data"] and fx["stale"] is False
    assert len(cr["series"][0]["data"]) == 5
    assert cr["as_of"] == (today - timedelta(days=1)).isoformat()
    snap = registered_client.get("/api/charts/snapshot/crypto").json()["rows"]
    btc = next(r for r in snap if r["pair"] == "BTCUSD")
    assert btc["close"] == 1.04 and len(btc["spark"]) == 5
    assert registered_client.get("/api/charts/fx/EURUSD?days=1").status_code == 422


def test_unknown_symbol_is_an_empty_chart_not_an_error(registered_client: TestClient) -> None:
    p = registered_client.get("/api/charts/equity/NOPE").json()
    assert p["empty"] is True and "not in the local store" in p["note"]


def test_status_strip_reports_kill_switch_and_feeds(registered_client: TestClient) -> None:
    from signalforge.killswitch import get_kill_switch

    r = registered_client.get("/ui/status-strip")
    assert r.status_code == 200 and "Running" in r.text
    get_kill_switch().engage(reason="test", actor="test")
    try:
        assert "Kill switch </span>ON" in registered_client.get("/ui/status-strip").text
    finally:
        get_kill_switch().release(reason="test", actor="test")


def test_new_pages_render_with_navigation_and_notices(registered_client: TestClient) -> None:
    for path, needle in (("/markets", "Charts"), ("/crypto-paper", "Crypto paper book")):
        r = registered_client.get(path)
        assert r.status_code == 200, path
        assert needle in r.text
        assert "not financial advice" in r.text.lower()
        assert "Research signal only" in r.text
        for href in ('href="/markets"', 'href="/crypto-paper"', 'href="/grid"', 'href="/ops"'):
            assert href in r.text
    assert "No crypto paper book yet" in registered_client.get("/crypto-paper").text


def test_overview_has_live_charts(registered_client: TestClient) -> None:
    t = registered_client.get("/").text
    assert 'data-chart="/api/charts/paper/equity"' in t
    assert 'data-snapshot="fx"' in t and "/static/sf-charts.js" in t


def test_chart_script_is_served(client: TestClient) -> None:
    r = client.get("/static/sf-charts.js")
    assert r.status_code == 200 and "data-chart" in r.text


def test_pages_redirect_when_signed_out(client: TestClient) -> None:
    for path in ("/markets", "/crypto-paper"):
        r = client.get(path, follow_redirects=False)
        assert r.status_code == 303
