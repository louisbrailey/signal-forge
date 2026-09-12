"""O3 — the D5 v0.1.0 short vertical, on SYNTHETIC chains only (I-O5).

No real option price, IV, greek, credit, return or P&L is read anywhere here.
Every chain is priced from Black-Scholes at a chosen sigma, so the strategy's
inverted IV comes back as that sigma exactly and the delta it selects on is
arithmetic the reader can check.

The last section records a **finding**, not a preference: on an arbitrage-free
chain the pre-registered ``min_credit_to_width`` floor is unreachable at the
pre-registered delta band.  It is asserted here so it cannot be lost.
"""

from __future__ import annotations

from datetime import date
from itertools import pairwise

import pytest

from signalforge.backtest.options_engine import (
    RBasis,
    StructureType,
    run_options_backtest,
)
from signalforge.data import calendar, options_calendar
from signalforge.data.option_chain import ContractPrint, ContractRef, OptionChainSeries, Right
from signalforge.data.series import PriceSeries
from signalforge.options import blackscholes as bs
from signalforge.research.options_strategies import (
    PREREGISTERED_COST_MODEL,
    OptionsShortVertical,
    ShortVerticalParams,
)
from signalforge.research.regime import RegimeState, Trend, Vol

EXPIRY = date(2024, 3, 15)  # third Friday, an XNYS session
SPOT = 500.0
Q = 0.013
R = 0.04
SESSIONS = calendar.sessions(date(2024, 1, 2), date(2024, 3, 20))
SIGNAL_IDX = SESSIONS.index(date(2024, 2, 9))  # calendar DTE 35; the prior session is 36


def _ticker(right: Right, strike: float) -> str:
    return f"O:SPY240315{'P' if right is Right.PUT else 'C'}{int(strike * 1000):08d}"


