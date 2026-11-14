#!/usr/bin/env python
"""R3-E — entry execution and the risk unit (engine item H14).

Pre-registration (binding): docs/research/PREREGISTRATION_r3_entry_execution_2026-11-10.md
Results file (named in advance): docs/research/RESULTS_r3_entry_execution_2026-11-10.md

What this script does, in order:

1. Loads persisted ``massive`` daily bars once for snapshots 3 and 11 (and SPY),
   window 2016-10-17..2025-09-05, from a read-only scratch copy of the database.
2. B0: runs the LIBRARY engine exactly as ``research/backtest_runner.py`` does and
   stops unless it reproduces the recorded development rows.
3. Runs a script-local copy of the engine loop with every hook off and stops
   unless it is trade-for-trade identical to the library engine on every symbol.
4. Computes B1 and every pre-registered cell (V1 g, V2 h, V3) on the in-sample
   and out-of-sample trades.
5. Selects on the in-sample trades only, then runs the four confirmation tests
   and the pre-registered decision rule on the out-of-sample trades.
6. Describes how the confirmation test moves when the saved trades of the two
   pre-registered arms are measured differently (added after adversarial review;
   no entry rule is simulated for it and no selection, test or verdict uses it).
7. Writes per-trade CSVs, ``summary.json`` and the results file.

It writes to no database, calls no data provider and loads no bar after
2025-09-05. Usage (environment as in the R3 orientation notes)::

    python entry_execution.py [--out DIR] [--results PATH] [--report-only | --no-report]

Research signal only — no order was placed.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import platform
import sys
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, fields, replace
from datetime import UTC, date, datetime, timedelta
from itertools import pairwise
from pathlib import Path
from typing import Any

import numpy as np
from sqlalchemy import text

from signalforge.backtest.costs import CostModel
from signalforge.backtest.engine import _DOLLAR_RISK_PER_TRADE, SimTrade, run_backtest
from signalforge.backtest.metrics import compute_metrics
from signalforge.data.series import PriceSeries
from signalforge.db.models import DataSnapshot
from signalforge.db.session import session_scope
from signalforge.domain import Direction, Horizon
from signalforge.research.backtest_runner import _is_boundary
from signalforge.research.features.daily import atr
from signalforge.research.regime import regime_lookup
from signalforge.research.strategies import (
    High52Breakout,
    RelativeStrength,
    TrendContinuation,
    signal_fn_for,
)

START = date(2016, 10, 17)
END = date(2025, 9, 5)  # last development session; nothing later is loaded
# Exclusive upper bound of the pre-sealed span. Used ONLY for the gate-1 fold
# arithmetic (research/promotion.py:1279-1284); it is never a load date.
PRE_SEALED_BOUND = date(2025, 9, 7)
SOURCE = "massive"
PROXY = "SPY"
MIN_BARS = 60  # backtest_runner.run_strategy_over_universe default
WARMUP = MIN_BARS // 2  # the runner passes warmup=min_bars // 2
SPREAD_BPS = 5.0  # run_backtest default; the runner does not override it
N_FOLDS = 4  # PromotionThresholds.min_walkforward_folds
N_RESAMPLES = 10_000
SEED = 20261110
ALPHA = 0.05
V1_GRID = (0.3, 0.6, 1.0)
V2_GRID = (0.3, 0.6, 1.0)
STRESS_SLIPPAGE_BPS = 6.0  # with a 10 bps spread: 6 + 10/2 = 11 bps per side
STRESS_SPREAD_BPS = 10.0
SAMPLES = ("IS", "OOS", "ALL")

# Descriptive sensitivity of the confirmation test, added after adversarial review.
# Nothing below enters the selection, the test or the verdict, and no entry rule is
# simulated for it: the trades are the saved trades of the pre-registered cells.
N_OTHER_SEEDS = 2_000  # seeds SEED+1.. : Monte-Carlo noise of the registered-seed p
N_OTHER_SEEDS_ALT = 300  # the same, for each alternative measurement of the baseline
ALT_BASELINES = ("b0_trades_minus_invalid", "above_target_at_open", "above_target_removed")

REPO = Path(__file__).resolve().parents[2]
DEFAULT_RESULTS = REPO / "docs" / "research" / "RESULTS_r3_entry_execution_2026-11-10.md"
PREREG = "docs/research/PREREGISTRATION_r3_entry_execution_2026-11-10.md"


@dataclass(frozen=True, slots=True)
class VersionDef:
    key: str
    snapshot: int
    run_id: int  # backtest_run holding the recorded development row
    eval_id: int  # strategy_promotion_evaluation holding the gate-1 folds
    prereg_oos_n: int  # the identity target written in the pre-registration
    prereg_oos_exp: float


VERSIONS = (
    VersionDef("trend_continuation.short_swing", 3, 53, 52, 341, 0.2648),
    VersionDef("relative_strength.medium_swing", 3, 54, 53, 197, 0.3004),
    VersionDef("trend_continuation.medium_swing", 11, 55, 54, 1986, 0.2209),
    VersionDef("high52_breakout.medium_swing", 11, 49, 51, 525, 0.2274),
)


@dataclass(frozen=True, slots=True)
class Hooks:
    """Trade-altering switches of the script-local engine. All off = library."""

    invalid_open: bool = False  # B1: raw open at or below the planned stop -> no trade
    g: float | None = None  # V1: enter only if open <= close_t + g * ATR14_t
    h: float | None = None  # V2: enter only if open >= close_t - h * ATR14_t
    fill_anchor: bool = False  # V3: stop and target recomputed from the fill


@dataclass(slots=True)
class LTrade:
    symbol: str
    signal_idx: int
    signal_date: date
    entry_date: date
    exit_date: date
    bars_held: int
    exit_reason: str
    close_t: float
    open_raw: float
    stop_signal: float
    target_signal: float | None
    stop_used: float
    target_used: float | None
    atr14: float
    planned_risk: float  # U = close_t - stop_t
    gap_atr: float  # (open - close_t) / ATR14_t
    entry_fill: float
    exit_fill: float
    engine_r: float  # (exit - entry) / |entry_fill - stop_t|, the library definition
    stable_r: float  # (exit - entry) / U
    sample: str = ""
    fold: int = 0


class IdentityError(RuntimeError):
    """An identity check failed: stop and report that instead of results."""


# --------------------------------------------------------------------------- #
# script-local copy of backtest/engine.py (run_backtest + _resolve_exit), long only
# --------------------------------------------------------------------------- #
def local_resolve_exit(
    series: Any,
    entry_idx: int,
    stop_price: float,
    target_price: float | None,
    time_stop_bars: int,
    d: int,
    slip: float,
) -> tuple[int, float, str]:
    n = len(series)
    for u in range(entry_idx, n):
        o, hi, lo = series.open[u], series.high[u], series.low[u]
        # --- stop (checked first) ---
        if lo <= stop_price:
            px = min(o, stop_price) if u > entry_idx else stop_price
            return u, px * (1 - slip), "stop"
        # --- target ---
        if target_price is not None and hi >= target_price:
            px = max(o, target_price) if u > entry_idx else target_price
            return u, px * (1 - slip), "target"
        # --- time stop ---
        if u - entry_idx >= time_stop_bars:
            return u, series.close[u] * (1 - d * slip), "time_stop"
    last = n - 1
    return last, series.close[last] * (1 - d * slip), "eod"


def local_engine(
    series: Any,
    get_signal: Callable[[int], Any],
    *,
    slip: float,
    warmup: int,
    hooks: Hooks,
    stop_mult: float,
    target_mult: float,
    build_simtrades: bool = False,
) -> tuple[list[LTrade], list[Any], Counter[str]]:
    """The library loop with hooks. ``hooks=Hooks()`` must equal ``run_backtest``."""
    n = len(series)
    out: list[LTrade] = []
    sim: list[Any] = []
    skips: Counter[str] = Counter()
    t = max(warmup, 1)
    while t < n - 1:
        sig = get_signal(t)
        if sig is None:
            t += 1
            continue
        if sig.direction is not Direction.LONG:
            raise IdentityError("the four approved versions are long-only in development runs")
        d = 1
        entry_idx = t + 1
        raw_entry = series.open[entry_idx]
        entry_fill = raw_entry * (1 + d * slip)
        risk_per_share = abs(entry_fill - sig.stop_price)
        if risk_per_share <= 0:  # the engine's own skip
            skips["engine_zero_risk"] += 1
            t += 1
            continue

        close_t = float(series.close[t])
        planned_risk = close_t - sig.stop_price  # U, fixed at the signal
        atr_t = planned_risk / stop_mult
        if hooks.invalid_open and raw_entry <= sig.stop_price:
            skips["open_at_or_below_stop"] += 1
            t += 1
            continue
        if hooks.g is not None and not (raw_entry <= close_t + hooks.g * atr_t):
            skips["v1_open_above_limit"] += 1
            t += 1
            continue
        if hooks.h is not None and not (raw_entry >= close_t - hooks.h * atr_t):
            skips["v2_weak_open"] += 1
            t += 1
            continue

        if hooks.fill_anchor:
            stop_px = entry_fill - stop_mult * atr_t
            target_px = None if sig.target_price is None else entry_fill + target_mult * atr_t
        else:
            stop_px, target_px = sig.stop_price, sig.target_price

        exit_idx, exit_fill, reason = local_resolve_exit(
            series, entry_idx, stop_px, target_px, sig.time_stop_bars, d, slip
        )
        pnl_r = d * (exit_fill - entry_fill) / risk_per_share
        out.append(
            LTrade(
                symbol=series.symbol,
                signal_idx=t,
                signal_date=series.dates[t],
                entry_date=series.dates[entry_idx],
                exit_date=series.dates[exit_idx],
                bars_held=exit_idx - entry_idx,
                exit_reason=reason,
                close_t=close_t,
                open_raw=float(raw_entry),
                stop_signal=float(sig.stop_price),
                target_signal=None if sig.target_price is None else float(sig.target_price),
                stop_used=float(stop_px),
                target_used=None if target_px is None else float(target_px),
                atr14=float(atr_t),
                planned_risk=float(planned_risk),
                gap_atr=float((raw_entry - close_t) / atr_t),
                entry_fill=float(entry_fill),
                exit_fill=float(exit_fill),
                engine_r=float(pnl_r),
                stable_r=float((exit_fill - entry_fill) / planned_risk),
            )
        )
        if build_simtrades:
            seg_high = series.high[entry_idx : exit_idx + 1]
            seg_low = series.low[entry_idx : exit_idx + 1]
            mfe = (float(seg_high.max()) - entry_fill) / risk_per_share
            mae = (float(seg_low.min()) - entry_fill) / risk_per_share
            pnl_pct = d * (exit_fill / entry_fill - 1.0)
            sim.append(
                SimTrade(
                    symbol=series.symbol,
                    direction=sig.direction,
                    entry_date=series.dates[entry_idx],
                    entry_price=round(entry_fill, 4),
                    exit_date=series.dates[exit_idx],
                    exit_price=round(exit_fill, 4),
                    bars_held=exit_idx - entry_idx,
                    pnl_r=pnl_r,
                    pnl_pct=pnl_pct,
                    pnl_dollars=pnl_r * _DOLLAR_RISK_PER_TRADE,
                    mae_r=mae,
                    mfe_r=mfe,
                    costs_bps=slip * 2 * 10_000.0,
                    exit_reason=reason,
                    reason=sig.reason,
                )
            )
        t = exit_idx + 1  # flat again; no overlapping positions
    return out, sim, skips


class SignalCache:
    """Memo of the pure signal function ``fn(series.head(t), t)`` for one symbol."""

    def __init__(self, fn: Callable[[Any, int], Any], series: Any) -> None:
        self._fn = fn
        self._series = series
        self._memo: dict[int, Any] = {}

    def get(self, t: int) -> Any:
        try:
            return self._memo[t]
        except KeyError:
            sig = self._fn(self._series.head(t), t)
            self._memo[t] = sig
            return sig


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def build_strategy(key: str) -> Any:
    if key == "trend_continuation.short_swing":
        return TrendContinuation(Horizon.SHORT_SWING)
    if key == "trend_continuation.medium_swing":
        return TrendContinuation(Horizon.MEDIUM_SWING)
    if key == "relative_strength.medium_swing":
        return RelativeStrength(Horizon.MEDIUM_SWING)
    if key == "high52_breakout.medium_swing":
        return High52Breakout()
    raise KeyError(key)


def fold_edges() -> list[date]:
    span_days = (PRE_SEALED_BOUND - START).days
    return [START + timedelta(days=span_days * k // N_FOLDS) for k in range(N_FOLDS + 1)]


def fold_of(d: date, edges: list[date]) -> int:
    for k in range(N_FOLDS):
        if edges[k] <= d < edges[k + 1]:
            return k + 1
    raise IdentityError(f"entry date {d} outside the pre-sealed span")


def sample_metrics(rs: list[float], bars_held: list[int], years: float) -> dict[str, Any]:
    n = len(rs)
    if n == 0:
        return {
            "n": 0,
            "expectancy": None,
            "total_r": 0.0,
            "total_r_per_year": 0.0,
            "entry_bar_n": 0,
            "entry_bar_share": None,
            "entry_bar_mean_r": None,
            "entry_bar_total_r": 0.0,
            "worst": None,
        }
    total = float(sum(rs))
    eb = [r for r, b in zip(rs, bars_held, strict=True) if b == 0]
    return {
        "n": n,
        "expectancy": total / n,
        "total_r": total,
        "total_r_per_year": total / years,
        "entry_bar_n": len(eb),
        "entry_bar_share": len(eb) / n,
        "entry_bar_mean_r": (float(sum(eb)) / len(eb)) if eb else None,
        "entry_bar_total_r": float(sum(eb)),
        "worst": float(min(rs)),
    }


def cell_metrics(trades: list[LTrade], r_attr: str, years: dict[str, float]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for s in SAMPLES:
        sel = [t for t in trades if s == "ALL" or t.sample == s]
        out[s] = sample_metrics(
            [getattr(t, r_attr) for t in sel], [t.bars_held for t in sel], years[s]
        )
    return out


def fold_metrics(trades: list[LTrade], r_attr: str) -> list[dict[str, Any]]:
    rows = []
    for k in range(1, N_FOLDS + 1):
        rs = [getattr(t, r_attr) for t in trades if t.fold == k]
        rows.append({"fold": k, "n": len(rs), "expectancy": (sum(rs) / len(rs)) if rs else None})
    return rows


def entry_bar_breakdown(trades: list[LTrade], r_attr: str) -> dict[str, Any]:
    """Descriptive only: entry-bar exits split by what closed them."""

    def agg(xs: list[LTrade]) -> dict[str, Any]:
        return {"n": len(xs), "total_r": float(sum(getattr(t, r_attr) for t in xs))}

    out: dict[str, Any] = {}
    for s in SAMPLES:
        sel = [t for t in trades if (s == "ALL" or t.sample == s) and t.bars_held == 0]
        stop = [t for t in sel if t.exit_reason == "stop"]
        tgt = [t for t in sel if t.exit_reason == "target"]
        above = [t for t in tgt if t.target_used is not None and t.open_raw > t.target_used]
        out[s] = {
            "all": agg(sel),
            "stop": agg(stop),
            "stop_open_at_or_below_stop": agg([t for t in stop if t.open_raw <= t.stop_used]),
            "target_open_above_target": agg(above),
            "target_reached_intraday": agg([t for t in tgt if t not in above]),
            "end_of_data": agg([t for t in sel if t.exit_reason not in ("stop", "target")]),
        }
    return out


def _r_stats(rs: list[float]) -> dict[str, Any]:
    if not rs:
        return {"n": 0, "mean": None, "min": None, "max": None, "total": 0.0}
    return {
        "n": len(rs),
        "mean": sum(rs) / len(rs),
        "min": min(rs),
        "max": max(rs),
        "total": float(sum(rs)),
    }


def gap_stats(gaps: list[float]) -> dict[str, Any]:
    if not gaps:
        return {"n": 0}
    a = np.asarray(gaps, dtype=np.float64)
    q = np.percentile(a, [5, 25, 50, 75, 95])
    return {
        "n": int(a.size),
        "mean": float(a.mean()),
        "min": float(a.min()),
        "p05": float(q[0]),
        "p25": float(q[1]),
        "p50": float(q[2]),
        "p75": float(q[3]),
        "p95": float(q[4]),
        "max": float(a.max()),
        "share_below_-1.0": float(np.mean(a < -1.0)),
        "share_below_-0.6": float(np.mean(a < -0.6)),
        "share_below_-0.3": float(np.mean(a < -0.3)),
        "share_above_+0.3": float(np.mean(a > 0.3)),
        "share_above_+0.6": float(np.mean(a > 0.6)),
        "share_above_+1.0": float(np.mean(a > 1.0)),
    }


def month_block_bootstrap(b1: list[LTrade], cand: list[LTrade]) -> dict[str, Any]:
    """Calendar-month block bootstrap of (candidate expectancy - B1 expectancy).

    The blocks are the calendar months holding at least one out-of-sample entry
    in either arm. Each resample draws that many months with replacement and
    applies the same draw to both arms. The null distribution is the bootstrap
    distribution of the difference recentred on zero; the one-sided p-value is
    the share of null draws at least as large as the observed difference, with
    the usual +1 Monte-Carlo correction.
    """
    months = sorted({(t.entry_date.year, t.entry_date.month) for t in (*b1, *cand)})
    idx = {m: i for i, m in enumerate(months)}
    m_count = len(months)
    sb, nb = np.zeros(m_count), np.zeros(m_count)
    sc, nc = np.zeros(m_count), np.zeros(m_count)
    for t in b1:
        i = idx[(t.entry_date.year, t.entry_date.month)]
        sb[i] += t.stable_r
        nb[i] += 1
    for t in cand:
        i = idx[(t.entry_date.year, t.entry_date.month)]
        sc[i] += t.stable_r
        nc[i] += 1
    observed = float(sc.sum() / nc.sum() - sb.sum() / nb.sum())
    rng = np.random.default_rng(SEED)
    draws = rng.integers(0, m_count, size=(N_RESAMPLES, m_count))
    n_c, n_b = nc[draws].sum(axis=1), nb[draws].sum(axis=1)
    if not ((n_c > 0).all() and (n_b > 0).all()):
        raise IdentityError("a bootstrap resample held no trades in one arm")
    diffs = sc[draws].sum(axis=1) / n_c - sb[draws].sum(axis=1) / n_b
    null = diffs - observed
    p = (1 + int(np.count_nonzero(null >= observed))) / (N_RESAMPLES + 1)
    lo, hi = np.percentile(diffs, [2.5, 97.5])
    return {
        "months": m_count,
        "first_month": f"{months[0][0]}-{months[0][1]:02d}",
        "last_month": f"{months[-1][0]}-{months[-1][1]:02d}",
        "observed_diff": observed,
        "bootstrap_se": float(diffs.std(ddof=1)),
        "bootstrap_mean_diff": float(diffs.mean()),
        "pct_interval_95": [float(lo), float(hi)],
        "share_resamples_diff_le_0": float(np.mean(diffs <= 0)),
        "p_one_sided": float(p),
        "resamples": N_RESAMPLES,
        "seed": SEED,
    }


def holm(pvals: dict[str, float]) -> dict[str, float]:
    items = sorted(pvals.items(), key=lambda kv: kv[1])
    m = len(items)
    adj: dict[str, float] = {}
    running = 0.0
    for i, (k, p) in enumerate(items):
        running = max(running, min(1.0, (m - i) * p))
        adj[k] = running
    return adj


# --------------------------------------------------------------------------- #
# descriptive sensitivity of the confirmation test (added after adversarial review)
#
# Nothing in this block is pre-registered, and nothing in it enters the selection,
# the test or the verdict. It simulates no entry rule: it re-measures the saved
# trades of the pre-registered cells and repeats the pre-registered bootstrap.
# --------------------------------------------------------------------------- #
def opens_above_target(t: LTrade) -> bool:
    """An entry that opened above its target and was closed at the target on that bar.

    On the entry bar the engine books a target exit at the target price even when
    the bar opened above it (backtest/engine.py, ``_resolve_exit``), so the sale is
    booked below the purchase price.
    """
    return (
        t.bars_held == 0
        and t.exit_reason == "target"
        and t.target_used is not None
        and t.open_raw > t.target_used
    )


def at_open_r(t: LTrade, slip: float) -> float:
    """Stable R of a round trip at the open: bought at open*(1+slip), sold at open*(1-slip)."""
    return (t.open_raw * (1 - slip) - t.entry_fill) / t.planned_risk


def remeasure(trades: list[LTrade], mode: str, slip: float) -> list[LTrade]:
    """Re-measure saved trades under one alternative baseline; nothing is simulated."""
    if mode == "above_target_removed":
        return [t for t in trades if not opens_above_target(t)]
    if mode == "above_target_at_open":
        return [
            replace(t, stable_r=at_open_r(t, slip)) if opens_above_target(t) else t for t in trades
        ]
    if mode == "b0_trades_minus_invalid":
        return trades
    raise KeyError(mode)


def screen_cells(is_by_cell: dict[str, dict[str, Any]], base_is: dict[str, Any]) -> dict[str, Any]:
    """The pre-registered in-sample screen and the script's pick rule, against any baseline."""

    def ok(name: str) -> bool:
        c = is_by_cell[name]
        return bool(
            c["n"] > 0
            and c["expectancy"] > base_is["expectancy"]
            and c["total_r_per_year"] > base_is["total_r_per_year"]
        )

    def pick(names: list[tuple[float, str]]) -> tuple[float | None, list[str]]:
        q = [(par, nm) for par, nm in names if ok(nm)]
        if not q:
            return None, []
        best = max(
            q,
            key=lambda x: (
                is_by_cell[x[1]]["expectancy"],
                is_by_cell[x[1]]["total_r_per_year"],
                -x[0],
            ),
        )
        return best[0], [nm for _, nm in q]

    g_pick, v1_q = pick([(g, f"V1 g={g}") for g in V1_GRID])
    h_pick, v2_q = pick([(h, f"V2 h={h}") for h in V2_GRID])
    v3_pick = ok("V3")
    return {
        "qualifies": {nm: ok(nm) for nm in is_by_cell},
        "v1_qualifying": v1_q,
        "v2_qualifying": v2_q,
        "v1_pick": g_pick,
        "v2_pick": h_pick,
        "v3_pick": bool(v3_pick),
        "e_star": cell_label(Hooks(invalid_open=True, g=g_pick, h=h_pick, fill_anchor=v3_pick)),
    }


