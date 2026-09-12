#!/usr/bin/env python
"""Stage A for ``volatility_breakout.short_swing`` v0.2.0 — ZERO sealed looks, ZERO DB rows.

Implements §12.5 and §12.7 of
``docs/research/designs/volatility_breakout_short_swing.md``.

Everything here is READ-ONLY by construction and by tripwire:

* it runs against a **backup copy** of the live database, opened through a
  ``mode=ro`` URI, so SQLite itself refuses a write;
* :func:`_install_tripwires` replaces ``evaluate_promotion``,
  ``_get_or_create_sealed_test`` and ``persist_promotion_evaluation`` with
  functions that raise, so a sealed entry point cannot be reached even by
  accident through an import this script does not make itself;
* a SQLAlchemy ``before_cursor_execute`` hook raises on any INSERT / UPDATE /
  DELETE / CREATE / DROP that reaches the driver;
* :func:`_assert_pre_sealed` re-checks every trade date and the run's own data
  provenance against ``PRE_SEALED_END`` (2025-09-07), so no quantity inside the
  sealed window 2025-09-08 → 2026-09-08 is ever computed.

The evidence itself is produced by ``research.backtest_runner`` and
``research.sensitivity`` — the real pipeline functions gates 1-8 use, neither of
which writes — so Stage A measures exactly what a promotion run would measure,
without minting anything.

Usage::

    export DATABASE_URL="sqlite+pysqlite:///file:$TMPDIR/scratch-v6.sqlite?mode=ro&uri=true"
    python scripts/stage_a_v6.py \\
        --snapshot-key research_150_massive_10y_presealed_sel \\
        --source massive \\
        --emit docs/research/designs/scripts/volatility_breakout_short_swing/stage_a.json
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import numpy as np

# --------------------------------------------------------------------------- #
# pre-registered constants — §12.1. NOTHING here may be changed by a result.
# --------------------------------------------------------------------------- #
SPAN_START = date(2016, 9, 10)
PRE_SEALED_END = date(2025, 9, 7)  # nothing at or after 2025-09-08 is computed
SEALED_WINDOW_START = date(2025, 9, 8)

# K3b's SE convention, fixed in the design before any expanded-snapshot number
# existed (v6_regime_power.md §6.1). Measuring the factor on this run's own
# data and then applying it would be choosing the SE afterwards.
CLUSTER_SE_FACTOR = 1.638
K3B_SE_BAR = 2.0

# §8: round trip bps = 2 * (slippage_bps + spread_bps/2) = 6 + spread_bps at
# CostModel defaults. The four mandatory re-pricings, plus the frozen baseline.
SPREAD_REPRICINGS: tuple[tuple[float, float], ...] = (
    (5.0, 11.0),  # frozen — what the gates actually use
    (10.0, 16.0),  # "2x" under W1 §7.1's reading
    (20.0, 26.0),  # MAP §0.4 / §3(a) "2x"
    (25.0, 31.0),  # "5x" under W1 §7.1's reading
    (60.0, 66.0),  # MAP §0.4 / §3(a) "5x"
)

BOOTSTRAP_RESAMPLES = 2_000
BOOTSTRAP_SEED = 20240101  # backtest/montecarlo.py:18-19, used everywhere else

# The snapshot-3 figures the degenerate cell must reproduce before anything
# else is believed (§0.4, §2.3).
REPRO_SNAPSHOT_ID = 3
REPRO_EXPECT = {"all": 211, "oos": 51, "oos_expectancy_r": 0.06135}

DEGENERATE = {"squeeze_lag": 0, "release_min": 0.0}  # == v0.1.0, exactly


# --------------------------------------------------------------------------- #
# read-only tripwires
# --------------------------------------------------------------------------- #
class StageAViolation(RuntimeError):
    """A Stage A invariant was broken. Always fatal: never caught, never warned."""


def _install_tripwires() -> None:
    """Make the forbidden entry points raise, and make any write SQL raise."""
    from sqlalchemy import event
    from sqlalchemy.engine import Engine

    from signalforge.research import promotion as _promo

    def _forbidden(name: str) -> Callable[..., Any]:
        def _raise(*_a: Any, **_k: Any) -> Any:
            raise StageAViolation(
                f"Stage A called {name}() — this is a sealed/writing entry point and "
                f"Stage A is pre-registered at zero looks and zero rows (§0.1(2), §12.5)."
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

    writes = ("insert", "update", "delete", "create", "drop", "alter", "replace")

    @event.listens_for(Engine, "before_cursor_execute")
    def _no_writes(  # type: ignore[no-untyped-def]
        conn, cursor, statement, parameters, context, executemany
    ) -> None:
        head = statement.lstrip().split(None, 1)
        if head and head[0].lower() in writes:
            raise StageAViolation(f"Stage A attempted a write: {statement[:160]!r}")


def _assert_pre_sealed(label: str, trades: Sequence[Any], provenance: Any = None) -> None:
    """No bar dated on or after 2025-09-08 may contribute to anything."""
    for tr in trades:
        for field_name in ("entry_date", "exit_date"):
            d = getattr(tr, field_name)
            d = d.date() if hasattr(d, "date") else d
            if d >= SEALED_WINDOW_START:
                raise StageAViolation(
                    f"{label}: trade {tr.symbol} has {field_name}={d}, inside the sealed window"
                )
    if (
        provenance is not None
        and provenance.last is not None
        and provenance.last >= SEALED_WINDOW_START
    ):
        raise StageAViolation(
            f"{label}: data provenance last bar {provenance.last} is inside the sealed window"
        )


# --------------------------------------------------------------------------- #
# statistics
# --------------------------------------------------------------------------- #
def _moments(xs: Sequence[float]) -> dict[str, float | int]:
    """n, mean, sample sd, SE. Sample sd (ddof=1) because these are estimates."""
    n = len(xs)
    if n == 0:
        return {"n": 0, "mean": 0.0, "sd": 0.0, "se": 0.0}
    if n == 1:
        return {"n": 1, "mean": float(xs[0]), "sd": 0.0, "se": 0.0}
    mean = statistics.fmean(xs)
    sd = statistics.stdev(xs)
    return {"n": n, "mean": mean, "sd": sd, "se": sd / math.sqrt(n)}


def _iid_bootstrap_ci(xs: Sequence[float]) -> dict[str, float]:
    """The same construction gate 4 uses (montecarlo.bootstrap_ci), reported here
    with the half-width so it can be compared to the clustered form."""
    if not xs:
        return {"low": 0.0, "point": 0.0, "high": 0.0, "half_width": 0.0, "se_boot": 0.0}
    arr = np.asarray(xs, dtype=np.float64)
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    idx = rng.integers(0, arr.size, size=(BOOTSTRAP_RESAMPLES, arr.size))
    means = arr[idx].mean(axis=1)
    lo, hi = float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))
    return {
        "low": lo,
        "point": float(arr.mean()),
        "high": hi,
        "half_width": (hi - lo) / 2.0,
        "se_boot": float(means.std(ddof=1)),
    }


def _clustered_bootstrap_ci(xs: Sequence[float], keys: Sequence[Any]) -> dict[str, float | int]:
    """Non-overlapping cluster bootstrap: whole clusters resampled with
    replacement, never re-ordered or shortened (clustered_bootstrap_all.md §2).
    Same 2,000 resamples / seed 20240101 / percentile method as the iid form."""
    if not xs:
        return {"low": 0.0, "point": 0.0, "high": 0.0, "half_width": 0.0, "se_boot": 0.0, "G": 0}
    buckets: dict[Any, list[float]] = {}
    for x, k in zip(xs, keys, strict=True):
        buckets.setdefault(k, []).append(x)
    groups = [np.asarray(v, dtype=np.float64) for _, v in sorted(buckets.items())]
    g = len(groups)
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    means = np.empty(BOOTSTRAP_RESAMPLES, dtype=np.float64)
    for b in range(BOOTSTRAP_RESAMPLES):
        pick = rng.integers(0, g, size=g)
        means[b] = float(np.concatenate([groups[i] for i in pick]).mean())
    lo, hi = float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))
    return {
        "low": lo,
        "point": float(np.concatenate(groups).mean()),
        "high": hi,
        "half_width": (hi - lo) / 2.0,
        "se_boot": float(means.std(ddof=1)),
        "G": g,
    }


def _month(d: Any) -> str:
    d = d.date() if hasattr(d, "date") else d
    return f"{d.year:04d}-{d.month:02d}"


# --------------------------------------------------------------------------- #
# the universe run
# --------------------------------------------------------------------------- #
def _params(overrides: Mapping[str, Any]) -> Any:
    from signalforge.research.strategies.breakout import BreakoutParams

    return BreakoutParams(**overrides)


def _strategy(overrides: Mapping[str, Any]) -> Any:
    from signalforge.domain import Horizon
    from signalforge.research.strategies.breakout import VolatilityBreakout

    return VolatilityBreakout(Horizon.SHORT_SWING, _params(overrides))


def _run(
    session: Any,
    overrides: Mapping[str, Any],
    symbols: Sequence[str],
    source: str,
    *,
    label: str,
) -> Any:
    from signalforge.research.backtest_runner import run_strategy_over_universe

    res = run_strategy_over_universe(
        session,
        _strategy(overrides),
        list(symbols),
        SPAN_START,
        PRE_SEALED_END,
        source=source,
    )
    _assert_pre_sealed(label, res.trades, res.data)
    return res


def _split_trades(session: Any, overrides: Mapping[str, Any], symbols: Sequence[str], source: str):
    """Re-derive the per-symbol IS/OOS split the runner performs, so every later
    slice (per class, per month, per symbol, re-pricing) uses the SAME boundary
    the headline numbers used. Mirrors backtest_runner._is_boundary exactly."""
    from signalforge.backtest.engine import run_backtest
    from signalforge.data.series import PriceSeries
    from signalforge.research.backtest_runner import DEFAULT_PROXY, _as_date, _is_boundary
    from signalforge.research.regime import regime_lookup
    from signalforge.research.strategies.base import signal_fn_for

    proxy = PriceSeries.load(session, DEFAULT_PROXY, SPAN_START, PRE_SEALED_END, source=source)
    regimes = regime_lookup(proxy) if len(proxy) else {}
    fn = signal_fn_for(_strategy(overrides), regime_by_date=regimes, allow_short=False)

    out: dict[str, dict[str, Any]] = {}
    for sym in symbols:
        series = PriceSeries.load(session, sym, SPAN_START, PRE_SEALED_END, source=source)
        if len(series) < 60:
            continue
        outcome = run_backtest(series, fn, warmup=30)
        boundary = _as_date(_is_boundary(series))
        oos = [t for t in outcome.trades if _as_date(t.entry_date) > boundary]
        out[sym] = {
            "boundary": boundary,
            "all": list(outcome.trades),
            "oos": oos,
            "first_bar": series.dates[0],
            "last_bar": series.dates[-1],
            "bars": len(series),
        }
    return out


def _reprice(
    session: Any,
    overrides: Mapping[str, Any],
    symbols: Sequence[str],
    source: str,
    spread_bps: float,
):
    """Re-run at a different quoted spread. ``run_strategy_over_universe`` never
    overrides ``spread_bps`` (backtest_runner.py), so the only faithful way to
    re-price is to drive ``run_backtest`` directly with the same warm-up,
    cost model and per-symbol IS/OOS boundary it uses."""
    from signalforge.backtest.engine import run_backtest
    from signalforge.data.series import PriceSeries
    from signalforge.research.backtest_runner import DEFAULT_PROXY, _as_date, _is_boundary
    from signalforge.research.regime import regime_lookup
    from signalforge.research.strategies.base import signal_fn_for

    proxy = PriceSeries.load(session, DEFAULT_PROXY, SPAN_START, PRE_SEALED_END, source=source)
    regimes = regime_lookup(proxy) if len(proxy) else {}
    fn = signal_fn_for(_strategy(overrides), regime_by_date=regimes, allow_short=False)

    all_r: list[float] = []
    oos_r: list[float] = []
    for sym in symbols:
        series = PriceSeries.load(session, sym, SPAN_START, PRE_SEALED_END, source=source)
        if len(series) < 60:
            continue
        outcome = run_backtest(series, fn, spread_bps=spread_bps, warmup=30)
        boundary = _as_date(_is_boundary(series))
        for tr in outcome.trades:
            all_r.append(tr.pnl_r)
            if _as_date(tr.entry_date) > boundary:
                oos_r.append(tr.pnl_r)
    return all_r, oos_r


# --------------------------------------------------------------------------- #
# per-version evidence block (§12.7)
# --------------------------------------------------------------------------- #
def _classify(symbols: Sequence[str], etfs: Sequence[str]) -> dict[str, str]:
    et = set(etfs)
    return {s: ("etf" if s in et else "single_name") for s in symbols}


def _version_block(
    session: Any,
    name: str,
    overrides: Mapping[str, Any],
    symbols: Sequence[str],
    source: str,
    etfs: Sequence[str],
) -> dict[str, Any]:
    t0 = time.time()
    res = _run(session, overrides, symbols, source, label=name)
    per_symbol = _split_trades(session, overrides, symbols, source)

    all_trades = [t for v in per_symbol.values() for t in v["all"]]
    oos_trades = [t for v in per_symbol.values() for t in v["oos"]]

    # The re-derived split must agree with the runner's own, or every slice below
    # is measuring something the headline numbers are not.
    if len(all_trades) != res.n_trades or len(oos_trades) != res.out_of_sample.n_trades:
        raise StageAViolation(
            f"{name}: re-derived split {len(all_trades)}/{len(oos_trades)} disagrees with "
            f"run_strategy_over_universe {res.n_trades}/{res.out_of_sample.n_trades}"
        )

    cls = _classify(symbols, etfs)
    oos_r = [t.pnl_r for t in oos_trades]
    all_r = [t.pnl_r for t in all_trades]
    oos_months = [_month(t.entry_date) for t in oos_trades]
    # SimTrade is a mutable slots dataclass and therefore unhashable: identify
    # the OOS subset by object identity, never by value.
    oos_ids = {id(t) for t in oos_trades}
    is_r = [t.pnl_r for t in all_trades if id(t) not in oos_ids]

    by_class: dict[str, Any] = {}
    for k in ("etf", "single_name"):
        sel_o = [t.pnl_r for t in oos_trades if cls.get(t.symbol) == k]
        sel_a = [t.pnl_r for t in all_trades if cls.get(t.symbol) == k]
        by_class[k] = {"oos": _moments(sel_o), "all_pre_sealed": _moments(sel_a)}

    block: dict[str, Any] = {
        "label": name,
        "params": dict(asdict(_params(overrides))),
        "version_string": res.spec.version,
        "elapsed_s": round(time.time() - t0, 1),
        "oos": _moments(oos_r),
        "all_pre_sealed": _moments(all_r),
        "in_sample": _moments(is_r),
        "oos_ci_iid": _iid_bootstrap_ci(oos_r),
        "oos_ci_month_clustered": _clustered_bootstrap_ci(oos_r, oos_months),
        "by_class": by_class,
        "per_symbol_trades": {s: len(v["all"]) for s, v in sorted(per_symbol.items())},
        "per_symbol_oos_trades": {s: len(v["oos"]) for s, v in sorted(per_symbol.items())},
        "per_symbol_boundary": {
            s: {
                "is_oos_boundary": v["boundary"].isoformat(),
                "first_bar": v["first_bar"].isoformat(),
                "last_bar": v["last_bar"].isoformat(),
                "bars": v["bars"],
            }
            for s, v in sorted(per_symbol.items())
        },
        "symbols_with_data": len(per_symbol),
        "data_provenance": {
            "sources": list(res.data.sources),
            "simulated": res.data.simulated,
            "bars": res.data.bars,
            "first": res.data.first.isoformat() if res.data.first else None,
            "last": res.data.last.isoformat() if res.data.last else None,
        },
        "costs_label": res.costs_label,
    }
    block["_trades"] = {"all": all_trades, "oos": oos_trades, "per_symbol": per_symbol}
    return block


# --------------------------------------------------------------------------- #
# gate replications (read-only)
# --------------------------------------------------------------------------- #
def _gate1_folds(all_trades: Sequence[Any], thresholds: Any) -> dict[str, Any]:
    """promotion.py gate 1, reproduced exactly."""
    from signalforge.research.portfolio_metrics import compute_portfolio_metrics

    span_days = (PRE_SEALED_END - SPAN_START).days
    n_folds = thresholds.min_walkforward_folds
    rows = []
    for k in range(n_folds):
        lo = SPAN_START + timedelta(days=span_days * k // n_folds)
        hi = SPAN_START + timedelta(days=span_days * (k + 1) // n_folds)
        ft = [t for t in all_trades if lo <= t.entry_date < hi]
        pm = compute_portfolio_metrics(ft, span_start=lo, span_end=hi)
        rows.append(
            {
                "fold": k + 1,
                "start": lo.isoformat(),
                "end": hi.isoformat(),
                "n_trades": pm.n_trades,
                "expectancy_r": pm.avg_trade_r,
                "sharpe": pm.sharpe,
            }
        )
    with_edge = sum(
        1
        for f in rows
        if f["n_trades"] >= thresholds.sensitivity_min_grid_trades
        and f["expectancy_r"] > thresholds.min_net_expectancy_r
    )
    need = max(1, n_folds // 2)
    return {
        "folds": rows,
        "folds_with_trades": sum(1 for f in rows if f["n_trades"] > 0),
        "folds_with_edge": with_edge,
        "need": need,
        "passed": bool(len(rows) >= n_folds and with_edge >= need),
    }


def _gate6_census(
    session: Any, all_trades: Sequence[Any], source: str, thresholds: Any
) -> dict[str, Any]:
    """promotion.py gate 6's census, including the unbucketed/warm-up decomposition."""
    from signalforge.backtest.regime import label_regimes
    from signalforge.data.series import PriceSeries
    from signalforge.research.backtest_runner import DEFAULT_PROXY
    from signalforge.research.promotion import _regime_census

    proxy = PriceSeries.load(session, DEFAULT_PROXY, SPAN_START, PRE_SEALED_END, source=source)
    regimes = label_regimes(proxy) if len(proxy) else {}
    census = _regime_census(list(all_trades), regimes)
    covered = sum(1 for c in census.buckets.values() if c >= thresholds.min_trades_per_regime)
    return {
        "buckets": dict(census.buckets),
        "warmup": census.warmup,
        "no_proxy_bar": census.no_proxy_bar,
        "unlabelled": census.unlabelled,
        "unbucketed": census.unbucketed,
        "n_trades_considered": census.n_trades,
        "census_closes": census.closes,
        "min_trades_per_regime": thresholds.min_trades_per_regime,
        "regimes_covered": covered,
        "min_regimes_covered": thresholds.min_regimes_covered,
        "passed": bool(covered >= thresholds.min_regimes_covered),
    }