def build_chain(
    *,
    sigma: float = 0.35,
    volume: float = 1000.0,
    transactions: int | None = 50,
    shares_per_contract: int = 100,
    strikes: range = range(380, 505, 5),
    spot: float = SPOT,
) -> tuple[OptionChainSeries, PriceSeries]:
    """An arbitrage-free chain: every print IS the Black-Scholes value at ``sigma``."""
    refs: list[ContractRef] = []
    prints: dict[date, dict[str, ContractPrint]] = {}
    ladders = (
        (Right.PUT, strikes),
        (Right.CALL, range(strikes.start + 120, strikes.stop + 120, 5)),
    )
    for right, ks in ladders:
        for k in ks:
            tk = _ticker(right, float(k))
            refs.append(
                ContractRef(
                    tk, "SPY", right, float(k), EXPIRY, shares_per_contract, "american", SESSIONS[0]
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
        "SPY",
        contracts=refs,
        underlying_closes=dict.fromkeys(SESSIONS, spot),
        prints=prints,
    )
    under = PriceSeries.from_bars("SPY", [(d, spot, spot, spot, spot, 1e6) for d in SESSIONS])
    return chain, under


def _q(_sym: str, _d: date) -> float:
    return Q


def strategy(**param_overrides) -> OptionsShortVertical:
    """A strategy whose credit floor is LOOSENED for mechanism tests only.

    0.08 is not a pre-registered value and is never used to evaluate anything —
    it exists so the selection, wing-placement and exit plumbing can be exercised
    at all, given the finding recorded at the bottom of this file.  The call side
    needs the lower value: on a flat-vol chain a 0.20-delta CALL is dearer than
    the equivalent put (``r > q``), so its credit-to-width ratio is lower still.
    """
    params = ShortVerticalParams(min_credit_to_width=0.08, **param_overrides)
    return OptionsShortVertical(params, q_lookup=_q, q_source="test:vendor_dividends")


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
    chain, under = build_chain(sigma=0.35)
    short, _ = _selected(strategy(), chain, under)
    years = (EXPIRY - SESSIONS[SIGNAL_IDX]).days / 365.0
    deltas = {
        k: abs(bs.greeks(SPOT, float(k), years, R, 0.35, call=False, q=Q).delta)
        for k in range(380, 505, 5)
    }
    best = min(
        (k for k, d in deltas.items() if d <= 0.35 and abs(d - 0.20) <= 0.05),
        key=lambda k: (abs(deltas[k] - 0.20), k),
    )
    assert short == float(best)
    assert deltas[best] == pytest.approx(0.198, abs=0.01)


def test_a_strike_beyond_max_short_delta_is_never_selectable() -> None:
    """``max_short_delta`` caps how far axis 1 may be pushed to satisfy the
    credit floor — map §3.2's Rule, honoured literally."""
    chain, under = build_chain(sigma=0.35)
    short_loose, _ = _selected(
        strategy(short_delta_target=0.30, max_short_delta=0.35), chain, under
    )
    short_capped, _ = _selected(
        strategy(short_delta_target=0.30, max_short_delta=0.28), chain, under
    )
    years = (EXPIRY - SESSIONS[SIGNAL_IDX]).days / 365.0
    capped_delta = abs(bs.greeks(SPOT, short_capped, years, R, 0.35, call=False, q=Q).delta)
    assert capped_delta <= 0.28
    assert short_capped != short_loose  # the axis genuinely binds, it is not inert


def test_no_strike_within_the_delta_tolerance_is_a_non_entry() -> None:
    chain, under = build_chain(sigma=0.35)
    assert (
        strategy(short_delta_target=0.02, delta_tolerance=0.001)(
            chain.head(SIGNAL_IDX), under.head(SIGNAL_IDX), SIGNAL_IDX
        )
        is None
    )


def test_the_wing_is_the_listed_strike_closest_to_width_pct_of_the_underlying() -> None:
    chain, under = build_chain(sigma=0.35)
    short, long_ = _selected(strategy(width_pct=0.020), chain, under)
    assert short - long_ == pytest.approx(0.020 * SPOT)
    short2, long2 = _selected(strategy(width_pct=0.030), chain, under)
    assert short2 - long2 == pytest.approx(0.030 * SPOT)


def test_a_realised_width_outside_the_tolerance_is_a_non_entry() -> None:
    """This is what stops a coarse strike ladder on a low-priced underlying from
    silently rewriting the width parameter."""
    coarse, under = build_chain(sigma=0.35, strikes=range(300, 501, 100))
    assert (
        strategy(width_pct=0.010)(coarse.head(SIGNAL_IDX), under.head(SIGNAL_IDX), SIGNAL_IDX)
        is None
    )


def test_the_long_wing_always_sits_strictly_further_otm_than_the_short() -> None:
    """A naked short is not representable: ``OptionStructure`` refuses it."""
    chain, under = build_chain(sigma=0.35)
    short, long_ = _selected(strategy(), chain, under)
    assert long_ < short
    sig = strategy()(chain.head(SIGNAL_IDX), under.head(SIGNAL_IDX), SIGNAL_IDX)
    assert sig.structure.structure_type is StructureType.VERTICAL_CREDIT
    assert sig.structure.contracts == 1


# --------------------------------------------------------------------------- #
# the fail-closed inputs
# --------------------------------------------------------------------------- #
def test_no_sourced_q_produces_no_entry_at_all() -> None:
    """``q = 0.0`` by default is a gate-0.g failure, so it is never substituted."""
    chain, under = build_chain()
    bare = OptionsShortVertical(ShortVerticalParams(min_credit_to_width=0.08))
    assert bare.q_lookup is None
    assert bare(chain.head(SIGNAL_IDX), under.head(SIGNAL_IDX), SIGNAL_IDX) is None

    missing = OptionsShortVertical(
        ShortVerticalParams(min_credit_to_width=0.08), q_lookup=lambda _s, _d: None
    )
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
    chain, under = build_chain(sigma=0.35)
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
    chain, under = build_chain(sigma=0.35)
    outcome = run_options_backtest(
        chain, under, strategy(), cost_model=PREREGISTERED_COST_MODEL, warmup=0
    )
    spans = [(t.entry_date, t.exit_date) for t in outcome.trades]
    assert all(a[1] < b[0] for a, b in pairwise(spans))


# --------------------------------------------------------------------------- #
# THE FINDING: the pre-registered credit floor is structurally unreachable
# --------------------------------------------------------------------------- #
def test_the_credit_to_width_ratio_is_bounded_by_roughly_the_short_delta() -> None:
    """Arithmetic, not opinion.

    ``credit = P(K_short) - P(K_long)``, and by the mean value theorem that is
    ``dP/dK x width`` somewhere inside the strike range, where
    ``dP/dK = e^{-rT} N(-d2)`` — the risk-neutral probability of finishing ITM,
    which is slightly above ``|delta|`` at the short strike and **falls** toward
    the wing.  So ``credit/width`` is bounded above by roughly the short delta
    and sits below it for any width worth trading.
    """
    years = (EXPIRY - SESSIONS[SIGNAL_IDX]).days / 365.0
    for sigma in (0.15, 0.20, 0.30, 0.40, 0.60):
        deltas = {
            k: abs(bs.greeks(SPOT, float(k), years, R, sigma, call=False, q=Q).delta)
            for k in range(380, 501, 5)
        }
        ks = min(deltas, key=lambda k: abs(deltas[k] - 0.20))
        kl = ks - 5
        ps = bs.price(SPOT, float(ks), years, R, sigma, call=False, q=Q)
        pl = bs.price(SPOT, float(kl), years, R, sigma, call=False, q=Q)
        print_ratio = (ps - pl) / (ks - kl)
        assert print_ratio <= deltas[ks] + 0.05, (sigma, print_ratio, deltas[ks])
        assert print_ratio < 0.25, (sigma, print_ratio)


@pytest.mark.parametrize("sigma", [0.15, 0.20, 0.35, 0.60])
@pytest.mark.parametrize("width_pct", [0.010, 0.020, 0.030])
def test_the_pre_registered_credit_floor_produces_no_entry_on_a_clean_chain(
    sigma: float, width_pct: float
) -> None:
    """**FINDING, recorded so it cannot be lost.**

    At D5 §4.1's baseline — ``short_delta_target = 0.20``, ``min_credit_to_width
    = 0.25`` — and at BOTH of axis 6's grid values (0.25 and 0.30), the strategy
    enters nothing on an arbitrage-free chain at any IV from 15% to 60%.  The
    ratio is bounded above by roughly the short delta (test above) and D5 §2.4's
    own 3%-of-print modelled spread, charged as a FULL spread per leg per side,
    takes a further 20-40% out of it.

    D5 §6.2a's representative structure (short print $1.95, wing $0.62, 5-wide at
    U = $500, adverse credit 0.2503 of width) does not correspond to any
    ``(sigma, strike)`` pair a 35-DTE 0.20-delta chain on a $500 underlying
    admits.  This is a **pre-registration arithmetic defect**, not a coding
    choice, and resolving it is an orchestrator decision: lower the floor, raise
    the delta band, or accept that v0.1.0 as written trades nothing.
    """
    chain, under = build_chain(sigma=sigma)
    for floor in (0.25, 0.30):
        strat = OptionsShortVertical(
            ShortVerticalParams(min_credit_to_width=floor, width_pct=width_pct),
            q_lookup=_q,
            q_source="test",
        )
        assert strat(chain.head(SIGNAL_IDX), under.head(SIGNAL_IDX), SIGNAL_IDX) is None


def test_the_floor_clears_only_well_below_the_pre_registered_values() -> None:
    """The same chain, with the floor walked down — so the gap is a number."""
    chain, under = build_chain(sigma=0.35)
    cleared = [
        floor
        for floor in (0.30, 0.25, 0.20, 0.15, 0.12, 0.10)
        if OptionsShortVertical(
            ShortVerticalParams(min_credit_to_width=floor, width_pct=0.020),
            q_lookup=_q,
            q_source="test",
        )(chain.head(SIGNAL_IDX), under.head(SIGNAL_IDX), SIGNAL_IDX)
        is not None
    ]
    assert 0.25 not in cleared and 0.30 not in cleared
    assert max(cleared) <= 0.15
