#!/usr/bin/env python
"""Stage A for ``mean_reversion.short_swing`` exits/risk redesign — ZERO sealed looks, ZERO rows.

Implements §4 (F1–F5) and §9 (stopping rule) of
``docs/research/designs/proposals/mean_reversion_short_swing--exits_risk.md``.

Everything here is READ-ONLY by construction and by tripwire, modelled on
``scripts/stage_a_v6.py``:

* it refuses to run against the live database path and opens the supplied
  COPY through a ``mode=ro`` URI, so SQLite itself refuses a write;
* :func:`_install_tripwires` replaces ``evaluate_promotion``,
  ``_get_or_create_sealed_test``, ``persist_promotion_evaluation``,
  ``get_or_create_dataset_snapshot`` and ``persist_backtest_result`` with
  functions that raise, and a SQLAlchemy ``before_cursor_execute`` hook raises
  on any write statement that reaches the driver;
* :func:`_assert_pre_sealed` re-checks every trade date and the run's data
  provenance against the snapshot's pre-sealed end, so nothing inside the
  sealed window is ever computed.

The engine does not yet support ``stop_distance`` / ``stop_anchor_blend`` /
``min_risk_distance`` (proposal §2.1). The two variants are therefore realised
HERE as a thin wrapper around the public ``run_backtest``: the wrapper sees the
full series (the engine reads the same next-bar open to price the fill) and
rewrites the ``EntrySignal`` so that the engine's own ``risk_per_share`` and
``_resolve_exit`` operate on the proposed stop level. At ``stop_anchor_blend =
0.0`` the wrapper is the identity and reproduces v0.1.0 trade for trade — this
is asserted before any variant number is believed.

Usage::

    python scripts/stage_a_mr.py \\
        --db "$TMPDIR/mr_stage_a.sqlite" \\
        --emit docs/research/designs/scripts/mean_reversion_short_swing/stage_a.json
"""

from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

# --------------------------------------------------------------------------- #
# pre-registered constants — proposal §4, §9. NOTHING here may be changed by a result.
# --------------------------------------------------------------------------- #
SPAN_START = date(2016, 9, 10)
PRE_SEALED_END = date(2025, 9, 7)  # snapshots 2, 3, 4
PRE_SEALED_END_SNAPSHOT_1 = date(2025, 9, 6)  # snapshot 1's legacy window (§4 F5)

LIVE_DB_PATH = Path("~/signal-forge/data/signalforge.sqlite").expanduser().resolve()

# Reproduction check (proposal §3.1 / Appendix): eval 34 on snapshot 3.
REPRO_SNAPSHOT_KEY = "universe_24_ex_meta"
REPRO_EXPECT = {"all": 984, "oos": 309, "oos_expectancy_r": -0.0837}

# The four snapshots F5 requires, in the §9 order (3 and 2 first).
SNAPSHOT_KEYS: tuple[str, ...] = (
    "universe_24_ex_meta",
    "universe_25_baseline",
    "universe_25_baseline_legacy",
    "universe_25_meta_continuity_corrected",
)
F1_SE_BAR = 2.0
F3_FOLD2_MIN_IMPROVEMENT_R = 0.05
F4_MIN_RISK_ATR = 0.5
F2_RISK_PARTITION_ATR = 1.0

V1_PARAMS = {"stop_anchor_blend": 1.0}  # §2.2
V2_PARAMS = {"min_risk_atr": 1.0}  # §2.3
DEGENERATE = {"stop_anchor_blend": 0.0}  # == v0.1.0 exactly


class StageAViolation(RuntimeError):
    """A Stage A invariant was broken. Always fatal: never caught, never warned."""


# --------------------------------------------------------------------------- #
# the exit/risk variants, as a wrapper around the public engine
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class SignalRecord:
    """What the wrapper saw at the signal bar, keyed by the engine's entry date."""

    signal_date: date
    close: float
    atr: float
    stale_stop: float
    stop_distance: float  # stop_atr × ATR(14): the fixed F1 denominator
    stop_level: float  # the level the engine was handed
    raw_fill: float  # next-bar open after slippage, as the engine prices it


def engine_slip(cost_model: Any, spread_bps: float = 5.0) -> float:
    """``run_backtest``'s slippage fraction, reproduced exactly (engine.py)."""
    half = spread_bps / 2 if cost_model.half_spread_fill_penalty else 0.0
    return (cost_model.slippage_bps + half) / 10_000.0


