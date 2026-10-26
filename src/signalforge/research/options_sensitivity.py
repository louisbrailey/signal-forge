"""Gate 5's options grid runner — the 96 pre-sealed re-runs (D5 §4.2, §4.4, §5.5).

``evaluate_options_promotion`` takes an ``OptionsSensitivitySummary`` and
``gate_5_sensitivity(None, ...)`` is an honest failure, so until something
*produces* that summary gate 5 is a permanent automatic fail rather than a
measurement.  This module produces it.

What it does, and the four things it refuses to do:

* **The grid is the strategy's own declaration.**  ``sensitivity_axes()`` is the
  full Cartesian product, exactly as ``research/sensitivity.py`` builds the equity
  grid, and the cap is the same ``MAX_GRID_POINTS`` constant imported from there —
  not a copy of the number.  D5 §4.2's whole shape (6 axes, 96 points, one 3-value
  axis) is *derived* from that cap, so a private second cap would silently
  invalidate the pre-registration's arithmetic.
* **Nothing is capped silently.**  If the product exceeds the cap, the run does
  not truncate to a "representative" subset: it raises by default, and when the
  caller explicitly allows a cap the dropped cells are enumerated in
  ``dropped_points`` and in ``reasons``, which flow into ``fragile`` and therefore
  into a gate-5 failure.  A grid that quietly lost 40 cells and then reported
  "82% positive" is the exact reading R5 exists to prevent.
* **Pre-sealed slice only.**  Every re-run is bounded by ``window.start ..
  window.pre_sealed_end``.  The sealed year is not loaded, not priced and not
  reachable from here — gate 5 is a pre-sealed robustness measurement and a grid
  that touched the sealed span would spend the look 96 times over.
* **OAT is reported, never selected from.**  ``oat_parameters()`` perturbations run
  one at a time from the baseline and are recorded in ``oat_points``; they do not
  enter ``positive_fraction`` or ``n_evaluable``, because D5 §4.4 makes them a
  disclosure table and a "best OAT value" reading is precisely the R1 move.

**The cache.**  96 grid points x 14 underlyings x 8 years is the single most
expensive thing in the program, and a re-run with identical inputs must be free.
The key is ``(strategy version, snapshot key, options_config_hash, q-series
digest)`` — the four things that can change what a cell measures.  The digest is
there because the dividend ``q`` series is mutable and outside the snapshot key.
A cache hit is reported as a hit;
nothing is ever read from the cache under a different key, and a corrupt or
unreadable entry is a miss, never a partial result.

S11b: this module imports nothing from ``llm``, ``alerts``, ``execution`` or any
paper ledger, and stays on the gate ladder's side of that wall.
"""

from __future__ import annotations

import itertools
import json
import statistics
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from signalforge.backtest.options_engine import OptionTrade
from signalforge.config.paths import data_dir
from signalforge.data.options_corporate_actions import Q_SERIES_SOURCE, q_series_digest
from signalforge.db.models import DataSnapshot
from signalforge.observability import get_logger
from signalforge.research.options_evidence import (
    OptionsStrategy,
    cap_concurrent,
    resolve_option_data_source,
    run_underlying,
)
from signalforge.research.options_gates import (
    OptionsGateThresholds,
    OptionsSensitivitySummary,
    OptionsWindow,
)
from signalforge.research.sensitivity import MAX_GRID_POINTS

_log = get_logger("research.options_sensitivity")

#: Cache schema; bumped when a stored field changes meaning, so an old entry is a
#: miss rather than a silently misread hit.
CACHE_SCHEMA_VERSION = 1

#: ``Callable[[Mapping[str, float | int]], OptionsStrategy]`` — the caller builds
#: a strategy at one parameter point.  A factory rather than ``replace()`` because
#: an options strategy's constructor carries the ``q_lookup``, the proxy regimes
#: and the selection cost model, none of which are params.
OptionsStrategyFactory = Callable[[Mapping[str, float | int]], OptionsStrategy]


class GridTooLarge(ValueError):
    """The declared grid exceeds ``MAX_GRID_POINTS`` and no cap was authorised."""


@dataclass(frozen=True, slots=True)
class OptionsGridPoint:
    params: dict[str, float | int]
    n_trades: int
    presealed_expectancy_r: float
    presealed_win_rate: float
    skipped_concurrency: int
    is_baseline: bool = False
    is_neighbour: bool = False
    kind: str = "grid"  # grid | oat

    def to_dict(self) -> dict[str, Any]:
        return {
            "params": dict(self.params),
            "n_trades": self.n_trades,
            "presealed_expectancy_r": round(self.presealed_expectancy_r, 4),
            "presealed_win_rate": round(self.presealed_win_rate, 4),
            "skipped_concurrency": self.skipped_concurrency,
            "is_baseline": self.is_baseline,
            "is_neighbour": self.is_neighbour,
            "kind": self.kind,
        }


