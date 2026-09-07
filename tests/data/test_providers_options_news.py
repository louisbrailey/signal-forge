"""Options + news adapters and ingestion: offline, delayed labels, dedupe, no secrets."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from signalforge.data.adapters.base import AdapterError
from signalforge.data.adapters.massive_news import MassiveNewsAdapter
from signalforge.data.adapters.massive_options import MassiveOptionsAdapter
from signalforge.data.entitlements import _scrub
from signalforge.data.news_ingest import ingest_news
from signalforge.data.options_ingest import ingest_options_for_underlying
from signalforge.db.models import NewsItem, OptionContract, OptionQuoteSnapshot
from signalforge.domain import LatencyCategory

_EXP = (date.today() + timedelta(days=30)).isoformat()

_CONTRACTS = {
    "status": "OK",
    "results": [
        {
            "ticker": "O:SPY_C1",
            "contract_type": "call",
            "strike_price": 500,
            "expiration_date": _EXP,
            "exercise_style": "american",
            "shares_per_contract": 100,
        },
        {
            "ticker": "O:SPY_P1",
            "contract_type": "put",
            "strike_price": 480,
            "expiration_date": _EXP,
            "exercise_style": "american",
            "shares_per_contract": 100,
        },
    ],
}
_SNAPSHOT = {
    "status": "OK",
    "results": [
        {
            "break_even_price": 505.0,
            "day": {
                "close": 5.1,
                "volume": 1200,
                "vwap": 5.0,
                "last_updated": 1_700_000_000_000_000_000,
            },
            "details": {"ticker": "O:SPY_C1", "contract_type": "call", "strike_price": 500},
            "greeks": {"delta": 0.55, "gamma": 0.02, "theta": -0.03, "vega": 0.4},
            "last_trade": {"price": 5.05, "size": 3, "sip_timestamp": 1_700_000_000_000_000_000},
            "open_interest": 8421,
            "implied_volatility": 0.19,
            "underlying_asset": {"price": 500.0},
        }
    ],
}
_NEWS = {
    "status": "OK",
    "results": [
        {
            "id": "abc123",
            "publisher": {"name": "Benzinga"},
            "title": "Example headline",
            "author": "A Writer",
            "published_utc": (datetime.now(UTC) - timedelta(hours=2))
            .isoformat()
            .replace("+00:00", "Z"),
            "article_url": "https://example.com/a",
            "tickers": ["AAPL"],
            "image_url": "https://example.com/i.png",
            "description": "body text",
            "keywords": ["earnings"],
        }
    ],
}


def _client(routes: dict[str, dict]) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"].startswith("Bearer ")
        for frag, payload in routes.items():
            if frag in str(request.url):
                return httpx.Response(200, json=payload)
        return httpx.Response(404, json={"status": "NOT_FOUND"})

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_options_adapter_parses_and_labels_delayed() -> None:
    a = MassiveOptionsAdapter("k", client=_client({"contracts": _CONTRACTS}))
    rows = a.fetch_contracts(
        "SPY", expiration_gte=date.today(), expiration_lte=date.today() + timedelta(days=60)
    )
    assert {r.contract_type for r in rows} == {"call", "put"}
    assert rows[0].shares_per_contract == 100

    a2 = MassiveOptionsAdapter("k", client=_client({"snapshot/options": _SNAPSHOT}))
    snap = a2.fetch_chain_snapshot("SPY")
    assert len(snap) == 1
    s = snap[0]
    assert s.latency_category is LatencyCategory.DELAYED  # never live
    assert s.open_interest == 8421 and s.vendor_iv == pytest.approx(0.19)
    assert s.vendor_greeks["delta"] == pytest.approx(0.55)
    assert s.day_last_updated is not None and s.last_trade_at is not None


def test_options_adapter_403_is_an_unauthorized_error_without_the_key() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"status": "NOT_AUTHORIZED"})

    a = MassiveOptionsAdapter("SECRET", client=httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(AdapterError) as exc:
        a.fetch_contracts("SPY", expiration_gte=date.today(), expiration_lte=date.today())
    assert "not authorized" in str(exc.value) and "SECRET" not in str(exc.value)


def test_news_adapter_parses_dedups_and_keeps_provenance() -> None:
    a = MassiveNewsAdapter("k", client=_client({"reference/news": _NEWS}))
    rows = a.fetch_news(["AAPL", "AAPL"], limit=5)  # same ticker twice -> still one row
    assert len(rows) == 1
    r = rows[0]
    assert r.source == "Benzinga" and r.provider_id == "abc123"
    assert r.dedupe_key == "massive_news:abc123"
    assert r.url and r.published_at.tzinfo is not None


def test_options_ingest_persists_and_dedups(session: Session) -> None:
    a = MassiveOptionsAdapter(
        "k", client=_client({"contracts": _CONTRACTS, "snapshot/options": _SNAPSHOT})
    )
    cov1 = ingest_options_for_underlying(session, a, "SPY", reference_price=500.0)
    assert cov1.contracts_written == 2 and cov1.snapshots_written == 1
    assert cov1.iv_present == 1 and cov1.greeks_present == 1
    cov2 = ingest_options_for_underlying(session, a, "SPY", reference_price=500.0)
    assert cov2.contracts_written == 0  # dedup
    assert session.scalar(select(func.count()).select_from(OptionContract)) == 2
    assert session.scalar(select(func.count()).select_from(OptionQuoteSnapshot)) == 2


def test_news_ingest_persists_and_dedups(session: Session) -> None:
    a = MassiveNewsAdapter("k", client=_client({"reference/news": _NEWS}))
    r1 = ingest_news(session, a, ["AAPL"], lookback_days=1)
    assert r1.written == 1 and r1.publishers == ["Benzinga"]
    r2 = ingest_news(session, a, ["AAPL"], lookback_days=1)
    assert r2.written == 0 and r2.duplicates >= 1
    assert session.scalar(select(func.count()).select_from(NewsItem)) == 1


def test_scrub_removes_secrets_and_keylike_query_fragments() -> None:
    out = _scrub("boom apikey=abcd1234 and Bearer XYZ here", "XYZ")
    assert "abcd1234" not in out and "XYZ" not in out and "[REDACTED]" in out