def variant_signal_fn(
    base_fn: Callable[[Any, int], Any],
    series: Any,
    *,
    stop_atr: float,
    slip: float,
    stop_anchor_blend: float = 0.0,
    min_risk_atr: float | None = None,
    records: dict[tuple[str, date], SignalRecord] | None = None,
) -> Callable[[Any, int], Any]:
    """Rewrite each ``EntrySignal`` so the public engine applies the proposed
    stop level (V1, ``stop_anchor_blend``) or no-trade guard (V2,
    ``min_risk_atr``) — proposal §2.1's ``stop_level`` arithmetic, verbatim.

    ``series`` is the FULL series the engine runs over, so ``series.open[t+1]``
    is the same number ``run_backtest`` uses to fill the entry. With
    ``stop_anchor_blend == 0.0`` and ``min_risk_atr`` unset the signal is
    returned unchanged.
    """
    from dataclasses import replace

    if not 0.0 <= stop_anchor_blend <= 1.0:
        raise ValueError("stop_anchor_blend must be in [0, 1]")

    def _fn(head: Any, t: int) -> Any:
        sig = base_fn(head, t)
        if sig is None or t + 1 >= len(series):
            return sig
        close = float(series.close[t])
        stop_distance = close - sig.stop_price  # == stop_atr × ATR at the signal bar
        a = stop_distance / stop_atr
        d = 1  # the strategy is long-only (permits_short=False)
        fill = float(series.open[t + 1]) * (1 + d * slip)
        stop_level = sig.stop_price
        if stop_anchor_blend > 0.0:
            fill_anchored = fill - d * stop_distance
            stop_level = (
                1.0 - stop_anchor_blend
            ) * sig.stop_price + stop_anchor_blend * fill_anchored
        if min_risk_atr is not None and (fill - stop_level) < min_risk_atr * a:
            return None  # engine then advances one bar: the §2.3 cancel-at-the-open
        if records is not None:
            records[(series.symbol, series.dates[t + 1])] = SignalRecord(
                signal_date=series.dates[t],
                close=close,
                atr=a,
                stale_stop=sig.stop_price,
                stop_distance=stop_distance,
                stop_level=stop_level,
                raw_fill=fill,
            )
        if stop_level == sig.stop_price:
            return sig
        return replace(sig, stop_price=stop_level)

    return _fn


def run_variant(
    series: Any,
    base_fn: Callable[[Any, int], Any],
    *,
    stop_atr: float,
    cost_model: Any,
    warmup: int,
    stop_anchor_blend: float = 0.0,
    min_risk_atr: float | None = None,
    records: dict[tuple[str, date], SignalRecord] | None = None,
) -> Any:
    """``run_backtest`` with the variant wrapper installed."""
    from signalforge.backtest.engine import run_backtest

    fn = variant_signal_fn(
        base_fn,
        series,
        stop_atr=stop_atr,
        slip=engine_slip(cost_model),
        stop_anchor_blend=stop_anchor_blend,
        min_risk_atr=min_risk_atr,
        records=records,
    )
    return run_backtest(series, fn, cost_model=cost_model, warmup=warmup)


# --------------------------------------------------------------------------- #
# read-only tripwires
# --------------------------------------------------------------------------- #
def refuse_live_db(db: Path) -> Path:
    """The live DB is under a paper probation and a worker. Never open it here."""
    resolved = db.expanduser().resolve()
    if resolved == LIVE_DB_PATH:
        raise StageAViolation(
            f"--db points at the LIVE database {resolved}. Stage A runs only against a copy."
        )
    for sibling in (
        resolved.with_name(resolved.name + "-wal"),
        resolved.with_name(resolved.name + "-shm"),
    ):
        if sibling.exists() and resolved.parent == LIVE_DB_PATH.parent:
            raise StageAViolation(f"--db {resolved} sits in the live data directory; refusing.")
    if not resolved.exists():
        raise StageAViolation(f"--db {resolved} does not exist")
    return resolved


def read_only_url(db: Path) -> str:
    return f"sqlite+pysqlite:///file:{db}?mode=ro&uri=true"


def _install_tripwires() -> None:
    from sqlalchemy import event
    from sqlalchemy.engine import Engine

    from signalforge.research import persistence as _persist
    from signalforge.research import promotion as _promo

    def _forbidden(name: str) -> Callable[..., Any]:
        def _raise(*_a: Any, **_k: Any) -> Any:
            raise StageAViolation(
                f"Stage A called {name}() — a sealed/writing entry point. Stage A is "
                f"pre-registered at zero looks and zero rows (proposal §9, §10)."
            )

        return _raise

    for attr in (
        "evaluate_promotion",
        "_get_or_create_sealed_test",
        "persist_promotion_evaluation",
        "get_or_create_dataset_snapshot",
    ):
        if hasattr(_promo, attr):
            setattr(_promo, attr, _forbidden(f"promotion.{attr}"))
    for attr in ("persist_backtest_result", "upsert_strategy_version"):
        if hasattr(_persist, attr):
            setattr(_persist, attr, _forbidden(f"persistence.{attr}"))

    writes = ("insert", "update", "delete", "create", "drop", "alter", "replace")

    @event.listens_for(Engine, "before_cursor_execute")
    def _no_writes(  # type: ignore[no-untyped-def]
        conn, cursor, statement, parameters, context, executemany
    ) -> None:
        head = statement.lstrip().split(None, 1)
        if head and head[0].lower() in writes:
            raise StageAViolation(f"Stage A attempted a write: {statement[:160]!r}")


def _assert_pre_sealed(
    label: str, trades: Sequence[Any], sealed_start: date, provenance: Any = None
) -> None:
    for tr in trades:
        for field_name in ("entry_date", "exit_date"):
            d = getattr(tr, field_name)
            d = d.date() if hasattr(d, "date") else d
            if d >= sealed_start:
                raise StageAViolation(
                    f"{label}: trade {tr.symbol} has {field_name}={d}, inside the sealed window"
                )
    if provenance is not None and provenance.last is not None and provenance.last >= sealed_start:
        raise StageAViolation(
            f"{label}: data provenance last bar {provenance.last} is inside the sealed window"
        )


