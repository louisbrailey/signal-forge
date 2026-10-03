"""O3 — the D5/D5a/Amendment-2 v0.1.2 short vertical, on SYNTHETIC chains only.

No real option price, IV, greek, credit, return or P&L is read anywhere here.
Every chain is priced from Black-Scholes at a chosen sigma, so the strategy's
inverted IV comes back as that sigma exactly and the delta it selects on is
arithmetic the reader can check.

The last sections are the **amendments' own arithmetic**, reproduced as tests so
that neither D5a nor Amendment 2 can be silently reverted:

* §2 — the credit-to-width bound: the ceiling is the short delta, the adverse
  charge eats it.  D5a's $2.00 table (attainable region ``(0, 0.155]``) is kept
  as history and still follows from the code; Amendment 2's $8.00 table
  (0.0938 - 0.1813, positive everywhere) is what the v0.1.2 band 0.140 / 0.150 /
  0.155 is read off.  Every floor D5 pre-registered (0.20 / 0.25 / 0.30) is still
  outside the attainable region at both widths.
* §3 — one R scale per version (``$800.00`` everywhere), the OP-1 $900 cap, the
  width ceiling it implies ($8), F14 at both widths, and the $3,600 aggregate.
* §5 — OQ-1: the holding period is bounded by the time stop, and POSITION is
  arithmetically impossible.
"""

from __future__ import annotations

import math
import statistics
from datetime import date
from itertools import pairwise

import pytest

from signalforge.backtest.options_costs import Side
from signalforge.backtest.options_engine import (
    RBasis,
    StructureType,
    run_options_backtest,
)
from signalforge.config.research import OptionsRiskLimits
from signalforge.data import calendar, options_calendar
from signalforge.data.option_chain import ContractPrint, ContractRef, OptionChainSeries, Right
from signalforge.data.series import PriceSeries
from signalforge.domain import Horizon
from signalforge.options import blackscholes as bs
from signalforge.research.options_gates import OptionsGateThresholds, gate_0_5_structure
from signalforge.research.options_strategies import (
    ATTAINABLE_ADVERSE_RATIO_MAX,
    CREDIT_TO_WIDTH_QUANTILES,
    DECLARED_STRIKE_INCREMENT,
    OAT_PARAMETERS,
    OPTIONS_PER_STRUCTURE_MAX_LOSS,
    PREREGISTERED_COST_MODEL,
    SENSITIVITY_GRID,
    OptionsShortVertical,
    ShortVerticalParams,
)
from signalforge.research.regime import RegimeState, Trend, Vol

EXPIRY = date(2024, 3, 15)  # third Friday, an XNYS session
SPOT = 240.0  # an IWM-scale underlying; D5a §0.3's declared Stage A level
Q = 0.013
R = 0.04
SESSIONS = calendar.sessions(date(2024, 1, 2), date(2024, 3, 20))
SIGNAL_IDX = SESSIONS.index(date(2024, 2, 9))  # calendar DTE 35; the prior session is 36
YEARS = (EXPIRY - SESSIONS[SIGNAL_IDX]).days / 365.0

#: D5a §0.3, asserted as market structure: SPY/QQQ/IWM monthly chains list $1.00
#: increments through the traded region.  The synthetic ladder uses the same.
LADDER_STEP = 1

#: The sigma the MECHANISM tests run at, derived rather than chosen: at v0.1.2's
#: $8.00 width the IWM-scale ($240) chain's adverse credit/width is 0.1387 at sigma
#: 0.20 and 0.1462 at 0.25 — BELOW the 0.150 baseline floor — and 0.1637 at 0.30,
#: which clears every grid value (0.150, 0.155) and the OAT value (0.140).  The
#: v0.1.1 tests ran at 0.20 because 0.20 cleared v0.1.1's 0.10 at $2.  Asserted
#: below in ``test_the_mechanism_sigma_clears_the_baseline_floor``.
MECH_SIGMA = 0.30


def _ticker(right: Right, strike: float, sym: str = "IWM") -> str:
    return f"O:{sym}240315{'P' if right is Right.PUT else 'C'}{int(strike * 1000):08d}"


def build_chain(
    *,
    sigma: float = MECH_SIGMA,
    volume: float = 1000.0,
    transactions: int | None = 50,
    shares_per_contract: int = 100,
    step: int = LADDER_STEP,
    spot: float = SPOT,
    symbol: str = "IWM",
) -> tuple[OptionChainSeries, PriceSeries]:
    """An arbitrage-free chain: every print IS the Black-Scholes value at ``sigma``.

    The ladder is derived from ``spot`` so the same builder serves every price
    level D5a §3 needs — which is the point: under a **dollar** width the strategy
    must behave identically at $120 and at $360.
    """
    lo, hi = int(spot * 0.70), int(spot * 1.30)
    refs: list[ContractRef] = []
    prints: dict[date, dict[str, ContractPrint]] = {}
    for right in (Right.PUT, Right.CALL):
        for k in range(lo, hi + 1, step):
            tk = _ticker(right, float(k), symbol)
            refs.append(
                ContractRef(
                    tk,
                    symbol,
                    right,
                    float(k),
                    EXPIRY,
                    shares_per_contract,
                    "american",
                    SESSIONS[0],
                )
            )
            for d in SESSIONS:
                years = max((EXPIRY - d).days, 0) / 365.0
                if years <= 0:
                    continue
                px = bs.price(spot, float(k), years, R, sigma, call=right is Right.CALL, q=Q)
                # A deep-OTM wing still PRINTS at the minimum tick near expiry.
                # Dropping the bar instead would make the force-close session
                # unpriceable and the engine would (correctly) exclude the whole
                # cycle -- which is a real rule, but not the one under test here.
                px = max(px, 0.01)
                prints.setdefault(d, {})[tk] = ContractPrint(
                    px, px, px, px, volume, px, transactions
                )
    chain = OptionChainSeries.from_rows(
        symbol,
        contracts=refs,
        underlying_closes=dict.fromkeys(SESSIONS, spot),
        prints=prints,
    )
    under = PriceSeries.from_bars(symbol, [(d, spot, spot, spot, spot, 1e6) for d in SESSIONS])
    return chain, under


def _q(_sym: str, _d: date) -> float:
    return Q