def _gate7(session: Any, all_trades: Sequence[Any], source: str, thresholds: Any) -> dict[str, Any]:
    """promotion.py gate 7 plus the sqrt(trades/year) identity disclosure (§5.7, A3)."""
    from signalforge.data.series import PriceSeries
    from signalforge.research.backtest_runner import DEFAULT_PROXY
    from signalforge.research.portfolio_metrics import compute_portfolio_metrics
    from signalforge.research.promotion import _benchmark_metrics

    proxy = PriceSeries.load(session, DEFAULT_PROXY, SPAN_START, PRE_SEALED_END, source=source)
    span = [d for d in proxy.dates if SPAN_START <= d <= PRE_SEALED_END]
    lo, hi = (span[0], span[-1]) if span else (SPAN_START, PRE_SEALED_END)
    pm = compute_portfolio_metrics(list(all_trades), span_start=lo, span_end=hi)
    bench = _benchmark_metrics(proxy, lo, hi)

    r = [t.pnl_r for t in all_trades]
    n = len(r)
    mean = statistics.fmean(r) if n else 0.0
    # portfolio_metrics.py uses the POPULATION sd (ddof=0) for this identity.
    sd_pop = math.sqrt(sum((x - mean) ** 2 for x in r) / n) if n else 0.0
    years = (hi - lo).days / 365.25
    tpy = n / years if years > 0 else 0.0
    quality = (mean / sd_pop) if sd_pop > 0 else 0.0
    return {
        "span": {"start": lo.isoformat(), "end": hi.isoformat(), "years": years},
        "strategy_sharpe": pm.sharpe,
        "benchmark_sharpe": bench["sharpe"],
        "passed": bool(
            (not thresholds.require_beat_benchmark_sharpe) or pm.sharpe > bench["sharpe"]
        ),
        "turnover_per_year": pm.turnover_per_year,
        "exposure": pm.exposure,
        "identity": {
            "per_trade_quality_mean_over_sd": quality,
            "trades_per_year": tpy,
            "sqrt_trades_per_year": math.sqrt(tpy) if tpy > 0 else 0.0,
            "reconstructed_sharpe": quality * math.sqrt(tpy) if tpy > 0 else 0.0,
            "note": (
                "portfolio_metrics.py:109-111 — sharpe = (mean/sd) * sqrt(trades_per_year). "
                "A pass driven by the second factor is a TURNOVER artefact, not evidence of "
                "edge quality (§5.7, approval A3)."
            ),
        },
    }


