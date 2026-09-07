"""Read-only licensed news adapter (Benzinga / publisher feed via Massive).

Read-only: no posting, no scraping of article bodies beyond the licensed
``description`` the API returns, no LLM here. Callers persist raw audit metadata,
deduplicate by the vendor id, and keep the source link. News never creates,
ranks, alters, or overrides a trading recommendation (import-linter contract S12).

The API key travels only in the Authorization header and is scrubbed from errors.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

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


def _parse_dt(s: Any) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None


class MassiveNewsAdapter:
    provider_name = "massive_news"

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
                vid = str(r.get("id") or r.get("article_url") or r.get("title", ""))
                publisher = (r.get("publisher") or {}).get("name", "") or "unknown"
                out.append(
                    NewsRow(
                        provider_id=vid,
                        dedupe_key=f"{self.provider_name}:{vid}",
                        headline=str(r.get("title", ""))[:400],
                        url=str(r.get("article_url", ""))[:600],
                        source=str(publisher)[:60],
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
        # newest first, de-duplicated within this fetch
        seen: set[str] = set()
        uniq: list[NewsRow] = []
        for row in sorted(out, key=lambda x: x.published_at, reverse=True):
            if row.dedupe_key in seen:
                continue
            seen.add(row.dedupe_key)
            uniq.append(row)
        return uniq