def strategy(**param_overrides) -> OptionsShortVertical:
    """The strategy at its **pre-registered v0.1.2 parameters**.

    v0.1.0's version of this helper had to loosen ``min_credit_to_width`` to 0.08
    — a value that was never pre-registered anywhere — because the pre-registered
    floor entered nothing on any chain.  D5a's amended floor is reachable, so the
    mechanism tests now run on the real parameters.  That is the repair, visible
    as a diff.
    """
    return OptionsShortVertical(
        ShortVerticalParams(**param_overrides), q_lookup=_q, q_source="test:vendor_dividends"
    )


def _regimes(trend_by_index: dict[int, Trend]) -> dict[date, RegimeState]:
    return {
        d: RegimeState(trend_by_index.get(i, Trend.BULL), Vol.LOW, d)
        for i, d in enumerate(SESSIONS)
    }


# --------------------------------------------------------------------------- #
# cycle and signal timing
# --------------------------------------------------------------------------- #
def test_the_signal_fires_on_the_first_session_at_or_inside_the_dte_target() -> None:
    chain, under = build_chain()
    strat = strategy()
    assert strat(chain.head(SIGNAL_IDX), under.head(SIGNAL_IDX), SIGNAL_IDX) is not None
    assert options_calendar.calendar_dte(SESSIONS[SIGNAL_IDX], EXPIRY) == 35


def test_no_earlier_and_no_later_session_is_the_signal_session() -> None:
    """Deterministic, exactly one per (underlying, cycle): the session before is
    still above ``dte_target``, and every session after has already had its."""
    chain, under = build_chain()
    strat = strategy()
    fired = [
        t for t in range(1, len(SESSIONS) - 1) if strat(chain.head(t), under.head(t), t) is not None
    ]
    assert fired == [SIGNAL_IDX]


def test_a_signal_session_outside_the_dte_window_skips_the_cycle() -> None:
    """A holiday run can push the first qualifying session past ``dte_window_hi``;
    the cycle is skipped rather than entered at the wrong distance."""
    chain, under = build_chain()
    strat = strategy(dte_target=35, dte_window_lo=34, dte_window_hi=34)
    assert strat(chain.head(SIGNAL_IDX), under.head(SIGNAL_IDX), SIGNAL_IDX) is None


# --------------------------------------------------------------------------- #
# the regime filter, lagged one completed session
# --------------------------------------------------------------------------- #
#: SIDE-SELECTION mechanism tests only.  At v0.1.2's $8 width the CALL mirror's
#: adverse credit/width tops out at 0.135 over the whole Stage A x IV space (0.125
#: on this $240 chain at sigma 0.30), below every v0.1.2 band value — Amendment 2
#: F15.  Testing WHICH side is chosen therefore needs a floor the call side can
#: clear; v0.1.1's pre-registered 0.10 is used, and F15 itself is asserted below.
SIDE_TEST_FLOOR = 0.10


def test_a_bear_regime_sells_the_call_side_mirror() -> None:
    """The mirror is what makes gate 6's bear bucket reachable at all."""
    chain, under = build_chain()
    strat = strategy(min_credit_to_width=SIDE_TEST_FLOOR)
    strat.proxy_regimes = _regimes(dict.fromkeys(range(len(SESSIONS)), Trend.BEAR))
    sig = strat(chain.head(SIGNAL_IDX), under.head(SIGNAL_IDX), SIGNAL_IDX)
    assert sig is not None
    assert {leg.contract.right for leg in sig.structure.legs} == {Right.CALL}


@pytest.mark.parametrize("sigma", [0.15, 0.20, 0.30, 0.40, 0.60])
def test_f15_the_call_mirror_enters_nothing_at_the_v012_band(sigma: float) -> None:
    """**F15, pre-registered in Amendment 2 §4.6 before any look.**

    The v0.1.2 band is read off the PUT side (D5a's rule, unchanged in scope).  At
    $8 the call mirror's attainable adverse ratio is 0.050 - 0.135, so under a
    BEAR label the strategy enters nothing at the 0.140 OAT value or either grid
    value: gate 6's bear bucket is expected EMPTY and the regime filter reduces to
    "sell puts, or stand aside".  Recorded so it is a prediction, not a discovery.
    """
    chain, under = build_chain(sigma=sigma)
    for floor in CREDIT_TO_WIDTH_QUANTILES.values():
        strat = strategy(min_credit_to_width=floor)
        strat.proxy_regimes = _regimes(dict.fromkeys(range(len(SESSIONS)), Trend.BEAR))
        assert strat(chain.head(SIGNAL_IDX), under.head(SIGNAL_IDX), SIGNAL_IDX) is None


def test_a_neutral_regime_sells_the_put_side_like_a_bull_one() -> None:
    """Trend only.  ``risk_off`` is BEAR *or* HIGH vol, and volume of volatility
    does not tell direction, so it deliberately does not flip the side."""
    chain, under = build_chain()
    strat = strategy()
    strat.proxy_regimes = {d: RegimeState(Trend.NEUTRAL, Vol.HIGH, d) for d in SESSIONS}
    sig = strat(chain.head(SIGNAL_IDX), under.head(SIGNAL_IDX), SIGNAL_IDX)
    assert sig is not None
    assert {leg.contract.right for leg in sig.structure.legs} == {Right.PUT}


def test_the_regime_read_is_lagged_by_exactly_one_completed_session() -> None:
    """The label used is the one in force at ``t-1``, so nothing depends on a
    close the signal session itself produced."""
    chain, under = build_chain()
    strat = strategy(min_credit_to_width=SIDE_TEST_FLOOR)
    strat.regime_lag_sessions = 1
    # BEAR at t-1, BULL at t: the lagged read must still choose the CALL mirror.
    strat.proxy_regimes = _regimes({SIGNAL_IDX - 1: Trend.BEAR, SIGNAL_IDX: Trend.BULL})
    sig = strat(chain.head(SIGNAL_IDX), under.head(SIGNAL_IDX), SIGNAL_IDX)
    assert sig is not None
    assert {leg.contract.right for leg in sig.structure.legs} == {Right.CALL}

    # and the unlagged label alone would have chosen the put side
    strat.proxy_regimes = _regimes({SIGNAL_IDX: Trend.BEAR})
    sig = strat(chain.head(SIGNAL_IDX), under.head(SIGNAL_IDX), SIGNAL_IDX)
    assert sig is not None
    assert {leg.contract.right for leg in sig.structure.legs} == {Right.PUT}


def test_the_mechanical_benchmark_ignores_the_regime_and_always_sells_puts() -> None:
    chain, under = build_chain()
    mech = strategy().mechanical_benchmark()
    mech.proxy_regimes = _regimes(dict.fromkeys(range(len(SESSIONS)), Trend.BEAR))
    sig = mech(chain.head(SIGNAL_IDX), under.head(SIGNAL_IDX), SIGNAL_IDX)
    assert sig is not None
    assert {leg.contract.right for leg in sig.structure.legs} == {Right.PUT}


