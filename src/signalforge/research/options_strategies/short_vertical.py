"""O3 — short vertical (credit) spread, regime-filtered.  D5's pre-registration.

**Every parameter, threshold, axis and rule in this file was fixed in
``docs/research/options_designs/D5_first_strategy_preregistration.md`` before any
option price, IV, greek, credit, return or P&L was inspected (R1).**  Nothing
here may be re-tuned in response to a result; a behavioural change ships as
``0.2.0`` and costs a fresh sealed look (R3).

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
  from :class:`OptionStructure`'s own constructor and land in a counter.

**Known conflict between D4 §3 clause (d) and D5 §4.1, recorded rather than
resolved here.** D4 §3 requires ``width``, ``M`` and the collateral basis to be
declared constants so the version has one fixed R scale; D5 §4.1 declares
``width_pct`` as a *fraction of the underlying close*, so R scales with the
underlying's price (D5 §9.2: ~$75 at U=$100, ~$525 at U=$700).  Gate 0.5 is left
**strict** — a multi-underlying evaluation of v0.1.0 as pre-registered will FAIL
it, and that is the gate doing its job rather than a bug to code around.
Resolving it is an orchestrator decision and belongs in a D5 amendment, not in
this file.
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

#: R3: any behavioural change ships as 0.2.0 and costs a fresh sealed look.
VERSION = "0.1.0"

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
    """D5 §4.1's frozen ``v0.1.0`` spec, field for field.

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
    width_pct: float = 0.010  # AXIS 3 — fraction of the underlying close
    dte_target: int = 35  # AXIS 4
    profit_target_pct: float = 0.50  # AXIS 5
    min_credit_to_width: float = 0.25  # AXIS 6
    stop_multiple: float = 2.0  # FIXED — OAT only (D5 §4.2, §4.4)
    time_stop_dte: int = 7  # FIXED
    dte_window_lo: int = 28  # FIXED — derived guard around dte_target
    dte_window_hi: int = 45  # FIXED
    delta_tolerance: float = 0.05  # FIXED
    width_tolerance_pct: float = 0.50  # FIXED
    min_leg_volume: int = 10  # FIXED — print eligibility, D5 §2.4
    min_leg_transactions: int = 5  # FIXED — print eligibility, D5 §2.4


#: D5 §4.2's complete, exhaustive grid: **6 axes, 96 points**.
#:
#: Seven free axes are ARITHMETICALLY IMPOSSIBLE, not merely undesirable:
#: ``sensitivity.MAX_GRID_POINTS = 120`` and the grid is the full Cartesian
#: product, so the smallest full factorial over seven axes is ``2**7 = 128 > 120``.
#: Six is the maximum, and only if at most one axis carries three values
#: (``3 x 2**5 = 96``; ``3 x 3 x 2**4 = 144`` does not fit).  ``stop_multiple`` is
#: the seventh parameter the cap forces out, and it goes to the OAT table below
#: — it is the axis whose high value is near-degenerate (``3.0 x 0.30 = 0.90`` of
#: width) and whose behaviour gate 8 measures directly anyway.
SENSITIVITY_GRID: Mapping[str, tuple[float | int, ...]] = {
    "short_delta_target": (0.12, 0.20, 0.30),
    "max_short_delta": (0.28, 0.35),
    "width_pct": (0.010, 0.020),
    "dte_target": (21, 35),
    "profit_target_pct": (0.50, 0.75),
    "min_credit_to_width": (0.25, 0.30),
}