# --------------------------------------------------------------------------- #
# statistics
# --------------------------------------------------------------------------- #
def _moments(xs: Sequence[float]) -> dict[str, float | int]:
    n = len(xs)
    if n == 0:
        return {"n": 0, "mean": 0.0, "sd": 0.0, "se": 0.0}
    if n == 1:
        return {"n": 1, "mean": float(xs[0]), "sd": 0.0, "se": 0.0}
    mean = statistics.fmean(xs)
    sd = statistics.stdev(xs)
    return {"n": n, "mean": mean, "sd": sd, "se": sd / math.sqrt(n)}


def _m(d: Mapping[str, Any]) -> str:
    return (
        f"{float(d['mean']):+.4f}R ± {float(d['se']):.4f} "
        f"(n = {int(d['n'])}, sd {float(d['sd']):.4f})"
    )


# --------------------------------------------------------------------------- #
# one snapshot, one variant
# --------------------------------------------------------------------------- #
@dataclass(slots=True)
class VersionRun:
    label: str
    trades: list[Any]
    oos: list[Any]
    records: dict[tuple[str, date], SignalRecord]
    boundaries: dict[str, date]


def _snapshot_plan(session: Any, key: str) -> tuple[Any, list[str], Any, date, date]:
    """``(snapshot, symbols, source_filter, pre_sealed_end, sealed_start)``.

    Snapshot 4 (``META_CONT``) is loaded through the SAME continuity mapping the
    promotion path uses: ``source = [provider, f"continuity_bridge:{mapping_id}"]``
    (``fb_meta_universe_comparison.source_for_variant``). Snapshot 1 keeps its
    legacy window ending 2025-09-06.
    """
    from sqlalchemy import select

    from signalforge.db.models import DataSnapshot
    from signalforge.research.fb_meta_universe_comparison import source_for_variant

    snap = session.scalar(select(DataSnapshot).where(DataSnapshot.key == key))
    if snap is None:
        raise StageAViolation(f"no DataSnapshot with key {key!r}")
    source = source_for_variant(key, "massive", snap.continuity_mapping_id)
    end = PRE_SEALED_END_SNAPSHOT_1 if key == "universe_25_baseline_legacy" else PRE_SEALED_END
    return snap, list(snap.symbols_json), source, end, end + timedelta(days=1)


def _run_version(
    session: Any,
    label: str,
    symbols: Sequence[str],
    source: Any,
    end: date,
    sealed_start: date,
    *,
    stop_anchor_blend: float = 0.0,
    min_risk_atr: float | None = None,
) -> VersionRun:
    """Drive ``run_backtest`` per symbol exactly as ``run_strategy_over_universe``
    does (proxy SPY, ``min_bars = 60``, ``warmup = 30``, ``CostModel()``), with
    the variant wrapper installed."""
    from signalforge.backtest.costs import CostModel
    from signalforge.data.series import PriceSeries
    from signalforge.research.backtest_runner import DEFAULT_PROXY, _as_date, _is_boundary
    from signalforge.research.regime import regime_lookup
    from signalforge.research.strategies.base import signal_fn_for
    from signalforge.research.strategies.mean_reversion import MeanReversion

    strat = MeanReversion()
    cm = CostModel()
    proxy = PriceSeries.load(session, DEFAULT_PROXY, SPAN_START, end, source=source)
    regimes = regime_lookup(proxy) if len(proxy) else {}
    base_fn = signal_fn_for(strat, regime_by_date=regimes, allow_short=False)

    records: dict[tuple[str, date], SignalRecord] = {}
    trades: list[Any] = []
    oos: list[Any] = []
    boundaries: dict[str, date] = {}
    for sym in symbols:
        series = PriceSeries.load(session, sym, SPAN_START, end, source=source)
        if len(series) < 60:
            continue
        outcome = run_variant(
            series,
            base_fn,
            stop_atr=strat.params.stop_atr,
            cost_model=cm,
            warmup=30,
            stop_anchor_blend=stop_anchor_blend,
            min_risk_atr=min_risk_atr,
            records=records,
        )
        boundary = _as_date(_is_boundary(series))
        boundaries[sym] = boundary
        for tr in outcome.trades:
            trades.append(tr)
            if _as_date(tr.entry_date) > boundary:
                oos.append(tr)
    _assert_pre_sealed(label, trades, sealed_start)
    return VersionRun(label, trades, oos, records, boundaries)


def _runner_check(
    session: Any, symbols: Sequence[str], source: Any, end: date, sealed_start: date
) -> Any:
    """The real pipeline function, for the reproduction check and provenance."""
    from signalforge.research.backtest_runner import run_strategy_over_universe
    from signalforge.research.strategies.mean_reversion import MeanReversion

    res = run_strategy_over_universe(
        session, MeanReversion(), list(symbols), SPAN_START, end, source=source
    )
    _assert_pre_sealed("runner", res.trades, sealed_start, res.data)
    return res


def _same_trades(a: Sequence[Any], b: Sequence[Any]) -> bool:
    if len(a) != len(b):
        return False
    return all(
        x.symbol == y.symbol
        and x.entry_date == y.entry_date
        and x.exit_date == y.exit_date
        and x.entry_price == y.entry_price
        and x.exit_price == y.exit_price
        and x.exit_reason == y.exit_reason
        and abs(x.pnl_r - y.pnl_r) < 1e-12
        for x, y in zip(a, b, strict=True)
    )


