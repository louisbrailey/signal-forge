"""Provider-entitlement verification (read-only, secret-safe).

Probes each concrete endpoint Signal Forge would use with the credentials already
in the local environment and records, per feed: entitlement status, endpoint,
source, timestamp, latency category, and error category. Nothing here changes
ingestion behaviour — an ``unavailable`` feed is never assumed available.

Secret safety: the API key travels only in the ``Authorization`` header; it is
scrubbed from every returned string; no key, header, full URL with query, or
webhook URL is ever logged, cached, committed, or returned. Discord is checked
for presence/format only — no request is made.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx

from signalforge.config import Settings, get_settings

_MASSIVE_BASE = "https://api.massive.com"
_TIMEOUT = 20.0
_REDACTED = "[REDACTED]"

# error categories: none | auth_missing | not_authorized | rate_limited
#                   | not_found | network | parse | empty
LatencyLabel = str  # REALTIME | DELAYED | END_OF_DAY | HISTORICAL | none


@dataclass(frozen=True, slots=True)
class EndpointCheck:
    feed: str
    subscription: str  # stocks_developer | options_developer | benzinga_news | discord
    endpoint: str  # path only, no query secrets
    source: str  # provider name
    checked_at: str  # ISO-8601 UTC
    http_status: int | None
    available: bool
    latency_category: LatencyLabel
    error_category: str
    detail: str = ""

    def to_row(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class EntitlementReport:
    checks: list[EndpointCheck] = field(default_factory=list)
    discord_configured: bool = False
    discord_note: str = ""

    def by_subscription(self, sub: str) -> list[EndpointCheck]:
        return [c for c in self.checks if c.subscription == sub]

    def available(self, feed: str) -> bool:
        return any(c.feed == feed and c.available for c in self.checks)

    def to_rows(self) -> list[dict[str, Any]]:
        return [c.to_row() for c in self.checks]


def _parse_iso(s: Any) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None


def _scrub(text: str, *secrets: str) -> str:
    out = text
    for s in secrets:
        if s:
            out = out.replace(s, _REDACTED)
    out = re.sub(r"(api[_-]?key|token|apikey)=[^&\s\"']+", r"\1=" + _REDACTED, out, flags=re.I)
    return out[:300]


def _classify(status: int | None, body: dict[str, Any] | None) -> tuple[bool, str]:
    """Return (available, error_category)."""
    if status is None:
        return False, "network"
    if status in (401,):
        return False, "not_authorized"
    if status == 403:
        return False, "not_authorized"
    if status == 404:
        return False, "not_found"
    if status == 429:
        return False, "rate_limited"
    if status != 200:
        return False, "network"
    if body is None:
        return False, "parse"
    # a 200 with an explicit non-OK status field, or no rows for the sample query
    st = str(body.get("status", "")).upper()
    if st not in ("OK", "DELAYED", ""):
        return False, "empty"
    rows = body.get("results")
    count = body.get("resultsCount") or body.get("count")
    has_rows = bool(rows) if isinstance(rows, list) else (rows not in (None, {}, []))
    if not has_rows and (count in (0, None)) and "results" in body:
        return False, "empty"
    return True, "none"


def _get(client: httpx.Client, path: str, key: str) -> tuple[int | None, dict[str, Any] | None]:
    try:
        resp = client.get(
            _MASSIVE_BASE + path,
            headers={"Authorization": f"Bearer {key}"},
            timeout=_TIMEOUT,
            follow_redirects=False,
        )
    except httpx.HTTPError:
        return None, None
    body: dict[str, Any] | None = None
    if resp.headers.get("content-type", "").startswith("application/json"):
        try:
            parsed = resp.json()
            body = parsed if isinstance(parsed, dict) else {"results": parsed}
        except ValueError:
            body = None
    return resp.status_code, body


def _check(
    client: httpx.Client,
    key: str,
    *,
    feed: str,
    subscription: str,
    endpoint_display: str,
    path: str,
    latency: LatencyLabel,
    source: str,
) -> EndpointCheck:
    now = datetime.now(UTC).isoformat()
    if not key:
        return EndpointCheck(
            feed,
            subscription,
            endpoint_display,
            source,
            now,
            None,
            False,
            "none",
            "auth_missing",
            "no API key configured",
        )
    status, body = _get(client, path, key)
    available, err = _classify(status, body)
    # trust the provider's own DELAYED marker over our assumption
    body_status = str((body or {}).get("status", "")).upper()
    eff_latency = "DELAYED" if body_status == "DELAYED" else latency
    detail = ""
    if not available and body is not None:
        detail = _scrub(str(body.get("message") or body.get("error") or ""), key)
    return EndpointCheck(
        feed,
        subscription,
        endpoint_display,
        source,
        now,
        status,
        available,
        eff_latency if available else "none",
        err,
        detail,
    )


def _sample_option_contract(client: httpx.Client, key: str) -> tuple[str | None, str | None]:
    """Pick a *liquid, near-the-money* SPY call ~20-45 days out so per-contract
    probes don't false-negative on an illiquid deep strike. Returns (contract, expiry)."""
    _, spy = _get(
        client, "/v2/aggs/ticker/SPY/range/1/day/2024-01-02/2024-01-05?adjusted=true", key
    )
    _, last = _get(client, "/v2/last/trade/SPY", key)
    px = None
    if last and isinstance(last.get("results"), dict):
        px = last["results"].get("p")
    if px is None and spy and spy.get("results"):
        px = spy["results"][-1].get("c")
    lo = round((px or 500) * 0.98)
    hi = round((px or 500) * 1.02)
    exp_lo = (date.today() + timedelta(days=20)).isoformat()
    exp_hi = (date.today() + timedelta(days=45)).isoformat()
    status, body = _get(
        client,
        f"/v3/reference/options/contracts?underlying_ticker=SPY&contract_type=call"
        f"&expiration_date.gte={exp_lo}&expiration_date.lte={exp_hi}"
        f"&strike_price.gte={lo}&strike_price.lte={hi}&limit=1",
        key,
    )
    if status == 200 and body and body.get("results"):
        r0 = body["results"][0]
        return str(r0.get("ticker") or "") or None, str(r0.get("expiration_date") or "") or None
    return None, None