# --------------------------------------------------------------------------- #
# strike selection
# --------------------------------------------------------------------------- #
def _selected(strat: OptionsShortVertical, chain, under) -> tuple[float, float]:
    sig = strat(chain.head(SIGNAL_IDX), under.head(SIGNAL_IDX), SIGNAL_IDX)
    assert sig is not None
    short = sig.structure.short_leg
    long_ = sig.structure.long_leg
    assert short is not None and long_ is not None
    return short.contract.strike, long_.contract.strike


def test_the_short_strike_is_the_listed_strike_closest_to_the_delta_target() -> None:
    chain, under = build_chain(sigma=MECH_SIGMA)
    short, _ = _selected(strategy(), chain, under)
    deltas = {
        k: abs(bs.greeks(SPOT, float(k), YEARS, R, MECH_SIGMA, call=False, q=Q).delta)
        for k in range(int(SPOT * 0.70), int(SPOT * 1.30) + 1)
    }
    best = min(
        (k for k, d in deltas.items() if d <= 0.35 and abs(d - 0.20) <= 0.05),
        key=lambda k: (abs(deltas[k] - 0.20), k),
    )
    assert short == float(best)
    assert deltas[best] == pytest.approx(0.20, abs=0.01)


def test_a_strike_beyond_max_short_delta_is_never_selectable() -> None:
    """``max_short_delta`` caps how far axis 1 may be pushed to satisfy the
    credit floor — map §3.2's Rule, honoured literally."""
    chain, under = build_chain(sigma=MECH_SIGMA)
    short_loose, _ = _selected(
        strategy(short_delta_target=0.30, max_short_delta=0.35), chain, under
    )
    short_capped, _ = _selected(
        strategy(short_delta_target=0.30, max_short_delta=0.28), chain, under
    )
    capped_delta = abs(bs.greeks(SPOT, short_capped, YEARS, R, MECH_SIGMA, call=False, q=Q).delta)
    assert capped_delta <= 0.28
    assert short_capped != short_loose  # the axis genuinely binds, it is not inert


def test_no_strike_within_the_delta_tolerance_is_a_non_entry() -> None:
    chain, under = build_chain(sigma=MECH_SIGMA)
    assert (
        strategy(short_delta_target=0.02, delta_tolerance=0.001)(
            chain.head(SIGNAL_IDX), under.head(SIGNAL_IDX), SIGNAL_IDX
        )
        is None
    )


@pytest.mark.parametrize(
    ("width_usd", "floor"),
    # v0.1.1's width at v0.1.1's floor (the OAT control), and v0.1.2's at its own.
    [(2.00, 0.10), (8.00, 0.150)],
)
def test_the_wing_sits_at_exactly_the_declared_dollar_width(width_usd: float, floor: float) -> None:
    """D5a §3: the width is dollars of STRIKE DISTANCE per contract, a constant of
    the version — not a fraction of the underlying close."""
    chain, under = build_chain(sigma=MECH_SIGMA)
    short, long_ = _selected(strategy(width_usd=width_usd, min_credit_to_width=floor), chain, under)
    assert short - long_ == pytest.approx(width_usd)


#: The price levels the multi-underlying tests use.  v0.1.1 used $120/$240/$360 at
#: sigma 0.15; at $8.00 a $120 underlying's adverse ratio is 0.083-0.143 over sigma
#: 0.20-0.40 and never clears the 0.150 floor (an $8 wing is 6.7% of a $120 close),
#: so the levels move up to where the mechanism is exercised at all.  That a cheap
#: underlying rarely clears the floor is itself Amendment 2 §4.5's disclosure.
PRICE_LEVELS = (240.0, 360.0, 480.0)


def test_the_declared_width_is_the_same_distance_at_every_price_level() -> None:
    """The whole repair, in one assertion: ``width_pct x U`` gave a different width
    (and therefore a different R scale) on every underlying, which is what failed
    gate 0.5.  ``width_usd`` gives $8.00 at $240 and at $480 alike."""
    for spot in PRICE_LEVELS:
        chain, under = build_chain(sigma=MECH_SIGMA, spot=spot)
        short, long_ = _selected(strategy(), chain, under)
        assert short - long_ == pytest.approx(8.00)


def test_a_ladder_that_cannot_place_the_declared_width_exactly_is_a_non_entry() -> None:
    """D5a §3.4 replaces D5 §3.3(3)'s +/-50% tolerance with exactness, because a
    run whose widths vary by 50% carries three R scales and gate 0.5 refuses it.

    A coarse ladder therefore produces a NON-ENTRY rather than a silently
    rewritten width — the same hazard the tolerance was written for, handled more
    strictly rather than less.
    """
    coarse, under = build_chain(sigma=MECH_SIGMA, step=5)
    assert strategy()(coarse.head(SIGNAL_IDX), under.head(SIGNAL_IDX), SIGNAL_IDX) is None


def test_the_long_wing_always_sits_strictly_further_otm_than_the_short() -> None:
    """A naked short is not representable: ``OptionStructure`` refuses it."""
    chain, under = build_chain(sigma=MECH_SIGMA)
    short, long_ = _selected(strategy(), chain, under)
    assert long_ < short
    sig = strategy()(chain.head(SIGNAL_IDX), under.head(SIGNAL_IDX), SIGNAL_IDX)
    assert sig is not None
    assert sig.structure.structure_type is StructureType.VERTICAL_CREDIT
    assert sig.structure.contracts == 1


# --------------------------------------------------------------------------- #
# the fail-closed inputs
# --------------------------------------------------------------------------- #
def test_no_sourced_q_produces_no_entry_at_all() -> None:
    """``q = 0.0`` by default is a gate-0.g failure, so it is never substituted."""
    chain, under = build_chain()
    bare = OptionsShortVertical()
    assert bare.q_lookup is None
    assert bare(chain.head(SIGNAL_IDX), under.head(SIGNAL_IDX), SIGNAL_IDX) is None

    missing = OptionsShortVertical(q_lookup=lambda _s, _d: None)
    assert missing(chain.head(SIGNAL_IDX), under.head(SIGNAL_IDX), SIGNAL_IDX) is None


