"""O3 — short vertical (credit) spread, regime-filtered.  D5's pre-registration,
as amended by D5a.

**Every parameter, threshold, axis and rule in this file was fixed in
``docs/research/options_designs/D5_first_strategy_preregistration.md`` and its
amendment ``D5a_amendment_1_reachable_credit_floor_and_fixed_R.md`` before any
option price, IV, greek, credit, return or P&L was inspected (R1).**  Nothing
here may be re-tuned in response to a result; a behavioural change ships as a new
version and costs a fresh sealed look (R3).

**v0.1.1 supersedes v0.1.0 at k = 0.**  ``count_sealed_looks`` keys on
``Strategy.name`` and no row in ``strategy`` begins ``options``, so no sealed look
has been spent on this family and v0.1.0 was never evaluated.  D5a repairs three
arithmetic defects that made v0.1.0 unevaluable and ratifies the horizon:

* ``min_credit_to_width`` 0.25 was **unreachable**.  On an arbitrage-free chain
  ``dP/dK = e^{-rT} N(-d2)`` falls toward the wing, so credit/width is bounded
  above by roughly ``|delta_short|``; the adverse spread charge then takes a
  further 4-48 points out of it.  Over the declared design space the attainable
  adverse ratio tops out at **0.155**.  The amended band is derived from the
  quantiles of that distribution: baseline **0.10**, axis ``(0.10, 0.13)``.
* ``width_pct`` as a fraction of the underlying gave R a different scale on every
  underlying, which fails gate 0.5's ``single_scale``.  Width is now **$2.00 of
  strike distance per contract**, fixed for the version: one R scale, $200.00,
  everywhere.
* At $2.00 the hard max loss is **$201.60** against decision 4's $250 cap — a
  19.4% margin no parameter setting inside this version can breach.  $3.00 would
  need a floor of 0.172 to clear the cap and 0.155 is the attainable maximum;
  $2.50 is not a multiple of the declared $1.00 strike increment.
* **OQ-1 ratified: MEDIUM_SWING.**  ``Horizon`` describes the HOLDING period and
  this structure's is bounded by its own time stop at ``35 - 7 = 28`` calendar
  days.  POSITION's lower bound is ~60.9 days — 2.17x that, and 1.79x even the
  deferral-extended force-close bound — so POSITION is arithmetically impossible
  for every cell of the grid, not merely a worse fit.

**F14, pre-registered before the first look (D5a §4).**  At the $250 cap and this
frozen cost model, *no* width is simultaneously cap-compliant and cost-viable: the
target-win outcome ``0.5C - F`` is negative in every Stage A cell at $2.00, and the
minimum cost-viable widths imply max losses of $254 (IWM) to $842 (SPY).  The
expected disposition is D5 §10's **null option**, and only the operator raising
``options_per_structure_max_loss`` (decision 4's reserved right, OP-1) can change
that — never a post-result adjustment, which D4 §2.8a forbids by name.

The claim, stated so it can be killed: index and large-cap equity options are
sold, on average and across most regimes, at an implied volatility above the
volatility subsequently realised, and *leaning with the lagged proxy trend*
produces a higher hit rate than selling the put side unconditionally.  Gate 7b
is the exact test of the second half; D5 §6.2b puts the break-even target-win
rate at **80.4% at the baseline modelled spread and 88.6% at 2x**, and says in
advance that the null option is the *expected* outcome.

Four design points that are structural here rather than conventional:

* **Selection is priced at the BASELINE cost model, always.**  ``min_credit_to_width``
  is applied to the *adverse modelled* credit (D5 §3.3(4)), so doubling the
  spread constant would change which cycles clear the floor and a naive 2x re-run
  would measure a favourably re-selected subsample rather than the same trades
  under worse costs.  Holding the selection cost model at ``spread_multiplier =
  1.0`` — asserted in ``__init__`` — makes ``run_dual_spread``'s stressed leg
  D5 §6.2c **form (a)**, the gating form, by construction.
* **The regime read is lagged one completed session** and is point-in-time twice
  over: ``regime_from_proxy`` already uses only bars at indices ``<= t``, and the
  extra lag removes any dependence on a close the signal session itself produced.
* **No ``q``, no entry.**  ``q_lookup`` defaults to ``None``, which yields zero
  entries — the correct posture today, because no dividend series is ingested
  anywhere and ``blackscholes``' ``q = 0.0`` default is precisely what gate 0.g
  forbids.  A strategy that silently defaulted ``q`` would produce a delta, a
  strike and a credit that look real and are not.
* **A structure is refused, never fudged.**  ``shares_per_contract != 100``,
  a naked short, two expirations, a zero width — all raise ``StructureRefused``
  from :class:`OptionStructure`'s own constructor and land in a counter.  A
  ``width_usd`` whose hard max loss breaches the pre-registered per-structure cap
  is refused in ``__init__``, before a backtest can be run on it.
* **The wing lands on the declared width exactly, or the cycle is a non-entry.**
  D5 §3.3(3)'s +/-50% width tolerance *is* a gate-0.5 failure once the width is a
  declared dollar constant: a run whose widths vary by 50% carries three R scales.
  Exactness is strictly more searching — it can only remove entries.

**A consequence D5a §2.5 records rather than smooths over.**  With a dollar width
the credit floor is no longer the volatility filter D5 §1 argued it was.  The
print ratio still rises with IV, but the 3%-of-print charge rises faster, so the
*adverse* ratio FALLS with IV: the floor now excludes rich cycles and admits quiet
ones.  No compensating filter is added — that would be a new lever chosen without
evidence — and the floor stays on the adverse credit, because moving it to the
print credit would be a loosening (R4).
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from itertools import pairwise

from signalforge.backtest.options_costs import OptionCostModel, Side
from signalforge.backtest.options_engine import (
    DteBasis,
    OptionLeg,
    OptionsEntrySignal,
    OptionStructure,
    StructureType,
)
from signalforge.backtest.options_pricing import IvSource, adverse_fill
from signalforge.data import options_calendar
from signalforge.data.option_chain import ContractPrint, ContractRef, OptionChainSeries, Right
from signalforge.data.series import PriceSeries
from signalforge.domain import Horizon
from signalforge.gitinfo import git_sha
from signalforge.options import blackscholes
from signalforge.research.options_gates import StructureIdentity
from signalforge.research.regime import RegimeState, Trend, regime_from_proxy
from signalforge.research.registry import StrategySpec, StrategyStatus
from signalforge.research.strategies.base import lagged_regime

#: R3: any behavioural change ships as a new version and costs a fresh sealed
#: look.  0.1.1 is D5a's amendment of the never-evaluated 0.1.0; because
#: ``count_sealed_looks`` reports k = 0 for this family, the amendment costs no
#: look and D5 §10's variant budget (1, hard cap 2) is untouched.
VERSION = "0.1.1"

#: D5 §2.1.  ``count_sealed_looks`` keys on this, so the options family starts at
#: k = 0 by construction and can never be conflated with an equity family.
FAMILY = "options_short_vertical"
STRATEGY_KEY = "options_short_vertical.medium_swing"

#: D5 §2.4.  ``r`` is STRIKE-SHAPING — it feeds ``greeks()`` and therefore picks
#: the short strike — which is why it is inside ``options_config_hash`` and is
#: reported as an assumption on every evaluation rather than buried in a default.
RISK_FREE_RATE = 0.04
R_SOURCE = "config_constant:OptionsEvaluationConfig.risk_free_rate=0.04"

#: D5 §5.4.  "Whichever is narrower" means the band never widens just because an
#: underlying happens to have a coarse strike ladder.
PIN_BAND_PCT = 0.005

#: Decision 4's per-structure max-loss cap, verbatim, and the arithmetic gate 0.i
#: applies to it (D5a §3.3).  ``R_hard = width_usd * M + entry_costs`` is the bound
#: no credit can breach, because the strategy refuses ``net_credit <= 0`` outright.
#: At the declared width that is ``2.00 * 100 + 1.60 = $201.60``, a 19.4% margin.
#: **The cap is the OPERATOR's (decision 4) and may be raised only BEFORE a gate
#: result** — D4 §2.8a names raising it afterwards as the forbidden move.
OPTIONS_PER_STRUCTURE_MAX_LOSS = 250.0

#: D5a §3.3, asserted as market structure exactly as ``tick_grid`` is: SPY, QQQ and
#: IWM monthly third-Friday chains list $1.00 strike increments through the traded
#: region.  A COARSER realised ladder is the conservative direction — it produces
#: non-entries, never a silently rewritten width.
DECLARED_STRIKE_INCREMENT = 1.00

#: Pre-registered here (D5 leaves it to D2's signal contract): a short leg whose
#: intrinsic value exceeds 1% of the underlying's close is flagged
#: ``assignment_risk``.  Recorded, never modelled — the force-close rule
#: approximates early assignment away and the bias is in the strategy's favour.
ASSIGNMENT_ITM_THRESHOLD_PCT = 0.01

#: D5 §2.4, frozen at this commit, **raisable but never lowerable** (D4 §2.6).
#: ``tick_grid`` is an asserted market-structure fact, not an assumption: penny-
#: pilot classes quote in $0.01 below $3.00 and $0.05 at or above it.  Rounding is
#: away from the engine, so a COARSER tick is the conservative direction.
PREREGISTERED_COST_MODEL = OptionCostModel(
    commission_per_contract=0.65,
    commission_min_per_order=0.0,
    exchange_fee_per_contract=0.15,
    spread_pct_of_last_print=0.03,
    spread_abs_floor_cents=2.0,
    tick_grid=((3.0, 0.01), (math.inf, 0.05)),
    assignment_fee=0.0,
    exercise_fee=0.0,
    spread_multiplier=1.0,
)

QLookup = Callable[[str, date], float | None]


@dataclass(frozen=True, slots=True)
class ShortVerticalParams:
    """D5 §4.1 as amended by D5a §6.1 — the frozen ``v0.1.1`` spec, field for field.

    These live in a params dataclass interpolated into the spec's TEXT fields,
    exactly as ``TrendParams`` does, and must **never** become ``StrategySpec``
    fields: ``persistence.spec_json_hash`` hashes every spec field, so adding one
    would change the hash of every existing strategy and put both live
    PAPER_APPROVED versions out of their own approval scope.

    ``promotion.py``'s sensitivity call passes ``asdict(strategy.params)``, so
    every grid axis must be a field here — which is what makes
    :meth:`OptionsShortVertical.sensitivity_axes` checkable against it.
    """

    short_delta_target: float = 0.20  # AXIS 1
    max_short_delta: float = 0.35  # AXIS 2
    stop_multiple: float = 2.0  # AXIS 3 — D5a §6.2: promoted from FIXED
    dte_target: int = 35  # AXIS 4
    profit_target_pct: float = 0.50  # AXIS 5
    min_credit_to_width: float = 0.10  # AXIS 6 — D5a §2.4 (was 0.25, unreachable)
    #: D5a §3: dollars of STRIKE DISTANCE per contract, fixed for the version, so
    #: ``R_scale = width_usd * 100 = $200.00`` is identical on every underlying and
    #: gate 0.5's ``single_scale``/``scale_matches`` pass by construction.  It is
    #: deliberately NOT a grid axis: a width axis would put two R scales into one
    #: gate-5 statistic, which is the pooling gate 0.5's own evidence forbids.
    width_usd: float = 2.00  # FIXED per version (was width_pct = 0.010 of U)
    time_stop_dte: int = 7  # FIXED
    dte_window_lo: int = 28  # FIXED — derived guard around dte_target
    dte_window_hi: int = 45  # FIXED
    delta_tolerance: float = 0.05  # FIXED
    #: D5a §3.4: 0.0 means the wing must land on EXACTLY ``K_short -/+ width_usd``.
    #: D5 §3.3(3)'s 0.50 tolerance is itself a gate-0.5 failure under a declared
    #: dollar width — a run whose widths vary by 50% carries three R scales.
    width_tolerance_pct: float = 0.0  # FIXED — exact placement or non-entry
    min_leg_volume: int = 10  # FIXED — print eligibility, D5 §2.4
    min_leg_transactions: int = 5  # FIXED — print eligibility, D5 §2.4

    @property
    def r_scale_usd(self) -> float:
        """``width_usd x shares_per_contract`` — the gross width in dollars, and
        the single R scale this version may produce (D5a §3.2)."""
        return self.width_usd * 100.0

    @property
    def r_hard_max_usd(self) -> float:
        """The max loss no credit can breach: the strategy refuses ``net_credit <=
        0``, so ``R <= width_usd * M + entry_costs`` whatever the floor is set to.

        This — not ``R`` at the baseline floor — is what gate 0.i's per-structure
        leg is checked against in :meth:`OptionsShortVertical.__init__`, because a
        margin that only holds at one parameter setting is not a margin.
        """
        return (
            self.r_scale_usd
            + PREREGISTERED_COST_MODEL.commission(2)
            + PREREGISTERED_COST_MODEL.fees(2)
        )


#: D5 §4.2 as amended by D5a §6.2 — still **6 axes, 96 points**.
#:
#: Seven free axes are ARITHMETICALLY IMPOSSIBLE, not merely undesirable:
#: ``sensitivity.MAX_GRID_POINTS = 120`` and the grid is the full Cartesian
#: product, so the smallest full factorial over seven axes is ``2**7 = 128 > 120``.
#: Six is the maximum, and only if at most one axis carries three values
#: (``3 x 2**5 = 96``; ``3 x 3 x 2**4 = 144`` does not fit).
#:
#: D5a swaps which parameter the cap forces out, for a reason that is dispositive
#: rather than a preference: **gate 0.5 forbids a width axis.**  Its own evidence
#: carries the rule — "this R stream may not be pooled, averaged, bootstrapped
#: together, or compared with any other structure's R stream" — and a width axis
#: puts two R scales into one gate-5 ``positive_fraction``.  ``width_pct`` was a
#: legal axis in D5 only because that document had not yet noticed R varied across
#: its own baseline cell.  The freed slot goes to ``stop_multiple``, which D5 §4.2
#: itself named as the seventh parameter that deserved an axis; its stated reason
#: for exclusion (``3.0 x 0.30 = 0.90`` of width, near-degenerate) no longer holds
#: at the amended floor, where ``3.0 x 0.155 = 0.465 < 1`` everywhere.
#:
#: Each axis's second value is the HARDER side, per D5 §4.2's rule: 3.0 leaves more
#: tail per trade than 1.5, and 0.13 thins the population more than 0.05.
SENSITIVITY_GRID: Mapping[str, tuple[float | int, ...]] = {
    "short_delta_target": (0.12, 0.20, 0.30),
    "max_short_delta": (0.28, 0.35),
    "stop_multiple": (2.0, 3.0),
    "dte_target": (21, 35),
    "profit_target_pct": (0.50, 0.75),
    "min_credit_to_width": (0.10, 0.13),
}

#: D5a §2.3/§2.4, recorded so the derivation is checkable and the amendment cannot
#: be silently reverted: the attainable adverse credit-to-width ratio over the
#: declared design space (Stage A price levels x IV 0.12-0.60, 35 DTE, baseline
#: delta and width) runs -0.2250 to +0.1550.  **The reachable region is (0, 0.155].**
#: D5's floor (0.25) misses it by at least 61%, its harder grid value (0.30) by 94%,
#: its OAT loosening value (0.20) by 29% — which is why v0.1.0 entered nothing.
#: The three amended values are the p25 / median / p75 of the POSITIVE attainable
#: ratios, each rounded DOWN to 0.01 (rounding up moves toward the unreachable side,
#: which is the whole defect being repaired).
ATTAINABLE_ADVERSE_RATIO_MAX = 0.155
CREDIT_TO_WIDTH_QUANTILES: Mapping[str, float] = {"p25": 0.05, "median": 0.10, "p75": 0.13}

#: D5 §4.4.  Every parameter that is NOT a grid axis is enumerated here, so that
#: under R5 "abandoned variant" stays definable as "a pre-registered cell that was
#: not reported".  A parameter in neither list would be invisible to both
#: mechanisms, which is exactly what R5 exists to prevent.
OAT_PARAMETERS: Mapping[str, tuple[float | int, ...]] = {
    # D5a §6.3.  The cap-compliant width alternative.  Reported, NEVER offered as a
    # selectable grid cell: a "best cell" reading could otherwise select it, and the
    # §2.3 table predicts in advance that $1.00 is cost-destroyed on SPY/QQQ (adverse
    # ratio -0.05 at U = 660, sigma 0.15) and marginal even on IWM.
    "width_usd": (1.00, 2.00),
    "stop_multiple": (1.5,),  # the TIGHTER direction; the grid carries 3.0
    "time_stop_dte": (5, 7, 14),
    "dte_window_lo": (24, 28, 31),
    "dte_window_hi": (50, 45, 42),
    "delta_tolerance": (0.03, 0.05, 0.08),
    # Degenerate by design after D5a §3.4 — exact wing placement is structural now.
    # It stays listed so R5's "a parameter in neither list is invisible" holds.
    "width_tolerance_pct": (0.0,),
    "min_leg_volume": (5, 10, 25),
    "min_leg_transactions": (3, 5, 10),
    # Reported one-at-a-time rather than offered as a selectable grid cell:
    # 0.25 is the EASIER direction on the profit target (less tail per trade) and
    # 0.05 is map §3.2's named failure mode on the credit floor (loosening it to
    # reach for credit).  The grid carries the harder side of each.  0.05 is the
    # derived p25 of the attainable region; D5 §4.4's 0.20 is outside it entirely.
    "profit_target_pct": (0.25,),
    "min_credit_to_width": (0.05,),
}

#: D5 §4.2: 45 DTE is excluded **by derivation, not preference**.  Third-Friday
#: expiries are 28 or 35 days apart, so at 45 DTE the signal session falls before
#: the prior cycle's time stop; under ``options_max_structures_per_underlying = 1``
#: the prior structure is still open and every cycle is skipped.
EXCLUDED_DTE_TARGET = 45

#: Float slack on the exact-width comparison (D5a §3.4).  Strikes arrive as floats
#: parsed from an option ticker's integer thousandths, so ``232.0 - 230.0`` is not
#: reliably ``2.0``.  A tenth of a cent is far below the finest listed increment
#: and cannot admit a genuinely different width.
_WIDTH_EPS = 1e-3


def _print_eligible(pr: ContractPrint, params: ShortVerticalParams) -> bool:
    """D5 §2.4's print-eligibility floor.  Fail-closed on ``volume``.

    A single-lot print struck hours before the underlying's close, inverted to an
    IV and then used to pick the short strike, size the width and measure the
    credit against the floor, is an asynchronous-pricing error of **unbounded
    sign** that no continuity fraction can detect — a bar exists.  The
    ``transactions`` half is enforceable only where the provider populates it.
    """
    if pr.volume < params.min_leg_volume:
        return False
    return not (pr.transactions is not None and pr.transactions < params.min_leg_transactions)


def _listed_increment(strikes: Sequence[float]) -> float:
    """The realised strike increment: the smallest positive gap in the ladder."""
    ordered = sorted(set(strikes))
    gaps = [b - a for a, b in pairwise(ordered) if b > a]
    return min(gaps) if gaps else 0.0


class OptionsShortVertical:
    """The D5 v0.1.0 strategy, as an ``OptionsSignalFn``.

    Deliberately **not** a :class:`~signalforge.research.strategies.base.BaselineStrategy`:
    ``evaluate(series, t, ctx) -> EntrySignal`` has no honest implementation for a
    two-legged structure, and making it one would put an options object into
    ``default_strategies()``' type — the exact coupling the separate registry
    exists to prevent.
    """

    #: ``strategies.base.declared_regime_lag_sessions`` reads this off the class.
    regime_lag_sessions = 1

    def __init__(
        self,
        params: ShortVerticalParams | None = None,
        *,
        selection_cost_model: OptionCostModel = PREREGISTERED_COST_MODEL,
        q_lookup: QLookup | None = None,
        q_source: str = "unsourced",
        risk_free_rate: float = RISK_FREE_RATE,
        r_source: str = R_SOURCE,
        proxy_regimes: Mapping[date, RegimeState] | None = None,
        regime_filter: bool = True,
    ) -> None:
        if selection_cost_model.spread_multiplier != 1.0:
            raise ValueError(
                "the SELECTION cost model is pinned to spread_multiplier = 1.0. Pricing the "
                "credit floor at the stressed spread would re-select a credit-richer "
                "population, which is D5 §6.2c form (b) — a reported diagnostic, never the "
                "gating form. The engine re-prices the same trades at 2x; selection does not "
                "move."
            )
        p = params or ShortVerticalParams()
        if p.dte_target == EXCLUDED_DTE_TARGET:
            raise ValueError(
                f"dte_target = {EXCLUDED_DTE_TARGET} is excluded by derivation (D5 §4.2): under "
                "options_max_structures_per_underlying = 1 the signal session falls before the "
                "prior cycle's time stop, so every cycle is skipped and the cell produces "
                "approximately zero trades"
            )
        if p.width_usd <= 0.0:
            raise ValueError("width_usd is dollars of strike distance per contract and must be > 0")
        if p.r_hard_max_usd > OPTIONS_PER_STRUCTURE_MAX_LOSS:
            raise ValueError(
                f"width_usd = {p.width_usd} gives a hard max loss of ${p.r_hard_max_usd:,.2f}, "
                f"which breaches the pre-registered per-structure cap of "
                f"${OPTIONS_PER_STRUCTURE_MAX_LOSS:,.2f} (decision 4). Gate 0.i would refuse the "
                "evaluated population, and D4 §2.8a forbids raising the cap after a gate result "
                "— the width is re-specified before any outcome is observed, or not at all."
            )
        self.params = p
        self.key = STRATEGY_KEY
        self.horizon = Horizon.MEDIUM_SWING
        self.selection_cost_model = selection_cost_model
        self.q_lookup = q_lookup
        self.q_source = q_source
        self.risk_free_rate = risk_free_rate
        self.r_source = r_source
        self.proxy_regimes = proxy_regimes
        self.regime_filter = regime_filter

    # -- declarations ------------------------------------------------------ #

    def sensitivity_axes(self) -> Mapping[str, Sequence[float | int]]:
        """D5 §4.2's 6-axis, 96-point grid.

        Every value is a field of :class:`ShortVerticalParams` and every axis
        carries the baseline value, so ``promotion._merge_declared_axes``'
        validation passes — a declaration that does not take effect reads as
        pre-registered coverage that was never tested, which is worse than no
        declaration at all.
        """
        return {k: list(v) for k, v in SENSITIVITY_GRID.items()}

    def oat_parameters(self) -> Mapping[str, Sequence[float | int]]:
        """The disclosed one-at-a-time table for every non-axis parameter (D5 §4.4)."""
        return {k: list(v) for k, v in OAT_PARAMETERS.items()}

    def grid_points(self) -> int:
        return math.prod(len(v) for v in SENSITIVITY_GRID.values())

    def structure_identity(self) -> StructureIdentity:
        """Gate 0.5's declared half — now a **constant of the version** (D5a §3).

        It takes no argument any more, and that is the repair: D4 §3 clause (d)
        requires ``width`` and ``M`` to be declared constants so the version has
        one fixed R scale, and gate 0.5 fails ``single_scale`` the moment two
        widths appear in one trade list.  ``width_pct x U`` produced one width per
        underlying; ``width_usd`` produces ``$200.00`` on every underlying, so
        ``single_scale`` and ``scale_matches`` pass by construction rather than by
        luck of which symbols happened to be evaluated.
        """
        return StructureIdentity(
            structure_type=StructureType.VERTICAL_CREDIT,
            r_basis_formula=(
                "R = strike_width x shares_per_contract x contracts - net_credit_received "
                "+ entry_costs"
            ),
            legs_per_structure=2,
            leg_sign_pattern=(-1, +1),
            width_declared=self.params.width_usd,
            m_declared=100,
            width_selected_adaptively=False,
        )

    def mechanical_benchmark(self) -> OptionsShortVertical:
        """Gate 7b's benchmark: the identical structure with the SIGNAL removed.

        Named in D5 §7 before any outcome was looked at.  It differs from the
        strategy in exactly one thing — the regime filter — which is the only
        thing the strategy claims, so 7b asks precisely "does the signal add
        anything over mechanical premium harvest?".  Choosing the mechanical
        variant after seeing results would turn 7b from a test into a rubber
        stamp, and R1 covers that.
        """
        return OptionsShortVertical(
            self.params,
            selection_cost_model=self.selection_cost_model,
            q_lookup=self.q_lookup,
            q_source=self.q_source,
            risk_free_rate=self.risk_free_rate,
            r_source=self.r_source,
            proxy_regimes=self.proxy_regimes,
            regime_filter=False,  # always the put side, every eligible cycle
        )

    def mechanical_spec(self) -> dict[str, object]:
        p = self.params
        return {
            "structure_type": StructureType.VERTICAL_CREDIT.value,
            "short_delta_target": p.short_delta_target,
            "max_short_delta": p.max_short_delta,
            "width_usd": p.width_usd,
            "dte_target": p.dte_target,
            "profit_target_pct": p.profit_target_pct,
            "stop_multiple": p.stop_multiple,
            "time_stop_dte": p.time_stop_dte,
            "min_credit_to_width": p.min_credit_to_width,
            "regime_filter": "REMOVED — always the put side, every eligible cycle",
            "everything_else": "identical to the strategy (D5 §7)",
        }

    # -- the spec ---------------------------------------------------------- #

    def spec(self) -> StrategySpec:
        p = self.params
        cm = self.selection_cost_model
        return StrategySpec(
            name=self.key,
            version=VERSION,
            git_sha=git_sha(),
            horizon=self.horizon,
            rule_definition=(
                "OPTIONS, SIMULATION ONLY. One short vertical CREDIT spread per (underlying, "
                "monthly third-Friday cycle). Sell the PUT side below the market when the "
                "lagged broad-market proxy trend is not bear; sell the CALL-side mirror above "
                f"the market when it is bear. Short strike targets |delta| "
                f"{p.short_delta_target} (cap {p.max_short_delta}); the long wing sits EXACTLY "
                f"${p.width_usd:.2f} of strike distance further out — a constant of the version, "
                f"so max loss is at most ${p.r_hard_max_usd:,.2f} on EVERY underlying. Entry only "
                f"if the net credit at the ADVERSE modelled fill is >= {p.min_credit_to_width} of "
                "the width. Regime label is lagged one completed session."
            ),
            required_data_sources=(
                "BAR_DAILY",
                "OPTION_CONTRACT",
                "OPTION_AGGREGATE_DAILY",
                "DIVIDEND_YIELD",
            ),
            feature_definitions=(
                f"cycle=monthly third-Friday expiry, signal at first session with "
                f"calendar DTE <= {p.dte_target} inside "
                f"[{p.dte_window_lo}, {p.dte_window_hi}]",
                f"sigma_K=blackscholes.implied_vol(print-eligible close, r={self.risk_free_rate}, "
                f"q per underlying per session)",
                f"delta_K=blackscholes.greeks(...).delta, |delta| <= {p.max_short_delta}, "
                f"target {p.short_delta_target} +/- {p.delta_tolerance}",
                f"width=the listed strike at EXACTLY ${p.width_usd:.2f} of strike distance from "
                f"the short strike (tolerance {p.width_tolerance_pct:.0%}); no such strike is a "
                "non-entry, never a rewritten width",
                f"print_eligible=volume >= {p.min_leg_volume} and (transactions is null or "
                f">= {p.min_leg_transactions})",
                f"net_credit_to_width >= {p.min_credit_to_width} at the adverse modelled fill",
            ),
            entry_conditions=(
                "cycle eligible + lagged regime selects the side + a strike within the delta "
                "band + a wing listed at exactly the declared width + the credit floor clears "
                "at the adverse modelled fill + both legs print-eligible + both legs deliver "
                "100 shares. Any failure is a NON-ENTRY, counted by reason — never a fudged fill."
            ),
            invalidation_conditions=(
                "no bracketing chain, no delta match, the declared width is not placeable on the "
                "listed ladder, credit floor not met, print-ineligible leg, no sourced q, "
                "shares_per_contract != 100, or a structure already open on that underlying"
            ),
            exit_logic=(
                f"buy back at <= {1.0 - p.profit_target_pct:.2f} x entry credit (profit target), "
                f"or DTE <= {p.time_stop_dte} (time stop), or the expiry-1 force close — "
                "whichever fires first; execution defers to the next session on which EVERY leg "
                "prints"
            ),
            stop_logic=(
                f"CLOSE-BASIS stop at a buy-back >= {p.stop_multiple} x the entry credit. There "
                "is no intrabar option data of any kind, so no resting stop order is simulated: "
                "a spread that gaps through both strikes realises max loss whatever "
                "stop_multiple said"
            ),
            time_stop=f"DTE <= {p.time_stop_dte}; hard force close on the expiry-1 session",
            liquidity_requirements=(
                f"per leg per session: volume >= {p.min_leg_volume} and, where the provider "
                f"populates it, transactions >= {p.min_leg_transactions}"
            ),
            event_filters=(
                "none beyond the underlying's ResearchConfig.events window; the credit floor IS "
                "the volatility filter, expressed in the units the trade pays in"
            ),
            assumed_transaction_costs=(
                f"OptionCostModel: ${cm.commission_per_contract}/contract + "
                f"${cm.exchange_fee_per_contract} exchange fee/contract, charged on legs x "
                "contracts — a 2-leg vertical pays FOUR contract-commissions round trip"
            ),
            slippage_model=(
                f"print_not_mid; a FULL modelled spread max("
                f"${cm.spread_abs_floor_cents / 100:.2f}, "
                f"{cm.spread_pct_of_last_print:.0%} x last_print) per leg per side — four "
                "crossings round trip. DIFFERENT from the equity engine's half-spread; the two "
                "R streams are not comparable. NBBO is 403 on options AND equities, so the "
                "spread is modelled, never observed"
            ),
            permits_long=True,  # put-side credit spread (bullish-to-neutral)
            permits_short=True,  # call-side mirror (bearish)
            known_failure_modes=(
                "short volatility: an edge that exists only in quiet rising markets",
                "a close-basis stop that does not bind when the underlying gaps through both "
                "strikes — max loss is realised whatever stop_multiple said",
                "the credit collected after four modelled spread crossings is smaller than the "
                "loss rate requires (D5 §6.2b: break-even 80.4% at baseline, 88.6% at 2x)",
                "edge concentrated in trades settled inside the pin band — a modelling artefact",
                "an asynchronous print: a wing that last traded at 10:03 inverted against the "
                "underlying's close biases delta, and therefore the short strike, in an "
                "unbounded direction",
                "early assignment on short calls is not modelled at all, and the force-close "
                "approximation's bias is in the strategy's favour",
            ),
            test_date_range="set per evaluation; D5 §2.3 pre-registers 8 years, floor 6",
            in_sample_period="first 60% of each underlying's bars",
            out_of_sample_period="last 40% of each underlying's bars",
            walkforward_result_ref=(
                "docs/research/options_designs/D5_first_strategy_preregistration.md"
            ),
            status=StrategyStatus.EXPERIMENTAL,
            notes=(
                "OPTIONS — EDUCATION / SIMULATION ONLY. A gate-ladder pass writes "
                "PAPER_APPROVED and authorises NO order. Nothing is armed; there is no ARMED "
                "state anywhere. R is max loss and is a property of the STRUCTURE: this R "
                "stream may never be pooled with, averaged against, or compared to any equity "
                "R stream or any other structure's."
            ),
        )

    # -- the signal function ----------------------------------------------- #

    def __call__(
        self, chain: OptionChainSeries, underlying: PriceSeries, t: int
    ) -> OptionsEntrySignal | None:
        """``OptionsSignalFn``: the chain and the underlying are handed in TRUNCATED.

        The strategy cannot opt out of ``head(t)``, so look-ahead is a structural
        impossibility rather than a review item — and ``head`` truncates the
        visible **contract set** as well as the session list, so a strike that had
        not yet printed is not selectable.
        """
        p = self.params
        if t < 1 or t >= len(chain) or len(chain) != len(underlying):
            return None
        session = chain.sessions[t]
        today = session.session_date
        spot = session.underlying_close
        if spot <= 0.0:
            return None

        expiry = self._cycle_expiry(chain, t, today)
        if expiry is None:
            return None

        right = self._side(underlying, t)
        q = self.q_lookup(chain.underlying, today) if self.q_lookup is not None else None
        if q is None:
            # D5 §2.4 / gate 0.g: a session with no sourced q produces NO entry on
            # that underlying.  q = 0.0 by default is a gate-0 failure, so it is
            # never silently substituted here.
            return None

        t_years = max((expiry - today).days, 0) / 365.0
        if t_years <= 0.0:
            return None

        candidates = self._selectable(chain, t, expiry, right, p)
        if not candidates:
            return None

        short_ref, short_print = self._pick_short(candidates, spot, t_years, q, right, p)
        if short_ref is None or short_print is None:
            return None

        long_ref, long_print = self._pick_wing(candidates, short_ref, right, p)
        if long_ref is None or long_print is None:
            return None

        width = abs(short_ref.strike - long_ref.strike)
        if width <= 0.0:
            return None
        # D5a §3.4: the wing must land on EXACTLY the declared width, or the cycle
        # is a non-entry.  D5 §3.3(3)'s +/-50% tolerance is itself a gate-0.5
        # failure once the width is a declared dollar constant — a run whose widths
        # vary by 50% carries three R scales, and `single_scale` refuses it.  A
        # coarse ladder therefore produces a non-entry rather than a silently
        # rewritten width, which is the same hazard handled more strictly.
        if abs(width - p.width_usd) > p.width_tolerance_pct * p.width_usd + _WIDTH_EPS:
            return None

        if not self._credit_floor_clears(
            short_print, long_print, short_ref, long_ref, spot, today, expiry, width, p
        ):
            return None

        structure = OptionStructure(
            structure_type=StructureType.VERTICAL_CREDIT,
            underlying_symbol=chain.underlying,
            legs=(OptionLeg(short_ref, -1), OptionLeg(long_ref, +1)),
            contracts=1,  # D5 §3.1(6): the backtest is position-count-unconstrained
        )
        increment = _listed_increment([c.strike for c, _ in candidates])
        return OptionsEntrySignal(
            structure=structure,
            entry_session_index=t,
            profit_target_pct_of_credit=p.profit_target_pct,
            stop_multiple_of_credit=p.stop_multiple,
            time_stop_dte=p.time_stop_dte,
            time_stop_dte_basis=DteBasis.CALENDAR,
            pin_band_pct=PIN_BAND_PCT,
            strike_increment=increment or DECLARED_STRIKE_INCREMENT,
            assignment_itm_threshold_pct=ASSIGNMENT_ITM_THRESHOLD_PCT,
            iv_source=IvSource.LOCAL_BS_INVERTED,
            q_source=self.q_source,
            r_source=self.r_source,
            reason=(
                f"{right.value} credit spread {short_ref.strike:g}/{long_ref.strike:g} exp "
                f"{expiry}, DTE {options_calendar.calendar_dte(today, expiry)}, width {width:g}"
            ),
        )

    # -- the pieces -------------------------------------------------------- #

    def _cycle_expiry(self, chain: OptionChainSeries, t: int, today: date) -> date | None:
        """The one monthly cycle this session is the SIGNAL session for.

        Deterministic and exactly one per ``(underlying, cycle)``: the signal
        session is the **first** session on which calendar DTE falls to or below
        ``dte_target``, so the previous session must still be above it.  If the
        first such session falls outside the eligibility window (a holiday run),
        the cycle is skipped.
        """
        p = self.params
        prev = chain.sessions[t - 1].session_date
        expiries = sorted(
            {
                c.expiration
                for c in chain.visible_contracts(t).values()
                if c.expiration >= today
                and options_calendar.is_expiry(c.expiration, monthly_only=True)
            }
        )
        for expiry in expiries:
            dte = options_calendar.calendar_dte(today, expiry)
            if dte > p.dte_target:
                continue
            if options_calendar.calendar_dte(prev, expiry) <= p.dte_target:
                continue  # an earlier session was this cycle's signal session
            if not (p.dte_window_lo <= dte <= p.dte_window_hi):
                return None  # cycle skipped and counted by the engine's non-entry path
            return expiry
        return None

    def _side(self, underlying: PriceSeries, t: int) -> Right:
        """The direction control, lagged one completed session (D5 §3.2).

        Trend only.  ``RegimeState.risk_off`` is ``BEAR or HIGH vol``, and volume
        of volatility does not tell direction, so it deliberately does not flip
        the side.  There is no "skip" branch: every eligible cycle attempts an
        entry on one side or the other, which is what makes gate 6's bear bucket
        reachable at all.
        """
        if not self.regime_filter:
            return Right.PUT  # the gate-7b mechanical benchmark
        if self.proxy_regimes is not None:
            state = lagged_regime(self.proxy_regimes, underlying.dates[t], self.regime_lag_sessions)
        else:
            state = regime_from_proxy(underlying, t - self.regime_lag_sessions)
        return Right.CALL if state.trend is Trend.BEAR else Right.PUT

    def _selectable(
        self,
        chain: OptionChainSeries,
        t: int,
        expiry: date,
        right: Right,
        p: ShortVerticalParams,
    ) -> list[tuple[ContractRef, ContractPrint]]:
        """Visible + right expiry + right side + PRINT-ELIGIBLE at ``t``.

        Sorted by ``option_ticker`` so dict iteration order can never affect a
        selection (S4 determinism).
        """
        out: list[tuple[ContractRef, ContractPrint]] = []
        for ticker, ref in sorted(chain.visible_contracts(t).items()):
            if ref.expiration != expiry or ref.right is not right:
                continue
            if ref.shares_per_contract != 100:
                continue  # refused; the engine counts it if it is ever selected
            pr = chain.print_at(t, ticker)
            if pr is None or not _print_eligible(pr, p):
                continue
            out.append((ref, pr))
        return out

    def _pick_short(
        self,
        candidates: list[tuple[ContractRef, ContractPrint]],
        spot: float,
        t_years: float,
        q: float,
        right: Right,
        p: ShortVerticalParams,
    ) -> tuple[ContractRef | None, ContractPrint | None]:
        """Among OTM strikes with ``|delta| <= max_short_delta``, the one closest
        to ``short_delta_target``; tie-break FURTHER OTM (the conservative side).

        ``sigma_K`` is inverted from that contract's **own print-eligible print**
        (``local_bs_inverted``).  A strike with no invertible IV is not
        selectable: realised volatility as a fallback is forbidden — it sits below
        implied on average, which is the exact quantity being harvested.
        """
        call = right is Right.CALL
        best: tuple[float, float, ContractRef, ContractPrint] | None = None
        for ref, pr in candidates:
            otm = (ref.strike < spot) if right is Right.PUT else (ref.strike > spot)
            if not otm:
                continue
            sigma = blackscholes.implied_vol(
                pr.last_print, spot, ref.strike, t_years, self.risk_free_rate, call=call, q=q
            )
            if sigma is None or sigma <= 0.0:
                continue
            delta = abs(
                blackscholes.greeks(
                    spot, ref.strike, t_years, self.risk_free_rate, sigma, call=call, q=q
                ).delta
            )
            if delta > p.max_short_delta:
                continue
            gap = abs(delta - p.short_delta_target)
            if gap > p.delta_tolerance:
                continue
            # tie-break further OTM: smaller strike for a put, larger for a call
            otm_rank = ref.strike if right is Right.PUT else -ref.strike
            key = (round(gap, 12), otm_rank)
            if best is None or key < (round(best[0], 12), best[1]):
                best = (gap, otm_rank, ref, pr)
        if best is None:
            return None, None
        return best[2], best[3]

    def _pick_wing(
        self,
        candidates: list[tuple[ContractRef, ContractPrint]],
        short_ref: ContractRef,
        right: Right,
        p: ShortVerticalParams,
    ) -> tuple[ContractRef | None, ContractPrint | None]:
        """The listed strike closest to ``K_short -/+ width_usd``, at least one
        listed increment beyond the short strike.

        The underlying's close no longer enters the target at all (D5a §3): the
        width is a
        declared dollar constant of the version, not a fraction of the underlying,
        so the same $2.00 distance is sought on a $240 underlying and a $660 one.
        The caller then refuses anything that is not that distance exactly.
        """
        target = (
            short_ref.strike - p.width_usd if right is Right.PUT else short_ref.strike + p.width_usd
        )
        further_otm = (
            (lambda k: k < short_ref.strike)
            if right is Right.PUT
            else (lambda k: k > short_ref.strike)
        )
        beyond = [(ref, pr) for ref, pr in candidates if further_otm(ref.strike)]
        if not beyond:
            return None, None
        ref, pr = min(beyond, key=lambda rp: (abs(rp[0].strike - target), rp[0].option_ticker))
        return ref, pr

    def _credit_floor_clears(
        self,
        short_print: ContractPrint,
        long_print: ContractPrint,
        short_ref: ContractRef,
        long_ref: ContractRef,
        spot: float,
        today: date,
        expiry: date,
        width: float,
        p: ShortVerticalParams,
    ) -> bool:
        """``net_credit / (width x M) >= min_credit_to_width`` at the ADVERSE fill.

        Applying the floor to the realistic credit rather than the print cannot be
        gamed by a generous spread constant.  The cost model used here is pinned
        to the baseline (``__init__``), so the gate-4b stressed run re-prices the
        **same** trades instead of re-selecting a credit-richer subsample.
        """
        cm = self.selection_cost_model
        dte = options_calendar.calendar_dte(today, expiry)
        sell = adverse_fill(
            short_print,
            cm,
            side=Side.SELL,
            strike=short_ref.strike,
            right=short_ref.right,
            underlying_close=spot,
            dte=dte,
        )
        buy = adverse_fill(
            long_print,
            cm,
            side=Side.BUY,
            strike=long_ref.strike,
            right=long_ref.right,
            underlying_close=spot,
            dte=dte,
        )
        m = short_ref.shares_per_contract
        net_credit = (sell.price - buy.price) * m
        if net_credit <= 0.0:
            return False
        return net_credit / (width * m) >= p.min_credit_to_width