def month_sums(b1: list[LTrade], cand: list[LTrade]) -> tuple[Any, ...]:
    """Per-month sums and counts of both arms, accumulated as ``month_block_bootstrap`` does."""
    months = sorted({(t.entry_date.year, t.entry_date.month) for t in (*b1, *cand)})
    idx = {m: i for i, m in enumerate(months)}
    m_count = len(months)
    sb, nb = np.zeros(m_count), np.zeros(m_count)
    sc, nc = np.zeros(m_count), np.zeros(m_count)
    for t in b1:
        i = idx[(t.entry_date.year, t.entry_date.month)]
        sb[i] += t.stable_r
        nb[i] += 1
    for t in cand:
        i = idx[(t.entry_date.year, t.entry_date.month)]
        sc[i] += t.stable_r
        nc[i] += 1
    return months, sb, nb, sc, nc


def resampled_diffs(sb: Any, nb: Any, sc: Any, nc: Any, seed: int) -> Any:
    """One bootstrap run with the pre-registered draw call, for any seed."""
    m_count = len(sb)
    draws = np.random.default_rng(seed).integers(0, m_count, size=(N_RESAMPLES, m_count))
    n_c, n_b = nc[draws].sum(axis=1), nb[draws].sum(axis=1)
    keep = (n_c > 0) & (n_b > 0)
    return sc[draws].sum(axis=1)[keep] / n_c[keep] - sb[draws].sum(axis=1)[keep] / n_b[keep]


def student_t_upper(z: float, df: int) -> float:
    """Upper tail of Student's t by numerical integration (scipy is not installed here)."""
    xs = np.linspace(z, z + 400.0, 2_000_001)
    c = math.exp(math.lgamma((df + 1) / 2) - math.lgamma(df / 2)) / math.sqrt(df * math.pi)
    trapezoid = getattr(np, "trapezoid", None) or np.trapz
    return float(trapezoid(c * (1 + xs * xs / df) ** (-(df + 1) / 2), xs))


def bootstrap_robustness(
    b1: list[LTrade],
    cand: list[LTrade],
    boot: dict[str, Any],
    factor: int,
    n_seeds: int,
    *,
    full: bool,
    oos_span: tuple[tuple[int, int], tuple[int, int]] | None = None,
) -> dict[str, Any]:
    """How the one-sided p of a test moves with the seed and with how p is formed.

    ``factor`` is the Holm multiplier of this test (4 for the smallest of four p).
    The first step re-derives the registered-seed p and stops if it differs.
    ``oos_span`` is the first and last calendar month of the out-of-sample span.
    """
    months, sb, nb, sc, nc = month_sums(b1, cand)
    observed = float(sc.sum() / nc.sum() - sb.sum() / nb.sum())
    d0 = resampled_diffs(sb, nb, sc, nc, SEED)
    cnt0 = int(np.count_nonzero(d0 - observed >= observed))
    if (
        observed != boot["observed_diff"]
        or d0.size != N_RESAMPLES
        or (1 + cnt0) / (N_RESAMPLES + 1) != boot["p_one_sided"]
    ):
        raise IdentityError("the robustness helper does not reproduce the registered-seed test")
    ps = np.empty(n_seeds)
    hit = le0 = tot = 0
    for j in range(n_seeds):
        d = resampled_diffs(sb, nb, sc, nc, SEED + 1 + j)
        c = int(np.count_nonzero(d - observed >= observed))
        ps[j] = (1 + c) / (d.size + 1)
        hit += c
        le0 += int(np.count_nonzero(d <= 0))
        tot += d.size
    allowed = math.ceil(ALPHA * (N_RESAMPLES + 1) / factor) - 2
    out: dict[str, Any] = {
        "holm_factor": factor,
        "exceedances_registered_seed": cnt0,
        "exceedances_allowed_for_a_pass": allowed,
        "other_seeds": {
            "n_seeds": n_seeds,
            "first_seed": SEED + 1,
            "last_seed": SEED + n_seeds,
            "resamples_each": N_RESAMPLES,
            "p_mean": float(ps.mean()),
            "p_sd": float(ps.std(ddof=1)),
            "p_min": float(ps.min()),
            "p_max": float(ps.max()),
            "share_adjusted_p_below_alpha": float(np.mean(factor * ps < ALPHA)),
            "n_adjusted_p_below_alpha": int(np.count_nonzero(factor * ps < ALPHA)),
        },
        "pooled": {
            "resamples": tot,
            "p": hit / tot,
            "adjusted_p": min(1.0, factor * hit / tot),
            "share_diff_le_0": le0 / tot,
            "adjusted_share_diff_le_0": min(1.0, factor * le0 / tot),
        },
    }
    if (
        not factor * (1 + allowed) / (N_RESAMPLES + 1)
        < ALPHA
        <= factor * (2 + allowed) / (N_RESAMPLES + 1)
    ):
        raise IdentityError("allowed-exceedance arithmetic is wrong")
    if full:
        se = float(d0.std(ddof=1))
        z = observed / se
        p_centred = (1 + int(np.count_nonzero(d0 - d0.mean() >= observed))) / (N_RESAMPLES + 1)
        p_pct = float(np.mean(d0 <= 0))
        p_normal = 0.5 * math.erfc(z / math.sqrt(2))
        p_t = student_t_upper(z, len(months) - 1)
        out["other_constructions"] = {
            "z": z,
            "bootstrap_se": se,
            "t_df": len(months) - 1,
            "p": {
                "share_of_resamples_le_0": p_pct,
                "null_centred_on_bootstrap_mean": p_centred,
                "normal_with_bootstrap_se": p_normal,
                "student_t_with_bootstrap_se": p_t,
            },
            "adjusted_p": {
                "share_of_resamples_le_0": min(1.0, factor * p_pct),
                "null_centred_on_bootstrap_mean": min(1.0, factor * p_centred),
                "normal_with_bootstrap_se": min(1.0, factor * p_normal),
                "student_t_with_bootstrap_se": min(1.0, factor * p_t),
            },
        }
        loo = []
        for m in months:
            bb = [t for t in b1 if (t.entry_date.year, t.entry_date.month) != m]
            cc = [t for t in cand if (t.entry_date.year, t.entry_date.month) != m]
            p_m = month_block_bootstrap(bb, cc)["p_one_sided"]
            loo.append({"month": f"{m[0]}-{m[1]:02d}", "p": p_m})
        out["leave_one_month_out"] = {
            "months": len(months),
            "n_adjusted_p_at_or_above_alpha": sum(1 for x in loo if factor * x["p"] >= ALPHA),
            "p_by_month": loo,
        }

        # Studentised (bootstrap-t) p: each resample's difference divided by its own
        # month-cluster linearised standard error; same draws as the registered seed.
        m_count = len(months)
        n_b, n_c = nb.sum(), nc.sum()
        mean_b, mean_c = sb.sum() / n_b, sc.sum() / n_c
        infl = (sc - mean_c * nc) / n_c - (sb - mean_b * nb) / n_b
        se_lin = math.sqrt(float((infl**2).sum()) * m_count / (m_count - 1))
        draws = np.random.default_rng(SEED).integers(0, m_count, size=(N_RESAMPLES, m_count))
        s_b, k_b, s_c, k_c = sb[draws], nb[draws], sc[draws], nc[draws]
        mb_s, mc_s = s_b.sum(axis=1) / k_b.sum(axis=1), s_c.sum(axis=1) / k_c.sum(axis=1)
        infl_s = (s_c - mc_s[:, None] * k_c) / k_c.sum(axis=1)[:, None] - (
            s_b - mb_s[:, None] * k_b
        ) / k_b.sum(axis=1)[:, None]
        se_s = np.sqrt((infl_s**2).sum(axis=1) * m_count / (m_count - 1))
        t_obs = observed / se_lin
        t_star = (mc_s - mb_s - observed) / se_s
        p_stud = (1 + int(np.count_nonzero(t_star >= t_obs))) / (N_RESAMPLES + 1)
        out["other_constructions"]["linearised_se"] = se_lin
        out["other_constructions"]["t_observed"] = t_obs
        out["other_constructions"]["p"]["studentised_bootstrap"] = p_stud
        out["other_constructions"]["adjusted_p"]["studentised_bootstrap"] = min(
            1.0, factor * p_stud
        )

        # Other block frames: calendar months with no entry in either arm also count as blocks.
        def month_range(a: tuple[int, int], b: tuple[int, int]) -> list[tuple[int, int]]:
            seq, (y, mo) = [], a
            while (y, mo) <= b:
                seq.append((y, mo))
                y, mo = (y + 1, 1) if mo == 12 else (y, mo + 1)
            return seq

        frames = {"first_to_last_entry_month": month_range(months[0], months[-1])}
        if oos_span is not None:
            frames["whole_out_of_sample_span"] = month_range(*oos_span)
        out["block_frames"] = {}
        for name, frame in frames.items():
            if not set(months) <= set(frame):
                raise IdentityError(f"block frame {name} does not cover every entry month")
            pos = [frame.index(m) for m in months]
            arrs = []
            for a in (sb, nb, sc, nc):
                wide = np.zeros(len(frame))
                wide[pos] = a
                arrs.append(wide)
            d = resampled_diffs(*arrs, SEED)
            p_f = (1 + int(np.count_nonzero(d - observed >= observed))) / (d.size + 1)
            out["block_frames"][name] = {
                "months": len(frame),
                "months_without_entry": len(frame) - len(months),
                "first_month": f"{frame[0][0]}-{frame[0][1]:02d}",
                "last_month": f"{frame[-1][0]}-{frame[-1][1]:02d}",
                "resamples_kept": int(d.size),
                "p": p_f,
                "adjusted_p": min(1.0, factor * p_f),
            }
    return out


def _diff(a: float | None, b: float | None) -> float | None:
    return None if a is None or b is None else a - b


def sensitivity_block(
    *,
    b0: list[LTrade],
    b1: list[LTrade],
    cell_trades: dict[str, list[LTrade]],
    e_trades: list[LTrade],
    e_label: str,
    has_candidate: bool,
    years: dict[str, float],
    slip: float,
    bars: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, tuple[list[LTrade], list[LTrade]]]]:
    """Describe the correction step by step and re-measure the baseline three ways.

    Returns the JSON block and, per alternative baseline, the two out-of-sample
    arms of its test (kept in memory only, for the seed-noise loop).
    """

    def by_sample(xs: list[LTrade]) -> dict[str, Any]:
        return {
            s: {
                "n": sum(1 for t in xs if s == "ALL" or t.sample == s),
                "stable_r_total": float(sum(t.stable_r for t in xs if s == "ALL" or t.sample == s)),
            }
            for s in SAMPLES
        }

    # -- the correction in three steps: risk unit, entries not taken, re-simulation
    literal = [t for t in b0 if t.open_raw > t.stop_signal]
    flagged = [t for t in b0 if t.open_raw <= t.stop_signal]
    m_b0e = cell_metrics(b0, "engine_r", years)
    m_b0s = cell_metrics(b0, "stable_r", years)
    m_lit = cell_metrics(literal, "stable_r", years)
    m_b1 = cell_metrics(b1, "stable_r", years)
    steps = {
        s: {
            "risk_unit": _diff(m_b0s[s]["expectancy"], m_b0e[s]["expectancy"]),
            "entries_not_taken": _diff(m_lit[s]["expectancy"], m_b0s[s]["expectancy"]),
            "re_simulation": _diff(m_b1[s]["expectancy"], m_lit[s]["expectancy"]),
            "total": _diff(m_b1[s]["expectancy"], m_b0e[s]["expectancy"]),
        }
        for s in SAMPLES
    }
    key0 = {(t.symbol, t.entry_date) for t in b0}
    key1 = {(t.symbol, t.entry_date) for t in b1}
    gone = [t for t in b0 if (t.symbol, t.entry_date) not in key1]
    side_effects = {
        "new_in_b1": by_sample([t for t in b1 if (t.symbol, t.entry_date) not in key0]),
        "b0_not_in_b1_invalid_open": by_sample([t for t in gone if t.open_raw <= t.stop_signal]),
        "b0_not_in_b1_displaced": by_sample([t for t in gone if t.open_raw > t.stop_signal]),
    }

    # -- entries that open above their target and are closed at the target on that bar
    def above(xs: list[LTrade]) -> dict[str, Any]:
        return by_sample([t for t in xs if opens_above_target(t)])

    b1_above = [t for t in b1 if opens_above_target(t)]
    for t in b1_above:
        if bars[t.symbol].dates[t.signal_idx + 1] != t.entry_date:
            raise IdentityError("entry bar index does not line up with the entry date")
    above_target = {
        "by_cell": {
            "B1": above(b1),
            **{nm: above(tr) for nm, tr in cell_trades.items()},
            "E*": above(e_trades),
        },
        # the whole entry bar traded above the target: the target price never traded that day
        "b1_bar_low_above_target": {
            s: sum(
                1
                for t in b1_above
                if (s == "ALL" or t.sample == s)
                and float(bars[t.symbol].low[t.signal_idx + 1]) > t.target_used
            )
            for s in SAMPLES
        },
        # the same count with the booked sale price (target less costs) against the bar's low
        "b1_booked_exit_below_bar_low": {
            s: sum(
                1
                for t in b1_above
                if (s == "ALL" or t.sample == s)
                and t.exit_fill < float(bars[t.symbol].low[t.signal_idx + 1])
            )
            for s in SAMPLES
        },
        "b1_total_r_if_closed_at_open": {
            s: float(sum(at_open_r(t, slip) for t in b1_above if s == "ALL" or t.sample == s))
            for s in SAMPLES
        },
    }

    # -- the baseline measured three other ways; the same screen and the same test
    baselines: dict[str, Any] = {}
    arms: dict[str, tuple[list[LTrade], list[LTrade]]] = {}
    for mode in ALT_BASELINES:
        base = literal if mode == "b0_trades_minus_invalid" else remeasure(b1, mode, slip)
        base_m = cell_metrics(base, "stable_r", years)
        cells_m = {
            nm: cell_metrics(remeasure(tr, mode, slip), "stable_r", years)
            for nm, tr in cell_trades.items()
        }
        scr = screen_cells({nm: m["IS"] for nm, m in cells_m.items()}, base_m["IS"])
        entry: dict[str, Any] = {
            "baseline": base_m,
            "cells_in_sample": {
                nm: {k: m["IS"][k] for k in ("n", "expectancy", "total_r_per_year")}
                for nm, m in cells_m.items()
            },
            "screen": scr,
            "e_star_unchanged": bool(scr["e_star"] == e_label),
        }
        if has_candidate:
            e_view = remeasure(e_trades, mode, slip)
            b_oos = [t for t in base if t.sample == "OOS"]
            e_oos = [t for t in e_view if t.sample == "OOS"]
            boot = month_block_bootstrap(b_oos, e_oos)
            e_m = cell_metrics(e_view, "stable_r", years)["OOS"]
            if abs(e_m["expectancy"] - base_m["OOS"]["expectancy"] - boot["observed_diff"]) > 1e-9:
                raise IdentityError("sensitivity: bootstrap difference is not the cell difference")
            entry["test"] = {
                "oos_base_n": base_m["OOS"]["n"],
                "oos_base_expectancy": base_m["OOS"]["expectancy"],
                "oos_e_n": e_m["n"],
                "oos_e_expectancy": e_m["expectancy"],
                "oos_diff": boot["observed_diff"],
                "bootstrap": boot,
                "p_one_sided": boot["p_one_sided"],
            }
            arms[mode] = (b_oos, e_oos)
        baselines[mode] = entry

    block = {
        "note": (
            "Descriptive, added after adversarial review. Not pre-registered; no selection, test "
            "or verdict uses it; no entry rule was simulated for it."
        ),
        "b0_trades_minus_invalid_open": m_lit,
        "invalid_open_entries": by_sample(flagged),
        "correction_steps": steps,
        "resimulation_side_effects": side_effects,
        "above_target_entries": above_target,
        "baselines": baselines,
    }
    return block, arms


