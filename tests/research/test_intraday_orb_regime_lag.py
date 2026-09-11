"""intraday_orb v0.2.0 — the lagged regime read, and the leakage it removes.

v0.1.0 gated an entry inside session *D* on the regime derived from *D*'s own
daily close (future information at 10:15). These tests pin the fix down three
ways: the regime object handed to the strategy is always stamped BEFORE the
session being traded; the decision flips when (and only when) the lag is
removed; and no daily strategy's behaviour moves.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from signalforge.backtest.engine import EntrySignal
from signalforge.data.series import PriceSeries
from signalforge.domain import Direction, Horizon
from signalforge.research.promotion import _sensitivity_plan
from signalforge.research.regime import NEUTRAL, RegimeState, Trend, Vol
from signalforge.research.strategies import IntradayORB
from signalforge.research.strategies.base import (
    StrategyContext,
    declared_regime_lag_sessions,
    lagged_regime,
    signal_fn_for,
)
from signalforge.research.strategies.intraday_orb import VERSION, ORBParams

# 2024-06-24 (Mon) and 2024-06-25 (Tue) are NYSE sessions; 13:30 UTC == 09:30 ET.
D_PREV = date(2024, 6, 24)
D = date(2024, 6, 25)

# Each label is stamped with the session it was DERIVED from, so a test can
# assert on the stamp and not merely on the dictionary key it was filed under.
RISK_ON = RegimeState(Trend.BULL, Vol.LOW, D_PREV)
RISK_OFF = RegimeState(Trend.BEAR, Vol.HIGH, D)


def _two_session_intraday(closes: list[float]) -> PriceSeries:
    """One flat prior session, then ``closes`` as session D's 15m bars."""
    rows = []
    t = datetime(2024, 6, 24, 13, 30, tzinfo=UTC)
    for _ in range(5):  # session D-1: flat, never triggers
        rows.append((t, 100.0, 100.0, 100.0, 100.0, 30_000.0))
        t += timedelta(minutes=15)
    t = datetime(2024, 6, 25, 13, 30, tzinfo=UTC)
    for c in closes:
        rows.append((t, c, c * 1.002, c * 0.998, c, 30_000.0))
        t += timedelta(minutes=15)
    return PriceSeries.from_bars("X", rows)


# bars 0-2 set the opening range, bar 4 closes well above it
BREAKOUT = [100.0, 101.0, 100.5, 100.7, 103.5]
BREAKOUT_BAR = 5 + 4  # 5 prior-session bars, then index 4 of session D


# --------------------------------------------------------------------------- #
# the version bump and the declared axis
# --------------------------------------------------------------------------- #
def test_version_is_bumped_and_the_lag_is_a_declared_gate5_axis() -> None:
    assert VERSION == "0.2.0"  # behavioural change => new StrategyVersion (R3/R7)
    assert ORBParams().regime_lag_sessions == 1
    assert IntradayORB().regime_lag_sessions == 1
    assert declared_regime_lag_sessions(IntradayORB()) == 1
    axes = IntradayORB().sensitivity_axes()
    assert dict(axes) == {"regime_lag_sessions": [1, 2]}


def test_lag_zero_is_rejected_because_it_is_the_v010_lookahead() -> None:
    """0 is the identity with v0.1.0. It must not be reachable — not by a
    caller, and not by a gate-5 grid point."""
    with pytest.raises(ValueError, match="regime_lag_sessions must be >= 1"):
        ORBParams(regime_lag_sessions=0)
    assert 0 not in IntradayORB().sensitivity_axes()["regime_lag_sessions"]


def test_sensitivity_plan_merges_the_declared_axis_into_the_family_grid() -> None:
    plan = _sensitivity_plan(IntradayORB())
    assert plan is not None, "gate 5 would hard-fail with no grid (B5)"
    factory, grid = plan
    assert grid == {
        "or_bars": [2, 3, 4],
        "target_range_mult": [1.25, 1.5, 1.75],
        "regime_lag_sessions": [1, 2],
    }
    # the factory really builds the perturbed strategy (a grid that silently
    # ignored its own axes would pass gate 5 having tested nothing)
    built = factory({"or_bars": 4, "regime_lag_sessions": 2})
    assert built.params.or_bars == 4 and built.regime_lag_sessions == 2


# --------------------------------------------------------------------------- #
# the leakage itself
# --------------------------------------------------------------------------- #
class _Recorder:
    """A strategy that records the regime it was handed for every bar."""

    key = "recorder.intraday"
    horizon = Horizon.INTRADAY

    def __init__(self, lag: int) -> None:
        self.regime_lag_sessions = lag
        self.seen: list[tuple[datetime, RegimeState]] = []

    def spec(self):  # pragma: no cover - never used by these tests
        raise NotImplementedError

    def evaluate(self, series: PriceSeries, t: int, ctx: StrategyContext) -> EntrySignal | None:
        self.seen.append((series.dates[t], ctx.regime))
        return None


