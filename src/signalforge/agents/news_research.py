"""News-research agent (read-only).

Splits the last 24 hours of ``NewsItem`` rows by provider (the dedicated
Benzinga feed vs every other licensed publisher), surfaces the latest
Benzinga entitlement check, and flags same-ticker "conflicts" — a ticker
mentioned by two or more distinct publishers in the window — with no
interpretation attached. News is never wired into any decision path
(import-linter contract S12): this agent only reports what showed up.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from signalforge.agents.base import ResearchAgent
from signalforge.db.models import EntitlementCheck, NewsItem

_WINDOW_HOURS = 24
_BENZINGA_PROVIDER = "massive_benzinga_news"
_BENZINGA_FEED = "benzinga_news"
_CONTEXT_ONLY_SENTENCE = "News is context only and cannot affect any trade decision."


def _item_dict(n: NewsItem) -> dict[str, Any]:
    return {
        "headline": n.headline,
        "publisher": n.source,
        "url": n.url,
        "published_at": n.published_at.isoformat(),
        "tickers": list(n.instrument_symbols or []),
        "provider": n.provider or "unknown",
        "source": n.provider or "unknown",
        "as_of": n.published_at.isoformat(),
    }


class NewsResearchAgent(ResearchAgent):
    name = "news_research"
    role = "News-research agent"
    allowed_inputs = (
        "signalforge.db.models.NewsItem (last 24h)",
        "signalforge.db.models.EntitlementCheck (feed=benzinga_news, latest)",
    )
    outputs = ("agent_report",)
    prohibited = (
        "trade decision",
        "candidate",
        "alert",
        "risk sizing",
        "setting change",
        "recommendation",
    )
    llm_narrative = True

    def collect(self, session: Session) -> dict[str, Any]:
        missing: list[str] = []
        now = datetime.now(UTC)
        start = now - timedelta(hours=_WINDOW_HOURS)

        rows = list(
            session.scalars(
                select(NewsItem)
                .where(NewsItem.published_at >= start, NewsItem.published_at <= now)
                .order_by(NewsItem.published_at.desc())
            )
        )
        benzinga_items = [_item_dict(n) for n in rows if n.provider == _BENZINGA_PROVIDER]
        generic_items = [_item_dict(n) for n in rows if n.provider != _BENZINGA_PROVIDER]

        if not rows:
            missing.append(f"no news items in the last {_WINDOW_HOURS} hours")

        entitlement_row = session.scalar(
            select(EntitlementCheck)
            .where(EntitlementCheck.feed == _BENZINGA_FEED)
            .order_by(EntitlementCheck.checked_at.desc())
            .limit(1)
        )
        entitlement: dict[str, Any] | None
        if entitlement_row is None:
            entitlement = None
            missing.append("no Benzinga entitlement check recorded")
        else:
            entitlement = {
                "feed": entitlement_row.feed,
                "available": entitlement_row.available,
                "detail": entitlement_row.detail,
                "checked_at": entitlement_row.checked_at.isoformat(),
            }
            if not entitlement_row.available:
                if (entitlement_row.detail or "").startswith("STALE"):
                    missing.append(f"Benzinga feed stale: {entitlement_row.detail}")
                else:
                    missing.append(
                        f"Benzinga feed unavailable: {entitlement_row.detail or 'not entitled'}"
                    )
            elif not benzinga_items:
                missing.append(
                    "Benzinga entitlement available but no Benzinga-provider items in the "
                    f"last {_WINDOW_HOURS} hours"
                )

        ticker_publishers: dict[str, set[str]] = defaultdict(set)
        ticker_headlines: dict[str, list[str]] = defaultdict(list)
        for item in [*benzinga_items, *generic_items]:
            for ticker in item["tickers"]:
                ticker_publishers[ticker].add(item["publisher"])
                ticker_headlines[ticker].append(item["headline"])
        conflicts = [
            {
                "ticker": ticker,
                "publishers": sorted(publishers),
                "headlines": ticker_headlines[ticker],
            }
            for ticker, publishers in sorted(ticker_publishers.items())
            if len(publishers) >= 2
        ]

        return {
            "source": "news_item + entitlement_check",
            "as_of": now.isoformat(),
            "window": {
                "start": start.isoformat(),
                "end": now.isoformat(),
                "hours": _WINDOW_HOURS,
            },
            "benzinga_items": benzinga_items,
            "generic_items": generic_items,
            "entitlement": entitlement,
            "conflicts": conflicts,
            "missing_data": missing,
        }

    def citations(self, evidence: dict[str, Any]) -> list[dict[str, Any]]:
        items = [*evidence.get("benzinga_items", []), *evidence.get("generic_items", [])]
        return [
            {
                "headline": i["headline"],
                "publisher": i["publisher"],
                "url": i["url"],
                "published_at": i["published_at"],
            }
            for i in items
        ]

    def summarize(self, evidence: dict[str, Any]) -> str:
        bz = evidence.get("benzinga_items", [])
        gen = evidence.get("generic_items", [])
        entitlement = evidence.get("entitlement")
        conflicts = evidence.get("conflicts", [])
        window = evidence["window"]

        lines = [
            f"News window: last {window['hours']} hours.",
            f"Benzinga-provider items: {len(bz)}. Generic-provider items: {len(gen)}.",
        ]
        if bz:
            publishers = sorted({i["publisher"] for i in bz})
            lines.append("Benzinga publishers seen: " + ", ".join(publishers) + ".")
        if gen:
            publishers = sorted({i["publisher"] for i in gen})
            lines.append("Generic publishers seen: " + ", ".join(publishers) + ".")

        if entitlement is None:
            lines.append("Benzinga entitlement has not been checked.")
        elif entitlement["available"]:
            lines.append(
                f"Benzinga entitlement is available (checked {entitlement['checked_at']})."
            )
        else:
            lines.append(
                f"Benzinga entitlement is unavailable (checked {entitlement['checked_at']}): "
                f"{entitlement['detail'] or 'no detail recorded'}."
            )

        if conflicts:
            parts = [f"{c['ticker']} ({len(c['publishers'])} publishers)" for c in conflicts]
            lines.append(
                "Tickers reported by multiple publishers in this window: " + ", ".join(parts) + "."
            )
        else:
            lines.append("No ticker was reported by multiple publishers in this window.")

        lines.append(_CONTEXT_ONLY_SENTENCE)
        return " ".join(lines)