#: D5 §4.4.  Every parameter that is NOT a grid axis is enumerated here, so that
#: under R5 "abandoned variant" stays definable as "a pre-registered cell that was
#: not reported".  A parameter in neither list would be invisible to both
#: mechanisms, which is exactly what R5 exists to prevent.
OAT_PARAMETERS: Mapping[str, tuple[float | int, ...]] = {
    "stop_multiple": (1.5, 2.0, 3.0),
    "time_stop_dte": (5, 7, 14),
    "dte_window_lo": (24, 28, 31),
    "dte_window_hi": (50, 45, 42),
    "delta_tolerance": (0.03, 0.05, 0.08),
    "width_tolerance_pct": (0.35, 0.50),
    "min_leg_volume": (5, 10, 25),
    "min_leg_transactions": (3, 5, 10),
    # Reported one-at-a-time rather than offered as a selectable grid cell:
    # 0.25 is the EASIER direction on the profit target (less tail per trade) and
    # 0.20 is map §3.2's named failure mode on the credit floor (loosening it to
    # reach for credit).  The grid carries the harder side of each.
    "profit_target_pct": (0.25,),
    "min_credit_to_width": (0.20,),
}

#: D5 §4.2: 45 DTE is excluded **by derivation, not preference**.  Third-Friday
#: expiries are 28 or 35 days apart, so at 45 DTE the signal session falls before
#: the prior cycle's time stop; under ``options_max_structures_per_underlying = 1``
#: the prior structure is still open and every cycle is skipped.
EXCLUDED_DTE_TARGET = 45


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

    def structure_identity(self, *, width_declared: float) -> StructureIdentity:
        """Gate 0.5's declared half.

        ``width_declared`` is in **strikes** (dollars of strike distance), which
        the caller derives from ``width_pct x U`` for the evaluated underlying —
        see this module's docstring for the D4 §3 clause (d) conflict that makes
        it an argument rather than a constant.
        """
        return StructureIdentity(
            structure_type=StructureType.VERTICAL_CREDIT,
            r_basis_formula=(
                "R = strike_width x shares_per_contract x contracts - net_credit_received "
                "+ entry_costs"
            ),
            legs_per_structure=2,
            leg_sign_pattern=(-1, +1),
            width_declared=width_declared,
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
            "width_pct": p.width_pct,
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
                f"{p.short_delta_target} (cap {p.max_short_delta}); the long wing sits "
                f"{p.width_pct:.3%} of the underlying further out. Entry only if the net credit "
                f"at the ADVERSE modelled fill is >= {p.min_credit_to_width} of the width. "
                "Regime label is lagged one completed session."
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
                f"width=nearest listed strike to {p.width_pct} x underlying close, within "
                f"{p.width_tolerance_pct:.0%}",
                f"print_eligible=volume >= {p.min_leg_volume} and (transactions is null or "
                f">= {p.min_leg_transactions})",
                f"net_credit_to_width >= {p.min_credit_to_width} at the adverse modelled fill",
            ),
            entry_conditions=(
                "cycle eligible + lagged regime selects the side + a strike within the delta "
                "band + a placeable wing within the width tolerance + the credit floor clears "
                "at the adverse modelled fill + both legs print-eligible + both legs deliver "
                "100 shares. Any failure is a NON-ENTRY, counted by reason — never a fudged fill."
            ),
            invalidation_conditions=(
                "no bracketing chain, no delta match, width out of tolerance, credit floor not "
                "met, print-ineligible leg, no sourced q, shares_per_contract != 100, or a "
                "structure already open on that underlying"
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

        long_ref, long_print = self._pick_wing(candidates, short_ref, spot, right, p)
        if long_ref is None or long_print is None:
            return None

        width = abs(short_ref.strike - long_ref.strike)
        if width <= 0.0:
            return None
        wanted = p.width_pct * spot
        if abs(width - wanted) > p.width_tolerance_pct * wanted:
            # A coarse strike ladder on a low-priced underlying would otherwise
            # silently rewrite the width parameter.
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
            strike_increment=increment or (p.width_pct * spot),
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
        spot: float,
        right: Right,
        p: ShortVerticalParams,
    ) -> tuple[ContractRef | None, ContractPrint | None]:
        """The listed strike closest to ``K_short -/+ width_pct x U``, at least one
        listed increment beyond the short strike."""
        target = (
            short_ref.strike - p.width_pct * spot
            if right is Right.PUT
            else short_ref.strike + p.width_pct * spot
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