def _csv_value(x: Any) -> Any:
    if x is None:
        return ""
    if isinstance(x, date):
        return x.isoformat()
    if isinstance(x, float):
        return repr(x)
    return x


def write_trades_csv(path: Path, version: str, cell: str, trades: list[LTrade]) -> None:
    cols = [f.name for f in fields(LTrade)]
    with path.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["version", "cell", *cols])
        for t in trades:
            w.writerow([version, cell, *[_csv_value(getattr(t, c)) for c in cols]])


def slug(key: str) -> str:
    return key.replace(".", "_")


def cell_label(h: Hooks) -> str:
    parts = []
    if h.g is not None:
        parts.append(f"V1 g={h.g}")
    if h.h is not None:
        parts.append(f"V2 h={h.h}")
    if h.fill_anchor:
        parts.append("V3")
    return " + ".join(parts) if parts else "B1"


# --------------------------------------------------------------------------- #
# compute
# --------------------------------------------------------------------------- #
def load_inputs(log: Callable[[str], None]) -> dict[str, Any]:
    t0 = time.time()
    with session_scope() as s:
        snaps: dict[int, dict[str, Any]] = {}
        for sid in sorted({v.snapshot for v in VERSIONS}):
            snap = s.get(DataSnapshot, sid)
            if snap is None:
                raise IdentityError(f"data snapshot {sid} not found")
            snaps[sid] = {"key": snap.key, "symbols": list(snap.symbols_json)}
        universe = sorted({PROXY, *(x for sn in snaps.values() for x in sn["symbols"])})
        bars = {x: PriceSeries.load(s, x, START, END, source=SOURCE) for x in universe}
        recorded: dict[str, Any] = {}
        for v in VERSIONS:
            run = s.execute(
                text("SELECT costs_json, date_start, date_end FROM backtest_run WHERE id=:r"),
                {"r": v.run_id},
            ).one()
            metrics = {
                phase: {"n": int(n), "expectancy": float(e), "total_r": float(tot)}
                for phase, n, e, tot in s.execute(
                    text(
                        "SELECT phase, json_extract(metrics_json,'$.n_trades'), "
                        "json_extract(metrics_json,'$.expectancy_r'), "
                        "json_extract(metrics_json,'$.total_return_r') FROM backtest_metric WHERE "
                        "run_id=:r AND segment='all' AND phase IN ('in_sample','out_of_sample')"
                    ),
                    {"r": v.run_id},
                )
            }
            # Gate 1 (development walk-forward folds) only; no other gate is read.
            folds_json = s.execute(
                text(
                    "SELECT json_extract(g.value,'$.evidence.folds') FROM "
                    "strategy_promotion_evaluation e, json_each(e.gates_json) g WHERE e.id=:e AND "
                    "json_extract(g.value,'$.number')=1"
                ),
                {"e": v.eval_id},
            ).scalar_one()
            costs = run[0] if isinstance(run[0], dict) else json.loads(run[0])
            recorded[v.key] = {
                "run_id": v.run_id,
                "eval_id": v.eval_id,
                "costs": costs,
                "date_start": str(run[1]),
                "metrics": metrics,
                "folds": json.loads(folds_json) if isinstance(folds_json, str) else folds_json,
            }

    rows = 0
    first: date | None = None
    last: date | None = None
    for sym, ps in bars.items():
        if not len(ps):
            continue
        ds = ps.dates
        if any(b <= a for a, b in pairwise(ds)):
            raise IdentityError(f"{sym}: session dates are not strictly increasing")
        if ds[0] < START or ds[-1] > END or ds[-1] >= PRE_SEALED_BOUND:
            raise IdentityError(f"{sym}: a bar outside {START}..{END} was loaded")
        rows += len(ps)
        first = ds[0] if first is None else min(first, ds[0])
        last = ds[-1] if last is None else max(last, ds[-1])
    log(f"loaded {len(bars)} symbols, {rows} bars, {first}..{last} in {time.time() - t0:.1f}s")
    return {
        "snaps": snaps,
        "bars": bars,
        "recorded": recorded,
        "bar_stats": {"symbols": len(bars), "rows": rows, "first": str(first), "last": str(last)},
    }