def test_every_intraday_bar_reads_a_regime_stamped_before_its_own_session() -> None:
    """The leakage test. For a lagged strategy, no bar in session D may ever be
    handed a regime whose ``as_of`` is D itself (or later)."""
    series = _two_session_intraday(BREAKOUT)
    regimes = {D_PREV: RISK_ON, D: RISK_OFF}

    rec = _Recorder(lag=1)
    fn = signal_fn_for(rec, regime_by_date=regimes)
    for t in range(len(series)):
        fn(series, t)

    assert rec.seen
    for stamp, regime in rec.seen:
        if stamp.date() == D:
            assert regime.as_of < D, f"bar {stamp} read a regime stamped {regime.as_of}"
            assert regime is RISK_ON  # D-1's label, not D's

    # and the v0.1.0 shape (lag 0) is exactly what that forbids
    leaky = _Recorder(lag=0)
    fn0 = signal_fn_for(leaky, regime_by_date=regimes)
    for t in range(len(series)):
        fn0(series, t)
    assert any(
        stamp.date() == D and regime.as_of == D for stamp, regime in leaky.seen
    ), "lag 0 must reproduce the same-session read this version removes"


def test_the_lag_changes_the_decision_and_lag_zero_restores_v010() -> None:
    """Session D-1 is risk-on, session D is risk-off. v0.2.0 trades (it reads
    D-1); the v0.1.0 shape does not (it reads D). The two differ ONLY in the
    lag, so this isolates the behavioural change the version bump pays for."""
    series = _two_session_intraday(BREAKOUT)
    regimes = {D_PREV: RISK_ON, D: RISK_OFF}

    v020 = signal_fn_for(IntradayORB(), regime_by_date=regimes)
    sig = v020(series, BREAKOUT_BAR)
    assert sig is not None and sig.direction is Direction.LONG

    # the same rules with the lag removed = v0.1.0 = gated off by D's own close
    class _Unlagged(IntradayORB):
        regime_lag_sessions = 0  # type: ignore[assignment]

    assert signal_fn_for(_Unlagged(), regime_by_date=regimes)(series, BREAKOUT_BAR) is None


def test_the_lag_is_not_a_free_pass_when_the_prior_session_was_risk_off() -> None:
    """Mirror image: D-1 risk-off, D risk-on. v0.2.0 must stay silent — the lag
    must not be able to launder a risk-off prior session into a trade."""
    series = _two_session_intraday(BREAKOUT)
    regimes = {
        D_PREV: RegimeState(Trend.BEAR, Vol.HIGH, D_PREV),
        D: RegimeState(Trend.BULL, Vol.LOW, D),
    }
    assert signal_fn_for(IntradayORB(), regime_by_date=regimes)(series, BREAKOUT_BAR) is None


def test_a_two_session_lag_reaches_two_sessions_back() -> None:
    series = _two_session_intraday(BREAKOUT)
    older = RegimeState(Trend.BULL, Vol.LOW, date(2024, 6, 21))
    regimes = {
        date(2024, 6, 21): older,
        D_PREV: RegimeState(Trend.BEAR, Vol.HIGH, D_PREV),
        D: RegimeState(Trend.BULL, Vol.LOW, D),
    }
    lag2 = IntradayORB(ORBParams(regime_lag_sessions=2))
    sig = signal_fn_for(lag2, regime_by_date=regimes)(series, BREAKOUT_BAR)
    assert sig is not None  # 2024-06-21's risk-on label, not D-1's risk-off one


def test_missing_history_degenerates_to_neutral_never_to_the_current_session() -> None:
    series = _two_session_intraday(BREAKOUT)
    # only D itself is labelled: there is nothing lagged to read
    rec = _Recorder(lag=1)
    fn = signal_fn_for(rec, regime_by_date={D: RISK_OFF})
    for t in range(len(series)):
        fn(series, t)
    for stamp, regime in rec.seen:
        if stamp.date() == D:
            assert regime is NEUTRAL


# --------------------------------------------------------------------------- #
# lagged_regime, and the untouched daily path
# --------------------------------------------------------------------------- #
def test_lagged_regime_semantics() -> None:
    regimes = {D_PREV: RISK_ON, D: RISK_OFF}
    assert lagged_regime(regimes, D, 0) is RISK_OFF  # same-session read
    assert lagged_regime(regimes, D, 1) is RISK_ON  # the completed close before D
    assert lagged_regime(regimes, D, 2) is NEUTRAL  # no history that far back
    assert lagged_regime({}, D, 1) is NEUTRAL
    # as_of need not itself be labelled (an uningested daily bar for D)
    assert lagged_regime({D_PREV: RISK_ON}, D, 1) is RISK_ON


def test_daily_strategies_are_unchanged_by_the_lag_mechanism() -> None:
    """Every strategy that declares no lag keeps the exact same-session read —
    the mechanism is opt-in per strategy version, not a global switch."""
    from signalforge.research.strategies import default_strategies

    for strat in default_strategies():
        expected = 1 if strat.key.startswith("intraday_orb") else 0
        assert declared_regime_lag_sessions(strat) == expected

    rec = _Recorder(lag=0)
    d0, d1 = date(2024, 1, 2), date(2024, 1, 3)
    daily = PriceSeries.from_bars(
        "X", [(d0, 10.0, 10.0, 10.0, 10.0, 1.0), (d1, 10.0, 10.0, 10.0, 10.0, 1.0)]
    )
    r0 = RegimeState(Trend.BULL, Vol.LOW, d0)
    r1 = RegimeState(Trend.BEAR, Vol.HIGH, d1)
    fn = signal_fn_for(rec, regime_by_date={d0: r0, d1: r1})
    fn(daily, 0)
    fn(daily, 1)
    assert [r for _, r in rec.seen] == [r0, r1]