def test_a_thin_print_may_not_set_an_iv_or_fill() -> None:
    """D5 §2.4: a single-lot print struck hours before the close, inverted to an
    IV and used to pick the strike, is an asynchronous error of unbounded sign
    that no continuity fraction can detect — a bar exists."""
    thin, under = build_chain(volume=3.0)
    assert strategy()(thin.head(SIGNAL_IDX), under.head(SIGNAL_IDX), SIGNAL_IDX) is None

    few_trades, under2 = build_chain(transactions=1)
    assert strategy()(few_trades.head(SIGNAL_IDX), under2.head(SIGNAL_IDX), SIGNAL_IDX) is None

    # a null `transactions` is tolerated — the provider does not always populate it
    null_trades, under3 = build_chain(transactions=None)
    assert strategy()(null_trades.head(SIGNAL_IDX), under3.head(SIGNAL_IDX), SIGNAL_IDX) is not None


def test_a_non_100_deliverable_contract_is_never_selected() -> None:
    odd, under = build_chain(shares_per_contract=10)
    assert strategy()(odd.head(SIGNAL_IDX), under.head(SIGNAL_IDX), SIGNAL_IDX) is None


def test_the_strategy_is_handed_a_truncated_view_it_cannot_opt_out_of() -> None:
    """``head(t)`` truncates the visible CONTRACT set as well as the sessions, so
    a strike that had not yet printed is not selectable."""
    chain, _under = build_chain()
    late = chain.head(SIGNAL_IDX)
    assert len(late) == SIGNAL_IDX + 1
    assert all(c.first_print_session <= SESSIONS[SIGNAL_IDX] for c in late.contracts.values())


# --------------------------------------------------------------------------- #
# end to end through the engine
# --------------------------------------------------------------------------- #
def test_the_strategy_drives_the_engine_to_a_closed_structure() -> None:
    chain, under = build_chain(sigma=MECH_SIGMA)
    outcome = run_options_backtest(
        chain,
        under,
        strategy(),
        cost_model=PREREGISTERED_COST_MODEL,
        r_basis=RBasis.INCL,
        warmup=0,
    )
    assert len(outcome.trades) == 1
    trade = outcome.trades[0]
    assert trade.structure_type is StructureType.VERTICAL_CREDIT
    assert trade.r_basis is RBasis.INCL
    assert trade.r_incl > trade.r_at_print  # entry costs are inside the gating denominator
    assert trade.entry_date == SESSIONS[SIGNAL_IDX + 1]  # filled at t+1's prints
    assert trade.iv_source.value == "local_bs_inverted"
    assert trade.q_source == "test:vendor_dividends"
    assert "close_basis_stop" in trade.fill_model


def test_the_engine_goes_flat_between_cycles_so_nothing_overlaps() -> None:
    chain, under = build_chain(sigma=MECH_SIGMA)
    outcome = run_options_backtest(
        chain, under, strategy(), cost_model=PREREGISTERED_COST_MODEL, warmup=0
    )
    spans = [(t.entry_date, t.exit_date) for t in outcome.trades]
    assert all(a[1] < b[0] for a, b in pairwise(spans))


# --------------------------------------------------------------------------- #
# §2 — THE BOUND TABLES.  Reproduced so neither amendment can be reverted.
# --------------------------------------------------------------------------- #
#: D5a §0.3's declared dividend yields, per Stage A underlying.  They are an
#: assumption **for this derivation only**: at evaluation time ``q`` is sourced per
#: underlying per session and an unsourced ``q`` is still a non-entry.
STAGE_A_Q: dict[float, float] = {660.0: 0.013, 590.0: 0.006, 240.0: 0.013}

#: D5a §2.3's declared IV grid over the Stage A levels — 30 cells.
IV_GRID = (0.12, 0.15, 0.18, 0.20, 0.25, 0.30, 0.35, 0.40, 0.50, 0.60)

#: Entry costs of one 2-leg structure, from the SHIPPED cost model: $1.60.
ENTRY_COSTS = PREREGISTERED_COST_MODEL.commission(2) + PREREGISTERED_COST_MODEL.fees(2)

#: D5 §2.2's declared population, all on the same monthly third-Friday cycle.
DECLARED_UNDERLYINGS = 14


def _short_strike(spot: float, sigma: float, q: float) -> int:
    deltas = {
        k: abs(bs.greeks(spot, float(k), YEARS, R, sigma, call=False, q=q).delta)
        for k in range(int(spot * 0.60), int(spot) + 1)
    }
    return min(
        (k for k, d in deltas.items() if d <= 0.35 and abs(d - 0.20) <= 0.05),
        key=lambda k: (abs(deltas[k] - 0.20), k),
    )


def _adverse_ratio(spot: float, sigma: float, width: float, *, q: float | None = None) -> float:
    """The adverse credit-to-width ratio D5a §2.3 tabulates, from the SHIPPED cost
    model rather than a re-implementation of it."""
    q = STAGE_A_Q.get(spot, Q) if q is None else q
    cm = PREREGISTERED_COST_MODEL
    ks = _short_strike(spot, sigma, q)
    kl = ks - width
    ps = bs.price(spot, float(ks), YEARS, R, sigma, call=False, q=q)
    pl = bs.price(spot, kl, YEARS, R, sigma, call=False, q=q)
    sell = max(
        cm.round_to_tick(max(ps - cm.spread(ps, moneyness=ks / spot, dte=35), 0.0), side=Side.SELL),
        0.0,
    )
    buy = cm.round_to_tick(pl + cm.spread(pl, moneyness=kl / spot, dte=35), side=Side.BUY)
    return (sell - buy) / width


def _target_win_usd(spot: float, sigma: float, width: float) -> float:
    """D5a §4's ``0.5 C - F``: half the adverse credit minus the four-crossing
    round-trip friction ``F``, which the leg PRINTS set and the width barely moves."""
    cm = PREREGISTERED_COST_MODEL
    q = STAGE_A_Q[spot]
    credit = _adverse_ratio(spot, sigma, width) * width * 100.0
    ks = _short_strike(spot, sigma, q)
    ps = bs.price(spot, float(ks), YEARS, R, sigma, call=False, q=q)
    pl = bs.price(spot, float(ks - width), YEARS, R, sigma, call=False, q=q)
    friction = (
        2
        * 100
        * (cm.spread(ps, moneyness=ks / spot, dte=35) + cm.spread(pl, moneyness=1.0, dte=35))
        + cm.commission(4)
        + cm.fees(4)
    )
    return 0.5 * credit - friction


def _design_space(width: float) -> list[float]:
    return [_adverse_ratio(s, g, width) for s in (660.0, 590.0, 240.0) for g in IV_GRID]