def run_version(
    v: VersionDef,
    inputs: dict[str, Any],
    regimes: dict[date, Any],
    years: dict[str, float],
    edges: list[date],
    out_dir: Path,
    log: Callable[[str], None],
) -> dict[str, Any]:
    t_start = time.time()
    bars = inputs["bars"]
    rec = inputs["recorded"][v.key]
    symbols = inputs["snaps"][v.snapshot]["symbols"]
    strategy = build_strategy(v.key)
    p = strategy.params
    if p.atr_window != 14:
        raise IdentityError(f"{v.key}: ATR window is {p.atr_window}, not 14")
    stop_mult, target_mult = float(p.stop_atr), float(p.target_atr)
    time_stop = (
        int(strategy._time_stop()) if hasattr(strategy, "_time_stop") else int(p.time_stop_bars)
    )

    cm = CostModel(
        commission_per_share=0.0,
        commission_min_per_order=0.0,
        slippage_bps=3.0,
        half_spread_fill_penalty=True,
    )
    my_costs = {
        "commission_per_share": cm.commission_per_share,
        "commission_min_per_order": cm.commission_min_per_order,
        "slippage_bps": cm.slippage_bps,
        "half_spread_fill_penalty": cm.half_spread_fill_penalty,
    }
    if my_costs != rec["costs"]:
        raise IdentityError(f"{v.key}: cost model {my_costs} differs from recorded {rec['costs']}")
    if rec["date_start"] != START.isoformat():
        raise IdentityError(f"{v.key}: recorded window start {rec['date_start']} differs")
    # identical expression to backtest/engine.py:94
    slip_base = (
        cm.slippage_bps + (SPREAD_BPS / 2 if cm.half_spread_fill_penalty else 0.0)
    ) / 10_000.0
    slip_stress = (STRESS_SLIPPAGE_BPS + STRESS_SPREAD_BPS / 2) / 10_000.0

    fn = signal_fn_for(strategy, regime_by_date=regimes)

    # ---- B0: the library engine, looped exactly as the runner loops it -------
    lib: dict[str, list[Any]] = {}
    boundary: dict[str, date] = {}
    run_syms: list[str] = []
    skipped_syms: list[str] = []
    is_lib: list[Any] = []
    oos_lib: list[Any] = []
    for sym in symbols:
        series = bars[sym]
        if len(series) < MIN_BARS:
            skipped_syms.append(sym)
            continue
        outcome = run_backtest(series, fn, cost_model=cm, warmup=WARMUP)
        b = _is_boundary(series)
        run_syms.append(sym)
        lib[sym] = outcome.trades
        boundary[sym] = b
        for tr in outcome.trades:
            (is_lib if tr.entry_date <= b else oos_lib).append(tr)
    m_is, m_oos = compute_metrics(is_lib), compute_metrics(oos_lib)
    all_lib = [tr for sym in run_syms for tr in lib[sym]]

    ident: dict[str, Any] = {
        "prereg_target": {"oos_n": v.prereg_oos_n, "oos_expectancy_4dp": v.prereg_oos_exp},
        "recorded_run_id": v.run_id,
        "recorded": rec["metrics"],
        "reproduced": {
            "in_sample": {
                "n": m_is.n_trades,
                "expectancy": m_is.expectancy_r,
                "total_r": m_is.total_return_r,
            },
            "out_of_sample": {
                "n": m_oos.n_trades,
                "expectancy": m_oos.expectancy_r,
                "total_r": m_oos.total_return_r,
            },
        },
    }
    ok_prereg = (
        m_oos.n_trades == v.prereg_oos_n and round(m_oos.expectancy_r, 4) == v.prereg_oos_exp
    )
    max_abs = 0.0
    ok_db = True
    for phase, m in (("in_sample", m_is), ("out_of_sample", m_oos)):
        r = rec["metrics"][phase]
        ok_db &= m.n_trades == r["n"]
        for mine, theirs in ((m.expectancy_r, r["expectancy"]), (m.total_return_r, r["total_r"])):
            max_abs = max(max_abs, abs(mine - theirs))
    ok_db &= max_abs <= 1e-9
    fold_rows = []
    ok_folds = True
    for k, rec_fold in enumerate(rec["folds"], start=1):
        rs = [tr.pnl_r for tr in all_lib if edges[k - 1] <= tr.entry_date < edges[k]]
        mean = (sum(rs) / len(rs)) if rs else 0.0
        if rec_fold["start"] != edges[k - 1].isoformat():
            ok_folds = False
        match = len(rs) == rec_fold["n_trades"] and abs(mean - rec_fold["expectancy_r"]) <= 5.001e-5
        ok_folds &= match
        fold_rows.append(
            {
                "fold": k,
                "start": edges[k - 1].isoformat(),
                "recorded_n": rec_fold["n_trades"],
                "recorded_expectancy_4dp": rec_fold["expectancy_r"],
                "reproduced_n": len(rs),
                "reproduced_expectancy": mean,
                "match": bool(match),
            }
        )
    ident.update(
        {
            "matches_prereg_4dp": bool(ok_prereg),
            "matches_recorded_row": bool(ok_db),
            "max_abs_diff_vs_recorded": max_abs,
            "gate1_folds": fold_rows,
            "matches_gate1_folds": bool(ok_folds),
        }
    )
    log(
        f"[{v.key}] B0 library: IS {m_is.n_trades} / {m_is.expectancy_r:+.6f}, OOS "
        f"{m_oos.n_trades} / {m_oos.expectancy_r:+.6f} (pre-registered {v.prereg_oos_n} / "
        f"{v.prereg_oos_exp:+.4f}); max |diff| vs recorded row {max_abs:.2e}; folds "
        f"match={ok_folds} [{time.time() - t_start:.1f}s]"
    )
    if not (ok_prereg and ok_db and ok_folds):
        raise IdentityError(
            f"{v.key}: B0 does not reproduce the recorded development rows: "
            f"{json.dumps(ident, default=str)}"
        )

    # ---- script-local engine, hooks off: must equal the library trade for trade
    caches = {sym: SignalCache(fn, bars[sym]) for sym in run_syms}

    def simulate(
        hooks: Hooks, slip: float, *, build_sim: bool = False
    ) -> tuple[list[LTrade], dict[str, list[Any]], Counter[str]]:
        trades: list[LTrade] = []
        sims: dict[str, list[Any]] = {}
        skips: Counter[str] = Counter()
        for sym in run_syms:
            lt, sm, sk = local_engine(
                bars[sym],
                caches[sym].get,
                slip=slip,
                warmup=WARMUP,
                hooks=hooks,
                stop_mult=stop_mult,
                target_mult=target_mult,
                build_simtrades=build_sim,
            )
            b = boundary[sym]
            for t in lt:
                t.sample = "IS" if t.entry_date <= b else "OOS"
                t.fold = fold_of(t.entry_date, edges)
            trades.extend(lt)
            sims[sym] = sm
            skips.update(sk)
        return trades, sims, skips

    b0_local, b0_sims, b0_skips = simulate(Hooks(), slip_base, build_sim=True)
    n_cmp = 0
    for sym in run_syms:
        if b0_sims[sym] != lib[sym]:
            raise IdentityError(
                f"{v.key}/{sym}: script-local engine (hooks off) differs from the library engine"
            )
        n_cmp += len(lib[sym])
    if n_cmp != len(b0_local) or n_cmp != m_is.n_trades + m_oos.n_trades:
        raise IdentityError(f"{v.key}: local/library trade counts differ")
    for lt_, tr in zip(b0_local, all_lib, strict=True):
        if lt_.engine_r != tr.pnl_r or lt_.entry_date != tr.entry_date or lt_.symbol != tr.symbol:
            raise IdentityError(
                f"{v.key}: local trade record does not line up with the library trade"
            )
    # ATR14 derived from U must equal the library ATR14 at the signal bar.
    atr_dev = 0.0
    for lt_ in b0_local:
        a = atr(bars[lt_.symbol], lt_.signal_idx, 14)
        atr_dev = max(atr_dev, abs(lt_.atr14 - a) / a)
        if lt_.target_signal is None or abs(
            (lt_.target_signal - lt_.close_t) - target_mult * a
        ) > 1e-9 * max(1.0, a):
            raise IdentityError(f"{v.key}: target is not close + {target_mult} x ATR14")
    if atr_dev > 1e-9:
        raise IdentityError(
            f"{v.key}: ATR14 from U deviates from the library ATR14 by {atr_dev:.2e}"
        )
    if any(lt_.sample not in ("IS", "OOS") for lt_ in b0_local):
        raise IdentityError("sample label missing")
    log(
        f"[{v.key}] local engine, hooks off: identical on {len(run_syms)} symbols / {n_cmp} "
        f"trades; max ATR dev {atr_dev:.1e} [{time.time() - t_start:.1f}s]"
    )

    # ---- cells ---------------------------------------------------------------
    b1_hooks = Hooks(invalid_open=True)
    cell_hooks: dict[str, Hooks] = {"B1": b1_hooks}
    for g in V1_GRID:
        cell_hooks[f"V1 g={g}"] = Hooks(invalid_open=True, g=g)
    for h in V2_GRID:
        cell_hooks[f"V2 h={h}"] = Hooks(invalid_open=True, h=h)
    cell_hooks["V3"] = Hooks(invalid_open=True, fill_anchor=True)

    trades_by_cell: dict[str, list[LTrade]] = {"B0": b0_local}
    cells: dict[str, Any] = {
        "B0": {
            **cell_metrics(b0_local, "engine_r", years),
            "r_unit": "engine R",
            "skips": dict(b0_skips),
        }
    }
    for name, hk in cell_hooks.items():
        tr, _, sk = simulate(hk, slip_base)
        trades_by_cell[name] = tr
        cells[name] = {
            **cell_metrics(tr, "stable_r", years),
            "r_unit": "stable R",
            "skips": dict(sk),
        }
        # post-conditions of each rule
        for t in tr:
            if t.open_raw <= t.stop_signal:
                raise IdentityError(
                    f"{name}: a trade entered with the open at or below the planned stop"
                )
            if hk.g is not None and not (t.open_raw <= t.close_t + hk.g * t.atr14):
                raise IdentityError(f"{name}: V1 limit violated")
            if hk.h is not None and not (t.open_raw >= t.close_t - hk.h * t.atr14):
                raise IdentityError(f"{name}: V2 rule violated")
            if hk.fill_anchor and abs((t.entry_fill - t.stop_used) - t.planned_risk) > 1e-9 * max(
                1.0, t.planned_risk
            ):
                raise IdentityError(f"{name}: V3 stop is not one planned risk unit below the fill")
    b1 = trades_by_cell["B1"]

    # ---- facts about the correction -----------------------------------------
    b0_stable = cell_metrics(b0_local, "stable_r", years)
    flagged = [t for t in b0_local if t.open_raw <= t.stop_signal]
    open_le_stop = {
        "n": len(flagged),
        "by_sample": {s: sum(1 for t in flagged if t.sample == s) for s in ("IS", "OOS")},
        "engine_r_mean": (sum(t.engine_r for t in flagged) / len(flagged)) if flagged else None,
        "engine_r_total": sum(t.engine_r for t in flagged),
        "engine_r_min": min((t.engine_r for t in flagged), default=None),
        "engine_r_max": max((t.engine_r for t in flagged), default=None),
        "stable_r_mean": (sum(t.stable_r for t in flagged) / len(flagged)) if flagged else None,
        "exit_reasons": dict(Counter(t.exit_reason for t in flagged)),
        "all_exit_on_entry_bar": all(t.bars_held == 0 for t in flagged),
        "n_fill_at_or_below_stop": sum(1 for t in flagged if t.entry_fill <= t.stop_signal),
        "booked_as_gain": _r_stats([t.engine_r for t in flagged if t.engine_r > 0]),
        "booked_as_loss": _r_stats([t.engine_r for t in flagged if t.engine_r <= 0]),
        "engine_r_total_by_sample": {
            s: sum(t.engine_r for t in flagged if t.sample == s) for s in ("IS", "OOS")
        },
        "gap_atr_mean": (sum(t.gap_atr for t in flagged) / len(flagged)) if flagged else None,
    }
    key0 = {(t.symbol, t.entry_date) for t in b0_local}
    key1 = {(t.symbol, t.entry_date) for t in b1}
    only_b1 = [t for t in b1 if (t.symbol, t.entry_date) not in key0]
    trade_sets = {
        "b0_n": len(b0_local),
        "b1_n": len(b1),
        "in_both": len(key0 & key1),
        "only_in_b0": len(key0 - key1),
        "only_in_b1": len(only_b1),
        "only_in_b1_stable_r_total": sum(t.stable_r for t in only_b1),
    }
    gaps = {
        "B1": {
            "all_trades": gap_stats([t.gap_atr for t in b1]),
            "entry_bar_losers": gap_stats(
                [t.gap_atr for t in b1 if t.bars_held == 0 and t.stable_r < 0]
            ),
            "entry_bar_exits": gap_stats([t.gap_atr for t in b1 if t.bars_held == 0]),
        },
        "B0": {
            "all_trades": gap_stats([t.gap_atr for t in b0_local]),
            "entry_bar_losers": gap_stats(
                [t.gap_atr for t in b0_local if t.bars_held == 0 and t.engine_r < 0]
            ),
            "entry_bar_exits": gap_stats([t.gap_atr for t in b0_local if t.bars_held == 0]),
        },
    }

    # ---- selection: in-sample only ------------------------------------------
    b1_is = cells["B1"]["IS"]

    def qualifies(name: str) -> bool:
        c = cells[name]["IS"]
        return bool(
            c["n"] > 0
            and c["expectancy"] > b1_is["expectancy"]
            and c["total_r_per_year"] > b1_is["total_r_per_year"]
        )

    def pick(names: list[tuple[float, str]]) -> tuple[float | None, list[str]]:
        q = [(par, nm) for par, nm in names if qualifies(nm)]
        if not q:
            return None, []
        # highest IS expectancy; ties -> higher IS total R per year, then smaller parameter
        best = max(
            q,
            key=lambda x: (
                cells[x[1]]["IS"]["expectancy"],
                cells[x[1]]["IS"]["total_r_per_year"],
                -x[0],
            ),
        )
        return best[0], [nm for _, nm in q]

    g_pick, v1_q = pick([(g, f"V1 g={g}") for g in V1_GRID])
    h_pick, v2_q = pick([(h, f"V2 h={h}") for h in V2_GRID])
    v3_pick = qualifies("V3")
    e_hooks = Hooks(invalid_open=True, g=g_pick, h=h_pick, fill_anchor=v3_pick)
    e_label = cell_label(e_hooks)
    has_candidate = e_label != "B1"
    selection = {
        "b1_is_expectancy": b1_is["expectancy"],
        "b1_is_total_r_per_year": b1_is["total_r_per_year"],
        "qualifies": {nm: qualifies(nm) for nm in cell_hooks if nm != "B1"},
        "v1_qualifying": v1_q,
        "v2_qualifying": v2_q,
        "v1_pick": g_pick,
        "v2_pick": h_pick,
        "v3_pick": bool(v3_pick),
        "e_star": e_label,
        "has_candidate": bool(has_candidate),
    }
    # The screen helper used by the sensitivity block must give this same selection.
    scr0 = screen_cells({nm: cells[nm]["IS"] for nm in cell_hooks if nm != "B1"}, b1_is)
    if (
        scr0["v1_pick"],
        scr0["v2_pick"],
        scr0["v3_pick"],
        scr0["e_star"],
        scr0["v1_qualifying"],
        scr0["v2_qualifying"],
        scr0["qualifies"],
    ) != (g_pick, h_pick, bool(v3_pick), e_label, v1_q, v2_q, selection["qualifies"]):
        raise IdentityError(f"{v.key}: the screen helper does not reproduce the selection")

    confirmation: dict[str, Any] = {"e_star": e_label, "has_candidate": bool(has_candidate)}
    e_trades = b1
    if has_candidate:
        e_trades, _, e_skips = simulate(e_hooks, slip_base)
        if e_label in trades_by_cell:  # single-component E*: must equal that cell
            same = [(a.symbol, a.entry_date, a.exit_date, a.stable_r) for a in e_trades] == [
                (a.symbol, a.entry_date, a.exit_date, a.stable_r) for a in trades_by_cell[e_label]
            ]
            if not same:
                raise IdentityError(f"{v.key}: E* re-simulation differs from its own cell")
        cells["E*"] = {
            **cell_metrics(e_trades, "stable_r", years),
            "r_unit": "stable R",
            "skips": dict(e_skips),
            "rule": e_label,
        }
        trades_by_cell["E*"] = e_trades

        b1_oos = [t for t in b1 if t.sample == "OOS"]
        e_oos = [t for t in e_trades if t.sample == "OOS"]
        boot = month_block_bootstrap(b1_oos, e_oos)
        c_b1, c_e = cells["B1"]["OOS"], cells["E*"]["OOS"]
        oos_diff = c_e["expectancy"] - c_b1["expectancy"]
        if abs(oos_diff - boot["observed_diff"]) > 1e-9:
            raise IdentityError("bootstrap observed difference does not equal the cell difference")
        total_ok = c_e["total_r_per_year"] >= c_b1["total_r_per_year"] - 0.10 * abs(
            c_b1["total_r_per_year"]
        )
        f_b1, f_e = fold_metrics(b1, "stable_r"), fold_metrics(e_trades, "stable_r")
        ref_sign = (oos_diff > 0) - (oos_diff < 0)
        folds = []
        same_sign = 0
        for fb, fe in zip(f_b1, f_e, strict=True):
            dk = (
                None
                if fb["expectancy"] is None or fe["expectancy"] is None
                else fe["expectancy"] - fb["expectancy"]
            )
            sgn = 0 if dk is None else (dk > 0) - (dk < 0)
            hit = bool(ref_sign != 0 and sgn == ref_sign)
            same_sign += hit
            folds.append(
                {
                    "fold": fb["fold"],
                    "start": edges[fb["fold"] - 1].isoformat(),
                    "b1_n": fb["n"],
                    "b1_expectancy": fb["expectancy"],
                    "e_n": fe["n"],
                    "e_expectancy": fe["expectancy"],
                    "diff": dk,
                    "same_sign_as_oos_diff": hit,
                }
            )
        # 11 bps per side, final candidate only
        b1_s, _, _ = simulate(b1_hooks, slip_stress)
        e_s, _, _ = simulate(e_hooks, slip_stress)
        cells["B1 @11bps"] = {**cell_metrics(b1_s, "stable_r", years), "r_unit": "stable R"}
        cells["E* @11bps"] = {
            **cell_metrics(e_s, "stable_r", years),
            "r_unit": "stable R",
            "rule": e_label,
        }
        diff_11 = cells["E* @11bps"]["OOS"]["expectancy"] - cells["B1 @11bps"]["OOS"]["expectancy"]
        confirmation.update(
            {
                "oos_b1_n": c_b1["n"],
                "oos_e_n": c_e["n"],
                "oos_b1_expectancy": c_b1["expectancy"],
                "oos_e_expectancy": c_e["expectancy"],
                "oos_diff": oos_diff,
                "bootstrap": boot,
                "oos_b1_total_r_per_year": c_b1["total_r_per_year"],
                "oos_e_total_r_per_year": c_e["total_r_per_year"],
                "total_r_per_year_ratio": (
                    (c_e["total_r_per_year"] / c_b1["total_r_per_year"])
                    if c_b1["total_r_per_year"]
                    else None
                ),
                "cond_total_r_per_year": bool(total_ok),
                "folds": folds,
                "folds_same_sign": int(same_sign),
                "cond_folds": bool(same_sign >= 3),
                "oos_b1_expectancy_11bps": cells["B1 @11bps"]["OOS"]["expectancy"],
                "oos_e_expectancy_11bps": cells["E* @11bps"]["OOS"]["expectancy"],
                "oos_diff_11bps": diff_11,
                "cond_11bps": bool(diff_11 > 0),
            }
        )

        # Descriptive only (added after review): the same difference split by sample
        # within each fold and by out-of-sample entry year.
        def _split(rb: list[float], re_: list[float]) -> dict[str, Any]:
            eb = (sum(rb) / len(rb)) if rb else None
            ee = (sum(re_) / len(re_)) if re_ else None
            return {
                "b1_n": len(rb),
                "b1_expectancy": eb,
                "e_n": len(re_),
                "e_expectancy": ee,
                "diff": _diff(ee, eb),
            }

        folds_by_sample = []
        for k in range(1, N_FOLDS + 1):
            for s in ("IS", "OOS"):
                rb = [t.stable_r for t in b1 if t.fold == k and t.sample == s]
                re_ = [t.stable_r for t in e_trades if t.fold == k and t.sample == s]
                if rb or re_:
                    folds_by_sample.append({"fold": k, "sample": s, **_split(rb, re_)})
        oos_years = sorted({t.entry_date.year for t in (*b1_oos, *e_oos)})
        confirmation["folds_by_sample"] = folds_by_sample
        confirmation["oos_by_entry_year"] = [
            {
                "year": y,
                **_split(
                    [t.stable_r for t in b1_oos if t.entry_date.year == y],
                    [t.stable_r for t in e_oos if t.entry_date.year == y],
                ),
            }
            for y in oos_years
        ]
    else:
        confirmation.update({"bootstrap": None, "p_one_sided": 1.0})

    # ---- descriptive sensitivity (added after adversarial review) -------------
    sensitivity, alt_arms = sensitivity_block(
        b0=b0_local,
        b1=b1,
        cell_trades={nm: trades_by_cell[nm] for nm in cell_hooks if nm != "B1"},
        e_trades=e_trades,
        e_label=e_label,
        has_candidate=bool(has_candidate),
        years=years,
        slip=slip_base,
        bars=bars,
    )
    if has_candidate:
        alt_arms["study"] = (
            [t for t in b1 if t.sample == "OOS"],
            [t for t in e_trades if t.sample == "OOS"],
        )

    # ---- per-trade tables ----------------------------------------------------
    write_trades_csv(out_dir / f"trades_B0_{slug(v.key)}.csv", v.key, "B0", b0_local)
    write_trades_csv(out_dir / f"trades_B1_{slug(v.key)}.csv", v.key, "B1", b1)
    write_trades_csv(
        out_dir / f"trades_Estar_{slug(v.key)}.csv", v.key, f"E* = {e_label}", e_trades
    )
    with (out_dir / f"trades_cells_{slug(v.key)}.csv").open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(
            [
                "version",
                "cell",
                "symbol",
                "signal_date",
                "entry_date",
                "exit_date",
                "sample",
                "fold",
                "bars_held",
                "exit_reason",
                "gap_atr",
                "entry_fill",
                "exit_fill",
                "planned_risk",
                "stable_r",
            ]
        )
        for name in cell_hooks:
            for t in trades_by_cell[name]:
                w.writerow(
                    [
                        v.key,
                        name,
                        t.symbol,
                        t.signal_date,
                        t.entry_date,
                        t.exit_date,
                        t.sample,
                        t.fold,
                        t.bars_held,
                        t.exit_reason,
                        repr(t.gap_atr),
                        repr(t.entry_fill),
                        repr(t.exit_fill),
                        repr(t.planned_risk),
                        repr(t.stable_r),
                    ]
                )

    log(
        f"[{v.key}] B1 IS {cells['B1']['IS']['n']} / {cells['B1']['IS']['expectancy']:+.4f}, OOS "
        f"{cells['B1']['OOS']['n']} / {cells['B1']['OOS']['expectancy']:+.4f}; E* = {e_label} "
        f"[{time.time() - t_start:.1f}s]"
    )
    return {
        "key": v.key,
        "snapshot": v.snapshot,
        "snapshot_key": inputs["snaps"][v.snapshot]["key"],
        "symbols_in_snapshot": len(symbols),
        "symbols_run": len(run_syms),
        "symbols_skipped": skipped_syms,
        "short_history_symbols": {
            s: {
                "bars": len(bars[s]),
                "first": str(bars[s].dates[0]),
                "is_boundary": str(boundary[s]),
            }
            for s in run_syms
            if len(bars[s]) != len(bars[PROXY])
        },
        "params": {
            "stop_atr": stop_mult,
            "target_atr": target_mult,
            "time_stop_bars": time_stop,
            "atr_window": 14,
        },
        "slip_base": slip_base,
        "slip_stress": slip_stress,
        "identity": ident,
        "local_engine_identity": {"symbols": len(run_syms), "trades": n_cmp, "identical": True},
        "atr_check_max_rel_dev": atr_dev,
        "cells": cells,
        "b0_trades_in_stable_r": b0_stable,
        "open_at_or_below_stop_b0": open_le_stop,
        "b1_vs_b0_trade_sets": trade_sets,
        "gap_distribution": gaps,
        "entry_bar_breakdown": {
            "B0": entry_bar_breakdown(b0_local, "engine_r"),
            "B1": entry_bar_breakdown(b1, "stable_r"),
            "E*": entry_bar_breakdown(e_trades, "stable_r"),
        },
        "selection": selection,
        "confirmation": confirmation,
        "sensitivity": sensitivity,
        "_arms": alt_arms,  # in memory only; removed before summary.json is written
        "seconds": time.time() - t_start,
    }


