"""Read-only dollar-target diagnostics from daily net-liquidation observations.

Never constructs historical equity from today's positions, promotes a strategy,
or estimates income by multiplying sequential trade R by hypothetical capital.
Input provenance is declared by the caller, not independently verified here.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

DAILY_TARGET = Decimal("1000")
WORKWEEK_TARGET = Decimal("5000")
WEEKEND_TARGET = Decimal("400")
ONE_DAY = timedelta(days=1)


class DailyMark(BaseModel):
    model_config = ConfigDict(extra="forbid")

    day: date
    net_liquidation_usd: Decimal = Field(ge=0, allow_inf_nan=False, decimal_places=2)
    external_flow_usd: Decimal = Field(allow_inf_nan=False, decimal_places=2)
    valuation_quality: Literal["complete", "stale", "missing"]


class IncomeEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data_kind: Literal["fixture", "backtest", "forward_paper"]
    source_reference: str = Field(min_length=1)
    strategy_version: str = Field(min_length=1)
    cost_model_reference: str = Field(min_length=1)
    costs_included: bool
    timezone: str
    weekend_market_access: bool
    opening_date: date
    opening_valuation_quality: Literal["complete", "stale", "missing"]
    opening_equity_usd: Decimal = Field(gt=0, allow_inf_nan=False, decimal_places=2)
    through_date: date
    observations: list[DailyMark]

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("timezone must be an IANA timezone name") from exc
        return value

    @model_validator(mode="after")
    def valid_panel(self) -> IncomeEvidence:
        span = (self.through_date - self.opening_date).days
        if not 1 <= span <= 36600:
            raise ValueError("observation window must be between 1 and 36600 calendar days")
        days = [row.day for row in self.observations]
        if len(set(days)) != len(days):
            raise ValueError("duplicate observation dates")
        if any(not self.opening_date < day <= self.through_date for day in days):
            raise ValueError("observations must lie after opening_date and through through_date")
        return self


def _money(value: Decimal) -> str:
    return f"{value:.2f}"


def _summary(values: list[Decimal], target: Decimal) -> dict[str, object]:
    count = len(values)
    hits = sum(value >= target for value in values)
    return {
        "target_usd": _money(target),
        "complete_periods": count,
        "target_hits": hits,
        "target_misses": count - hits,
        "observed_hit_fraction": hits / count if count else None,
        "mean_net_pnl_usd": _money(sum(values, Decimal(0)) / count) if count else None,
        "worst_net_pnl_usd": _money(min(values)) if count else None,
        "best_net_pnl_usd": _money(max(values)) if count else None,
        "loss_periods": sum(value < 0 for value in values),
        "zero_pnl_periods": sum(value == 0 for value in values),
    }


def assess_income_targets(evidence: IncomeEvidence) -> dict[str, object]:
    """Describe observed targets, not future reliability or deployment readiness.

    Every calendar day is required, including holidays/no-trade days. Missing or
    stale marks invalidate adjacent daily differences and any containing period.
    Weeks are Monday-Friday; weekends Saturday-Sunday, in the declared timezone.
    Net P&L includes realized AND unrealized value, not necessarily withdrawable cash.
    """
    dates = [
        evidence.opening_date + ONE_DAY * offset
        for offset in range(1, (evidence.through_date - evidence.opening_date).days + 1)
    ]
    marks = {row.day: row for row in evidence.observations}
    valid = {day: row for day, row in marks.items() if row.valuation_quality == "complete"}
    pnl: dict[date, Decimal] = {}
    if evidence.costs_included:
        for day in dates:
            row = valid.get(day)
            previous = valid.get(day - ONE_DAY)
            if row is None or (previous is None and day - ONE_DAY != evidence.opening_date):
                continue
            if previous is None and evidence.opening_valuation_quality != "complete":
                continue
            before = previous.net_liquidation_usd if previous else evidence.opening_equity_usd
            pnl[day] = row.net_liquidation_usd - before - row.external_flow_usd

    def periods(start_weekday: int, length: int, target: Decimal) -> dict[str, object]:
        values: list[Decimal] = []
        incomplete: list[str] = []
        boundary: list[str] = []
        starts = {
            day - ONE_DAY * ((day.weekday() - start_weekday) % 7)
            for day in dates
            if (day.weekday() - start_weekday) % 7 < length
        }
        for start in sorted(starts):
            days = [start + ONE_DAY * offset for offset in range(length)]
            if any(day <= evidence.opening_date or day > evidence.through_date for day in days):
                boundary.append(start.isoformat())
            elif not all(day in pnl for day in days):
                incomplete.append(start.isoformat())
            else:
                values.append(sum((pnl[day] for day in days), Decimal(0)))
        return {
            **_summary(values, target),
            "incomplete_period_starts": incomplete,
            "boundary_partial_period_starts": boundary,
        }

    panel_complete = len(pnl) == len(dates)
    drawdown_dollars: Decimal | None = None
    drawdown_pct: Decimal | None = None
    if panel_complete:
        wealth = peak = evidence.opening_equity_usd
        drawdown_dollars = drawdown_pct = Decimal(0)
        for day in dates:
            wealth += pnl[day]
            peak = max(peak, wealth)
            drawdown_dollars = max(drawdown_dollars, peak - wealth)
            drawdown_pct = max(drawdown_pct, (peak - wealth) / peak * 100)

    blockers = [
        "Historical or simulated observations cannot establish future reliable profit.",
        "Provenance, costs, market access, and valuation quality are declared, not audited.",
    ]
    if evidence.data_kind != "forward_paper":
        blockers.append("This is not prospective forward-paper evidence.")
    if not evidence.costs_included:
        blockers.append("Costs are not included; all net-profit target metrics are withheld.")
    if len(valid) != len(dates) or evidence.opening_valuation_quality != "complete":
        blockers.append("Incomplete/stale daily valuations; full-period P&L and drawdown withheld.")
    if not evidence.weekend_market_access:
        blockers.append("Weekend market access is not established; no weekend strategy claim.")

    return {
        "schema_version": "income-targets-v1",
        "reliability_status": "not_established",
        "automatic_trading_authorized": False,
        "provenance": evidence.model_dump(mode="json", exclude={"observations"}),
        "measurement": (
            "Cost-adjusted net-liquidation P&L, including unrealized marks; not cash income."
        ),
        "daily_pnl_formula": (
            "closing net liquidation - prior closing net liquidation - net external flow"
        ),
        "expected_calendar_days": len(dates),
        "usable_daily_changes": len(pnl),
        "missing_dates": [day.isoformat() for day in dates if day not in marks],
        "stale_or_missing_valuation_dates": [
            day.isoformat() for day in sorted(marks) if day not in valid
        ],
        "unassessable_daily_changes": [day.isoformat() for day in dates if day not in pnl],
        "full_period_net_pnl_usd": (
            _money(sum(pnl.values(), Decimal(0))) if panel_complete else None
        ),
        "cashflow_adjusted_drawdown_usd": (
            _money(drawdown_dollars) if drawdown_dollars is not None else None
        ),
        "cashflow_adjusted_drawdown_pct": (
            _money(drawdown_pct) if drawdown_pct is not None else None
        ),
        "calendar_days": _summary(list(pnl.values()), DAILY_TARGET),
        "weekday_days": _summary(
            [value for day, value in pnl.items() if day.weekday() < 5], DAILY_TARGET
        ),
        "workweeks": periods(0, 5, WORKWEEK_TARGET),
        "weekends": periods(5, 2, WEEKEND_TARGET),
        "daily_net_pnl_usd": {day.isoformat(): _money(value) for day, value in sorted(pnl.items())},
        "limitations": [
            *blockers,
            "Hit fractions are descriptive, not independent observations or confidence bounds.",
            "Daily closes miss intraday drawdowns and execution/liquidity risk.",
            "Cashflow-adjusted drawdown is fixed-base dollar wealth, not a time-weighted return.",
            "No compounding, leverage, strategy promotion, or extrapolated income is inferred.",
        ],
    }