def _grid(session: Any, symbols: Sequence[str], source: str, thresholds: Any) -> dict[str, Any]:
    """The 81-cell gate-5 grid, through the real ``run_parameter_sensitivity``
    (which performs no writes) so the enumeration, the ``evaluable`` filter, the
    one-step ``neighbour`` test and the K5 axis-movement check are the pipeline's
    own, not a paraphrase."""
    from dataclasses import asdict as _asdict

    from signalforge.research.promotion import _sensitivity_plan
    from signalforge.research.sensitivity import run_parameter_sensitivity

    strat = _strategy({})
    plan = _sensitivity_plan(strat)
    if plan is None:
        raise StageAViolation("no sensitivity plan for volatility_breakout")
    factory, grid = plan
    if math.prod(len(v) for v in grid.values()) != 81:
        raise StageAViolation(f"grid is not 81 points: { {k: len(v) for k, v in grid.items()} }")

    rep = run_parameter_sensitivity(
        session,
        strategy_key=strat.spec().name,
        version=strat.spec().version,
        factory=factory,
        baseline_params=_asdict(strat.params),
        grid=grid,
        symbols=list(symbols),
        start=SPAN_START,
        end=PRE_SEALED_END,
        source=source,
        min_trades=thresholds.sensitivity_min_grid_trades,
        positive_fraction_min=thresholds.sensitivity_positive_fraction_min,
        neighbour_fraction_min=thresholds.sensitivity_neighbour_fraction_min,
    )
    d = rep.to_dict()
    d["axes"] = {k: list(v) for k, v in grid.items()}
    d["n_neighbours_evaluable"] = sum(
        1 for p in rep.grid if p.is_neighbour and p.n_trades >= rep.min_trades
    )
    d["n_neighbours_total"] = sum(1 for p in rep.grid if p.is_neighbour)
    d["passed"] = not rep.fragile
    d["K5_all_axes_move"] = bool(d["axis_moved"]) and all(d["axis_moved"].values())
    return d


