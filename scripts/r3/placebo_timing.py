#!/usr/bin/env python
"""R3-P — placebo timing test: do the approved entry signals beat random entries
with the same exits?

Pre-registration (binding): docs/research/PREREGISTRATION_r3_placebo_timing_2026-11-10.md
Results file (named there): docs/research/RESULTS_r3_placebo_timing_2026-11-10.md

What this script does, in order:

1. Loads daily ``massive`` bars 2016-10-17..2025-09-05 (development window only;
   nothing on or after 2025-09-07 is loaded) from a READ-ONLY database copy.
2. Runs the four PAPER_APPROVED versions with the library engine exactly as the
   runner does and checks the recorded development OOS rows (identity check).
   Any mismatch stops the study before a single placebo run.
3. Checks that the placebo signal function, given the real rule's own signal
   dates, reproduces the real rule's trades exactly (same stop, target, time
   stop, fills and R), and that the fast date planner equals a slow twin that
   finds blocked draws by running the library engine itself.
4. Runs K placebo runs per version and null (P-gate, P-trend), seed
   20261110 + run index, through the library engine. Finished runs are kept
   on disk and reused, so a second invocation only adds what is missing. Every
   run row carries a fingerprint of this script, the library modules it calls,
   the bars and the real rule's trade counts; rows with another fingerprint
   are refused, never reused.
5. Writes run-level CSVs, summary.json and the results markdown.

Two things in the output are NOT pre-registered. Both were added after the
adversarial review, are labelled as such in the results file, and feed no
reading:

* a post hoc benchmark, "always in when the gate allows" (the placebo signal
  function offered every bar instead of drawn bars), which sizes how much the
  P-gate placebo gains from being told the symbol-years the rule traded
  (``--no-posthoc`` leaves it out);
* descriptive splits of the pre-registered runs: trades whose entry fill is at
  or below the stop, and how the real signals bunch in time.

The placebo signal function is causal: at bar ``t`` it reads only the engine's
``series.head(t)`` view (ATR14, close, SMA50) and the regime label of that
session. Only the *dates* are drawn in advance.

How to run (from a directory without a ``.env``; the URL must be read-only)::

    PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=<repo>/src:<repo>/scripts \
    MARKET_DATA_PROVIDER=massive SIGNALFORGE_DATA_DIR=<dir of the copy> \
    DATABASE_URL="sqlite+pysqlite:///file:<copy>.sqlite?mode=ro&uri=true" \
    python <repo>/scripts/r3/placebo_timing.py --k 200 --out <raw output dir>

``--out`` is required and must be a directory this script owns: run rows found
there are reused only if their fingerprint matches. At most four worker
processes; each loads the bars once.

Research signal only — no order is placed, nothing is written to any database.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib
import json
import math
import os
import sys
import time
from datetime import UTC, date, datetime
from multiprocessing import get_context
from pathlib import Path
from typing import Any

import numpy as np

from signalforge.backtest.costs import CostModel
from signalforge.backtest.engine import EntrySignal, _resolve_exit, run_backtest
from signalforge.backtest.metrics import compute_metrics
from signalforge.data.series import PriceSeries
from signalforge.db.models import DataSnapshot
from signalforge.db.session import session_scope
from signalforge.domain import Direction, Horizon
from signalforge.research.backtest_runner import _is_boundary
from signalforge.research.features.daily import atr, sma
from signalforge.research.regime import NEUTRAL, RegimeState, Trend, regime_lookup
from signalforge.research.strategies import (
    High52Breakout,
    RelativeStrength,
    TrendContinuation,
    signal_fn_for,
)

# --------------------------------------------------------------------------- #
# fixed by the pre-registration
# --------------------------------------------------------------------------- #
START = date(2016, 10, 17)
END = date(2025, 9, 5)  # last development session
SEALED_FROM = date(2025, 9, 7)  # nothing on or after this date may be loaded
SOURCE = "massive"
BASE_SEED = 20261110  # seed of run r is BASE_SEED + r, r = 0..K-1
K_DEFAULT = 200
MAX_REDRAWS = 20
TREND_SMA = 50  # P-trend: close > SMA50
MIN_BARS = 60  # runner default (backtest_runner.run_strategy_over_universe)
WARMUP = MIN_BARS // 2  # the runner passes warmup=min_bars // 2
SPREAD_BPS = 5.0  # engine default; the runner does not override it
NULLS = ("gate", "trend")
SEGS = ("is", "oos", "all")
YEARS = tuple(range(START.year, END.year + 1))
# The pre-registration's own words for a "no" (quoted, never paraphrased, in the report).
NOT_DISTINGUISHABLE = (
    '"not distinguishable from gated (or trend-state) exposure with its exit geometry on this '
    'universe"'
)

# (version key, approved snapshot, recorded development OOS trades, recorded OOS expectancy R)
VERSIONS: tuple[tuple[str, int, int, float], ...] = (
    ("trend_continuation.short_swing", 3, 341, 0.2648),
    ("relative_strength.medium_swing", 3, 197, 0.3004),
    ("trend_continuation.medium_swing", 11, 1986, 0.2209),
    ("high52_breakout.medium_swing", 11, 525, 0.2274),
)
SNAPSHOT = {v[0]: v[1] for v in VERSIONS}

# Raw outputs are not committed; --out is required (no default location).
DEFAULT_RESULTS = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "research"
    / "RESULTS_r3_placebo_timing_2026-11-10.md"
)

# Library modules whose code decides a run's numbers. Their source, this script,
# the bars and the real rule's trade counts make up the fingerprint stamped on
# every run row.
_LIB_MODULES = (
    "signalforge.backtest.costs",
    "signalforge.backtest.engine",
    "signalforge.backtest.metrics",
    "signalforge.data.series",
    "signalforge.domain",
    "signalforge.research.backtest_runner",
    "signalforge.research.features.daily",
    "signalforge.research.regime",
    "signalforge.research.strategies",
    "signalforge.research.strategies.base",
    "signalforge.research.strategies.high52_breakout",
    "signalforge.research.strategies.relative_strength",
    "signalforge.research.strategies.trend_continuation",
)


_CODE_SHA: dict[str, str] = {}  # per process; the files do not change during a run


def script_sha256() -> str:
    if "script" not in _CODE_SHA:
        _CODE_SHA["script"] = hashlib.sha256(Path(__file__).resolve().read_bytes()).hexdigest()
    return _CODE_SHA["script"]


def library_sha256() -> str:
    if "library" not in _CODE_SHA:
        h = hashlib.sha256()
        for name in _LIB_MODULES:
            src = importlib.import_module(name).__file__
            if not src:
                raise RuntimeError(f"no source file for {name}")
            h.update(name.encode())
            h.update(Path(src).read_bytes())
        _CODE_SHA["library"] = h.hexdigest()
    return _CODE_SHA["library"]


def counts_sha256(counts: dict[str, dict[int, int]]) -> str:
    """Hash of one version's real trade counts per symbol-year (what the placebo matches)."""
    flat = sorted((s, int(y), int(n)) for s, d in counts.items() for y, n in d.items())
    return hashlib.sha256(json.dumps(flat).encode()).hexdigest()


def cell_fingerprint(key: str, null: str, bars_sha: str, counts_sha: str) -> str:
    """What a run row of this cell must have been made from: this script, the
    library modules, the bars of the version's snapshot and its trade counts."""
    parts = (script_sha256(), library_sha256(), bars_sha, counts_sha, key, null)
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]


def make_strategy(key: str) -> Any:
    if key == "trend_continuation.short_swing":
        return TrendContinuation(Horizon.SHORT_SWING)
    if key == "trend_continuation.medium_swing":
        return TrendContinuation(Horizon.MEDIUM_SWING)
    if key == "relative_strength.medium_swing":
        return RelativeStrength(Horizon.MEDIUM_SWING)
    if key == "high52_breakout.medium_swing":
        return High52Breakout()
    raise KeyError(key)


def geometry(key: str) -> tuple[int, float, float, int]:
    """(ATR window, stop multiple, target multiple, time-stop bars) read off the
    version's own parameter object — never typed in here."""
    strat = make_strategy(key)
    if strat.key != key:
        raise RuntimeError(f"strategy key mismatch: {strat.key} != {key}")
    p = strat.params
    ts = strat._time_stop() if hasattr(strat, "_time_stop") else p.time_stop_bars
    return int(p.atr_window), float(p.stop_atr), float(p.target_atr), int(ts)


def gate_allows(key: str, regime: RegimeState) -> bool:
    """The version's own regime gate, copied from its ``evaluate``:
    relative_strength requires trend BULL (and a market 63-day return to exist);
    trend_continuation and high52_breakout require ``not risk_off``."""
    if key.startswith("relative_strength"):
        return regime.trend is Trend.BULL and regime.market_ret_63d is not None
    return not regime.risk_off


def engine_slip(cm: CostModel) -> float:
    # identical expression to backtest/engine.py:94
    return (cm.slippage_bps + (SPREAD_BPS / 2 if cm.half_spread_fill_penalty else 0.0)) / 10_000.0


# --------------------------------------------------------------------------- #
# per-process state (bars are loaded once per process)
# --------------------------------------------------------------------------- #
_W: dict[str, Any] = {}


def _state() -> dict[str, Any]:
    if not _W:
        _W.update(
            bars={},
            snaps={},
            bars_sha={},
            regimes=None,
            feat={},
            elig={},
            exits={},
            counts=None,
            geom={},
        )
    return _W


def load_snapshot(snapshot_id: int) -> list[str]:
    st = _state()
    if snapshot_id in st["snaps"]:
        return st["snaps"][snapshot_id]
    with session_scope() as s:
        snap = s.get(DataSnapshot, snapshot_id)
        if snap is None:
            raise RuntimeError(f"data_snapshot {snapshot_id} not found")
        syms = sorted({str(x).strip().upper() for x in snap.symbols_json})
        for sym in [*syms, "SPY"]:
            if sym in st["bars"]:
                continue
            ser = PriceSeries.load(s, sym, START, END, source=SOURCE)
            if len(ser) and (ser.dates[0] < START or ser.dates[-1] > END):
                raise RuntimeError(f"window guard: {sym} {ser.dates[0]}..{ser.dates[-1]}")
            if len(ser) and ser.dates[-1] >= SEALED_FROM:
                raise RuntimeError(f"sealed guard: {sym} has a bar on {ser.dates[-1]}")
            st["bars"][sym] = ser
    if st["regimes"] is None:
        st["regimes"] = regime_lookup(st["bars"]["SPY"])
    # Fingerprint of every bar this snapshot's runs can read (its symbols and SPY).
    h = hashlib.sha256()
    for sym in sorted({*syms, "SPY"}):
        ser = st["bars"][sym]
        h.update(sym.encode())
        h.update(np.array([d.toordinal() for d in ser.dates], dtype=np.int64).tobytes())
        for arr in (ser.open, ser.high, ser.low, ser.close, ser.volume):
            h.update(np.ascontiguousarray(arr, dtype=np.float64).tobytes())
    st["bars_sha"][snapshot_id] = h.hexdigest()
    st["snaps"][snapshot_id] = syms
    return syms


def bars_sha256(snapshot_id: int) -> str:
    load_snapshot(snapshot_id)
    return _state()["bars_sha"][snapshot_id]


def geom(key: str) -> tuple[int, float, float, int]:
    st = _state()
    if key not in st["geom"]:
        st["geom"][key] = geometry(key)
    return st["geom"][key]


def features(sym: str, atr_window: int) -> dict[str, Any]:
    """Per-bar inputs for the date planner, each computed with the library
    feature functions (which read only bars <= t)."""
    st = _state()
    key = (sym, atr_window)
    f = st["feat"].get(key)
    if f is None:
        ser: PriceSeries = st["bars"][sym]
        n = len(ser)
        regimes = st["regimes"]
        regs = [regimes.get(d, NEUTRAL) for d in ser.dates]
        f = {
            "atr": np.array([atr(ser, t, atr_window) for t in range(n)], dtype=np.float64),
            "sma": np.array([sma(ser, t, TREND_SMA) for t in range(n)], dtype=np.float64),
            "not_off": np.array([not r.risk_off for r in regs], dtype=bool),
            "bull": np.array(
                [r.trend is Trend.BULL and r.market_ret_63d is not None for r in regs], dtype=bool
            ),
            "years": np.array([d.year for d in ser.dates], dtype=np.int64),
            "index": {d: i for i, d in enumerate(ser.dates)},
        }
        st["feat"][key] = f
    return f


def eligible_by_year(key: str, null: str, sym: str) -> dict[int, np.ndarray]:
    """Bars a placebo signal date may be drawn from, per calendar year.

    P-gate: the version's own regime gate allows an entry. P-trend: additionally
    close > SMA50. Both are limited to bars the engine can act on (index >=
    warm-up and not the last bar, so a next open exists) with ATR defined."""
    st = _state()
    ck = (key, null, sym)
    out = st["elig"].get(ck)
    if out is None:
        ser: PriceSeries = st["bars"][sym]
        n = len(ser)
        aw = geom(key)[0]
        f = features(sym, aw)
        mask = np.zeros(n, dtype=bool)
        mask[max(WARMUP, 1) : n - 1] = True
        mask &= f["bull"] if key.startswith("relative_strength") else f["not_off"]
        a = f["atr"]
        mask &= np.isfinite(a)
        mask &= np.where(np.isfinite(a), a, 0.0) > 0
        if null == "trend":
            s = f["sma"]
            mask &= np.isfinite(s)
            mask &= ser.close > np.where(np.isfinite(s), s, np.inf)
        elif null != "gate":
            raise KeyError(null)
        idx = np.nonzero(mask)[0]
        yrs = f["years"][idx]
        out = {int(y): idx[yrs == y] for y in np.unique(yrs)}
        st["elig"][ck] = out
    return out


def exit_index(key: str, sym: str, t: int) -> int:
    """Index of the bar on which a placebo trade signalled at bar ``t`` exits
    (library ``_resolve_exit``), or -1 if the engine would skip the signal
    (zero risk per share). Used only to decide whether a later drawn date falls
    inside an open placebo trade; the trades themselves come from
    ``run_backtest``."""
    st = _state()
    cache = st["exits"].setdefault((key, sym), {})
    e = cache.get(t)
    if e is None:
        ser: PriceSeries = st["bars"][sym]
        aw, sm, tm, ts = geom(key)
        a = float(features(sym, aw)["atr"][t])
        close = float(ser.close[t])
        sig = EntrySignal(
            direction=Direction.LONG,
            stop_price=close - sm * a,
            target_price=close + tm * a,
            time_stop_bars=ts,
        )
        slip = engine_slip(CostModel())
        entry_idx = t + 1
        entry_fill = ser.open[entry_idx] * (1 + slip)
        if abs(entry_fill - sig.stop_price) <= 0:
            e = -1
        else:
            e = int(_resolve_exit(ser, entry_idx, entry_fill, sig, 1, slip)[0])
        cache[t] = e
    return e