def verify_entitlements(settings: Settings | None = None) -> EntitlementReport:
    s = settings or get_settings()
    stock_key = s.market_data_api_key.get_secret_value()
    opt_key = s.options_api_key.get_secret_value() or stock_key
    news_key = s.news_api_key.get_secret_value() or stock_key
    provider = s.market_data_provider or "unset"
    today = date.today()
    d9 = today - timedelta(days=int(9 * 365.25))

    checks: list[EndpointCheck] = []
    with httpx.Client() as client:
        # ---- Stocks Developer -------------------------------------------------
        checks.append(
            _check(
                client,
                stock_key,
                feed="stocks_daily_bars",
                subscription="stocks_developer",
                endpoint_display="/v2/aggs/ticker/{sym}/range/1/day/{from}/{to}",
                path="/v2/aggs/ticker/AAPL/range/1/day/2024-01-02/2024-01-08?adjusted=true&limit=5",
                latency="END_OF_DAY",
                source=provider,
            )
        )
        checks.append(
            _check(
                client,
                stock_key,
                feed="stocks_history_10y",
                subscription="stocks_developer",
                endpoint_display="/v2/aggs/ticker/{sym}/range/1/day/{~9y}/{...}",
                path=f"/v2/aggs/ticker/AAPL/range/1/day/{d9}/{d9 + timedelta(days=10)}"
                "?adjusted=true&limit=5",
                latency="HISTORICAL",
                source=provider,
            )
        )
        checks.append(
            _check(
                client,
                stock_key,
                feed="stocks_intraday_aggs_5m",
                subscription="stocks_developer",
                endpoint_display="/v2/aggs/ticker/{sym}/range/5/minute/{from}/{to}",
                path=f"/v2/aggs/ticker/AAPL/range/5/minute/{today - timedelta(days=4)}/"
                f"{today - timedelta(days=1)}?adjusted=true&limit=5",
                latency="DELAYED",
                source=provider,
            )
        )
        checks.append(
            _check(
                client,
                stock_key,
                feed="stocks_last_trade",
                subscription="stocks_developer",
                endpoint_display="/v2/last/trade/{sym}",
                path="/v2/last/trade/AAPL",
                latency="DELAYED",
                source=provider,
            )
        )
        checks.append(
            _check(
                client,
                stock_key,
                feed="stocks_nbbo_quotes",
                subscription="stocks_developer",
                endpoint_display="/v3/quotes/{sym}",
                path="/v3/quotes/AAPL?limit=1",
                latency="DELAYED",
                source=provider,
            )
        )

        # ---- Options Developer ---------------------------------------------- #
        oc, oc_exp = _sample_option_contract(client, opt_key)
        checks.append(
            _check(
                client,
                opt_key,
                feed="options_contracts",
                subscription="options_developer",
                endpoint_display="/v3/reference/options/contracts",
                path="/v3/reference/options/contracts?underlying_ticker=SPY&limit=1",
                latency="HISTORICAL",
                source=provider,
            )
        )
        checks.append(
            _check(
                client,
                opt_key,
                feed="options_chain_snapshot",
                subscription="options_developer",
                endpoint_display="/v3/snapshot/options/{underlying}",
                path="/v3/snapshot/options/SPY?limit=1",
                latency="DELAYED",
                source=provider,
            )
        )
        checks.append(
            _check(
                client,
                opt_key,
                feed="options_contract_snapshot",
                subscription="options_developer",
                endpoint_display="/v3/snapshot/options/{underlying}/{contract}",
                path=f"/v3/snapshot/options/SPY/{oc}" if oc else "/v3/snapshot/options/SPY/O:NONE",
                latency="DELAYED",
                source=provider,
            )
        )
        checks.append(
            _check(
                client,
                opt_key,
                feed="options_historical_aggs",
                subscription="options_developer",
                endpoint_display="/v2/aggs/ticker/{O:contract}/range/1/day/{from}/{to}",
                path=(
                    (
                        f"/v2/aggs/ticker/{oc}/range/1/day/{today - timedelta(days=30)}/"
                        f"{today - timedelta(days=1)}?limit=5"
                    )
                    if oc
                    else "/v2/aggs/ticker/O:NONE/range/1/day/2024-01-01/2024-01-05"
                ),
                latency="HISTORICAL",
                source=provider,
            )
        )
        checks.append(
            _check(
                client,
                opt_key,
                feed="options_delayed_trades",
                subscription="options_developer",
                endpoint_display="/v3/trades/{O:contract}",
                path=f"/v3/trades/{oc}?limit=2" if oc else "/v3/trades/O:NONE",
                latency="DELAYED",
                source=provider,
            )
        )
        checks.append(
            _check(
                client,
                opt_key,
                feed="options_last_trade",
                subscription="options_developer",
                endpoint_display="/v2/last/trade/{O:contract}",
                path=f"/v2/last/trade/{oc}" if oc else "/v2/last/trade/O:NONE",
                latency="DELAYED",
                source=provider,
            )
        )
        checks.append(
            _check(
                client,
                opt_key,
                feed="options_quotes_bidask",
                subscription="options_developer",
                endpoint_display="/v3/quotes/{O:contract}",
                path=f"/v3/quotes/{oc}?limit=2" if oc else "/v3/quotes/O:NONE",
                latency="DELAYED",
                source=provider,
            )
        )
        # greeks / IV / OI live inside the chain snapshot — probe field presence
        gc = _greeks_iv_oi(client, opt_key, provider, expiry=oc_exp)
        checks.extend(gc)

        # ---- Benzinga News ------------------------------------------------- #
        # On this vendor Benzinga *news* is delivered through the unified
        # /v2/reference/news feed (there is no /benzinga/v1/news path — it 404s
        # with an empty body, unlike the real, structured-403 /benzinga/v1/*
        # sub-products). The entitlement gates *which publishers appear* in that
        # feed, so the only honest check is content-based: sample the feed and
        # look for Benzinga-published articles.
        checks.append(_benzinga_news_check(client, news_key, provider))
        # licensed-feed reachability, independent of Benzinga content
        checks.append(
            _check(
                client,
                news_key,
                feed="news_licensed_feed",
                subscription="benzinga_news",
                endpoint_display="/v2/reference/news",
                path="/v2/reference/news?ticker=AAPL&limit=1&order=desc",
                latency="DELAYED",
                source=provider,
            )
        )
        # Benzinga *structured* sub-products (ratings / analyst insights) are a
        # separate entitlement from Benzinga news — probed so the report is exact.
        for feed, seg in (
            ("benzinga_ratings", "ratings"),
            ("benzinga_analyst_insights", "analyst-insights"),
        ):
            checks.append(
                _check(
                    client,
                    news_key,
                    feed=feed,
                    subscription="benzinga_news",
                    endpoint_display=f"/benzinga/v1/{seg}",
                    path=f"/benzinga/v1/{seg}?limit=1",
                    latency="DELAYED",
                    source="benzinga",
                )
            )

    webhook = s.discord_webhook_url.get_secret_value()
    discord_ok = bool(re.match(r"https://(discord(app)?\.com)/api/webhooks/\d+/[\w-]+", webhook))
    discord_note = (
        "webhook URL present and well-formed (not contacted)"
        if discord_ok
        else ("no DISCORD_WEBHOOK_URL set" if not webhook else "DISCORD_WEBHOOK_URL is malformed")
    )
    return EntitlementReport(
        checks=checks, discord_configured=discord_ok, discord_note=discord_note
    )