# --------------------------------------------------------------------------- #
# sweeps
# --------------------------------------------------------------------------- #
def _leave_one_month_out(oos_trades: Sequence[Any]) -> dict[str, Any]:
    rows = []
    by_month: dict[str, list[float]] = {}
    for t in oos_trades:
        by_month.setdefault(_month(t.entry_date), []).append(t.pnl_r)
    pooled = [t.pnl_r for t in oos_trades]
    base = statistics.fmean(pooled) if pooled else 0.0
    for m, vals in sorted(by_month.items()):
        rest = [x for k, v in by_month.items() if k != m for x in v]
        mean = statistics.fmean(rest) if rest else 0.0
        rows.append({"dropped": m, "n_dropped": len(vals), "n_left": len(rest), "mean": mean})
    rows.sort(key=lambda r: r["mean"])
    return {
        "pooled_mean": base,
        "n_months": len(by_month),
        "worst": rows[:5],
        "best": rows[-5:],
        "min_mean": rows[0]["mean"] if rows else 0.0,
        "max_mean": rows[-1]["mean"] if rows else 0.0,
        "any_sign_flip": bool(rows and (rows[0]["mean"] <= 0 < base)),
    }


def _leave_one_symbol_out(oos_trades: Sequence[Any]) -> dict[str, Any]:
    rows = []
    by_sym: dict[str, list[float]] = {}
    for t in oos_trades:
        by_sym.setdefault(t.symbol, []).append(t.pnl_r)
    pooled = [t.pnl_r for t in oos_trades]
    base = statistics.fmean(pooled) if pooled else 0.0
    for s, vals in sorted(by_sym.items()):
        rest = [x for k, v in by_sym.items() if k != s for x in v]
        mean = statistics.fmean(rest) if rest else 0.0
        rows.append({"dropped": s, "n_dropped": len(vals), "n_left": len(rest), "mean": mean})
    rows.sort(key=lambda r: r["mean"])
    return {
        "pooled_mean": base,
        "n_symbols": len(by_sym),
        "worst": rows[:5],
        "best": rows[-5:],
        "min_mean": rows[0]["mean"] if rows else 0.0,
        "max_mean": rows[-1]["mean"] if rows else 0.0,
        "any_sign_flip": bool(rows and (rows[0]["mean"] <= 0 < base)),
    }