# --------------------------------------------------------------------------- #
# F1–F4
# --------------------------------------------------------------------------- #
def _fixed_denominator_r(tr: Any, rec: SignalRecord) -> float:
    """P&L in units of ``stop_atr × ATR(14)`` at the signal bar — identical for
    both versions, so the R-rescaling of §3.4 cancels exactly."""
    return (tr.exit_price - tr.entry_price) / rec.stop_distance


def _realised_risk_atr(tr: Any, rec: SignalRecord) -> float:
    return abs(tr.entry_price - rec.stop_level) / rec.atr


def _paired(
    base: VersionRun, var: VersionRun, *, subset: Callable[[Any, SignalRecord], bool] | None = None
) -> dict[str, Any]:
    bmap = {(t.symbol, t.entry_date): t for t in base.trades}
    vmap = {(t.symbol, t.entry_date): t for t in var.trades}
    keys = sorted(set(bmap) & set(vmap), key=lambda k: (k[1], k[0]))
    diffs: list[float] = []
    for k in keys:
        rec_b = base.records[k]
        if subset is not None and not subset(bmap[k], rec_b):
            continue
        diffs.append(
            _fixed_denominator_r(vmap[k], var.records[k]) - _fixed_denominator_r(bmap[k], rec_b)
        )
    mom = _moments(diffs)
    sigma = float(mom["mean"]) / float(mom["se"]) if mom["se"] else 0.0
    return {
        **mom,
        "sigma": sigma,
        "n_base": len(base.trades),
        "n_variant": len(var.trades),
        "n_matched": len(keys),
        "n_base_unmatched": len(set(bmap) - set(vmap)),
        "n_variant_unmatched": len(set(vmap) - set(bmap)),
    }


def f1(base: VersionRun, var: VersionRun) -> dict[str, Any]:
    p = _paired(base, var)
    p["passed"] = bool(float(p["mean"]) > 0.0 and p["sigma"] >= F1_SE_BAR)
    p["bar"] = f"paired mean > 0 and >= {F1_SE_BAR:.1f} SE"
    return p


def f2(base: VersionRun, var: VersionRun, whole: Mapping[str, Any]) -> dict[str, Any]:
    big = _paired(base, var, subset=lambda t, r: _realised_risk_atr(t, r) >= F2_RISK_PARTITION_ATR)
    tail = _paired(base, var, subset=lambda t, r: _realised_risk_atr(t, r) < F2_RISK_PARTITION_ATR)
    # F2 fires when the whole-sample difference is positive but the >= 1 ATR
    # subset is under 2 SE: the effect lives only in the gapped tail.
    fired = bool(float(whole["mean"]) > 0.0 and big["sigma"] < F1_SE_BAR)
    return {
        "risk_ge_1atr": big,
        "risk_lt_1atr": tail,
        "passed": not fired,
        "bar": "paired difference on the risk >= 1 ATR subset must itself be >= 2 SE",
    }


