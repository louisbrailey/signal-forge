"""Shared vocabulary: cross-cutting enums with zero internal dependencies.

Every layer may import this module. Modules that historically defined these
enums re-export them from here so existing imports keep working.
"""

from __future__ import annotations

from enum import StrEnum


class Horizon(StrEnum):
    """Independent research horizons — never blended into one score."""

    INTRADAY = "INTRADAY"  # ~1h to close  (Phase 2)
    SHORT_SWING = "SHORT_SWING"  # 2-10 trading days
    MEDIUM_SWING = "MEDIUM_SWING"  # 2-8 weeks
    POSITION = "POSITION"  # 2-6 months


class Direction(StrEnum):
    LONG = "LONG"
    SHORT = "SHORT"
    AVOID = "AVOID"


class StrategyStatus(StrEnum):
    EXPERIMENTAL = "experimental"  # runs in paper only; never alerts
    PAPER_APPROVED = "paper_approved"  # alert-eligible
    DISABLED = "disabled"


class LatencyCategory(StrEnum):
    REALTIME = "REALTIME"
    DELAYED = "DELAYED"
    END_OF_DAY = "END_OF_DAY"
    HISTORICAL = "HISTORICAL"

    @property
    def is_live(self) -> bool:
        """Only a confirmed real-time entitlement may be labelled 'live'."""
        return self is LatencyCategory.REALTIME


class FeedType(StrEnum):
    QUOTE = "QUOTE"
    BAR_INTRADAY = "BAR_INTRADAY"
    BAR_DAILY = "BAR_DAILY"
    CORP_ACTION = "CORP_ACTION"
    EARNINGS_CAL = "EARNINGS_CAL"
    ECON_CAL = "ECON_CAL"
    NEWS = "NEWS"
    FUNDAMENTALS = "FUNDAMENTALS"
    SHORT_INTEREST = "SHORT_INTEREST"
    OPTIONS_CHAIN = "OPTIONS_CHAIN"


class DataQualityFlag(StrEnum):
    MISSING_VALUES = "missing_values"
    STALE_FEED = "stale_feed"
    SPLIT_UNCERTAINTY = "split_uncertainty"
    VENDOR_MISMATCH = "vendor_mismatch"
    RATE_LIMITED = "rate_limited"
    HOLIDAY_OR_CLOSED = "holiday_or_closed"
    RECONCILIATION_DISAGREEMENT = "reconciliation_disagreement"


class QualityGate(StrEnum):
    """Outcome of the per-candidate quality gates (ARCHITECTURE.md §6.4)."""

    PASSED = "PASSED"
    NO_TRADE = "NO_TRADE"


class PaperDecision(StrEnum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    IGNORED = "ignored"
    WATCH = "watch"


class PositionSide(StrEnum):
    LONG = "long"
    SHORT = "short"


class AlertType(StrEnum):
    CANDIDATE = "candidate"
    DAILY_BRIEFING = "daily_briefing"
    SYSTEM_HEALTH = "system_health"  # DB unreachable, a scheduled job raised
    DATA_ISSUE = "data_issue"  # stale feed, or a recent ingestion run failed/partial


class AlertChannel(StrEnum):
    LOCAL = "local"
    EMAIL = "email"
    DISCORD = "discord"
    SLACK = "slack"


class AlertStatus(StrEnum):
    SENT = "sent"
    SUPPRESSED = "suppressed"
    FAILED = "failed"
