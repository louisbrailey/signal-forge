"""Parameter-sensitivity analysis (ARCHITECTURE.md §1.4).

Re-runs a strategy's out-of-sample backtest across a small grid of parameter
values and asks: does the edge survive a perturbation, or does it live only at
one lucky point?  A strategy whose positive expectancy collapses as soon as a
parameter is nudged is flagged ``fragile`` and must not be promoted.

Deterministic: the same grid + data always produce the same verdict (S4).
"""

from __future__ import annotations

import itertools
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from signalforge.backtest.costs import CostModel
from signalforge.data.repository import SourceFilter
from signalforge.research.backtest_runner import run_strategy_over_universe
from signalforge.research.strategies.base import BaselineStrategy

StrategyFactory = Callable[[Mapping[str, Any]], BaselineStrategy]
ParamGrid = Mapping[str, Sequence[float | int]]

MAX_GRID_POINTS = 120


@dataclass(frozen=True, slots=True)
class GridPoint:
    params: dict[str, float | int]
    n_trades: int
    oos_expectancy_r: float
    oos_ci_low_r: float
    oos_win_rate: float
    is_baseline: bool = False
    is_neighbour: bool = False  # differs from baseline on exactly one axis, by one step


@dataclass(frozen=True, slots=True)
class SensitivityReport:
    strategy_key: str
    version: str
    baseline_params: dict[str, float | int]
    baseline_expectancy_r: float
    min_trades: int
    n_points: int
    n_evaluable: int
    n_positive: int
    positive_fraction: float
    neighbour_positive_fraction: float
    median_expectancy_r: float
    worst_expectancy_r: float
    fragile: bool
    reasons: list[str] = field(default_factory=list)
    grid: list[GridPoint] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy_key": self.strategy_key,
            "version": self.version,
            "baseline_params": self.baseline_params,
            "baseline_expectancy_r": self.baseline_expectancy_r,
            "min_trades": self.min_trades,
            "n_points": self.n_points,
            "n_evaluable": self.n_evaluable,
            "n_positive": self.n_positive,
            "positive_fraction": round(self.positive_fraction, 3),
            "neighbour_positive_fraction": round(self.neighbour_positive_fraction, 3),
            "median_expectancy_r": round(self.median_expectancy_r, 4),
            "worst_expectancy_r": round(self.worst_expectancy_r, 4),
            "fragile": self.fragile,
            "reasons": list(self.reasons),
            "grid": [
                {
                    "params": g.params,
                    "n_trades": g.n_trades,
                    "oos_expectancy_r": round(g.oos_expectancy_r, 4),
                    "oos_ci_low_r": round(g.oos_ci_low_r, 4),
                    "oos_win_rate": round(g.oos_win_rate, 4),
                    "is_baseline": g.is_baseline,
                    "is_neighbour": g.is_neighbour,
                }
                for g in self.grid
            ],
        }


def _median(xs: Sequence[float]) -> float:
    if not xs:
        return 0.0
    s = sorted(xs)
    mid = len(s) // 2
    return s[mid] if len(s) % 2 else (s[mid - 1] + s[mid]) / 2


def _is_neighbour(point: Mapping[str, Any], baseline: Mapping[str, Any], grid: ParamGrid) -> bool:
    """True when ``point`` differs from ``baseline`` on exactly one axis, by one grid step."""
    differing = [k for k in grid if point.get(k) != baseline.get(k)]
    if len(differing) != 1:
        return False
    axis = differing[0]
    values = list(grid[axis])
    try:
        bi = values.index(baseline[axis])
        pi = values.index(point[axis])
    except ValueError:
        return False
    return abs(bi - pi) == 1