# --------------------------------------------------------------------------- #
# placebo signal function (causal) and date planner
# --------------------------------------------------------------------------- #
def make_placebo_fn(
    key: str,
    null: str,
    plan_dates: dict[str, set[date]],
    record: dict[tuple[str, int], tuple[float, float, float | None, int]] | None = None,
):
    """A ``SignalFn`` that fires on pre-drawn dates only.

    At bar ``t`` it sees the engine's ``series.head(t)`` and nothing else. It
    re-checks the regime gate (and, for P-trend, close > SMA50) on that bar and
    builds stop / target / time stop from ATR at ``t`` with the version's own
    multiples — the same arithmetic as the real rule's ``evaluate``."""
    aw, sm, tm, ts = geom(key)
    regimes = _state()["regimes"]
    trend_null = null == "trend"
    if null not in NULLS:
        raise KeyError(null)

    def _fn(series: PriceSeries, t: int) -> EntrySignal | None:
        planned = plan_dates.get(series.symbol)
        if not planned:
            return None
        stamp = series.dates[t]
        if stamp not in planned:
            return None
        if not gate_allows(key, regimes.get(stamp, NEUTRAL)):
            return None
        a = atr(series, t, aw)
        if math.isnan(a) or a <= 0:
            return None
        close = float(series.close[t])
        if trend_null:
            m = sma(series, t, TREND_SMA)
            if math.isnan(m) or not close > m:
                return None
        sig = EntrySignal(
            direction=Direction.LONG,
            stop_price=close - sm * a,
            target_price=close + tm * a,
            time_stop_bars=ts,
            reason=f"placebo {null}",
        )
        if record is not None:
            record[(series.symbol, t)] = (close, sig.stop_price, sig.target_price, ts)
        return sig

    return _fn


def plan_symbol(
    rng: np.random.Generator,
    key: str,
    null: str,
    sym: str,
    counts: dict[int, int],
) -> dict[str, Any]:
    """Draw the placebo signal bars of one symbol for one run.

    Every draw is uniform over its symbol-year's eligible bars. The draws are
    then played in date order, as the engine would: a draw on a bar the engine
    does not evaluate because an earlier placebo trade is open (signal bar
    through exit bar) "falls inside an open placebo trade" and is redrawn
    uniformly from the same symbol-year, up to MAX_REDRAWS times, then dropped.
    Rounds repeat until every surviving draw is executed."""
    elig = eligible_by_year(key, null, sym)
    d_year: list[int] = []
    d_t: list[int] = []
    no_eligible = 0
    target = 0
    for y in sorted(counts):
        k = int(counts[y])
        target += k
        el = elig.get(y)
        if el is None or len(el) == 0:
            no_eligible += k
            continue
        picks = rng.integers(0, len(el), size=k)
        for j in picks:
            d_year.append(y)
            d_t.append(int(el[int(j)]))
    n = len(d_t)
    attempts = [0] * n
    alive = [True] * n
    dropped = 0
    redraws = 0
    zero_risk: list[int] = []
    executed: list[int] = []
    while True:
        order = sorted((i for i in range(n) if alive[i]), key=lambda i: (d_t[i], i))
        block_end = -1
        skipped: list[int] = []
        executed = []
        zero_risk = []
        for i in order:
            t = d_t[i]
            if t > block_end:
                e = exit_index(key, sym, t)
                if e < 0:
                    zero_risk.append(t)
                    block_end = t
                else:
                    executed.append(t)
                    block_end = e
            else:
                skipped.append(i)
        if not skipped:
            break
        for i in sorted(skipped):
            if attempts[i] >= MAX_REDRAWS:
                alive[i] = False
                dropped += 1
            else:
                attempts[i] += 1
                redraws += 1
                el = elig[d_year[i]]
                d_t[i] = int(el[int(rng.integers(0, len(el)))])
    return {
        "bars": executed,  # ascending, each produces exactly one engine trade
        "zero_risk": zero_risk,
        "target": target,
        "dropped": dropped,
        "no_eligible": no_eligible,
        "redraws": redraws,
    }


