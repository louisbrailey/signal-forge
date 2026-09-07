"""Persist licensed news items with raw-audit metadata + dedupe.

Read-only. News is stored for display and for LLM *summaries* only; it never
creates, ranks, or alters a recommendation or risk decision (contract S12).
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from signalforge.data.adapters.base import AdapterError
from signalforge.data.adapters.massive_news import MassiveNewsAdapter
from signalforge.db.models import NewsItem
from signalforge.observability import get_logger

_log = get_logger("news.ingest")


@dataclass(slots=True)
class NewsIngestReport:
    fetched: int = 0
    written: int = 0
    duplicates: int = 0
    publishers: list[str] | None = None
    error: str | None = None


def ingest_news(
    session: Session,
    adapter: MassiveNewsAdapter,
    tickers: list[str],
    *,
    lookback_days: int = 3,
    limit: int = 50,
) -> NewsIngestReport:
    from datetime import UTC, datetime, timedelta

    report = NewsIngestReport()
    since = datetime.now(UTC) - timedelta(days=lookback_days)
    try:
        rows = adapter.fetch_news(tickers, published_gte=since, limit=limit)
    except AdapterError as exc:
        report.error = str(exc)
        _log.warning("news.fetch_failed", error=str(exc))
        return report

    report.fetched = len(rows)
    seen = {
        k
        for (k,) in session.execute(
            select(NewsItem.dedupe_key).where(
                NewsItem.dedupe_key.in_([r.dedupe_key for r in rows] or [""])
            )
        )
    }
    publishers: set[str] = set()
    for r in rows:
        publishers.add(r.source)
        if r.dedupe_key in seen:
            report.duplicates += 1
            continue
        seen.add(r.dedupe_key)
        session.add(
            NewsItem(
                headline=r.headline,
                url=r.url,
                published_at=r.published_at,
                retrieved_at=r.retrieved_at,
                source=r.source,
                provider=adapter.provider_name,
                provider_id=r.provider_id,
                dedupe_key=r.dedupe_key,
                author=r.author,
                category=r.category,
                image_url=r.image_url,
                instrument_symbols=r.tickers,
            )
        )
        report.written += 1
    session.flush()
    report.publishers = sorted(publishers)
    _log.info("news.ingest_done", fetched=report.fetched, written=report.written)
    return report