def run_parameter_sensitivity(
    session: Session,
    *,
    strategy_key: str,
    version: str,
    factory: StrategyFactory,
    baseline_params: Mapping[str, float | int],
    grid: ParamGrid,
    symbols: list[str],
    start: date,
    end: date,
    source: SourceFilter = None,
    cost_model: CostModel | None = None,
    intraday: bool = False,
    bar_size: str = "15m",
    min_bars: int = 60,
    min_trades: int = 15,
    positive_fraction_min: float = 0.6,
    neighbour_fraction_min: float = 0.75,
) -> SensitivityReport:
    axes = list(grid.keys())
    combos = list(itertools.product(*(list(grid[a]) for a in axes)))
    if len(combos) > MAX_GRID_POINTS:
        raise ValueError(
            f"grid has {len(combos)} points; cap is {MAX_GRID_POINTS}. Shrink the grid."
        )

    baseline = dict(baseline_params)
    points: list[GridPoint] = []
    for combo in combos:
        overrides = dict(zip(axes, combo, strict=True))
        params = {**baseline, **overrides}
        strat = factory(params)
        res = run_strategy_over_universe(
            session,
            strat,
            symbols,
            start,
            end,
            source=source,
            cost_model=cost_model,
            intraday=intraday,
            bar_size=bar_size,
            min_bars=min_bars,
        )
        exp = res.out_of_sample.expectancy_r
        ci_low = float(res.oos_ci.get("expectancy_r", {}).get("low", 0.0))
        win = res.out_of_sample.win_rate
        is_base = all(overrides[a] == baseline.get(a) for a in axes)
        points.append(
            GridPoint(
                params={a: params[a] for a in axes},
                n_trades=res.out_of_sample.n_trades,
                oos_expectancy_r=exp,
                oos_ci_low_r=ci_low,
                oos_win_rate=win,
                is_baseline=is_base,
                is_neighbour=_is_neighbour(params, baseline, grid),
            )
        )

    evaluable = [p for p in points if p.n_trades >= min_trades]
    positive = [p for p in evaluable if p.oos_expectancy_r > 0]
    neighbours = [p for p in evaluable if p.is_neighbour]
    neighbour_pos = [p for p in neighbours if p.oos_expectancy_r > 0]

    pos_frac = len(positive) / len(evaluable) if evaluable else 0.0
    nb_frac = len(neighbour_pos) / len(neighbours) if neighbours else 0.0
    baseline_point = next((p for p in points if p.is_baseline), None)
    baseline_exp = baseline_point.oos_expectancy_r if baseline_point else 0.0

    reasons: list[str] = []
    if len(evaluable) < 3:
        reasons.append(f"only {len(evaluable)} grid points produced >= {min_trades} OOS trades")
    if evaluable and pos_frac < positive_fraction_min:
        reasons.append(
            f"only {pos_frac:.0%} of evaluated points have positive OOS expectancy "
            f"(need {positive_fraction_min:.0%})"
        )
    if neighbours and nb_frac < neighbour_fraction_min:
        reasons.append(
            f"only {nb_frac:.0%} of one-step neighbours of the baseline stay positive "
            f"(need {neighbour_fraction_min:.0%})"
        )
    if len(evaluable) >= 4 and len(positive) <= 1:
        reasons.append("the edge exists at a single parameter point only")
    if baseline_point and baseline_exp > 0 and not neighbour_pos and neighbours:
        reasons.append("baseline is positive but every adjacent parameter value is not")

    return SensitivityReport(
        strategy_key=strategy_key,
        version=version,
        baseline_params=dict(baseline),
        baseline_expectancy_r=round(baseline_exp, 4),
        min_trades=min_trades,
        n_points=len(points),
        n_evaluable=len(evaluable),
        n_positive=len(positive),
        positive_fraction=pos_frac,
        neighbour_positive_fraction=nb_frac,
        median_expectancy_r=_median([p.oos_expectancy_r for p in evaluable]),
        worst_expectancy_r=min((p.oos_expectancy_r for p in evaluable), default=0.0),
        fragile=bool(reasons),
        reasons=reasons,
        grid=points,
    )