def plan_symbol_engine_loop(
    rng: np.random.Generator,
    key: str,
    null: str,
    sym: str,
    counts: dict[int, int],
) -> dict[str, Any]:
    """Self-check twin of ``plan_symbol`` that never calls ``exit_index``.

    It finds out which draws fall inside an open placebo trade by running the
    library engine itself on the current date set and seeing which dates the
    engine never evaluated, then redraws exactly as ``plan_symbol`` does (same
    order, same generator calls). Used once per version and null on a few
    symbols to prove the fast planner is the engine's own behaviour."""
    st = _state()
    ser: PriceSeries = st["bars"][sym]
    elig = eligible_by_year(key, null, sym)
    cm = CostModel()
    d_year: list[int] = []
    d_t: list[int] = []
    no_eligible = 0
    target = 0
    for y in sorted(counts):
        k = int(counts[y])
        target += k
        el = elig.get(y)
        if el is None or len(el) == 0:
            no_eligible += k
            continue
        picks = rng.integers(0, len(el), size=k)
        for j in picks:
            d_year.append(y)
            d_t.append(int(el[int(j)]))
    n = len(d_t)
    attempts = [0] * n
    alive = [True] * n
    dropped = 0
    redraws = 0
    executed: list[int] = []
    passes = 0
    while True:
        live = [i for i in range(n) if alive[i]]
        rec: dict[tuple[str, int], tuple[float, float, float | None, int]] = {}
        fn = make_placebo_fn(key, null, {sym: {ser.dates[d_t[i]] for i in live}}, rec)
        out = run_backtest(ser, fn, cost_model=cm, warmup=MIN_BARS // 2)
        passes += 1
        fired = {t for (_s, t) in rec}
        if len(out.trades) != len(fired):
            raise RuntimeError("engine fired a signal without a trade (zero risk) in self-check")
        seen: set[int] = set()
        skipped: list[int] = []
        for i in sorted(live, key=lambda i: (d_t[i], i)):
            t = d_t[i]
            if t in fired and t not in seen:
                seen.add(t)
            else:
                skipped.append(i)
        executed = sorted(seen)
        if not skipped:
            break
        for i in sorted(skipped):
            if attempts[i] >= MAX_REDRAWS:
                alive[i] = False
                dropped += 1
            else:
                attempts[i] += 1
                redraws += 1
                el = elig[d_year[i]]
                d_t[i] = int(el[int(rng.integers(0, len(el)))])
    return {
        "bars": executed,
        "zero_risk": [],
        "target": target,
        "dropped": dropped,
        "no_eligible": no_eligible,
        "redraws": redraws,
        "engine_passes": passes,
    }


# --------------------------------------------------------------------------- #
# metrics
# --------------------------------------------------------------------------- #
def stable_r(pnl_r: float, entry_fill: float, close_t: float, stop: float) -> float:
    """Stable R = (exit - entry) / (close_t - stop_t).

    Engine R divides the same price move by |entry fill - stop|, so
    exit - entry = pnl_r * |entry fill - stop| exactly (unrounded fills)."""
    return pnl_r * abs(entry_fill - stop) / (close_t - stop)


def seg_metrics(
    pnl: np.ndarray, stab: np.ndarray, hold: np.ndarray, mask: np.ndarray
) -> dict[str, float]:
    n = int(mask.sum())
    if n == 0:
        nan = float("nan")
        return {
            "n": 0,
            "exp_r": nan,
            "total_r": 0.0,
            "win": nan,
            "hold": nan,
            "exp_s": nan,
            "total_s": 0.0,
        }
    p = pnl[mask]
    s = stab[mask]
    return {
        "n": n,
        "exp_r": float(p.mean()),
        "total_r": float(p.sum()),
        "win": float((p > 0).mean()),
        "hold": float(hold[mask].mean()),
        "exp_s": float(s.mean()),
        "total_s": float(s.sum()),
    }


def flat_metrics(
    pnl: list[float],
    stab: list[float],
    hold: list[int],
    oos: list[bool],
    yrs: list[int],
    gap: list[bool],
) -> dict[str, float]:
    """Run-level numbers. ``gap`` marks trades whose entry fill is at or below
    the stop; the ``*_gap_*`` columns are a descriptive split added after the
    review (not pre-registered) and change no other column."""
    p = np.asarray(pnl, dtype=np.float64)
    s = np.asarray(stab, dtype=np.float64)
    h = np.asarray(hold, dtype=np.float64)
    o = np.asarray(oos, dtype=bool)
    y = np.asarray(yrs, dtype=np.int64)
    g = np.asarray(gap, dtype=bool)
    out: dict[str, float] = {}
    masks = {"is": ~o, "oos": o, "all": np.ones(len(p), dtype=bool)}
    for seg in SEGS:
        for k, v in seg_metrics(p, s, h, masks[seg]).items():
            out[f"{seg}_{k}"] = v
    for yr in YEARS:
        m = y == yr
        out[f"y{yr}_n"] = int(m.sum())
        out[f"y{yr}_total_r"] = float(p[m].sum()) if m.any() else 0.0
    for seg in SEGS:
        m = masks[seg] & g
        out[f"{seg}_gap_n"] = int(m.sum())
        out[f"{seg}_gap_total_r"] = float(p[m].sum()) if m.any() else 0.0
    return out


# --------------------------------------------------------------------------- #
# worker tasks
# --------------------------------------------------------------------------- #
def actual_task(key: str) -> dict[str, Any]:
    """The real rule through the library engine, exactly as the runner loops it,
    plus the placebo-geometry replay check."""
    t0 = time.time()
    syms = load_snapshot(SNAPSHOT[key])
    st = _state()
    bars = st["bars"]
    regimes = st["regimes"]
    strat = make_strategy(key)
    fn = signal_fn_for(strat, regime_by_date=regimes)
    cm = CostModel()
    slip = engine_slip(cm)
    aw, sm, tm, ts = geom(key)

    rows: list[dict[str, Any]] = []
    is_trades, oos_trades = [], []
    actual_by_sym: dict[str, list[Any]] = {}
    sig_by_sym: dict[str, dict[int, tuple[float, float, float | None, int]]] = {}
    n_series = 0
    for sym in syms:
        ser: PriceSeries = bars[sym]
        if len(ser) < MIN_BARS:
            continue
        n_series += 1
        rec: dict[int, tuple[float, float, float | None, int]] = {}

        def rfn(series: PriceSeries, t: int, _rec=rec) -> EntrySignal | None:
            sig = fn(series, t)
            if sig is not None:
                _rec[t] = (
                    float(series.close[t]),
                    sig.stop_price,
                    sig.target_price,
                    sig.time_stop_bars,
                )
            return sig

        out = run_backtest(ser, rfn, cost_model=cm, warmup=MIN_BARS // 2)
        boundary = _is_boundary(ser)
        index = features(sym, aw)["index"]
        actual_by_sym[sym] = out.trades
        sig_by_sym[sym] = rec
        for tr in out.trades:
            ei = index[tr.entry_date]
            t = ei - 1
            close_t, stop, target, tsb = rec[t]
            entry_fill = ser.open[ei] * (1 + slip)
            if abs(round(entry_fill, 4) - tr.entry_price) > 1e-9:
                raise RuntimeError(f"entry fill reconstruction failed for {sym} {tr.entry_date}")
            # stable R from unrounded fills must agree with the trade's rounded prices
            direct = (tr.exit_price - tr.entry_price) / (close_t - stop)
            if abs(direct - stable_r(tr.pnl_r, entry_fill, close_t, stop)) > 5e-3:
                raise RuntimeError(f"stable R reconstruction failed for {sym} {tr.entry_date}")
            in_oos = tr.entry_date > boundary
            (oos_trades if in_oos else is_trades).append(tr)
            rows.append(
                {
                    "symbol": sym,
                    "signal_date": ser.dates[t].isoformat(),
                    "signal_year": ser.dates[t].year,
                    "entry_date": tr.entry_date.isoformat(),
                    "exit_date": tr.exit_date.isoformat(),
                    "segment": "oos" if in_oos else "is",
                    "bars_held": tr.bars_held,
                    "exit_reason": tr.exit_reason,
                    "pnl_r": tr.pnl_r,
                    "stable_r": stable_r(tr.pnl_r, entry_fill, close_t, stop),
                    "close_t": close_t,
                    "stop": stop,
                    "target": target,
                    "time_stop_bars": tsb,
                    "trend_ok": bool(
                        math.isfinite(features(sym, aw)["sma"][t])
                        and close_t > features(sym, aw)["sma"][t]
                    ),
                    # descriptive, added after the review: the entry fill (and the raw
                    # open) at or below the stop — the engine closes such a trade on
                    # the entry bar at the stop price
                    "fill_le_stop": bool(entry_fill <= stop),
                    "open_le_stop": bool(ser.open[ei] <= stop),
                }
            )

    m_is, m_oos = compute_metrics(is_trades), compute_metrics(oos_trades)

    # --- replay check: placebo P-gate function on the real rule's own dates ---
    plan_dates = {sym: {bars[sym].dates[t] for t in rec} for sym, rec in sig_by_sym.items() if rec}
    prec: dict[tuple[str, int], tuple[float, float, float | None, int]] = {}
    pfn = make_placebo_fn(key, "gate", plan_dates, prec)
    replay_trades = 0
    replay_mismatch = 0
    geometry_mismatch = 0
    for sym, trades in actual_by_sym.items():
        if not trades:
            continue
        out2 = run_backtest(bars[sym], pfn, cost_model=cm, warmup=MIN_BARS // 2)
        replay_trades += len(out2.trades)
        if len(out2.trades) != len(trades):
            replay_mismatch += abs(len(out2.trades) - len(trades)) or 1
            continue
        for a_tr, b_tr in zip(trades, out2.trades, strict=True):
            same = (
                a_tr.entry_date == b_tr.entry_date
                and a_tr.exit_date == b_tr.exit_date
                and a_tr.entry_price == b_tr.entry_price
                and a_tr.exit_price == b_tr.exit_price
                and a_tr.pnl_r == b_tr.pnl_r
                and a_tr.bars_held == b_tr.bars_held
                and a_tr.exit_reason == b_tr.exit_reason
            )
            replay_mismatch += 0 if same else 1
        for t, real in sig_by_sym[sym].items():
            got = prec.get((sym, t))
            if got is None or got[1] != real[1] or got[2] != real[2] or got[3] != real[3]:
                geometry_mismatch += 1

    # --- one-symbol example (first symbol, alphabetically, that traded) ---
    example: dict[str, Any] = {}
    for sym in syms:
        rec = sig_by_sym.get(sym) or {}
        if not rec:
            continue
        ser = bars[sym]
        one_fn = make_placebo_fn(key, "gate", {sym: {ser.dates[t] for t in rec}})
        checked, equal, samples = 0, 0, []
        for t in sorted(rec):
            psig = one_fn(ser.head(t), t)
            real = rec[t]
            ok = (
                psig is not None
                and psig.stop_price == real[1]
                and psig.target_price == real[2]
                and psig.time_stop_bars == real[3]
            )
            checked += 1
            equal += 1 if ok else 0
            if len(samples) < 3:
                samples.append(
                    {
                        "signal_date": ser.dates[t].isoformat(),
                        "real_stop": real[1],
                        "placebo_stop": None if psig is None else psig.stop_price,
                        "real_target": real[2],
                        "placebo_target": None if psig is None else psig.target_price,
                        "real_time_stop": real[3],
                        "placebo_time_stop": None if psig is None else psig.time_stop_bars,
                    }
                )
        example = {"symbol": sym, "signals_checked": checked, "equal": equal, "samples": samples}
        break

    # --- planner self-check: fast planner vs engine-in-the-loop redraw ---
    # Own generators (seed BASE_SEED), so the study's run streams are untouched.
    year_counts: dict[str, dict[int, int]] = {}
    for r in rows:
        year_counts.setdefault(r["symbol"], {}).setdefault(r["signal_year"], 0)
        year_counts[r["symbol"]][r["signal_year"]] += 1
    busiest = sorted(year_counts, key=lambda s: (-sum(year_counts[s].values()), s))[:5]
    selfcheck = {"symbols": busiest, "cases": 0, "equal": 0, "redraws": 0, "engine_passes": 0}
    for null in NULLS:
        for sym in busiest:
            fast = plan_symbol(np.random.default_rng(BASE_SEED), key, null, sym, year_counts[sym])
            slow = plan_symbol_engine_loop(
                np.random.default_rng(BASE_SEED), key, null, sym, year_counts[sym]
            )
            same = all(
                fast[f] == slow[f] for f in ("bars", "target", "dropped", "no_eligible", "redraws")
            )
            selfcheck["cases"] += 1
            selfcheck["equal"] += 1 if same and not fast["zero_risk"] else 0
            selfcheck["redraws"] += slow["redraws"]
            selfcheck["engine_passes"] += slow["engine_passes"]

    # --- eligible-bar census (context for the shortfall) ---
    census = {}
    for null in NULLS:
        tot = 0
        for sym in syms:
            if len(bars[sym]) < MIN_BARS:
                continue
            tot += sum(len(v) for v in eligible_by_year(key, null, sym).values())
        census[null] = tot
    total_bars = sum(len(bars[s]) for s in syms if len(bars[s]) >= MIN_BARS)

    spy = bars["SPY"]
    return {
        "key": key,
        "snapshot": SNAPSHOT[key],
        "n_symbols": len(syms),
        "n_series": n_series,
        "geometry": {"atr_window": aw, "stop_atr": sm, "target_atr": tm, "time_stop_bars": ts},
        "rows": rows,
        "identity": {
            "oos_n": m_oos.n_trades,
            "oos_expectancy_r": m_oos.expectancy_r,
            "is_n": m_is.n_trades,
            "is_expectancy_r": m_is.expectancy_r,
        },
        "replay": {
            "actual_trades": len(rows),
            "replay_trades": replay_trades,
            "trade_mismatches": replay_mismatch,
            "geometry_mismatches": geometry_mismatch,
        },
        "example": example,
        "planner_selfcheck": selfcheck,
        "eligible_bars": census,
        "total_bars": total_bars,
        "full_history_boundary": _is_boundary(spy).isoformat(),
        "first_bar": min(bars[s].dates[0] for s in syms if len(bars[s])).isoformat(),
        "last_bar": max(bars[s].dates[-1] for s in syms if len(bars[s])).isoformat(),
        "bars_sha256": bars_sha256(SNAPSHOT[key]),
        "seconds": round(time.time() - t0, 1),
    }


def gated_exposure_task(key: str) -> dict[str, Any]:
    """POST HOC, NOT PRE-REGISTERED (added after the adversarial review; no
    reading uses it): "always in when the gate allows".

    The placebo signal function is offered every bar of every symbol instead of
    drawn bars, so it fires whenever the version's regime gate allows an entry
    and the symbol is flat: same ATR14 stop, target and time stop, same library
    engine, one position per symbol. No random number, no parameter. It shows
    what gated exposure with the exit geometry earns when nothing tells it
    which symbol-years the real rule traded."""
    t0 = time.time()
    syms = load_snapshot(SNAPSHOT[key])
    bars = _state()["bars"]
    cm = CostModel()
    fn = make_placebo_fn(key, "gate", {sym: set(bars[sym].dates) for sym in syms})
    pnl: dict[str, list[float]] = {"is": [], "oos": []}
    for sym in syms:
        ser: PriceSeries = bars[sym]
        if len(ser) < MIN_BARS:
            continue
        boundary = _is_boundary(ser)
        for tr in run_backtest(ser, fn, cost_model=cm, warmup=MIN_BARS // 2).trades:
            pnl["oos" if tr.entry_date > boundary else "is"].append(tr.pnl_r)
    return {
        "key": key,
        "segments": {
            seg: {"n": len(v), "exp_r": float(np.mean(v)) if v else float("nan")}
            for seg, v in pnl.items()
        },
        "bars_sha256": bars_sha256(SNAPSHOT[key]),
        "seconds": round(time.time() - t0, 1),
    }


def _counts(path: str) -> dict[str, dict[str, dict[int, int]]]:
    st = _state()
    if st["counts"] is None or st["counts"][0] != path:
        raw = json.loads(Path(path).read_text())
        st["counts"] = (
            path,
            {
                k: {s: {int(y): int(c) for y, c in d.items()} for s, d in v.items()}
                for k, v in raw.items()
            },
        )
    return st["counts"][1]


def twin_task(task: tuple[str, str, int, str, dict[str, Any]]) -> dict[str, Any]:
    """Whole-run check: redo one placebo run with the engine-in-the-loop planner
    and compare every run-level number with the row the study wrote."""
    key, null, run, counts_path, want = task
    got = placebo_task((key, null, run, counts_path), planner=plan_symbol_engine_loop)["row"]
    diffs = []
    for c in got:
        if c == "seconds":
            continue
        same = got[c] == want[c] if c == "fp" else abs(float(got[c]) - float(want[c])) <= 1e-12
        if not same:
            diffs.append(c)
    return {
        "key": key,
        "null": null,
        "run": run,
        "fp": got["fp"],
        "identical": not diffs,
        "differing_columns": diffs,
        "seconds": got["seconds"],
    }


def placebo_task(task: tuple[str, str, int, str], planner: Any = None) -> dict[str, Any]:
    key, null, run, counts_path = task
    plan_one = planner or plan_symbol
    t0 = time.time()
    syms = load_snapshot(SNAPSHOT[key])
    st = _state()
    bars = st["bars"]
    counts = _counts(counts_path)[key]
    cm = CostModel()
    slip = engine_slip(cm)
    seed = BASE_SEED + run
    rng = np.random.default_rng(seed)

    plan: dict[str, list[int]] = {}
    target = dropped = no_eligible = redraws = zero_risk = 0
    for sym in syms:  # alphabetical — fixes the order the generator is consumed in
        c = counts.get(sym)
        if not c:
            continue
        res = plan_one(rng, key, null, sym, c)
        target += res["target"]
        dropped += res["dropped"]
        no_eligible += res["no_eligible"]
        redraws += res["redraws"]
        zero_risk += len(res["zero_risk"])
        if res["bars"] or res["zero_risk"]:
            plan[sym] = res["bars"]
            if res["zero_risk"]:
                plan[sym] = sorted([*res["bars"], *res["zero_risk"]])

    plan_dates = {sym: {bars[sym].dates[t] for t in ts} for sym, ts in plan.items()}
    rec: dict[tuple[str, int], tuple[float, float, float | None, int]] = {}
    fn = make_placebo_fn(key, null, plan_dates, rec)

    pnl: list[float] = []
    stab: list[float] = []
    hold: list[int] = []
    oos: list[bool] = []
    yrs: list[int] = []
    gap: list[bool] = []
    for sym in syms:
        ts = plan.get(sym)
        if not ts:
            continue
        ser: PriceSeries = bars[sym]
        out = run_backtest(ser, fn, cost_model=cm, warmup=MIN_BARS // 2)
        traded = [t for t in ts if exit_index(key, sym, t) >= 0]
        if [tr.entry_date for tr in out.trades] != [ser.dates[t + 1] for t in traded] or [
            tr.exit_date for tr in out.trades
        ] != [ser.dates[exit_index(key, sym, t)] for t in traded]:
            raise RuntimeError(
                f"planner/engine disagreement: {key} {null} run {run} {sym}: "
                f"{len(out.trades)} engine trades vs {len(traded)} planned"
            )
        boundary = _is_boundary(ser)
        for tr, t in zip(out.trades, traded, strict=True):
            close_t, stop, _target, _ts = rec[(sym, t)]
            entry_fill = ser.open[t + 1] * (1 + slip)
            pnl.append(tr.pnl_r)
            stab.append(stable_r(tr.pnl_r, entry_fill, close_t, stop))
            hold.append(tr.bars_held)
            oos.append(tr.entry_date > boundary)
            yrs.append(ser.dates[t].year)
            gap.append(bool(entry_fill <= stop))

    row: dict[str, Any] = {
        "run": run,
        "seed": seed,
        "target": target,
        "placed": len(pnl),
        "dropped": dropped,
        "no_eligible": no_eligible,
        "zero_risk": zero_risk,
        "redraws": redraws,
    }
    row.update(flat_metrics(pnl, stab, hold, oos, yrs, gap))
    row["seconds"] = round(time.time() - t0, 2)
    # Stamped where the work is done: this process's own script, library, bars and counts.
    row["fp"] = cell_fingerprint(
        key, null, bars_sha256(SNAPSHOT[key]), counts_sha256(_counts(counts_path)[key])
    )
    return {"key": key, "null": null, "row": row}


# --------------------------------------------------------------------------- #
# main-process helpers
# --------------------------------------------------------------------------- #
def log(msg: str) -> None:
    print(f"[{datetime.now(UTC).strftime('%H:%M:%S')}Z] {msg}", flush=True)


def cell_path(out: Path, key: str, null: str) -> Path:
    return out / f"placebo__{key}__{null}.csv"


_INT_COLS = frozenset(
    {"run", "seed", "target", "placed", "dropped", "no_eligible", "zero_risk", "redraws"}
)


def read_cell(path: Path) -> dict[int, dict[str, Any]]:
    """Run rows of one cell, keyed by run index. ``fp`` (the fingerprint) stays a
    string; a file written before fingerprints existed has no such column."""
    rows: dict[int, dict[str, Any]] = {}
    if not path.exists():
        return rows
    with path.open(newline="") as fh:
        for r in csv.DictReader(fh):
            row: dict[str, Any] = {}
            for k, v in r.items():
                if k == "fp":
                    row[k] = v
                    continue
                x = float(v)
                row[k] = int(x) if (k in _INT_COLS or k.endswith("_n")) else x
            rows[int(row["run"])] = row
    return rows


def write_cell(path: Path, rows: dict[int, dict[str, Any]]) -> None:
    if not rows:
        return
    cols = list(next(iter(rows.values())).keys())
    tmp = path.with_suffix(".csv.tmp")
    with tmp.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for run in sorted(rows):
            w.writerow(rows[run])
    tmp.replace(path)


def _json_default(o: Any) -> Any:
    if isinstance(o, np.bool_):
        return bool(o)
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.floating):
        return float(o)
    raise TypeError(f"not JSON serialisable: {type(o).__name__}")


def holm(pvals: dict[str, float]) -> dict[str, float]:
    items = sorted(pvals.items(), key=lambda kv: kv[1])
    m = len(items)
    out: dict[str, float] = {}
    running = 0.0
    for i, (k, p) in enumerate(items):
        running = max(running, min(1.0, (m - i) * p))
        out[k] = running
    return out


def compare(actual: float, placebo: np.ndarray) -> dict[str, float]:
    """Actual vs the placebo distribution. p is one-sided: the share of placebo
    runs at or above the actual value, with the (k+1)/(K+1) correction."""
    k_runs = len(placebo)
    ge = int((placebo >= actual).sum())
    lo, hi = np.percentile(placebo, [2.5, 97.5])
    mean = float(placebo.mean())
    return {
        "actual": float(actual),
        "placebo_mean": mean,
        "placebo_p2_5": float(lo),
        "placebo_p97_5": float(hi),
        "alpha": float(actual - mean),
        "n_placebo_ge_actual": ge,
        "p": (ge + 1) / (k_runs + 1),
    }


def gap_split(
    am: dict[str, float], col: dict[str, np.ndarray], seg: str, alpha: float
) -> dict[str, float]:
    """Descriptive split (not pre-registered): how much of a segment's expectancy,
    and of its timing alpha, comes from trades whose entry fill is at or below
    the stop. The engine closes such a trade on the entry bar at the stop price."""
    n_act = am[f"{seg}_n"]
    act_contrib = am[f"{seg}_gap_total_r"] / n_act
    n_pl = col[f"{seg}_n"]
    pl_contrib = float((col[f"{seg}_gap_total_r"] / n_pl).mean())
    return {
        "actual_n": int(am[f"{seg}_gap_n"]),
        "actual_share": am[f"{seg}_gap_n"] / n_act,
        "actual_total_r": am[f"{seg}_gap_total_r"],
        "actual_contribution_to_exp_r": act_contrib,
        "placebo_share_mean": float((col[f"{seg}_gap_n"] / n_pl).mean()),
        "placebo_contribution_to_exp_r_mean": pl_contrib,
        "alpha_from_these_fills": act_contrib - pl_contrib,
        "alpha_from_other_trades": alpha - (act_contrib - pl_contrib),
    }


def clustering(rows: list[dict[str, Any]], seg: str) -> dict[str, float]:
    """Descriptive (not pre-registered): how the real rule's trades of a segment
    bunch in time, and the standard error of its expectancy when trades signalled
    in the same ISO week are treated as one cluster."""
    sel = [r for r in rows if r["segment"] == seg]
    n = len(sel)
    r = np.array([x["pnl_r"] for x in sel], dtype=np.float64)
    dev = r - r.mean()
    days = [date.fromisoformat(x["signal_date"]) for x in sel]
    per_day: dict[date, int] = {}
    per_week: dict[tuple[int, int], float] = {}
    for d, x in zip(days, dev, strict=True):
        per_day[d] = per_day.get(d, 0) + 1
        wk = (d.isocalendar().year, d.isocalendar().week)
        per_week[wk] = per_week.get(wk, 0.0) + float(x)
    g = np.array(list(per_week.values()), dtype=np.float64)
    return {
        "n": n,
        "signal_dates": len(per_day),
        "top10_dates_share": sum(sorted(per_day.values(), reverse=True)[:10]) / n,
        "weeks": len(g),
        "se_iid": float(r.std(ddof=1) / math.sqrt(n)),
        "se_week_clustered": float(
            math.sqrt(float((g**2).sum())) / n * math.sqrt(len(g) / (len(g) - 1))
        ),
    }


def summarise(out: Path, actual: dict[str, Any], k_target: int) -> dict[str, Any]:
    boundary = date.fromisoformat(
        next(iter(actual.values()))["full_history_boundary"]
    )  # same SPY series for every version
    years = {
        "is": (boundary - START).days / 365.25,
        "oos": (END - boundary).days / 365.25,
        "all": (END - START).days / 365.25,
    }
    summary: dict[str, Any] = {
        "meta": {
            "study": "R3-P placebo timing",
            "preregistration": "docs/research/PREREGISTRATION_r3_placebo_timing_2026-11-10.md",
            "window": [START.isoformat(), END.isoformat()],
            "source": SOURCE,
            "base_seed": BASE_SEED,
            "k_target": k_target,
            "max_redraws": MAX_REDRAWS,
            "full_history_is_oos_boundary": boundary.isoformat(),
            "segment_years": years,
            "generated_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        },
        "versions": {},
    }
    primary_p: dict[str, float] = {}
    primary_p_stable: dict[str, float] = {}
    for key, snapshot, rec_n, rec_exp in VERSIONS:
        a = actual[key]
        rows = a["rows"]
        pnl = [r["pnl_r"] for r in rows]
        stab = [r["stable_r"] for r in rows]
        hold = [r["bars_held"] for r in rows]
        oos = [r["segment"] == "oos" for r in rows]
        yrs = [r["signal_year"] for r in rows]
        gap = [r["fill_le_stop"] for r in rows]
        am = flat_metrics(pnl, stab, hold, oos, yrs, gap)
        v: dict[str, Any] = {
            "snapshot": snapshot,
            "n_symbols": a["n_symbols"],
            "geometry": a["geometry"],
            "identity": {
                **a["identity"],
                "recorded_oos_n": rec_n,
                "recorded_oos_expectancy_r": rec_exp,
                "match": bool(
                    a["identity"]["oos_n"] == rec_n
                    and round(float(a["identity"]["oos_expectancy_r"]), 4) == rec_exp
                ),
            },
            "replay_check": a["replay"],
            "planner_selfcheck": a["planner_selfcheck"],
            "bars_loaded": {"first": a["first_bar"], "last": a["last_bar"]},
            "geometry_example": a["example"],
            "eligible_bars": a["eligible_bars"],
            "total_bars": a["total_bars"],
            "actual_trend_ok_share": float(np.mean([r["trend_ok"] for r in rows])),
            "actual": {
                seg: {
                    "n": am[f"{seg}_n"],
                    "exp_r": am[f"{seg}_exp_r"],
                    "total_r": am[f"{seg}_total_r"],
                    "exp_s": am[f"{seg}_exp_s"],
                    "total_s": am[f"{seg}_total_s"],
                    "win": am[f"{seg}_win"],
                    "hold": am[f"{seg}_hold"],
                    "total_r_per_year": am[f"{seg}_total_r"] / years[seg],
                    "total_s_per_year": am[f"{seg}_total_s"] / years[seg],
                }
                for seg in SEGS
            },
            "actual_by_year": {
                str(y): {"n": am[f"y{y}_n"], "total_r": am[f"y{y}_total_r"]} for y in YEARS
            },
            # descriptive, not pre-registered (see gap_split and clustering)
            "actual_open_le_stop_n": {
                seg: int(
                    sum(
                        1
                        for r in rows
                        if r["open_le_stop"] and (seg == "all" or r["segment"] == seg)
                    )
                )
                for seg in SEGS
            },
            "clustering": {seg: clustering(rows, seg) for seg in ("is", "oos")},
            "actual_fill_le_stop_pnl_r": [r["pnl_r"] for r in rows if r["fill_le_stop"]],
            "nulls": {},
        }
        for null in NULLS:
            cell = read_cell(cell_path(out, key, null))
            runs = sorted(cell)
            k_runs = len(runs)
            nd: dict[str, Any] = {"K": k_runs, "runs": [runs[0], runs[-1]] if runs else []}
            if k_runs == 0:
                v["nulls"][null] = nd
                continue
            col = {c: np.array([cell[r][c] for r in runs]) for c in cell[runs[0]] if c != "fp"}
            nd["fingerprint"] = sorted({str(cell[r].get("fp")) for r in runs})
            nd["contiguous_from_zero"] = runs == list(range(k_runs))
            tgt = col["target"]
            nd["shortfall"] = {
                "target_per_run": float(tgt.mean()),
                "placed_mean": float(col["placed"].mean()),
                "placed_min": float(col["placed"].min()),
                "dropped_after_redraws_mean": float(col["dropped"].mean()),
                "dropped_after_redraws_max": float(col["dropped"].max()),
                "no_eligible_bar_mean": float(col["no_eligible"].mean()),
                "zero_risk_mean": float(col["zero_risk"].mean()),
                "shortfall_mean": float((tgt - col["placed"]).mean()),
                "shortfall_pct_mean": float(((tgt - col["placed"]) / tgt).mean() * 100.0),
                "shortfall_pct_max": float(((tgt - col["placed"]) / tgt).max() * 100.0),
                "redraws_mean": float(col["redraws"].mean()),
            }
            nd["segments"] = {}
            for seg in SEGS:
                sa = v["actual"][seg]
                sd: dict[str, Any] = {"placebo_n_mean": float(col[f"{seg}_n"].mean())}
                sd["exp_r"] = compare(sa["exp_r"], col[f"{seg}_exp_r"])
                sd["exp_s"] = compare(sa["exp_s"], col[f"{seg}_exp_s"])
                sd["total_r"] = compare(sa["total_r"], col[f"{seg}_total_r"])
                sd["total_s"] = compare(sa["total_s"], col[f"{seg}_total_s"])
                sd["win"] = compare(sa["win"], col[f"{seg}_win"])
                sd["hold"] = compare(sa["hold"], col[f"{seg}_hold"])
                sd["total_r_per_year"] = compare(
                    sa["total_r_per_year"], col[f"{seg}_total_r"] / years[seg]
                )
                sd["total_s_per_year"] = compare(
                    sa["total_s_per_year"], col[f"{seg}_total_s"] / years[seg]
                )
                sd["fill_le_stop"] = gap_split(am, col, seg, sd["exp_r"]["alpha"])
                sd["placebo_sd_exp_r"] = float(col[f"{seg}_exp_r"].std(ddof=1))
                nd["segments"][seg] = sd
            nd["by_year_total_r"] = {
                str(y): compare(v["actual_by_year"][str(y)]["total_r"], col[f"y{y}_total_r"])
                for y in YEARS
            }
            nd["seconds_per_run_mean"] = float(col["seconds"].mean())
            v["nulls"][null] = nd
        if v["nulls"].get("gate", {}).get("K"):
            primary_p[key] = v["nulls"]["gate"]["segments"]["oos"]["exp_r"]["p"]
            primary_p_stable[key] = v["nulls"]["gate"]["segments"]["oos"]["exp_s"]["p"]
        summary["versions"][key] = v

    hp = holm(primary_p) if len(primary_p) == len(VERSIONS) else {}
    hps = holm(primary_p_stable) if len(primary_p_stable) == len(VERSIONS) else {}
    for key, v in summary["versions"].items():
        v["holm_p_gate_oos_engine_r"] = hp.get(key)
        v["holm_p_gate_oos_stable_r"] = hps.get(key)
        v["reading"] = reading(v)
    # descriptive: how the engine booked the real entries filled at or below the stop
    booked = np.array(
        [x for v in summary["versions"].values() for x in v["actual_fill_le_stop_pnl_r"]],
        dtype=np.float64,
    )
    summary["actual_fill_le_stop_all_versions"] = {
        "n": len(booked),
        "n_booked_as_gain": int((booked > 0).sum()),
        "median_r": float(np.median(booked)) if len(booked) else float("nan"),
        "min_r": float(booked.min()) if len(booked) else float("nan"),
    }
    return summary


def reading(v: dict[str, Any]) -> dict[str, Any]:
    """The pre-registered reading, applied mechanically (engine R is primary).

    P-gate: p < 0.05 on BOTH IS and OOS, the OOS leg after the Holm adjustment
    across the four versions. P-trend: raw p < 0.05 on both IS and OOS."""
    out: dict[str, Any] = {}
    g = v["nulls"].get("gate", {})
    t = v["nulls"].get("trend", {})
    if not g.get("K") or not t.get("K") or v.get("holm_p_gate_oos_engine_r") is None:
        return {"available": False}
    for unit, holm_key in (
        ("exp_r", "holm_p_gate_oos_engine_r"),
        ("exp_s", "holm_p_gate_oos_stable_r"),
    ):
        g_is, g_oos = g["segments"]["is"][unit], g["segments"]["oos"][unit]
        t_is, t_oos = t["segments"]["is"][unit], t["segments"]["oos"][unit]
        gate_pass = g_is["p"] < 0.05 and v[holm_key] < 0.05
        gate_pass_raw = g_is["p"] < 0.05 and g_oos["p"] < 0.05
        trend_pass = t_is["p"] < 0.05 and t_oos["p"] < 0.05
        out[unit] = {
            "gate_p_is": g_is["p"],
            "gate_p_oos_raw": g_oos["p"],
            "gate_p_oos_holm": v[holm_key],
            "beats_gate_both": gate_pass,
            "beats_gate_both_raw_p": gate_pass_raw,
            "trend_p_is": t_is["p"],
            "trend_p_oos": t_oos["p"],
            "beats_trend_both": trend_pass,
        }
    # The quoted words are the pre-registration's; "gated exposure" there stands for
    # the P-gate placebo as pre-registered (see the results file, Deviations and Limits).
    e = out["exp_r"]
    not_dist = NOT_DISTINGUISHABLE
    if e["beats_gate_both"] and e["beats_trend_both"]:
        text = (
            "Beats both placebos at p < 0.05 on both IS and OOS. Pre-registered reading: "
            '"the trigger adds value beyond gated exposure" and "beyond a simple trend state".'
        )
    elif e["beats_gate_both"]:
        text = (
            "Beats the P-gate placebo at p < 0.05 on both IS and OOS, not the P-trend placebo. "
            'Pre-registered reading: "the trigger adds value beyond gated exposure"; against '
            f"the trend state its R is {not_dist}."
        )
    else:
        text = (
            "Does not beat the P-gate placebo at p < 0.05 on both IS and OOS. Pre-registered "
            f"reading: its R is {not_dist}."
        )
        if e["beats_trend_both"]:
            text += " It does clear P-trend on both segments, which does not change the reading."
    text += (
        f" P-gate p: IS {e['gate_p_is']:.3f}, OOS {e['gate_p_oos_raw']:.3f} raw / "
        f"{e['gate_p_oos_holm']:.3f} Holm. P-trend p: IS {e['trend_p_is']:.3f}, OOS "
        f"{e['trend_p_oos']:.3f}."
    )
    out["available"] = True
    out["text"] = text
    return out


# --------------------------------------------------------------------------- #
# results markdown
# --------------------------------------------------------------------------- #
def _r(x: float, nd: int = 3) -> str:
    return "n/a" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x:+.{nd}f}"


def _band(c: dict[str, float], nd: int = 3, signed: bool = True) -> str:
    f = (lambda x: f"{x:+.{nd}f}") if signed else (lambda x: f"{x:.{nd}f}")
    return f"{f(c['placebo_mean'])} [{f(c['placebo_p2_5'])}, {f(c['placebo_p97_5'])}]"


def _p(p: float | None) -> str:
    return "n/a" if p is None else f"{p:.3f}"


def _names(keys: list[str]) -> str:
    names = list(keys)
    if not names:
        return "none"
    if len(names) == 1:
        return names[0]
    return ", ".join(names[:-1]) + " and " + names[-1]


def posthoc_rows(vs: dict[str, Any], keys: list[str], posthoc: dict[str, Any]) -> list[dict]:
    """The post hoc "always in when the gate allows" figures next to the real rule and
    the P-gate placebo mean (IS and OOS, engine R). Not pre-registered; no reading."""
    rows = []
    for k in keys:
        for seg in ("is", "oos"):
            g = posthoc[k]["segments"][seg]
            real = vs[k]["actual"][seg]["exp_r"]
            plc = vs[k]["nulls"]["gate"]["segments"][seg]["exp_r"]["placebo_mean"]
            ai = g["exp_r"]
            rows.append(
                {
                    "key": k,
                    "seg": seg,
                    "n": g["n"],
                    "always_in": ai,
                    "real": real,
                    "placebo": plc,
                    "placebo_over_always_in": plc / ai if ai > 0 else float("nan"),
                    "always_in_share_of_real": ai / real if ai > 0 and real > 0 else float("nan"),
                    "real_minus_always_in": real - ai,
                    "real_minus_always_in_in_week_se": (real - ai)
                    / vs[k]["clustering"][seg]["se_week_clustered"],
                }
            )
    return rows


def lead_paragraphs(
    vs: dict[str, Any], keys: list[str], posthoc: dict[str, Any] | None
) -> list[str]:
    """The answer in three sentences, written from the numbers (engine R, P-gate),
    then one short paragraph on what the placebo's symbol-year matching means."""
    seg = {k: vs[k]["nulls"]["gate"]["segments"] for k in keys}
    gate_ok = [k for k in keys if vs[k]["reading"]["exp_r"]["beats_gate_both"]]
    gate_no = [k for k in keys if k not in gate_ok]
    trend_ok = [k for k in gate_ok if vs[k]["reading"]["exp_r"]["beats_trend_both"]]
    if not gate_ok:
        s1 = (
            "None of the four approved versions beats the pre-registered placebo (P-gate) at "
            "p < 0.05 on both IS and OOS, so the pre-registered reading for each is that its R "
            f"is {NOT_DISTINGUISHABLE}."
        )
    else:
        s1 = (
            f"{_names(gate_ok)} beat{'s' if len(gate_ok) == 1 else ''} the pre-registered "
            "placebo (P-gate) at p < 0.05 on both IS and OOS (OOS Holm-adjusted across the four "
            "versions)"
        )
        if gate_no:
            s1 += f"; {_names(gate_no)} do{'es' if len(gate_no) == 1 else ''} not"
        if trend_ok:
            s1 += (
                f", and {_names(trend_ok)} also beat{'s' if len(trend_ok) == 1 else ''} the "
                "placebo restricted to close > SMA50 (P-trend)"
            )
        s1 += "."

    pos = [k for k in keys if seg[k]["oos"]["exp_r"]["alpha"] > 0]
    neg = [k for k in keys if k not in pos]

    def _alpha(k: str, with_holm: bool) -> str:
        c = seg[k]["oos"]["exp_r"]
        tail = f"{c['alpha']:+.3f}R, p {c['p']:.3f}"
        if with_holm:
            tail += f", Holm {vs[k]['holm_p_gate_oos_engine_r']:.3f}"
        return f"{k} ({tail})"

    def _join(items: list[str]) -> str:
        return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]

    parts = []
    if pos:
        parts.append("positive for " + _join([_alpha(k, True) for k in pos]))
    if neg:
        parts.append("negative for " + _join([_alpha(k, False) for k in neg]))
    s2 = "Against that placebo, OOS timing alpha is " + ", and ".join(parts)

    is_neg = [k for k in keys if seg[k]["is"]["exp_r"]["alpha"] < 0]
    is_p = [seg[k]["is"]["exp_r"]["p"] for k in is_neg]
    if len(is_neg) == len(keys):
        s2 += (
            "; on IS every version earned less per trade than the placebo "
            f"(p {min(is_p):.3f} to {max(is_p):.3f})."
        )
    elif is_neg:
        s2 += f"; on IS {_names(is_neg)} earned less per trade than the placebo."
    else:
        s2 += "; on IS every version earned more per trade than the placebo."

    s3 = (
        "The placebo is not plain random entry: for each symbol and calendar year it draws as "
        "many random gate-allowed dates as the rule had trades there, with the same stop, "
        "target and time stop, so the comparison tests whether a trigger picked better days "
        "than chance inside the symbol-years it traded and says nothing about whether a rule "
        "earns more than plain gated exposure."
    )

    if posthoc:
        ph = [r for r in posthoc_rows(vs, keys, posthoc) if r["seg"] == "oos"]
        ai = [r["always_in"] for r in ph]
        ratios = [r["placebo_over_always_in"] for r in ph]
        p2 = (
            "Being told the symbol-years favours the placebo. A post hoc check that is not "
            'pre-registered and decides nothing (under "Deviations and clarifications") puts a '
            "rough size on it: a signal on every gate-allowed bar, with the same exits through the "
            f"same engine, earned {min(ai):+.3f}R to {max(ai):+.3f}R per trade OOS"
        )
        if all(math.isfinite(x) for x in ratios):
            p2 += (
                f", so the placebo's OOS expectancy is {min(ratios):.1f} to {max(ratios):.1f} "
                "times that of plain gated exposure."
            )
        else:
            p2 += "."
    else:
        p2 = (
            "Being told the symbol-years can favour the placebo, by an amount this study does "
            "not measure."
        )
    if gate_no:
        p2 += (
            ' The pre-registration also said a "no" would make "a looser trigger with the same '
            'exits" a legitimate candidate to pre-register next; this study does not support '
            "that step, because a looser trigger would not know which symbol-years to trade "
            "and the placebo does."
        )
    return [" ".join([s1, s2, s3]), p2]


def render(summary: dict[str, Any]) -> str:
    vs = summary["versions"]
    meta = summary["meta"]
    keys = [v[0] for v in VERSIONS]
    seg_name = {"is": "IS", "oos": "OOS", "all": "All"}
    null_name = {"gate": "P-gate", "trend": "P-trend"}
    ks = {(k, n): vs[k]["nulls"].get(n, {}).get("K", 0) for k in keys for n in NULLS}
    k_min, k_max = min(ks.values()), max(ks.values())
    complete = k_min == meta["k_target"]

    L: list[str] = []
    L.append("# Results — R3-P: do the entry signals beat random entries with the same exits?")
    L.append("")

    # ---- lead -----------------------------------------------------------
    ready = all(vs[k]["reading"].get("available") for k in keys)
    posthoc = (summary.get("posthoc") or {}).get("gated_exposure") if ready else None
    if ready:
        for para in lead_paragraphs(vs, keys, posthoc):
            L.append(para)
            L.append("")
    else:
        L.append("Placebo runs are incomplete; no reading is available yet.")
        L.append("")
    L.append(
        "Pre-registration: `docs/research/PREREGISTRATION_r3_placebo_timing_2026-11-10.md` "
        "(commit 9bc9d24). Script: `scripts/r3/placebo_timing.py`. Development window "
        f"{meta['window'][0]}..{meta['window'][1]}, daily `massive` bars from the read-only "
        f"scratch copy of 2026-11-10. K = {k_min if k_min == k_max else f'{k_min} to {k_max}'} "
        f"placebo runs per version and null, seeds {BASE_SEED} + run index. No sealed data, no "
        "database write, no change to any frozen study or approved version."
    )
    L.append("")
    L.append(
        "The two placebos. **P-gate** (primary): for every symbol and calendar year, as many "
        "random signal dates as the real rule had trades in that symbol-year, drawn uniformly "
        "from that symbol-year's bars on which the version's own regime gate allows an entry; "
        "stop, target and time stop from ATR14 at the drawn bar with the version's own "
        "multiples; one position per symbol. **P-trend** (secondary): the same, drawn only from "
        "bars that also have close > SMA50. Both are told how many trades the rule had in each "
        'symbol-year. "Placebo" below always means these, never plain random entry.'
    )
    L.append("")
    if not complete:
        L.append(
            f"**K achieved is below the pre-registered {meta['k_target']} in at least one cell** "
            f"(minimum {k_min}, maximum {k_max}; per-cell K is in every table). Runs use seeds "
            f"{BASE_SEED} + run index from 0, so the missing runs can be added later without "
            "re-running the finished ones."
        )
        L.append("")

    # ---- primary --------------------------------------------------------
    L.append("## Primary comparison — P-gate, OOS, engine R")
    L.append("")
    L.append(
        "| Version (snapshot) | OOS trades | Actual exp. R | Placebo mean [2.5%, 97.5%] | "
        "Timing alpha | p (one-sided) | Holm p | K |"
    )
    L.append("|---|---:|---:|---:|---:|---:|---:|---:|")
    for k in keys:
        v = vs[k]
        g = v["nulls"].get("gate", {})
        if not g.get("K"):
            L.append(
                f"| {k} ({v['snapshot']}) | {v['actual']['oos']['n']:,} | "
                f"{_r(v['actual']['oos']['exp_r'])} | n/a | n/a | n/a | n/a | 0 |"
            )
            continue
        c = g["segments"]["oos"]["exp_r"]
        L.append(
            f"| {k} ({v['snapshot']}) | {v['actual']['oos']['n']:,} | {_r(c['actual'])} | "
            f"{_band(c)} | {_r(c['alpha'])} | {_p(c['p'])} | "
            f"{_p(v['holm_p_gate_oos_engine_r'])} | {g['K']} |"
        )
    L.append("")
    L.append(
        "Timing alpha = actual expectancy − placebo mean. p = (number of placebo runs with "
        "expectancy ≥ actual + 1) / (K + 1); with K = 200 the smallest possible p is 0.005. "
        "OOS is the runner's definition: each symbol's last 40% of bars by entry date, from "
        f"{meta['full_history_is_oos_boundary']} for full-history symbols. No rule parameter is "
        "fitted on IS, so IS and OOS are simply the earlier and the later period."
    )
    L.append("")
    L.append("The same comparison in stable R, `(exit − entry) / (close_t − stop_t)`:")
    L.append("")
    L.append(
        "| Version | Actual exp. stable R | Placebo mean [2.5%, 97.5%] | Timing alpha | "
        "p (one-sided) | Holm p |"
    )
    L.append("|---|---:|---:|---:|---:|---:|")
    for k in keys:
        v = vs[k]
        g = v["nulls"].get("gate", {})
        if not g.get("K"):
            continue
        c = g["segments"]["oos"]["exp_s"]
        L.append(
            f"| {k} | {_r(c['actual'])} | {_band(c)} | {_r(c['alpha'])} | {_p(c['p'])} | "
            f"{_p(v['holm_p_gate_oos_stable_r'])} |"
        )
    L.append("")

    # ---- reading --------------------------------------------------------
    L.append("## Pre-registered reading, per version")
    L.append("")
    L.append(
        "Rule fixed in advance: timing alpha with p < 0.05 against P-gate on both IS and OOS "
        "means the trigger adds value beyond gated exposure; against P-trend as well, beyond a "
        "simple trend state; otherwise the version's R is not distinguishable from gated (or "
        "trend-state) exposure with its exit geometry on this universe. Engine R decides; the "
        "P-gate OOS leg uses the Holm-adjusted p. The rule is applied as written. Its words "
        '"gated exposure" stand for the P-gate placebo as pre-registered, which draws inside '
        "the symbol-years the rule traded and is not plain gated exposure (Limits)."
    )
    L.append("")
    L.append(
        "| Version | P-gate p IS | P-gate p OOS (raw / Holm) | Beats P-gate on both | "
        "P-trend p IS | P-trend p OOS | Beats P-trend on both | Same reading in stable R |"
    )
    L.append("|---|---:|---:|:---:|---:|---:|:---:|:---:|")
    for k in keys:
        rd = vs[k]["reading"]
        if not rd.get("available"):
            L.append(f"| {k} | n/a | n/a | n/a | n/a | n/a | n/a | n/a |")
            continue
        e, s = rd["exp_r"], rd["exp_s"]
        same = (
            e["beats_gate_both"] == s["beats_gate_both"]
            and e["beats_trend_both"] == s["beats_trend_both"]
        )
        yes_no = {True: "yes", False: "no"}
        stable_cell = (
            "yes"
            if same
            else f"no (gate {yes_no[s['beats_gate_both']]}, trend {yes_no[s['beats_trend_both']]})"
        )
        L.append(
            f"| {k} | {_p(e['gate_p_is'])} | {_p(e['gate_p_oos_raw'])} / "
            f"{_p(e['gate_p_oos_holm'])} | {yes_no[e['beats_gate_both']]} | "
            f"{_p(e['trend_p_is'])} | {_p(e['trend_p_oos'])} | "
            f"{yes_no[e['beats_trend_both']]} | {stable_cell} |"
        )
    L.append("")
    for k in keys:
        rd = vs[k]["reading"]
        if rd.get("available"):
            note = ""
            if rd["exp_r"]["beats_gate_both"] != rd["exp_r"]["beats_gate_both_raw_p"]:
                note = (
                    " (With the raw OOS p instead of the Holm-adjusted one the P-gate answer "
                    "would flip.)"
                )
            L.append(f"- **{k}** — {rd['text']}{note}")
    L.append("")
    L.append(
        'A "no" does not make a rule unprofitable, and it does not say the rule earns no more '
        "than plain gated exposure. It says the rule did not earn more, on both segments, than "
        "random gate-allowed dates inside the same symbol-years with the same number of trades "
        'and the same exits. The pre-registration attached two consequences to a "no": '
        'refinement effort "belongs in exposure, capacity and costs", and "a looser trigger '
        'with the same exits is a legitimate candidate to pre-register next". The second does '
        "not follow from this placebo: a looser trigger would not know in advance which "
        "symbol-years to trade, and the placebo does (Limits)."
    )
    L.append("")

    # ---- per version ----------------------------------------------------
    L.append("## Every pre-registered cell")
    L.append("")
    L.append(
        "Placebo columns are the mean over K runs with the 2.5th and 97.5th percentiles in "
        "brackets. Total R is the sum over all trades of the segment. p is one-sided (share of "
        "placebo runs at or above the actual value), so p = 1.000 means the real rule came in "
        "below every placebo run. Limits explains why these p-values overstate the evidence in "
        "both directions (the placebo dates do not bunch in time as the real signals do)."
    )
    L.append("")
    for k in keys:
        v = vs[k]
        gm = v["geometry"]
        L.append(
            f"### {k} — snapshot {v['snapshot']} ({v['n_symbols']} symbols); stop "
            f"{gm['stop_atr']:g} × ATR{gm['atr_window']}, target {gm['target_atr']:g} × "
            f"ATR{gm['atr_window']}, time stop {gm['time_stop_bars']} bars"
        )
        L.append("")
        L.append("Engine R:")
        L.append("")
        L.append(
            "| Null | Segment | Actual trades | Placebo trades (mean) | Actual exp. R | "
            "Placebo exp. R | Timing alpha | p | Actual total R | Placebo total R | K |"
        )
        L.append("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
        for null in NULLS:
            nd = v["nulls"].get(null, {})
            for seg in SEGS:
                a = v["actual"][seg]
                if not nd.get("K"):
                    L.append(
                        f"| {null_name[null]} | {seg_name[seg]} | {a['n']} | n/a | "
                        f"{_r(a['exp_r'])} | n/a | n/a | n/a | {a['total_r']:+.1f} | n/a | 0 |"
                    )
                    continue
                sd = nd["segments"][seg]
                c, tot = sd["exp_r"], sd["total_r"]
                L.append(
                    f"| {null_name[null]} | {seg_name[seg]} | {a['n']:,} | "
                    f"{sd['placebo_n_mean']:,.1f} | {_r(c['actual'])} | {_band(c)} | "
                    f"{_r(c['alpha'])} | {_p(c['p'])} | {tot['actual']:+.1f} | "
                    f"{_band(tot, 1)} | {nd['K']} |"
                )
        L.append("")
        L.append("Stable R:")
        L.append("")
        L.append(
            "| Null | Segment | Actual exp. stable R | Placebo exp. stable R | Timing alpha | p | "
            "Actual total stable R | Placebo total stable R |"
        )
        L.append("|---|---|---:|---:|---:|---:|---:|---:|")
        for null in NULLS:
            nd = v["nulls"].get(null, {})
            if not nd.get("K"):
                continue
            for seg in SEGS:
                sd = nd["segments"][seg]
                c, tot = sd["exp_s"], sd["total_s"]
                L.append(
                    f"| {null_name[null]} | {seg_name[seg]} | {_r(c['actual'])} | {_band(c)} | "
                    f"{_r(c['alpha'])} | {_p(c['p'])} | {tot['actual']:+.1f} | {_band(tot, 1)} |"
                )
        L.append("")
        L.append("Win rate, mean hold (bars) and total R per year (engine R):")
        L.append("")
        L.append(
            "| Null | Segment | Win rate actual | Win rate placebo | p | Hold actual | "
            "Hold placebo | p | Total R/yr actual | Total R/yr placebo | p |"
        )
        L.append("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
        for null in NULLS:
            nd = v["nulls"].get(null, {})
            if not nd.get("K"):
                continue
            for seg in SEGS:
                sd = nd["segments"][seg]
                w, h, ty = sd["win"], sd["hold"], sd["total_r_per_year"]
                L.append(
                    f"| {null_name[null]} | {seg_name[seg]} | {w['actual'] * 100:.1f}% | "
                    f"{w['placebo_mean'] * 100:.1f}% [{w['placebo_p2_5'] * 100:.1f}, "
                    f"{w['placebo_p97_5'] * 100:.1f}] | {_p(w['p'])} | {h['actual']:.1f} | "
                    f"{_band(h, 1, signed=False)} | {_p(h['p'])} | {ty['actual']:+.1f} | "
                    f"{_band(ty, 1)} | {_p(ty['p'])} |"
                )
        L.append("")
        g_nd, t_nd = v["nulls"].get("gate", {}), v["nulls"].get("trend", {})
        if g_nd.get("K") and t_nd.get("K"):
            L.append("Total R by calendar year of the signal (engine R):")
            L.append("")
            L.append(
                "| Year | Actual trades | Actual total R | P-gate placebo total R | p | "
                "P-trend placebo total R | p |"
            )
            L.append("|---|---:|---:|---:|---:|---:|---:|")
            for y in YEARS:
                ay = v["actual_by_year"][str(y)]
                cg, ct = g_nd["by_year_total_r"][str(y)], t_nd["by_year_total_r"][str(y)]
                if ay["n"] == 0:
                    L.append(f"| {y} | 0 | +0.0 | no draws | n/a | no draws | n/a |")
                    continue
                L.append(
                    f"| {y} | {ay['n']:,} | {ay['total_r']:+.1f} | {_band(cg, 1)} | "
                    f"{_p(cg['p'])} | {_band(ct, 1)} | {_p(ct['p'])} |"
                )
            L.append("")

    # ---- shortfall ------------------------------------------------------
    L.append("## Shortfall from dropped draws")
    L.append("")
    L.append(
        "Target = the real rule's trade count (draws per run). A draw that still fell inside "
        f"an open placebo trade after {MAX_REDRAWS} redraws was dropped; under P-trend a "
        "symbol-year with no bar above SMA50 on a gate-allowed day cannot be drawn at all."
    )
    L.append("")
    L.append(
        "| Version | Null | K | Target per run | Placed (mean / min) | Dropped after "
        f"{MAX_REDRAWS} redraws (mean / max) | No eligible bar (mean) | Shortfall % "
        "(mean / max) | Redraws per run (mean) |"
    )
    L.append("|---|---|---:|---:|---:|---:|---:|---:|---:|")
    for k in keys:
        for null in NULLS:
            nd = vs[k]["nulls"].get(null, {})
            if not nd.get("K"):
                L.append(f"| {k} | {null_name[null]} | 0 | n/a | n/a | n/a | n/a | n/a | n/a |")
                continue
            sf = nd["shortfall"]
            L.append(
                f"| {k} | {null_name[null]} | {nd['K']} | {sf['target_per_run']:,.0f} | "
                f"{sf['placed_mean']:,.1f} / {sf['placed_min']:,.0f} | "
                f"{sf['dropped_after_redraws_mean']:.2f} / {sf['dropped_after_redraws_max']:.0f} | "
                f"{sf['no_eligible_bar_mean']:.2f} | {sf['shortfall_pct_mean']:.2f}% / "
                f"{sf['shortfall_pct_max']:.2f}% | {sf['redraws_mean']:,.0f} |"
            )
    L.append("")
    L.append(
        "Eligible bars (all symbols, whole window) and the share of the real rule's signal bars "
        "that are themselves P-trend-eligible:"
    )
    L.append("")
    L.append(
        "| Version | Bars loaded | P-gate eligible | P-trend eligible | Real signal bars "
        "with close > SMA50 |"
    )
    L.append("|---|---:|---:|---:|---:|")
    for k in keys:
        v = vs[k]
        L.append(
            f"| {k} | {v['total_bars']:,} | {v['eligible_bars']['gate']:,} | "
            f"{v['eligible_bars']['trend']:,} | {v['actual_trend_ok_share'] * 100:.1f}% |"
        )
    L.append("")

    # ---- identity -------------------------------------------------------
    L.append("## Identity and construction checks")
    L.append("")
    L.append(
        "The identity check, the replay of the real dates and the redraw-rule comparison run "
        "before any placebo run and stop the study on a mismatch; the whole-run comparison is "
        "made after the runs."
    )
    L.append("")
    L.append(
        "| Version | Snapshot | Recorded OOS (trades / exp. R) | Reproduced OOS (trades / exp. R) "
        "| Match | Placebo function on the real dates: trades reproduced | Stop/target/time-stop "
        "mismatches |"
    )
    L.append("|---|---:|---:|---:|:---:|---:|---:|")
    for k in keys:
        v = vs[k]
        i, rp = v["identity"], v["replay_check"]
        L.append(
            f"| {k} | {v['snapshot']} | {i['recorded_oos_n']:,} / "
            f"{i['recorded_oos_expectancy_r']:+.4f} | {i['oos_n']:,} / "
            f"{i['oos_expectancy_r']:+.4f} | {'yes' if i['match'] else 'NO'} | "
            f"{rp['replay_trades'] - rp['trade_mismatches']:,} of {rp['actual_trades']:,} | "
            f"{rp['geometry_mismatches']} |"
        )
    L.append("")
    L.append(
        "The last two columns feed the placebo signal function the real rule's own signal "
        "dates: it must return the same stop, target and time stop, and the library engine "
        "must then produce the same trades (dates, fills and R, compared exactly). One-symbol "
        "examples:"
    )
    L.append("")
    L.append(
        "| Version | Symbol | Signals compared | Equal | First signal date | Real stop / target "
        "| Placebo stop / target |"
    )
    L.append("|---|---|---:|---:|---|---:|---:|")
    for k in keys:
        ex = vs[k]["geometry_example"]
        if not ex:
            continue
        s0 = ex["samples"][0]
        L.append(
            f"| {k} | {ex['symbol']} | {ex['signals_checked']} | {ex['equal']} | "
            f"{s0['signal_date']} | {s0['real_stop']:.4f} / {s0['real_target']:.4f} | "
            f"{s0['placebo_stop']:.4f} / {s0['placebo_target']:.4f} |"
        )
    L.append("")
    L.append(
        "Window: the bars loaded run from "
        f"{min(vs[k]['bars_loaded']['first'] for k in keys)} to "
        f"{max(vs[k]['bars_loaded']['last'] for k in keys)}. Bars are requested up to "
        f"{END.isoformat()} only, and the loader stops if a later bar ever appears."
    )
    L.append("")
    sc_cases = sum(vs[k]["planner_selfcheck"]["cases"] for k in keys)
    sc_equal = sum(vs[k]["planner_selfcheck"]["equal"] for k in keys)
    sc_redraws = sum(vs[k]["planner_selfcheck"]["redraws"] for k in keys)
    L.append(
        "Redraw rule: the date planner was compared with a slow twin that finds blocked draws "
        "by running the library engine itself and seeing which dates it never evaluated, on the "
        f"five busiest symbols of each version under both nulls. {sc_equal} of {sc_cases} cases "
        f"gave identical dates, drops and redraw counts ({sc_redraws:,} redraws exercised)."
    )
    L.append("")
    tw = summary.get("twin_check") or {}
    if tw.get("cases"):
        L.append(
            f"Whole runs: runs {' and '.join(str(r) for r in tw['runs'])} of every version and "
            "null were redone from the seed with that slow twin as the planner, so the library "
            f"engine alone decided which draws were blocked. {tw['identical']} of {tw['cases']} "
            "reproduced the study's run-level rows exactly."
        )
        L.append("")
    L.append(
        "In every placebo run the planned entry and exit dates and the library engine's trades "
        "were compared symbol by symbol; a disagreement would have stopped the run. None "
        "occurred."
    )
    L.append("")

    # ---- expectations ---------------------------------------------------
    L.append("## Stated expectations against the outcome")
    L.append("")
    if ready:
        pos = [
            k
            for k in keys
            if vs[k]["nulls"]["gate"]["segments"]["oos"]["exp_r"]["placebo_p2_5"] > 0
            and vs[k]["nulls"]["gate"]["segments"]["is"]["exp_r"]["placebo_p2_5"] > 0
        ]
        L.append(
            '- "Placebo expectancy will be clearly positive on both universes": the P-gate '
            "2.5th percentile is above zero on both IS and OOS for "
            f"{_names(pos) if len(pos) < len(keys) else 'all four versions'}"
            f"{'' if len(pos) == len(keys) else ' only'}."
        )
        for k in keys:
            g = vs[k]["nulls"]["gate"]["segments"]
            L.append(
                f"- {k}: P-gate timing alpha {_r(g['is']['exp_r']['alpha'])}R IS "
                f"(p {_p(g['is']['exp_r']['p'])}), {_r(g['oos']['exp_r']['alpha'])}R OOS "
                f"(p {_p(g['oos']['exp_r']['p'])})."
            )
        L.append(
            "- Expected in advance: positive but small alpha for the two trend_continuation "
            "versions and high52, uncertain for relative_strength; a null for one or more "
            "versions was called a likely outcome."
        )
        exp_keys = [k for k in keys if not k.startswith("relative_strength")]
        held = [
            k
            for k in exp_keys
            if vs[k]["nulls"]["gate"]["segments"]["is"]["exp_r"]["alpha"] > 0
            and vs[k]["nulls"]["gate"]["segments"]["oos"]["exp_r"]["alpha"] > 0
        ]
        oos_only = [
            k
            for k in exp_keys
            if k not in held and vs[k]["nulls"]["gate"]["segments"]["oos"]["exp_r"]["alpha"] > 0
        ]
        neither = [k for k in exp_keys if k not in held and k not in oos_only]
        L.append(
            "- Outcome for the three versions with a stated sign: alpha positive on both IS and "
            f"OOS for {_names(held)}; positive OOS but negative IS for {_names(oos_only)}; "
            f"negative OOS for {_names(neither)}. The expectation of a positive alpha did not "
            "hold on IS for any of them."
            if not held
            else "- Outcome for the three versions with a stated sign: alpha positive on both "
            f"IS and OOS for {_names(held)}; positive OOS but negative IS for "
            f"{_names(oos_only)}; negative OOS for {_names(neither)}."
        )
    L.append("")

    # ---- deviations -----------------------------------------------------
    L.append("## Deviations and clarifications")
    L.append("")
    dev = [
        "No deviation from the pre-registered design. Items 2 to 10 are choices the "
        "pre-registration left open. The later items record what an adversarial review of the "
        "first write-up led to: wording, descriptive splits of the same runs, a re-run from the "
        "same seeds and, where shown, one post hoc check. None changes a pre-registered number "
        "or a reading. Nothing in the placebo construction changed after the first placebo "
        "run: a smoke test of runs 0–5 made before the first full run matches that run's rows "
        "exactly. The calendar-year tables were added to the write-up after the runs; every "
        "run had recorded its per-year totals from the start.",
        "**Symbol-year of a trade.** A real trade is counted in the calendar year of its "
        "signal bar (the session before the fill), because the placebo draws signal dates.",
        "**Eligible bars.** P-gate: bars where the version's own regime gate allows an entry "
        "(`not risk_off` for trend_continuation and high52_breakout; trend BULL for "
        "relative_strength), limited to bars the engine can act on (bar index ≥ 30, the "
        "runner's warm-up; not the last bar) with ATR14 defined. The rule's own indicator "
        "warm-up (SMA50/SMA100, 252-bar high) is not imposed, as the pre-registration says "
        '"that symbol-year\'s bars on which the regime gate allows an entry". P-trend adds '
        "close > SMA50 (library `sma`).",
        "**Redraw rule.** Each draw is an independent uniform draw from its symbol-year's "
        "eligible bars. Draws are played in date order as the engine does: a draw on a bar the "
        "engine does not evaluate because an earlier placebo trade is open — from that trade's "
        "signal bar through its exit bar, which includes a second draw on the same bar — is "
        f"redrawn uniformly from the same symbol-year, up to {MAX_REDRAWS} times, then dropped. "
        "A new earlier trade can displace a later one, which is then the one redrawn. No draw "
        "is ever rejected because of its own outcome.",
        "**No look-ahead in the signal.** Dates are drawn in advance; the signal function "
        "receives the engine's `series.head(t)` and builds stop, target and time stop from "
        "ATR14 at the drawn bar. The date planner uses the library's exit resolution only to "
        "know when an earlier placebo trade is still open; every reported trade comes from "
        "`run_backtest`.",
        "**Seeds.** Run r (0-based) of every version and null uses "
        f"`numpy.random.default_rng({BASE_SEED} + r)`; symbols are processed alphabetically, "
        "years ascending.",
        "**Stable R** is computed inside this script as engine R × |entry fill − stop| / "
        "(close_t − stop_t), which equals (exit − entry) / (close_t − stop_t) on unrounded "
        "fills. The R3-E script is not used.",
        "**Holm.** Applied to the four P-gate OOS expectancy p-values (engine R; shown for "
        "stable R too). The per-version reading uses the Holm-adjusted p for the P-gate OOS "
        "leg and raw p elsewhere.",
        "**Total R per year** is shown both ways the phrase can be read: the segment's total R "
        f"divided by its length in years (IS {meta['segment_years']['is']:.2f}, OOS "
        f"{meta['segment_years']['oos']:.2f}, whole window {meta['segment_years']['all']:.2f}; "
        f"full-history IS/OOS boundary {meta['full_history_is_oos_boundary']}), and total R by "
        "calendar year of the signal.",
        "**p for win rate, hold and total R per year** is the same one-sided share of placebo "
        "runs at or above the actual value.",
    ]
    dev.append(
        "**Wording of the reading.** The pre-registered rule is applied as written and its "
        "yes/no outcome is unchanged. The pre-registration's sentence calls the P-gate placebo "
        '"gated exposure" and names a looser trigger as a candidate to pre-register next. '
        "Because the P-gate placebo, as pre-registered, also matches the rule's realised trade "
        "count in every symbol-year, this file quotes those words as the pre-registration's and "
        "does not repeat them as findings."
    )
    dev.append(
        "**Descriptive additions, not pre-registered and used in no reading.** Two splits of "
        "the pre-registered runs and of the real trades are quoted under Limits: trades whose "
        "entry fill is at or below the stop (run-level columns `*_gap_n` and `*_gap_total_r`), "
        "and how the real signals bunch in time (signal dates, a week-clustered standard "
        "error). They add no run and change no pre-registered number."
    )
    prov = meta.get("provenance") or {}
    sha_note = f" (SHA-256 `{prov['script_sha256'][:12]}…`)" if prov.get("script_sha256") else ""
    rerun = (
        "**Runs redone after the review.** The first results file had been rebuilt by a script "
        "that was edited after the placebo runs had finished. Every run row now carries a "
        "fingerprint of the script, the library modules it calls, the bars and the real rule's "
        "trade counts, and rows with another fingerprint are refused; `--out` has no default. "
        "All runs of every cell were redone from the same seeds with the script as committed"
        f"{sha_note}."
    )
    cmp_ = summary.get("comparison") or []
    if cmp_:
        if all(c["rows_equal"] == c["rows"] and c["rows"] > 0 for c in cmp_):
            rerun += (
                " Every earlier run row was reproduced exactly on all the columns it shares "
                "with the new rows: "
                + "; ".join(
                    f"{c['rows_equal']:,} of {c['rows']:,} rows of {c['label']} "
                    f"({c['shared_columns']} columns)"
                    for c in cmp_
                )
                + "."
            )
        else:
            rerun += (
                " **The earlier run rows were NOT all reproduced:** "
                + "; ".join(
                    f"{c['rows_equal']:,} of {c['rows']:,} rows of {c['label']}" for c in cmp_
                )
                + "."
            )
    dev.append(rerun)
    ph_rows = posthoc_rows(vs, keys, posthoc) if posthoc else []
    if ph_rows:
        oos_r = [r for r in ph_rows if r["seg"] == "oos"]
        is_r = [r for r in ph_rows if r["seg"] == "is"]
        ratios_ok = all(math.isfinite(r["placebo_over_always_in"]) for r in ph_rows) and all(
            math.isfinite(r["always_in_share_of_real"]) for r in oos_r
        )
        ph = (
            "**Post hoc check — not pre-registered, asked for by the adversarial review, used "
            "in no reading.** How much does the P-gate placebo gain from being told the "
            "symbol-years? The placebo signal function was offered every bar instead of drawn "
            "bars, so it enters whenever the version's regime gate allows and the symbol is "
            'flat ("always in when the gate allows"): same ATR14 stop, target and time stop, '
            "same library engine, one position per symbol, no random number and no parameter. "
            "It differs from the placebo in a second way, trading back to back instead of on a "
            "matched number of random dates, so the ratios are a rough size and not a "
            "decomposition. The table below this list sets it beside the real rule and the "
            "P-gate placebo mean."
        )
        if ratios_ok:
            ph += (
                " OOS the placebo mean is "
                f"{min(r['placebo_over_always_in'] for r in oos_r):.1f} to "
                f"{max(r['placebo_over_always_in'] for r in oos_r):.1f} times the always-in "
                f"figure (IS: {min(r['placebo_over_always_in'] for r in is_r):.1f} to "
                f"{max(r['placebo_over_always_in'] for r in is_r):.1f} times), and the always-in "
                f"figure is {min(r['always_in_share_of_real'] for r in oos_r) * 100:.0f}% to "
                f"{max(r['always_in_share_of_real'] for r in oos_r) * 100:.0f}% of the real "
                "rule's OOS expectancy."
            )
        n_above_oos = sum(1 for r in oos_r if r["real_minus_always_in"] > 0)
        n_below_is = sum(1 for r in is_r if r["real_minus_always_in"] < 0)
        gaps = [abs(r["real_minus_always_in_in_week_se"]) for r in oos_r]
        ph += (
            f" The real rule is above the always-in figure OOS for {n_above_oos} of "
            f"{len(oos_r)} versions and below it IS for {n_below_is} of {len(is_r)}. This is one "
            "fixed path per version with no error band and no test: the OOS gaps between the "
            f"real rules and the always-in figure are {min(gaps):.1f} to {max(gaps):.1f} times "
            "the real rule's own week-clustered standard error (Limits), so it is not evidence "
            "that the triggers add value. It shows only that the P-gate placebo is not plain "
            "gated exposure."
        )
        dev.append(ph)
    if not complete:
        dev.append(
            f"**K.** The wall-time budget ended before K = {meta['k_target']} in every cell; "
            "achieved K per cell is shown in the tables. Only whole runs are counted."
        )
    for i, d in enumerate(dev, 1):
        L.append(f"{i}. {d}")
    L.append("")
    if ph_rows:
        L.append(
            "Post hoc check (not pre-registered, no reading): always in when the gate allows, "
            "engine R per trade, beside the pre-registered figures."
        )
        L.append("")
        L.append(
            "| Version | Segment | Real rule exp. R | P-gate placebo mean | Always in when the "
            "gate allows: exp. R (trades) | Placebo mean ÷ always-in | Real rule − always-in |"
        )
        L.append("|---|---|---:|---:|---:|---:|---:|")
        for r in ph_rows:
            ratio = r["placebo_over_always_in"]
            L.append(
                f"| {r['key']} | {seg_name[r['seg']]} | {_r(r['real'])} | {_r(r['placebo'])} | "
                f"{_r(r['always_in'])} ({r['n']:,}) | "
                f"{f'{ratio:.2f}' if math.isfinite(ratio) else 'n/a'} | "
                f"{_r(r['real_minus_always_in'])} |"
            )
        L.append("")

    # ---- limits ---------------------------------------------------------
    L.append("## Limits")
    L.append("")
    L.append(
        "- The placebo inherits the same survivorship and the same regime gate as the rule; it "
        "measures the trigger's value only, and only as a choice of days inside the "
        "symbol-years the rule traded (next point)."
    )
    if ph_rows and all(math.isfinite(r["placebo_over_always_in"]) for r in ph_rows):
        oos_ratio = [r["placebo_over_always_in"] for r in ph_rows if r["seg"] == "oos"]
        size = (
            "That favours the placebo. The pre-registered design does not measure by how much; "
            'the post hoc check under "Deviations and clarifications" gives a rough size: OOS '
            f"the placebo mean is {min(oos_ratio):.1f} to {max(oos_ratio):.1f} times what always "
            "being in when the gate allows earned."
        )
    else:
        size = "That can favour the placebo; this study does not measure by how much."
    L.append(
        "- Matching trade counts per symbol-year tells the placebo which symbol-years the rule "
        "ended up trading, and how often. Each rule fires after strength (price above its "
        "averages, 63-day outperformance, a new 52-week high), so a symbol-year in which it "
        "fired often is likely one that turned out strong, and a random date in the same "
        f"symbol-year can fall before the rise the rule waited for. {size} A negative timing "
        "alpha therefore says the trigger did not pick better days than chance *inside the "
        "symbol-years it traded*; it does not test the trigger's choice of symbol-years, and it "
        "does not mean the rule earns less than plain gated exposure."
    )
    if ready:
        # -- time-clustering and K resolution (descriptive; adversarial review) --
        cl = {(k, s): vs[k]["clustering"][s] for k in keys for s in ("is", "oos")}
        gsd = {
            (k, s): vs[k]["nulls"]["gate"]["segments"][s]["placebo_sd_exp_r"]
            for k in keys
            for s in ("is", "oos")
        }
        ratio = [cl[c]["se_week_clustered"] / gsd[c] for c in cl]
        busiest = max(keys, key=lambda k: cl[(k, "is")]["n"])
        in_se = {
            c: vs[c[0]]["nulls"]["gate"]["segments"][c[1]]["exp_r"]["alpha"]
            / cl[c]["se_week_clustered"]
            for c in cl
        }
        in_sd = {
            c: vs[c[0]]["nulls"]["gate"]["segments"][c[1]]["exp_r"]["alpha"] / gsd[c] for c in cl
        }
        below_all = [
            k
            for k in keys
            if vs[k]["nulls"]["gate"]["segments"]["is"]["exp_r"]["n_placebo_ge_actual"]
            == vs[k]["nulls"]["gate"]["K"]
        ]
        text = (
            "- The p-values compare each rule with random dates, which are spread across the "
            "calendar, while the real rules' trades bunch on common market days: "
            f"{busiest}'s {cl[(busiest, 'is')]['n']:,} IS trades fall on "
            f"{cl[(busiest, 'is')]['signal_dates']:,} signal dates, and the ten busiest dates "
            f"hold {min(c['top10_dates_share'] for c in cl.values()) * 100:.0f}% to "
            f"{max(c['top10_dates_share'] for c in cl.values()) * 100:.0f}% of a segment's "
            "trades. A no-skill rule that bunched the same way would stray further from the "
            "placebo mean than the placebo runs do, in both directions. As a yardstick (not a "
            "test), the spread of the P-gate runs (SD "
            f"{min(gsd.values()):.3f}R to {max(gsd.values()):.3f}R) is {min(ratio):.1f} to "
            f"{max(ratio):.1f} times smaller than the standard error of the real rule's own "
            "expectancy when trades signalled in the same week count as one cluster "
            f"({min(c['se_week_clustered'] for c in cl.values()):.3f}R to "
            f"{max(c['se_week_clustered'] for c in cl.values()):.3f}R). So the p-values overstate "
            "the evidence both ways"
        )
        if below_all:
            text += (
                f": for the {len(below_all)} version{'s' if len(below_all) != 1 else ''} whose "
                "IS expectancy is below every placebo run (p 1.000), the IS timing alpha is "
                f"{max(in_sd[(k, 'is')] for k in below_all):+.1f} to "
                f"{min(in_sd[(k, 'is')] for k in below_all):+.1f} placebo SDs but "
                f"{max(in_se[(k, 'is')] for k in below_all):+.1f} to "
                f"{min(in_se[(k, 'is')] for k in below_all):+.1f} of those standard errors"
            )
        best = min(keys, key=lambda k: vs[k]["nulls"]["gate"]["segments"]["oos"]["exp_r"]["p"])
        bo = vs[best]["nulls"]["gate"]["segments"]["oos"]
        text += (
            f"; {best}'s OOS {bo['exp_r']['alpha']:+.3f}R is {in_sd[(best, 'oos')]:+.1f} placebo "
            f"SDs but {in_se[(best, 'oos')]:+.1f} standard errors. No reading changes. The first "
            "table after this list has every cell."
        )
        L.append(text)
        k_all = vs[best]["nulls"]["gate"]["K"]
        m = len(keys)
        passing = [j for j in range(k_all + 1) if m * (j + 1) / (k_all + 1) < 0.05]
        if passing:
            k_pass = max(passing)
            res = (
                f"the best of the {m} versions passes it only if at most {k_pass} of its "
                f"{k_all} placebo runs {'is' if k_pass == 1 else 'are'} at or above the rule "
                f"({m} × {k_pass + 1}/{k_all + 1} = {m * (k_pass + 1) / (k_all + 1):.3f}; "
                f"{m} × {k_pass + 2}/{k_all + 1} = {m * (k_pass + 2) / (k_all + 1):.3f})"
            )
        else:
            res = (
                f"no version can pass it (the smallest possible adjusted p is {m} × 1/"
                f"{k_all + 1} = {m / (k_all + 1):.3f})"
            )
        L.append(
            f"- With K = {k_all} the Holm-adjusted P-gate OOS leg has little resolution: {res}. "
            f"{best} has {bo['exp_r']['n_placebo_ge_actual']} of {k_all} runs at or above it in "
            f"engine R (Holm {vs[best]['holm_p_gate_oos_engine_r']:.3f}) and "
            f"{bo['exp_s']['n_placebo_ge_actual']} of {k_all} in stable R (Holm "
            f"{vs[best]['holm_p_gate_oos_stable_r']:.3f}), so that leg turns on a handful of "
            f"runs. Its IS leg (p {vs[best]['nulls']['gate']['segments']['is']['exp_r']['p']:.3f}) "
            "settles the reading either way."
        )
        # -- entry fills at or below the stop (descriptive; adversarial review) --
        gf = {
            (k, s): vs[k]["nulls"]["gate"]["segments"][s]["fill_le_stop"]
            for k in keys
            for s in ("is", "oos")
        }
        c1 = max(gf, key=lambda c: abs(gf[c]["alpha_from_these_fills"]))
        g1 = gf[c1]
        a1 = vs[c1[0]]["nulls"]["gate"]["segments"][c1[1]]["exp_r"]["alpha"]
        rest = [gf[c]["alpha_from_these_fills"] for c in gf if c != c1]
        more = sum(1 for g in gf.values() if g["actual_share"] > g["placebo_share_mean"])
        bk = summary["actual_fill_le_stop_all_versions"]
        L.append(
            "- Engine R books an entry that fills at or below its stop as closed on the entry "
            f"bar at the stop price. Of the {bk['n']:,} such real trades across the four "
            f"versions, {bk['n_booked_as_gain']:,} are booked as gains (median "
            f"{bk['median_r']:+.2f}R); the few whose fill is only just below the stop are "
            f"booked as losses, down to {bk['min_r']:+.1f}R. The R3-E study of this round "
            "takes no trade when the entry bar opens at or below the stop (its corrected "
            "baseline, pre-registered as a measurement correction). The real rules have such fills "
            f"more often than the placebo in {more} of the {len(gf)} P-gate IS and OOS "
            "cells, which moves timing alpha in engine R. The largest effect is in "
            f"{c1[0]} {seg_name[c1[1]]}: {g1['actual_n']:,} of "
            f"{vs[c1[0]]['actual'][c1[1]]['n']:,} real trades ({g1['actual_share'] * 100:.2f}%) "
            f"are such fills and add {g1['actual_contribution_to_exp_r']:+.4f}R to expectancy, "
            f"against {g1['placebo_share_mean'] * 100:.2f}% and "
            f"{g1['placebo_contribution_to_exp_r_mean']:+.4f}R in the placebo, so "
            f"{g1['alpha_from_these_fills']:+.4f}R of the {a1:+.4f}R timing alpha comes from "
            f"these fills and {g1['alpha_from_other_trades']:+.4f}R from all other trades "
            f"(counted by the raw open rather than the fill, as R3-E counts them, the same "
            f"segment has {vs[c1[0]]['actual_open_le_stop_n'][c1[1]]:,}). In "
            f"the other {len(rest)} cells they move timing alpha by {min(rest):+.4f}R to "
            f"{max(rest):+.4f}R (second table after this list). The stable-R tables, which "
            "divide by the risk planned at the signal, show part of the same effect. The engine "
            "was pre-registered as unchanged, so no pre-registered table is adjusted."
        )
        hk = "high52_breakout.medium_swing"
        hy = vs[hk]["nulls"]["gate"]["by_year_total_r"]["2017"]
        hs = vs[hk]["nulls"]["gate"]["segments"]["is"]["total_r"]
        L.append(
            "- P-gate draws from every gate-allowed bar of a symbol-year, including bars before "
            "a rule's own indicators could have fired (the 252-bar high cannot fire before "
            "October 2017). For high52_breakout the 2017 gap between actual and P-gate placebo "
            f"total R is {hy['actual'] - hy['placebo_mean']:+.1f}R, against "
            f"{hs['actual'] - hs['placebo_mean']:+.1f}R for the whole IS segment, so the IS "
            "result does not rest on that year."
        )
        worst = max(
            ((k, n) for k in keys for n in NULLS),
            key=lambda kn: vs[kn[0]]["nulls"][kn[1]]["shortfall"]["shortfall_pct_mean"],
        )
        wk = worst[0]
        L.append(
            "- A draw is dropped only after 21 consecutive draws landed inside open placebo "
            f"trades. The shortfall is largest for {wk} "
            f"({vs[wk]['nulls']['gate']['shortfall']['shortfall_pct_mean']:.2f}% of draws under "
            f"P-gate, {vs[wk]['nulls']['trend']['shortfall']['shortfall_pct_mean']:.2f}% under "
            "P-trend) and below 0.2% elsewhere. Twenty-one misses in a row need a symbol-year "
            "already crowded with open placebo trades, so the dropped draws thin out the "
            "busiest symbol-years."
            if all(
                vs[k]["nulls"][n]["shortfall"]["shortfall_pct_mean"] < 0.2
                for k in keys
                for n in NULLS
                if k != wk
            )
            else "- A draw is dropped only after 21 consecutive draws landed inside open "
            "placebo trades; the shortfall table shows how often that happened in each cell."
        )
    L.append(
        "- The calendar-year p-values are dozens of separate comparisons with no multiplicity "
        "adjustment; they are shown to locate the gaps in time, not as tests."
    )
    L.append("- It says nothing about a different universe or about the sealed year.")
    L.append("")
    if ready:
        L.append(
            "Time-clustering of the real signals against the spread of the P-gate runs "
            "(descriptive, not pre-registered, no reading; engine R). The clustered standard "
            "error treats trades signalled in the same ISO week as one cluster."
        )
        L.append("")
        L.append(
            "| Version | Segment | Real trades | Signal dates | Ten busiest dates | P-gate "
            "placebo SD | Real rule SE, week-clustered | Timing alpha | in placebo SDs | in "
            "clustered SEs |"
        )
        L.append("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|")
        for k in keys:
            for s in ("is", "oos"):
                c = cl[(k, s)]
                a = vs[k]["nulls"]["gate"]["segments"][s]["exp_r"]["alpha"]
                L.append(
                    f"| {k} | {seg_name[s]} | {c['n']:,} | {c['signal_dates']:,} | "
                    f"{c['top10_dates_share'] * 100:.1f}% | {gsd[(k, s)]:.4f} | "
                    f"{c['se_week_clustered']:.4f} | {a:+.4f} | {in_sd[(k, s)]:+.1f} | "
                    f"{in_se[(k, s)]:+.1f} |"
                )
        L.append("")
        L.append(
            "Entry fills at or below the stop, real rule against the P-gate placebo "
            "(descriptive, not pre-registered, no reading; engine R). The last two columns "
            "split the timing alpha."
        )
        L.append("")
        L.append(
            "| Version | Segment | Real: such fills | Real: R they add to expectancy | Placebo: "
            "such fills (mean) | Placebo: R they add (mean) | Timing alpha | from these fills | "
            "from all other trades |"
        )
        L.append("|---|---|---:|---:|---:|---:|---:|---:|---:|")
        for k in keys:
            for s in ("is", "oos"):
                g = gf[(k, s)]
                a = vs[k]["nulls"]["gate"]["segments"][s]["exp_r"]["alpha"]
                L.append(
                    f"| {k} | {seg_name[s]} | {g['actual_n']:,} of "
                    f"{vs[k]['actual'][s]['n']:,} ({g['actual_share'] * 100:.2f}%) | "
                    f"{g['actual_contribution_to_exp_r']:+.4f} | "
                    f"{g['placebo_share_mean'] * 100:.2f}% | "
                    f"{g['placebo_contribution_to_exp_r_mean']:+.4f} | {a:+.4f} | "
                    f"{g['alpha_from_these_fills']:+.4f} | {g['alpha_from_other_trades']:+.4f} |"
                )
        L.append("")
    fp_note = (
        " Each run row carries a fingerprint of the script"
        f"{sha_note}, the library modules it calls, the bars and the real rule's trade counts; "
        "finished runs in the output directory are reused only if that fingerprint matches, "
        "and are refused otherwise."
    )
    L.append(
        "Raw outputs (not committed): one run-level CSV per version and null "
        "(`placebo__<version>__<null>.csv`), `actual_trades__<version>.csv`, `identity.json` "
        "and `summary.json` under the round's scratch output directory `r3/out/placebo/`. To "
        "reproduce, run `scripts/r3/placebo_timing.py --k 200 --out <an empty directory>` with "
        f"`DATABASE_URL` set to a read-only (`mode=ro`) copy of the database.{fp_note} The "
        f"{sum(ks.values()):,} placebo runs here took "
        f"{meta.get('placebo_worker_seconds_total', float('nan')):,.0f} worker-seconds on "
        f"{meta.get('procs', 4)} processes."
    )
    L.append("")
    L.append("Research signal only — no order was placed.")
    L.append("")
    return "\n".join(L)


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
def compare_with(
    label: str, old_dir: Path, cells: dict[tuple[str, str], dict[int, dict[str, Any]]]
) -> dict[str, Any]:
    """Regression check: do the run rows of an earlier output directory equal the
    current rows, value for value, on every column both have? (``seconds`` and
    ``fp`` are not results.)"""
    rows = rows_equal = 0
    shared_n: set[int] = set()
    first_diff: str | None = None
    for (key, null), new_rows in cells.items():
        for run, old in read_cell(cell_path(old_dir, key, null)).items():
            rows += 1
            new = new_rows.get(run)
            if new is None:
                first_diff = first_diff or f"{key} {null} run {run}: not in the current rows"
                continue
            shared = [c for c in old if c in new and c not in ("seconds", "fp")]
            shared_n.add(len(shared))
            diff = [
                c
                for c in shared
                if old[c] != new[c]
                and not (
                    isinstance(old[c], float)
                    and isinstance(new[c], float)
                    and math.isnan(old[c])
                    and math.isnan(new[c])
                )
            ]
            if diff:
                first_diff = first_diff or f"{key} {null} run {run}: {diff[:5]}"
            else:
                rows_equal += 1
    return {
        "label": label,
        "path": str(old_dir),
        "rows": rows,
        "rows_equal": rows_equal,
        "shared_columns": min(shared_n) if shared_n else 0,
        "first_difference": first_diff,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--k", type=int, default=K_DEFAULT, help="placebo runs per version and null")
    ap.add_argument("--procs", type=int, default=4, help="worker processes (budget: 4)")
    ap.add_argument(
        "--out",
        type=Path,
        required=True,
        help="raw output directory; run rows found there are reused only if their "
        "fingerprint matches this script, the library, the bars and the trade counts",
    )
    ap.add_argument("--results", type=Path, default=DEFAULT_RESULTS)
    ap.add_argument("--budget-min", type=float, default=50.0, help="wall-time for placebo runs")
    ap.add_argument("--batch", type=int, default=10, help="run indices per batch")
    ap.add_argument("--no-results", action="store_true", help="do not write the results file")
    ap.add_argument(
        "--twin-runs",
        default="0,137",
        help="run indices re-done with the engine-in-the-loop planner as a whole-run check",
    )
    ap.add_argument(
        "--no-posthoc",
        action="store_true",
        help="leave out the post hoc 'always in when the gate allows' check (not "
        "pre-registered); the report then says the size is not measured",
    )
    ap.add_argument(
        "--compare-with",
        action="append",
        default=[],
        metavar="LABEL=DIR",
        help="earlier output directory whose run rows must equal the current ones on every "
        "shared column (regression check; repeatable)",
    )
    args = ap.parse_args()

    url = os.environ.get("DATABASE_URL", "")
    if "mode=ro" not in url:
        print("refusing to run: DATABASE_URL must be a read-only (mode=ro) SQLite URI")
        return 2
    if args.procs > 4:
        print("refusing to run: CPU budget is 4 worker processes")
        return 2
    out: Path = args.out
    out.mkdir(parents=True, exist_ok=True)
    keys = [v[0] for v in VERSIONS]
    t_start = time.time()
    log(f"R3-P placebo timing: K={args.k}, procs={args.procs}, out={out}")
    log(f"script sha256 {script_sha256()}, library sha256 {library_sha256()}")

    ctx = get_context("spawn")
    with ctx.Pool(processes=args.procs) as pool:
        # ---- 1. the real rules + identity check ---------------------------
        actual: dict[str, Any] = {}
        for res in pool.imap_unordered(actual_task, keys, chunksize=1):
            actual[res["key"]] = res
            i = res["identity"]
            log(
                f"actual {res['key']} (snapshot {res['snapshot']}, {res['n_series']} series): "
                f"OOS {i['oos_n']} / {i['oos_expectancy_r']:+.4f}R, IS {i['is_n']} / "
                f"{i['is_expectancy_r']:+.4f}R, bars {res['first_bar']}..{res['last_bar']}, "
                f"{res['seconds']}s"
            )
        failures = []
        bars_sha: dict[int, str] = {}
        for key, snap, rec_n, rec_exp in VERSIONS:
            a = actual[key]
            i, rp, ex = a["identity"], a["replay"], a["example"]
            if i["oos_n"] != rec_n or round(i["oos_expectancy_r"], 4) != rec_exp:
                failures.append(
                    f"{key}: reproduced OOS {i['oos_n']} / {i['oos_expectancy_r']:+.4f}R, "
                    f"recorded {rec_n} / {rec_exp:+.4f}R"
                )
            if (
                rp["trade_mismatches"]
                or rp["geometry_mismatches"]
                or rp["replay_trades"] != rp["actual_trades"]
            ):
                failures.append(f"{key}: placebo replay on the real dates failed: {rp}")
            if not ex or ex["equal"] != ex["signals_checked"]:
                failures.append(f"{key}: one-symbol stop/target check failed: {ex}")
            sc = a["planner_selfcheck"]
            if sc["cases"] == 0 or sc["equal"] != sc["cases"]:
                failures.append(f"{key}: planner vs engine-in-the-loop self-check failed: {sc}")
            log(
                f"checks {key}: planner self-check {sc['equal']}/{sc['cases']} equal on "
                f"{','.join(sc['symbols'])} ({sc['redraws']} redraws, "
                f"{sc['engine_passes']} engine passes)"
            )
            if date.fromisoformat(a["last_bar"]) > END:
                failures.append(f"{key}: bar after the development window: {a['last_bar']}")
            if bars_sha.setdefault(snap, a["bars_sha256"]) != a["bars_sha256"]:
                failures.append(f"{key}: two workers loaded different bars for snapshot {snap}")
            log(
                f"checks {key}: replay {rp['replay_trades']}/{rp['actual_trades']} trades, "
                f"{rp['trade_mismatches']} trade mismatches, {rp['geometry_mismatches']} geometry "
                f"mismatches; example {ex.get('symbol')} {ex.get('equal')}/"
                f"{ex.get('signals_checked')} equal"
            )
        identity_doc = {
            "failures": failures,
            "versions": {
                k: {kk: vv for kk, vv in a.items() if kk != "rows"} for k, a in actual.items()
            },
        }
        if failures:
            (out / "identity.json").write_text(
                json.dumps(identity_doc, indent=2, default=_json_default)
            )
            log("IDENTITY CHECK FAILED — stopping before any placebo run")
            for f in failures:
                log("  " + f)
            return 3
        log("identity and construction checks passed")

        counts: dict[str, dict[str, dict[int, int]]] = {}
        for key in keys:
            c: dict[str, dict[int, int]] = {}
            for r in actual[key]["rows"]:
                c.setdefault(r["symbol"], {}).setdefault(r["signal_year"], 0)
                c[r["symbol"]][r["signal_year"]] += 1
            counts[key] = c

        # ---- 1b. provenance: refuse run rows made from anything else -------
        counts_sha = {k: counts_sha256(counts[k]) for k in keys}
        want_fp = {
            (k, n): cell_fingerprint(k, n, actual[k]["bars_sha256"], counts_sha[k])
            for k in keys
            for n in NULLS
        }
        cells = {(k, n): read_cell(cell_path(out, k, n)) for k in keys for n in NULLS}
        stale = []
        for (k, n), rows_ in cells.items():
            bad = sum(1 for r in rows_.values() if r.get("fp") != want_fp[(k, n)])
            if bad:
                stale.append(f"{cell_path(out, k, n).name}: {bad} of {len(rows_)} rows")
        if stale:
            log(
                "REFUSING TO REUSE RUN ROWS: they were not made by this script with these "
                "library modules, bars and trade counts. Nothing was written. Use an empty "
                "--out directory or move these files away:"
            )
            for s in sorted(stale):
                log("  " + s)
            return 4
        provenance = {
            "script_sha256": script_sha256(),
            "library_sha256": library_sha256(),
            "library_modules": list(_LIB_MODULES),
            "bars_sha256_by_snapshot": {str(s): h for s, h in sorted(bars_sha.items())},
            "counts_sha256": counts_sha,
            "cell_fingerprints": {f"{k}|{n}": fp for (k, n), fp in want_fp.items()},
        }
        identity_doc["provenance"] = provenance
        (out / "identity.json").write_text(
            json.dumps(identity_doc, indent=2, default=_json_default)
        )
        for key in keys:
            rows = actual[key]["rows"]
            with (out / f"actual_trades__{key}.csv").open("w", newline="") as fh:
                w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
                w.writeheader()
                w.writerows(rows)
        counts_path = out / "actual_counts.json"
        counts_path.write_text(json.dumps(counts, indent=0, sort_keys=True))

        # ---- 2. placebo runs ---------------------------------------------
        done0 = sum(len(v) for v in cells.values())
        if done0:
            log(f"resuming: {done0} finished runs with a matching fingerprint found on disk")
        deadline = time.time() + args.budget_min * 60.0
        stopped_early = False
        for b0 in range(0, args.k, args.batch):
            runs = range(b0, min(args.k, b0 + args.batch))
            tasks = [
                (k, n, r, str(counts_path))
                for r in runs
                for k in keys
                for n in NULLS
                if r not in cells[(k, n)]
            ]
            if not tasks:
                continue
            if time.time() > deadline:
                stopped_early = True
                log(f"wall-time budget reached before run {b0}; stopping at whole batches")
                break
            tb = time.time()
            for res in pool.imap_unordered(placebo_task, tasks, chunksize=1):
                cell_key = (res["key"], res["null"])
                if res["row"]["fp"] != want_fp[cell_key]:
                    raise RuntimeError(
                        f"a worker made {cell_key} run {res['row']['run']} from another script, "
                        f"library, bars or trade counts: {res['row']['fp']} != {want_fp[cell_key]}"
                    )
                cells[cell_key][res["row"]["run"]] = res["row"]
            for (k, n), rows_ in cells.items():
                write_cell(cell_path(out, k, n), rows_)
            log(
                f"runs {runs.start}..{runs.stop - 1} done for all cells in "
                f"{time.time() - tb:.0f}s (elapsed {time.time() - t_start:.0f}s)"
            )

        # ---- 2b. whole-run check with the engine-in-the-loop planner -------
        twin_path = out / "twin_check.json"
        twin: dict[str, Any] = json.loads(twin_path.read_text()) if twin_path.exists() else {}
        old_twin = [t for t, v in twin.items() if v.get("fp") != want_fp[(v["key"], v["null"])]]
        for t in old_twin:  # a check made with another script or other data proves nothing here
            del twin[t]
        if old_twin:
            log(f"whole-run twin check: {len(old_twin)} earlier results discarded (fingerprint)")
        twin_runs = [int(x) for x in args.twin_runs.split(",") if x.strip()]
        todo = [
            (k, n, r, str(counts_path), cells[(k, n)][r])
            for k in keys
            for n in NULLS
            for r in twin_runs
            if r in cells[(k, n)] and f"{k}|{n}|{r}" not in twin
        ]
        if todo:
            for res in pool.imap_unordered(twin_task, todo, chunksize=1):
                twin[f"{res['key']}|{res['null']}|{res['run']}"] = res
            twin_path.write_text(json.dumps(twin, indent=2, sort_keys=True))
        twin_bad = sorted(k for k, v in twin.items() if not v["identical"])
        log(
            f"whole-run twin check: {len(twin) - len(twin_bad)} of {len(twin)} runs identical "
            f"({len(todo)} computed now)"
        )
        if twin_bad:
            log("WHOLE-RUN TWIN CHECK FAILED — no results written: " + ", ".join(twin_bad))
            return 3

        # ---- 2c. post hoc, not pre-registered: always in when the gate allows ----
        posthoc: dict[str, Any] | None = None
        if not args.no_posthoc:
            posthoc = {}
            for res in pool.imap_unordered(gated_exposure_task, keys, chunksize=1):
                if res["bars_sha256"] != actual[res["key"]]["bars_sha256"]:
                    raise RuntimeError(f"post hoc check for {res['key']} read other bars")
                posthoc[res["key"]] = res
                log(
                    f"post hoc (not pre-registered) {res['key']}: always in when the gate "
                    f"allows, IS {res['segments']['is']['n']:,} trades "
                    f"{res['segments']['is']['exp_r']:+.4f}R, OOS "
                    f"{res['segments']['oos']['n']:,} trades "
                    f"{res['segments']['oos']['exp_r']:+.4f}R, {res['seconds']}s"
                )
            (out / "posthoc_gated_exposure.json").write_text(
                json.dumps(
                    {
                        "note": "POST HOC, NOT PRE-REGISTERED; no reading uses it",
                        "versions": {k: posthoc[k] for k in keys},
                    },
                    indent=2,
                    default=_json_default,
                )
            )

    # ---- 2d. regression check against earlier output directories ----------
    comparison = []
    for spec in args.compare_with:
        label, _, path = spec.partition("=")
        if not path:
            label, path = Path(spec).name, spec
        comparison.append(compare_with(label, Path(path), cells))
        c_ = comparison[-1]
        log(
            f"comparison with {label}: {c_['rows_equal']} of {c_['rows']} earlier run rows "
            f"equal on {c_['shared_columns']} shared columns"
        )
    if comparison:
        (out / "comparison.json").write_text(json.dumps(comparison, indent=2))
    cmp_bad = [c_ for c_ in comparison if c_["rows"] == 0 or c_["rows_equal"] != c_["rows"]]
    if cmp_bad:
        log("COMPARISON FAILED — no results written:")
        for c_ in cmp_bad:
            log(f"  {c_['label']}: {c_['rows_equal']} of {c_['rows']}; {c_['first_difference']}")
        return 5

    # ---- 3. summary + results ---------------------------------------------
    summary = summarise(out, actual, args.k)
    summary["meta"]["provenance"] = provenance
    summary["twin_check"] = {
        "runs": twin_runs,
        "cases": len(twin),
        "identical": len(twin) - len(twin_bad),
    }
    if posthoc is not None:
        summary["posthoc"] = {
            "note": "POST HOC, NOT PRE-REGISTERED; no reading uses it",
            "gated_exposure": {k: posthoc[k] for k in keys},
        }
    if comparison:
        summary["comparison"] = comparison
    summary["meta"]["stopped_early"] = stopped_early
    summary["meta"]["procs"] = args.procs
    # This invocation may only have rebuilt the report from runs already on disk.
    summary["meta"]["this_invocation"] = {
        "wall_seconds": round(time.time() - t_start, 1),
        "placebo_runs_found_on_disk": done0,
        "placebo_runs_executed": sum(len(v) for v in cells.values()) - done0,
    }
    summary["meta"]["placebo_worker_seconds_total"] = round(
        sum(float(r["seconds"]) for v in cells.values() for r in v.values()), 1
    )
    (out / "summary.json").write_text(json.dumps(summary, indent=2, default=_json_default))
    md = render(summary)
    (out / "results_preview.md").write_text(md)
    if not args.no_results:
        args.results.write_text(md)
        log(f"results written to {args.results}")
    for key in keys:
        v = summary["versions"][key]
        for null in NULLS:
            nd = v["nulls"].get(null, {})
            if not nd.get("K"):
                continue
            c = nd["segments"]["oos"]["exp_r"]
            log(
                f"{key} {null}: K={nd['K']} OOS actual {c['actual']:+.4f} placebo "
                f"{c['placebo_mean']:+.4f} [{c['placebo_p2_5']:+.4f}, {c['placebo_p97_5']:+.4f}] "
                f"alpha {c['alpha']:+.4f} p {c['p']:.4f}"
            )
    log(f"finished in {time.time() - t_start:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
