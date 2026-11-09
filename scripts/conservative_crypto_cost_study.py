"""Offline, SQL-bounded CRYPTO-5 study. See the committed fixed protocol.

Run with PYTHONPATH=src <python> scripts/conservative_crypto_cost_study.py DB.
No application session, provider, execution, paper or notification API is used.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sqlite3
import subprocess
from collections import Counter
from dataclasses import asdict, dataclass, replace
from datetime import date, timedelta
from decimal import ROUND_DOWN, Decimal, getcontext
from pathlib import Path
from typing import Any

import numpy as np

from signalforge.backtest.costs import CostModel
from signalforge.data.series import PriceSeries
from signalforge.domain import Direction
from signalforge.research.fx.continuity import continuity_breach, gap_profile
from signalforge.research.fx.harness import CRYPTO5_DEV_CUT, FxGates, backtest
from signalforge.research.fx.strategies import (
    CRYPTO2_STRATEGIES,
    CRYPTO5_PAIRS,
    CRYPTO5_STRATEGIES,
    CRYPTO_STRATEGIES,
    FxStrategy,
    long_only_variant,
)
from signalforge.research.fx.venues import COINBASE_SPOT_INTRO

getcontext().prec = 34
D = Decimal
ZERO = D(0)
ONE = D(1)
CASH = D(10000)
ALLOCATION, THEME, GROSS = D("0.05"), D("0.20"), D("0.60")
TRADE_RISK, OPEN_RISK, DRAWDOWN = D("0.005"), D("0.015"), D("0.10")
SOURCE = "massive_crypto"
LOWER = date(2016, 1, 1)
SEALED = date(2025, 10, 26)
ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = "docs/research/CONSERVATIVE_CRYPTO_COST_PROTOCOL_2026-11-08.md"
REPORT = "reports/CONSERVATIVE_CRYPTO_COST_STUDY_2026-11-08.md"
WINDOWS = (
    ("development", date(2017, 1, 1), date(2020, 12, 31)),
    ("validation_SEEN", date(2021, 1, 1), date(2023, 12, 31)),
    ("followup_SEEN", date(2024, 1, 1), date(2025, 10, 25)),
)


def dec(value: Any) -> Decimal:
    return D(str(value))


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def dates(start: date, end: date) -> list[date]:
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


@dataclass(frozen=True)
class Limits:
    allocation: Decimal = ALLOCATION
    theme: Decimal = THEME
    gross: Decimal = GROSS
    trade_risk: Decimal = TRADE_RISK
    open_risk: Decimal = OPEN_RISK
    drawdown: Decimal = DRAWDOWN


def rates(pair: str, stress: int) -> dict[str, Decimal]:
    if stress not in (1, 2):
        raise ValueError("only the registered base/2x-spread cost cases")
    venue = COINBASE_SPOT_INTRO
    return {
        "fee": dec(venue.taker_bps) * stress / 10000,
        "spread": dec(venue.half_spread(pair)) * stress / 10000,
        "slippage": dec(FxGates().slippage_bps) / 10000,
    }


def side_rate(pair: str, stress: int) -> Decimal:
    return sum(rates(pair, stress).values(), ZERO)


@dataclass(frozen=True)
class Trade:
    pair: str
    entry: date
    exit: date
    raw_entry: Decimal
    raw_exit: Decimal
    stop: Decimal
    reason: str
    stress: int = 1

    @property
    def rate(self) -> Decimal:
        return side_rate(self.pair, self.stress)

    @property
    def entry_fill(self) -> Decimal:
        return self.raw_entry * (ONE + self.rate)

    @property
    def exit_fill(self) -> Decimal:
        return self.raw_exit * (ONE - self.rate)

    @property
    def stop_risk(self) -> Decimal:
        return self.entry_fill - self.stop * (ONE - self.rate)


def open_readonly(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    return conn


def load_bounded(path: Path, pairs: list[str]) -> tuple[dict[str, PriceSeries], dict[str, Any]]:
    """The only bar reader: SQL bounds apply BEFORE rows enter Python."""
    panel: dict[str, PriceSeries] = {}
    meta: dict[str, Any] = {"source": SOURCE, "sql_start": str(LOWER), "sql_before": str(SEALED)}
    with open_readonly(path) as conn:
        conn.execute("BEGIN")
        schema = [dict(r) for r in conn.execute("PRAGMA table_info(crypto_bar_daily)")]
        cols = {r["name"] for r in schema}
        required = {"pair", "session_date", "open", "high", "low", "close", "source"}
        if not required <= cols:
            raise ValueError(f"required crypto_bar_daily schema missing: {required - cols}")
        meta["schema"] = schema
        meta["quality_status"] = "recorded_flags_only" if "quality_flags" in cols else "UNKNOWN"
        meta["simulation_status"] = (
            "recorded_field" if "is_simulated" in cols else "UNKNOWN: no explicit simulation field"
        )
        meta["liquidity"] = "UNVALIDATED: no measured venue spread/impact validation"
        chosen = sorted(
            required
            | (cols & {"volume", "quality_flags", "latency_category", "is_simulated", "simulated"})
        )
        # Column identifiers come only from this fixed allowlist, never from input.
        sql = (
            f"SELECT {', '.join(chosen)} FROM crypto_bar_daily "  # noqa: S608
            "WHERE pair = ? AND source = ? AND session_date >= ? AND session_date < ? "
            "ORDER BY session_date"
        )
        meta["query"] = sql
        summaries = {}
        for pair in sorted(pairs):
            raw = [dict(r) for r in conn.execute(sql, (pair, SOURCE, str(LOWER), str(SEALED)))]
            good, excluded = [], Counter()
            previous = None
            for row in raw:
                day = date.fromisoformat(row["session_date"])
                if not LOWER <= day < SEALED or row["source"] != SOURCE:
                    raise ValueError("source/sealed boundary violated")
                if previous is not None and day <= previous:
                    raise ValueError("duplicate or unordered source dates")
                previous = day
                flag = row.get("quality_flags", "[]")
                try:
                    flagged = json.loads(flag) if isinstance(flag, str) else flag
                except (ValueError, TypeError):
                    flagged = True
                if "quality_flags" in row and (flagged or flagged is None):
                    excluded["quality_flags"] += 1
                    continue
                simulation = str(row.get("latency_category", "")).upper()
                if (
                    row.get("is_simulated")
                    or row.get("simulated")
                    or "SIMULAT" in simulation
                    or "FIXTURE" in simulation
                ):
                    excluded["explicit_simulation"] += 1
                    continue
                o, h, lo, c = (float(row[k]) for k in ("open", "high", "low", "close"))
                if not all(math.isfinite(v) and v > 0 for v in (o, h, lo, c)):
                    excluded["invalid_price"] += 1
                    continue
                if not lo <= min(o, c) <= max(o, c) <= h:
                    excluded["invalid_ohlc"] += 1
                    continue
                vol = row.get("volume")
                good.append((day, o, h, lo, c, float(vol) if vol is not None else float("nan")))
            panel[pair] = PriceSeries.from_bars(pair, good)
            summaries[pair] = {
                "selected_rows": len(raw),
                "accepted_rows": len(good),
                "excluded": dict(excluded),
                "first": str(good[0][0]) if good else None,
                "last": str(good[-1][0]) if good else None,
                "positive_volume_rows": sum(math.isfinite(r[5]) and r[5] > 0 for r in good),
                "finite_volume_rows": sum(math.isfinite(r[5]) for r in good),
                "bounded_rows_sha256": digest(raw),
            }
        meta["pairs"] = summaries
        meta["bounded_data_sha256"] = digest(summaries)
        conn.rollback()
    return panel, meta


def coverage(series: PriceSeries, start: date, end: date) -> dict[str, Any]:
    inside = [d for d in series.dates if start <= d <= end]
    if len(series) and series.dates[0] > end:
        return {
            "first": None,
            "last": None,
            "observed": 0,
            "expected": 0,
            "missing": 0,
            "longest_gap": 0,
            "breach": "not yet incepted",
            "gaps": [],
        }
    begin = max(start, series.dates[0]) if len(series) else start
    profile = gap_profile(inside, timedelta(days=1), start=begin, end=end)
    breach = continuity_breach(inside, timedelta(days=1), start=begin, end=end)
    absent = sorted(set(dates(begin, end)) - set(inside)) if begin <= end else []
    intervals: list[list[str]] = []
    for day in absent:
        if intervals and date.fromisoformat(intervals[-1][1]) + timedelta(days=1) == day:
            intervals[-1][1] = str(day)
        else:
            intervals.append([str(day), str(day)])
    return {
        "first": str(inside[0]) if inside else None,
        "last": str(inside[-1]) if inside else None,
        "observed": len(inside),
        **asdict(profile),
        "breach": breach,
        "gaps": intervals,
    }


def continuous_history(series: PriceSeries, t: int, warmup: int) -> bool:
    if t < warmup:
        return False
    return series.dates[t] - series.dates[t - warmup] == timedelta(days=warmup)


def eligible_entry(series: PriceSeries, warmup: int, start: date, end: date) -> date | None:
    for t in range(warmup, len(series) - 1):
        if (
            start <= series.dates[t]
            and series.dates[t + 1] <= end
            and continuous_history(series, t, warmup)
            and series.dates[t + 1] - series.dates[t] == timedelta(days=1)
        ):
            return series.dates[t + 1]
    return None


def harness_candidates(
    strat: FxStrategy, series: PriceSeries, start: date, end: date, stress: int
) -> tuple[list[Trade], dict[str, int]]:
    """Use the real harness schedule/fills, not a parallel strategy implementation."""
    if len(series) and (series.dates[0] < LOWER or series.dates[-1] >= SEALED):
        raise ValueError("unbounded input rejected BEFORE strategy evaluation")
    if not LOWER <= start <= end < SEALED:
        raise ValueError("unregistered/sealed evaluation boundary")
    series = series.head(sum(d <= end for d in series.dates) - 1)
    stops = {}
    rejected: Counter[str] = Counter()

    def record(sub: PriceSeries, t: int) -> Any:
        if not start <= sub.dates[-1] <= end:
            return None
        if not continuous_history(sub, len(sub) - 1, strat.warmup):
            return None
        sig = strat.signal(sub, t)
        if sig is not None:
            stops[sub.dates[-1]] = sig
        return sig

    cm = CostModel(slippage_bps=FxGates().slippage_bps)
    spread = COINBASE_SPOT_INTRO.engine_spread_bps(series.symbol) * stress
    outcome = backtest(replace(strat, signal=record), series, cost_model=cm, spread_bps=spread)
    index = {d: i for i, d in enumerate(series.dates)}
    result = []
    for tr in outcome.trades:
        if tr.direction != Direction.LONG:
            rejected["parent_short_discarded"] += 1
            continue
        e, x = index[tr.entry_date], index[tr.exit_date]
        sig = stops[series.dates[e - 1]]
        if series.dates[e] - series.dates[e - 1] != timedelta(days=1):
            rejected["missing_next_calendar_open"] += 1
            continue
        raw_entry, stop = dec(series.open[e]), dec(sig.stop_price)
        if not ZERO < stop < raw_entry:
            rejected["stop_not_below_entry_open"] += 1
            continue
        if tr.exit_reason == "stop":
            raw_exit = min(dec(series.open[x]), stop) if x > e else stop
        elif tr.exit_reason == "target":
            target = dec(sig.target_price)
            raw_exit = max(dec(series.open[x]), target) if x > e else target
        else:
            raw_exit = dec(series.close[x])
        candidate = Trade(
            series.symbol,
            tr.entry_date,
            tr.exit_date,
            raw_entry,
            raw_exit,
            stop,
            tr.exit_reason,
            stress,
        )
        # Harness prices are rounded to 4 dp; pnl_pct retains the unrounded fill.
        pnl = float(candidate.exit_fill / candidate.entry_fill - ONE)
        if not math.isclose(pnl, tr.pnl_pct, abs_tol=1e-12, rel_tol=1e-10):
            raise AssertionError("reconstructed fills differ from existing harness")
        result.append(candidate)
    return result, dict(rejected)


@dataclass
class Holding:
    trade: Trade
    qty: Decimal

    def reserve(self, mark: Decimal) -> Decimal:
        current = mark * (ONE + self.trade.rate) - self.trade.stop * (ONE - self.trade.rate)
        return self.qty * max(self.trade.stop_risk, current, ZERO)


def quantity(
    tr: Trade, *, cash: Decimal, equity: Decimal, gross: Decimal, open_risk: Decimal, limits: Limits
) -> Decimal:
    if tr.stop <= 0 or tr.stop >= tr.raw_entry or tr.stop_risk <= 0 or equity <= 0:
        return ZERO
    cost = tr.raw_entry * tr.rate
    bounds = [
        cash / tr.entry_fill,
        limits.allocation * equity / (tr.entry_fill + limits.allocation * cost),
        (limits.theme * equity - gross) / (tr.raw_entry + limits.theme * cost),
        (limits.gross * equity - gross) / (tr.raw_entry + limits.gross * cost),
        limits.trade_risk * equity / (tr.stop_risk + limits.trade_risk * cost),
        (limits.open_risk * equity - open_risk) / (tr.stop_risk + limits.open_risk * cost),
    ]
    return max(ZERO, min(bounds)).quantize(D("1e-18"), rounding=ROUND_DOWN)


def metrics(days: list[date], curve: list[Decimal], exposure: list[Decimal]) -> dict[str, Any]:
    high, dd = CASH, ZERO
    for equity in curve:
        high = max(high, equity)
        dd = max(dd, ONE - equity / high)
    return {
        "net_return_pct": float((curve[-1] / CASH - ONE) * 100),
        "ending_equity": float(curve[-1]),
        "max_drawdown_pct": float(dd * 100),
        "mean_exposure_pct": float(sum(exposure, ZERO) / len(days) * 100),
        "max_close_exposure_pct": float(max(exposure, default=ZERO) * 100),
    }


def replay(
    trades: list[Trade],
    panel: dict[str, PriceSeries],
    start: date,
    end: date,
    limits: Limits = Limits(),
) -> dict[str, Any]:
    days = dates(start, end)
    bars = {
        p: {d: (dec(s.open[i]), dec(s.close[i])) for i, d in enumerate(s.dates)}
        for p, s in panel.items()
    }
    by_entry: dict[date, list[Trade]] = {}
    for tr in trades:
        if not start <= tr.entry <= tr.exit <= end < SEALED:
            raise ValueError("trade outside replay/sealed boundary")
        by_entry.setdefault(tr.entry, []).append(tr)
    cash, previous, peak = CASH, CASH, CASH
    pos: dict[str, Holding] = {}
    last: dict[str, Decimal] = {}
    curve, exposures, closed, audit = [], [], [], []
    skipped: Counter[str] = Counter()
    costs = dict.fromkeys(("fee", "spread", "slippage"), ZERO)
    stale, halt, turnover, max_open_dd = 0, None, ZERO, ZERO
    minima = cash
    for day in days:
        missing = any(day not in bars[p] for p in pos)
        marks = {p: bars[p][day][0] if day in bars[p] else last[p] for p in pos}
        gross = sum((h.qty * marks[p] for p, h in pos.items()), ZERO)
        open_equity = cash + gross
        peak = max(peak, open_equity)
        max_open_dd = max(max_open_dd, ONE - open_equity / peak)
        if open_equity <= peak * (ONE - limits.drawdown):
            halt = halt or str(day)
        for tr in sorted(by_entry.get(day, []), key=lambda t: t.pair):
            if halt or missing or tr.pair in pos:
                reason = "drawdown_halt" if halt else "stale_holding" if missing else "already_open"
                skipped[reason] += 1
                continue
            mark = bars.get(tr.pair, {}).get(day)
            if mark is None or mark[0] != tr.raw_entry:
                raise ValueError("candidate does not use actual entry open")
            basis = min(previous, open_equity)
            reserve = sum((h.reserve(marks[p]) for p, h in pos.items()), ZERO)
            qty = quantity(
                tr, cash=cash, equity=basis, gross=gross, open_risk=reserve, limits=limits
            )
            if qty <= 0:
                skipped["cash_or_cap_or_risk"] += 1
                continue
            cost = qty * tr.raw_entry * tr.rate
            after_basis = basis - cost
            admission = {
                "date": str(day),
                "pair": tr.pair,
                "qty": str(qty),
                "cash_before": str(cash),
                "cash_after": str(cash - qty * tr.entry_fill),
                "basis_after_cost": str(after_basis),
                "allocation": float(qty * tr.entry_fill / after_basis),
                "theme": float((gross + qty * tr.raw_entry) / after_basis),
                "gross": float((gross + qty * tr.raw_entry) / after_basis),
                "trade_risk": float(qty * tr.stop_risk / after_basis),
                "open_risk": float((reserve + qty * tr.stop_risk) / after_basis),
            }
            for key in ("allocation", "theme", "gross", "trade_risk", "open_risk"):
                if admission[key] > float(getattr(limits, key)) + 1e-12:
                    raise AssertionError(f"admission cap violated: {key}")
            audit.append(admission)
            cash -= qty * tr.entry_fill
            for key, rate in rates(tr.pair, tr.stress).items():
                costs[key] += qty * tr.raw_entry * rate
            turnover += qty * tr.raw_entry
            pos[tr.pair], marks[tr.pair] = Holding(tr, qty), tr.raw_entry
            gross += qty * tr.raw_entry
            open_equity -= cost
            max_open_dd = max(max_open_dd, ONE - open_equity / peak)
            minima = min(minima, cash)
            if cash < 0:
                raise AssertionError("negative cash")
            if open_equity <= peak * (ONE - limits.drawdown):
                halt = halt or str(day)
        # No proceeds OR room from today's exits were available above.
        for pair in sorted(pos):
            h = pos[pair]
            tr = h.trade
            if tr.exit == day:
                cash += h.qty * tr.exit_fill
                for key, rate in rates(pair, tr.stress).items():
                    costs[key] += h.qty * tr.raw_exit * rate
                turnover += h.qty * tr.raw_exit
                closed.append(
                    {
                        **asdict(tr),
                        "qty": h.qty,
                        "net_pnl": h.qty * (tr.exit_fill - tr.entry_fill),
                        "costs": h.qty * (tr.raw_entry + tr.raw_exit) * tr.rate,
                    }
                )
                del pos[pair]
        for pair in pos:
            if day in bars[pair]:
                last[pair] = bars[pair][day][1]
            else:
                stale += 1
        gross = sum((h.qty * last[p] for p, h in pos.items()), ZERO)
        equity = cash + gross
        peak = max(peak, equity)
        max_open_dd = max(max_open_dd, ONE - equity / peak)
        if equity <= peak * (ONE - limits.drawdown):
            halt = halt or str(day)
        curve.append(equity)
        exposures.append(gross / equity if equity > 0 else ZERO)
        previous = equity
    if pos:
        raise AssertionError("harness positions remain at fixed window end")
    net = sum((t["net_pnl"] for t in closed), ZERO)
    if abs(curve[-1] - CASH - net) > D("1e-20"):
        raise AssertionError("cash/trade conservation failed")
    return {
        "metrics": {
            **metrics(days, curve, exposures),
            "max_observed_drawdown_pct": float(max_open_dd * 100),
            "trades": len(closed),
            "candidates": len(trades),
            "costs": {k: float(v) for k, v in costs.items()},
            "total_costs": float(sum(costs.values(), ZERO)),
            "skipped": dict(skipped),
            "halt_date": halt,
            "stale_position_days": stale,
            "min_cash": float(minima),
            "turnover_initial_equity": float(turnover / CASH),
            "admission_maxima": {
                k: max((a[k] for a in audit), default=0.0)
                for k in ("allocation", "theme", "gross", "trade_risk", "open_risk")
            },
        },
        "days": list(map(str, days)),
        "equity": list(map(float, curve)),
        "exposure": list(map(float, exposures)),
        "trades": closed,
        "admissions": audit,
    }


def hold_components(
    panel: dict[str, PriceSeries], warmup: int, start: date, end: date, stress: int
) -> dict[str, Any]:
    """Unit-funded sleeve paths: linear in initial allocation; no daily rebalancing."""
    days = dates(start, end)
    funded_equity = np.ones(len(days))
    funded_gross = np.zeros(len(days))
    components = dict.fromkeys(("fee", "spread", "slippage"), 0.0)
    entries = []
    n = len(panel)
    for pair, s in sorted(panel.items()):
        entry = eligible_entry(s, warmup, start, end)
        if entry is None:
            continue
        i = s.dates.index(entry)
        x = max(j for j, day in enumerate(s.dates) if day <= end)
        side = side_rate(pair, stress)
        qty = ONE / n / (dec(s.open[i]) * (ONE + side))
        lookup = {day: dec(s.close[j]) for j, day in enumerate(s.dates)}
        last = dec(s.open[i])
        paid = qty * (dec(s.open[i]) + dec(s.close[x]))
        for key, rate in rates(pair, stress).items():
            components[key] += float(paid * rate * CASH)
        entries.append({"pair": pair, "entry": str(entry), "exit": str(s.dates[x])})
        for j, day in enumerate(days):
            if day < entry:
                continue
            last = lookup.get(day, last)  # valuation only, never synthetic OHLC
            if day < s.dates[x]:
                funded_equity[j] += float(qty * last - ONE / n)
                funded_gross[j] += float(qty * last)
            else:
                funded_equity[j] += float(qty * dec(s.close[x]) * (ONE - side) - ONE / n)
    return {
        "days": list(map(str, days)),
        "unit_equity": funded_equity,
        "unit_gross": funded_gross,
        "costs": components,
        "entries": entries,
    }


def hold_scaled(components: dict[str, Any], fraction: float) -> dict[str, Any]:
    equity = (1 + fraction * (components["unit_equity"] - 1)) * float(CASH)
    gross = fraction * components["unit_gross"] * float(CASH)
    exposure = gross / equity
    result = metrics(
        [date.fromisoformat(d) for d in components["days"]],
        list(map(dec, equity)),
        list(map(dec, exposure)),
    )
    costs = {k: v * fraction for k, v in components["costs"].items()}
    return {
        "metrics": {
            **result,
            "costs": costs,
            "total_costs": sum(costs.values()),
            "initial_invested_fraction": fraction,
            "trades": len(components["entries"]) if fraction > 0 else 0,
        },
        "days": components["days"],
        "equity": equity.tolist(),
        "exposure": exposure.tolist(),
        "entries": components["entries"],
    }


def matched_hold(components: dict[str, Any], target: float) -> dict[str, Any]:
    lo, hi = 0.0, 1.0
    achievable = float(np.mean(components["unit_gross"] / components["unit_equity"]))
    if target > achievable + 1e-10:
        raise ValueError("target exposure cannot be matched without leverage")
    for _ in range(50):
        mid = (lo + hi) / 2
        exposure = np.mean(
            mid * components["unit_gross"] / (1 + mid * (components["unit_equity"] - 1))
        )
        if exposure < target:
            lo = mid
        else:
            hi = mid
    return hold_scaled(components, (lo + hi) / 2)


def block_interval(strategy: list[float], benchmark: list[float]) -> list[float]:
    a, b = np.array([float(CASH), *strategy]), np.array([float(CASH), *benchmark])
    excess = np.diff(a) / a[:-1] - np.diff(b) / b[:-1]
    rng = np.random.default_rng(20261108)
    samples = []
    for _ in range(500):
        starts = rng.integers(0, len(excess), size=math.ceil(len(excess) / 20))
        indices = ((starts[:, None] + np.arange(20)) % len(excess)).ravel()[: len(excess)]
        samples.append(float(np.mean(excess[indices]) * 365 * 100))
    return np.percentile(samples, [5, 95]).tolist()


def run_study(panel: dict[str, PriceSeries], meta: dict[str, Any]) -> dict[str, Any]:
    rows, profiles, comparisons = [], {}, []
    parents = {s.key: s for s in (*CRYPTO_STRATEGIES, *CRYPTO2_STRATEGIES)}
    for label, start, end in WINDOWS:
        profiles[label] = {p: coverage(s, start, end) for p, s in panel.items()}
        for variant in CRYPTO5_STRATEGIES:
            parent = parents[variant.key.removesuffix("_long")]
            eligible = {
                p: panel[p]
                for p in CRYPTO5_PAIRS[variant.key]
                if not profiles[label][p]["breach"]
                and eligible_entry(panel[p], variant.warmup, start, end) is not None
            }
            for stress in (1, 2):
                schedules = {}
                rejects = {}
                for name, strat in (("parent_long_legs", parent), ("variant", variant)):
                    trades, rejection = [], Counter()
                    for series in eligible.values():
                        ts, rs = harness_candidates(strat, series, start, end, stress)
                        trades.extend(ts)
                        rejection.update(rs)
                    schedules[name], rejects[name] = trades, dict(rejection)
                # Equivalent signal filter is verified on every admitted real series.
                equivalent = long_only_variant(parent, "parity", "parent long signal parity")
                parity = []
                for series in eligible.values():
                    parity.extend(harness_candidates(equivalent, series, start, end, stress)[0])
                if parity != schedules["variant"]:
                    raise AssertionError(
                        "registered variant differs from parent's long signal filter"
                    )
                comparison = {
                    "window": label,
                    "strategy": variant.key,
                    "stress": stress,
                    "parent_long_candidates": len(schedules["parent_long_legs"]),
                    "variant_candidates": len(schedules["variant"]),
                    "same_schedule": schedules["parent_long_legs"] == schedules["variant"],
                    "long_signal_filter_parity": True,
                }
                comparisons.append(comparison)
                hold = hold_components(eligible, variant.warmup, start, end, stress)
                full = hold_scaled(hold, 1.0)
                for name, trades in schedules.items():
                    portfolio = replay(trades, eligible, start, end)
                    matched = matched_hold(hold, portfolio["metrics"]["mean_exposure_pct"] / 100)
                    rows.append(
                        {
                            "window": label,
                            "strategy": variant.key,
                            "schedule": name,
                            "stress": stress,
                            "eligible_pairs": sorted(eligible),
                            "candidate_rejections": rejects[name],
                            "portfolio": portfolio,
                            "buy_hold": full,
                            "exposure_matched": matched,
                            "excess_annual_mean_90pct_block_interval_pp": block_interval(
                                portfolio["equity"], matched["equity"]
                            ),
                        }
                    )
    return {"data": meta, "coverage": profiles, "comparisons": comparisons, "runs": rows}


def render(result: dict[str, Any], evidence: Path, evidence_hash: str) -> str:
    unique = [r for r in result["runs"] if r["schedule"] == "variant"]
    positive = sum(r["portfolio"]["metrics"]["net_return_pct"] > 0 for r in unique)
    beats_matched = sum(
        r["portfolio"]["metrics"]["net_return_pct"]
        > r["exposure_matched"]["metrics"]["net_return_pct"]
        for r in unique
    )
    follows = [r for r in unique if r["window"] == "followup_SEEN"]
    follow_intervals = sum(
        r["excess_annual_mean_90pct_block_interval_pp"][0]
        <= 0
        <= r["excess_annual_mean_90pct_block_interval_pp"][1]
        for r in follows
    )
    lines = [
        "# Conservative crypto cost study — 2026-11-08",
        "",
        "DESCRIPTIVE, already-seen history. Liquidity UNVALIDATED. "
        "No promotion or execution claim.",
        "",
        f"Protocol commit: `{result['protocol_commit']}`. Source: `{result['source_commit']}`.",
        f"Base: `bb624d7`. Bounded data SHA256: `{result['data']['bounded_data_sha256']}`.",
        f"Local detailed evidence: `{evidence}`; SHA256 `{evidence_hash}`.",
        "",
        "24 fixed portfolio runs, each $10,000; 5% all-in entry allocation, 20% crypto theme,",
        "60% gross, 0.5% trade / 1.5% aggregate modeled all-in stop risk; 10% DD entry halt.",
        "Limits apply at admission; price drift and stop gaps can exceed them afterward.",
        "",
        f"Outcome: {positive}/{len(unique)} distinct long-only window/cost portfolios had positive",
        f"net returns; {beats_matched}/{len(unique)} exceeded the exposure-matched basket's point",
        f"return. {follow_intervals}/{len(follows)} followup excess-return intervals include zero.",
        "Every parent LONG-leg schedule and full account path equals its CRYPTO-5 variant here:",
        "24 runs represent 12 distinct accounts, not 24 independent confirmations.",
        "Fully funded buy-and-hold has higher absolute returns in every comparison and much",
        "larger drawdowns. Conservative sizing reduces losses; it does not remove cost drag",
        "or establish reliable future excess returns.",
        "",
        "Costs: base Coinbase Intro 90 bps taker + estimated half-spread (BTC 2, ETH 3,",
        "SOL 10, other pairs 15 bps) + 1 bp slippage, each side. Stress doubles fee and",
        "half-spread; the separate 1 bp slip stays fixed (harness convention).",
        "",
        "## Data and coverage",
        "",
        "One SQLite mode=ro, query_only transaction, exact massive_crypto rows, SQL-bounded",
        "2016-01-01 <= date < 2025-10-26. No sealed bars fetched, providers called, operating",
        "writes, paper trades, alerts, or study updates. 2016 context is warmup only.",
        "",
        f"Quality: {result['data']['quality_status']}. "
        f"Simulation: {result['data']['simulation_status']}.",
        "Source identifies stored Massive data; it does not establish historical venue listing,",
        "point-in-time universe membership, measured depth/spreads or execution capacity.",
        "",
        "| Pair | Bounded selected/accepted rows | First–last accepted | "
        "Finite/positive volume rows | Excluded |",
        "|---|---:|---|---:|---|",
    ]
    for p, m in result["data"]["pairs"].items():
        lines.append(
            f"| {p} | {m['selected_rows']}/{m['accepted_rows']} | {m['first']}–{m['last']} | "
            f"{m['finite_volume_rows']}/{m['positive_volume_rows']} | {m['excluded']} |"
        )
    lines += [
        "",
        "| Window | Pair | Actual/expected days | Longest gap | Admission / gaps |",
        "|---|---|---:|---:|---|",
    ]
    for label, ps in result["coverage"].items():
        for p, c in ps.items():
            lines.append(
                f"| {label} | {p} | {c['observed']}/{c['expected']} | {c['longest_gap']} | "
                f"{c['breach'] or 'within continuity policy'}; {c['gaps']} |"
            )
    lines += [
        "",
        "Stored daily volume is present for all accepted bars in this snapshot. Venue spreads,",
        "depth and market impact were not measured: liquidity remains UNVALIDATED.",
        "Not-yet-incepted symbols have zero expected days, rather than a continuity failure.",
        "",
        "Warmup resets signal eligibility after any gap; entries require the next actual",
        "calendar open. No synthetic bars. Missing holding marks use the last real close",
        "for accounting only and block entries; exits still follow the harness's surviving",
        "bars, so missing-interval stop paths remain unknown. Each window starts flat, with",
        "no carry-in; harness EOD exits liquidate at the last actual window close.",
        "",
        "| Window/rule | First eligible actual benchmark opens (after warmup) |",
        "|---|---|",
    ]
    for row in unique:
        if row["stress"] == 1:
            entries = ", ".join(f"{e['pair']} {e['entry']}" for e in row["buy_hold"]["entries"])
            lines.append(f"| {row['window']}/{row['strategy']} | {entries} |")
    lines += [
        "",
        "## Results",
        "",
        "D = 2017–20 development; V = 2021–23 validation (SEEN); F = 2024–2025-10-25",
        "followup (SEEN). P = actual parent schedule's LONG legs; L = registered long-only",
        "variant. 3/9 identifies the registered pair list, before coverage exclusions.",
        "",
        "B&H reserves equal initial sleeves, admits after inception/warmup and holds to",
        "window end. It is an unmanaged fully funded reference with different risk limits.",
        "Matched holds the same sleeves plus cash, fitted to average realized close exposure;",
        "it is an ex-post normalization, not a forecast. All benchmarks pay both-side costs.",
        "",
        "| Window | Rule/schedule | Cost | Net % | Cost $ | Close/observed DD % | "
        "Mean/max exposure % | "
        "Trades/candidates | B&H % / DD % | Matched % / DD % |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in result["runs"]:
        m, b, x = (row[k]["metrics"] for k in ("portfolio", "buy_hold", "exposure_matched"))
        label = {"development": "D", "validation_SEEN": "V", "followup_SEEN": "F"}[row["window"]]
        rule = ("9" if "u10" in row["strategy"] else "3") + (
            "P" if row["schedule"].startswith("parent") else "L"
        )
        lines.append(
            f"| {label} | {rule} | {row['stress']}x | {m['net_return_pct']:.3f} | "
            f"{m['total_costs']:.2f} | {m['max_drawdown_pct']:.3f}/"
            f"{m['max_observed_drawdown_pct']:.3f} | "
            f"{m['mean_exposure_pct']:.2f}/{m['max_close_exposure_pct']:.2f} | "
            f"{m['trades']}/{m['candidates']} | "
            f"{b['net_return_pct']:.2f}/{b['max_drawdown_pct']:.2f} | "
            f"{x['net_return_pct']:.3f}/{x['max_drawdown_pct']:.3f} |"
        )
    lines += [
        "",
        "| Distinct variant window/rule/cost | Ending equity $ | Losing trades / total | "
        "Total losing P&L $ | Largest trade loss $ |",
        "|---|---:|---:|---:|---:|",
    ]
    for row in unique:
        portfolio = row["portfolio"]
        losses = [dec(t["net_pnl"]) for t in portfolio["trades"] if dec(t["net_pnl"]) < 0]
        label = f"{row['window']}/{row['strategy']}/{row['stress']}x"
        lines.append(
            f"| {label} | {portfolio['metrics']['ending_equity']:.2f} | "
            f"{len(losses)}/{len(portfolio['trades'])} | {sum(losses, ZERO):.2f} | "
            f"{min(losses, default=ZERO):.2f} |"
        )
    lines += [
        "",
        "## Accounting and uncertainty",
        "",
        "| Window/rule/schedule/cost | Fee/spread/slip $ | Min cash $ | "
        "Turnover / initial equity | Halt | Skips | Annual mean excess 90% interval, pp |",
        "|---|---:|---:|---:|---|---|---:|",
    ]
    for r in result["runs"]:
        m = r["portfolio"]["metrics"]
        c = m["costs"]
        ci = r["excess_annual_mean_90pct_block_interval_pp"]
        label = f"{r['window']}/{r['strategy']}/{r['schedule']}/{r['stress']}x"
        lines.append(
            f"| {label} | {c['fee']:.2f}/{c['spread']:.2f}/{c['slippage']:.2f} | "
            f"{m['min_cash']:.2f} | {m['turnover_initial_equity']:.3f} | {m['halt_date']} | "
            f"{m['skipped']} | [{ci[0]:.3f}, {ci[1]:.3f}] |"
        )
    maxima = {
        k: max(r["portfolio"]["metrics"]["admission_maxima"][k] for r in result["runs"])
        for k in ("allocation", "theme", "gross", "trade_risk", "open_risk")
    }
    lines += [
        "",
        f"Maximum admission ratios across all runs: `{maxima}`.",
        "Stale held-position days: "
        f"{sum(r['portfolio']['metrics']['stale_position_days'] for r in result['runs'])}.",
        "Gross and theme are identical for a crypto-only book. Exposure is calendar close",
        "gross/equity, so same-day round trips contribute costs and trades but no close exposure.",
        "Observed DD includes available portfolio opens and closes; benchmark DD uses closes.",
        "Ending equity is $10,000 × (1 + net return / 100); exact values are in local evidence.",
        "Daily curves, all closed trades, admission audits, exact eligibility and rejected",
        "candidate reasons are in the hashed local JSON evidence.",
        "",
        "Uncertainty uses 500 paired circular 20-day block resamples, seed 20261108,",
        "365-day annualization. Intervals describe mean daily excess over the matched",
        "benchmark, not compounded return differences or independent OOS confidence.",
        "",
        "## Parent comparison",
        "",
        "| Window/rule/cost | Parent LONG / variant candidates | Same schedule | "
        "Filter-before-scheduling parity |",
        "|---|---:|---|---|",
    ]
    for c in result["comparisons"]:
        lines.append(
            f"| {c['window']}/{c['strategy']}/{c['stress']}x | "
            f"{c['parent_long_candidates']}/{c['variant_candidates']} | {c['same_schedule']} | "
            f"{c['long_signal_filter_parity']} |"
        )
    lines += [
        "",
        "A two-sided parent's short can block a later long; its funded LONG legs therefore",
        "need not match the variant. Removing shorts at signal time reproduces CRYPTO-5",
        "exactly. No short/futures/margin positions enter any cash account.",
        "",
        "## Limitations and interpretation",
        "",
        "These are fixed seen-history comparisons, not a strategy search or a new sealed look.",
        "The registered surviving pair lists, earliest available stored bars and historical",
        "quality filters are not a point-in-time exchange universe. Venue spread/depth",
        "measurements, order increments, minimum sizes, impact, queueing, trading",
        "availability and intraday mark paths are unvalidated. Stops can gap beyond reserved",
        "risk. The 10% DD control only halts entries at observed opens/closes; it cannot",
        "guarantee a maximum loss. Zero yield is assumed on idle cash. No guarantee of",
        "positive returns, excess returns, execution capacity or promotion follows.",
        "",
    ]
    return "\n".join(lines)


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()  # noqa: S603,S607


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", type=Path)
    args = parser.parse_args()
    if SEALED != CRYPTO5_DEV_CUT:
        raise ValueError("parent sealed boundary changed")
    protocol_commit = git("log", "-1", "--format=%H", "--", PROTOCOL)
    if not protocol_commit or git("status", "--porcelain", "--", PROTOCOL, __file__):
        raise ValueError("commit clean protocol and implementation before the fixed run")
    pairs = sorted({p for ps in CRYPTO5_PAIRS.values() for p in ps})
    panel, meta = load_bounded(args.database, pairs)
    result = run_study(panel, meta)
    result.update(protocol_commit=protocol_commit, source_commit=git("rev-parse", "HEAD"))
    evidence = ROOT / ".toolkit-runs/conservative-crypto-cost-study/evidence.json"
    evidence.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(result, sort_keys=True, indent=2, default=str) + "\n"
    evidence.write_text(payload)
    evidence_hash = hashlib.sha256(payload.encode()).hexdigest()
    (ROOT / REPORT).write_text(render(result, evidence, evidence_hash))
    print(
        json.dumps(
            {
                "report": str(ROOT / REPORT),
                "evidence": str(evidence),
                "sha256": evidence_hash,
                "portfolio_runs": len(result["runs"]),
            }
        )
    )


if __name__ == "__main__":
    main()