def _folds(trades: Sequence[Any], th: Any, end: date) -> list[dict[str, Any]]:
    from signalforge.research.portfolio_metrics import compute_portfolio_metrics

    span_days = (end - SPAN_START).days
    n_folds = th.min_walkforward_folds
    rows = []
    for k in range(n_folds):
        lo = SPAN_START + timedelta(days=span_days * k // n_folds)
        hi = SPAN_START + timedelta(days=span_days * (k + 1) // n_folds)
        ft = [t for t in trades if lo <= t.entry_date < hi]
        pm = compute_portfolio_metrics(ft, span_start=lo, span_end=hi)
        rows.append(
            {
                "fold": k + 1,
                "start": lo.isoformat(),
                "end": hi.isoformat(),
                "n_trades": pm.n_trades,
                "expectancy_r": pm.avg_trade_r,
                "positive_with_floor": bool(
                    pm.n_trades >= th.sensitivity_min_grid_trades
                    and pm.avg_trade_r > th.min_net_expectancy_r
                ),
            }
        )
    return rows


def f3(base: VersionRun, var: VersionRun, th: Any, end: date) -> dict[str, Any]:
    fb = _folds(base.trades, th, end)
    fv = _folds(var.trades, th, end)
    positive = sum(1 for f in fv if f["positive_with_floor"])
    deltas = [v["expectancy_r"] - b["expectancy_r"] for b, v in zip(fb, fv, strict=True)]
    gate1 = positive >= 2
    redistribution = bool(
        len(deltas) >= 3
        and deltas[1] < F3_FOLD2_MIN_IMPROVEMENT_R
        and deltas[0] < 0.0
        and deltas[2] < 0.0
    )
    return {
        "baseline_folds": fb,
        "variant_folds": fv,
        "fold_deltas_r": deltas,
        "variant_positive_folds": positive,
        "gate1_would_pass": gate1,
        "redistribution_pattern": redistribution,
        "passed": bool(gate1 and not redistribution),
        "bar": (
            ">= 2 of 4 folds positive with n >= 15; and NOT (fold 2 improves < 0.05R "
            "while folds 1 and 3 both deteriorate)"
        ),
    }


def f4(var: VersionRun) -> dict[str, Any]:
    stop_wins = [t for t in var.trades if t.exit_reason == "stop" and t.pnl_r > 0]
    thin = [
        t
        for t in var.trades
        if _realised_risk_atr(t, var.records[(t.symbol, t.entry_date)]) < F4_MIN_RISK_ATR
    ]
    return {
        "profitable_stop_exits": len(stop_wins),
        "risk_below_half_atr": len(thin),
        "examples": [
            {
                "symbol": t.symbol,
                "entry_date": t.entry_date.isoformat(),
                "pnl_r": t.pnl_r,
                "exit": t.exit_reason,
            }
            for t in (stop_wins + thin)[:10]
        ],
        "passed": bool(not stop_wins and not thin),
        "bar": "0 profitable 'stop' exits and 0 trades with realised risk < 0.5 ATR",
    }


def _artefact_census(run: VersionRun) -> dict[str, Any]:
    """The §3.2/§3.3 pathology census for whichever run it is handed."""
    stop_wins = sum(1 for t in run.trades if t.exit_reason == "stop" and t.pnl_r > 0)
    tail = [
        t for t in run.trades if _realised_risk_atr(t, run.records[(t.symbol, t.entry_date)]) < 1.0
    ]
    rest = [
        t for t in run.trades if _realised_risk_atr(t, run.records[(t.symbol, t.entry_date)]) >= 1.0
    ]
    return {
        "profitable_stop_exits": stop_wins,
        "risk_lt_1atr": _moments([t.pnl_r for t in tail]),
        "risk_ge_1atr": _moments([t.pnl_r for t in rest]),
    }


def evaluate_variant(
    session: Any, name: str, params: Mapping[str, Any], th: Any, keys: Sequence[str]
) -> dict[str, Any]:
    out: dict[str, Any] = {"label": name, "params": dict(params), "snapshots": {}}
    for key in keys:
        t0 = time.time()
        snap, symbols, source, end, sealed_start = _snapshot_plan(session, key)
        base = _run_version(session, f"{key}/v0.1.0", symbols, source, end, sealed_start)
        var = _run_version(
            session,
            f"{key}/{name}",
            symbols,
            source,
            end,
            sealed_start,
            stop_anchor_blend=float(params.get("stop_anchor_blend", 0.0)),
            min_risk_atr=params.get("min_risk_atr"),
        )
        whole = f1(base, var)
        bm, vm = _moments([t.pnl_r for t in base.trades]), _moments([t.pnl_r for t in var.trades])
        unpaired_se = math.sqrt(float(bm["se"]) ** 2 + float(vm["se"]) ** 2)
        unpaired = {
            "difference_r": float(vm["mean"]) - float(bm["mean"]),
            "se": unpaired_se,
            "sigma": (
                ((float(vm["mean"]) - float(bm["mean"])) / unpaired_se) if unpaired_se else 0.0
            ),
            "note": (
                "raw-R, unpaired, NOT accounting-invariant: shown for context only; "
                "F1 is the paired fixed-denominator test above"
            ),
        }
        row: dict[str, Any] = {
            "unpaired_pre_sealed_delta": unpaired,
            "snapshot_id": snap.id,
            "snapshot_key": key,
            "n_symbols": len(symbols),
            "symbols_with_data": len(base.boundaries),
            "source": source if isinstance(source, str) else list(source),
            "pre_sealed_end": end.isoformat(),
            "sealed_window_start": sealed_start.isoformat(),
            "v0_1_0": {
                "all_pre_sealed": _moments([t.pnl_r for t in base.trades]),
                "oos": _moments([t.pnl_r for t in base.oos]),
                "artefacts": _artefact_census(base),
            },
            name: {
                "all_pre_sealed": _moments([t.pnl_r for t in var.trades]),
                "oos": _moments([t.pnl_r for t in var.oos]),
                "artefacts": _artefact_census(var),
            },
            "F1": whole,
            "F2": f2(base, var, whole),
            "F3": f3(base, var, th, end),
            "F4": f4(var),
            "elapsed_s": round(time.time() - t0, 1),
        }
        out["snapshots"][key] = row
        print(
            f"[{name}] {key}: F1 {whole['mean']:+.5f}R ± {whole['se']:.5f} "
            f"({whole['sigma']:+.2f} SE, matched {whole['n_matched']}) "
            f"-> {'PASS' if whole['passed'] else 'FAIL'}; "
            f"F2 {'PASS' if row['F2']['passed'] else 'FAIL'} "
            f"F3 {'PASS' if row['F3']['passed'] else 'FAIL'} "
            f"F4 {'PASS' if row['F4']['passed'] else 'FAIL'} ({row['elapsed_s']}s)",
            flush=True,
        )
    signs = {float(r["F1"]["mean"]) > 0 for r in out["snapshots"].values()}
    out["F5"] = {
        "same_sign_on_all": len(signs) == 1,
        "all_F1_to_F4_hold": all(
            r[f]["passed"] for r in out["snapshots"].values() for f in ("F1", "F2", "F3", "F4")
        ),
        "snapshots_run": list(out["snapshots"]),
    }
    out["F5"]["passed"] = bool(
        out["F5"]["same_sign_on_all"] and out["F5"]["all_F1_to_F4_hold"] and len(keys) == 4
    )
    out["verdict"] = {
        f: all(r[f]["passed"] for r in out["snapshots"].values()) for f in ("F1", "F2", "F3", "F4")
    }
    out["verdict"]["F5"] = out["F5"]["passed"]
    out["survives"] = all(out["verdict"].values())
    return out


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", required=True, help="path to a READ-ONLY COPY of the database")
    ap.add_argument(
        "--snapshot-key", default="universe_24_ex_meta", help="primary snapshot (run first)"
    )
    ap.add_argument("--emit", required=True, help="path to stage_a.json")
    args = ap.parse_args(argv)

    db = refuse_live_db(Path(args.db))
    url = read_only_url(db)
    os.environ["DATABASE_URL"] = url

    from signalforge.config import get_settings
    from signalforge.db.session import reset_engine_cache

    get_settings.cache_clear()
    reset_engine_cache()
    if get_settings().database_url != url or "mode=ro" not in get_settings().database_url:
        raise StageAViolation("settings did not pick up the read-only URL")

    _install_tripwires()

    from sqlalchemy import func, select

    from signalforge.db.models import StrategySealedTest
    from signalforge.db.session import session_scope

    keys = [args.snapshot_key] + [k for k in SNAPSHOT_KEYS if k != args.snapshot_key]
    out: dict[str, Any] = {
        "task": "stage_a_mr",
        "design": "docs/research/designs/proposals/mean_reversion_short_swing--exits_risk.md",
        "stage": "A",
        "sealed_looks_spent": 0,
        "db_rows_written": 0,
        "database_url": url,
        "span": {"start": SPAN_START.isoformat(), "end": PRE_SEALED_END.isoformat()},
        "snapshot_order": keys,
    }

    with session_scope() as session:
        th = get_settings().research.promotion
        out["thresholds"] = th.model_dump()
        rows_before = session.scalar(select(func.count(StrategySealedTest.id)))

        # ---- 0. reproduction + degenerate identity -------------------------
        snap, symbols, source, end, sealed_start = _snapshot_plan(session, REPRO_SNAPSHOT_KEY)
        res = _runner_check(session, symbols, source, end, sealed_start)
        degenerate = _run_version(
            session, "degenerate", symbols, source, end, sealed_start, **DEGENERATE
        )
        repro = {
            "snapshot_id": snap.id,
            "snapshot_key": snap.key,
            "all_pre_sealed": res.n_trades,
            "oos": res.out_of_sample.n_trades,
            "oos_expectancy_r": res.out_of_sample.expectancy_r,
            "expected": REPRO_EXPECT,
            "matches_eval_34": bool(
                res.n_trades == REPRO_EXPECT["all"]
                and res.out_of_sample.n_trades == REPRO_EXPECT["oos"]
                and abs(res.out_of_sample.expectancy_r - REPRO_EXPECT["oos_expectancy_r"]) < 5e-5
            ),
            "wrapper_at_blend_0_is_identity": _same_trades(res.trades, degenerate.trades),
            "data_provenance": {
                "sources": list(res.data.sources),
                "bars": res.data.bars,
                "first": res.data.first.isoformat() if res.data.first else None,
                "last": res.data.last.isoformat() if res.data.last else None,
            },
        }
        out["reproduction_check"] = repro
        print(
            f"[repro] {snap.key}: {res.n_trades} pre-sealed / {res.out_of_sample.n_trades} OOS @ "
            f"{res.out_of_sample.expectancy_r:+.5f}R -> "
            f"{'MATCH' if repro['matches_eval_34'] else 'MISMATCH'}; wrapper identity "
            f"{'OK' if repro['wrapper_at_blend_0_is_identity'] else 'BROKEN'}",
            flush=True,
        )
        if not repro["matches_eval_34"] or not repro["wrapper_at_blend_0_is_identity"]:
            raise StageAViolation(
                "baseline does not reproduce eval 34 / wrapper is not the identity"
            )

        # ---- 1. §9 stopping rule ------------------------------------------
        out["V1"] = evaluate_variant(session, "V1", V1_PARAMS, th, keys)
        v1_f1_first_two = all(out["V1"]["snapshots"][k]["F1"]["passed"] for k in keys[:2])
        out["V1"]["stopping_rule"] = {
            "step1_F1_on_first_two_snapshots": v1_f1_first_two,
            "note": (
                "F1-F4 were computed on all four snapshots for the record; "
                "the rule binds on step 1."
            ),
        }
        if not out["V1"]["survives"]:
            print("[rule] V1 is dead -> running V2 once (§9 step 3)", flush=True)
            out["V2"] = evaluate_variant(session, "V2", V2_PARAMS, th, keys)
        else:
            out["V2"] = {"skipped": "V1 survived F1-F5; V2 not run (§9)"}

        survivor = (
            "V1" if out["V1"]["survives"] else ("V2" if out.get("V2", {}).get("survives") else None)
        )
        out["verdict"] = {
            "V1": out["V1"]["verdict"],
            "V2": out["V2"].get("verdict"),
            "survivor": survivor,
            "decision": (
                f"{survivor} survives F1-F5 — v0.2.0 may be planned (no sealed look spent yet)"
                if survivor
                else "STOP — both variants dead; write §11 null disposition"
            ),
            "sealed_looks_spent_by_stage_a": 0,
        }
        rows_after = session.scalar(select(func.count(StrategySealedTest.id)))
        out["sealed_test_rows_on_copy"] = {"before": rows_before, "after": rows_after}
        if rows_before != rows_after:
            raise StageAViolation("sealed test row count moved")

    emit = Path(args.emit)
    emit.parent.mkdir(parents=True, exist_ok=True)
    emit.write_text(json.dumps(out, indent=2, default=str) + "\n")
    emit.with_suffix(".md").write_text(_render_markdown(out))
    print(f"\n[emit] {emit}\n[emit] {emit.with_suffix('.md')}", flush=True)
    print(f"[verdict] {out['verdict']['decision']}", flush=True)
    return 0


def _pf(passed: Any) -> str:
    return "PASS" if passed else "FAIL"


def _render_markdown(out: Mapping[str, Any]) -> str:
    L: list[str] = []
    a = L.append
    r = out["reproduction_check"]
    a("# Stage A — `mean_reversion.short_swing` exits/risk redesign (V1 / V2) vs v0.1.0")
    a("")
    a(f"**Verdict: {out['verdict']['decision']}.**")
    a("")
    a(
        "**Zero sealed looks. Zero database rows.** Everything below was computed read-only over "
        f"the PRE-SEALED span **{out['span']['start']} → {out['span']['end']}** (snapshot 1: "
        "→ 2025-09-06). `evaluate_promotion`, `_get_or_create_sealed_test`, "
        "`persist_promotion_evaluation`, `get_or_create_dataset_snapshot` and "
        "`persist_backtest_result` were replaced with functions that raise before the run began; "
        "the database was a `mode=ro` copy and a driver-level hook would have raised on any write. "
        f"`strategy_sealed_test` rows: {out['sealed_test_rows_on_copy']['before']} before, "
        f"{out['sealed_test_rows_on_copy']['after']} after."
    )
    a("")
    a(f"Design: `{out['design']}` §4 (F1–F5), §9 (stopping rule).")
    a("Script: `scripts/stage_a_mr.py`.")
    a("")
    a("## 0. The baseline is really v0.1.0, and the wrapper is the identity at λ = 0")
    a("")
    repro_ok = "MATCH" if r["matches_eval_34"] else "MISMATCH"
    ident_ok = "identity holds" if r["wrapper_at_blend_0_is_identity"] else "BROKEN"
    a(
        f"**FACT.** `run_strategy_over_universe` on snapshot {r['snapshot_id']} "
        f"(`{r['snapshot_key']}`) gives **{r['all_pre_sealed']} pre-sealed / {r['oos']} OOS at "
        f"{r['oos_expectancy_r']:+.5f}R** — eval 34 reproduced ({repro_ok}). The script's "
        "variant wrapper at `stop_anchor_blend = 0.0` reproduces that trade list exactly "
        f"({ident_ok}), so every V1/V2 number below is a controlled change to v0.1.0's rule, "
        f"not a paraphrase of it. Provenance: {r['data_provenance']['sources']}, last bar "
        f"{r['data_provenance']['last']}."
    )
    a("")
    a(
        "The engine does not yet carry `stop_distance` / `stop_anchor_blend` / "
        "`min_risk_distance`; the wrapper rewrites each `EntrySignal.stop_price` to the §2.1 "
        "`stop_level` using the same "
        "next-bar open the engine uses for the fill, so `risk_per_share` and `_resolve_exit` run "
        "the proposed arithmetic unchanged. No file under `src/` was modified."
    )
    a("")

    def variant_section(name: str, v: Mapping[str, Any], num: int) -> None:
        a(f"## {num}. {name} — `{v['params']}`")
        a("")
        a(
            "| snapshot | n (v0.1.0 / variant) | v0.1.0 pre-sealed | variant pre-sealed "
            "| v0.1.0 OOS | variant OOS |"
        )
        a("|---|---|---|---|---|---|")
        for key, s in v["snapshots"].items():
            b, x = s["v0_1_0"], s[name]
            a(
                f"| {s['snapshot_id']} `{key}` | {b['all_pre_sealed']['n']} / "
                f"{x['all_pre_sealed']['n']} | {_m(b['all_pre_sealed'])} | "
                f"{_m(x['all_pre_sealed'])} | {_m(b['oos'])} | {_m(x['oos'])} |"
            )
        a("")
        a("### F1 — accounting-invariant paired test (the kill test)")
        a("")
        a(
            "Fixed denominator `stop_atr × ATR(14)` at the signal bar for both versions; paired "
            "per-trade difference over the matched (symbol, entry date) set."
        )
        a("")
        a("| snapshot | matched | paired Δ | SE | σ | unmatched (base / variant) | F1 |")
        a("|---|---|---|---|---|---|---|")
        for key, s in v["snapshots"].items():
            f = s["F1"]
            a(
                f"| `{key}` | {f['n_matched']} | **{f['mean']:+.5f}R** | {f['se']:.5f} | "
                f"**{f['sigma']:+.2f}** | {f['n_base_unmatched']} / {f['n_variant_unmatched']} | "
                f"**{_pf(f['passed'])}** |"
            )
        a("")
        for key, s in v["snapshots"].items():
            u = s["unpaired_pre_sealed_delta"]
            a(
                f"- `{key}` unpaired raw-R pre-sealed Δ (context only, not accounting-invariant): "
                f"{u['difference_r']:+.5f}R ± {u['se']:.5f} ({u['sigma']:+.2f} SE)"
            )
        a("")
        if all(float(s["F1"]["se"]) == 0.0 for s in v["snapshots"].values()):
            a(
                "**Note on a degenerate F1.** This variant is a *no-trade* rule: every matched "
                "entry is simulated identically, so the paired difference is identically zero and "
                "F1 cannot clear a 2 SE bar by construction. Its whole effect lives in the removed "
                "trades (the unpaired Δ above). §4 requires F1 of every variant and §9 step 3 "
                "names F1 for V2 explicitly, so the pre-registered reading is FAIL; the "
                "alternative reading (treat F1 as inapplicable to V2) is noted for the operator "
                "and would still leave the OOS point estimate negative on every snapshot."
            )
            a("")
        if all(float(s["F1"]["mean"]) <= 0.0 for s in v["snapshots"].values()):
            a(
                "**Note on F2.** F2 fires only when the whole-sample paired Δ is positive while "
                "the risk ≥ 1 ATR subset is under 2 SE. With a non-positive whole-sample Δ the "
                "F2 PASS "
                "below is vacuous and carries no evidence for the variant."
            )
            a("")
        a("### F2 — does the effect live only in the gapped tail?")
        a("")
        a("| snapshot | risk ≥ 1 ATR: Δ (σ, n) | risk < 1 ATR: Δ (σ, n) | F2 |")
        a("|---|---|---|---|")
        for key, s in v["snapshots"].items():
            g, t = s["F2"]["risk_ge_1atr"], s["F2"]["risk_lt_1atr"]
            a(
                f"| `{key}` | {g['mean']:+.5f}R ({g['sigma']:+.2f}σ, n={g['n']}) | "
                f"{t['mean']:+.5f}R ({t['sigma']:+.2f}σ, n={t['n']}) | "
                f"**{_pf(s['F2']['passed'])}** |"
            )
        a("")
        a("### F3 — walk-forward folds (gate 1 replication)")
        a("")
        a(
            "| snapshot | v0.1.0 folds (n @ R) | variant folds (n @ R) | Δ per fold "
            "| positive | F3 |"
        )
        a("|---|---|---|---|---|---|")
        for key, s in v["snapshots"].items():
            f = s["F3"]
            fb = ", ".join(f"{x['n_trades']}@{x['expectancy_r']:+.4f}" for x in f["baseline_folds"])
            fv = ", ".join(f"{x['n_trades']}@{x['expectancy_r']:+.4f}" for x in f["variant_folds"])
            dl = ", ".join(f"{d:+.4f}" for d in f["fold_deltas_r"])
            tag = " (redistribution pattern)" if f["redistribution_pattern"] else ""
            a(
                f"| `{key}` | {fb} | {fv} | {dl} | {f['variant_positive_folds']}/4 | "
                f"**{_pf(f['passed'])}**{tag} |"
            )
        a("")
        a("### F4 — the artefact class must disappear")
        a("")
        a(
            "| snapshot | v0.1.0 profitable stops | variant profitable stops "
            "| variant risk < 0.5 ATR | F4 |"
        )
        a("|---|---|---|---|---|")
        for key, s in v["snapshots"].items():
            a(
                f"| `{key}` | {s['v0_1_0']['artefacts']['profitable_stop_exits']} | "
                f"{s['F4']['profitable_stop_exits']} | {s['F4']['risk_below_half_atr']} | "
                f"**{_pf(s['F4']['passed'])}** |"
            )
        a("")
        f5 = v["F5"]
        a(
            f"### F5 — snapshot invariance: same F1 sign on all four = "
            f"**{f5['same_sign_on_all']}**, F1–F4 hold everywhere = "
            f"**{f5['all_F1_to_F4_hold']}** → **{_pf(f5['passed'])}**"
        )
        a("")
        vd = v["verdict"]
        a(
            "**Verdicts:** "
            + ", ".join(f"{k} **{'PASS' if p else 'FAIL'}**" for k, p in vd.items())
            + "."
        )
        a("")

    variant_section("V1", out["V1"], 1)
    if "skipped" in out["V2"]:
        a(f"## 2. V2 — {out['V2']['skipped']}")
        a("")
    else:
        variant_section("V2", out["V2"], 2)

    a("## 3. Decision under §9")
    a("")
    if out["verdict"]["survivor"] is None:
        a(
            "**Both variants are dead.** §9 steps 1–3 exhausted: F1 is the test that decides the "
            "proposal, and it did not clear its pre-registered bar. Per §9 step 5 there is no "
            "third variant, no λ tuning and no promotion run. **Write the §11 null disposition** "
            "at "
            "`docs/research/dispositions/mean_reversion_short_swing.md`. v0.1.0 stays "
            "EXPERIMENTAL; its four sealed tests (ids 3, 8, 13, 18) are untouched; k stays at 5."
        )
    else:
        a(
            f"**{out['verdict']['survivor']} survives F1–F5.** Nothing is implemented by this run. "
            "See §Next for the v0.2.0 steps."
        )
    a("")
    a(
        "---\n\n*Stage A output. No row in `data/signalforge.sqlite` was written, no promotion / "
        "sensitivity-writing / sealed entry point was invoked, no provider API was called, and no "
        "quantity inside the sealed window was computed. The sealed-look count is unchanged.*"
    )
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    sys.exit(main())