def _round_down(x: float, step: float) -> float:
    return round(math.floor(x / step + 1e-9) * step, 6)


@pytest.mark.parametrize("width", [2.00, 8.00])
def test_the_credit_to_width_ratio_is_bounded_by_roughly_the_short_delta(width: float) -> None:
    """Arithmetic, not opinion — D5a §2.1, at both the v0.1.1 and v0.1.2 widths.

    ``credit = P(K_short) - P(K_long)``, and by the mean value theorem that is
    ``dP/dK x width`` somewhere inside the strike range, where
    ``dP/dK = e^{-rT} N(-d2)`` — the risk-neutral probability of finishing ITM,
    which is slightly above ``|delta|`` at the short strike and **falls** toward
    the wing.  So ``credit/width`` is bounded above by roughly the short delta
    and sits below it for any width worth trading — and further below it the
    wider the width, because the average is taken further toward the wing.
    """
    for spot in (240.0, 590.0, 660.0):
        q = STAGE_A_Q[spot]
        for sigma in (0.15, 0.20, 0.30, 0.40, 0.60):
            ks = _short_strike(spot, sigma, q)
            delta = abs(bs.greeks(spot, float(ks), YEARS, R, sigma, call=False, q=q).delta)
            ps = bs.price(spot, float(ks), YEARS, R, sigma, call=False, q=q)
            pl = bs.price(spot, float(ks - width), YEARS, R, sigma, call=False, q=q)
            print_ratio = (ps - pl) / width
            assert print_ratio <= delta + 0.06, (spot, sigma, print_ratio, delta)
            assert print_ratio < 0.25 + 0.12, (spot, sigma, print_ratio)


#: D5a §2.3's table, verbatim: (U, sigma) -> adverse credit/width at width_usd 2.00,
#: ``short_delta_target`` 0.20, 35 DTE, r 0.04.  **v0.1.1 history**: still follows
#: from the shipped code and is kept so the superseded band stays checkable.  The
#: signs are the finding: the index ETFs at $590-$660 go NEGATIVE above ~0.25 vol.
D5A_BOUND_TABLE: dict[tuple[float, float], float] = {
    (660.0, 0.15): +0.0750,
    (660.0, 0.30): -0.0250,
    (660.0, 0.60): -0.2250,
    (590.0, 0.15): +0.1050,
    (590.0, 0.30): +0.0250,
    (590.0, 0.60): -0.1750,
    (240.0, 0.15): +0.1550,
    (240.0, 0.30): +0.1400,
    (240.0, 0.60): +0.0500,
}

#: Amendment 2 §4.1's table: the same cells at v0.1.2's ``width_usd = 8.00``.  The
#: charge ``chi = 100 (s_short + s_wing) / W`` scales as ``1/W``, so a 4x wider wing
#: cuts it to about a quarter and every cell turns positive.  Several values are
#: exact multiples of 0.00625 = $5 / $800 — the $0.05 tick above $3.00, per $8 wide.
D5A2_BOUND_TABLE: dict[tuple[float, float], float] = {
    (660.0, 0.15): 0.15000,
    (660.0, 0.30): 0.15625,
    (660.0, 0.60): 0.13125,
    (590.0, 0.15): 0.15250,
    (590.0, 0.30): 0.15625,
    (590.0, 0.60): 0.14375,
    (240.0, 0.15): 0.12375,
    (240.0, 0.30): 0.16375,
    (240.0, 0.60): 0.18125,
}


@pytest.mark.parametrize(("cell", "expected"), sorted(D5A_BOUND_TABLE.items()))
def test_the_v011_bound_table_at_two_dollars_is_still_reproduced(
    cell: tuple[float, float], expected: float
) -> None:
    """D5a's load-bearing table, recomputed from the shipped code.  If this fails
    the cost model moved (R4 forbids it) — not merely the width."""
    spot, sigma = cell
    assert _adverse_ratio(spot, sigma, 2.00) == pytest.approx(expected, abs=5e-4)


@pytest.mark.parametrize(("cell", "expected"), sorted(D5A2_BOUND_TABLE.items()))
def test_the_v012_bound_table_at_eight_dollars_is_reproduced(
    cell: tuple[float, float], expected: float
) -> None:
    """**Amendment 2's load-bearing table, recomputed from the shipped code.**

    If this test fails, either the cost model moved (R4 forbids it) or someone
    changed the derivation the v0.1.2 floor band was read off.  Either way the
    amendment's numbers no longer follow from the code and must be re-derived in
    the open, before the first sealed look — never after one.
    """
    spot, sigma = cell
    assert _adverse_ratio(spot, sigma, 8.00) == pytest.approx(expected, abs=5e-4)
    assert ShortVerticalParams().width_usd == 8.00


def test_the_v011_band_is_what_d5as_rule_gives_at_two_dollars() -> None:
    """History, re-derived: at $2.00 the design space ran -0.2250 .. +0.1550,
    positive in 21 of 30 cells, and the rule gave 0.05 / 0.10 / 0.13."""
    space = _design_space(2.00)
    positive = sorted(v for v in space if v > 0)
    assert min(space) == pytest.approx(-0.2250, abs=5e-4)
    assert max(space) == pytest.approx(0.1550, abs=5e-4)
    assert len(positive) == 21
    q1, q2, q3 = statistics.quantiles(positive, n=4, method="inclusive")
    assert [_round_down(v, 0.01) for v in (q1, q2, q3)] == [0.05, 0.10, 0.13]


def test_the_v012_band_is_read_off_the_eight_dollar_design_space() -> None:
    """**Amendment 2 §4.2, as arithmetic.**

    At $8.00 the attainable adverse ratio over Stage A x the IV grid runs 0.0938 ..
    0.1813 and is positive in all 30 cells.  Its quartiles are 0.14375 / 0.15188 /
    0.15625.  D5a's rule rounds DOWN to 0.01, which gives 0.14 / 0.15 / **0.15** —
    the median and p75 collapse and axis 6 would have one value.  Rounding down to
    the next finer step, 0.005, keeps the direction (never toward the unreachable
    side) and separates them: 0.140 / 0.150 / 0.155.
    """
    space = _design_space(8.00)
    positive = sorted(v for v in space if v > 0)
    assert len(positive) == len(space) == 30
    assert min(space) == pytest.approx(0.09375, abs=5e-4)
    assert max(space) == pytest.approx(ATTAINABLE_ADVERSE_RATIO_MAX, abs=5e-4)
    q1, q2, q3 = statistics.quantiles(positive, n=4, method="inclusive")
    assert (q1, q2, q3) == pytest.approx((0.14375, 0.151875, 0.15625), abs=5e-5)
    # D5a's 0.01 step collapses the median and p75 — a one-valued axis
    coarse = [_round_down(v, 0.01) for v in (q1, q2, q3)]
    assert coarse == [0.14, 0.15, 0.15]
    fine = [_round_down(v, 0.005) for v in (q1, q2, q3)]
    assert fine == [0.140, 0.150, 0.155]
    assert dict(zip(("p25", "median", "p75"), fine, strict=True)) == CREDIT_TO_WIDTH_QUANTILES


