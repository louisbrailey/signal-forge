"""Descriptive funded-replay diagnostics; no parameter selection or promotion.

XNYS closures carry the previous modeled liquidation value, explicitly. This
valuation convention does not turn closed markets into tradable weekend income.
"""

from __future__ import annotations

from collections import Counter
from datetime import date, timedelta
from decimal import ROUND_CEILING, Decimal
from typing import Any

from signalforge.backtest.costs import CostModel
from signalforge.backtest.funded import FundedReplay, money, sell_price
from signalforge.data.calendar import sessions
from signalforge.data.series import PriceSeries
from signalforge.research.income_targets import DailyMark, IncomeEvidence, assess_income_targets


def diagnose(
    result: FundedReplay,
    *,
    start: date,
    end: date,
    initial_cash: Decimal,
    source_reference: str,
    strategy_version: str,
    cost_model_reference: str,
) -> dict[str, Any]:
    """Require every session; fill only known exchange closures, never a data gap."""
    expected = tuple(sessions(start, end))
    if not expected or tuple(date.fromisoformat(m["day"]) for m in result.marks) != expected:
        raise ValueError("Complete ordered session marks required")
    marks = {date.fromisoformat(m["day"]): m for m in result.marks}
    value = initial_cash
    observations = []
    carried = []
    for offset in range((end - start).days + 1):
        day = start + timedelta(days=offset)
        if day in marks:
            value = Decimal(marks[day]["net_liquidation_usd"])
        else:
            carried.append(str(day))
        observations.append(
            DailyMark(
                day=day,
                net_liquidation_usd=value,
                external_flow_usd=Decimal(0),
                valuation_quality="complete",
            )
        )
    evidence = IncomeEvidence(
        data_kind="backtest",
        source_reference=source_reference,
        strategy_version=strategy_version,
        cost_model_reference=cost_model_reference,
        costs_included=True,
        timezone="America/New_York",
        weekend_market_access=False,
        opening_date=start - timedelta(days=1),
        opening_valuation_quality="complete",
        opening_equity_usd=initial_cash,
        through_date=end,
        observations=observations,
    )
    buys: dict[str, dict[str, Any]] = {}
    pnl_by_symbol: dict[str, Decimal] = {}
    pnl = []
    for fill in result.fills:
        symbol = fill["symbol"]
        if fill["side"] == "buy":
            if symbol in buys:
                raise ValueError("Duplicate unmatched entry")
            buys[symbol] = fill
        elif fill["side"] == "sell":
            buy = buys.pop(symbol, None)
            if buy is None or buy["shares"] != fill["shares"]:
                raise ValueError("Unmatched round trip")
            net = (
                (Decimal(fill["price"]) - Decimal(buy["price"])) * fill["shares"]
                - Decimal(fill["commission"])
                - Decimal(buy["commission"])
            )
            pnl.append(net)
            pnl_by_symbol[symbol] = pnl_by_symbol.get(symbol, Decimal(0)) + net
        else:
            raise ValueError("Unknown fill side")
    if (
        buys
        or result.marks[-1]["open_positions"] != 0
        or any(m["open_positions"] < 0 for m in result.marks)
    ):
        raise ValueError("Terminal liquidation required")
    net = value - initial_cash
    if sum(pnl, Decimal(0)) != net:
        raise ValueError("Round trips do not reconcile to terminal cash")
    exposures = [
        float(Decimal(m["gross_exposure_usd"]) / Decimal(m["net_liquidation_usd"]))
        for m in result.marks
        if Decimal(m["net_liquidation_usd"]) > 0
    ]
    losses = -sum((p for p in pnl if p < 0), Decimal(0))
    gains = sum((p for p in pnl if p > 0), Decimal(0))
    return {
        "income_targets": assess_income_targets(evidence),
        "calendar_evidence": evidence.model_dump(mode="json"),
        "closed_market_carry_dates": carried,
        "valuation_policy": "Carry prior mark only on XNYS closures; no weekend trades.",
        "net_return_pct": float(net / initial_cash * 100),
        "annualized_return_pct": float(
            ((value / initial_cash) ** (Decimal("365.25") / len(observations)) - 1) * 100
        ),
        "closed_trades": len(pnl),
        "hit_rate": sum(p > 0 for p in pnl) / len(pnl) if pnl else None,
        "profit_factor": float(gains / losses) if losses else None,
        "average_session_exposure_pct": (
            sum(exposures) / len(exposures) * 100 if exposures else None
        ),
        "maximum_session_exposure_pct": max(exposures) * 100 if exposures else None,
        "modeled_costs_usd": str(result.costs),
        "rejection_counts": dict(
            Counter(d["reason"] for d in result.decisions if d["status"] == "rejected")
        ),
        "net_pnl_by_symbol_usd": {s: str(v) for s, v in sorted(pnl_by_symbol.items())},
        "best_trade_net_pnl_usd": str(max(pnl)) if pnl else None,
        "net_pnl_excluding_best_trade_usd": str(net - max(pnl)) if pnl else None,
        "disclaimer": "Research signal only — no order was placed.",
    }


def passive_comparator(
    series: dict[str, PriceSeries],
    sectors: dict[str, str],
    *,
    initial_cash: Decimal,
    cost_model: CostModel,
    spread_bps: float,
) -> dict[str, Any]:
    """5%-per-name/20%-per-sector/60%-total buy/hold reference with cash.

    Same capital, dates and cost assumptions. No stop or open-risk cap: this is
    a different risk profile, explicitly not a strategy replacement.
    Caller supplies the same validated complete calendar as the funded engine.
    """
    cash = initial_cash
    sector_spent: dict[str, Decimal] = {}
    positions = {}
    fees = Decimal(0)
    penalty = (
        cost_model.slippage_bps + (spread_bps / 2 if cost_model.half_spread_fill_penalty else 0)
    ) / 10000
    for symbol in sorted(series):
        bars = series[symbol]
        buy = Decimal(str(float(bars.open[0]) * (1 + penalty))).quantize(
            Decimal("0.01"), rounding=ROUND_CEILING
        )
        sector = sectors[symbol]
        budget = min(
            initial_cash * Decimal("0.05"),
            cash,
            initial_cash * Decimal("0.60") - (initial_cash - cash),
            initial_cash * Decimal("0.20") - sector_spent.get(sector, Decimal(0)),
        )
        shares = int(max(Decimal(0), budget) / buy)
        while shares and buy * shares + money(cost_model.commission(shares)) > budget:
            shares -= 1
        if not shares:
            continue
        fee = money(cost_model.commission(shares))
        spend = buy * shares + fee
        cash -= spend
        sector_spent[sector] = sector_spent.get(sector, Decimal(0)) + spend
        fees += money((float(buy) - float(bars.open[0])) * shares) + fee
        positions[symbol] = shares
    cash_after_entry = cash
    for symbol, shares in positions.items():
        raw = float(series[symbol].close[-1])
        price = sell_price(raw, penalty)
        fee = money(cost_model.commission(shares))
        cash += price * shares - fee
        fees += money((raw - float(price)) * shares) + fee
    return {
        "label": "5% name/20% sector/60% total passive reference; no stops or dividends",
        "final_cash_usd": str(cash),
        "net_pnl_usd": str(cash - initial_cash),
        "modeled_costs_usd": str(fees),
        "shares_by_symbol": positions,
        "cash_after_entry_usd": str(cash_after_entry),
        "limitations": "Different risk profile; no dividends, rebalancing or promotion.",
    }
