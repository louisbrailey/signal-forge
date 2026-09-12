"""O3 — the D5/D5a v0.1.1 short vertical, on SYNTHETIC chains only (I-O5, W3a).

No real option price, IV, greek, credit, return or P&L is read anywhere here.
Every chain is priced from Black-Scholes at a chosen sigma, so the strategy's
inverted IV comes back as that sigma exactly and the delta it selects on is
arithmetic the reader can check.

The last three sections are the **amendment's own arithmetic**, reproduced as
tests so that D5a cannot be silently reverted:

* §2 — the credit-to-width bound: the ceiling is the short delta, the adverse
  charge eats it, the attainable region is ``(0, 0.155]``, and every floor D5
  pre-registered (0.20 / 0.25 / 0.30) sits outside it while the amended band
  (0.05 / 0.10 / 0.13) sits inside it and trades.
* §3 — one R scale per version: the same ``$200.00`` on every underlying, so
  gate 0.5 passes and gate 0.i's $250 per-structure cap clears with a margin no
  parameter setting can breach.
* §5 — OQ-1: the holding period is bounded by the time stop, and POSITION is
  arithmetically impossible.
"""

from __future__ import annotations

import math
from datetime import date
from itertools import pairwise

import pytest

from signalforge.backtest.options_costs import Side
from signalforge.backtest.options_engine import (
    RBasis,
    StructureType,
    run_options_backtest,
)
from signalforge.data import calendar, options_calendar
from signalforge.data.option_chain import ContractPrint, ContractRef, OptionChainSeries, Right
from signalforge.data.series import PriceSeries
from signalforge.domain import Horizon
from signalforge.options import blackscholes as bs
from signalforge.research.options_gates import gate_0_5_structure
from signalforge.research.options_strategies import (
    ATTAINABLE_ADVERSE_RATIO_MAX,
    CREDIT_TO_WIDTH_QUANTILES,
    OPTIONS_PER_STRUCTURE_MAX_LOSS,
    PREREGISTERED_COST_MODEL,
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


def _ticker(right: Right, strike: float, sym: str = "IWM") -> str:
    return f"O:{sym}240315{'P' if right is Right.PUT else 'C'}{int(strike * 1000):08d}"


def build_chain(
    *,
    sigma: float = 0.20,
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
    """The strategy at its **pre-registered v0.1.1 parameters**.

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
def test_a_bear_regime_sells_the_call_side_mirror() -> None:
    """The mirror is what makes gate 6's bear bucket reachable at all."""
    chain, under = build_chain()
    strat = strategy()
    strat.proxy_regimes = _regimes(dict.fromkeys(range(len(SESSIONS)), Trend.BEAR))
    sig = strat(chain.head(SIGNAL_IDX), under.head(SIGNAL_IDX), SIGNAL_IDX)
    assert sig is not None
    assert {leg.contract.right for leg in sig.structure.legs} == {Right.CALL}


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
    strat = strategy()
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
    chain, under = build_chain(sigma=0.20)
    short, _ = _selected(strategy(), chain, under)
    deltas = {
        k: abs(bs.greeks(SPOT, float(k), YEARS, R, 0.20, call=False, q=Q).delta)
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
    chain, under = build_chain(sigma=0.20)
    short_loose, _ = _selected(
        strategy(short_delta_target=0.30, max_short_delta=0.35), chain, under
    )
    short_capped, _ = _selected(
        strategy(short_delta_target=0.30, max_short_delta=0.28), chain, under
    )
    capped_delta = abs(bs.greeks(SPOT, short_capped, YEARS, R, 0.20, call=False, q=Q).delta)
    assert capped_delta <= 0.28
    assert short_capped != short_loose  # the axis genuinely binds, it is not inert


def test_no_strike_within_the_delta_tolerance_is_a_non_entry() -> None:
    chain, under = build_chain(sigma=0.20)
    assert (
        strategy(short_delta_target=0.02, delta_tolerance=0.001)(
            chain.head(SIGNAL_IDX), under.head(SIGNAL_IDX), SIGNAL_IDX
        )
        is None
    )


@pytest.mark.parametrize("width_usd", [1.00, 2.00])
def test_the_wing_sits_at_exactly_the_declared_dollar_width(width_usd: float) -> None:
    """D5a §3: the width is dollars of STRIKE DISTANCE per contract, a constant of
    the version — not a fraction of the underlying close."""
    chain, under = build_chain(sigma=0.20)
    short, long_ = _selected(strategy(width_usd=width_usd), chain, under)
    assert short - long_ == pytest.approx(width_usd)


def test_the_declared_width_is_the_same_distance_at_every_price_level() -> None:
    """The whole repair, in one assertion: ``width_pct x U`` gave a different width
    (and therefore a different R scale) on every underlying, which is what failed
    gate 0.5.  ``width_usd`` gives $2.00 at $120 and at $360 alike."""
    for spot in (120.0, 240.0, 360.0):
        chain, under = build_chain(sigma=0.15, spot=spot)
        short, long_ = _selected(strategy(), chain, under)
        assert short - long_ == pytest.approx(2.00)


def test_a_ladder_that_cannot_place_the_declared_width_exactly_is_a_non_entry() -> None:
    """D5a §3.4 replaces D5 §3.3(3)'s +/-50% tolerance with exactness, because a
    run whose widths vary by 50% carries three R scales and gate 0.5 refuses it.

    A coarse ladder therefore produces a NON-ENTRY rather than a silently
    rewritten width — the same hazard the tolerance was written for, handled more
    strictly rather than less.
    """
    coarse, under = build_chain(sigma=0.20, step=5)
    assert strategy()(coarse.head(SIGNAL_IDX), under.head(SIGNAL_IDX), SIGNAL_IDX) is None


def test_the_long_wing_always_sits_strictly_further_otm_than_the_short() -> None:
    """A naked short is not representable: ``OptionStructure`` refuses it."""
    chain, under = build_chain(sigma=0.20)
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
    chain, under = build_chain(sigma=0.20)
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
    chain, under = build_chain(sigma=0.20)
    outcome = run_options_backtest(
        chain, under, strategy(), cost_model=PREREGISTERED_COST_MODEL, warmup=0
    )
    spans = [(t.entry_date, t.exit_date) for t in outcome.trades]
    assert all(a[1] < b[0] for a, b in pairwise(spans))


# --------------------------------------------------------------------------- #
# D5a §2 — THE BOUND TABLE.  Reproduced so the amendment cannot be reverted.
# --------------------------------------------------------------------------- #
#: D5a §0.3's declared dividend yields, per Stage A underlying.  They are an
#: assumption **for this derivation only**: at evaluation time ``q`` is sourced per
#: underlying per session and an unsourced ``q`` is still a non-entry.
STAGE_A_Q: dict[float, float] = {660.0: 0.013, 590.0: 0.006, 240.0: 0.013}


def _adverse_ratio(spot: float, sigma: float, width: float, *, q: float | None = None) -> float:
    """The adverse credit-to-width ratio D5a §2.3 tabulates, from the SHIPPED cost
    model rather than a re-implementation of it."""
    q = STAGE_A_Q.get(spot, Q) if q is None else q
    cm = PREREGISTERED_COST_MODEL
    deltas = {
        k: abs(bs.greeks(spot, float(k), YEARS, R, sigma, call=False, q=q).delta)
        for k in range(int(spot * 0.60), int(spot) + 1)
    }
    ks = min(
        (k for k, d in deltas.items() if d <= 0.35 and abs(d - 0.20) <= 0.05),
        key=lambda k: (abs(deltas[k] - 0.20), k),
    )
    kl = ks - width
    ps = bs.price(spot, float(ks), YEARS, R, sigma, call=False, q=q)
    pl = bs.price(spot, kl, YEARS, R, sigma, call=False, q=q)
    sell = max(
        cm.round_to_tick(max(ps - cm.spread(ps, moneyness=ks / spot, dte=35), 0.0), side=Side.SELL),
        0.0,
    )
    buy = cm.round_to_tick(pl + cm.spread(pl, moneyness=kl / spot, dte=35), side=Side.BUY)
    return (sell - buy) / width


def test_the_credit_to_width_ratio_is_bounded_by_roughly_the_short_delta() -> None:
    """Arithmetic, not opinion — D5a §2.1.

    ``credit = P(K_short) - P(K_long)``, and by the mean value theorem that is
    ``dP/dK x width`` somewhere inside the strike range, where
    ``dP/dK = e^{-rT} N(-d2)`` — the risk-neutral probability of finishing ITM,
    which is slightly above ``|delta|`` at the short strike and **falls** toward
    the wing.  So ``credit/width`` is bounded above by roughly the short delta
    and sits below it for any width worth trading.
    """
    for spot in (240.0, 590.0, 660.0):
        q = STAGE_A_Q[spot]
        for sigma in (0.15, 0.20, 0.30, 0.40, 0.60):
            deltas = {
                k: abs(bs.greeks(spot, float(k), YEARS, R, sigma, call=False, q=q).delta)
                for k in range(int(spot * 0.60), int(spot) + 1)
            }
            ks = min(deltas, key=lambda k: abs(deltas[k] - 0.20))
            kl = ks - 2
            ps = bs.price(spot, float(ks), YEARS, R, sigma, call=False, q=q)
            pl = bs.price(spot, float(kl), YEARS, R, sigma, call=False, q=q)
            print_ratio = (ps - pl) / (ks - kl)
            assert print_ratio <= deltas[ks] + 0.06, (spot, sigma, print_ratio, deltas[ks])
            assert print_ratio < 0.25 + 0.12, (spot, sigma, print_ratio)


#: D5a §2.3's table, verbatim: (U, sigma) -> adverse credit/width at width_usd 2.00,
#: ``short_delta_target`` 0.20, 35 DTE, r 0.04.  The signs are the finding: the
#: index ETFs at $590-$660 go NEGATIVE above ~0.25 vol, which is what makes the
#: floor a cost filter rather than the volatility filter D5 §1 argued for.
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


@pytest.mark.parametrize(("cell", "expected"), sorted(D5A_BOUND_TABLE.items()))
def test_the_credit_to_width_bound_table_is_reproduced(
    cell: tuple[float, float], expected: float
) -> None:
    """**The amendment's load-bearing table, recomputed from the shipped code.**

    If this test fails, either the cost model moved (R4 forbids it) or someone
    changed the derivation D5a §2.4's floor band was read off.  Either way the
    amendment's numbers no longer follow from the code and must be re-derived in
    the open, before the first sealed look — never after one.
    """
    spot, sigma = cell
    assert _adverse_ratio(spot, sigma, 2.00) == pytest.approx(expected, abs=5e-4)


def test_every_superseded_floor_is_outside_the_attainable_region() -> None:
    """D5's 0.25 / 0.30 and its OAT 0.20 all sit above the attainable maximum, so
    v0.1.0 entered nothing anywhere — the defect, as arithmetic."""
    attainable = max(D5A_BOUND_TABLE.values())
    assert attainable == pytest.approx(ATTAINABLE_ADVERSE_RATIO_MAX, abs=5e-4)
    for superseded in (0.20, 0.25, 0.30):
        assert superseded > attainable


def test_the_amended_band_sits_inside_the_attainable_region() -> None:
    """And the amended values are the p25 / median / p75 of the positive attainable
    ratios, rounded DOWN — so each is reachable by construction."""
    attainable = max(D5A_BOUND_TABLE.values())
    band = CREDIT_TO_WIDTH_QUANTILES
    assert band == {"p25": 0.05, "median": 0.10, "p75": 0.13}
    assert band["p25"] < band["median"] < band["p75"] < attainable
    assert ShortVerticalParams().min_credit_to_width == band["median"]


@pytest.mark.parametrize("sigma", [0.15, 0.20, 0.25])
@pytest.mark.parametrize("floor", [0.05, 0.10, 0.13])
def test_the_amended_floor_trades_where_the_superseded_floor_traded_nothing(
    sigma: float, floor: float
) -> None:
    """**The rewrite of v0.1.0's "trades nothing" finding.**

    On the same arbitrage-free chain, at the same delta band and the same frozen
    cost model: every amended value enters, and every superseded value still
    enters nothing.  The finding is preserved *and* the repair is demonstrated in
    one assertion pair.
    """
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
    amended band brackets the attainable ratio rather than sitting under it."""
    chain, under = build_chain(sigma=0.20)
    cleared = [
        floor
        for floor in (0.05, 0.10, 0.13, 0.155, 0.20, 0.25, 0.30)
        if OptionsShortVertical(
            ShortVerticalParams(min_credit_to_width=floor), q_lookup=_q, q_source="test"
        )(chain.head(SIGNAL_IDX), under.head(SIGNAL_IDX), SIGNAL_IDX)
        is not None
    ]
    assert cleared == [0.05, 0.10, 0.13]
    assert max(cleared) == CREDIT_TO_WIDTH_QUANTILES["p75"]


def test_the_stop_is_a_real_stop_at_every_grid_and_oat_value() -> None:
    """D5 §3.4: the stop binds only while ``stop_multiple x c/W < 1``.  At D5's
    floors the high value was near-degenerate (``3.0 x 0.30 = 0.90``); at the
    amended band the worst case anywhere is ``3.0 x 0.155 = 0.465``.

    This is what re-opens ``stop_multiple`` as a grid axis (D5a §6.2) — it is no
    longer the near-inert parameter D5 §4.2 pushed into the OAT table.
    """
    for multiple in (1.5, 2.0, 3.0):
        assert multiple * ATTAINABLE_ADVERSE_RATIO_MAX < 1.0
    # what the argument looked like at D5's floor: 90% of the width, i.e. a stop
    # that sits so close to max loss it can barely fire first
    assert pytest.approx(0.90) == 3.0 * 0.30
    assert 3.0 * ATTAINABLE_ADVERSE_RATIO_MAX < 0.5


# --------------------------------------------------------------------------- #
# D5a §3 — ONE R SCALE PER VERSION, and the $250 cap
# --------------------------------------------------------------------------- #
def test_gate_0_5_passes_on_a_genuinely_multi_underlying_trade_list() -> None:
    """**The defect this amendment exists for.**

    ``width_pct x U`` gave R a different scale on every underlying, so gate 0.5's
    ``single_scale`` refused any multi-underlying run.  With a declared dollar
    width the recovered width is $200.00 at every price level and the gate passes
    by construction, not by luck of which symbols were evaluated.
    """
    strat = strategy()
    trades = []
    for spot in (120.0, 240.0, 360.0):
        chain, under = build_chain(sigma=0.15, spot=spot)
        outcome = run_options_backtest(
            chain, under, strat, cost_model=PREREGISTERED_COST_MODEL, r_basis=RBasis.INCL, warmup=0
        )
        assert outcome.trades, f"no entry at spot {spot}"
        trades.extend(outcome.trades)

    gate = gate_0_5_structure(strat.structure_identity(), trades)
    assert gate.passed, gate.detail
    assert gate.evidence["widths_observed"] == [200.0]
    assert gate.evidence["r_scale_usd"] == 200.0
    assert gate.evidence["width_selected_adaptively"] is False


def test_the_structure_identity_is_a_constant_of_the_version() -> None:
    """It takes no argument any more: D4 §3 clause (d) requires ``width`` and ``M``
    to be declared constants, and an argument is exactly what let them vary."""
    ident = strategy().structure_identity()
    assert ident.width_declared == 2.00
    assert ident.m_declared == 100
    assert ident.r_scale_usd == 200.00
    assert ident.structure_type is StructureType.VERTICAL_CREDIT


def test_the_hard_max_loss_clears_the_two_hundred_and_fifty_dollar_cap() -> None:
    """D5a §3.3.  ``R_hard = width_usd x M + entry_costs`` is the bound no credit
    can breach, because the strategy refuses ``net_credit <= 0`` outright — so the
    margin holds at EVERY floor, not only at the baseline one."""
    p = ShortVerticalParams()
    assert p.r_scale_usd == 200.0
    assert p.r_hard_max_usd == pytest.approx(201.60)
    assert p.r_hard_max_usd < OPTIONS_PER_STRUCTURE_MAX_LOSS
    margin = (OPTIONS_PER_STRUCTURE_MAX_LOSS - p.r_hard_max_usd) / OPTIONS_PER_STRUCTURE_MAX_LOSS
    assert margin == pytest.approx(0.194, abs=5e-4)


def test_no_realised_trade_ever_exceeds_the_per_structure_cap() -> None:
    """Gate 0.i's ``structures_breaching_per_structure_cap`` is 0 by construction,
    and that is asserted rather than hoped for."""
    strat = strategy()
    for spot in (120.0, 240.0, 360.0):
        chain, under = build_chain(sigma=0.15, spot=spot)
        outcome = run_options_backtest(
            chain, under, strat, cost_model=PREREGISTERED_COST_MODEL, r_basis=RBasis.INCL, warmup=0
        )
        for trade in outcome.trades:
            assert trade.r_incl <= OPTIONS_PER_STRUCTURE_MAX_LOSS
            assert trade.r_incl <= ShortVerticalParams().r_hard_max_usd


@pytest.mark.parametrize(
    ("width_usd", "hard_max", "fits"),
    [(1.00, 101.60, True), (2.00, 201.60, True), (2.50, 251.60, False), (3.00, 301.60, False)],
)
def test_the_width_cap_arithmetic_is_what_selected_two_dollars(
    width_usd: float, hard_max: float, fits: bool
) -> None:
    """D5a §3.3's table, as a test.  $3.00 would need a floor of 0.172 to clear the
    cap at all and 0.155 is the attainable maximum, so no floor rescues it.  $2.50
    fits the cap at the baseline floor but is not a multiple of the declared $1.00
    strike increment, so it is rejected on **placeability** rather than on risk.
    """
    entry_costs = PREREGISTERED_COST_MODEL.commission(2) + PREREGISTERED_COST_MODEL.fees(2)
    assert width_usd * 100 + entry_costs == pytest.approx(hard_max)
    assert (hard_max <= OPTIONS_PER_STRUCTURE_MAX_LOSS) is fits
    if fits:
        assert OptionsShortVertical(ShortVerticalParams(width_usd=width_usd)) is not None
    else:
        with pytest.raises(ValueError, match="breaches the pre-registered per-structure cap"):
            OptionsShortVertical(ShortVerticalParams(width_usd=width_usd))
    # $2.50 clears the cap at the baseline floor but is unplaceable on a $1 ladder
    if width_usd == 2.50:
        assert not math.isclose(width_usd % 1.00, 0.0, abs_tol=1e-9)
        assert 250 * (1 - 0.10) + entry_costs < OPTIONS_PER_STRUCTURE_MAX_LOSS


def test_the_cost_coverage_finding_f14_holds_at_the_cap_compliant_width() -> None:
    """**F14, pre-registered in D5a §4 before the first look.**

    The target-win outcome is ``0.5C - F``.  ``F`` is set by the leg PRINTS and is
    nearly independent of the width; ``C`` is proportional to it.  At the width the
    $250 cap permits, the winning outcome is a LOSS on every Stage A cell — so the
    expected disposition is D5 §10's null option, and only the operator raising the
    cap (OP-1) can change it.  Never a post-result adjustment: D4 §2.8a forbids it.
    """
    cm = PREREGISTERED_COST_MODEL
    for spot, sigma in ((660.0, 0.15), (660.0, 0.20), (590.0, 0.15), (240.0, 0.15), (240.0, 0.20)):
        q = STAGE_A_Q[spot]
        ratio = _adverse_ratio(spot, sigma, 2.00)
        credit = ratio * 200.0
        deltas = {
            k: abs(bs.greeks(spot, float(k), YEARS, R, sigma, call=False, q=q).delta)
            for k in range(int(spot * 0.60), int(spot) + 1)
        }
        ks = min(deltas, key=lambda k: abs(deltas[k] - 0.20))
        ps = bs.price(spot, float(ks), YEARS, R, sigma, call=False, q=q)
        pl = bs.price(spot, float(ks - 2), YEARS, R, sigma, call=False, q=q)
        friction = (
            2
            * 100
            * (cm.spread(ps, moneyness=ks / spot, dte=35) + cm.spread(pl, moneyness=1.0, dte=35))
            + cm.commission(4)
            + cm.fees(4)
        )
        assert 0.5 * credit - friction < 0.0, (spot, sigma, credit, friction)


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
