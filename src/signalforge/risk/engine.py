"""Position sizing + portfolio-limit enforcement (ARCHITECTURE.md §7.4).

Size comes from ``per_trade_risk_pct`` and the entry-to-stop distance, then is
capped by concentration / exposure / correlated-exposure / daily-risk limits. If
the trade cannot be honoured within every limit the result carries a
``rejected_reason`` and the candidate becomes NO TRADE.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from signalforge.config.research import RiskLimits


def _shares_within(budget: float, per_unit: float) -> int:
    """Largest integer ``n`` with ``n * per_unit <= budget`` (FP-safe)."""
    n = math.floor(budget / per_unit)
    while n > 0 and n * per_unit > budget:  # correct a float floor overshoot
        n -= 1
    return n


@dataclass(frozen=True, slots=True)
class SizingRequest:
    symbol: str
    sector: str
    entry_price: float
    stop_price: float
    account_equity: float


@dataclass(frozen=True, slots=True)
class OpenExposure:
    """Snapshot of current open paper positions for limit checks."""

    gross_dollars: float = 0.0
    open_risk_dollars: float = 0.0  # sum of remaining risk-to-stop
    by_sector_dollars: dict[str, float] = field(default_factory=dict)
    position_count: int = 0


@dataclass(frozen=True, slots=True)
class SizingResult:
    shares: int
    notional: float
    risk_dollars: float
    risk_pct_of_account: float
    rejected: bool = False
    rejected_reason: str | None = None
    checks: dict[str, str] = field(default_factory=dict)

    @classmethod
    def reject(cls, reason: str, checks: dict[str, str]) -> SizingResult:
        return cls(0, 0.0, 0.0, 0.0, rejected=True, rejected_reason=reason, checks=checks)


def size_position(
    request: SizingRequest,
    limits: RiskLimits,
    exposure: OpenExposure | None = None,
) -> SizingResult:
    exp = exposure or OpenExposure()
    checks: dict[str, str] = {}
    equity = request.account_equity
    if equity <= 0:
        return SizingResult.reject("account_equity must be positive", checks)

    per_share_risk = abs(request.entry_price - request.stop_price)
    if per_share_risk <= 0:
        return SizingResult.reject("entry and stop are equal", checks)

    risk_budget = equity * (limits.per_trade_risk_pct / 100.0)
    shares = _shares_within(risk_budget, per_share_risk)
    if shares < 1:
        return SizingResult.reject("per-trade risk budget too small for one share", checks)

    notional = shares * request.entry_price
    risk_dollars = shares * per_share_risk
    risk_pct = risk_dollars / equity * 100.0

    # --- concentration: single position notional ---
    conc_cap = equity * (limits.max_position_concentration_pct / 100.0)
    if notional > conc_cap:
        shares = _shares_within(conc_cap, request.entry_price)
        if shares < 1:
            return SizingResult.reject("position concentration cap below one share", checks)
        notional = shares * request.entry_price
        risk_dollars = shares * per_share_risk
        risk_pct = risk_dollars / equity * 100.0
        checks["concentration"] = f"trimmed to {limits.max_position_concentration_pct}% of equity"
    else:
        checks["concentration"] = "ok"

    # --- total portfolio exposure ---
    expo_cap = equity * (limits.max_portfolio_exposure_pct / 100.0)
    if exp.gross_dollars + notional > expo_cap:
        return SizingResult.reject(
            f"max portfolio exposure {limits.max_portfolio_exposure_pct}% would be exceeded",
            checks,
        )
    checks["portfolio_exposure"] = "ok"

    # --- correlated (sector) exposure ---
    corr_cap = equity * (limits.max_correlated_exposure_pct / 100.0)
    sector_now = exp.by_sector_dollars.get(request.sector, 0.0)
    if sector_now + notional > corr_cap:
        return SizingResult.reject(
            f"max correlated exposure {limits.max_correlated_exposure_pct}% for sector "
            f"{request.sector!r} would be exceeded",
            checks,
        )
    checks["correlated_exposure"] = "ok"

    # --- daily portfolio risk ---
    daily_cap = equity * (limits.max_daily_portfolio_risk_pct / 100.0)
    if exp.open_risk_dollars + risk_dollars > daily_cap:
        return SizingResult.reject(
            f"max daily portfolio risk {limits.max_daily_portfolio_risk_pct}% would be exceeded",
            checks,
        )
    checks["daily_risk"] = "ok"

    return SizingResult(
        shares=shares,
        notional=round(notional, 2),
        risk_dollars=round(risk_dollars, 2),
        risk_pct_of_account=round(risk_pct, 4),
        checks=checks,
    )
