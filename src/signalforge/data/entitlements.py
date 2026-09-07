"""Provider-entitlement verification (read-only, secret-safe).

Probes the endpoints Signal Forge would use with the credentials already in the
local environment and reports, per feed, whether it is *actually* reachable and
authorized. Nothing here changes ingestion behaviour — callers decide what to do
with an ``unavailable`` result, and an unavailable feed is never assumed live.

Secret safety: the API key travels only in the ``Authorization`` header; it is
scrubbed from every returned string; no key, header, full URL with query, or
webhook URL is ever logged, cached, or returned. Discord is checked for
presence/format only — no request is made (a test post is a separate, explicitly
confirmed action).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import httpx

from signalforge.config import Settings, get_settings

_MASSIVE_BASE = "https://api.massive.com"
_TIMEOUT = 15.0
_REDACTED = "[REDACTED]"


@dataclass(frozen=True, slots=True)
class Probe:
    feed: str  # stocks_daily | stocks_history_10y | options_contracts | options_chain | news
    provider: str
    reachable: bool
    http_status: int | None
    authorized: bool
    available: bool
    sample_keys: tuple[str, ...] = ()
    note: str = ""


@dataclass(frozen=True, slots=True)
class EntitlementReport:
    probes: list[Probe] = field(default_factory=list)
    discord_configured: bool = False
    discord_note: str = ""

    def available_feeds(self) -> list[str]:
        return [p.feed for p in self.probes if p.available]

    def unavailable_feeds(self) -> list[str]:
        return [p.feed for p in self.probes if not p.available]

    def to_rows(self) -> list[dict[str, Any]]:
        return [
            {
                "feed": p.feed,
                "provider": p.provider,
                "reachable": p.reachable,
                "http_status": p.http_status,
                "authorized": p.authorized,
                "available": p.available,
                "sample_keys": list(p.sample_keys),
                "note": p.note,
            }
            for p in self.probes
        ]


def _scrub(text: str, *secrets: str) -> str:
    out = text
    for s in secrets:
        if s:
            out = out.replace(s, _REDACTED)
    # Also drop any apiKey/token-looking query fragment defensively.
    out = re.sub(r"(api[_-]?key|token|apikey)=[^&\s\"']+", r"\1=" + _REDACTED, out, flags=re.I)
    return out[:400]


def _get(
    client: httpx.Client, path: str, key: str
) -> tuple[int | None, dict[str, Any] | None, str]:
    """GET a Massive path with the key in the header only. Returns (status, json, note)."""
    try:
        resp = client.get(
            _MASSIVE_BASE + path,
            headers={"Authorization": f"Bearer {key}"},
            timeout=_TIMEOUT,
            follow_redirects=False,
        )
    except httpx.HTTPError as exc:
        return None, None, _scrub(f"network error: {type(exc).__name__}", key)
    status = resp.status_code
    body: dict[str, Any] | None = None
    if resp.headers.get("content-type", "").startswith("application/json"):
        try:
            parsed = resp.json()
            body = parsed if isinstance(parsed, dict) else {"_list": parsed}
        except ValueError:
            body = None
    note = "" if status == 200 else _scrub(resp.text, key)
    return status, body, note


def _probe(
    client: httpx.Client,
    key: str,
    *,
    feed: str,
    provider: str,
    path: str,
    ok_keys: tuple[str, ...] = ("results", "data", "_list"),
) -> Probe:
    if not key:
        return Probe(feed, provider, False, None, False, False, note="no API key configured")
    status, body, note = _get(client, path, key)
    reachable = status is not None
    authorized = status not in (401, 403)
    keys = tuple(sorted(body.keys()))[:12] if isinstance(body, dict) else ()
    has_payload = isinstance(body, dict) and any(
        k in body and body[k] not in (None, [], {}) for k in ok_keys
    )
    available = bool(status == 200 and (has_payload or not ok_keys))
    if status == 200 and not has_payload:
        note = "200 OK but no data rows for the sample query — entitlement unclear"
    return Probe(feed, provider, reachable, status, authorized, available, keys, note)


def verify_entitlements(settings: Settings | None = None) -> EntitlementReport:
    s = settings or get_settings()
    stock_key = s.market_data_api_key.get_secret_value()
    opt_key = s.options_api_key.get_secret_value() or stock_key
    news_key = s.news_api_key.get_secret_value() or stock_key
    provider = s.market_data_provider or "unset"

    probes: list[Probe] = []
    with httpx.Client() as client:
        probes.append(
            _probe(
                client,
                stock_key,
                feed="stocks_daily",
                provider=provider,
                path="/v2/aggs/ticker/AAPL/range/1/day/2024-01-02/2024-01-08?adjusted=true&limit=5",
            )
        )
        probes.append(
            _probe(
                client,
                stock_key,
                feed="stocks_history_10y",
                provider=provider,
                path="/v2/aggs/ticker/AAPL/range/1/day/2015-01-05/2015-01-16?adjusted=true&limit=5",
            )
        )
        probes.append(
            _probe(
                client,
                opt_key,
                feed="options_contracts",
                provider=s.options_provider or provider,
                path="/v3/reference/options/contracts?underlying_ticker=SPY&limit=1",
            )
        )
        probes.append(
            _probe(
                client,
                opt_key,
                feed="options_chain",
                provider=s.options_provider or provider,
                path="/v3/snapshot/options/SPY?limit=1",
            )
        )
        # News: try the two documented shapes; report the first that authorizes.
        news_probe = _probe(
            client,
            news_key,
            feed="news",
            provider=s.news_provider or "benzinga-via-massive",
            path="/v2/reference/news?ticker=AAPL&limit=1&order=desc",
        )
        if not news_probe.available:
            alt = _probe(
                client,
                news_key,
                feed="news",
                provider=s.news_provider or "benzinga-via-massive",
                path="/benzinga/v1/news?tickers=AAPL&pageSize=1",
                ok_keys=("_list", "data", "results"),
            )
            news_probe = alt if alt.available or alt.authorized else news_probe
        probes.append(news_probe)

    webhook = s.discord_webhook_url.get_secret_value()
    discord_ok = bool(re.match(r"https://(discord(app)?\.com)/api/webhooks/\d+/[\w-]+", webhook))
    discord_note = (
        "webhook URL present and well-formed (not contacted)"
        if discord_ok
        else ("no DISCORD_WEBHOOK_URL set" if not webhook else "DISCORD_WEBHOOK_URL is malformed")
    )
    return EntitlementReport(
        probes=probes, discord_configured=discord_ok, discord_note=discord_note
    )