@dataclass(frozen=True, slots=True)
class OptionsSensitivityReport:
    """The full grid, plus the reduced :class:`OptionsSensitivitySummary` gate 5 reads."""

    strategy_key: str
    version: str
    snapshot_key: str
    options_config_hash: str
    axes: tuple[str, ...]
    baseline_params: dict[str, float | int]
    min_trades: int
    declared_points: int
    evaluated_points: int
    dropped_points: tuple[dict[str, float | int], ...]
    grid: tuple[OptionsGridPoint, ...]
    oat_points: tuple[OptionsGridPoint, ...]
    inert_axes: tuple[str, ...]
    reasons: tuple[str, ...]
    cache_hit: bool = False

    @property
    def evaluable(self) -> tuple[OptionsGridPoint, ...]:
        return tuple(p for p in self.grid if p.n_trades >= self.min_trades)

    def summary(self, th: OptionsGateThresholds | None = None) -> OptionsSensitivitySummary:
        """The object ``gate_5_sensitivity`` binds on.

        ``fragile`` is true whenever ANY reason was recorded — an inert axis, a
        dropped cell, a thin grid or a failed fraction — which is the same
        all-or-nothing convention the equity report uses.
        """
        t = th or OptionsGateThresholds()
        ev = self.evaluable
        positives = [p for p in ev if p.presealed_expectancy_r > 0]
        neighbours = [p for p in ev if p.is_neighbour]
        neighbour_pos = [p for p in neighbours if p.presealed_expectancy_r > 0]
        pos_frac = len(positives) / len(ev) if ev else 0.0
        nb_frac = len(neighbour_pos) / len(neighbours) if neighbours else 0.0
        reasons = list(self.reasons)
        if ev and pos_frac < t.sensitivity_positive_fraction_min:
            reasons.append(
                f"only {pos_frac:.0%} of evaluated points have positive pre-sealed expectancy "
                f"(need {t.sensitivity_positive_fraction_min:.0%})"
            )
        if neighbours and nb_frac < t.sensitivity_neighbour_fraction_min:
            reasons.append(
                f"only {nb_frac:.0%} of one-step neighbours of the baseline stay positive "
                f"(need {t.sensitivity_neighbour_fraction_min:.0%})"
            )
        if len(ev) < 3:
            reasons.append(
                f"only {len(ev)} grid points produced >= {self.min_trades} pre-sealed structures"
            )
        return OptionsSensitivitySummary(
            n_points=self.declared_points,
            n_evaluable=len(ev),
            positive_fraction=pos_frac,
            neighbour_positive_fraction=nb_frac,
            fragile=bool(reasons),
            axes=self.axes,
            reasons=tuple(reasons),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy_key": self.strategy_key,
            "version": self.version,
            "snapshot_key": self.snapshot_key,
            "options_config_hash": self.options_config_hash,
            "axes": list(self.axes),
            "baseline_params": dict(self.baseline_params),
            "min_trades": self.min_trades,
            "declared_points": self.declared_points,
            "evaluated_points": self.evaluated_points,
            "dropped_points": [dict(p) for p in self.dropped_points],
            "grid": [p.to_dict() for p in self.grid],
            "oat_points": [p.to_dict() for p in self.oat_points],
            "inert_axes": list(self.inert_axes),
            "reasons": list(self.reasons),
            "cache_hit": self.cache_hit,
        }


# --------------------------------------------------------------------------- #
# cache
# --------------------------------------------------------------------------- #
def cache_key(
    *, version: str, snapshot_key: str, options_config_hash: str, q_series_digest: str
) -> str:
    """The four things that can change what a grid cell measures.

    ``q_series_digest`` is required, not defaulted: the dividend ``q`` series is
    mutable and outside the snapshot key, so a key without it would let a grid
    cached before the series existed (or before a re-derivation) be served as a
    hit while the ladder prices on the current ``q``.
    """
    if not q_series_digest:
        raise ValueError("cache_key needs the q-series digest; an empty one is not a key")
    # ``cc1``: grids cached before the D5a §3.5 portfolio cap was applied measured
    # a different population; the schema tag makes every such entry a miss.
    return (
        f"{version}__{snapshot_key}__{options_config_hash or 'nohash'}"
        f"__q{q_series_digest[:32]}__cc1"
    ).replace("/", "_")


