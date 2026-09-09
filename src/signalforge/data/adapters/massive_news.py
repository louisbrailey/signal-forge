"""Read-only licensed news adapters via Massive.

Two distinct, separately-labelled feeds, never merged:

- ``MassiveNewsAdapter`` — the generic multi-publisher feed
  (``/v2/reference/news``). Benzinga-attributed rows are explicitly excluded
  here (defense in depth) so Benzinga content only ever enters through its
  own adapter below.
- ``BenzingaNewsAdapter`` — the dedicated Benzinga News add-on endpoint
  (``GET /benzinga/v2/news``). The retired workaround of sampling the
  generic feed and filtering client-side for ``publisher == "Benzinga"``
  (the only option before this add-on was active, since ``?publisher=``
  is silently ignored on the generic feed and there never was a working
  ``/benzinga/v1/news`` path) is gone — this is the only Benzinga news
  endpoint used anywhere in this codebase.

Read-only: no posting, no scraping of article bodies beyond the licensed
short-form text the API returns, no LLM here. Callers persist raw audit
metadata, deduplicate by the vendor id, and keep the source link. News never
creates, ranks, alters, or overrides a trading recommendation (import-linter
contract S12).

The API key travels only in the Authorization header and is scrubbed from
errors.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

import httpx

from signalforge.config import get_settings
from signalforge.data.adapters.base import AdapterError
from signalforge.killswitch import ensure_not_engaged

_BASE = "https://api.massive.com"
_TIMEOUT = 20.0
_MAX_PAGES = 10


@dataclass(frozen=True, slots=True)
class NewsRow:
    provider_id: str
    dedupe_key: str
    headline: str
    url: str
    source: str  # publisher name, e.g. "Benzinga"
    author: str
    published_at: datetime
    retrieved_at: datetime
    tickers: list[str]
    category: str
    image_url: str
    description: str
    raw: dict[str, Any] = field(default_factory=dict)


class NewsFeedAdapter(Protocol):
    """Structural type shared by every news adapter here — lets
    ``news_ingest.ingest_news`` accept ``MassiveNewsAdapter`` or
    ``BenzingaNewsAdapter`` (or any future feed adapter) interchangeably
    without importing every concrete class."""

    provider_name: str

    def fetch_news(
        self,
        tickers: list[str],
        *,
        published_gte: datetime | None = None,
        limit: int = 50,
    ) -> list[NewsRow]: ...


def _parse_dt(s: Any) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None


class _MassiveNewsBase:
    """Shared HTTP plumbing for every Massive-hosted news adapter: key
    resolution, auth header, error classification, and ``next_url``
    pagination (cursor- or date-based — both are plain absolute URLs, so the
    same domain-stripping regex follows either)."""

    provider_name = "massive_news_base"  # overridden by each concrete adapter

    def __init__(self, api_key: str | None = None, *, client: httpx.Client | None = None) -> None:
        s = get_settings()
        self._key = (
            (s.news_api_key.get_secret_value() or s.market_data_api_key.get_secret_value())
            if api_key is None
            else api_key
        )
        self._client = client

    def _get(self, path: str) -> dict[str, Any]:
        ensure_not_engaged()
        if not self._key:
            raise AdapterError("news adapter: no API key configured")
        getter = self._client.get if self._client is not None else httpx.get
        try:
            resp = getter(
                _BASE + path,
                headers={"Authorization": f"Bearer {self._key}"},
                timeout=_TIMEOUT,
                follow_redirects=False,
            )
        except httpx.HTTPError:
            raise AdapterError("news adapter: network request failed") from None
        if resp.status_code in (401, 403):
            raise AdapterError("news adapter: not authorized for this data")
        if resp.status_code == 429:
            raise AdapterError("news adapter: rate limited", rate_limited=True)
        if resp.status_code != 200:
            raise AdapterError(f"news adapter: HTTP {resp.status_code}")
        try:
            body = resp.json()
        except ValueError:
            raise AdapterError("news adapter: non-JSON response") from None
        return body if isinstance(body, dict) else {"results": body}

    def _paginate(self, path: str) -> Iterator[dict[str, Any]]:
        pages = 0
        nxt: str | None = path
        while nxt and pages < _MAX_PAGES:
            body = self._get(nxt)
            yield from body.get("results", []) or []
            follow = body.get("next_url") or ""
            nxt = re.sub(r"^https?://[^/]+", "", follow) if follow else None
            pages += 1


class MassiveNewsAdapter(_MassiveNewsBase):
    """The generic, multi-publisher licensed feed. Benzinga-attributed items
    are excluded here even if the vendor's unified feed still includes some —
    Benzinga content only ever comes from ``BenzingaNewsAdapter``, so the two
    stay cleanly separate in the database (``NewsItem.provider``)."""

    provider_name = "massive_news_generic"

    def fetch_news(
        self,
        tickers: list[str],
        *,
        published_gte: datetime | None = None,
        limit: int = 50,
    ) -> list[NewsRow]:
        retrieved = datetime.now(UTC)
        out: list[NewsRow] = []
        for tk in [t.upper().strip() for t in tickers if t.strip()]:
            q = f"/v2/reference/news?ticker={tk}&order=desc&limit={min(limit, 1000)}"
            if published_gte is not None:
                # date-only bound keeps the value URL-safe (no '+'/':' in the query)
                q += f"&published_utc.gte={published_gte.astimezone(UTC).date().isoformat()}"
            for r in self._paginate(q):
                pub_at = _parse_dt(r.get("published_utc"))
                if pub_at is None:
                    continue
                publisher = str((r.get("publisher") or {}).get("name", "") or "unknown")
                if publisher.strip().lower() == "benzinga":
                    continue  # belongs to BenzingaNewsAdapter, not the generic feed
                vid = str(r.get("id") or r.get("article_url") or r.get("title", ""))
                out.append(
                    NewsRow(
                        provider_id=vid,
                        dedupe_key=f"{self.provider_name}:{vid}",
                        headline=str(r.get("title", ""))[:400],
                        url=str(r.get("article_url", ""))[:600],
                        source=publisher[:60],
                        author=str(r.get("author", ""))[:160],
                        published_at=pub_at,
                        retrieved_at=retrieved,
                        tickers=[str(x).upper() for x in (r.get("tickers") or [])][:40],
                        category=str((r.get("keywords") or [""])[0])[:60],
                        image_url=str(r.get("image_url", ""))[:600],
                        description=str(r.get("description", "")),
                        raw=r,
                    )
                )
        return _dedupe_newest_first(out)


class BenzingaNewsAdapter(_MassiveNewsBase):
    """The dedicated Benzinga News add-on feed — ``GET /benzinga/v2/news``.
    Every item is Benzinga-published by construction (the endpoint carries no
    other publisher), so ``source`` is set directly rather than read from a
    per-item field."""

    provider_name = "massive_benzinga_news"

    def fetch_news(
        self,
        tickers: list[str],
        *,
        published_gte: datetime | None = None,
        limit: int = 50,
    ) -> list[NewsRow]:
        retrieved = datetime.now(UTC)
        out: list[NewsRow] = []
        for tk in [t.upper().strip() for t in tickers if t.strip()]:
            q = f"/benzinga/v2/news?tickers={tk}&order=desc&limit={min(limit, 100)}"
            for r in self._paginate(q):
                pub_at = _parse_dt(r.get("published"))
                if pub_at is None:
                    continue
                if published_gte is not None and pub_at < published_gte:
                    # results are strictly newest-first; once a page goes
                    # older than the cutoff, every later page will too.
                    break
                vid = str(r.get("benzinga_id") or r.get("url") or r.get("title", ""))
                images = r.get("images")
                image_url = str(images[0]) if isinstance(images, list) and images else ""
                channels = r.get("channels")
                category = str(channels[0]) if isinstance(channels, list) and channels else ""
                out.append(
                    NewsRow(
                        provider_id=vid,
                        dedupe_key=f"{self.provider_name}:{vid}",
                        headline=str(r.get("title", ""))[:400],
                        url=str(r.get("url", ""))[:600],
                        source="Benzinga",
                        author=str(r.get("author", ""))[:160],
                        published_at=pub_at,
                        retrieved_at=retrieved,
                        tickers=[str(x).upper() for x in (r.get("tickers") or [])][:40],
                        category=category[:60],
                        image_url=image_url[:600],
                        description=str(r.get("teaser", "")),
                        raw=r,
                    )
                )
        return _dedupe_newest_first(out)


def _dedupe_newest_first(rows: list[NewsRow]) -> list[NewsRow]:
    seen: set[str] = set()
    uniq: list[NewsRow] = []
    for row in sorted(rows, key=lambda x: x.published_at, reverse=True):
        if row.dedupe_key in seen:
            continue
        seen.add(row.dedupe_key)
        uniq.append(row)
    return uniq
