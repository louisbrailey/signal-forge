"""The options gate ladder's predicates and evidence (D4).

**Nothing in this module can change the equity ladder.**  It defines a *sibling*
gate type, :class:`OptionsGate`, rather than adding a ``label`` field to
``promotion.Gate`` as D4 §1 proposed.  The reason is the one constraint D4 §1
could not have known about: ``Gate.to_dict()`` is what lands verbatim in
``strategy_promotion_evaluation.gates_json`` (``db/models/research.py``), so
adding a field to it would change the stored JSON of **every** equity
evaluation, historical readers included, in the same commit that ships an
options gate.  I-O4's brief makes byte-identical equity ``gates_json`` a test,
and a sibling type satisfies both that test and D4 §1's actual requirement —
that ``0.5`` / ``4b`` / ``6b`` / ``7b`` be expressible at all, which
``Gate.number: int`` cannot do.

The second half of D4 §1's motivation falls away with it: gate 4b lands in the
equity ladder only if the equity application is a *ladder* change.  It is not —
D4 §4.5 step 4 and the I-O4 brief both make the equity 4b run a **documented
pre-sealed disposition input**, so no equity gate, threshold, sealed row or
ladder-shape assertion moves.

Everything here is pure: no database, no clock, no RNG (S4).  The evidence
dataclasses are the *measured facts*; the ``gate_*`` functions are the
*predicates over them*, so a predicate can be tested against arithmetic a reader
can do on paper.

Two threshold conflicts between D4 and D5 are resolved here in the **tighter**
direction, and both are recorded rather than silently picked:

* clamp-rate ceiling — D4 §6.3 item 7 hands D5 ``r_clamped_fraction <= 0.05``;
  D5 §3.5 / F9 pre-registers ``0.10``.  The **gate** binds on 0.05; F9's 0.10 is
  recorded alongside as a separate NO-SHIP disposition flag.
* stop-non-binding ceiling — D4 §6.3 item 9 states 0.25 of losing trades; D5 F9
  states 0.20.  The gate binds on **0.20**; 0.25 is recorded.

R4 permits tightening and forbids loosening, so binding on the tighter of two
pre-registered numbers is the only safe reading of a conflict neither document
can settle on its own.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from signalforge.backtest.options_costs import OptionCostModel
from signalforge.backtest.options_engine import OptionTrade, RBasis, StructureType
from signalforge.domain import Horizon
from signalforge.research.options_backtest_runner import (
    DualSpreadReport,
    JointRegimeCensus,
    RegimePartitionDisclosure,
)

# --------------------------------------------------------------------------- #
# gate identity
# --------------------------------------------------------------------------- #

#: The ordered ``(number, label)`` shape of the options ladder.  D4 §1 requires
#: the shape to be asserted on ordered pairs and **re-specified, never deleted**;
#: this constant is what the test asserts against, and a change to it is visible
#: in a diff of one line.
OPTIONS_LADDER_SHAPE: tuple[tuple[int, str], ...] = (
    (0, "0.a"),
    (0, "0.b"),
    (0, "0.c"),
    (0, "0.d"),
    (0, "0.e"),
    (0, "0.f"),
    (0, "0.g"),
    (0, "0.h"),
    (0, "0.i"),
    (0, "0.5"),
    (1, ""),
    (2, ""),
    (3, ""),
    (4, ""),
    (4, "4b"),
    (5, ""),
    (6, ""),
    (6, "6b"),
    (7, ""),
    (7, "7b"),
    (8, ""),
    (9, ""),
    (10, ""),
)


@dataclass(frozen=True, slots=True)
class OptionsGate:
    """One rung of the options ladder.

    ``number`` carries the **parent** integer so the visual link to the equity
    gate it extends survives; ``label`` carries the human id (``"0.c"``,
    ``"4b"``) that ``int`` cannot express.  ``label == ""`` means "the gate is
    exactly its number".
    """

    number: int
    name: str
    passed: bool
    detail: str
    evidence: dict[str, Any] = field(default_factory=dict)
    label: str = ""

    @property
    def gate_id(self) -> str:
        return self.label or str(self.number)

    def to_dict(self) -> dict[str, Any]:
        return {
            "number": self.number,
            "label": self.label,
            "gate_id": self.gate_id,
            "name": self.name,
            "passed": self.passed,
            "detail": self.detail,
            "evidence": self.evidence,
        }


# --------------------------------------------------------------------------- #
# pre-registered thresholds (D4 §11's ten items + D5 §5, §8)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class OptionsGateThresholds:
    """Every number here was fixed before any options outcome was observed.

    Each may be **tightened** at any time (R4); none may be loosened, and a
    loosening after any result is seen is the move R1 forbids whatever it is
    called.
    """

    # gate 0.a — D4 §2.1.  350 + 365; 0DTE is refused outright in Phase 1.
    min_presealed_days: int = 350
    sealed_window_days: int = 365
    min_dte_at_entry: int = 1
    # gate 0.c / 0.d — D5 §5.1, §5.2
    bracket_fraction_min: float = 0.90
    bar_continuity_min: float = 0.80
    thin_continuity_floor: float = 0.60
    # gate 0.e — D5 §2.4: pct_otm_proxy is NEVER admissible for this family
    pct_otm_proxy_max_fraction: float = 0.0
    surface_n_floor: int = 5
    surface_min_distinct_strikes: int = 3
    # gate 0.i — decisions #4 / #13, D4 §2.8a
    options_per_structure_max_loss: float = 250.0
    options_total_open_max_loss: float = 1000.0
    account_equity_basis: float = 25_000.0
    # gate 1-4 — the equity PromotionThresholds, restated verbatim because
    # ``PromotionThresholds`` is outside SCOPE_HASH_FIELDS (D5 §2.5 item 2) and
    # an options record must therefore carry its own copy.
    min_walkforward_folds: int = 4
    min_oos_trades: int = 30
    min_net_expectancy_r: float = 0.0
    min_bootstrap_ci_low_r: float = 0.02
    min_fold_trades: int = 15
    # gate 5 — D5 §5.5
    sensitivity_min_grid_trades: int = 15
    sensitivity_positive_fraction_min: float = 0.60
    sensitivity_neighbour_fraction_min: float = 0.75
    sensitivity_min_evaluable: int = 58
    # gate 6 / 6b — config/research.py + D4 §5.3
    min_regimes_covered: int = 3
    min_trades_per_regime: int = 10
    min_vol_marginal_trades: int = 10
    min_joint_cell_trades: int = 5
    # gate 7 — config/research.py require_beat_benchmark_sharpe
    require_beat_benchmark_sharpe: bool = True
    # gate 8 — D4 §6.3 items 3/7/9, tightened against D5 where they disagree
    synthetic_mark_fraction_max: float = 0.10
    r_clamped_fraction_max: float = 0.05
    r_clamped_fraction_f9_noship: float = 0.10
    stop_non_binding_of_losers_max: float = 0.20
    stop_non_binding_of_losers_d4: float = 0.25
    pinned_fraction_max: float = 0.15
    # gate 9 — config/research.py sealed_*
    sealed_min_trades: int = 10
    sealed_min_expectancy_r: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        from dataclasses import asdict

        return asdict(self)


# --------------------------------------------------------------------------- #
# evidence inputs — the measured facts each gate reads
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class OptionsWindow:
    start: date
    pre_sealed_end: date
    sealed_start: date
    end: date

    @property
    def presealed_days(self) -> int:
        return (self.pre_sealed_end - self.start).days

    def to_dict(self) -> dict[str, str]:
        return {
            "start": self.start.isoformat(),
            "pre_sealed_end": self.pre_sealed_end.isoformat(),
            "sealed_start": self.sealed_start.isoformat(),
            "end": self.end.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class UnderlyingCoverage:
    symbol: str
    source: str
    first_bar: date | None
    last_bar: date | None
    gap_sessions: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "source": self.source,
            "first_bar": self.first_bar.isoformat() if self.first_bar else None,
            "last_bar": self.last_bar.isoformat() if self.last_bar else None,
            "gap_sessions": self.gap_sessions,
        }


@dataclass(frozen=True, slots=True)
class OptionsDataAvailability:
    """Gate 0.a-0.i's inputs, measured by the caller from the coverage summary.

    Everything here is a **count or a fraction**: map §7 Phase I permits a
    coverage summary to be read before D5 is committed and permits nothing else,
    so no field of this object may ever carry a price, an IV, a greek, a credit,
    a return or a P&L.
    """

    # 0.a
    horizon: Horizon
    min_dte_at_entry_declared: int
    # 0.b
    underlyings: tuple[UnderlyingCoverage, ...]
    required_source: str
    # 0.c
    cycles_eligible: int
    cycles_bracketed: int
    bracket_fraction_matrix: Mapping[str, Mapping[str, float]]
    bracket_gated_cells: tuple[tuple[int, str], ...]
    eligible_cycle_definition: str
    bracket_failures_by_underlying: Mapping[str, int]
    bracket_failures_by_side: Mapping[str, int]
    # 0.d
    bar_continuity_min_observed: float
    bar_continuity_median: float
    non_entry_count: int
    non_entry_reasons: Mapping[str, int]
    exit_deferral_histogram: Mapping[str, int]
    gap_sessions: int
    # 0.e
    iv_source_mix: Mapping[str, float]
    iv_source_unnamed_count: int
    surface_n_actual_min: int
    # 0.f
    fill_model: str
    cost_model: OptionCostModel
    cost_model_frozen_at: str
    cost_per_structure_roundtrip_usd: Mapping[str, float]
    entitlement_batches_checked: int
    # 0.g
    q_by_underlying: Mapping[str, Mapping[str, Any]]
    q_defaulted_count: int
    # 0.h
    deliverable_refusal_count: int
    deliverable_refusals: tuple[Mapping[str, Any], ...] = ()
    # 0.i
    r_max_observed_usd: float = 0.0
    r_max_by_width: Mapping[str, float] = field(default_factory=dict)
    concurrent_open_r_max_usd: float = 0.0
    structures_breaching_per_structure_cap: int = 0
    width_grid_declared: tuple[float, ...] = ()
    limits_source: str = ""
    limits_in_options_config_hash: bool = False

    @property
    def bracket_fraction(self) -> float:
        return self.cycles_bracketed / self.cycles_eligible if self.cycles_eligible else 0.0


@dataclass(frozen=True, slots=True)
class StructureIdentity:
    """Gate 0.5's declared half (D4 §3, including revision 3's clause (d))."""

    structure_type: StructureType
    r_basis_formula: str
    legs_per_structure: int
    leg_sign_pattern: tuple[int, ...]
    width_declared: float
    m_declared: int
    width_selected_adaptively: bool = False

    @property
    def r_scale_usd(self) -> float:
        return self.width_declared * self.m_declared


@dataclass(frozen=True, slots=True)
class OptionsSensitivitySummary:
    """Gate 5's result, computed by an options grid runner (not by this module).

    ``None`` in place of this object is an honest gate-5 **failure**, exactly as
    ``_sensitivity_plan`` returning ``None`` is on the equity side — never a skip.
    """

    n_points: int
    n_evaluable: int
    positive_fraction: float
    neighbour_positive_fraction: float
    fragile: bool
    axes: tuple[str, ...]
    reasons: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "n_points": self.n_points,
            "n_evaluable": self.n_evaluable,
            "positive_fraction": self.positive_fraction,
            "neighbour_positive_fraction": self.neighbour_positive_fraction,
            "fragile": self.fragile,
            "axes": list(self.axes),
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True, slots=True)
class BenchmarkPair:
    """Gate 7 and 7b's Sharpes, at both spread settings (D4 §4.1, §6.1, §6.2).

    Gate 7's market benchmark is computed from **raw proxy closes** and pays no
    cost at all (``promotion._benchmark_metrics``), so doubling the modelled
    spread moves the strategy's Sharpe and leaves the benchmark's untouched.
    That asymmetry is why gate 7 is gated at the stressed setting and is
    recorded here rather than left to a reader.
    """

    strategy_sharpe_baseline: float
    strategy_sharpe_stressed: float
    market_sharpe: float
    mechanical_sharpe_baseline: float | None
    mechanical_sharpe_stressed: float | None
    mechanical_n_trades: int
    mechanical_spec: Mapping[str, Any]
    eff_start: date
    eff_end: date
    proxy_symbol: str = "SPY"
    benchmark_pays_no_cost: bool = True


@dataclass(frozen=True, slots=True)
class OptionsDataQuality:
    """Gate 8's inputs: the two existing checks plus D4 §6.3's twelve additions."""

    data_validation_passed: bool
    data_validation_findings: tuple[str, ...]
    leakage_error: str | None
    chain_leakage_error: str | None
    corporate_action_exclusions: Mapping[str, int]
    synthetic_mark_fraction_trade_weighted: float
    pinned_fraction: float
    expectancy_excluding_pinned_r: float
    pinned_r_distribution: Mapping[str, float]
    clustered_bootstrap_ci: Mapping[str, float]
    clustering_unit: str = "(underlying, expiry cycle)"
    assignment_approximation_disclosed: bool = True
    assignment_risk_count: int = 0
    nbbo_unavailable_options: bool = True
    nbbo_unavailable_equities: bool = True
    forced_intrinsic_mark_fraction: float = 0.0
    thin_continuity_fraction: float = 0.0


@dataclass(frozen=True, slots=True)
class SealedOptionsOutcome:
    """Gate 9's input.  **Baseline cost model only** (D4 §4.3a rule 1).

    The stressed leg has no path to this type by construction: every
    constructor call asserts ``spread_multiplier == 1.0``, so a stressed run
    that tried to seal RAISES rather than sealing (D4 §4.3a rule 3).
    """

    window_start: date
    window_end: date
    n_trades: int
    expectancy_r: float
    spread_multiplier: float
    r_basis: RBasis
    metrics: Mapping[str, Any]
    benchmark: Mapping[str, Any]
    data_provenance: Mapping[str, Any]

    def __post_init__(self) -> None:
        if self.spread_multiplier != 1.0:
            raise SealedAtNonBaselineCost(
                "a sealed options record is always a BASELINE-cost record (D4 §4.3a rule 1); "
                f"refusing to seal at spread_multiplier={self.spread_multiplier!r}"
            )


class SealedAtNonBaselineCost(ValueError):
    """A stressed-cost run reached the sealed path.  Raise, never seal."""


# --------------------------------------------------------------------------- #
# gate 0.a - 0.i (fail-fast; D4 §2)
# --------------------------------------------------------------------------- #
def gate_0a_window(
    window: OptionsWindow, av: OptionsDataAvailability, th: OptionsGateThresholds
) -> OptionsGate:
    """Horizon and window arithmetic, plus Phase 1's 0DTE refusal.

    D4 §2.1's CORRECTION: gate 0's INTRADAY branch is a real coverage query
    since ``9b7e7c3``, not an unconditional fail, so an options ladder needs its
    own 0DTE rule.  There is no intraday option bar anywhere in the schema
    (``OptionAggregateDaily`` is daily-only), so an intraday or same-session
    structure would be priced entirely by model.
    """
    long_enough = (
        window.sealed_start > window.start and window.presealed_days >= th.min_presealed_days
    )
    intraday = av.horizon is Horizon.INTRADAY
    dte_ok = av.min_dte_at_entry_declared >= th.min_dte_at_entry
    passed = bool(long_enough and not intraday and dte_ok)
    reasons = []
    if not long_enough:
        reasons.append(
            f"pre-sealed span is {window.presealed_days}d, needs >= {th.min_presealed_days}d "
            f"before the {th.sealed_window_days}d sealed window"
        )
    if intraday:
        reasons.append(
            "an options strategy may not declare Horizon.INTRADAY in Phase 1 — there is no "
            "intraday option bar in the schema, so it would be priced entirely by model"
        )
    if not dte_ok:
        reasons.append(
            f"minimum admissible DTE at entry is {av.min_dte_at_entry_declared}, needs "
            f">= {th.min_dte_at_entry} (0DTE is refused outright in Phase 1)"
        )
    return OptionsGate(
        0,
        "data_availability_window",
        passed,
        "window and horizon admissible" if passed else "; ".join(reasons),
        {
            "window": window.to_dict(),
            "presealed_days": window.presealed_days,
            "min_presealed_days": th.min_presealed_days,
            "sealed_window_days": th.sealed_window_days,
            "horizon": av.horizon.value,
            "min_dte_at_entry_declared": av.min_dte_at_entry_declared,
            "min_dte_at_entry": th.min_dte_at_entry,
        },
        label="0.a",
    )


def gate_0b_underlyings(av: OptionsDataAvailability) -> OptionsGate:
    """Every underlying is continuously covered from ONE source (R6).

    A blended or bridged underlying must fail here, *before* gate 8 sees it:
    gate 0 is fail-fast and gate 8 is never reached.
    """
    sources = sorted({u.source for u in av.underlyings})
    single_source = sources == [av.required_source]
    gapped = [u.symbol for u in av.underlyings if u.gap_sessions > 0]
    missing_bars = [u.symbol for u in av.underlyings if u.first_bar is None or u.last_bar is None]
    passed = bool(av.underlyings) and single_source and not gapped and not missing_bars
    reasons = []
    if not av.underlyings:
        reasons.append("no underlying passed coverage")
    if not single_source:
        reasons.append(f"sources {sources} != [{av.required_source!r}] — R6 forbids a blend")
    if gapped:
        reasons.append(f"gap sessions in {gapped}")
    if missing_bars:
        reasons.append(f"no bars at all for {missing_bars}")
    return OptionsGate(
        0,
        "data_availability_underlyings",
        passed,
        (
            f"{len(av.underlyings)} underlyings continuous on {av.required_source!r}"
            if passed
            else "; ".join(reasons)
        ),
        {
            "underlyings": [u.to_dict() for u in av.underlyings],
            "underlying_source": av.required_source,
            "underlying_sources_observed": sources,
        },
        label="0.b",
    )


def gate_0c_bracketing(av: OptionsDataAvailability, th: OptionsGateThresholds) -> OptionsGate:
    """Cycle bracketing, reported as a MATRIX and gated on the declared cells.

    D4 §2.3: the denominator is **strategy-independent** — a cycle is eligible
    iff its underlying passes 0.b over that cycle and its expiry falls inside the
    evaluation window.  Neither the regime filter, nor the DTE window, nor the
    delta target, nor the width enters it; ``dte_target`` is a declared grid axis,
    and a denominator that moved with it would be computed differently in every
    grid cell.
    """
    aggregate = av.bracket_fraction
    failing_cells: list[str] = []
    for dte, side in av.bracket_gated_cells:
        cell = av.bracket_fraction_matrix.get(str(dte), {}).get(side)
        if cell is None or cell < th.bracket_fraction_min:
            failing_cells.append(f"{dte}/{side}={'absent' if cell is None else f'{cell:.3f}'}")
    passed = bool(
        av.cycles_eligible > 0 and aggregate >= th.bracket_fraction_min and not failing_cells
    )
    return OptionsGate(
        0,
        "data_availability_bracketing",
        passed,
        (
            f"{av.cycles_bracketed}/{av.cycles_eligible} eligible cycles bracket the structure "
            f"({aggregate:.3f}, need >= {th.bracket_fraction_min:.2f})"
            + (
                f"; gated cells below the floor: {', '.join(failing_cells)}"
                if failing_cells
                else ""
            )
        ),
        {
            "cycles_eligible": av.cycles_eligible,
            "cycles_bracketed": av.cycles_bracketed,
            "bracket_fraction": round(aggregate, 6),
            "bracket_fraction_matrix": {k: dict(v) for k, v in av.bracket_fraction_matrix.items()},
            "bracket_fraction_min": th.bracket_fraction_min,
            "bracket_fraction_gated_cells": [list(c) for c in av.bracket_gated_cells],
            "bracket_fraction_failing_cells": failing_cells,
            "eligible_cycle_definition": av.eligible_cycle_definition,
            "bracket_failures_by_underlying": dict(av.bracket_failures_by_underlying),
            "bracket_failures_by_side": dict(av.bracket_failures_by_side),
        },
        label="0.c",
    )


def gate_0d_continuity(av: OptionsDataAvailability, th: OptionsGateThresholds) -> OptionsGate:
    """Per-leg bar continuity.  A missing bar is a liquidity fact, never a fill.

    D4 §2.4: entry on a session where any leg lacks a bar is a **non-entry**; an
    exit signalled on such a session is **deferred**.  So this fraction measures
    *mark* coverage, not *fill* coverage, and there is no "synthetic fill
    fraction" anywhere because the model must not be able to express one.
    """
    passed = av.bar_continuity_min_observed >= th.bar_continuity_min
    return OptionsGate(
        0,
        "data_availability_bar_continuity",
        passed,
        (
            f"per-leg bar continuity min {av.bar_continuity_min_observed:.3f}, median "
            f"{av.bar_continuity_median:.3f} (need >= {th.bar_continuity_min:.2f} per leg); "
            f"{av.non_entry_count} non-entries, {av.gap_sessions} gap sessions"
        ),
        {
            "bar_continuity_min_observed": av.bar_continuity_min_observed,
            "bar_continuity_median": av.bar_continuity_median,
            "bar_continuity_min": th.bar_continuity_min,
            "thin_continuity_floor": th.thin_continuity_floor,
            "non_entry_count": av.non_entry_count,
            "non_entry_reasons": dict(av.non_entry_reasons),
            "exit_deferral_histogram": dict(av.exit_deferral_histogram),
            "gap_sessions": av.gap_sessions,
            "synthetic_fill_fraction": None,
            "synthetic_fill_note": (
                "absent by construction — map §2.4(3) forbids synthetic fills, so the model "
                "cannot express one"
            ),
        },
        label="0.d",
    )


def gate_0e_iv_provenance(av: OptionsDataAvailability, th: OptionsGateThresholds) -> OptionsGate:
    """Every trade's IV/delta came from one of four NAMED paths, and no other.

    D5 §2.4 pre-registers ``pct_otm_proxy`` as **never** admissible for this
    family, so its ceiling is 0.0 — a stricter reading than D4 §2.5's "recorded
    and capped", and tightening is R4-clean.
    """
    proxy_fraction = float(av.iv_source_mix.get("pct_otm_proxy", 0.0))
    total = sum(float(v) for v in av.iv_source_mix.values())
    sums_to_one = av.iv_source_mix == {} or abs(total - 1.0) <= 1e-9
    surface_ok = av.surface_n_actual_min >= th.surface_n_floor
    passed = bool(
        av.iv_source_unnamed_count == 0
        and proxy_fraction <= th.pct_otm_proxy_max_fraction
        and sums_to_one
        and surface_ok
    )
    reasons = []
    if av.iv_source_unnamed_count:
        reasons.append(f"{av.iv_source_unnamed_count} trades used an UNNAMED IV path")
    if proxy_fraction > th.pct_otm_proxy_max_fraction:
        reasons.append(
            f"pct_otm_proxy covered {proxy_fraction:.3f} of trades, ceiling "
            f"{th.pct_otm_proxy_max_fraction:.3f}"
        )
    if not sums_to_one:
        reasons.append(f"iv_source_mix sums to {total:.6f}, not 1.0")
    if not surface_ok:
        reasons.append(
            f"same-session surface fitted from {av.surface_n_actual_min} prints, floor "
            f"{th.surface_n_floor}"
        )
    return OptionsGate(
        0,
        "data_availability_iv_provenance",
        passed,
        "every IV came from a named path" if passed else "; ".join(reasons),
        {
            "iv_source_mix": dict(av.iv_source_mix),
            "iv_source_unnamed_count": av.iv_source_unnamed_count,
            "pct_otm_proxy_max_fraction": th.pct_otm_proxy_max_fraction,
            "surface_n_floor": th.surface_n_floor,
            "surface_min_distinct_strikes": th.surface_min_distinct_strikes,
            "surface_n_actual_min": av.surface_n_actual_min,
            "realised_vol_fallback": False,
        },
        label="0.e",
    )


def gate_0f_fill_provenance(av: OptionsDataAvailability) -> OptionsGate:
    """The NBBO disclosure and the COMPLETE, frozen ``OptionCostModel``.

    D4 §2.6's correction: recording only the two spread constants left out the
    commissions and fees, which on a $0.50 credit over a $5 width are a
    double-digit percentage of the credit and therefore of gate 3's expectancy
    and gate 4's CI lower bound.  Every field is emitted, no default elided, and
    a constant may only ever be **raised**.
    """
    cm = av.cost_model
    model = {
        "commission_per_contract": cm.commission_per_contract,
        "commission_min_per_order": cm.commission_min_per_order,
        "exchange_fee_per_contract": cm.exchange_fee_per_contract,
        "spread_pct_of_last_print": cm.spread_pct_of_last_print,
        "spread_abs_floor_cents": cm.spread_abs_floor_cents,
        "tick_grid": [[t, v] for t, v in cm.tick_grid],
        "assignment_fee": cm.assignment_fee,
        "exercise_fee": cm.exercise_fee,
        "spread_multiplier": cm.spread_multiplier,
    }
    frozen = bool(av.cost_model_frozen_at)
    disclosed = bool(av.fill_model) and av.entitlement_batches_checked > 0
    passed = frozen and disclosed
    reasons = []
    if not frozen:
        reasons.append("option_cost_model_frozen_at is empty — the constants are not frozen")
    if not disclosed:
        reasons.append("the fill model / entitlement disclosure is incomplete")
    return OptionsGate(
        0,
        "data_availability_fill_provenance",
        passed,
        (
            "NBBO unavailable for options AND equities (403); spread is modelled, not observed; "
            f"cost model frozen at {av.cost_model_frozen_at}"
            if passed
            else "; ".join(reasons)
        ),
        {
            "nbbo_available_options": False,
            "nbbo_available_equities": False,
            "entitlement_batches_checked": av.entitlement_batches_checked,
            "fill_model": av.fill_model,
            "spread_pct_of_last_print": cm.spread_pct_of_last_print,
            "spread_abs_floor_cents": cm.spread_abs_floor_cents,
            "spread_multiple": cm.spread_multiplier,
            "option_cost_model": model,
            "option_cost_model_frozen_at": av.cost_model_frozen_at,
            "cost_per_structure_roundtrip_usd": dict(av.cost_per_structure_roundtrip_usd),
            "raisable_never_lowerable": True,
        },
        label="0.f",
    )


def gate_0g_dividend_yield(av: OptionsDataAvailability) -> OptionsGate:
    """``q`` is sourced and recorded per underlying; a DEFAULTED ``q`` fails.

    D4 §2.7's distinction, which the evidence must preserve: a *recorded,
    sourced* ``q = 0.0`` for a genuinely non-dividend-paying underlying is a
    pass; an *unset* ``q`` that fell through ``blackscholes``' default is a fail.
    That is why the field is a ``(value, source, as_of)`` triple, not a float.
    """
    untyped = [
        sym
        for sym, rec in av.q_by_underlying.items()
        if not rec.get("source") or rec.get("value") is None
    ]
    covered = {u.symbol for u in av.underlyings} <= set(av.q_by_underlying)
    passed = bool(av.q_defaulted_count == 0 and not untyped and covered and av.q_by_underlying)
    reasons = []
    if av.q_defaulted_count:
        reasons.append(f"{av.q_defaulted_count} evaluations used a DEFAULTED q")
    if untyped:
        reasons.append(f"q recorded without a source for {sorted(untyped)}")
    if not covered:
        missing = sorted({u.symbol for u in av.underlyings} - set(av.q_by_underlying))
        reasons.append(f"no q at all for {missing}")
    if not av.q_by_underlying:
        reasons.append("no dividend series is recorded for any underlying")
    return OptionsGate(
        0,
        "data_availability_dividend_yield",
        passed,
        "q sourced and recorded per underlying" if passed else "; ".join(reasons),
        {
            "q_by_underlying": {k: dict(v) for k, v in av.q_by_underlying.items()},
            "q_defaulted_count": av.q_defaulted_count,
        },
        label="0.g",
    )


def gate_0h_deliverable(av: OptionsDataAvailability) -> OptionsGate:
    """Every traded contract had ``shares_per_contract == 100`` at entry.

    Zero refusals today, which is exactly why the check is written now while it
    is free rather than after the first split produces a 10-share deliverable
    and a 10x P&L error.
    """
    passed = av.deliverable_refusal_count == 0
    return OptionsGate(
        0,
        "data_availability_deliverable",
        passed,
        (
            "every traded contract delivered 100 shares"
            if passed
            else f"{av.deliverable_refusal_count} contracts refused for shares_per_contract != 100"
        ),
        {
            "deliverable_refusal_count": av.deliverable_refusal_count,
            "deliverable_refusals": [dict(r) for r in av.deliverable_refusals],
            "require_shares_per_contract": 100,
        },
        label="0.h",
    )


def gate_0i_risk_limits(av: OptionsDataAvailability, th: OptionsGateThresholds) -> OptionsGate:
    """The evaluated population must FIT the pre-registered arming limits (D4 §2.8a).

    Without this the ladder certifies an R stream the arming limits refuse, and
    the first thing anyone wants to move after a pass is the limit.  That is the
    R1/R4 move the ladder exists to block, arrived at by omission.  At decision
    #4's $250 per-structure cap, two of D5's three declared widths breach
    unconditionally — a decision to take **now**, in the open, not a measurement
    to wait for.
    """
    fits_per_structure = av.r_max_observed_usd <= th.options_per_structure_max_loss
    fits_aggregate = av.concurrent_open_r_max_usd <= th.options_total_open_max_loss
    no_breaches = av.structures_breaching_per_structure_cap == 0
    hashed = av.limits_in_options_config_hash
    passed = bool(fits_per_structure and fits_aggregate and no_breaches and hashed)
    reasons = []
    if not fits_per_structure:
        reasons.append(
            f"max R per structure ${av.r_max_observed_usd:,.2f} exceeds the pre-registered "
            f"per-structure cap ${th.options_per_structure_max_loss:,.2f}"
        )
    if not fits_aggregate:
        reasons.append(
            f"max concurrent open R ${av.concurrent_open_r_max_usd:,.2f} exceeds the aggregate "
            f"cap ${th.options_total_open_max_loss:,.2f}"
        )
    if not no_breaches:
        reasons.append(
            f"{av.structures_breaching_per_structure_cap} structures breach the per-structure cap"
        )
    if not hashed:
        reasons.append("the limit set is NOT inside options_config_hash — it can move silently")
    return OptionsGate(
        0,
        "data_availability_risk_limit_fit",
        passed,
        (
            "the evaluated population fits the pre-registered arming limits"
            if passed
            else "; ".join(reasons)
        ),
        {
            "options_per_structure_max_loss": th.options_per_structure_max_loss,
            "options_total_open_max_loss": th.options_total_open_max_loss,
            "account_equity_basis": th.account_equity_basis,
            "r_max_observed_usd": av.r_max_observed_usd,
            "r_max_by_width": dict(av.r_max_by_width),
            "concurrent_open_r_max_usd": av.concurrent_open_r_max_usd,
            "structures_breaching_per_structure_cap": av.structures_breaching_per_structure_cap,
            "width_grid_declared": list(av.width_grid_declared),
            "limits_source": av.limits_source,
            "limits_in_options_config_hash": av.limits_in_options_config_hash,
        },
        label="0.i",
    )


# --------------------------------------------------------------------------- #
# gate 0.5 — one structure type, one R scale, per version (D4 §3)
# --------------------------------------------------------------------------- #
def gate_0_5_structure(identity: StructureIdentity, trades: Sequence[OptionTrade]) -> OptionsGate:
    """One ``structure_type`` **and one R scale** per strategy version.

    Clauses (a)-(c) of D4 §3 are purely formal and re-admit at 3.3x the
    incomparability this gate exists to prevent: every short vertical is one
    ``structure_type`` regardless of width, but ``R = width x M - credit``, so a
    3-wide and a 10-wide differ 3.3x in dollars at risk inside one pooled R
    stream and ``bootstrap_ci`` cannot see it.  Clause (d) is what closes it:
    ``width`` is a declared constant, evaluated one value per run, never
    selected per trade.
    """
    observed_types = sorted({t.structure_type.value for t in trades})
    observed_widths = sorted(
        {round(t.r_at_print + t.net_credit_at_print, 6) for t in trades}
    )  # width x M x C, recovered from the R identity
    r_values = [t.r_incl for t in trades]
    dispersion = (max(r_values) / min(r_values)) if r_values and min(r_values) > 0 else 0.0
    single_type = observed_types in ([], [identity.structure_type.value])
    single_scale = len(observed_widths) <= 1
    declared_scale = identity.r_scale_usd
    scale_matches = not observed_widths or math.isclose(
        observed_widths[0], declared_scale, rel_tol=1e-6
    )
    passed = bool(
        single_type and single_scale and scale_matches and not identity.width_selected_adaptively
    )
    reasons = []
    if not single_type:
        reasons.append(
            f"more than one structure_type in the trade list: {observed_types} — R is max loss "
            "and max loss is a property of the structure"
        )
    if not single_scale:
        reasons.append(f"more than one R scale observed: {observed_widths}")
    if observed_widths and not scale_matches:
        reasons.append(
            f"observed R scale ${observed_widths[0]:,.2f} != declared width x M "
            f"${declared_scale:,.2f}"
        )
    if identity.width_selected_adaptively:
        reasons.append(
            "width is selected adaptively — the R stream has no fixed scale, so gates 3 and 4 "
            "would be computed on a unit that moves with the data"
        )
    return OptionsGate(
        0,
        "structure_singularity",
        passed,
        (
            f"{identity.structure_type.value}, {identity.legs_per_structure} legs, R scale "
            f"${declared_scale:,.2f} ({len(trades)} trades)"
            if passed
            else "; ".join(reasons)
        ),
        {
            "structure_type": identity.structure_type.value,
            "r_basis_formula": identity.r_basis_formula,
            "structure_types_observed": observed_types,
            "legs_per_structure": identity.legs_per_structure,
            "leg_sign_pattern": list(identity.leg_sign_pattern),
            "width_declared": identity.width_declared,
            "widths_observed": observed_widths,
            "m_declared": identity.m_declared,
            "r_scale_usd": declared_scale,
            "r_scale_dispersion": round(dispersion, 6),
            "width_selected_adaptively": identity.width_selected_adaptively,
            "incomparability_notice": (
                "this R stream may not be pooled, averaged, bootstrapped together, or compared "
                "with any other structure's R stream, or with the equity R stream"
            ),
        },
        label="0.5",
    )


# --------------------------------------------------------------------------- #
# gates 1-4 on the options stream
# --------------------------------------------------------------------------- #
def gate_1_walkforward(
    folds: Sequence[Mapping[str, Any]], th: OptionsGateThresholds
) -> OptionsGate:
    with_edge = sum(
        1
        for f in folds
        if int(f["n_trades"]) >= th.min_fold_trades
        and float(f["expectancy_r"]) > th.min_net_expectancy_r
    )
    need = max(1, th.min_walkforward_folds // 2)
    passed = bool(len(folds) >= th.min_walkforward_folds and with_edge >= need)
    return OptionsGate(
        1,
        "rolling_walkforward",
        passed,
        (
            f"{len(folds)} rolling folds over the pre-sealed span, {with_edge} clearing both a "
            f"per-fold trade floor (>={th.min_fold_trades}) and positive expectancy "
            f"(need >= {need} of {th.min_walkforward_folds})"
        ),
        {"folds": [dict(f) for f in folds], "min_fold_trades": th.min_fold_trades},
    )


def gate_2_oos_trades(n_oos: int, th: OptionsGateThresholds) -> OptionsGate:
    passed = n_oos >= th.min_oos_trades
    return OptionsGate(
        2,
        "min_oos_trades",
        passed,
        f"{n_oos} out-of-sample structures (threshold {th.min_oos_trades}, fixed before this run)",
        {"n_oos_trades": n_oos, "threshold": th.min_oos_trades},
    )


def gate_3_expectancy(expectancy_r: float, basis: str, th: OptionsGateThresholds) -> OptionsGate:
    passed = expectancy_r > th.min_net_expectancy_r
    return OptionsGate(
        3,
        "net_expectancy",
        passed,
        (
            f"OOS expectancy {expectancy_r:+.4f}R on the {basis} basis, UNCLAMPED series, net of "
            f"the modelled per-leg-per-side spread; need > {th.min_net_expectancy_r:+.4f}R"
        ),
        {
            "expectancy_r": expectancy_r,
            "threshold": th.min_net_expectancy_r,
            "r_basis": basis,
            "series_basis": "unclamped",
        },
    )


def gate_4_bootstrap(ci_low: float, basis: str, th: OptionsGateThresholds) -> OptionsGate:
    passed = ci_low > th.min_bootstrap_ci_low_r
    return OptionsGate(
        4,
        "bootstrap_ci",
        passed,
        (
            f"95% bootstrap CI lower bound {ci_low:+.4f}R on the {basis} basis; need > "
            f"{th.min_bootstrap_ci_low_r:+.4f}R (materially above zero, not merely non-negative)"
        ),
        {
            "ci_low_r": ci_low,
            "threshold": th.min_bootstrap_ci_low_r,
            "r_basis": basis,
            "series_basis": "unclamped",
            "iid_caveat": (
                "bootstrap_ci resamples iid; options cycles on one underlying are more "
                "correlated than equity swing trades, so this CI is too narrow — the clustered "
                "CI is reported at gate 8"
            ),
        },
    )


# --------------------------------------------------------------------------- #
# gate 4b — dual spread on the OPTIONS stream (D4 §4)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class StressedOos:
    """The OOS triple at the stressed setting, on the ``R_incl`` basis.

    Gates 2/3/4 read ``full.out_of_sample`` while the four-way surface is computed
    over the whole run, so 4b would otherwise compare an OOS threshold against a
    whole-sample count.  Under D5 §6.2c **form (a)** the stressed run re-prices
    the *same* trades, so ``n_trades`` must equal the baseline OOS count — and a
    mismatch is not a rounding detail, it means form (b)'s re-selection leaked
    into the gating path.  :func:`gate_4b_dual_spread` checks it.
    """

    n_trades: int
    expectancy_r: float
    ci_low_r: float


def gate_4b_dual_spread(
    dual: DualSpreadReport,
    bench: BenchmarkPair,
    th: OptionsGateThresholds,
    *,
    baseline_oos: StressedOos,
    stressed_oos: StressedOos,
    equity_diagnostic_ref: str = "",
) -> OptionsGate:
    """Gates 2, 3, 4, **7 and 7b** must clear at the stressed setting too.

    D4 §4.1's revision-3 correction: gate 7 was the one comparison exempted from
    the cost stress, and it is the one with a **cost-free benchmark** —
    ``_benchmark_metrics`` builds its return series from raw proxy closes with no
    commission, no slippage and no spread, so doubling the modelled spread moves
    the strategy's Sharpe and leaves the benchmark's untouched.  A strategy that
    cleared gate 7 at baseline and failed it at 2x would have been recorded as 4b
    evidence and promoted anyway.

    The equity application stays a **documented pre-sealed disposition input**
    (D4 §4.5 steps 3-4): no equity gate, threshold, sealed row or ladder-shape
    assertion moves here, and this gate reads the options stream only.
    """
    s_exp = stressed_oos.expectancy_r
    s_ci = stressed_oos.ci_low_r
    g2 = stressed_oos.n_trades >= th.min_oos_trades
    g3 = s_exp > th.min_net_expectancy_r
    g4 = s_ci > th.min_bootstrap_ci_low_r
    g7 = (not th.require_beat_benchmark_sharpe) or (
        bench.strategy_sharpe_stressed > bench.market_sharpe
    )
    mech_s = bench.mechanical_sharpe_stressed
    g7b = mech_s is not None and bench.strategy_sharpe_stressed > mech_s
    selection_frozen = stressed_oos.n_trades == baseline_oos.n_trades
    passed = bool(g2 and g3 and g4 and g7 and g7b and selection_frozen)
    failed = [n for n, ok in (("2", g2), ("3", g3), ("4", g4), ("7", g7), ("7b", g7b)) if not ok]
    if not selection_frozen:
        failed.append("form-(a) selection freeze")
    return OptionsGate(
        4,
        "dual_spread_pass",
        passed,
        (
            f"at spread_multiple 2.0 on the {DualSpreadReport.BINDING_KEY} basis: "
            f"{stressed_oos.n_trades} OOS structures, expectancy {s_exp:+.4f}R, CI low "
            f"{s_ci:+.4f}R, Sharpe {bench.strategy_sharpe_stressed:+.2f} vs market "
            f"{bench.market_sharpe:+.2f} and mechanical "
            f"{mech_s if mech_s is None else f'{mech_s:+.2f}'}"
            + ("" if passed else f" — {', '.join(failed)} FAIL at the stressed setting")
        ),
        {
            "spread_multiple_baseline": 1.0,
            "spread_multiple_stressed": 2.0,
            "applied_to": "options",
            "spread_source": "modelled — NBBO 403 on options AND equities",
            "gated_at_stressed": ["2", "3", "4", "7", "7b"],
            "reported_only_at_stressed": ["1", "5", "6", "6b"],
            "baseline": {
                "n_oos_trades": baseline_oos.n_trades,
                "expectancy_r": baseline_oos.expectancy_r,
                "ci_low_r": baseline_oos.ci_low_r,
                "strategy_sharpe": bench.strategy_sharpe_baseline,
                "mechanical_sharpe": bench.mechanical_sharpe_baseline,
            },
            "stressed": {
                "n_oos_trades": stressed_oos.n_trades,
                "expectancy_r": s_exp,
                "ci_low_r": s_ci,
                "strategy_sharpe": bench.strategy_sharpe_stressed,
                "mechanical_sharpe": mech_s,
                "gate2": g2,
                "gate3": g3,
                "gate4": g4,
                "gate7": g7,
                "gate7b": g7b,
            },
            "market_sharpe": bench.market_sharpe,
            "benchmark_pays_no_cost": bench.benchmark_pays_no_cost,
            "dual_spread_surface": dual.to_dict(),
            "selection_frozen_form_a": selection_frozen,
            "selection_frozen_note": (
                "D5 §6.2c form (a): the strategy's credit floor and strike selection are priced "
                "with the BASELINE cost model in both runs, so the 2x run re-prices the same "
                "trades rather than re-selecting a credit-richer subsample. An OOS count that "
                "differs between the two settings means form (b) leaked into the gating path"
            ),
            "equity_application": (
                "DOCUMENTED PRE-SEALED DISPOSITION INPUT ONLY — no equity gate, threshold, "
                "sealed row or ladder-shape assertion is changed by this ladder"
            ),
            "equity_diagnostic_ref": equity_diagnostic_ref,
        },
        label="4b",
    )


# --------------------------------------------------------------------------- #
# gate 5
# --------------------------------------------------------------------------- #
def gate_5_sensitivity(
    sens: OptionsSensitivitySummary | None, th: OptionsGateThresholds
) -> OptionsGate:
    if sens is None:
        return OptionsGate(
            5,
            "parameter_sensitivity",
            False,
            (
                "no options parameter-sensitivity grid was run for this version — robustness "
                "cannot be verified, so it cannot pass"
            ),
            {"grid_run": False},
        )
    evaluable_ok = sens.n_evaluable >= th.sensitivity_min_evaluable
    passed = bool(not sens.fragile and evaluable_ok)
    reasons = list(sens.reasons)
    if not evaluable_ok:
        reasons.append(
            f"only {sens.n_evaluable} of {sens.n_points} grid points were evaluable; the "
            f"pre-registered floor is {th.sensitivity_min_evaluable} — a grid where most cells "
            "are too thin can report '100% positive' off a handful of cells"
        )
    return OptionsGate(
        5,
        "parameter_sensitivity",
        passed,
        (
            f"{sens.n_evaluable}/{sens.n_points} grid points evaluable, "
            f"{sens.positive_fraction:.0%} positive, "
            f"{sens.neighbour_positive_fraction:.0%} of one-step neighbours positive"
            + (f"; {'; '.join(reasons)}" if reasons else "")
        ),
        {**sens.to_dict(), "min_evaluable": th.sensitivity_min_evaluable, "grid_run": True},
    )


# --------------------------------------------------------------------------- #
# gate 6 and 6b — the census on backtest/regime.py's own labels (D4 §5)
# --------------------------------------------------------------------------- #
def gate_6_regime(
    census: JointRegimeCensus,
    th: OptionsGateThresholds,
    partition: RegimePartitionDisclosure,
) -> OptionsGate:
    """Bull / bear / range coverage, with the two-partition mismatch DISCLOSED.

    ``partition`` is required, not optional.  D4 §5.1a: the strategy filters on
    ``research/regime.py``'s trend (D5 §3.2 pre-registers it) while the census
    reads ``backtest/regime.py``'s labels, and those are different partitions — a
    cycle the call-side mirror fires on can be counted ``range`` by the census
    whenever the proxy close sits inside the +/-3% SMA band.  Gate-6 reachability
    is what decided O3 ships before O1, so the mismatch is evidence the gate
    carries rather than a caveat a reader has to remember.

    No threshold moves: the pass computation is ``covered >= min_regimes_covered``
    exactly as the equity gate computes it.
    """
    buckets = census.trend_buckets
    covered = sum(1 for c in buckets.values() if c >= th.min_trades_per_regime)
    passed = covered >= th.min_regimes_covered
    return OptionsGate(
        6,
        "regime_coverage",
        passed,
        (
            f"structures per regime — bull {buckets['bull']}, bear {buckets['bear']}, "
            f"range {buckets['range']} (need >= {th.min_trades_per_regime} each in "
            f"{th.min_regimes_covered} of 3; {covered}/3 met); census labels from "
            f"{census.regime_label_source}, signal labels from "
            f"{partition.signal_label_source} — {partition.mismatch_fraction:.1%} of "
            "signal-bear sessions are counted `range` by the census"
        ),
        {
            "trades_per_regime": dict(buckets),
            "min_trades_per_regime": th.min_trades_per_regime,
            "min_regimes_covered": th.min_regimes_covered,
            "n_trades_considered": census.n_trades,
            **partition.to_dict(),
            "regime_partition_note": (
                "D4 §5.1a option (b): D5 §3.2 pre-registers research/regime.py for the filter, "
                "so the filter and the census read DIFFERENT partitions and the cross-tab above "
                "is mandatory gate-6 evidence. The call-side mirror is a NECESSARY condition for "
                "bear-bucket trades and is not by itself a SUFFICIENT one"
            ),
            "census_closes": census.census_closes,
            "unbucketed": {
                "warmup": census.warmup,
                "no_proxy_bar": census.no_proxy_bar,
                "unlabelled": census.unlabelled,
            },
        },
    )


def gate_6b_joint(census: JointRegimeCensus, th: OptionsGateThresholds) -> OptionsGate:
    """Joint trend x vol, on the five labels ``backtest/regime.py`` actually emits.

    D4 §5.1's CORRECTION C1: map §5 says "3 trend x 2 vol = 6 cells"; the code
    short-circuits on ``range_bound`` **before** the vol label is attached
    (``regime.py:59-62``), so there are **five** non-warmup labels and the range
    cell carries no vol label at all.  It therefore contributes to NEITHER vol
    marginal, and saying so is a gate-6b evidence field rather than a footnote.

    ``>= 10`` marginal / ``>= 5`` joint rather than ``>= 10`` everywhere:
    ``bear_lowvol`` is rare by construction, and a flat floor would fail on that
    one cell with ample total trades — a rule that gets abandoned the first time
    it binds is worse than no rule.
    """
    marg = census.vol_marginals
    joint = census.joint_cells
    marg_ok = {k: v >= th.min_vol_marginal_trades for k, v in marg.items()}
    joint_ok = {k: v >= th.min_joint_cell_trades for k, v in joint.items()}
    passed = bool(all(marg_ok.values()) and all(joint_ok.values()) and census.census_closes)
    thin = [k for k, ok in {**marg_ok, **joint_ok}.items() if not ok]
    return OptionsGate(
        6,
        "regime_coverage_joint",
        passed,
        (
            f"vol marginals highvol {marg['highvol']} / lowvol {marg['lowvol']} "
            f"(need >= {th.min_vol_marginal_trades} each); joint cells "
            + ", ".join(f"{k} {v}" for k, v in sorted(joint.items()))
            + f" (need >= {th.min_joint_cell_trades} each); range_bound "
            f"{census.range_bound_count}, vol-UNLABELLED by construction and in neither marginal"
            + (f"; thin: {', '.join(sorted(thin))}" if thin else "")
            + ("" if census.census_closes else "; CENSUS DOES NOT CLOSE")
        ),
        {
            **census.to_dict(),
            "min_joint_cell_trades": th.min_joint_cell_trades,
            "min_vol_marginal_trades": th.min_vol_marginal_trades,
            "range_bound_vol_labelled_citation": "backtest/regime.py:59-62",
            "thin_cells": sorted(thin),
        },
        label="6b",
    )


# --------------------------------------------------------------------------- #
# gate 7 and 7b (D4 §6.1, §6.2)
# --------------------------------------------------------------------------- #
def gate_7_benchmark(bench: BenchmarkPair, th: OptionsGateThresholds) -> OptionsGate:
    """KEPT, never replaced.  Replacing it with 7b is a relaxation in costume.

    A short-premium strategy can beat a mechanical premium-harvest benchmark
    while losing to simply holding SPY; dropping the market benchmark removes
    exactly the comparison that would catch it (D4 §6.1).
    """
    passed = bool(
        (not th.require_beat_benchmark_sharpe)
        or bench.strategy_sharpe_baseline > bench.market_sharpe
    )
    return OptionsGate(
        7,
        "benchmark_comparison",
        passed,
        (
            f"strategy Sharpe {bench.strategy_sharpe_baseline:+.2f} vs {bench.proxy_symbol} "
            f"buy-and-hold Sharpe {bench.market_sharpe:+.2f} over the matched span "
            f"{bench.eff_start}..{bench.eff_end} — risk-adjusted, not cumulative return alone"
        ),
        {
            "strategy_sharpe": bench.strategy_sharpe_baseline,
            "benchmark_sharpe_market": bench.market_sharpe,
            "span": {
                "eff_start": bench.eff_start.isoformat(),
                "eff_end": bench.eff_end.isoformat(),
            },
            "trade_set": "ALL pre-sealed structures, in-sample and out-of-sample together",
            "standing_caveat": (
                "the market benchmark pays NO commission, slippage or spread, so this comparison "
                "is the most cost-sensitive in the ladder — which is why gate 4b gates it at the "
                "stressed setting"
            ),
        },
    )


def gate_7b_mechanical(bench: BenchmarkPair) -> OptionsGate:
    """Does the SIGNAL add anything over mechanical premium harvest?

    The mechanical configuration is **one** configuration, named in D5 §7 before
    any outcome was looked at.  Choosing it afterwards — picking the weakest
    variant — turns 7b from a test into a rubber stamp, and R1 covers that: the
    benchmark definition is a design choice and may not be informed by any
    outcome, sealed or pre-sealed.
    """
    mech = bench.mechanical_sharpe_baseline
    if mech is None:
        return OptionsGate(
            7,
            "mechanical_benchmark",
            False,
            (
                "the pre-registered mechanical benchmark was not run — 7b cannot pass on an "
                "un-run comparison"
            ),
            {"mechanical_run": False, "mechanical_spec": dict(bench.mechanical_spec)},
            label="7b",
        )
    passed = bench.strategy_sharpe_baseline > mech
    return OptionsGate(
        7,
        "mechanical_benchmark",
        passed,
        (
            f"strategy Sharpe {bench.strategy_sharpe_baseline:+.2f} vs the pre-registered "
            f"mechanical structure's {mech:+.2f} on {bench.mechanical_n_trades} structures — "
            "the benchmark differs in exactly one thing, the regime filter, which is the only "
            "thing this strategy claims"
        ),
        {
            "mechanical_run": True,
            "strategy_sharpe": bench.strategy_sharpe_baseline,
            "benchmark_sharpe_mechanical": mech,
            "benchmark_sharpe_market": bench.market_sharpe,
            "mechanical_spec": dict(bench.mechanical_spec),
            "mechanical_n_trades": bench.mechanical_n_trades,
            "span": {
                "eff_start": bench.eff_start.isoformat(),
                "eff_end": bench.eff_end.isoformat(),
            },
            "both_pass": bool(passed and bench.strategy_sharpe_baseline > bench.market_sharpe),
        },
        label="7b",
    )


# --------------------------------------------------------------------------- #
# gate 8 (D4 §6.3)
# --------------------------------------------------------------------------- #
def gate_8_data_quality(
    dq: OptionsDataQuality,
    dual: DualSpreadReport,
    th: OptionsGateThresholds,
) -> OptionsGate:
    """The two existing checks, plus D4 §6.3's twelve fields.

    Four of the additions are pass/fail and **all four can fail on data that
    cleared gate 0**: the trade-weighted synthetic-mark fraction (item 3, which
    at D4 revision 1's 0.20 was non-binding by construction against gate 0.d's
    own 0.80 per-leg floor), the clamp fraction (item 7), the stop-non-binding
    fraction of LOSING trades (item 9), and the pinned-trade falsification
    condition (item 8 — the expectancy sign must survive removing them).
    """
    counters = dual.baseline.counters
    n_trades = len(dual.baseline.trades)
    n_losers = counters.n_losing_trades
    clamp_frac = counters.r_clamped / n_trades if n_trades else 0.0
    stop_all = counters.stop_non_binding / n_trades if n_trades else 0.0
    stop_losers = counters.stop_non_binding / n_losers if n_losers else 0.0
    baseline_exp = dual.cells["incl@1x"].metrics.expectancy_r
    pinned_sign_survives = (baseline_exp <= 0.0) or (dq.expectancy_excluding_pinned_r > 0.0)

    validation_ok = dq.data_validation_passed
    leak_ok = dq.leakage_error is None and dq.chain_leakage_error is None
    synth_ok = dq.synthetic_mark_fraction_trade_weighted <= th.synthetic_mark_fraction_max
    clamp_ok = clamp_frac <= th.r_clamped_fraction_max
    stop_ok = stop_losers <= th.stop_non_binding_of_losers_max
    pinned_ok = pinned_sign_survives and dq.pinned_fraction <= th.pinned_fraction_max
    passed = bool(validation_ok and leak_ok and synth_ok and clamp_ok and stop_ok and pinned_ok)

    reasons = []
    if not validation_ok:
        reasons.append(f"validate_daily FAIL ({'; '.join(dq.data_validation_findings)})")
    if dq.leakage_error is not None:
        reasons.append(f"equity leakage self-check: {dq.leakage_error}")
    if dq.chain_leakage_error is not None:
        reasons.append(f"chain leakage self-check: {dq.chain_leakage_error}")
    if not synth_ok:
        reasons.append(
            "trade-weighted synthetic-mark fraction "
            f"{dq.synthetic_mark_fraction_trade_weighted:.3f}"
            f" > {th.synthetic_mark_fraction_max:.2f}"
        )
    if not clamp_ok:
        reasons.append(f"r_clamped fraction {clamp_frac:.3f} > {th.r_clamped_fraction_max:.2f}")
    if not stop_ok:
        reasons.append(
            f"{stop_losers:.3f} of LOSING trades closed worse than stop_multiple x credit "
            f"(> {th.stop_non_binding_of_losers_max:.2f})"
        )
    if not pinned_ok:
        reasons.append(
            f"pinned fraction {dq.pinned_fraction:.3f} (ceiling {th.pinned_fraction_max:.2f}), "
            f"expectancy excluding pinned {dq.expectancy_excluding_pinned_r:+.4f}R — the edge "
            "must survive removing the pinned trades"
        )
    return OptionsGate(
        8,
        "data_quality_and_leakage",
        passed,
        (
            f"validate_daily: {'PASS' if validation_ok else 'FAIL'}; leakage self-check: "
            f"{'clean' if leak_ok else 'FINDING'}; options artefacts within their pre-registered "
            "ceilings"
            if passed
            else "; ".join(reasons)
        ),
        {
            "data_validation_passed": dq.data_validation_passed,
            "data_validation_findings": list(dq.data_validation_findings),
            "leakage_error": dq.leakage_error,
            "chain_leakage_error": dq.chain_leakage_error,
            # 1
            "corporate_action_exclusions": dict(dq.corporate_action_exclusions),
            # 2
            "deliverable_refusal_count": counters.shares_per_contract_refusals,
            # 3
            "synthetic_mark_fraction_trade_weighted": dq.synthetic_mark_fraction_trade_weighted,
            "synthetic_mark_fraction_max": th.synthetic_mark_fraction_max,
            # 4
            "synthetic_fill_fraction": None,
            "synthetic_fill_note": (
                "no such field exists: map §2.4(3) forbids synthetic fills and the model cannot "
                "express one"
            ),
            # 5
            "non_entry_count": (
                counters.non_entry_missing_leg_bar + counters.non_entry_no_signal_window
            ),
            "non_entry_reasons": {
                "missing_leg_bar": counters.non_entry_missing_leg_bar,
                "no_signal_window": counters.non_entry_no_signal_window,
                "force_close_unpriceable": counters.force_close_unpriceable_exclusions,
                "force_close_beyond_data": counters.force_close_beyond_data,
                "non_positive_r": counters.non_positive_r_refusals,
                "zero_spread": counters.zero_spread_refusals,
            },
            # 6
            "exit_deferral_distribution": _histogram(counters.exit_deferred_sessions),
            # 7
            "r_clamped_count": counters.r_clamped,
            "r_clamped_fraction": round(clamp_frac, 6),
            "r_clamped_fraction_max": th.r_clamped_fraction_max,
            "r_clamped_fraction_f9_noship": th.r_clamped_fraction_f9_noship,
            "r_clamped_f9_breached": clamp_frac > th.r_clamped_fraction_f9_noship,
            "pnl_r_min_unclamped": (min((t.pnl_r for t in dual.baseline.trades), default=0.0)),
            # 8
            "pinned_fraction": dq.pinned_fraction,
            "pinned_fraction_max": th.pinned_fraction_max,
            "pinned_r_distribution": dict(dq.pinned_r_distribution),
            "expectancy_excluding_pinned_r": dq.expectancy_excluding_pinned_r,
            "expectancy_sign_survives_pin_removal": pinned_sign_survives,
            # 9
            "stop_non_binding_count": counters.stop_non_binding,
            "n_losing_trades": n_losers,
            "stop_non_binding_fraction_all_trades": round(stop_all, 6),
            "stop_non_binding_fraction_of_losers": round(stop_losers, 6),
            "stop_non_binding_ceiling_binds_on": "stop_non_binding_fraction_of_losers",
            "stop_non_binding_of_losers_max": th.stop_non_binding_of_losers_max,
            "stop_non_binding_of_losers_d4_value": th.stop_non_binding_of_losers_d4,
            # 10
            "assignment_approximation_disclosed": dq.assignment_approximation_disclosed,
            "assignment_risk_count": counters.assignment_risk,
            "assignment_bias_direction": (
                "the force-close rule approximates early assignment away, and the bias is IN THE "
                "STRATEGY'S FAVOUR — it removes the tail where a short leg is assigned at the "
                "worst moment; early assignment on short calls is not modelled at all"
            ),
            # 11
            "nbbo_unavailable_options": dq.nbbo_unavailable_options,
            "nbbo_unavailable_equities": dq.nbbo_unavailable_equities,
            # 12
            "clustered_bootstrap_ci": dict(dq.clustered_bootstrap_ci),
            "clustering_unit": dq.clustering_unit,
            "clustered_ci_is_reported_not_gated": True,
            # D5 §3.3(6) / §5.2 additions
            "forced_intrinsic_mark_fraction": dq.forced_intrinsic_mark_fraction,
            "thin_continuity_fraction": dq.thin_continuity_fraction,
            "unmarked_session_fraction": counters.to_dict()["unmarked_session_fraction"],
            "known_caveats": [
                "the stop is a CLOSE-BASIS stop: there is no intrabar option data of any kind, "
                "so no resting stop order is simulated anywhere",
                "the modelled spread is a full spread per leg per side — a DIFFERENT convention "
                "from the equity engine's half-spread; the two R streams are not comparable",
                "NBBO is unavailable under the active entitlement for options AND equities",
            ],
        },
    )


def _histogram(values: Sequence[int]) -> dict[str, int]:
    out: dict[str, int] = {}
    for v in values:
        out[str(v)] = out.get(str(v), 0) + 1
    return dict(sorted(out.items(), key=lambda kv: int(kv[0])))


# --------------------------------------------------------------------------- #
# gate 9 and 10
# --------------------------------------------------------------------------- #
def gate_9_sealed(
    sealed: SealedOptionsOutcome | None,
    ledger: Mapping[str, Any],
    th: OptionsGateThresholds,
    *,
    sealed_test_id: int | None,
    reused: bool,
    options_program_looks: int,
    seal_note: str,
) -> OptionsGate:
    if sealed is None:
        return OptionsGate(
            9,
            "sealed_final_test",
            False,
            (
                "no sealed options window was evaluated — gate 9 cannot pass on an unmeasured "
                "sealed slice, and a pre-sealed diagnostic must leave count_sealed_looks "
                "UNCHANGED"
            ),
            {
                "sealed_test_id": None,
                "sealed_look_ledger": dict(ledger),
                "options_program_looks": options_program_looks,
            },
        )
    passed = bool(
        sealed.n_trades >= th.sealed_min_trades
        and sealed.expectancy_r >= th.sealed_min_expectancy_r
    )
    return OptionsGate(
        9,
        "sealed_final_test",
        passed,
        (
            f"sealed window {sealed.window_start}..{sealed.window_end} ({seal_note}; never "
            f"recomputed once locked): {sealed.n_trades} structures, net expectancy "
            f"{sealed.expectancy_r:+.4f}R (need >= {th.sealed_min_expectancy_r:+.4f}R on >= "
            f"{th.sealed_min_trades}); look {ledger.get('this_look')} of this family "
            f"(k_prior {ledger.get('k_prior')})"
        ),
        {
            "sealed_test_id": sealed_test_id,
            "window": f"{sealed.window_start}..{sealed.window_end}",
            "metrics": dict(sealed.metrics),
            "benchmark": dict(sealed.benchmark),
            "n_trades": sealed.n_trades,
            "expectancy_r": sealed.expectancy_r,
            "spread_multiplier": sealed.spread_multiplier,
            "r_basis": sealed.r_basis.value,
            "reused": reused,
            "created_by_this_run": not reused,
            "sealed_look_ledger": dict(ledger),
            "options_program_looks": options_program_looks,
            "sealed_cost_basis": (
                "BASELINE cost model, structurally — the stressed leg has no path to this row "
                "(D4 §4.3a rule 1)"
            ),
        },
    )


def gate_10_probation(
    *, enabled: bool, min_paper_trades: int, downgrade_z: float, disable_z: float
) -> OptionsGate:
    return OptionsGate(
        10,
        "live_paper_probation",
        enabled,
        (
            f"health-monitor probation {'active' if enabled else 'DISABLED — cannot promote'}: "
            f"downgrade at z<={downgrade_z} once >={min_paper_trades} paper trades exist and "
            f"paper expectancy is negative; disable at z<={disable_z}"
        ),
        {
            "enabled": enabled,
            "min_paper_trades": min_paper_trades,
            "downgrade_z": downgrade_z,
            "disable_z": disable_z,
            "options_paper_precondition": (
                "no options PaperTrade may be created, and any gate-10 evidence derived from one "
                "is VOID, until accept_candidate itself refuses every instrument whose type is "
                "not stock/etf — fail-closed at the shared entry point, not only in the auto path"
            ),
        },
    )
