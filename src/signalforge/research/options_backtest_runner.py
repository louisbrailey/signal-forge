"""Segmentation and gate-facing reduction for the options engine (D2 §9, §12; D4 §5).

**Scope.** I-O3 builds the arithmetic core and the reductions that do not need a
strategy class.  The universe loop, persistence, and the append-only variant
ledger of D2 §14.3 land with the first strategy class (I-O5) and the gate wiring
(I-O4); nothing here writes to a database, and nothing here is wired into
``evaluate_promotion``.

What is here, and why each piece exists:

* **IS/OOS boundary reuse.**  The boundary is computed from the **underlying's**
  ``PriceSeries`` by the identical function the equity runner uses, so the options
  convention is the same function of the same data (D2 §12.3).  It is never
  derived from option-print dates (sparse, chain-dependent) or from cycle counts.
* **The pooling guard.**  ``R`` is max loss, and max loss is a property of the
  structure, so it varies by ~100x between a 5-wide vertical and a cash-secured
  put on the same underlying.  Map §5.1's "forbid pooling across structures"
  becomes a runtime precondition here, caught at the point where it would corrupt
  a statistic (D2 §9.5).
* **An explicit ``risk_fraction``.**  ``compute_portfolio_metrics`` defaults to
  ``0.005`` and **no** gate-path call site overrides it, while options R is a fixed
  structural dollar amount — against a $25,000 options paper account D2 §9.3's
  R = $390 is 1.56%, about 3x.  Passing ``R_dollars / start_equity`` makes the gate
  more faithful and *harder* to pass, which is exactly R4's carve-out.  It is still
  an approximation (the function compounds a fraction of *current* equity); the
  faithful fixed-dollar-R curve is a D3/D4 item.
* **The gate-6 / 6b census on ``backtest/regime.py``.**  D4 §11 hands D2 option (a)
  of §5.1a: label the options trades with the **same** function ``_regime_census``
  reads, so the partition the strategy trades on is the partition gate 6 counts.
  ``backtest/regime.py`` emits five non-warmup labels — ``range_bound`` plus four
  joint cells — and the range cell is **vol-unlabelled by construction**
  (``regime.py:59-62``), so it contributes to neither vol marginal.
* **The four-way (R basis x spread setting) surface.**  All four cells are
  reported; the gate binds on the worst, which by construction is ``R_incl`` at
  ``2x`` — the largest denominator against the smallest numerator.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime
from typing import cast

from signalforge.backtest.engine import SimTrade
from signalforge.backtest.metrics import Metrics, compute_metrics
from signalforge.backtest.montecarlo import bootstrap_ci
from signalforge.backtest.options_costs import OptionCostModel
from signalforge.backtest.options_engine import (
    OptionsBacktestOutcome,
    OptionsSignalFn,
    OptionTrade,
    RBasis,
    run_options_backtest,
)
from signalforge.backtest.regime import label_regimes
from signalforge.data.option_chain import OptionChainSeries
from signalforge.data.series import PriceSeries
from signalforge.research.backtest_runner import _is_boundary  # the EXACT equity convention
from signalforge.research.portfolio_metrics import PortfolioMetrics, compute_portfolio_metrics

#: The four labels ``backtest/regime.py`` emits that carry a volatility half.
JOINT_CELLS = ("bull_highvol", "bull_lowvol", "bear_highvol", "bear_lowvol")


def _as_date(x: date | datetime) -> date:
    return x.date() if isinstance(x, datetime) else x


def _as_sim_trades(trades: Sequence[OptionTrade]) -> Sequence[SimTrade]:
    """Structural compatibility, asserted once (D2 §12.1).

    ``compute_metrics`` reads ``.pnl_r`` and ``.bars_held``;
    ``compute_portfolio_metrics`` reads ``.entry_date``, ``.exit_date``, ``.pnl_r``
    and ``getattr(t, "bars_held", 0)``; ``_regime_census`` and the walk-forward fold
    assignment read ``.entry_date``.  :class:`OptionTrade` exposes all four, so the
    metrics stack runs unmodified.  The cast is the honest way to say that in a
    codebase where ``SimTrade`` is a concrete frozen dataclass rather than a
    Protocol — and ``SimTrade`` must not gain options fields (that would change
    ``spec_json_hash``'s neighbourhood and is the whole reason for the sibling).
    """
    return cast(Sequence[SimTrade], trades)


# ---------------------------------------------------------------------------
# IS / OOS segmentation (D2 §12.3)
# ---------------------------------------------------------------------------


def is_oos_boundary(underlying: PriceSeries) -> date:
    """The 60%-of-bars boundary date, from the underlying, via the equity function."""
    return _as_date(_is_boundary(underlying))


@dataclass(frozen=True, slots=True)
class SegmentedTrades:
    boundary: date
    in_sample: tuple[OptionTrade, ...]
    out_of_sample: tuple[OptionTrade, ...]


def split_is_oos(trades: Sequence[OptionTrade], boundary: date) -> SegmentedTrades:
    """Assign by entry date, ``<= boundary`` is in-sample (``backtest_runner.py:212``)."""
    is_trades = tuple(t for t in trades if _as_date(t.entry_date) <= boundary)
    oos_trades = tuple(t for t in trades if _as_date(t.entry_date) > boundary)
    return SegmentedTrades(boundary=boundary, in_sample=is_trades, out_of_sample=oos_trades)


# ---------------------------------------------------------------------------
# The pooling guard (D2 §9.5)
# ---------------------------------------------------------------------------


class MixedRStreams(ValueError):
    """More than one ``(structure_type, r_basis)`` pair reached one statistic."""


def assert_single_r_stream(trades: Sequence[OptionTrade]) -> None:
    """Raise before any statistic is computed over a pooled R stream.

    An equity +0.30R, a vertical +0.30R and a cash-secured put +0.30R are three
    different claims.  This is the cheapest possible implementation of gate 0.5
    (one structure type per strategy version).
    """
    pairs = {(t.structure_type, t.r_basis) for t in trades}
    if len(pairs) > 1:
        rendered = sorted(f"{s.value}/{b.value}" for s, b in pairs)
        raise MixedRStreams(
            "R is max loss and max loss is a property of the structure; refusing to "
            f"pool {rendered} into one statistic (D2 §9.5)"
        )


def options_risk_fraction(r_dollars: float, start_equity: float) -> float:
    """``R_dollars / start_equity`` — passed explicitly, never defaulted (D2 §12.1)."""
    if start_equity <= 0.0:
        raise ValueError("start_equity must be > 0")
    if r_dollars <= 0.0:
        raise ValueError("r_dollars must be > 0")
    return r_dollars / start_equity


def options_portfolio_metrics(
    trades: Sequence[OptionTrade],
    *,
    start_equity: float,
    r_dollars: float,
    span_start: date | None = None,
    span_end: date | None = None,
) -> PortfolioMetrics:
    """``compute_portfolio_metrics`` with an explicit, recorded ``risk_fraction``."""
    assert_single_r_stream(trades)
    return compute_portfolio_metrics(
        _as_sim_trades(trades),
        start_equity=start_equity,
        risk_fraction=options_risk_fraction(r_dollars, start_equity),
        span_start=span_start,
        span_end=span_end,
    )


# ---------------------------------------------------------------------------
# Gate-6 / 6b census on backtest/regime.py's labels (D4 §5)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class JointRegimeCensus:
    """Gate-6 and gate-6b evidence, on the labels ``_regime_census`` actually reads."""

    regime_label_source: str
    trend_buckets: dict[str, int]
    joint_cells: dict[str, int]
    vol_marginals: dict[str, int]
    range_bound_count: int
    range_bound_vol_labelled: bool
    warmup: int
    no_proxy_bar: int
    unlabelled: int
    n_trades: int

    @property
    def census_closes(self) -> bool:
        """No trade may vanish between the census and the trade list (``promotion.py:399``)."""
        total = (
            sum(self.joint_cells.values())
            + self.range_bound_count
            + self.warmup
            + self.no_proxy_bar
            + self.unlabelled
        )
        return total == self.n_trades

    def to_dict(self) -> dict[str, object]:
        return {
            "regime_label_source": self.regime_label_source,
            "trend_buckets": dict(self.trend_buckets),
            "joint_cells": dict(self.joint_cells),
            "vol_marginals": dict(self.vol_marginals),
            "range_bound_count": self.range_bound_count,
            "range_bound_vol_labelled": self.range_bound_vol_labelled,
            "warmup": self.warmup,
            "no_proxy_bar": self.no_proxy_bar,
            "unlabelled": self.unlabelled,
            "n_trades": self.n_trades,
            "census_closes": self.census_closes,
        }


def joint_regime_census(trades: Sequence[OptionTrade], proxy: PriceSeries) -> JointRegimeCensus:
    """Label each trade's **entry** date with ``backtest/regime.py::label_regimes``.

    Entry-date labelling means there is no look-ahead into how the regime later
    evolved, matching ``regime.py``'s own module contract.
    """
    labels = label_regimes(proxy)
    trend = {"bull": 0, "bear": 0, "range": 0}
    joint = dict.fromkeys(JOINT_CELLS, 0)
    warmup = no_bar = unlabelled = 0
    for tr in trades:
        label = labels.get(_as_date(tr.entry_date))
        if label is None:
            no_bar += 1
            continue
        if label == "warmup":
            warmup += 1
        elif label == "range_bound":
            trend["range"] += 1
        elif label in joint:
            joint[label] += 1
            trend["bull" if label.startswith("bull") else "bear"] += 1
        else:  # pragma: no cover - regime.py emits no other label today
            unlabelled += 1
    vol_marginals = {
        "highvol": joint["bull_highvol"] + joint["bear_highvol"],
        "lowvol": joint["bull_lowvol"] + joint["bear_lowvol"],
    }
    return JointRegimeCensus(
        regime_label_source="signalforge.backtest.regime:label_regimes",
        trend_buckets=trend,
        joint_cells=joint,
        vol_marginals=vol_marginals,
        # range_bound is emitted by an early-returning branch that DISCARDS the
        # computed vol half (regime.py:59-62), so it belongs to neither marginal.
        range_bound_count=trend["range"],
        range_bound_vol_labelled=False,
        warmup=warmup,
        no_proxy_bar=no_bar,
        unlabelled=unlabelled,
        n_trades=len(trades),
    )


# ---------------------------------------------------------------------------
# The two-spread rule (D2 §8, §9.3 — gate 4b)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SpreadCell:
    r_basis: RBasis
    spread_multiplier: float
    metrics: Metrics
    ci: dict[str, dict[str, float]]
    n_trades: int
    series_basis: str = "unclamped"

    @property
    def key(self) -> str:
        return f"{self.r_basis.value}@{self.spread_multiplier:g}x"


@dataclass(frozen=True, slots=True)
class DualSpreadReport:
    """All four (R basis x spread setting) cells; the gate binds on ONE of them.

    ``R_at_print`` is a fixed-denominator reporting basis computed from unadjusted
    prints — nobody receives the print credit — and **no gate binds on it**.  The
    binding cell is ``R_incl`` at ``2x``: the largest denominator against the
    smallest numerator.  Publishing the other three is disclosure, not slack, which
    is only honest if the report says which one binds.  This class says so.
    """

    cells: dict[str, SpreadCell]
    baseline: OptionsBacktestOutcome
    stressed: OptionsBacktestOutcome

    BINDING_KEY = "incl@2x"

    @property
    def binding_cell(self) -> SpreadCell:
        return self.cells[self.BINDING_KEY]

    @property
    def worst_cell(self) -> SpreadCell:
        """The numerically lowest expectancy of the four, whichever cell that is."""
        return min(self.cells.values(), key=lambda c: (c.metrics.expectancy_r, c.key))

    @property
    def binding_is_worst(self) -> bool:
        """Whether the pre-registered binding cell is also the numerically worst.

        D2 §9.3 asserts it is "by construction", and that holds for a
        positive-expectancy sample: ``R_incl > R_at_print`` always, so a larger
        denominator shrinks a positive expectancy.  It **inverts** on a sample whose
        expectancy is negative, where the larger denominator flatters the result.
        Such a sample fails gates 3 and 4 on any basis, so nothing is weakened — but
        the report states the fact rather than repeating a claim that is false for
        that sample.
        """
        return self.binding_cell.key == self.worst_cell.key

    def to_dict(self) -> dict[str, object]:
        return {
            "binding_cell": self.BINDING_KEY,
            "worst_cell": self.worst_cell.key,
            "binding_is_worst": self.binding_is_worst,
            "binding_basis_note": (
                "gates bind on R_incl at 2x spread (the worst of the four); "
                "R_at_print is a fixed-denominator REPORTING basis and no gate binds on it"
            ),
            "series_basis": "unclamped",
            "cells": {
                k: {
                    "r_basis": c.r_basis.value,
                    "spread_multiplier": c.spread_multiplier,
                    "n_trades": c.n_trades,
                    "series_basis": c.series_basis,
                    "metrics": c.metrics.to_dict(),
                    "ci": c.ci,
                }
                for k, c in sorted(self.cells.items())
            },
            "baseline_counters": self.baseline.counters.to_dict(),
            "stressed_counters": self.stressed.counters.to_dict(),
            "gate9_disclosure": (
                "a 4b evidence run replays a sealed result computed under the BASELINE "
                "cost model; gate 9 is omitted or labelled 'replayed sealed result, "
                "locked under the BASELINE cost model; not re-measured at 2x'"
            ),
        }


def _cells_for(outcome: OptionsBacktestOutcome) -> dict[str, SpreadCell]:
    out: dict[str, SpreadCell] = {}
    for basis in (RBasis.AT_PRINT, RBasis.INCL):
        # Every gate statistic runs on the UNCLAMPED series (D2 §9.4 rule 1).
        rs = [
            t.pnl_r_at_print if basis is RBasis.AT_PRINT else t.pnl_r_incl for t in outcome.trades
        ]
        rebased = tuple(_rebase(t, basis) for t in outcome.trades)
        cell = SpreadCell(
            r_basis=basis,
            spread_multiplier=outcome.spread_multiplier,
            metrics=compute_metrics(_as_sim_trades(rebased)),
            ci=bootstrap_ci(rs),
            n_trades=len(rebased),
        )
        out[cell.key] = cell
    return out


def _rebase(trade: OptionTrade, basis: RBasis) -> OptionTrade:
    """The same trade reported on the other denominator.  Fills are untouched."""
    pnl_r = trade.pnl_r_at_print if basis is RBasis.AT_PRINT else trade.pnl_r_incl
    r_dollars = trade.r_at_print if basis is RBasis.AT_PRINT else trade.r_incl
    return replace(trade, r_basis=basis, pnl_r=pnl_r, r_dollars=r_dollars, r_clamped=pnl_r < -1.0)


def run_dual_spread(
    chain: OptionChainSeries,
    underlying: PriceSeries,
    signal_fn: OptionsSignalFn,
    *,
    baseline: OptionCostModel,
    stressed: OptionCostModel,
    warmup: int = 50,
) -> DualSpreadReport:
    """Run the engine at both spread settings and report the four-way surface.

    The two cost models must differ in **exactly one recorded scalar**,
    ``spread_multiplier`` (D2 §8.2), so a change between the runs cannot be
    attributed to anything else.
    """
    if baseline.spread_multiplier != 1.0 or stressed.spread_multiplier != 2.0:
        raise ValueError("baseline must be 1.0x and stressed 2.0x (gate 4b)")
    if replace(baseline, spread_multiplier=2.0) != stressed:
        raise ValueError(
            "the 4b run must differ from the baseline in spread_multiplier and nothing else"
        )
    base_out = run_options_backtest(
        chain, underlying, signal_fn, cost_model=baseline, r_basis=RBasis.INCL, warmup=warmup
    )
    stress_out = run_options_backtest(
        chain, underlying, signal_fn, cost_model=stressed, r_basis=RBasis.INCL, warmup=warmup
    )
    cells = _cells_for(base_out) | _cells_for(stress_out)
    return DualSpreadReport(cells=cells, baseline=base_out, stressed=stress_out)