# --------------------------------------------------------------------------- #
# K3
# --------------------------------------------------------------------------- #
def _k3(e01: Mapping[str, Any], e02: Mapping[str, Any]) -> dict[str, Any]:
    """K3a (sign) and K3b (magnitude at 2.0 CLUSTERED SE, the pre-registered
    iid SE x 1.638). Both forms reported; the clustered one binds."""
    m1, m2 = e01["oos"], e02["oos"]
    diff = float(m2["mean"]) - float(m1["mean"])
    se_iid = math.sqrt(float(m1["se"]) ** 2 + float(m2["se"]) ** 2)
    se_clu = se_iid * CLUSTER_SE_FACTOR
    k3a = diff > 0.0
    k3b = bool(se_clu > 0 and diff / se_clu >= K3B_SE_BAR)
    return {
        "E01_oos_expectancy_r": float(m1["mean"]),
        "E01_n": int(m1["n"]),
        "E01_sd": float(m1["sd"]),
        "E01_se": float(m1["se"]),
        "E02_oos_expectancy_r": float(m2["mean"]),
        "E02_n": int(m2["n"]),
        "E02_sd": float(m2["sd"]),
        "E02_se": float(m2["se"]),
        "difference_r": diff,
        "se_difference_iid": se_iid,
        "se_difference_clustered": se_clu,
        "cluster_factor": CLUSTER_SE_FACTOR,
        "sigma_iid": (diff / se_iid) if se_iid > 0 else 0.0,
        "sigma_clustered": (diff / se_clu) if se_clu > 0 else 0.0,
        "K3a_passed": k3a,
        "K3b_passed": k3b,
        "K3b_bar_sigma": K3B_SE_BAR,
        "required_difference_at_bar": K3B_SE_BAR * se_clu,
    }


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--snapshot-key", required=True)
    ap.add_argument("--source", required=True)
    ap.add_argument("--emit", required=True, help="path to stage_a.json")
    ap.add_argument("--skip-grid", action="store_true", help="diagnostic only; never for a verdict")
    ap.add_argument(
        "--grid-json",
        default=None,
        help=(
            "checkpoint for the 81-cell grid, which is by far the slowest step. If the file "
            "exists it is loaded instead of recomputed; otherwise the grid is computed and "
            "written there immediately. The grid is a deterministic function of the code, the "
            "snapshot and the read-only data (S4), so reusing it is reuse, not a second look."
        ),
    )
    args = ap.parse_args(argv)

    _install_tripwires()

    from sqlalchemy import func, select

    from signalforge.backtest.costs import CostModel
    from signalforge.config import get_settings
    from signalforge.db.models import DataSnapshot, StrategySealedTest
    from signalforge.db.session import session_scope

    url = get_settings().database_url
    if "mode=ro" not in url:
        raise StageAViolation(
            f"DATABASE_URL is not a read-only URI ({url!r}). Stage A must run against a "
            f"read-only backup copy; the live DB is under a paper probation and a worker."
        )

    out: dict[str, Any] = {
        "task": "stage_a_v6",
        "design": "docs/research/designs/volatility_breakout_short_swing.md",
        "stage": "A",
        "sealed_looks_spent": 0,
        "db_rows_written": 0,
        "database_url": url,
        "span": {"start": SPAN_START.isoformat(), "end": PRE_SEALED_END.isoformat()},
        "sealed_window_untouched": f"{SEALED_WINDOW_START.isoformat()} .. 2026-09-08",
        "source": args.source,
    }

    with session_scope() as session:
        th = get_settings().research.promotion
        out["thresholds"] = th.model_dump()
        out["cost_model"] = asdict(CostModel())

        # ---- 0. reproduce the snapshot-3 baseline before believing anything --
        snap3 = session.get(DataSnapshot, REPRO_SNAPSHOT_ID)
        s3 = list(snap3.symbols_json)
        r3 = _run(session, DEGENERATE, s3, args.source, label="repro-snapshot-3")
        repro = {
            "snapshot_id": REPRO_SNAPSHOT_ID,
            "snapshot_key": snap3.key,
            "n_symbols": len(s3),
            "all_pre_sealed": r3.n_trades,
            "oos": r3.out_of_sample.n_trades,
            "oos_expectancy_r": r3.out_of_sample.expectancy_r,
            "expected": REPRO_EXPECT,
        }
        repro["matches"] = bool(
            r3.n_trades == REPRO_EXPECT["all"]
            and r3.out_of_sample.n_trades == REPRO_EXPECT["oos"]
            and abs(r3.out_of_sample.expectancy_r - REPRO_EXPECT["oos_expectancy_r"]) < 5e-5
        )
        out["reproduction_check"] = repro
        print(
            f"[repro] snapshot 3 degenerate cell: {r3.n_trades} pre-sealed / "
            f"{r3.out_of_sample.n_trades} OOS @ {r3.out_of_sample.expectancy_r:+.5f}R "
            f"-> {'MATCH' if repro['matches'] else 'MISMATCH'}",
            flush=True,
        )
        if not repro["matches"]:
            raise StageAViolation(
                "the degenerate cell does not reproduce v0.1.0's stored snapshot-3 result; "
                "E01 would not be a v0.1.0 baseline. Stop."
            )

        # ---- 1. the expanded snapshot ---------------------------------------
        snap = session.scalar(select(DataSnapshot).where(DataSnapshot.key == args.snapshot_key))
        if snap is None:
            raise StageAViolation(f"no DataSnapshot with key {args.snapshot_key!r}")
        symbols = list(snap.symbols_json)
        # W1-COMP: the 15 snapshot-3 ETFs verbatim + the top 135 common stocks.
        etfs = [s for s in s3 if s in {"DIA", "IWM", "QQQ", "SPY"} or s.startswith("XL")]
        if len(etfs) != 15 or not set(etfs) <= set(symbols):
            raise StageAViolation(
                f"expected W1-COMP's 15 ETFs inside the snapshot, got {len(etfs)}: {etfs}"
            )
        singles = [s for s in symbols if s not in set(etfs)]
        out["snapshot"] = {
            "id": snap.id,
            "key": snap.key,
            "n_symbols": len(symbols),
            "n_etfs": len(etfs),
            "n_single_names": len(singles),
            "etfs": etfs,
            "new_vs_snapshot_3": sorted(set(symbols) - set(s3)),
            "n_new_vs_snapshot_3": len(set(symbols) - set(s3)),
        }
        print(
            f"[snapshot] id={snap.id} key={snap.key} n={len(symbols)} "
            f"({len(etfs)} ETFs + {len(singles)} single names)",
            flush=True,
        )

        # ---- 2. E01 and E02 --------------------------------------------------
        print("[run] v0.1.0 (degenerate cell) over 150 symbols ...", flush=True)
        v010 = _version_block(session, "v0.1.0", DEGENERATE, symbols, args.source, etfs)
        print(
            f"       E01 OOS {v010['oos']['mean']:+.5f}R  n={v010['oos']['n']}  "
            f"sd={v010['oos']['sd']:.4f}  SE={v010['oos']['se']:.4f}  "
            f"({v010['elapsed_s']}s)",
            flush=True,
        )
        print("[run] v0.2.0 (defaults) over 150 symbols ...", flush=True)
        v020 = _version_block(session, "v0.2.0", {}, symbols, args.source, etfs)
        print(
            f"       E02 OOS {v020['oos']['mean']:+.5f}R  n={v020['oos']['n']}  "
            f"sd={v020['oos']['sd']:.4f}  SE={v020['oos']['se']:.4f}  "
            f"({v020['elapsed_s']}s)",
            flush=True,
        )

        tr010 = v010.pop("_trades")
        tr020 = v020.pop("_trades")
        out["v0_1_0"] = v010
        out["v0_2_0"] = v020

        # ---- 3. K3 -----------------------------------------------------------
        out["K3"] = _k3(v010, v020)
        print(
            f"[K3] diff {out['K3']['difference_r']:+.5f}R  "
            f"iid {out['K3']['sigma_iid']:.2f} SE  "
            f"clustered {out['K3']['sigma_clustered']:.2f} SE  "
            f"K3a={'PASS' if out['K3']['K3a_passed'] else 'FIRED'} "
            f"K3b={'PASS' if out['K3']['K3b_passed'] else 'FIRED'}",
            flush=True,
        )

        # ---- 4. gates 1/6/7 for both versions --------------------------------
        out["gates"] = {}
        for key, tr in (("v0_1_0", tr010), ("v0_2_0", tr020)):
            out["gates"][key] = {
                "gate1_walkforward": _gate1_folds(tr["all"], th),
                "gate6_regime": _gate6_census(session, tr["all"], args.source, th),
                "gate7_benchmark": _gate7(session, tr["all"], args.source, th),
            }
            print(f"[gates] {key}: 1/6/7 computed", flush=True)

        # ---- 5. the 81-cell grid (v0.2.0, the version gate 5 would judge) ----
        cache = Path(args.grid_json) if args.grid_json else None
        if args.skip_grid:
            out["gate5_grid"] = {"skipped": True}
        elif cache is not None and cache.exists():
            out["gate5_grid"] = json.loads(cache.read_text())
            print(f"[gate5] loaded the 81-cell grid from {cache}", flush=True)
        else:
            print("[gate5] 81-cell grid (this is the slow part) ...", flush=True)
            t0 = time.time()
            out["gate5_grid"] = _grid(session, symbols, args.source, th)
            if cache is not None:
                cache.parent.mkdir(parents=True, exist_ok=True)
                cache.write_text(json.dumps(out["gate5_grid"], indent=2, default=str) + "\n")
            print(
                f"        {out['gate5_grid']['n_evaluable']}/{out['gate5_grid']['n_points']} "
                f"evaluable, {out['gate5_grid']['positive_fraction']:.0%} positive, "
                f"neighbours {out['gate5_grid']['neighbour_positive_fraction']:.0%}, "
                f"K5 axes all move = {out['gate5_grid']['K5_all_axes_move']} "
                f"({time.time() - t0:.0f}s)",
                flush=True,
            )

        # ---- 6. sweeps -------------------------------------------------------
        out["sweeps"] = {
            "v0_1_0": {
                "leave_one_month_out": _leave_one_month_out(tr010["oos"]),
                "leave_one_symbol_out": _leave_one_symbol_out(tr010["oos"]),
            },
            "v0_2_0": {
                "leave_one_month_out": _leave_one_month_out(tr020["oos"]),
                "leave_one_symbol_out": _leave_one_symbol_out(tr020["oos"]),
            },
        }
        print("[sweeps] LOMO / LOSO computed", flush=True)

        # ---- 7. spread re-pricings ------------------------------------------
        out["spread_repricings"] = {}
        for key, ov in (("v0_1_0", DEGENERATE), ("v0_2_0", {})):
            rows = []
            for quoted, rt in SPREAD_REPRICINGS:
                a, o = _reprice(session, ov, symbols, args.source, quoted)
                rows.append(
                    {
                        "quoted_spread_bps": quoted,
                        "round_trip_bps": rt,
                        "oos": _moments(o),
                        "all_pre_sealed": _moments(a),
                    }
                )
                print(
                    f"[spread] {key} @ {rt:g} bps RT: OOS {rows[-1]['oos']['mean']:+.5f}R "
                    f"(n={rows[-1]['oos']['n']})",
                    flush=True,
                )
            out["spread_repricings"][key] = rows

        # ---- 8. the new-symbols-only runs ------------------------------------
        cs135 = [s for s in symbols if s not in set(etfs)]
        new126 = sorted(set(symbols) - set(s3))
        out["subuniverse_runs"] = {}
        for name, syms in (("single_names_135", cs135), ("new_vs_snapshot3_126", new126)):
            entry: dict[str, Any] = {"n_symbols": len(syms)}
            for key, ov in (("v0_1_0", DEGENERATE), ("v0_2_0", {})):
                per = _split_trades(session, ov, syms, args.source)
                _assert_pre_sealed(f"{name}/{key}", [t for v in per.values() for t in v["all"]])
                o = [t.pnl_r for v in per.values() for t in v["oos"]]
                a = [t.pnl_r for v in per.values() for t in v["all"]]
                entry[key] = {"oos": _moments(o), "all_pre_sealed": _moments(a)}
            entry["difference_r"] = entry["v0_2_0"]["oos"]["mean"] - entry["v0_1_0"]["oos"]["mean"]
            out["subuniverse_runs"][name] = entry
            print(
                f"[subuniverse] {name} (n={len(syms)}): "
                f"E01 {entry['v0_1_0']['oos']['mean']:+.5f}R / "
                f"E02 {entry['v0_2_0']['oos']['mean']:+.5f}R",
                flush=True,
            )

        # ---- 9. gate-by-gate forecast ---------------------------------------
        out["gate_forecast"] = _forecast(out, th)

        # ---- 10. verdict -----------------------------------------------------
        k3 = out["K3"]
        k5_ok = bool(out.get("gate5_grid", {}).get("K5_all_axes_move", False))
        stop = (not k3["K3a_passed"]) or (not k3["K3b_passed"]) or (not k5_ok)
        out["verdict"] = {
            "K3a_passed": k3["K3a_passed"],
            "K3b_passed": k3["K3b_passed"],
            "K5_passed": k5_ok,
            "decision": "STOP — write §11" if stop else "Stage B may be requested",
            "sealed_looks_spent_by_stage_a": 0,
        }

        # ---- 11. sealed-test row count, read-only ----------------------------
        out["sealed_test_rows_on_copy"] = session.scalar(select(func.count(StrategySealedTest.id)))

    Path(args.emit).parent.mkdir(parents=True, exist_ok=True)
    Path(args.emit).write_text(json.dumps(out, indent=2, default=str) + "\n")
    print(f"\n[emit] {args.emit}", flush=True)
    print(f"[verdict] {out['verdict']['decision']}", flush=True)
    return 0


