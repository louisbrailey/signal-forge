"""Descriptive fixed-risk profit arithmetic on explicitly listed historical windows.

This is not a promotion run or a capital-constrained portfolio forecast. Window
choices are fixed below; currency research candidates remain development-only.
An old blanket claim that every full-history equity run reused a sealed test
was incorrect: sealed status is keyed by both version and dataset snapshot.
The output must never be used to create or widen approval. Data gaps and
portfolio feasibility require separate validation (see REPAIR_AUDIT_2026-11-02).
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

from signalforge.backtest.costs import CostModel
from signalforge.db.session import session_scope
from signalforge.domain import Horizon
from signalforge.research.backtest_runner import run_strategy_over_universe
from signalforge.research.fx import harness as h
from signalforge.research.fx.strategies import (
    CRYPTO2_STRATEGIES,
    CRYPTO3_STRATEGIES,
    CRYPTO_STRATEGIES,
    FX2_STRATEGIES,
    FX_STRATEGIES,
)
from signalforge.research.strategies import (
    MeanReversion,
    RelativeStrength,
    TrendContinuation,
    TsmomEtf,
    TurnOfMonth,
    VolatilityBreakout,
)


def _as_date(d):
    return d.date() if hasattr(d, "hour") else d


def stats(trades, r_values, window_start=None, window_end=None):
    n = len(trades)
    if n == 0:
        return {"n": 0}
    pnl = [t.pnl_r for t in trades]
    exp = sum(pnl) / n
    byyear = defaultdict(float)
    for t in trades:
        byyear[_as_date(t.exit_date).year] += t.pnl_r
    ordered = sorted(trades, key=lambda t: _as_date(t.exit_date))
    cum = peak = dd = 0.0
    for t in ordered:
        cum += t.pnl_r
        peak = max(peak, cum)
        dd = max(dd, peak - cum)
    first = window_start or min(_as_date(t.entry_date) for t in trades)
    last = window_end or max(_as_date(t.exit_date) for t in trades)
    years = max((last - first).days / 365.25, 0.25)
    neg_years = sum(1 for v in byyear.values() if v < 0)
    out = {
        "n": n,
        "exp_r": round(exp, 3),
        "win_rate": round(sum(1 for x in pnl if x > 0) / n, 3),
        "total_r": round(sum(pnl), 1),
        "trades_per_yr": round(n / years, 1),
        "r_per_yr": round(sum(pnl) / years, 1),
        "max_dd_r": round(dd, 1),
        "drawdown_basis": "realized trade exits only, excludes intratrade mark-to-market",
        "portfolio_constraints_applied": False,
        "forecast": False,
        "years": round(years, 1),
        "neg_years": f"{neg_years}/{len(byyear)}",
        "span": f"{first}..{last}",
        "by_year_r": {str(k): round(v, 1) for k, v in sorted(byyear.items())},
    }
    monthly = {}
    month = date(first.year, first.month, 1)
    while month <= last:
        monthly[month.strftime("%Y-%m")] = 0.0
        month = date(month.year + (month.month == 12), month.month % 12 + 1, 1)
    for trade in trades:
        key = _as_date(trade.exit_date).strftime("%Y-%m")
        if key in monthly:
            monthly[key] += trade.pnl_r
    values = sorted(monthly.values())
    out["monthly_realized_r"] = {k: round(v, 4) for k, v in monthly.items()}
    out["worst_calendar_month_r"] = round(min(values), 4)
    out["best_calendar_month_r"] = round(max(values), 4)
    out["losing_calendar_months"] = int(sum(v < 0 for v in values))
    out["calendar_months"] = len(values)
    for label, r in r_values.items():
        out[f"usd_per_month@{label}"] = round(sum(pnl) / years * r / 12)
        out[f"max_dd_usd@{label}"] = round(dd * r)
    return out


if __name__ == "__main__":
    S = Path(sys.argv[1])
    SYM24 = (S / "syms24_snap3.txt").read_text().strip().split(",")
    SYM150 = (S / "syms150_snap11.txt").read_text().strip().split(",")
    ETF10 = "SPY,QQQ,IWM,EFA,EEM,TLT,IEF,GLD,DBC,VNQ".split(",")
    IDX6 = "SPY,QQQ,DIA,IWM,EFA,EEM".split(",")
    FULL_END = date(2026, 11, 2)
    DEV_END = date(2025, 9, 7)
    CM = CostModel()  # 0 commission, 3 bps slippage, half spread

    results = {}
    with session_scope() as session:
        # ---------------- equities (ladder engine, long only) ----------------
        eq = [
            (
                "trend_continuation.short_swing",
                TrendContinuation(Horizon.SHORT_SWING),
                SYM24,
                date(2016, 10, 17),
                FULL_END,
                "sealed consumed (ids 1,6,11,16)",
            ),
            (
                "trend_continuation.short_swing",
                TrendContinuation(Horizon.SHORT_SWING),
                SYM150,
                date(2016, 10, 17),
                FULL_END,
                "DESCRIPTIVE ONLY; snapshot 11 short-swing sealed row in scratch was diagnostic",
            ),
            (
                "trend_continuation.medium_swing",
                TrendContinuation(Horizon.MEDIUM_SWING),
                SYM24,
                date(2016, 10, 17),
                FULL_END,
                "DESCRIPTIVE ONLY; no new approval or OOS claim",
            ),
            (
                "trend_continuation.medium_swing",
                TrendContinuation(Horizon.MEDIUM_SWING),
                SYM150,
                date(2016, 10, 17),
                FULL_END,
                "sealed consumed (id 21, approved)",
            ),
            (
                "relative_strength.medium_swing",
                RelativeStrength(Horizon.MEDIUM_SWING),
                SYM24,
                date(2016, 10, 17),
                FULL_END,
                "sealed consumed (id 14, approved)",
            ),
            (
                "relative_strength.medium_swing",
                RelativeStrength(Horizon.MEDIUM_SWING),
                SYM150,
                date(2016, 10, 17),
                FULL_END,
                "DESCRIPTIVE ONLY; no new approval or OOS claim",
            ),
            (
                "mean_reversion.short_swing",
                MeanReversion(),
                SYM24,
                date(2016, 10, 17),
                FULL_END,
                "DESCRIPTIVE ONLY; version/snapshot-specific sealed status must be checked separately",
            ),
            (
                "volatility_breakout.short_swing",
                VolatilityBreakout(Horizon.SHORT_SWING),
                SYM24,
                date(2016, 10, 17),
                FULL_END,
                "DESCRIPTIVE ONLY; version/snapshot-specific sealed status must be checked separately",
            ),
            (
                "volatility_breakout.short_swing",
                VolatilityBreakout(Horizon.SHORT_SWING),
                SYM150,
                date(2016, 10, 17),
                FULL_END,
                "DESCRIPTIVE ONLY; version/snapshot-specific sealed status must be checked separately",
            ),
            (
                "tsmom_etf.medium_swing",
                TsmomEtf(),
                [s for s in ETF10 if s != "QQQ"],
                date(2006, 3, 1),
                DEV_END,
                "DEV ONLY (no sealed look); closed",
            ),
            (
                "turn_of_month.short_swing",
                TurnOfMonth(),
                [s for s in IDX6 if s != "QQQ"],
                date(2003, 10, 20),
                DEV_END,
                "DEV ONLY; rejected",
            ),
        ]
        for key, strat, syms, start, end, note in eq:
            res = run_strategy_over_universe(
                session, strat, list(syms), start, end, source="massive", cost_model=CM
            )
            st = stats(res.trades, {"55": 55, "150": 150}, start, end)
            st["note"] = note
            results[f"{key} | {len(syms)} symbols"] = st
            print(
                key,
                len(syms),
                json.dumps({k: v for k, v in st.items() if k != "by_year_r"}),
                flush=True,
            )

        # ---------------- crypto / FX (currency harness) ----------------
        def currency(label, strategies, pairs, market, cut_sealed, r_values, note):
            series = {p: h.load_series(session, p, market) for p in pairs}
            series = {p: s for p, s in series.items() if len(s)}
            seal_from = h.sealed_start(series, 365)
            for strat in strategies:
                trades = []
                for pair, full in sorted(series.items()):
                    s = h._cut(full, seal_from) if cut_sealed else full
                    if len(s) < strat.warmup + 50:
                        continue
                    out = h.backtest(
                        strat,
                        s,
                        cost_model=CostModel(slippage_bps=1.0),
                        spread_bps=market.spread(pair),
                    )
                    trades += list(out.trades)
                st = stats(
                    trades,
                    r_values,
                    min(s.dates[0] for s in series.values()),
                    seal_from if cut_sealed else max(s.dates[-1] for s in series.values()),
                )
                st["note"] = note + (
                    f"; cut at sealed start {seal_from}" if cut_sealed else "; through last bar"
                )
                results[f"{label} {strat.key} | {len(series)} pairs"] = st
                print(
                    label,
                    strat.key,
                    json.dumps({k: v for k, v in st.items() if k != "by_year_r"}),
                    flush=True,
                )

        c3 = ["BTCUSD", "ETHUSD", "SOLUSD"]
        c10 = "BTCUSD,ETHUSD,XRPUSD,BNBUSD,SOLUSD,DOGEUSD,ADAUSD,LINKUSD,AVAXUSD,LTCUSD".split(",")
        fx8 = "EURUSD,USDJPY,GBPUSD,AUDUSD,USDCAD,USDCHF,NZDUSD,XAUUSD".split(",")
        currency(
            "CRYPTO-1",
            [CRYPTO_STRATEGIES[0]],
            c3,
            h.CRYPTO_MARKET,
            False,
            {"100": 100},
            "sealed consumed (SEALED_PASS) — in paper",
        )
        currency(
            "CRYPTO-1",
            CRYPTO_STRATEGIES[1:],
            c3,
            h.CRYPTO_MARKET,
            True,
            {"100": 100},
            "DEV ONLY; rejected",
        )
        currency(
            "CRYPTO-2",
            [CRYPTO2_STRATEGIES[0]],
            c10,
            h.CRYPTO2_MARKET,
            True,
            {"100": 100},
            "INVALIDATED AS PROMOTION EVIDENCE: BNB data gaps; descriptive development arithmetic only",
        )
        currency(
            "CRYPTO-3",
            CRYPTO3_STRATEGIES,
            c10,
            h.CRYPTO3_MARKET,
            True,
            {"100": 100},
            "SEALED_FAIL; BNB history also incomplete; no forecast",
        )
        currency("FX-1", FX_STRATEGIES, fx8, h.FX_MARKET, True, {"55": 55}, "DEV ONLY; rejected")
        currency("FX-2", FX2_STRATEGIES, fx8, h.FX2_MARKET, True, {"55": 55}, "DEV ONLY; rejected")

    (S / "profit_backtest.json").write_text(json.dumps(results, indent=1))
    print("DONE")