def compute(out_dir: Path) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    log_path = out_dir / "run.log"
    log_fh = log_path.open("w")
    t0 = time.time()

    def log(msg: str) -> None:
        line = f"{datetime.now(UTC).strftime('%H:%M:%SZ')} {msg}"
        print(line, flush=True)
        log_fh.write(line + "\n")
        log_fh.flush()

    inputs = load_inputs(log)
    bars = inputs["bars"]
    regimes = regime_lookup(bars[PROXY])
    full_boundary = _is_boundary(bars[PROXY])
    years = {
        "IS": ((full_boundary - START).days + 1) / 365.25,
        "OOS": (END - full_boundary).days / 365.25,
    }
    years["ALL"] = years["IS"] + years["OOS"]
    edges = fold_edges()
    log(
        f"full-history IS boundary {full_boundary}; years {years}; fold starts "
        f"{[e.isoformat() for e in edges[:-1]]}"
    )

    versions: dict[str, Any] = {}
    for v in VERSIONS:
        versions[v.key] = run_version(v, inputs, regimes, years, edges, out_dir, log)

    # Holm across the four versions; a version without a candidate has no test (p = 1).
    pvals = {
        k: (
            r["confirmation"]["bootstrap"]["p_one_sided"]
            if r["confirmation"]["has_candidate"]
            else 1.0
        )
        for k, r in versions.items()
    }
    adj = holm(pvals)
    for k, r in versions.items():
        c = r["confirmation"]
        c["p_one_sided"] = pvals[k]
        c["holm_p"] = adj[k]
        c["cond_holm"] = bool(c["has_candidate"] and adj[k] < ALPHA)
        if c["has_candidate"]:
            c["upgrade_candidate"] = bool(
                c["cond_holm"]
                and c["cond_total_r_per_year"]
                and c["cond_folds"]
                and c["cond_11bps"]
            )
            r["verdict"] = "upgrade candidate" if c["upgrade_candidate"] else "no upgrade"
        else:
            c["upgrade_candidate"] = False
            r["verdict"] = "no candidate (E* = B1): no upgrade"
        log(
            f"[{k}] E* = {c['e_star']}; p = {pvals[k]:.4f}; Holm p = {adj[k]:.4f}; verdict: "
            f"{r['verdict']}"
        )

    # ---- descriptive sensitivity (added after adversarial review) -------------
    # None of this feeds back into anything above. The Holm factor of a test is the
    # multiplier Holm applies to its p (4 for the smallest of four).
    order = [k for k, _ in sorted(pvals.items(), key=lambda kv: kv[1])]
    arms_by_version = {k: r.pop("_arms") for k, r in versions.items()}
    for k, r in versions.items():
        r["confirmation"]["holm_factor"] = len(order) - order.index(k)
    for mode in ALT_BASELINES:
        alt_p = {
            k: (
                r["sensitivity"]["baselines"][mode]["test"]["p_one_sided"]
                if r["confirmation"]["has_candidate"]
                else 1.0
            )
            for k, r in versions.items()
        }
        alt_adj = holm(alt_p)
        changed = [
            k
            for k, r in versions.items()
            if not r["sensitivity"]["baselines"][mode]["e_star_unchanged"]
        ]
        for k, r in versions.items():
            e = r["sensitivity"]["baselines"][mode]
            # Other versions whose in-sample screen would name a different candidate under
            # this baseline: that combination was not run, so its p is unknown. The floor
            # is the adjusted p this version would get if each of those had p = 0.
            others = [x for x in changed if x != k]
            rank = sum(1 for x in versions if x != k and x not in others and alt_p[x] < alt_p[k])
            e["p_one_sided"] = alt_p[k]
            e["holm_p_same_candidates"] = alt_adj[k]
            e["other_versions_with_a_different_candidate"] = others
            e["holm_p_floor"] = min(1.0, max(1, len(versions) - len(others) - rank) * alt_p[k])
    for k, r in versions.items():
        c = r["confirmation"]
        if not c["upgrade_candidate"]:
            continue
        t_rob = time.time()
        b_oos, e_oos = arms_by_version[k]["study"]
        first_oos = full_boundary + timedelta(days=1)
        rob = bootstrap_robustness(
            b_oos,
            e_oos,
            c["bootstrap"],
            c["holm_factor"],
            N_OTHER_SEEDS,
            full=True,
            oos_span=((first_oos.year, first_oos.month), (END.year, END.month)),
        )
        r["sensitivity"]["bootstrap_robustness"] = rob
        for mode in ALT_BASELINES:
            e = r["sensitivity"]["baselines"][mode]
            ab, ae = arms_by_version[k][mode]
            e["bootstrap_robustness"] = bootstrap_robustness(
                ab, ae, e["test"]["bootstrap"], c["holm_factor"], N_OTHER_SEEDS_ALT, full=False
            )
        alt_holm = {
            mode: r["sensitivity"]["baselines"][mode]["holm_p_same_candidates"]
            for mode in ALT_BASELINES
        }
        log(
            f"[{k}] sensitivity of the pass (descriptive): pooled p "
            f"{rob['pooled']['p']:.5f} over {rob['pooled']['resamples']:,} resamples; "
            f"{rob['other_seeds']['n_adjusted_p_below_alpha']} of {N_OTHER_SEEDS} other seeds "
            "pass; "
            + "; ".join(f"{mode}: Holm p {p:.4f}" for mode, p in alt_holm.items())
            + f" [{time.time() - t_rob:.1f}s]"
        )

    summary = {
        "study": "R3-E entry execution and the risk unit (engine item H14)",
        "preregistration": PREREG,
        "run_started_utc": datetime.fromtimestamp(t0, UTC).isoformat(timespec="seconds"),
        "seconds": time.time() - t0,
        "environment": {"python": platform.python_version(), "numpy": np.__version__},
        "window": {"start": START.isoformat(), "end": END.isoformat(), "source": SOURCE},
        "bars": inputs["bar_stats"],
        "costs": {
            "base_bps_per_side": 5.5,
            "stress_bps_per_side": 11.0,
            "stress_definition": f"slippage {STRESS_SLIPPAGE_BPS} bps + half of "
            f"a {STRESS_SPREAD_BPS} bps spread",
        },
        "is_boundary_full_history": full_boundary.isoformat(),
        "years": years,
        "fold_starts": [e.isoformat() for e in edges[:-1]],
        "bootstrap": {"resamples": N_RESAMPLES, "seed": SEED, "block": "calendar month of entry"},
        "holm": {"alpha": ALPHA, "p": pvals, "adjusted": adj},
        "revision": {
            "after_adversarial_review": True,
            "note": (
                "Per version, 'sensitivity', 'confirmation.folds_by_sample', "
                "'confirmation.oos_by_entry_year' and 'confirmation.holm_factor' were added after "
                "review. They are descriptive: not pre-registered, used by no selection, test or "
                "verdict, and computed without simulating any entry rule. Every other field is "
                "as in the pre-review run."
            ),
            "other_seeds": {
                "first": SEED + 1,
                "study_arms": N_OTHER_SEEDS,
                "each_alternative_baseline": N_OTHER_SEEDS_ALT,
            },
            "alternative_baselines": list(ALT_BASELINES),
        },
        "versions": versions,
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2, default=str) + "\n")
    log(f"wrote {out_dir / 'summary.json'} in {time.time() - t0:.1f}s total")
    log_fh.close()
    return summary


# --------------------------------------------------------------------------- #
# report
# --------------------------------------------------------------------------- #
MINUS = "\u2212"  # house style in docs/research: a real minus sign


def fr(x: float | None, nd: int = 4) -> str:
    return "—" if x is None else f"{x:+.{nd}f}".replace("-", MINUS)


def f1(x: float | None) -> str:
    return "—" if x is None else f"{x:+.1f}".replace("-", MINUS)


def fpct(x: float) -> str:
    return f"{x:+.1f}%".replace("-", MINUS)


def pc(x: float | None) -> str:
    return "—" if x is None else f"{100 * x:.1f}%"


def num(n: int) -> str:
    return f"{n:,}"


def md_table(headers: list[str], rows: list[list[str]], align: str | None = None) -> str:
    al = align or ("l" + "r" * (len(headers) - 1))
    sep = ["---" if a == "l" else "---:" for a in al]
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join(sep) + " |"]
    lines += ["| " + " | ".join(r) + " |" for r in rows]
    return "\n".join(lines)


ES = "E\\*"  # markdown-safe "E*"
CELL_ORDER = (
    "B0",
    "B1",
    "V1 g=0.3",
    "V1 g=0.6",
    "V1 g=1.0",
    "V2 h=0.3",
    "V2 h=0.6",
    "V2 h=1.0",
    "V3",
)
FAMILY_CELLS = CELL_ORDER[2:]
NUM_WORD = {1: "one", 2: "two", 3: "three", 4: "four"}


def _join(parts: list[str]) -> str:
    if len(parts) <= 1:
        return "".join(parts)
    return ", ".join(parts[:-1]) + " and " + parts[-1]


def _runs(nums: list[int]) -> str:
    """Row numbers as prose: [3, 4, 5, 7] -> "3 to 5 and 7"."""
    parts, i = [], 0
    while i < len(nums):
        j = i
        while j + 1 < len(nums) and nums[j + 1] == nums[j] + 1:
            j += 1
        if j == i:
            parts.append(str(nums[i]))
        elif j == i + 1:
            parts += [str(nums[i]), str(nums[j])]
        else:
            parts.append(f"{nums[i]} to {nums[j]}")
        i = j + 1
    return _join(parts)


def rule_words(sel: dict[str, Any]) -> str:
    parts = []
    if sel["v1_pick"] is not None:
        parts.append(
            f"skipping entries that open more than {sel['v1_pick']:g} ATR above the signal close"
        )
    if sel["v2_pick"] is not None:
        parts.append(
            f"skipping entries that open more than {sel['v2_pick']:g} ATR below the signal close"
        )
    if sel["v3_pick"]:
        parts.append("anchoring the stop and target to the fill")
    return _join(parts) if parts else "no change"


def yn(flag: bool) -> str:
    return "yes" if flag else "no"


