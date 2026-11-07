"""Decimal share sizing and settlement for the offline R2 replay overlay."""

from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_EVEN, Decimal

from signalforge.backtest.costs import CostModel
from signalforge.config.research import RiskLimits

SHARE_STEP = Decimal("0.001")
CENT = Decimal("0.01")
ZERO = Decimal(0)


def settle(price: Decimal, shares: Decimal, *, buy: bool) -> Decimal:
    return (price * shares).quantize(CENT, rounding=ROUND_CEILING if buy else ROUND_FLOOR)


def commission(costs: CostModel, shares: Decimal) -> Decimal:
    return max(
        shares * Decimal(str(costs.commission_per_share)),
        Decimal(str(costs.commission_min_per_order)),
    ).quantize(CENT, rounding=ROUND_HALF_EVEN)


def stop_risk(price: Decimal, stop_fill: Decimal, shares: Decimal, fees: Decimal) -> Decimal:
    # Rounded buy and sell settlements can add less than one cent on each side.
    # The bound is monotone in quantity, so cash/risk trimming can bisect lots.
    return max(ZERO, price - stop_fill) * shares + fees + 2 * CENT


def size_fractional(
    *,
    fill: Decimal,
    stop: Decimal,
    stop_fill: Decimal,
    equity: Decimal,
    cash: Decimal,
    gross: Decimal,
    sector: Decimal,
    open_risk: Decimal,
    volume_cap: Decimal,
    limits: RiskLimits,
    costs: CostModel,
) -> tuple[Decimal, str | None]:
    if equity <= 0:
        return ZERO, "account_equity must be positive"

    risk_per_share = fill - stop
    trade_budget = equity * Decimal(str(limits.per_trade_risk_pct)) / 100
    position_cap = equity * Decimal(str(limits.max_position_concentration_pct)) / 100
    risk_lots = int(trade_budget / risk_per_share / SHARE_STEP)
    if risk_lots == 0:
        return ZERO, "per_trade_risk_below_one_lot"

    # A rounded purchase debit must fit inside the position limit.
    position_lots = int(position_cap.quantize(CENT, rounding=ROUND_FLOOR) / fill / SHARE_STEP)
    lots = min(risk_lots, position_lots)
    if lots == 0:
        return ZERO, "position_cap_below_one_lot"

    shares = lots * SHARE_STEP
    debit = settle(fill, shares, buy=True)
    daily_budget = equity * Decimal(str(limits.max_daily_portfolio_risk_pct)) / 100
    if gross + debit > equity * Decimal(str(limits.max_portfolio_exposure_pct)) / 100:
        return ZERO, "portfolio_exposure_cap"
    if sector + debit > equity * Decimal(str(limits.max_correlated_exposure_pct)) / 100:
        return ZERO, "sector_exposure_cap"
    if open_risk + risk_per_share * shares > daily_budget:
        return ZERO, "aggregate_risk_cap"

    high = min(lots, int(volume_cap / SHARE_STEP))
    if high == 0:
        return ZERO, "volume_cap_below_one_lot"

    risk_budget = min(trade_budget, daily_budget - open_risk)
    low = 0
    while low < high:
        middle = (low + high + 1) // 2
        shares = middle * SHARE_STEP
        fee = commission(costs, shares)
        if (
            settle(fill, shares, buy=True) + fee <= cash
            and stop_risk(fill, stop_fill, shares, 2 * fee) <= risk_budget
        ):
            low = middle
        else:
            high = middle - 1
    return (low * SHARE_STEP, None) if low else (ZERO, "cash_or_open_risk")
