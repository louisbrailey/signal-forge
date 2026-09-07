"""Options-learning and News dashboard pages.

Covers: the /options and /news routes render for a signed-in user; the options
page never claims a live quote (NBBO bid/ask is not entitled on this plan) and
carries the education-only risk warnings; the news page shows the real publisher
and states the Benzinga entitlement limitation instead of pretending the generic
multi-publisher feed is Benzinga.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from fastapi.testclient import TestClient

from signalforge.db.session import session_scope
from signalforge.domain import LatencyCategory


def _seed_news_and_entitlements() -> None:
    from signalforge.db.models import EntitlementCheck, NewsItem

    with session_scope() as s:
        s.add(
            EntitlementCheck(
                batch_id="test-batch",
                subscription="benzinga_news",
                feed="benzinga_news_dedicated",
                endpoint="/benzinga/v1/news",
                source="massive",
                checked_at=datetime(2026, 9, 6, 12, 0, tzinfo=UTC),
                http_status=404,
                available=False,
                latency_category="none",
                error_category="not_found",
                detail="HTTP 404 — dedicated Benzinga news endpoint not provisioned on this key",
            )
        )
        s.add(
            EntitlementCheck(
                batch_id="test-batch",
                subscription="options_developer",
                feed="options_quotes_bidask",
                endpoint="/v3/quotes/{optionsTicker}",
                source="massive",
                checked_at=datetime(2026, 9, 6, 12, 0, tzinfo=UTC),
                http_status=403,
                available=False,
                latency_category="none",
                error_category="not_authorized",
                detail="HTTP 403 — NBBO quotes not entitled",
            )
        )
        s.add(
            NewsItem(
                headline="Chipmaker raises full-year outlook",
                url="https://example.com/a",
                published_at=datetime(2026, 9, 5, 13, 30, tzinfo=UTC),
                retrieved_at=datetime(2026, 9, 5, 13, 46, tzinfo=UTC),
                source="Reuters",
                provider="massive_news_generic",
                provider_id="rt-1",
                dedupe_key="dk-reuters-1",
                category="markets",
                instrument_symbols=["NVDA"],
            )
        )
        s.add(
            NewsItem(
                headline="Index futures flat ahead of jobs report",
                url="https://example.com/b",
                published_at=datetime(2026, 9, 4, 9, 0, tzinfo=UTC),
                retrieved_at=datetime(2026, 9, 4, 9, 12, tzinfo=UTC),
                source="MarketWatch",
                provider="massive_news_generic",
                provider_id="mw-9",
                dedupe_key="dk-mw-9",
                category="economy",
                instrument_symbols=["SPY"],
            )
        )


def _seed_option_chain() -> None:
    from signalforge.db.models import OptionContract, OptionQuoteSnapshot

    as_of = datetime(2026, 9, 4, 20, 15, tzinfo=UTC)
    with session_scope() as s:
        s.add(
            OptionContract(
                option_ticker="O:SPY261016C00500000",
                underlying_symbol="SPY",
                contract_type="call",
                strike_price=500.0,
                expiration_date=date(2026, 10, 16),
                source="massive_options",
                ingested_at=as_of,
            )
        )
        s.add(
            OptionQuoteSnapshot(
                option_ticker="O:SPY261016C00500000",
                underlying_symbol="SPY",
                as_of=as_of,
                source="massive_options",
                latency_category=LatencyCategory.DELAYED,
                underlying_price=498.2,
                day_close=12.35,
                day_volume=4210,
                last_trade_price=12.4,
                last_trade_at=datetime(2026, 9, 4, 20, 0, tzinfo=UTC),
                open_interest=88123,
                break_even_price=512.4,
                vendor_iv=0.184,
                vendor_greeks_json={"delta": 0.47, "theta": -0.08, "vega": 0.55},
            )
        )


# ---------------------------------------------------------------------------
def test_news_page_states_benzinga_is_unavailable(registered_client: TestClient) -> None:
    _seed_news_and_entitlements()
    r = registered_client.get("/news")
    assert r.status_code == 200
    assert "no dedicated Benzinga entitlement" in r.text
    assert "not provisioned on this key" in r.text
    # real publishers shown, not relabelled as Benzinga
    assert "Reuters" in r.text and "MarketWatch" in r.text
    assert "Chipmaker raises full-year outlook" in r.text
    assert "not financial advice" in r.text.lower()


def test_news_context_reports_limitation_and_source_label(db_url: str) -> None:
    from signalforge.app.views import news_context

    _seed_news_and_entitlements()
    with session_scope() as s:
        ctx = news_context(s)
    assert ctx["benzinga_available"] is False
    assert "not provisioned" in ctx["benzinga_limitation"]
    assert "multi-publisher" in ctx["news_source_label"]
    assert len(ctx["news_items"]) == 2
    assert {i["publisher"] for i in ctx["news_items"]} == {"Reuters", "MarketWatch"}


def test_news_filter_by_symbol(db_url: str) -> None:
    from signalforge.app.views import news_context

    _seed_news_and_entitlements()
    with session_scope() as s:
        ctx = news_context(s, symbol="nvda")
    assert [i["publisher"] for i in ctx["news_items"]] == ["Reuters"]
    assert ctx["news_items"][0]["tickers"] == ["NVDA"]


def test_options_page_never_claims_a_live_quote(registered_client: TestClient) -> None:
    _seed_news_and_entitlements()
    _seed_option_chain()
    r = registered_client.get("/options?underlying=SPY&contract=O:SPY261016C00500000")
    assert r.status_code == 200
    body = r.text
    assert "not entitled" in body.lower()
    assert "spread is estimated, not observed" in body
    assert "not entitled (spread estimated)" in body  # contract-detail bid/ask row
    # delayed labelling, never live
    assert "DELAYED" in body
    assert "never live" in body
    # education-only risk warnings present
    assert "expire worthless" in body
    assert "No order is ever placed." in body


def test_options_context_quote_unavailable_and_payoff_math(db_url: str) -> None:
    from signalforge.app.views import options_context

    _seed_news_and_entitlements()
    with session_scope() as s:
        ctx = options_context(
            s, underlying="SPY", sim="long_call", spot=100.0, strike=100.0, premium=2.0
        )
    assert ctx["quotes_available"] is False
    assert "NOT entitled" in ctx["quote_note"]
    res = ctx["sim"]["result"]
    assert res.max_loss == 200.0  # premium * 100
    assert res.break_evens == (102.0,)
    assert ctx["sim"]["payoff_svg"].startswith("<svg")
    assert len(ctx["risk_warnings"]) >= 4


def test_options_chain_explorer_renders_delayed_snapshot(registered_client: TestClient) -> None:
    _seed_option_chain()
    r = registered_client.get("/options?underlying=SPY")
    assert r.status_code == 200
    assert "O:SPY261016C00500000" in r.text
    assert "500.00" in r.text  # strike
    assert "88123" in r.text  # open interest (EOD)
    assert "snapshot as of" in r.text


@pytest.mark.parametrize("path", ["/options", "/news"])
def test_pages_are_auth_gated(client: TestClient, path: str) -> None:
    r = client.get(path, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/login")