def test_every_superseded_floor_is_outside_the_attainable_region() -> None:
    """D5's 0.25 / 0.30 and its OAT 0.20 sit above the attainable maximum at BOTH
    widths, so v0.1.0 would still enter nothing anywhere."""
    for table in (D5A_BOUND_TABLE, D5A2_BOUND_TABLE):
        attainable = max(table.values())
        for superseded in (0.20, 0.25, 0.30):
            assert superseded > attainable


def test_the_amended_band_sits_inside_the_attainable_region() -> None:
    band = CREDIT_TO_WIDTH_QUANTILES
    assert band == {"p25": 0.140, "median": 0.150, "p75": 0.155}
    assert band["p25"] < band["median"] < band["p75"] < ATTAINABLE_ADVERSE_RATIO_MAX
    assert ShortVerticalParams().min_credit_to_width == band["median"]
    assert SENSITIVITY_GRID["min_credit_to_width"] == (band["median"], band["p75"])
    assert OAT_PARAMETERS["min_credit_to_width"] == (band["p25"],)


def test_the_v012_band_binds_without_emptying_and_the_v011_floor_would_not_bind() -> None:
    """A floor must BIND (D5 §1) without EMPTYING the space (D5 §4.3).

    Over the 30 cells at $8.00: 0.140 admits 25, 0.150 admits 19, 0.155 admits 13
    — each binds and none is empty.  v0.1.1's 0.10 would admit 29 of 30 and 0.13
    would admit 28: carried forward to $8 they would be near-inert, which is why
    the band is re-derived rather than kept.  Compared as exact arithmetic (the
    strategy's ``_RATIO_EPS``), because 0.150 sits on the $5-per-$800 lattice.
    """
    space = _design_space(8.00)

    def admitted(floor: float) -> int:
        return sum(v >= floor - 1e-9 for v in space)

    assert [admitted(f) for f in (0.140, 0.150, 0.155)] == [25, 19, 13]
    assert [admitted(f) for f in (0.10, 0.13)] == [29, 28]


def test_the_mechanism_sigma_clears_the_baseline_floor() -> None:
    """``MECH_SIGMA`` is derived: 0.20 and 0.25 do NOT clear 0.150 on the $240
    chain at $8, and 0.30 clears every grid and OAT value."""
    assert _adverse_ratio(SPOT, 0.20, 8.00, q=Q) < 0.150
    assert _adverse_ratio(SPOT, 0.25, 8.00, q=Q) < 0.150
    assert _adverse_ratio(SPOT, MECH_SIGMA, 8.00, q=Q) >= max(CREDIT_TO_WIDTH_QUANTILES.values())


@pytest.mark.parametrize("sigma", [0.30, 0.35, 0.40])
@pytest.mark.parametrize("floor", [0.140, 0.150, 0.155])
def test_the_amended_floor_trades_where_the_superseded_floor_traded_nothing(
    sigma: float, floor: float
) -> None:
    """On the same arbitrage-free chain, at the same delta band and the same frozen
    cost model: every v0.1.2 band value enters, and every value D5 pre-registered
    still enters nothing.  The sigmas are the ones Amendment 2's $240 row clears
    (0.1637 / 0.1650 / 0.1662 >= 0.155)."""
    chain, under = build_chain(sigma=sigma)
    amended = OptionsShortVertical(
        ShortVerticalParams(min_credit_to_width=floor), q_lookup=_q, q_source="test"
    )
    assert amended(chain.head(SIGNAL_IDX), under.head(SIGNAL_IDX), SIGNAL_IDX) is not None

    for superseded in (0.20, 0.25, 0.30):
        stale = OptionsShortVertical(
            ShortVerticalParams(min_credit_to_width=superseded), q_lookup=_q, q_source="test"
        )
        assert stale(chain.head(SIGNAL_IDX), under.head(SIGNAL_IDX), SIGNAL_IDX) is None


def test_the_floor_still_binds_and_is_not_merely_lowered_until_everything_passes() -> None:
    """A floor that admits everything is not a floor.  Walked up on one chain, the
    strategy clears exactly the floors at or below that chain's derived adverse
    ratio (0.16375) and none above it."""
    chain, under = build_chain(sigma=MECH_SIGMA)
    ratio = _adverse_ratio(SPOT, MECH_SIGMA, 8.00, q=Q)
    walk = (0.140, 0.150, 0.155, 0.16, 0.165, 0.20, 0.25, 0.30)
    cleared = [
        floor
        for floor in walk
        if OptionsShortVertical(
            ShortVerticalParams(min_credit_to_width=floor), q_lookup=_q, q_source="test"
        )(chain.head(SIGNAL_IDX), under.head(SIGNAL_IDX), SIGNAL_IDX)
        is not None
    ]
    assert cleared == [f for f in walk if f <= ratio]
    assert cleared == [0.140, 0.150, 0.155, 0.16]


@pytest.mark.parametrize("sigma", [0.15, 0.20, 0.35])
def test_a_ratio_exactly_on_the_floor_is_admitted_whatever_the_float_rounding(
    sigma: float,
) -> None:
    """Amendment 2 §4.4.  On the $660 chain these cells' adverse credit is exactly
    $120 on an $800 width — ratio 0.150, the baseline floor itself.  In floats
    ``(sell - buy) * 100 / 800`` lands either side of 0.15, so without the
    strategy's ``_RATIO_EPS`` the pre-registered ``>=`` would depend on rounding."""
    assert _adverse_ratio(660.0, sigma, 8.00, q=Q) == pytest.approx(0.150, abs=1e-12)
    chain, under = build_chain(sigma=sigma, spot=660.0, symbol="SPY")
    assert strategy()(chain.head(SIGNAL_IDX), under.head(SIGNAL_IDX), SIGNAL_IDX) is not None