def cache_dir(root: Path | None = None) -> Path:
    path = (root or data_dir()) / "options_sensitivity_cache"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _cache_path(key: str, root: Path | None = None) -> Path:
    return cache_dir(root) / f"{key}.json"


def load_cached(key: str, root: Path | None = None) -> OptionsSensitivityReport | None:
    """A stored report, or ``None``.  A malformed entry is a MISS, never a partial."""
    path = _cache_path(key, root)
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if int(payload.get("schema_version", 0)) != CACHE_SCHEMA_VERSION:
            return None
        body = payload["report"]
        return OptionsSensitivityReport(
            strategy_key=body["strategy_key"],
            version=body["version"],
            snapshot_key=body["snapshot_key"],
            options_config_hash=body["options_config_hash"],
            axes=tuple(body["axes"]),
            baseline_params=dict(body["baseline_params"]),
            min_trades=int(body["min_trades"]),
            declared_points=int(body["declared_points"]),
            evaluated_points=int(body["evaluated_points"]),
            dropped_points=tuple(dict(p) for p in body["dropped_points"]),
            grid=tuple(OptionsGridPoint(**_point(p)) for p in body["grid"]),
            oat_points=tuple(OptionsGridPoint(**_point(p)) for p in body["oat_points"]),
            inert_axes=tuple(body["inert_axes"]),
            reasons=tuple(body["reasons"]),
            cache_hit=True,
        )
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        _log.warning("options sensitivity cache entry unreadable; recomputing", extra={"key": key})
        return None


def _point(raw: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "params": dict(raw["params"]),
        "n_trades": int(raw["n_trades"]),
        "presealed_expectancy_r": float(raw["presealed_expectancy_r"]),
        "presealed_win_rate": float(raw["presealed_win_rate"]),
        "skipped_concurrency": int(raw.get("skipped_concurrency", 0)),
        "is_baseline": bool(raw.get("is_baseline", False)),
        "is_neighbour": bool(raw.get("is_neighbour", False)),
        "kind": str(raw.get("kind", "grid")),
    }