_BENZINGA_SAMPLE_TICKERS = ("SPY", "AAPL", "NVDA", "TSLA", "MSFT", "NFLX")
_BENZINGA_SAMPLE_PER_TICKER = 50
_BENZINGA_SAMPLE_PAGES = 4  # paginate: Benzinga items may sit deeper than page 1
_BENZINGA_FRESH_DAYS = 10  # a live licensed feed carries Benzinga items this recent


def _benzinga_news_check(client: httpx.Client, key: str, provider: str) -> EndpointCheck:
    """Content-based Benzinga-news entitlement probe.

    On this vendor Benzinga news rides the unified ``/v2/reference/news`` feed and
    the entitlement decides whether Benzinga-published articles appear in it — so
    a bare "is any Benzinga article present" check is not enough: a lapsed feed
    still returns historical Benzinga items. ``available`` therefore requires a
    Benzinga article no older than ``_BENZINGA_FRESH_DAYS`` (i.e. the feed is
    *currently* delivering Benzinga), sampled across several liquid tickers and a
    few pages deep.
    """
    now_dt = datetime.now(UTC)
    now = now_dt.isoformat()
    feed = sub = "benzinga_news"
    endpoint = "/v2/reference/news (publisher=Benzinga)"
    if not key:
        return EndpointCheck(
            feed,
            sub,
            endpoint,
            "benzinga",
            now,
            None,
            False,
            "none",
            "auth_missing",
            "no API key configured",
        )

    total = benzinga = 0
    publishers: set[str] = set()
    newest_bz: datetime | None = None
    newest_any: datetime | None = None
    last_status: int | None = None
    for tk in _BENZINGA_SAMPLE_TICKERS:
        path: str | None = (
            f"/v2/reference/news?ticker={tk}&order=desc&limit={_BENZINGA_SAMPLE_PER_TICKER}"
        )
        for _ in range(_BENZINGA_SAMPLE_PAGES):
            if not path:
                break
            status, body = _get(client, path, key)
            last_status = status
            if status != 200 or not body:
                break
            for art in body.get("results") or []:
                if not isinstance(art, dict):
                    continue
                total += 1
                name = str((art.get("publisher") or {}).get("name") or "").strip()
                if name:
                    publishers.add(name)
                pub_dt = _parse_iso(art.get("published_utc"))
                if pub_dt and (newest_any is None or pub_dt > newest_any):
                    newest_any = pub_dt
                parts = str(art.get("article_url") or "").split("/")
                host = (parts[2] if len(parts) > 2 else "").lower()
                if name.lower() == "benzinga" or "benzinga.com" in host:
                    benzinga += 1
                    if pub_dt and (newest_bz is None or pub_dt > newest_bz):
                        newest_bz = pub_dt
            follow = body.get("next_url") or ""
            path = re.sub(r"^https?://[^/]+", "", follow) if follow else None

    if last_status in (401, 403):
        return EndpointCheck(
            feed,
            sub,
            endpoint,
            "benzinga",
            now,
            last_status,
            False,
            "none",
            "not_authorized",
            "licensed news feed rejected the key",
        )
    if total == 0:
        return EndpointCheck(
            feed,
            sub,
            endpoint,
            "benzinga",
            now,
            last_status,
            False,
            "none",
            "empty",
            "licensed news feed returned no articles for the sample",
        )

    bz_date = newest_bz.date().isoformat() if newest_bz else "never"
    any_date = newest_any.date().isoformat() if newest_any else "?"
    age_days = (now_dt - newest_bz).days if newest_bz else None
    available = age_days is not None and age_days <= _BENZINGA_FRESH_DAYS
    seen = ", ".join(sorted(publishers)[:6]) or "none"
    if available:
        detail = (
            f"live via /v2/reference/news — {benzinga}/{total} sampled articles "
            f"Benzinga-published, newest {bz_date} ({age_days}d old); also seen: {seen}"
        )
    elif benzinga > 0:
        detail = (
            f"STALE — {benzinga} Benzinga articles in the sample but the newest is "
            f"{bz_date} ({age_days}d old); the feed is not currently delivering Benzinga "
            f"(other publishers current to {any_date}). The account may show Benzinga active "
            f"but this API key is not receiving it."
        )
    else:
        detail = f"no Benzinga-published articles in a {total}-article sample (seen: {seen})"
    return EndpointCheck(
        feed,
        sub,
        endpoint,
        "benzinga",
        now,
        last_status,
        available,
        "DELAYED" if available else "none",
        "none" if available else "empty",
        detail,
    )


