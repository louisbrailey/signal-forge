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


def _seed_news_and_entitlements(*, benzinga_ok: bool = False, not_authorized: bool = False) -> None:
    from signalforge.db.models import EntitlementCheck, NewsItem

    if benzinga_ok:
        detail = (
            "live via /v2/reference/news — 8/200 sampled articles Benzinga-published, "
            "newest 2026-09-06 (0d old); also seen: The Motley Fool, Zacks"
        )
        error_category = "none"
    elif not_authorized:
        detail = "HTTP 403 — licensed news feed rejected the key"
        error_category = "not_authorized"
    else:
        detail = (
            "STALE — 152 Benzinga articles in the sample but the newest is "
            "2026-06-18 (81d old); the feed is not currently delivering Benzinga "
            "(other publishers current to 2026-09-07). The account may show "
            "Benzinga active but this API key is not receiving it."
        )
        error_category = "empty"

    with session_scope() as s:
        s.add(
            EntitlementCheck(
                batch_id="test-batch",
                subscription="benzinga_news",
                feed="benzinga_news",
                endpoint="/v2/reference/news (publisher=Benzinga)",
                source="benzinga",
                checked_at=datetime(2026, 9, 6, 12, 0, tzinfo=UTC),
                http_status=200 if not not_authorized else 403,
                available=benzinga_ok,
                latency_category="DELAYED" if benzinga_ok else "none",
                error_category=error_category,
                detail=detail,
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
        # a Benzinga-published article ingested before the 2026-06-18 cutoff —
        # still in storage, must stay in its own labelled section, never blended
        # into "current" generic news.
        s.add(
            NewsItem(
                headline="Benzinga: sector rotation into small caps",
                url="https://example.com/c",
                published_at=datetime(2026, 6, 17, 15, 0, tzinfo=UTC),
                retrieved_at=datetime(2026, 6, 17, 15, 10, tzinfo=UTC),
                source="Benzinga",
                provider="massive_benzinga_news",
                provider_id="bz-1",
                dedupe_key="dk-bz-1",
                category="markets",
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
def test_news_page_states_benzinga_is_stale(registered_client: TestClient) -> None:
    _seed_news_and_entitlements()
    r = registered_client.get("/news")
    assert r.status_code == 200
    assert "Stale feed" in r.text
    assert "subscribed but not delivering current content" in r.text
    assert "not used for alerts or the daily briefing" in r.text
    assert "STALE" in r.text and "81d old" in r.text
    # Benzinga content is shown in its own section, separate from generic news
    assert "Benzinga-labelled news" in r.text and "Generic publisher news" in r.text
    assert "Benzinga: sector rotation into small caps" in r.text
    # real publishers shown, not relabelled as Benzinga
    assert "Reuters" in r.text and "MarketWatch" in r.text
    assert "Chipmaker raises full-year outlook" in r.text
    assert "not financial advice" in r.text.lower()


def test_news_page_states_benzinga_not_authorized(registered_client: TestClient) -> None:
    """A genuine auth/entitlement failure (not staleness) keeps the older,
    distinct 'not entitled' framing — the two failure modes must not collapse
    into one message."""
    _seed_news_and_entitlements(not_authorized=True)
    r = registered_client.get("/news")
    assert r.status_code == 200
    assert "not currently entitled on this API key" in r.text
    assert "Stale feed" not in r.text
    assert "not financial advice" in r.text.lower()


def test_news_context_reports_limitation_and_source_label(db_url: str) -> None:
    from signalforge.app.views import news_context

    _seed_news_and_entitlements()
    with session_scope() as s:
        ctx = news_context(s)
    assert ctx["benzinga_available"] is False
    assert ctx["benzinga_stale"] is True
    assert "STALE" in ctx["benzinga_limitation"]
    assert "STALE" in ctx["news_source_label"]
    assert len(ctx["news_items"]) == 3
    assert {i["publisher"] for i in ctx["news_items"]} == {"Reuters", "MarketWatch", "Benzinga"}
    # split: Benzinga-labelled news never mixes into the generic list
    assert [i["publisher"] for i in ctx["benzinga_items"]] == ["Benzinga"]
    assert {i["publisher"] for i in ctx["generic_items"]} == {"Reuters", "MarketWatch"}


def test_news_context_not_authorized_is_not_flagged_stale(db_url: str) -> None:
    from signalforge.app.views import news_context

    _seed_news_and_entitlements(not_authorized=True)
    with session_scope() as s:
        ctx = news_context(s)
    assert ctx["benzinga_available"] is False
    assert ctx["benzinga_stale"] is False
    assert "not currently entitled" in ctx["news_source_label"]


def test_news_context_label_switches_when_benzinga_is_live(db_url: str) -> None:
    from signalforge.app.views import news_context

    _seed_news_and_entitlements(benzinga_ok=True)
    with session_scope() as s:
        ctx = news_context(s)
    assert ctx["benzinga_available"] is True
    assert ctx["benzinga_stale"] is False
    assert (
        ctx["news_source_label"] == "Benzinga News (licensed primary) + other licensed publishers"
    )
    assert ctx["benzinga_limitation"] == ""  # no limitation when live
    assert "live via /v2/reference/news" in ctx["benzinga_note"]
    assert [i["publisher"] for i in ctx["benzinga_items"]] == ["Benzinga"]


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