def store_cached(key: str, report: OptionsSensitivityReport, root: Path | None = None) -> Path:
    path = _cache_path(key, root)
    path.write_text(
        json.dumps(
            {"schema_version": CACHE_SCHEMA_VERSION, "key": key, "report": report.to_dict()},
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return path


# --------------------------------------------------------------------------- #
# grid construction
# --------------------------------------------------------------------------- #
def _is_neighbour(
    point: Mapping[str, Any], baseline: Mapping[str, Any], grid: Mapping[str, Sequence[Any]]
) -> bool:
    """Differs from the baseline on exactly one axis, by exactly one grid step.

    Same definition as ``sensitivity._is_neighbour``; restated rather than imported
    because the equity helper is private to a module this one must not perturb.
    """
    differing = [k for k in grid if point.get(k) != baseline.get(k)]
    if len(differing) != 1:
        return False
    axis = differing[0]
    values = list(grid[axis])
    try:
        return abs(values.index(baseline[axis]) - values.index(point[axis])) == 1
    except ValueError:
        return False


def _inert_axes(points: Sequence[OptionsGridPoint], axes: Sequence[str]) -> list[str]:
    """An axis whose perturbations move neither trade count nor expectancy tested nothing."""
    base = next((p for p in points if p.is_baseline), None)
    if base is None:
        return []
    base_exp = round(base.presealed_expectancy_r, 4)
    inert: list[str] = []
    for axis in axes:
        off = [
            p
            for p in points
            if not p.is_baseline
            and p.params.get(axis) != base.params.get(axis)
            and all(p.params.get(o) == base.params.get(o) for o in axes if o != axis)
        ]
        if not off:
            continue
        moved = any(
            p.n_trades != base.n_trades or round(p.presealed_expectancy_r, 4) != base_exp
            for p in off
        )
        if not moved:
            inert.append(axis)
    return inert


def declared_grid(
    strategy: OptionsStrategy, *, allow_cap: bool = False
) -> tuple[list[dict[str, float | int]], list[dict[str, float | int]]]:
    """``(evaluated, dropped)`` — the full Cartesian product, capped ONLY if asked.

    The cap is ``sensitivity.MAX_GRID_POINTS``, imported rather than copied.  When
    capping is authorised the *trailing* cells in ``itertools.product`` order are
    dropped and returned, so what was lost is enumerable and lands in the report;
    there is no sampling rule that could be mistaken for a design choice.
    """
    axes = strategy.sensitivity_axes()
    names = list(axes)
    combos = list(itertools.product(*(list(axes[a]) for a in names)))
    points = [dict(zip(names, c, strict=True)) for c in combos]
    if len(points) <= MAX_GRID_POINTS:
        return points, []
    if not allow_cap:
        raise GridTooLarge(
            f"declared grid has {len(points)} points; cap is {MAX_GRID_POINTS} "
            f"(sensitivity.MAX_GRID_POINTS). Shrink the grid, or pass allow_cap=True to run "
            f"the first {MAX_GRID_POINTS} and have the dropped cells recorded as a gate-5 "
            f"failure reason."
        )
    return points[:MAX_GRID_POINTS], points[MAX_GRID_POINTS:]


def oat_points(
    strategy: OptionsStrategy, baseline: Mapping[str, float | int]
) -> list[dict[str, float | int]]:
    """One-at-a-time perturbations: baseline with exactly one parameter moved."""
    out: list[dict[str, float | int]] = []
    for name, values in strategy.oat_parameters().items():
        for v in values:
            if baseline.get(name) == v:
                continue
            out.append({name: v})
    return out


# --------------------------------------------------------------------------- #
# the runner
# --------------------------------------------------------------------------- #
def _presealed(trades: Sequence[OptionTrade], window: OptionsWindow) -> list[OptionTrade]:
    return [t for t in trades if window.start <= t.entry_date <= window.pre_sealed_end]


def _evaluate_point(
    session: Session,
    factory: OptionsStrategyFactory,
    params: Mapping[str, float | int],
    *,
    symbols: Sequence[str],
    window: OptionsWindow,
    source: str,
    option_source: str,
    warmup: int,
) -> tuple[int, float, float, int]:
    """``(n_trades, expectancy_r, win_rate, skipped_concurrency)`` on the PRE-SEALED slice.

    The window handed to ``run_underlying`` ends at ``pre_sealed_end``; the sealed
    span is never loaded, so a grid point cannot see it even by accident.
    """
    strat = factory(params)
    # A window whose END is the pre-sealed end: the chain loader's date filter is
    # the mechanical guarantee, not a convention the grid code has to remember.
    # ``sealed_start`` is pushed to the day after it so the object stays internally
    # coherent (a sealed span that starts after the window ends is empty).
    presealed_window = OptionsWindow(
        start=window.start,
        pre_sealed_end=window.pre_sealed_end,
        sealed_start=window.pre_sealed_end + timedelta(days=1),
        end=window.pre_sealed_end,
    )
    trades: list[OptionTrade] = []
    skipped = 0
    for sym in symbols:
        run = run_underlying(
            session,
            strat,
            sym,
            window=presealed_window,
            source=source,
            option_source=option_source,
            dte_targets=[int(params.get("dte_target", 35))],
            include_mechanical=False,
            warmup=warmup,
        )
        if run.dual is None:
            continue
        trades.extend(_presealed(run.dual.baseline.trades, presealed_window))
    # The same pre-registered portfolio cap the evidence assembler applies
    # (D5a §3.5): a grid cell must measure the population the gates will see.
    trades, capped = cap_concurrent(trades, getattr(strat, "portfolio_concurrency_cap", None))
    skipped = len(capped)
    if not trades:
        return 0, 0.0, 0.0, skipped
    rs = [t.pnl_r for t in trades]
    return (
        len(trades),
        statistics.fmean(rs),
        sum(1 for r in rs if r > 0) / len(rs),
        skipped,
    )


def run_options_sensitivity(
    session: Session,
    strategy: OptionsStrategy,
    factory: OptionsStrategyFactory,
    *,
    baseline_params: Mapping[str, float | int],
    dataset_snapshot: DataSnapshot,
    window: OptionsWindow,
    version: str,
    options_config_hash: str,
    thresholds: OptionsGateThresholds | None = None,
    source: str = "massive",
    warmup: int = 50,
    allow_cap: bool = False,
    use_cache: bool = True,
    cache_root: Path | None = None,
    include_oat: bool = True,
    q_source: str = Q_SERIES_SOURCE,
) -> OptionsSensitivityReport:
    """Run the declared grid (and the OAT table) on the pre-sealed slice.

    The cache key is ``(version, snapshot key, options_config_hash, q-series
    digest)``: a new strategy version, a different dataset, a changed evaluation
    assumption or a changed dividend ``q`` series on the evaluated underlyings
    and pre-sealed span all invalidate it, and nothing else can.  A hit returns
    the stored report with ``cache_hit=True`` and runs no backtest at all.

    ``source`` is the underlying-bar source; the option-data source is read from
    the snapshot's recorded provenance and its absence is a refusal
    (``OptionSourceUnresolved``), exactly as in the evidence assembler — every
    grid point of a mis-sourced run would otherwise report zero trades silently.
    """
    th = thresholds or OptionsGateThresholds()
    option_source = resolve_option_data_source(session, dataset_snapshot)
    key = cache_key(
        version=version,
        snapshot_key=dataset_snapshot.key,
        options_config_hash=options_config_hash,
        q_series_digest=q_series_digest(
            session,
            [str(s) for s in (dataset_snapshot.symbols_json or [])],
            window.start,
            window.pre_sealed_end,
            q_source,
        ),
    )
    if use_cache:
        cached = load_cached(key, cache_root)
        if cached is not None:
            _log.info("options sensitivity cache HIT", extra={"key": key})
            return cached

    axes = strategy.sensitivity_axes()
    names = tuple(axes)
    evaluated, dropped = declared_grid(strategy, allow_cap=allow_cap)
    declared_points = len(evaluated) + len(dropped)
    symbols = [str(s).upper() for s in (dataset_snapshot.symbols_json or [])]
    baseline = dict(baseline_params)

    grid: list[OptionsGridPoint] = []
    for overrides in evaluated:
        params = {**baseline, **overrides}
        n, exp, win, skipped = _evaluate_point(
            session,
            factory,
            params,
            symbols=symbols,
            window=window,
            source=source,
            option_source=option_source,
            warmup=warmup,
        )
        grid.append(
            OptionsGridPoint(
                params={a: params[a] for a in names},
                n_trades=n,
                presealed_expectancy_r=exp,
                presealed_win_rate=win,
                skipped_concurrency=skipped,
                is_baseline=all(overrides[a] == baseline.get(a) for a in names),
                is_neighbour=_is_neighbour(params, baseline, axes),
            )
        )

    oat: list[OptionsGridPoint] = []
    if include_oat:
        for overrides in oat_points(strategy, baseline):
            params = {**baseline, **overrides}
            n, exp, win, skipped = _evaluate_point(
                session,
                factory,
                params,
                symbols=symbols,
                window=window,
                source=source,
                option_source=option_source,
                warmup=warmup,
            )
            oat.append(
                OptionsGridPoint(
                    params=dict(overrides),
                    n_trades=n,
                    presealed_expectancy_r=exp,
                    presealed_win_rate=win,
                    skipped_concurrency=skipped,
                    kind="oat",
                )
            )

    inert = _inert_axes(grid, names)
    reasons: list[str] = [
        f"axis {a!r} does not change the pre-sealed trade count or expectancy — the grid "
        f"tested nothing on it"
        for a in inert
    ]
    if dropped:
        # No silent cap: the count, the cap and the first dropped cell are all in
        # the reason string, and the full list is in ``dropped_points``.
        reasons.append(
            f"{len(dropped)} of {declared_points} declared grid points were DROPPED by the "
            f"{MAX_GRID_POINTS}-point cap and were never evaluated (first dropped cell: "
            f"{dropped[0]}); gate 5 cannot read a grid it did not run"
        )
        _log.warning(
            "options sensitivity grid capped",
            extra={"declared": declared_points, "cap": MAX_GRID_POINTS, "dropped": len(dropped)},
        )

    report = OptionsSensitivityReport(
        strategy_key=strategy.key,
        version=version,
        snapshot_key=dataset_snapshot.key,
        options_config_hash=options_config_hash,
        axes=names,
        baseline_params=baseline,
        min_trades=th.sensitivity_min_grid_trades,
        declared_points=declared_points,
        evaluated_points=len(grid),
        dropped_points=tuple(dropped),
        grid=tuple(grid),
        oat_points=tuple(oat),
        inert_axes=tuple(inert),
        reasons=tuple(reasons),
        cache_hit=False,
    )
    if use_cache:
        store_cached(key, report, cache_root)
    return report


__all__ = [
    "CACHE_SCHEMA_VERSION",
    "GridTooLarge",
    "OptionsGridPoint",
    "OptionsSensitivityReport",
    "OptionsStrategyFactory",
    "cache_dir",
    "cache_key",
    "declared_grid",
    "load_cached",
    "oat_points",
    "run_options_sensitivity",
    "store_cached",
]