def test_the_stop_is_a_real_stop_at_every_grid_and_oat_value() -> None:
    """D5 §3.4: the stop binds only while ``stop_multiple x c/W < 1``.  At D5's
    floors the high value was near-degenerate (``3.0 x 0.30 = 0.90``); at $2 the
    worst case was ``3.0 x 0.155 = 0.465`` and at v0.1.2's $8 it is
    ``3.0 x 0.1813 = 0.544`` — still a stop that fires well before max loss.
    """
    for multiple in (1.5, 2.0, 3.0):
        assert multiple * ATTAINABLE_ADVERSE_RATIO_MAX < 1.0
    assert pytest.approx(0.90) == 3.0 * 0.30
    assert pytest.approx(0.544, abs=5e-4) == 3.0 * ATTAINABLE_ADVERSE_RATIO_MAX


# --------------------------------------------------------------------------- #
# §3 — ONE R SCALE PER VERSION, the OP-1 $900 / $3,600 caps, and F14
# --------------------------------------------------------------------------- #
def test_gate_0_5_passes_on_a_genuinely_multi_underlying_trade_list() -> None:
    """``width_pct x U`` gave R a different scale on every underlying, so gate 0.5's
    ``single_scale`` refused any multi-underlying run.  With a declared dollar
    width the recovered width is $800.00 at every price level."""
    strat = strategy()
    trades = []
    for spot in PRICE_LEVELS:
        chain, under = build_chain(sigma=MECH_SIGMA, spot=spot)
        outcome = run_options_backtest(
            chain, under, strat, cost_model=PREREGISTERED_COST_MODEL, r_basis=RBasis.INCL, warmup=0
        )
        assert outcome.trades, f"no entry at spot {spot}"
        trades.extend(outcome.trades)

    gate = gate_0_5_structure(strat.structure_identity(), trades)
    assert gate.passed, gate.detail
    assert gate.evidence["widths_observed"] == [800.0]
    assert gate.evidence["r_scale_usd"] == 800.0
    assert gate.evidence["width_selected_adaptively"] is False


def test_the_structure_identity_is_a_constant_of_the_version() -> None:
    ident = strategy().structure_identity()
    assert ident.width_declared == 8.00
    assert ident.m_declared == 100
    assert ident.r_scale_usd == 800.00
    assert ident.structure_type is StructureType.VERTICAL_CREDIT


def test_every_copy_of_the_op1_caps_agrees() -> None:
    """The strategy's fail-closed guard, gate 0.i's thresholds and the paper-book
    refusal limits must carry the SAME operator numbers (OP-1, 2026-09-23)."""
    th = OptionsGateThresholds()
    limits = OptionsRiskLimits()
    assert OPTIONS_PER_STRUCTURE_MAX_LOSS == th.options_per_structure_max_loss == 900.0
    assert limits.per_structure_max_loss_dollars == 900.0
    assert th.options_total_open_max_loss == limits.total_open_max_loss_dollars == 3_600.0
    # OP-1's recommendation expressed them against the $25,000 options account
    assert 900.0 / th.account_equity_basis == pytest.approx(0.036)
    assert 3_600.0 / th.account_equity_basis == pytest.approx(0.144)


def test_the_width_ceiling_under_the_op1_cap_is_eight_dollars() -> None:
    """Amendment 2 §3.1: ``width_usd x 100 + $1.60 <= $900`` gives ``width_usd <=
    8.984``; the widest multiple of the declared $1.00 increment is $8.00."""
    assert pytest.approx(1.60) == ENTRY_COSTS
    ceiling = (OPTIONS_PER_STRUCTURE_MAX_LOSS - ENTRY_COSTS) / 100.0
    assert ceiling == pytest.approx(8.984)
    widest = math.floor(ceiling / DECLARED_STRIKE_INCREMENT) * DECLARED_STRIKE_INCREMENT
    assert widest == 8.00 == ShortVerticalParams().width_usd


def test_the_hard_max_loss_clears_the_nine_hundred_dollar_cap() -> None:
    """``R_hard = width_usd x M + entry_costs`` is the bound no credit can breach,
    because the strategy refuses ``net_credit <= 0`` outright — so the margin
    holds at EVERY floor, not only at the baseline one."""
    p = ShortVerticalParams()
    assert p.r_scale_usd == 800.0
    assert p.r_hard_max_usd == pytest.approx(801.60)
    assert p.r_hard_max_usd < OPTIONS_PER_STRUCTURE_MAX_LOSS
    margin = (OPTIONS_PER_STRUCTURE_MAX_LOSS - p.r_hard_max_usd) / OPTIONS_PER_STRUCTURE_MAX_LOSS
    assert margin == pytest.approx(0.1093, abs=5e-4)


def test_no_realised_trade_ever_exceeds_the_per_structure_cap() -> None:
    strat = strategy()
    for spot in PRICE_LEVELS:
        chain, under = build_chain(sigma=MECH_SIGMA, spot=spot)
        outcome = run_options_backtest(
            chain, under, strat, cost_model=PREREGISTERED_COST_MODEL, r_basis=RBasis.INCL, warmup=0
        )
        for trade in outcome.trades:
            assert trade.r_incl <= OPTIONS_PER_STRUCTURE_MAX_LOSS
            assert trade.r_incl <= ShortVerticalParams().r_hard_max_usd


@pytest.mark.parametrize(
    ("width_usd", "hard_max", "fits"),
    [
        (2.00, 201.60, True),
        (7.00, 701.60, True),
        (8.00, 801.60, True),
        (8.50, 851.60, True),
        (9.00, 901.60, False),
        (10.00, 1001.60, False),
    ],
)
def test_the_width_cap_arithmetic_is_what_selected_eight_dollars(
    width_usd: float, hard_max: float, fits: bool
) -> None:
    """Amendment 2 §3.1's table, as a test.  $9.00 clears the cap at the baseline
    floor (``900 x 0.85 + 1.60 = $766.60``) but not on the hard bound, and D5a's
    convention — kept — is that the margin must hold at EVERY floor.  $8.50 fits
    but is not a multiple of the $1.00 increment, so it is rejected on
    placeability.  $8.00 is therefore the widest admissible width.
    """
    assert width_usd * 100 + ENTRY_COSTS == pytest.approx(hard_max)
    assert (hard_max <= OPTIONS_PER_STRUCTURE_MAX_LOSS) is fits
    if fits:
        assert OptionsShortVertical(ShortVerticalParams(width_usd=width_usd)) is not None
    else:
        with pytest.raises(ValueError, match="breaches the pre-registered per-structure cap"):
            OptionsShortVertical(ShortVerticalParams(width_usd=width_usd))
    if width_usd == 8.50:
        assert not math.isclose(width_usd % DECLARED_STRIKE_INCREMENT, 0.0, abs_tol=1e-9)
    if width_usd == 9.00:
        assert 900 * (1 - 0.150) + ENTRY_COSTS < OPTIONS_PER_STRUCTURE_MAX_LOSS