def _greeks_iv_oi(
    client: httpx.Client, key: str, provider: str, *, expiry: str | None = None
) -> list[EndpointCheck]:
    """Probe greeks / implied_volatility / open_interest presence in a near-the-money
    chain snapshot for a single near expiry (they are fields, not endpoints)."""
    now = datetime.now(UTC).isoformat()
    out: list[EndpointCheck] = []
    exp_q = f"&expiration_date={expiry}" if expiry else ""
    status, body = _get(
        client,
        f"/v3/snapshot/options/SPY?limit=50{exp_q}",
        key,
    )
    rows = (body or {}).get("results") or []
    # keep only the near-the-money slice
    ua = next(
        (r.get("underlying_asset", {}).get("price") for r in rows if isinstance(r, dict)), None
    )
    if ua:
        rows = [
            r
            for r in rows
            if isinstance(r, dict)
            and abs((r.get("details", {}).get("strike_price") or 0) - ua) / ua < 0.05
        ] or rows
    for feed, field_names in (
        ("options_greeks", ("greeks",)),
        ("options_implied_vol", ("implied_volatility",)),
        ("options_open_interest", ("open_interest",)),
    ):
        present = any(
            all(r.get(fn) not in (None, {}, []) for fn in field_names)
            for r in rows
            if isinstance(r, dict)
        )
        latency = "END_OF_DAY" if feed == "options_open_interest" else "DELAYED"
        out.append(
            EndpointCheck(
                feed=feed,
                subscription="options_developer",
                endpoint=f"/v3/snapshot/options/{{underlying}} :: {field_names[0]}",
                source=provider,
                checked_at=now,
                http_status=status,
                available=bool(status == 200 and present),
                latency_category=latency if (status == 200 and present) else "none",
                error_category=(
                    "none"
                    if (status == 200 and present)
                    else ("not_authorized" if status in (401, 403) else "empty")
                ),
                detail="" if present else "field absent from a near-the-money snapshot sample",
            )
        )
    return out
