"""Freshness gate (invariant S8).

Before a scan uses an instrument, and before any live alert fires, every required
feed must have succeeded within the horizon's freshness budget and must not be
rate-limited. Otherwise the instrument/horizon is marked stale, excluded from
candidates, and live alerts for that horizon are disabled.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from signalforge.config import get_settings
from signalforge.data.adapters.base import FeedType
from signalforge.db.models import DataFeedStatus
from signalforge.db.types import utcnow
from signalforge.domain import Horizon


@dataclass
class FreshnessResult:
    fresh: bool
    reasons: list[str] = field(default_factory=list)
    per_feed: dict[str, dict[str, object]] = field(default_factory=dict)

    def as_dict(self) -> dict[str, object]:
        return {"fresh": self.fresh, "reasons": self.reasons, "per_feed": self.per_feed}


def check_feeds_fresh(
    session: Session,
    required: list[tuple[str, FeedType]],
    budget: timedelta,
) -> FreshnessResult:
    now = utcnow()
    result = FreshnessResult(fresh=True)
    for provider, feed_type in required:
        row = session.scalar(
            select(DataFeedStatus).where(
                DataFeedStatus.provider == provider,
                DataFeedStatus.feed_type == feed_type,
            )
        )
        key = f"{provider}:{feed_type.value}"
        if row is None or row.last_success_at is None:
            result.fresh = False
            result.reasons.append(f"{key}: no successful fetch on record")
            result.per_feed[key] = {"status": "missing"}
            continue
        age = now - row.last_success_at
        rate_limited = row.rate_limited_until is not None and row.rate_limited_until > now
        entry: dict[str, object] = {
            "age_seconds": age.total_seconds(),
            "budget_seconds": budget.total_seconds(),
            "rate_limited": rate_limited,
            "latency_category": row.latency_category.value,
        }
        if age > budget:
            result.fresh = False
            result.reasons.append(
                f"{key}: stale ({int(age.total_seconds())}s old > "
                f"{int(budget.total_seconds())}s budget)"
            )
            entry["status"] = "stale"
        elif rate_limited:
            result.fresh = False
            result.reasons.append(f"{key}: rate-limited until {row.rate_limited_until}")
            entry["status"] = "rate_limited"
        else:
            entry["status"] = "fresh"
        result.per_feed[key] = entry
    return result


def gate_for_horizon(
    session: Session,
    horizon: Horizon,
    required: list[tuple[str, FeedType]],
) -> FreshnessResult:
    budget_minutes = get_settings().research.data_quality.freshness_budget_minutes[horizon]
    return check_feeds_fresh(session, required, timedelta(minutes=budget_minutes))
