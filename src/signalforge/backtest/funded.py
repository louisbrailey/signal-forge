"""Offline long-only daily portfolio replay; no account, provider or study I/O.

Input series must share a complete XNYS calendar and already have validated
adjustments/provenance. Conservative fixed spread assumptions are not NBBO.
Signals are evaluated at close, pending entries fill next open. Intrabar exit
proceeds cannot fund that morning's entries. Output contains no income forecast.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from typing import Any

from signalforge.backtest.costs import CostModel
from signalforge.backtest.engine import EntrySignal, SignalFn
from signalforge.config.research import RiskLimits
from signalforge.data.calendar import sessions
from signalforge.data.series import PriceSeries
from signalforge.domain import Direction
from signalforge.risk.engine import OpenExposure, SizingRequest, size_position


def money(value: float | Decimal) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"))


def sell_price(raw: float, penalty: float) -> Decimal:
    return Decimal(str(raw * (1 - penalty))).quantize(Decimal("0.01"), rounding=ROUND_FLOOR)


@dataclass
class Position:
    shares: int
    entry: Decimal
    signal: EntrySignal
    entry_index: int
    entry_fee: Decimal


@dataclass
class FundedReplay:
    marks: list[dict[str, Any]] = field(default_factory=list)
    decisions: list[dict[str, Any]] = field(default_factory=list)
    fills: list[dict[str, Any]] = field(default_factory=list)
    costs: Decimal = Decimal(0)


def run_funded_replay(
    series: dict[str, PriceSeries],
    signals: dict[str, SignalFn],
    sectors: dict[str, str],
    *,
    limits: RiskLimits,
    cost_model: CostModel | None = None,
    initial_cash: Decimal = Decimal("10000"),
    spread_bps: float = 5.0,
    warmup: int = 50,
    max_volume_participation: float = 0.01,
) -> FundedReplay:
    """Deterministic alphabetic admission order; shared cash, no leverage.

    Does not promote strategies or independently verify an input dataset's
    provenance, dividends, survivorship, earnings or corporate-action history.
    No implicit truncation to an intersection of available dates is permitted.
    """
    if not series or set(signals) != set(series):
        raise ValueError("Each instrument requires a signal function")
    if not initial_cash.is_finite() or initial_cash <= 0 or warmup < 0:
        raise ValueError("Invalid cash or warmup")
    if not math.isfinite(max_volume_participation) or not 0 < max_volume_participation <= 1:
        raise ValueError("Invalid volume participation")
    cm = cost_model or CostModel()
    if any(
        not math.isfinite(x) or x < 0
        for x in (spread_bps, cm.slippage_bps, cm.commission_per_share, cm.commission_min_per_order)
    ):
        raise ValueError("Costs must be finite and nonnegative")
    keys = sorted(series)
    dates = series[keys[0]].dates
    if not dates or any(type(d) is not date for d in dates):
        raise ValueError("Daily session dates required")
    if tuple(sessions(dates[0], dates[-1])) != dates:
        raise ValueError("Missing, duplicate or unordered exchange sessions")
    for symbol, bars in series.items():
        if bars.symbol != symbol or bars.dates != dates:
            raise ValueError("Series must use identical complete calendars")
        if symbol not in sectors or not sectors[symbol]:
            raise ValueError("Explicit sector metadata required")
        for i in range(len(bars)):
            o, h, lo, c, v = (
                float(a[i]) for a in (bars.open, bars.high, bars.low, bars.close, bars.volume)
            )
            if (
                not all(math.isfinite(x) for x in (o, h, lo, c, v))
                or not 0 < lo <= min(o, c) <= max(o, c) <= h
                or v < 0
            ):
                raise ValueError("Invalid OHLCV")
    # Research-only conservative ceiling; stricter caller limits remain effective.
    limits = limits.model_copy(
        update={
            "max_position_concentration_pct": min(limits.max_position_concentration_pct, 5.0),
            "max_correlated_exposure_pct": min(limits.max_correlated_exposure_pct, 20.0),
            "max_portfolio_exposure_pct": min(limits.max_portfolio_exposure_pct, 100.0),
        }
    )
    cash = money(initial_cash)
    positions: dict[str, Position] = {}
    pending: dict[str, EntrySignal] = {}
    result = FundedReplay()
    penalty = (cm.slippage_bps + (spread_bps / 2 if cm.half_spread_fill_penalty else 0)) / 10000

    def sell(symbol: str, i: int, raw: float, reason: str) -> None:
        nonlocal cash
        p = positions.pop(symbol)
        fill = Decimal(str(raw * (1 - penalty))).quantize(Decimal("0.01"), rounding=ROUND_FLOOR)
        fee = money(cm.commission(p.shares))
        cash += fill * p.shares - fee
        result.costs += money(abs(raw - float(fill)) * p.shares) + fee
        result.fills.append(
            {
                "day": str(dates[i]),
                "symbol": symbol,
                "side": "sell",
                "shares": p.shares,
                "price": str(fill),
                "commission": str(fee),
                "reason": reason,
            }
        )

    for i, day in enumerate(dates):
        # Only known opening gaps may free cash before other opening entries.
        for symbol in list(positions):
            p = positions[symbol]
            o = float(series[symbol].open[i])
            if o <= p.signal.stop_price:
                sell(symbol, i, o, "gap_stop")
        for symbol, sig in sorted(pending.items()):
            if symbol in positions:
                continue
            raw = float(series[symbol].open[i])
            fill = Decimal(str(raw * (1 + penalty))).quantize(
                Decimal("0.01"), rounding=ROUND_CEILING
            )
            reason = None
            if (
                not math.isfinite(sig.stop_price)
                or sig.stop_price <= 0
                or sig.stop_price >= float(fill)
            ):
                reason = "invalid_or_crossed_stop"
            elif sig.target_price is not None and (
                not math.isfinite(sig.target_price)
                or (sig.target_price - float(fill)) / (float(fill) - sig.stop_price)
                < limits.min_reward_to_risk
            ):
                reason = "reward_risk"
            if reason:
                result.decisions.append(
                    {
                        "day": str(day),
                        "symbol": symbol,
                        "status": "rejected",
                        "reason": reason,
                        "shares": 0,
                    }
                )
                continue
            marks = {s: float(series[s].open[i]) for s in positions}
            gross = sum(positions[s].shares * marks[s] for s in positions)
            equity = float(cash) + gross
            sector_totals: dict[str, float] = {}
            risk = 0.0
            for s, p in positions.items():
                sector_totals[sectors[s]] = sector_totals.get(sectors[s], 0) + p.shares * marks[s]
                risk += (
                    p.shares
                    * max(
                        0.0,
                        max(float(p.entry), marks[s])
                        - float(sell_price(p.signal.stop_price, penalty)),
                    )
                    + float(p.entry_fee)
                    + cm.commission(p.shares)
                )
            sized = size_position(
                SizingRequest(symbol, sectors[symbol], float(fill), sig.stop_price, equity),
                limits,
                OpenExposure(gross, risk, sector_totals, len(positions)),
            )
            shares = min(
                sized.shares,
                math.floor(float(series[symbol].volume[i - 1]) * max_volume_participation),
            )
            if sized.rejected:
                reason = reason or sized.rejected_reason
            # Includes commissions in both affordability and total open risk.
            while shares > 0 and (
                fill * shares + money(cm.commission(shares)) > cash
                or (float(fill) - float(sell_price(sig.stop_price, penalty))) * shares
                + 2 * cm.commission(shares)
                > min(
                    equity * limits.per_trade_risk_pct / 100,
                    equity * limits.max_daily_portfolio_risk_pct / 100 - risk,
                )
            ):
                shares -= 1
            if shares < 1:
                reason = reason or "cash_or_open_risk"
            result.decisions.append(
                {
                    "day": str(day),
                    "symbol": symbol,
                    "status": "rejected" if reason else "accepted",
                    "reason": reason,
                    "shares": 0 if reason else shares,
                    "signal_day": str(dates[i - 1]),
                }
            )
            if reason:
                continue
            fee = money(cm.commission(shares))
            cash -= fill * shares + fee
            result.costs += money(abs(float(fill) - raw) * shares) + fee
            positions[symbol] = Position(shares, fill, sig, i, fee)
            result.fills.append(
                {
                    "day": str(day),
                    "symbol": symbol,
                    "side": "buy",
                    "shares": shares,
                    "price": str(fill),
                    "commission": str(fee),
                }
            )
        pending = {}
        # Stop before target; end-of-window liquidation includes costs.
        for symbol in list(positions):
            p = positions[symbol]
            bars = series[symbol]
            raw_exit: float | None = None
            why = ""
            if bars.low[i] <= p.signal.stop_price:
                raw_exit, why = p.signal.stop_price, "stop"
            elif p.signal.target_price is not None and bars.high[i] >= p.signal.target_price:
                raw_exit, why = p.signal.target_price, "target"
            elif i - p.entry_index >= p.signal.time_stop_bars:
                raw_exit, why = float(bars.close[i]), "time_stop"
            elif i == len(dates) - 1:
                raw_exit, why = float(bars.close[i]), "end_of_data"
            if raw_exit is not None:
                sell(symbol, i, raw_exit, why)
        liquidation = cash
        gross_close = Decimal(0)
        for symbol, p in positions.items():
            raw = float(series[symbol].close[i])
            gross_close += money(raw) * p.shares
            liquidation += sell_price(raw, penalty) * p.shares - money(cm.commission(p.shares))
        result.marks.append(
            {
                "day": str(day),
                "cash_usd": str(cash),
                "gross_exposure_usd": str(gross_close),
                "net_liquidation_usd": str(liquidation),
                "open_positions": len(positions),
            }
        )
        if i >= warmup and i < len(dates) - 1:
            for symbol in keys:
                if symbol in positions:
                    continue
                next_signal = signals[symbol](series[symbol].head(i), i)
                if next_signal is not None:
                    if next_signal.direction is Direction.LONG:
                        pending[symbol] = next_signal
                    else:
                        result.decisions.append(
                            {
                                "day": str(day),
                                "symbol": symbol,
                                "status": "rejected",
                                "reason": "long_only",
                                "shares": 0,
                            }
                        )
    return result