#: D5a §4's F14 cells.
F14_CELLS = (
    (660.0, 0.15),
    (660.0, 0.20),
    (660.0, 0.30),
    (590.0, 0.15),
    (590.0, 0.20),
    (590.0, 0.30),
    (240.0, 0.15),
    (240.0, 0.20),
    (240.0, 0.30),
)


def test_f14_the_target_win_is_negative_in_every_cell_at_the_v011_width() -> None:
    """**F14 as D5a pre-registered it** (history, still true): at $2.00 ``0.5C - F``
    is a LOSS in every Stage A cell."""
    for spot, sigma in F14_CELLS:
        assert _target_win_usd(spot, sigma, 2.00) < 0.0, (spot, sigma)


def test_f14_the_target_win_is_positive_in_seven_of_nine_cells_at_eight_dollars() -> None:
    """**Amendment 2 §3.2.**  At $8.00 ``0.5C - F`` is positive everywhere except
    SPY and QQQ at sigma 0.30 (-$17.64 and -$8.24).  OP-1 makes O3 cost-viable on
    most of the declared space — not all of it, and that is pre-registered too."""
    wins = {cell: _target_win_usd(*cell, 8.00) for cell in F14_CELLS}
    negative = sorted(cell for cell, w in wins.items() if w <= 0.0)
    assert negative == [(590.0, 0.30), (660.0, 0.30)]
    assert wins[(660.0, 0.30)] == pytest.approx(-17.64, abs=0.01)
    assert wins[(590.0, 0.30)] == pytest.approx(-8.24, abs=0.01)
    assert wins[(660.0, 0.15)] == pytest.approx(23.37, abs=0.01)
    assert wins[(240.0, 0.30)] == pytest.approx(38.33, abs=0.01)


#: D5a §4's minimum cost-viable width per cell (reproduced, not copied).
MIN_VIABLE_WIDTH: dict[tuple[float, float], int] = {
    (660.0, 0.15): 6,
    (660.0, 0.20): 8,
    (660.0, 0.30): 10,
    (590.0, 0.15): 5,
    (590.0, 0.20): 7,
    (590.0, 0.30): 9,
    (240.0, 0.15): 3,
    (240.0, 0.20): 3,
    (240.0, 0.30): 4,
}


def test_the_cost_viable_widths_and_which_the_op1_cap_admits() -> None:
    """Amendment 2 §3.2's cross-check against F14's viable range.

    D5a quoted the viable range as $254-$842 of CREDIT-NET R.  The guard (and gate
    0.i's hard reading) uses ``R_hard = W x 100 + $1.60``, on which the same
    widths cost **$301.60-$1,001.60**.  The $900 cap admits 7 of the 9; SPY at
    sigma 0.30 ($10 -> $1,001.60) and QQQ at sigma 0.30 ($9 -> $901.60) stay out.
    D5a's '~$900 (SPY at sigma 0.30)' was read off the credit-net column.
    """
    for cell, expected in MIN_VIABLE_WIDTH.items():
        viable = [w for w in range(1, 12) if _target_win_usd(*cell, float(w)) > 0.0]
        assert viable and viable[0] == expected, (cell, viable)
    hard = {cell: w * 100 + ENTRY_COSTS for cell, w in MIN_VIABLE_WIDTH.items()}
    assert min(hard.values()) == pytest.approx(301.60)
    assert max(hard.values()) == pytest.approx(1001.60)
    admitted = sorted(c for c, r in hard.items() if r <= OPTIONS_PER_STRUCTURE_MAX_LOSS)
    assert len(admitted) == 7
    assert (660.0, 0.30) not in admitted and (590.0, 0.30) not in admitted
    declared = ShortVerticalParams().width_usd
    assert all(w <= declared for c, w in MIN_VIABLE_WIDTH.items() if c in admitted)


def test_the_aggregate_leg_at_the_op1_numbers() -> None:
    """Amendment 2 §3.3 (was D5a §3.5's ``14 x $201.60 = $2,822.40`` vs $1,000).

    At $8.00: ``14 x $801.60 = $11,222.40`` against the $3,600 aggregate, so at most
    ``floor(3600 / 801.60) = 4`` structures may be open at once and D5a §3.5's
    pre-registered 4-structure concurrency branch applies.  (At $2.00 the whole
    population would fit — ``$2,822.40 <= $3,600`` — which is the trade the wider,
    cost-viable width makes: n for viability.)
    """
    agg = OptionsGateThresholds().options_total_open_max_loss
    r_hard = ShortVerticalParams().r_hard_max_usd
    assert DECLARED_UNDERLYINGS * r_hard == pytest.approx(11_222.40)
    assert DECLARED_UNDERLYINGS * r_hard > agg
    assert math.floor(agg / r_hard) == 4
    assert DECLARED_UNDERLYINGS * ShortVerticalParams(width_usd=2.00).r_hard_max_usd <= agg


# --------------------------------------------------------------------------- #
# D5a §5 — OQ-1 ratified
# --------------------------------------------------------------------------- #
def test_the_horizon_is_medium_swing_because_position_is_arithmetically_impossible() -> None:
    """``Horizon`` is a HOLDING-period vocabulary (``domain.py:15-18``), and this
    structure's holding period is bounded by its own time stop, not by its DTE.

    Longest possible hold at the baseline is ``dte_target - time_stop_dte`` = 28
    calendar days = 4.0 weeks; at the grid's other DTE value it is 14 days.
    POSITION's lower bound is ~2 months (~8.7 weeks) — more than 1.8x the longest
    hold the design can produce — so no trade it generates could ever be one.
    """
    strat = strategy()
    assert strat.horizon is Horizon.MEDIUM_SWING
    assert strat.spec().horizon is Horizon.MEDIUM_SWING
    assert strat.key.endswith(".medium_swing")

    p = ShortVerticalParams()
    longest_hold_days = p.dte_target - p.time_stop_dte
    assert longest_hold_days == 28
    assert longest_hold_days / 7.0 <= 8.0  # inside MEDIUM_SWING's "2-8 weeks"
    # and strictly short of POSITION's "2-6 months" lower bound, even allowing the
    # expiry-1 force close after a print deferral
    force_close_hold_days = p.dte_target - 1
    assert force_close_hold_days / 30.44 < 2.0