def _forecast(out: Mapping[str, Any], th: Any) -> dict[str, Any]:
    """The gate-by-gate forecast on the expanded snapshot, for v0.2.0, computed
    from the read-only evidence. Gate 9 is NOT forecast: it is the sealed test
    Stage A refuses to buy."""
    v = out["v0_2_0"]
    g = out["gates"]["v0_2_0"]
    grid = out.get("gate5_grid", {})
    oos_n = int(v["oos"]["n"])
    exp = float(v["oos"]["mean"])
    ci_low = float(v["oos_ci_iid"]["low"])
    rows = {
        "gate1_rolling_walkforward": {
            "passed": g["gate1_walkforward"]["passed"],
            "detail": f"{g['gate1_walkforward']['folds_with_edge']} of "
            f"{len(g['gate1_walkforward']['folds'])} folds clear the floor and are positive "
            f"(need {g['gate1_walkforward']['need']})",
        },
        "gate2_min_oos_trades": {
            "passed": oos_n >= th.min_oos_trades,
            "detail": f"{oos_n} OOS trades vs threshold {th.min_oos_trades}",
        },
        "gate3_net_expectancy": {
            "passed": exp > th.min_net_expectancy_r,
            "detail": f"{exp:+.4f}R vs > {th.min_net_expectancy_r:+.4f}R",
        },
        "gate4_bootstrap_ci": {
            "passed": ci_low > th.min_bootstrap_ci_low_r,
            "detail": f"iid CI low {ci_low:+.4f}R vs > {th.min_bootstrap_ci_low_r:+.4f}R "
            f"(month-clustered low {v['oos_ci_month_clustered']['low']:+.4f}R)",
        },
        "gate5_parameter_sensitivity": {
            "passed": grid.get("passed"),
            "detail": f"{grid.get('n_evaluable')}/{grid.get('n_points')} evaluable, "
            f"{grid.get('positive_fraction')} positive, "
            f"{grid.get('neighbour_positive_fraction')} neighbours positive",
        },
        "gate6_regime_coverage": {
            "passed": g["gate6_regime"]["passed"],
            "detail": f"bull {g['gate6_regime']['buckets']['bull']}, "
            f"bear {g['gate6_regime']['buckets']['bear']}, "
            f"range {g['gate6_regime']['buckets']['range']}; "
            f"unbucketed {g['gate6_regime']['unbucketed']}",
        },
        "gate7_benchmark": {
            "passed": g["gate7_benchmark"]["passed"],
            "detail": f"Sharpe {g['gate7_benchmark']['strategy_sharpe']:+.2f} vs SPY "
            f"{g['gate7_benchmark']['benchmark_sharpe']:+.2f}; "
            f"turnover {g['gate7_benchmark']['turnover_per_year']:.1f}/yr",
        },
        "gate8_data_quality_and_leakage": {
            "passed": None,
            "detail": "not run in Stage A: validate_daily(persist=True) writes rows. The four "
            "v0.2.0 entry features are covered by LEAKAGE_FEATURE_CHECKS and are unit-tested "
            "in tests/research/test_breakout_v020.py.",
        },
        "gate9_sealed_test": {
            "passed": None,
            "detail": "NOT COMPUTED. This is the look Stage A exists to avoid (§0.1(2)).",
        },
    }
    return rows


if __name__ == "__main__":
    sys.exit(main())