def render(summary: dict[str, Any], out_dir: Path) -> str:
    vs = summary["versions"]
    keys = list(vs)
    years = summary["years"]
    boundary = summary["is_boundary_full_history"]
    fold_starts = summary["fold_starts"]
    conf = {k: vs[k]["confirmation"] for k in keys}
    passes = [k for k in keys if conf[k]["upgrade_candidate"]]
    cands = [k for k in keys if conf[k]["has_candidate"]]
    out: list[str] = []
    add = out.append

    def code(k: str) -> str:
        return f"`{k}`"

    # ------------------------------------------------------------------ lead
    corr = {
        k: vs[k]["cells"]["B1"]["OOS"]["expectancy"] - vs[k]["cells"]["B0"]["OOS"]["expectancy"]
        for k in keys
    }
    big = max(keys, key=lambda k: abs(corr[k]))
    ols = vs[big]["open_at_or_below_stop_b0"]
    rest = [k for k in keys if k != big]
    steps_big = vs[big]["sensitivity"]["correction_steps"]["OOS"]
    inv_big = vs[big]["sensitivity"]["invalid_open_entries"]["OOS"]
    others = [k for k in keys if k not in passes]
    # A pass "holds up" only if it survives each re-measurement of the baseline (section 5).
    fragile = {
        k: [
            m
            for m in ALT_BASELINES
            if vs[k]["sensitivity"]["baselines"][m]["holm_p_same_candidates"] >= ALPHA
        ]
        for k in passes
    }
    lead: list[str] = []
    if passes:
        one = len(passes) == 1
        if all(fragile[k] for k in passes):
            tail = (
                f"but {'that pass does' if one else 'those passes do'} not hold up and "
                f"{'is' if one else 'are'} best read as not confirmed"
            )
        else:
            tail = "see section 5 for how firm that is"
        if others:
            lead.append(
                f"{NUM_WORD[len(others)].capitalize()} of the four approved versions show no "
                f"upgrade; the {'fourth meets' if one else 'rest meet'} the pre-registered rule as "
                f"written, {tail}."
            )
        else:
            lead.append(f"All four approved versions meet the pre-registered rule, {tail}.")
        for k in passes:
            c = conf[k]
            sb_ = vs[k]["sensitivity"]["baselines"]
            at_open, lit = sb_["above_target_at_open"], sb_["b0_trades_minus_invalid"]
            n_art = vs[k]["sensitivity"]["above_target_entries"]["by_cell"]["B1"]["OOS"]["n"]
            art_share = 1 - at_open["test"]["oos_diff"] / c["oos_diff"]
            bit = (
                f"On {code(k)}, {rule_words(vs[k]['selection'])} lifts out-of-sample expectancy "
                f"from {fr(c['oos_b1_expectancy'])}R ({num(c['oos_b1_n'])} trades) to "
                f"{fr(c['oos_e_expectancy'])}R ({num(c['oos_e_n'])} trades) per unit of planned "
                f"risk, with a Holm-adjusted p of {c['holm_p']:.3f} against the 0.05 line"
            )
            if fragile[k]:
                bit += (
                    f"; but about {100 * art_share:.0f}% of that lift is the removal of {n_art} "
                    "baseline trades that the engine books as bought above their target and sold "
                    "at it on the same bar, a loss no live bracket would take, and the same test "
                    f"gives an adjusted p of {at_open['holm_p_same_candidates']:.3f} with those "
                    f"trades priced at the open and {lit['holm_p_same_candidates']:.3f} against "
                    "the corrected baseline read the other way its definition allows (section 5)"
                )
            lead.append(bit + ".")
        if others:
            moved = _join(
                [
                    f"{fr(conf[k]['oos_diff'])}R ({code(k)})"
                    for k in others
                    if conf[k]["has_candidate"]
                ]
            )
            min_p = min(conf[k]["p_one_sided"] for k in others)
            lead.append(
                f"On the other {NUM_WORD[len(others)]} the rules picked in-sample moved "
                f"out-of-sample expectancy by {moved}, none near significance (smallest one-sided "
                f"p {min_p:.2f})."
            )
    else:
        lead.append("No entry rule earned an upgrade on any of the four approved versions.")
        if cands:
            moved = _join([f"{fr(conf[k]['oos_diff'])}R ({code(k)})" for k in cands])
            min_h = min(conf[k]["holm_p"] for k in cands)
            lead.append(
                f"The rules picked in-sample moved out-of-sample expectancy by {moved}; the "
                f"smallest Holm-adjusted p is {min_h:.3f}."
            )
    correction = (
        "The measurement correction alone (B1: risk counted as planned the evening before, and no "
        "trade when the open is at or below the stop) lowers the recorded out-of-sample "
        f"expectancy of {code(big)} from {fr(vs[big]['cells']['B0']['OOS']['expectancy'])}R to "
        f"{fr(vs[big]['cells']['B1']['OOS']['expectancy'])}R: {fr(steps_big['risk_unit'])}R from "
        f"the risk unit, {fr(steps_big['entries_not_taken'])}R from not taking "
        f"{ols['by_sample']['OOS']} out-of-sample entries that opened at or below their stop "
        f"({f1(inv_big['stable_r_total'])}R in stable R; the engine had booked them at "
        f"{f1(ols['engine_r_total_by_sample']['OOS'])}R), and {fr(steps_big['re_simulation'])}R "
        "from the re-simulation that follows those skips (section 2). The other three move by "
        f"{_join([fr(corr[k]) + 'R' for k in rest])}."
        if corr[big] < 0
        else "The measurement correction alone (B1) moves recorded out-of-sample expectancy by "
        f"{_join([fr(corr[k]) + 'R (' + code(k) + ')' for k in keys])}."
    )

    add("# Results — R3-E: entry execution and the risk unit (engine item H14)")
    add("")
    add(
        f"Pre-registration: `{PREREG}` (commit 9bc9d24), followed as written. Script: "
        f"`scripts/r3/entry_execution.py`. Run {summary['run_started_utc'][:10]} on a read-only "
        f"scratch copy of the database. Development window only: `{summary['window']['source']}` "
        f"daily bars {summary['window']['start']} to {summary['window']['end']}; no later bar was "
        "loaded. No sealed look was taken and nothing was written to any database. Revised the "
        "same day after adversarial review: no pre-registered number changed; sections 2 and 5 "
        "gained the checks that show how little the one pass can carry (clarification 14)."
    )
    add("")
    add("**Answer.** " + " ".join(lead))
    add("")
    add("**The correction.** " + correction)
    add("")
    add(
        "R means result per unit of risk. *Engine R* divides by the distance from the fill to the "
        "stop (the library's unit). *Stable R* divides by the risk planned at the signal, U = "
        "signal close − stop, which is what an order sized the evening before actually risks. "
        "ATR is the 14-session average true range at the signal. IS is the in-sample (selection) "
        "part of each symbol's history, OOS the rest; the OOS part has been looked at by earlier "
        "work, so it is a confirmation sample, not an untouched holdout."
    )
    add("")
    # ------------------------------------------------------------------ 1
    add("## 1. Checks passed before any result was read")
    add("")
    rows = []
    for k in keys:
        v = vs[k]
        idn = v["identity"]
        rec, rep = idn["recorded"], idn["reproduced"]
        rows.append(
            [
                code(k),
                f"snapshot {v['snapshot']} ({v['symbols_run']} symbols)",
                str(idn["recorded_run_id"]),
                f"{num(rec['in_sample']['n'])} / {fr(rec['in_sample']['expectancy'])}",
                f"{num(rep['in_sample']['n'])} / {fr(rep['in_sample']['expectancy'])}",
                f"{num(rec['out_of_sample']['n'])} / {fr(rec['out_of_sample']['expectancy'])}",
                f"{num(rep['out_of_sample']['n'])} / {fr(rep['out_of_sample']['expectancy'])}",
                (
                    "0 (exact)"
                    if idn["max_abs_diff_vs_recorded"] == 0
                    else f"{idn['max_abs_diff_vs_recorded']:.1e}"
                ),
                f"{sum(1 for f in idn['gate1_folds'] if f['match'])} of {len(idn['gate1_folds'])}",
                f"identical, {num(v['local_engine_identity']['trades'])} trades",
            ]
        )
    add(
        md_table(
            [
                "Version",
                "Universe",
                "Recorded run",
                "IS recorded (n / R)",
                "IS reproduced",
                "OOS recorded (n / R)",
                "OOS reproduced",
                "Largest gap to recorded row",
                "Gate-1 folds matched",
                "Local engine copy, hooks off",
            ],
            rows,
            "lllrrrrrrl",
        )
    )
    add("")
    max_atr = max(vs[k]["atr_check_max_rel_dev"] for k in keys)
    add(
        "- **B0 reproduces the record.** The library engine, looped as "
        "`research/backtest_runner.py` loops it (bars loaded once, symbols under 60 bars skipped, "
        "30-bar warm-up, 5.5 bps per side, SPY regime series), gives the recorded development "
        "rows exactly: the four pre-registered out-of-sample targets to four decimals, the "
        "full-precision in-sample and out-of-sample rows, and all sixteen gate-1 fold rows."
    )
    add(
        "- **The script's copy of the engine loop is exact.** With every hook off it returns the "
        "same trades as the library engine on every symbol (every field of every trade equal; "
        "asserted in the script)."
    )
    add(
        "- **The risk unit is what it should be.** ATR14 taken from U ÷ stop multiple equals the "
        f"library's ATR14 at every signal (largest relative gap {max_atr:.0e})."
    )
    add(
        f"- **Data.** {num(summary['bars']['rows'])} bars for {summary['bars']['symbols']} "
        f"symbols, {summary['bars']['first']} to {summary['bars']['last']}. No symbol was "
        f"skipped. The in-sample part ends {boundary} for full-history symbols."
    )
    add("")

    # ------------------------------------------------------------------ 2
    add("## 2. The correction: B0 against B1 (fact, no test)")
    add("")
    add(
        "B0 is the library engine unchanged. B1 keeps the same signals and exits, measures each "
        "trade in stable R, and takes no trade when the entry bar opens at or below the stop; it "
        "is a re-simulation (clarification 2). The two middle columns are the steps in between: "
        "B0's own trades re-measured in stable R, then that same list without the entries that "
        "opened at or below the stop. That list is the other way the pre-registered definition "
        "of B1 can be read, and section 5 tests against it as well."
    )
    add("")
    rows = []
    for k in keys:
        v = vs[k]
        lit_all = v["sensitivity"]["b0_trades_minus_invalid_open"]
        for s, lab in (("IS", "IS"), ("OOS", "OOS"), ("ALL", "all")):
            b0, b1, b0s = v["cells"]["B0"][s], v["cells"]["B1"][s], v["b0_trades_in_stable_r"][s]
            rows.append(
                [
                    code(k) if s == "IS" else "",
                    lab,
                    num(b0["n"]),
                    fr(b0["expectancy"]),
                    fr(b0s["expectancy"]),
                    f"{num(lit_all[s]['n'])} / {fr(lit_all[s]['expectancy'])}",
                    num(b1["n"]),
                    fr(b1["expectancy"]),
                    fr(b1["expectancy"] - b0["expectancy"]),
                ]
            )
    add(
        md_table(
            [
                "Version",
                "Sample",
                "B0 trades",
                "B0 expectancy (engine R)",
                "Same B0 trades in stable R",
                "…without the entries opening at or below the stop (n / stable R)",
                "B1 trades",
                "B1 expectancy (stable R)",
                "B1 − B0",
            ],
            rows,
            "llrrrrrrr",
        )
    )
    add("")
    add(
        "**The correction in three steps** (change in expectancy, R; the three steps add up to "
        "B1 − B0)."
    )
    add("")
    rows = []
    for k in keys:
        st_all = vs[k]["sensitivity"]["correction_steps"]
        for s, lab in (("IS", "IS"), ("OOS", "OOS"), ("ALL", "all")):
            st = st_all[s]
            rows.append(
                [
                    code(k) if s == "IS" else "",
                    lab,
                    fr(st["risk_unit"]),
                    fr(st["entries_not_taken"]),
                    fr(st["re_simulation"]),
                    fr(st["total"]),
                ]
            )
    add(
        md_table(
            [
                "Version",
                "Sample",
                "Risk unit (engine R to stable R)",
                "Entries opening at or below the stop not taken",
                "Re-simulation after those skips",
                "B1 − B0",
            ],
            rows,
            "llrrrr",
        )
    )
    add("")
    add(
        "**Entries that opened at or below the stop under B0, and what the engine booked for "
        "them.**"
    )
    add("")
    rows = []
    for k in keys:
        o = vs[k]["open_at_or_below_stop_b0"]
        if o["n"] == 0:
            rows.append([code(k), "0", "0 / 0", "—", "—", "—", "—", "—", "—"])
            continue
        gain, loss = o["booked_as_gain"], o["booked_as_loss"]
        inv = vs[k]["sensitivity"]["invalid_open_entries"]
        rows.append(
            [
                code(k),
                str(o["n"]),
                f"{o['by_sample']['IS']} / {o['by_sample']['OOS']}",
                (
                    f"{gain['n']} at {fr(gain['mean'], 2)}R on average ({fr(gain['min'], 2)} to "
                    f"{fr(gain['max'], 2)})"
                    if gain["n"]
                    else "0"
                ),
                (
                    f"{loss['n']} at {fr(loss['mean'], 2)}R on average ({fr(loss['min'], 2)} to "
                    f"{fr(loss['max'], 2)})"
                    if loss["n"]
                    else "0"
                ),
                f1(o["engine_r_total"]),
                f"{f1(o['engine_r_total_by_sample']['IS'])} / "
                f"{f1(o['engine_r_total_by_sample']['OOS'])}",
                f"{f1(inv['IS']['stable_r_total'])} / {f1(inv['OOS']['stable_r_total'])}",
                fr(o["gap_atr_mean"], 2),
            ]
        )
    add(
        md_table(
            [
                "Version",
                "Trades",
                "IS / OOS",
                "Booked as a gain",
                "Booked as a loss",
                "Total engine R booked",
                "Total IS / OOS",
                "Same entries in stable R, IS / OOS",
                "Mean opening gap (ATR)",
            ],
            rows,
            "lrrllrrrr",
        )
    )
    add("")
    gain_means = [
        vs[k]["open_at_or_below_stop_b0"]["booked_as_gain"]["mean"]
        for k in keys
        if vs[k]["open_at_or_below_stop_b0"]["n"]
        and vs[k]["open_at_or_below_stop_b0"]["booked_as_gain"]["n"]
    ]
    add(
        'All of them close on the entry bar as a "stop" at the stop price. Most are booked as a '
        "gain "
        + (
            f"({fr(min(gain_means), 2)}R to {fr(max(gain_means), 2)}R on average by " f"version): "
            if gain_means
            else ": "
        )
        + 'the fill is below the stop, so "selling at the stop" is a sale above the purchase '
        "price, a trade that could not have happened. A few are booked as a large loss: when the "
        "fill lands within about 5.5 bps of the stop, the engine's risk unit shrinks to almost "
        "nothing and the two-way cost alone becomes many R. B1 takes none of these."
    )
    add("")
    sets_bits = []
    for k in keys:
        ts = vs[k]["b1_vs_b0_trade_sets"]
        se = vs[k]["sensitivity"]["resimulation_side_effects"]
        n_inv = se["b0_not_in_b1_invalid_open"]["ALL"]["n"]
        n_dis = se["b0_not_in_b1_displaced"]["ALL"]["n"]
        if n_inv + n_dis != ts["only_in_b0"] or se["new_in_b1"]["ALL"]["n"] != ts["only_in_b1"]:
            raise IdentityError(f"{k}: B0/B1 trade-set counts do not add up")
        split = f" ({n_inv} that opened at or below the stop, {n_dis} displaced)" if n_dis else ""
        sets_bits.append(f"{code(k)} {ts['only_in_b0']} dropped{split} / {ts['only_in_b1']} new")
    se_big = vs[big]["sensitivity"]["resimulation_side_effects"]
    add(
        "B1 is a re-simulation: a symbol freed by a skipped entry can take a signal B0 never "
        "reached, and that can displace a later B0 trade. Trades in B0 but not B1, and in B1 but "
        "not B0: " + "; ".join(sets_bits) + ". Every trade present in both has the "
        "same exit and the same stable R (checked on the per-trade tables). The last step of the "
        f"table above is those side effects: out-of-sample, for {code(big)}, "
        f"{se_big['new_in_b1']['OOS']['n']} new trades totalling "
        f"{f1(se_big['new_in_b1']['OOS']['stable_r_total'])}R and "
        f"{se_big['b0_not_in_b1_displaced']['OOS']['n']} displaced trades that had totalled "
        f"{f1(se_big['b0_not_in_b1_displaced']['OOS']['stable_r_total'])}R."
    )
    add("")

    add("**Entry-bar exits (trades closed on the bar they were opened).**")
    add("")
    rows = []
    for k in keys:
        v = vs[k]
        for s in ("IS", "OOS"):
            b0, b1 = v["cells"]["B0"][s], v["cells"]["B1"][s]
            rows.append(
                [
                    code(k) if s == "IS" else "",
                    s,
                    f"{pc(b0['entry_bar_share'])} ({b0['entry_bar_n']})",
                    fr(b0["entry_bar_mean_r"]),
                    f1(b0["entry_bar_total_r"]),
                    f"{pc(b1['entry_bar_share'])} ({b1['entry_bar_n']})",
                    fr(b1["entry_bar_mean_r"]),
                    f1(b1["entry_bar_total_r"]),
                ]
            )
    add(
        md_table(
            [
                "Version",
                "Sample",
                "B0 share (n)",
                "B0 mean (engine R)",
                "B0 total R",
                "B1 share (n)",
                "B1 mean (stable R)",
                "B1 total R",
            ],
            rows,
            "llrrrrrr",
        )
    )
    add("")
    tcs = vs.get("trend_continuation.short_swing")
    if tcs is not None:
        eb = tcs["cells"]["B0"]["ALL"]
        same = (
            eb["entry_bar_n"] == 118
            and round(eb["entry_bar_mean_r"], 4) == -0.8338
            and round(eb["entry_bar_total_r"], 2) == -98.39
        )
        add(
            "Cross-check: B0's whole-window bucket for `trend_continuation.short_swing` is "
            f"{eb['entry_bar_n']} trades at {fr(eb['entry_bar_mean_r'])}R, "
            f"{fr(eb['entry_bar_total_r'], 2)}R in total, which "
            + ("matches" if same else "does NOT match")
            + " the figure recorded in `docs/research/diagnostics/v3_duration_exits.md` §6(a) "
            f"(118 trades, {MINUS}0.8338R, {MINUS}98.39R)."
        )
        add("")
    add(
        "**What B1's entry-bar exits are** (description of the saved B1 trades; not a "
        "pre-registered metric). Each pair is trades / total stable R."
    )
    add("")
    rows = []
    for k in keys:
        for s in ("IS", "OOS"):
            b = vs[k]["entry_bar_breakdown"]["B1"][s]

            def pair(name: str, b: dict[str, Any] = b) -> str:
                return f"{b[name]['n']} / {f1(b[name]['total_r'])}"

            rows.append(
                [
                    code(k) if s == "IS" else "",
                    s,
                    pair("all"),
                    pair("stop"),
                    pair("target_open_above_target"),
                    pair("target_reached_intraday"),
                    pair("end_of_data"),
                ]
            )
    add(
        md_table(
            [
                "Version",
                "Sample",
                "All entry-bar exits",
                "Stop hit during the entry bar",
                "Opened above the target, closed at the target",
                "Target reached during the entry bar",
                "Last bar of the data",
            ],
            rows,
            "llrrrrr",
        )
    )
    add("")
    add(
        'The third column is a second engine quirk that B1 keeps ("same exits as B0"): an entry '
        "that opens above its target is closed at the target price on the same bar, below where "
        "it was bought, so it is booked as a loss. V1 removes those entries and V3 moves the "
        "target above the fill."
    )
    add("")

    add(
        "**Opening gap in ATR units, (open − signal close) ÷ ATR14: all B1 trades against B1's "
        "entry-bar losers** (whole development window)."
    )
    add("")
    rows = []
    for k in keys:
        g = vs[k]["gap_distribution"]["B1"]
        for name, lab in (("all_trades", "all trades"), ("entry_bar_losers", "entry-bar losers")):
            d = g[name]
            rows.append(
                [
                    code(k) if name == "all_trades" else "",
                    lab,
                    num(d["n"]),
                    fr(d["mean"], 2),
                    fr(d["p05"], 2),
                    fr(d["p25"], 2),
                    fr(d["p50"], 2),
                    fr(d["p75"], 2),
                    fr(d["p95"], 2),
                    fr(d["min"], 2),
                    fr(d["max"], 2),
                ]
            )
    add(
        md_table(
            [
                "Version",
                "Group",
                "Trades",
                "Mean",
                "5%",
                "25%",
                "Median",
                "75%",
                "95%",
                "Min",
                "Max",
            ],
            rows,
            "llrrrrrrrrr",
        )
    )
    add("")
    rows = []
    for k in keys:
        g = vs[k]["gap_distribution"]["B1"]
        for name, lab in (("all_trades", "all trades"), ("entry_bar_losers", "entry-bar losers")):
            d = g[name]
            rows.append(
                [
                    code(k) if name == "all_trades" else "",
                    lab,
                    pc(d["share_below_-1.0"]),
                    pc(d["share_below_-0.6"]),
                    pc(d["share_below_-0.3"]),
                    pc(d["share_above_+0.3"]),
                    pc(d["share_above_+0.6"]),
                    pc(d["share_above_+1.0"]),
                ]
            )
    add(
        md_table(
            [
                "Version",
                "Group",
                "Gap below −1.0",
                "below −0.6",
                "below −0.3",
                "above +0.3",
                "above +0.6",
                "above +1.0",
            ],
            rows,
            "llrrrrrr",
        )
    )
    add("")
    med_l = [vs[k]["gap_distribution"]["B1"]["entry_bar_losers"]["p50"] for k in keys]
    med_a = [vs[k]["gap_distribution"]["B1"]["all_trades"]["p50"] for k in keys]
    weak_l = [vs[k]["gap_distribution"]["B1"]["entry_bar_losers"]["share_below_-0.3"] for k in keys]
    weak_a = [vs[k]["gap_distribution"]["B1"]["all_trades"]["share_below_-0.3"] for k in keys]
    add(
        "In every version the entry-bar losers sit on weaker opens than trades in general: their "
        f"median gap is {fr(min(med_l), 2)} to {fr(max(med_l), 2)} ATR against "
        f"{fr(min(med_a), 2)} to {fr(max(med_a), 2)} ATR for all trades, and {pc(min(weak_l))} to "
        f"{pc(max(weak_l))} of them opened more than 0.3 ATR below the signal close against "
        f"{pc(min(weak_a))} to {pc(max(weak_a))} of all trades. The same tables for B0 are in "
        "`summary.json`."
    )
    add("")

    # ------------------------------------------------------------------ 3
    add("## 3. Every pre-registered cell")
    add("")
    add(
        "Each cell is a full re-simulation of B1 plus one rule. V1 g: enter only if open ≤ "
        "signal close + g × ATR14. V2 h: enter only if open ≥ signal close − h × ATR14. V3: stop "
        "and target recomputed from the fill with the version's own ATR multiples. B0 is in "
        f"engine R; every other row is in stable R. Total R per year divides by {years['IS']:.2f} "
        f"years in-sample and {years['OOS']:.2f} years out-of-sample for every cell. "
        f'"Raises both" is the pre-registered screen: higher in-sample expectancy and higher '
        f"in-sample total R per year than B1."
    )
    add("")
    for k in keys:
        v = vs[k]
        p = v["params"]
        sel = v["selection"]
        add(
            f"### {code(k)} — snapshot {v['snapshot']}, {v['symbols_run']} symbols; stop "
            f"{p['stop_atr']:g} ATR, target {p['target_atr']:g} ATR, time stop "
            f"{p['time_stop_bars']} bars"
        )
        add("")
        order = list(CELL_ORDER)
        e_label = sel["e_star"]
        show_e = sel["has_candidate"] and e_label not in CELL_ORDER
        for s, lab in (("IS", "In-sample cell"), ("OOS", "Out-of-sample cell")):
            b1n = v["cells"]["B1"][s]["n"]
            rows = []
            for name in order + (["E*"] if show_e else []):
                c = v["cells"][name][s]
                label = f"{ES} = {e_label}" if name == "E*" else name
                if name == e_label:
                    label += f" (= {ES})"
                row = [
                    label,
                    num(c["n"]),
                    "—" if name in ("B0", "B1") else fpct(100 * (c["n"] / b1n - 1)),
                    fr(c["expectancy"]),
                    f1(c["total_r_per_year"]),
                    f"{pc(c['entry_bar_share'])} ({c['entry_bar_n']})",
                    fr(c["entry_bar_mean_r"]),
                    fr(c["worst"], 2),
                ]
                if s == "IS":
                    row.append("—" if name in ("B0", "B1", "E*") else yn(sel["qualifies"][name]))
                rows.append(row)
            hdr = [
                lab,
                "Trades",
                "Trades vs B1",
                "Expectancy (R)",
                "Total R per year",
                "Entry-bar exits (n)",
                "Entry-bar mean R",
                "Worst trade (R)",
            ]
            if s == "IS":
                hdr.append("Raises both vs B1")
            add(md_table(hdr, rows, "l" + "r" * (len(hdr) - 1)))
            add("")

    # ------------------------------------------------------------------ 4
    add("## 4. Selection on the in-sample trades only")
    add("")
    rows = []
    tie_notes = []
    for k in keys:
        v = vs[k]
        sel = v["selection"]
        rows.append(
            [
                code(k),
                ", ".join(n.split("=")[1] for n in sel["v1_qualifying"]) or "none",
                "—" if sel["v1_pick"] is None else f"g = {sel['v1_pick']}",
                ", ".join(n.split("=")[1] for n in sel["v2_qualifying"]) or "none",
                "—" if sel["v2_pick"] is None else f"h = {sel['v2_pick']}",
                yn(sel["v3_pick"]),
                sel["e_star"] if sel["has_candidate"] else "B1 (no candidate)",
            ]
        )
        for fam, qual in (("V1", sel["v1_qualifying"]), ("V2", sel["v2_qualifying"])):
            if len(qual) > 1:
                by_exp = max(qual, key=lambda n: v["cells"][n]["IS"]["expectancy"])
                by_tot = max(qual, key=lambda n: v["cells"][n]["IS"]["total_r_per_year"])
                if by_exp != by_tot:
                    c_exp, c_tot = v["cells"][by_exp]["IS"], v["cells"][by_tot]["IS"]
                    tie_notes.append(
                        f"{code(k)} {fam}: highest in-sample expectancy is {by_exp.split(' ')[1]} "
                        f"({fr(c_exp['expectancy'])}R, {f1(c_exp['total_r_per_year'])}R per "
                        f"year), highest in-sample total R per year is {by_tot.split(' ')[1]} "
                        f"({fr(c_tot['expectancy'])}R, {f1(c_tot['total_r_per_year'])}R per year)"
                    )
    add(
        md_table(
            [
                "Version",
                "V1 cells that raise both (g)",
                "V1 pick",
                "V2 cells that raise both (h)",
                "V2 pick",
                "V3 raises both",
                f"Candidate {ES}",
            ],
            rows,
            "lllllll",
        )
    )
    add("")
    add(
        "Where several cells of one family qualify, the script takes the one with the highest "
        "in-sample expectancy (clarification 5). "
        + (
            "That choice changed the pick in one place — "
            + "; ".join(tie_notes)
            + ". The alternative combination was not run by the study (section 5)."
            if tie_notes
            else "No pick depended on that choice."
        )
    )
    add("")

    # ------------------------------------------------------------------ 5
    add("## 5. Confirmation on the out-of-sample trades, and the decision rule")
    add("")
    add(
        f"One test per version: out-of-sample expectancy of {ES} minus that of B1, one-sided, "
        f"calendar-month block bootstrap ({summary['bootstrap']['resamples']:,} resamples of "
        "entry months, the same months drawn for both arms, seed "
        f"{summary['bootstrap']['seed']}), Holm-adjusted across the four versions. Clarification "
        "8 gives the exact construction of p."
    )
    add("")
    rows = []
    for k in keys:
        c = conf[k]
        if not c["has_candidate"]:
            rows.append(
                [
                    code(k),
                    "B1 (no candidate)",
                    "—",
                    "—",
                    "—",
                    "—",
                    "—",
                    "1.0000",
                    f"{c['holm_p']:.4f}",
                ]
            )
            continue
        b = c["bootstrap"]
        rows.append(
            [
                code(k),
                c["e_star"],
                f"{num(c['oos_b1_n'])} / {fr(c['oos_b1_expectancy'])}",
                f"{num(c['oos_e_n'])} / {fr(c['oos_e_expectancy'])}",
                fr(c["oos_diff"]),
                f"{b['bootstrap_se']:.4f}",
                f"{b['months']} ({b['first_month']} to {b['last_month']})",
                f"{c['p_one_sided']:.4f}",
                f"{c['holm_p']:.4f}",
            ]
        )
    add(
        md_table(
            [
                "Version",
                f"{ES}",
                "B1 OOS (n / R)",
                f"{ES} OOS (n / R)",
                "Difference (R)",
                "Bootstrap SE",
                "Entry months resampled",
                "p, one-sided",
                "Holm-adjusted p",
            ],
            rows,
            "llrrrrrrr",
        )
    )
    add("")
    add("**The four conditions of the decision rule** (all must hold).")
    add("")
    rows = []
    for k in keys:
        c = conf[k]
        if not c["has_candidate"]:
            rows.append([code(k), "—", "—", "—", "—", "**no candidate: no upgrade**"])
            continue
        rows.append(
            [
                code(k),
                f"{c['holm_p']:.4f}: {yn(c['cond_holm'])}",
                f"{f1(c['oos_e_total_r_per_year'])} vs {f1(c['oos_b1_total_r_per_year'])} "
                f"({100 * c['total_r_per_year_ratio']:.0f}%): {yn(c['cond_total_r_per_year'])}",
                f"{c['folds_same_sign']} of 4: {yn(c['cond_folds'])}",
                f"{fr(c['oos_diff_11bps'])}: {yn(c['cond_11bps'])}",
                (
                    (
                        "**upgrade candidate** by the rule as run; it does not hold up (below)"
                        if fragile.get(k)
                        else "**upgrade candidate**"
                    )
                    if c["upgrade_candidate"]
                    else "**no upgrade**"
                ),
            ]
        )
    add(
        md_table(
            [
                "Version",
                "Holm p < 0.05",
                f"Total R per year, {ES} vs B1 (not more than 10% below)",
                "Folds with the same sign as the OOS difference (at least 3)",
                "Difference at 11 bps per side (> 0)",
                "Verdict",
            ],
            rows,
            "lrrrrl",
        )
    )
    add("")
    add(
        f"**Expectancy of {ES} minus B1 in the four gate-1 calendar folds** (whole development "
        f"window; trades B1 → {ES} in brackets). Folds 1 and 2 lie wholly inside the selection "
        "sample, fold 3 straddles the boundary and fold 4 is wholly out-of-sample."
    )
    add("")
    rows = []
    for k in keys:
        c = conf[k]
        if not c["has_candidate"]:
            rows.append([code(k), "—", "—", "—", "—"])
            continue
        rows.append(
            [code(k)]
            + [f"{fr(f['diff'])} ({num(f['b1_n'])} → {num(f['e_n'])})" for f in c["folds"]]
        )
    add(
        md_table(
            ["Version"] + [f"Fold {i + 1}, from {d}" for i, d in enumerate(fold_starts)],
            rows,
            "lrrrr",
        )
    )
    add("")
    add(
        f"**At 11 bps per side** (slippage 6 bps plus half of a 10 bps spread; B1 and {ES} only), "
        "out-of-sample."
    )
    add("")
    rows = []
    for k in keys:
        c = conf[k]
        if not c["has_candidate"]:
            rows.append([code(k), "—", "—", "—"])
            continue
        cb, ce = vs[k]["cells"]["B1 @11bps"]["OOS"], vs[k]["cells"]["E* @11bps"]["OOS"]
        rows.append(
            [
                code(k),
                f"{num(cb['n'])} / {fr(cb['expectancy'])}",
                f"{num(ce['n'])} / {fr(ce['expectancy'])}",
                fr(c["oos_diff_11bps"]),
            ]
        )
    add(md_table(["Version", "B1 (n / R)", f"{ES} (n / R)", "Difference (R)"], rows, "lrrr"))
    add("")

    for k in passes:
        v, c = vs[k], conf[k]
        b = c["bootstrap"]
        sens = v["sensitivity"]
        rob = sens["bootstrap_robustness"]
        seeds, pooled, oc = rob["other_seeds"], rob["pooled"], rob["other_constructions"]
        loo = rob["leave_one_month_out"]
        fac = c["holm_factor"]
        alt = sens["baselines"]
        lit, at_open, removed = (
            alt["b0_trades_minus_invalid"],
            alt["above_target_at_open"],
            alt["above_target_removed"],
        )
        at = sens["above_target_entries"]
        art, art_e = at["by_cell"]["B1"], at["by_cell"]["E*"]
        n_art = art["OOS"]["n"]
        sel = v["selection"]
        p_ = v["params"]
        need = ALPHA / fac
        comp = []
        if sel["v1_pick"] is not None:
            v1_cell = v["cells"]["V1 g=" + str(sel["v1_pick"])]["OOS"]
            comp.append(f"V1 g={sel['v1_pick']} alone {fr(v1_cell['expectancy'])}R")
        if sel["v2_pick"] is not None:
            v2_cell = v["cells"]["V2 h=" + str(sel["v2_pick"])]["OOS"]
            comp.append(f"V2 h={sel['v2_pick']} alone {fr(v2_cell['expectancy'])}R")
        if sel["v3_pick"]:
            comp.append(f"V3 alone {fr(v['cells']['V3']['OOS']['expectancy'])}R")

        def under(x: float) -> str:
            return "yes" if x < ALPHA else "no"

        def p4(x: float) -> str:
            return f"{x:.4f}"

        same_base = f"{num(c['oos_b1_n'])} / {fr(c['oos_b1_expectancy'])}"
        same_diff = fr(c["oos_diff"])

        def alt_row(label: str, e: dict[str, Any]) -> list[str]:
            t = e["test"]
            return [
                label,
                f"{num(t['oos_base_n'])} / {fr(t['oos_base_expectancy'])}",
                fr(t["oos_diff"]),
                p4(t["p_one_sided"]),
                p4(e["holm_p_same_candidates"]),
                under(e["holm_p_same_candidates"]),
            ]

        def p_row(
            label: str,
            key: str,
            base: str = same_base,
            diff: str = same_diff,
            oc: dict[str, Any] = oc,
        ) -> list[str]:
            return [
                label,
                base,
                diff,
                p4(oc["p"][key]),
                p4(oc["adjusted_p"][key]),
                under(oc["adjusted_p"][key]),
            ]

        frames = rob["block_frames"]
        fr_entry, fr_span = frames["first_to_last_entry_month"], frames["whole_out_of_sample_span"]

        def frame_row(
            label: str, f: dict[str, Any], base: str = same_base, diff: str = same_diff
        ) -> list[str]:
            return [label, base, diff, p4(f["p"]), p4(f["adjusted_p"]), under(f["adjusted_p"])]

        rows = [
            [
                "1. Nothing: the pre-registered test as run",
                same_base,
                same_diff,
                p4(c["p_one_sided"]),
                p4(c["holm_p"]),
                under(c["holm_p"]),
            ],
            [
                f"2. {pooled['resamples']:,} resamples instead of {b['resamples']:,} "
                f"({seeds['n_seeds']:,} other seeds pooled)",
                same_base,
                same_diff,
                p4(pooled["p"]),
                p4(pooled["adjusted_p"]),
                under(pooled["adjusted_p"]),
            ],
            alt_row(
                f"3. The baseline's {n_art} above-target entries priced at the open, not at the "
                "target",
                at_open,
            ),
            alt_row(f"4. Those {n_art} entries left out of the baseline", removed),
            alt_row(
                "5. Baseline = B0's own trades without the entries opening at or below the stop "
                "(no re-simulation)",
                lit,
            ),
            p_row(
                "6. p = share of resamples with a difference of zero or less",
                "share_of_resamples_le_0",
            ),
            p_row(
                "7. Null centred on the bootstrap mean, not on the observed difference",
                "null_centred_on_bootstrap_mean",
            ),
            p_row(
                "8. Normal reference with the bootstrap standard error", "normal_with_bootstrap_se"
            ),
            p_row(
                f"9. Student t reference, {oc['t_df']} degrees of freedom, same standard error",
                "student_t_with_bootstrap_se",
            ),
            p_row(
                "10. Studentised bootstrap (each resample divided by its own standard error)",
                "studentised_bootstrap",
            ),
            frame_row(
                f"11. Blocks = every calendar month from the first to the last entry month "
                f"({fr_entry['months']}, of which {fr_entry['months_without_entry']} hold no "
                "entry)",
                fr_entry,
            ),
            frame_row(
                f"12. Blocks = every calendar month of the out-of-sample span "
                f"({fr_span['months']}, from {fr_span['first_month']})",
                fr_span,
            ),
        ]
        fail_rows = [int(r[0].split(".")[0]) for r in rows[1:] if r[5] == "no"]
        pass_rows = [int(r[0].split(".")[0]) for r in rows[1:] if r[5] == "yes"]

        add(f"### How firm the {code(k)} pass is")
        add("")
        add(
            'By the rule as written the verdict is "upgrade candidate". It does not hold up. Of '
            f"the {len(rows) - 1} single changes in the table below, {len(fail_rows)} turn the "
            f"pass into a fail (rows {_runs(fail_rows)}) and {len(pass_rows)} leave it a pass by "
            f"the same hair (rows {_runs(pass_rows)}); the result is best read as **not "
            "confirmed**. The table and the bullets that refer to its rows were added after "
            "adversarial review (clarification 14). They re-measure the saved trades of the two "
            "pre-registered arms and repeat the pre-registered bootstrap; no entry rule was "
            "simulated for them, and nothing in them enters the selection, the test or the "
            "verdict."
            if fragile.get(k)
            else 'By the rule as written the verdict is "upgrade candidate". The rows below '
            "re-measure the saved trades of the two pre-registered arms and repeat the "
            "pre-registered bootstrap (added after adversarial review, clarification 14); "
            "nothing in them enters the selection, the test or the verdict."
        )
        add("")
        add(
            f"**The same test with one thing changed at a time** ({ES} minus the baseline, "
            "out-of-sample, one-sided; the registered seed and the same month blocks unless the "
            f"row says otherwise). Adjusted p is p × {fac}, the Holm factor for this test; it "
            f"passes only below {ALPHA:g}, that is p below {need:g}."
        )
        add("")

        add(
            md_table(
                [
                    "What is changed",
                    "Baseline OOS (n / R)",
                    f"{ES} − baseline (R)",
                    "p, one-sided",
                    "Adjusted p",
                    f"Under {ALPHA:g}?",
                ],
                rows,
                "lrrrrl",
            )
        )
        add("")
        foot = []
        for label, mode in (
            ("row 3", "above_target_at_open"),
            ("row 4", "above_target_removed"),
            ("row 5", "b0_trades_minus_invalid"),
        ):
            e = alt[mode]
            if not e["e_star_unchanged"]:
                foot.append(
                    f"Under {label} the screen would name {e['screen']['e_star']} for this "
                    "version, which was not run."
                )
            for o in e["other_versions_with_a_different_candidate"]:
                o_alt = vs[o]["sensitivity"]["baselines"][mode]["screen"]["e_star"]
                foot.append(
                    f"Under {label} it would name {o_alt} for {code(o)} instead of "
                    f"{vs[o]['selection']['e_star']}; that combination was not run, and whatever "
                    f"it would give, this version's adjusted p is at least "
                    f"{p4(e['holm_p_floor'])}."
                )
        add(
            "Rows 3 to 5 apply the same re-measurement to every cell and repeat the in-sample "
            "screen. "
            + (
                "It names the same candidate for this version in each. "
                if all(alt[m]["e_star_unchanged"] for m in ALT_BASELINES)
                else ""
            )
            + (" ".join(foot) if foot else "No other version's candidate changes either.")
        )
        add("")
        art_share = 1 - at_open["test"]["oos_diff"] / c["oos_diff"]
        rb_open, rb_rem, rb_lit = (
            at_open["bootstrap_robustness"],
            removed["bootstrap_robustness"],
            lit["bootstrap_robustness"],
        )
        add(
            f"- **About {100 * art_share:.0f}% of the lift is a booking artefact in the "
            "baseline** (rows 3 and 4). B1 keeps B0's exits, as pre-registered. Among them are "
            f"{n_art} out-of-sample entries that opened above their target "
            f"({art['ALL']['n']} over the whole window): the engine closes each at the target "
            "price on the bar it was bought, below the purchase price, for "
            f"{f1(art['OOS']['stable_r_total'])}R in total "
            f"({f1(art['ALL']['stable_r_total'])}R over the whole window). In "
            f"{at['b1_bar_low_above_target']['OOS']} of the {n_art} the whole bar traded above "
            "the target, so the target price never traded that day "
            f"({at['b1_booked_exit_below_bar_low']['OOS']} if the booked sale price, the target "
            "less costs, is set against the bar's low). A sell limit that is below "
            f"the market when it is placed fills near the open; priced that way the {n_art} cost "
            f"{f1(at['b1_total_r_if_closed_at_open']['OOS'])}R (costs only), B1's out-of-sample "
            f"expectancy is {fr(at_open['test']['oos_base_expectancy'])}R rather than "
            f"{fr(c['oos_b1_expectancy'])}R, and the lift is {fr(at_open['test']['oos_diff'])}R "
            f"rather than {fr(c['oos_diff'])}R. {ES} holds {art_e['ALL']['n']} such entries (V1 "
            "skips them and V3 puts the target above the fill), so "
            f"{c['oos_diff'] - at_open['test']['oos_diff']:.4f}R of the lift is the removal of "
            "losses that no live bracket would take. That is more than the pass can spare: "
            f"{rob['exceedances_registered_seed']} of the {b['resamples']:,} null draws were at "
            "or above the observed difference, and a pass allows at most "
            f"{rob['exceedances_allowed_for_a_pass']}. It is not seed noise either: with the "
            "entries priced at the open "
            f"{rb_open['other_seeds']['n_adjusted_p_below_alpha']} of "
            f"{rb_open['other_seeds']['n_seeds']} other seeds pass (pooled p "
            f"{p4(rb_open['pooled']['p'])}, adjusted {p4(rb_open['pooled']['adjusted_p'])}); "
            f"with them left out, {rb_rem['other_seeds']['n_adjusted_p_below_alpha']} of "
            f"{rb_rem['other_seeds']['n_seeds']} (pooled p {p4(rb_rem['pooled']['p'])}, adjusted "
            f"{p4(rb_rem['pooled']['adjusted_p'])})."
        )
        add(
            "- **It depends on reading B1 as a re-simulation** (row 5, clarification 2). Against "
            "B0's own trades without the entries that opened at or below the stop, the baseline "
            f"is {num(lit['test']['oos_base_n'])} trades at "
            f"{fr(lit['test']['oos_base_expectancy'])}R and the test gives p "
            f"{p4(lit['test']['p_one_sided'])}, adjusted {p4(lit['holm_p_same_candidates'])} "
            f"({rb_lit['other_seeds']['n_adjusted_p_below_alpha']} of "
            f"{rb_lit['other_seeds']['n_seeds']} other seeds pass; pooled p "
            f"{p4(rb_lit['pooled']['p'])}). Which reading the pre-registration meant is for its "
            "author to say; under this one the rule gives no upgrade for this version (adjusted "
            f"p at least {p4(lit['holm_p_floor'])})."
        )
        add(
            "- **It depends on how the bootstrap p is formed** (rows 6 to 12, clarification 8). "
            'The script reads "null distribution" as the resampled differences recentred on '
            f"zero, which gives {p4(c['p_one_sided'])}. The share of resamples with a difference "
            f"of zero or less is {p4(oc['p']['share_of_resamples_le_0'])}; centring on the "
            f"bootstrap mean gives {p4(oc['p']['null_centred_on_bootstrap_mean'])}; a normal or "
            f"a t reference with the bootstrap standard error ({oc['bootstrap_se']:.4f}R) gives "
            f"{p4(oc['p']['normal_with_bootstrap_se'])} and "
            f"{p4(oc['p']['student_t_with_bootstrap_se'])}; a studentised bootstrap gives "
            f"{p4(oc['p']['studentised_bootstrap'])}. None of those is below {need:g}. The "
            "choice of blocks cuts both ways. The script resamples the "
            f"{b['months']} months that hold an entry. Counting the "
            f"{fr_entry['months_without_entry']} months inside that stretch with no entry as "
            f"blocks too gives {p4(fr_entry['p'])}, which is "
            f"{'a pass' if fr_entry['adjusted_p'] < ALPHA else 'a fail'}; counting every month "
            f"of the out-of-sample span from {fr_span['first_month']} gives "
            f"{p4(fr_span['p'])}, which is "
            f"{'a pass' if fr_span['adjusted_p'] < ALPHA else 'a fail'}. The 95% "
            f"percentile interval for the difference is {fr(b['pct_interval_95'][0])}R to "
            f"{fr(b['pct_interval_95'][1])}R."
        )
        add(
            "- **The margin is inside the simulation noise** (row 2). Adjusted p is "
            f"{p4(c['holm_p'])} against {ALPHA:g}. Pooling {seeds['n_seeds']:,} other seeds "
            f"({pooled['resamples']:,} resamples) gives p {p4(pooled['p'])}, adjusted "
            f"{p4(pooled['adjusted_p'])}; taken one seed at a time, "
            f"{num(seeds['n_adjusted_p_below_alpha'])} of the {seeds['n_seeds']:,} "
            f"({100 * seeds['share_adjusted_p_below_alpha']:.0f}%) pass and the rest do not. The "
            "seed was fixed in advance, so the verdict as run stands. Leaving out any one of the "
            f"{loo['months']} entry months and repeating the test, "
            f"{loo['n_adjusted_p_at_or_above_alpha']} of the {loo['months']} deletions fail."
        )
        reviewer_runs = (
            k == "trend_continuation.medium_swing"
            and sel["e_star"] == "V1 g=0.3 + V3"
            and c["oos_b1_n"] == 1936
            and c["oos_e_n"] == 1717
        )
        tie = any(n.startswith(code(k)) for n in tie_notes)
        add(
            "- **It depends on two more choices that only a new simulation could vary** "
            "(clarifications 3 and 5): keeping the planned stop as the validity test under V3, "
            "and "
            + (
                "picking among qualifying cells by in-sample expectancy (section 4). "
                if tie
                else "the pick rule among qualifying cells (which did not bind here). "
            )
            + "The study did not run the alternatives: they would be cells the pre-registration "
            "does not contain. "
            + (
                "An adversarial reviewer ran both outside the study, with an independently "
                "written engine loop that the review reports as matching every study cell trade "
                "for trade. Picking the V1 cell by in-sample total R per year names V1 g=1.0 + "
                "V3: out-of-sample 1,884 trades at +0.2133R, difference +0.0329R, p 0.0419, "
                "adjusted 0.1676. V3 without the planned-stop validity test: 1,768 trades at "
                "+0.2168R, difference +0.0364R, p 0.0397, adjusted 0.1588. Those are the "
                "reviewer's numbers, not study cells, and they were not re-run here."
                if reviewer_runs
                else "They remain not run."
            )
        )
        add(
            "- **The confirmation sample is short and covers one market stretch.** This version "
            f"has no out-of-sample entry before {b['first_month']}: the test rests on "
            f"{b['months']} entry months, {b['first_month']} to {b['last_month']}. That sample "
            "has also been inspected by earlier work on this version, so it is not an untouched "
            "holdout."
        )
        fbs = {(f["fold"], f["sample"]): f for f in c["folds_by_sample"]}
        f3i, f3o, f4o = fbs.get((3, "IS")), fbs.get((3, "OOS")), fbs.get((4, "OOS"))
        yrs = _join([f"{fr(y['diff'])}R ({y['year']})" for y in c["oos_by_entry_year"]])
        if c["folds_same_sign"] == 4 and f3i and f3o and f4o and (4, "IS") not in fbs:
            add(
                "- **What the fold condition adds, and what it does not.** The difference is "
                "positive in all 4 gate-1 folds, but folds 1 and 2 are the selection sample, "
                f"{num(f3i['b1_n'])} of the {num(f3i['b1_n'] + f3o['b1_n'])} B1 trades in fold 3 "
                f"are too, and fold 4 holds {num(f4o['b1_n'])} of the {num(c['oos_b1_n'])} "
                "out-of-sample trades the test already uses. Out-of-sample only, the difference "
                f"is {fr(f3o['diff'])}R in fold 3's part ({num(f3o['b1_n'])} → "
                f"{num(f3o['e_n'])} trades) and {fr(f4o['diff'])}R in fold 4; by entry year, "
                f"{yrs}. It is also positive at 11 bps per side ({fr(c['oos_diff_11bps'])}R), "
                f"and total R per year rises ({f1(c['oos_b1_total_r_per_year'])} to "
                f"{f1(c['oos_e_total_r_per_year'])}). Each part alone has a higher out-of-sample "
                f"point estimate than B1's {fr(c['oos_b1_expectancy'])}R ({_join(comp)}), but "
                "neither was tested on its own and both also drop the above-target entries."
            )
        else:
            add(
                f"- **Other conditions.** Same sign in {c['folds_same_sign']} of 4 folds; "
                f"difference at 11 bps {fr(c['oos_diff_11bps'])}R; by out-of-sample entry year, "
                f"{yrs}."
            )
        if sel["v1_pick"] is not None and p_["stop_atr"] > 0:
            g_rr = (p_["target_atr"] - 1.5 * p_["stop_atr"]) / 2.5
            add(
                "- **The V1 part is close to a check the code base already has elsewhere.** The "
                "funded replay rejects a fill at or below the stop and a fill whose "
                "reward-to-risk is under 1.5 (`backtest/funded.py:442-453`, `min_reward_to_risk "
                f"= 1.5`). For this version's bracket (stop {p_['stop_atr']:g} ATR, target "
                f"{p_['target_atr']:g} ATR) that is the same line as fill ≤ signal close + "
                f"{g_rr:.2g} ATR; the selected V1 cell is g = {sel['v1_pick']}. The promotion "
                "engine has no such check. Code reading only; the funded replay was not run here."
            )
        add(
            f"- **Scale.** The candidate's {fr(c['oos_e_expectancy'])}R is close to the "
            f"{fr(v['cells']['B0']['OOS']['expectancy'])}R already on record for this version "
            "(engine R, uncorrected). Measured consistently the gain is against the corrected "
            f"{fr(c['oos_b1_expectancy'])}R: the rule mostly wins back what the correction takes "
            "away."
        )
        add(
            "- **What a pass licenses** (pre-registration): evidence for a *new version* of the "
            "strategy, which would still need the full gate ladder, an operator-authorised sealed "
            "look and forward paper evidence. Nothing here changes any approved version, the "
            "operating scan, the paper ledger or the frozen studies. A fair test of this rule "
            "needs a baseline with both booking artefacts corrected (the stop side, which B1 "
            "fixes, and the target side, which it keeps), and that needs its own "
            "pre-registration."
        )
        add("")

    # ------------------------------------------------------------------ 6
    add("## 6. Expectations stated in advance, against the outcome")
    add("")
    d_is = [
        vs[k]["cells"]["B1"]["IS"]["expectancy"] - vs[k]["cells"]["B0"]["IS"]["expectancy"]
        for k in keys
    ]
    d_oos = [corr[k] for k in keys]
    add(
        f'- *"B1 will differ from B0 by a few hundredths of an R in either direction."* Held. '
        f"In-sample the change runs from {fr(min(d_is))}R to {fr(max(d_is))}R, out-of-sample from "
        f"{fr(min(d_oos))}R to {fr(max(d_oos))}R."
    )
    cuts = {
        name: [
            100 * (vs[k]["cells"][name]["ALL"]["n"] / vs[k]["cells"]["B1"]["ALL"]["n"] - 1)
            for k in keys
        ]
        for name in FAMILY_CELLS[:6]
    }
    cut_bits = [f"{name} {fpct(min(x))} to {fpct(max(x))}" for name, x in cuts.items()]
    add(
        '- *"V1 and V2 are expected to cut trade count by 10–30%."* Mostly not. Over the whole '
        "window the change in trade count across the four versions is: "
        + "; ".join(cut_bits)
        + ". Only the tightest cells come near 10%, "
        "because a skipped entry frees the symbol for its next signal."
    )
    n_null = len(keys) - len(passes)
    add(
        f'- *"A null is a likely outcome."* {NUM_WORD[n_null].capitalize()} of four versions are a '
        f"null"
        + (
            f"; the remaining {NUM_WORD[len(passes)]} "
            f"{'meets' if len(passes) == 1 else 'meet'} the rule as run, at the line, and "
            f"{'does' if len(passes) == 1 else 'do'} not hold up (section 5)."
            if passes and all(fragile[k] for k in passes)
            else (
                f"; the remaining {NUM_WORD[len(passes)]} "
                f"{'passes' if len(passes) == 1 else 'pass'} (section 5)."
                if passes
                else "."
            )
        )
    )
    add("")

    # ------------------------------------------------------------------ deviations
    add("## Deviations and clarifications")
    add("")
    add(
        "**Deviations from the pre-registration: none.** Scope, cells, selection screen, test, "
        "Holm adjustment and decision rule were applied as written; no cell was added and nothing "
        "was re-run with a changed rule."
        + (
            " The pre-registration left several points open (below). Four of them decide the one "
            "pass — clarifications 2, 3, 5 and 8 — and section 5 shows what the other reading of "
            "each gives. The pre-registered baseline also keeps a booking artefact that the "
            "candidate removes (section 5); that is the design as written, not a deviation, but "
            "the pass does not survive correcting it."
            if passes and all(fragile[k] for k in passes)
            else ""
        )
    )
    add("")
    add(
        "**Clarifications** — points the pre-registration left open. Items 1–12 were fixed in the "
        "script before its first run; item 13 lists the descriptive additions made by the "
        "implementer, item 14 those made after adversarial review."
    )
    add("")
    short_hist = sorted({s for k in keys for s in vs[k]["short_history_symbols"]})
    alt_bits, alt_verdict_changes = [], 0
    for k in cands:
        c = conf[k]
        diffs = [f["diff"] for f in c["folds"] if f["diff"] is not None]
        n_pos, n_neg = sum(1 for d in diffs if d > 0), sum(1 for d in diffs if d < 0)
        any_three = max(n_pos, n_neg) >= 3
        if any_three != c["cond_folds"]:
            alt_bits.append(
                f"{code(k)} ({n_pos} folds positive, {n_neg} negative, out-of-sample difference "
                f"{fr(c['oos_diff'])}R)"
            )
            alt_pass = (
                c["cond_holm"] and c["cond_total_r_per_year"] and any_three and c["cond_11bps"]
            )
            alt_verdict_changes += alt_pass != c["upgrade_candidate"]
    alt_fold_note = (
        'Read instead as "any three folds sharing one sign", the condition would read '
        f"differently for {_join(alt_bits)}; "
        + ("no verdict would change." if alt_verdict_changes == 0 else "a verdict would change.")
        if alt_bits
        else 'Read instead as "any three folds sharing one sign", no condition would change.'
    )
    clar = [
        "*The open.* Every rule compares the raw opening print of the entry bar. The fill is that "
        "open plus costs, as in the engine.",
        "*B1 is a re-simulation.* When an entry is not taken the loop moves to the next bar, as "
        "the engine's own skip does, so a freed symbol can take a later signal (counts in section "
        '2). The pre-registration calls B1 "same signals and exits as B0 … a measurement '
        'correction" and says "each is a full re-simulation" of the variants only, so B1 can '
        "also be read as B0's own trades without the entries that opened at or below the stop. "
        "The build instruction for this study (written by the round's orchestrator before the "
        'run) lists "entry open at or below the stop = no trade" as a switch in the engine loop, '
        "which is what the script does; it also keeps both arms of every comparison on one "
        "engine path. Section 2 shows both baselines and section 5 tests against both"
        + (
            ": the one pass holds only against the re-simulated one."
            if passes and all(fragile[k] for k in passes)
            else "."
        ),
        "*Every V cell is B1 plus one rule:* stable R, and no trade when the open is at or below "
        "the planned stop. That includes V3, where the stop planned at the signal remains the "
        "validity test.",
        "*V3.* Stop = fill − stop multiple × ATR14; target = fill + target multiple × ATR14; the "
        "fill is the cost-inclusive entry price; ATR14 = U ÷ stop multiple; time stop unchanged; "
        "R is still measured against U. All four versions have an ATR target.",
        '*Choosing among several qualifying cells.* The pre-registration says "pick at most one" '
        "per family but not how. The script takes the qualifying cell with the highest in-sample "
        "expectancy (the statistic the confirmation tests), then the higher in-sample total R per "
        "year, then the smaller parameter. Section 4 shows where this mattered.",
        f"*{ES} is one combined rule,* simulated in a single pass. Its combined in-sample result "
        "is shown but not screened again against B1.",
        "*Total R per year.* Total stable R divided by calendar years of the full-history split: "
        f"{START.isoformat()} to {boundary} ({years['IS']:.2f} years) in-sample, the rest to "
        f"{END.isoformat()} ({years['OOS']:.2f} years) out-of-sample. The same divisors are used "
        "for every cell, so every comparison of total R per year is a comparison of total R. "
        f"{_join(short_hist)} have shorter histories and later per-symbol boundaries, exactly as "
        "the runner defines them.",
        "*Bootstrap.* Blocks are the calendar months holding at least one out-of-sample entry in "
        "either arm. Each resample draws that many months with replacement and applies the same "
        "draw to both arms; the statistic is the difference of the two pooled means. The null "
        "distribution is the resampled differences minus the observed difference; p = (1 + number "
        "of null draws at or above the observed difference) ÷ 10,001. Draws come from "
        "`numpy.random.default_rng(20261110).integers(0, M, size=(10000, M))`, re-seeded for each "
        "version.",
        "*Holm.* Applied across all four versions. A version without a candidate would have "
        "entered with p = 1; all four had one.",
        "*Fold condition* (clarified by the round's orchestrator before the run). Computed over "
        "the whole development "
        f'window in the four gate-1 calendar folds, comparing {ES} with B1 in each; "same sign" '
        "means the sign of the out-of-sample difference. Folds 1 and 2 are inside the selection "
        "sample and fold 3 straddles the boundary, so only part of fold 3 and fold 4 add "
        "out-of-sample information. " + alt_fold_note,
        "*11 bps per side.* Slippage 6 bps plus half of a 10 bps spread (the base model "
        f"doubled), for B1 and {ES} only. Because V3 anchors the bracket to the cost-inclusive "
        f"fill, {ES} takes a slightly different set of trades at the higher cost.",
        "*Identity checks.* Beyond the pre-registered four-decimal check, B0 was also matched to "
        "the full-precision recorded rows and to the recorded gate-1 fold rows. The recorded "
        "high52 row was written with a window end two calendar days after the last session (a "
        "weekend); the bars are the same.",
        "*Descriptive additions, not pre-registered and not used in any selection or test:* the "
        "column re-measuring B0's own trades in stable R (section 2), and the breakdown of "
        "entry-bar exits (section 2). The breakdown and the gain/loss split of the entries that "
        "opened at or below the stop were added after the first run, to describe what those "
        "buckets hold; they are counts over the saved per-trade tables. The script was re-run "
        "after the first run only to store these counts and after code formatting. Every "
        "pre-registered number is identical in every run (the first run's `summary.json` is kept "
        "as `summary.first_run.json` and was compared field by field). The cross-check against "
        "the earlier diagnostic (section 2) and the note on the funded replay's fill check "
        "(section 5) come from reading existing files, also after the first run.",
        "*Added after adversarial review, the same day; descriptive only.* Two reviewers "
        "reproduced every number of the first version of this file and found no error in the "
        "code; they found that the file did not say how little the one pass can carry. Added in "
        "response: in section 2, the column for B0's own trades without the entries opening at "
        "or below the stop, the three-step table, the stable-R column for those entries and the "
        "split of dropped trades; in section 5, the wording of the verdict and, in the "
        '"How firm" subsection, the table and the bullets that refer to its rows (the baseline '
        "measured three other ways, other seeds, other ways of forming p), the reviewer's two "
        "runs, and the fold differences split by sample and by year; and the lead. One "
        "sentence of the first version was imprecise and is corrected there: it put all of "
        f"{fr(steps_big['entries_not_taken'] + steps_big['re_simulation'])}R down to not taking "
        f"the {ols['by_sample']['OOS']} out-of-sample entries that opened at or below their stop; "
        f"{fr(steps_big['entries_not_taken'])}R is those entries and "
        f"{fr(steps_big['re_simulation'])}R is the re-simulation that follows. All of "
        "it re-measures the saved trades of the pre-registered cells or repeats the "
        f"pre-registered bootstrap with other seeds ({SEED + 1} to {SEED + N_OTHER_SEEDS}). No "
        "entry rule was simulated for it, no cell was added, and no selection, test or verdict "
        "uses any of it. The script was re-run in full for this revision: every pre-registered "
        "field of `summary.json` and all sixteen per-trade tables are identical to the "
        "pre-review run (kept under `repair/`). The verdict by the rule is unchanged; how much "
        "it can carry is not.",
    ]
    for i, c_ in enumerate(clar, start=1):
        add(f"{i}. {c_}")
    add("")

    # ------------------------------------------------------------------ files
    add("## Files")
    add("")
    add(
        "- Script: `scripts/r3/entry_execution.py` (`--report-only` rebuilds this file from "
        "`summary.json`)."
    )
    add(f"- Raw outputs, not committed: `{out_dir}/`")
    add(
        "  - `summary.json` — every number in this file; `summary.first_run.json` — the first "
        "run, for comparison."
    )
    add(
        "  - `trades_B0_<version>.csv`, `trades_B1_<version>.csv`, `trades_Estar_<version>.csv` — "
        "per-trade tables."
    )
    add("  - `trades_cells_<version>.csv` — per-trade table for every pre-registered cell.")
    add("  - `run.log` — identity checks and timings.")
    add(
        "  - `repair/` — the pre-review copies of this file, the script and `summary.json`, and "
        "the checks run against the reviewers' numbers; `review/` — the reviewers' own scripts."
    )
    add("")
    add("Research signal only — no order was placed.")
    return "\n".join(out) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", type=Path, default=Path.cwd() / "out" / "entry-exec")
    ap.add_argument("--results", type=Path, default=DEFAULT_RESULTS)
    ap.add_argument(
        "--report-only", action="store_true", help="rebuild the results file from summary.json"
    )
    ap.add_argument("--no-report", action="store_true", help="compute only")
    args = ap.parse_args()
    try:
        if args.report_only:
            summary = json.loads((args.out / "summary.json").read_text())
        else:
            summary = compute(args.out)
    except IdentityError as exc:
        print(f"IDENTITY CHECK FAILED — stopping before any result: {exc}", file=sys.stderr)
        return 2
    if not args.no_report:
        summary = json.loads((args.out / "summary.json").read_text())  # render what was saved
        args.results.write_text(render(summary, args.out))
        print(f"wrote {args.results}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
