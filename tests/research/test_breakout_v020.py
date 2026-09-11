"""`volatility_breakout` v0.2.0 — squeeze lag and break-bar release.

The §12.3 test battery of
``docs/research/designs/volatility_breakout_short_swing.md``. Nothing here
touches a database, a provider or the sealed window: these are pure
fixture-series unit tests plus two plan-time/plumbing checks.
"""

from __future__ import annotations

import math
from datetime import date, timedelta

import numpy as np
import pytest

from signalforge.backtest.engine import EntrySignal
from signalforge.data.series import PriceSeries
from signalforge.domain import Direction, Horizon
from signalforge.research.features.daily import (
    atr,
    atr_contraction,
    donchian_high,
    donchian_low,
)
from signalforge.research.regime import RegimeState, Trend, Vol
from signalforge.research.strategies.base import StrategyContext
from signalforge.research.strategies.breakout import (
    VERSION,
    BreakoutParams,
    VolatilityBreakout,
)

BULL = RegimeState(Trend.BULL, Vol.LOW, date(2024, 1, 1), market_ret_20d=0.01, market_ret_63d=0.02)
BEAR = RegimeState(Trend.BEAR, Vol.HIGH, date(2024, 1, 1), market_ret_63d=-0.05)

# The degenerate cell: set-identical to v0.1.0 by construction (design §2.3).
DEGENERATE = BreakoutParams(squeeze_lag=0, release_min=0.0)


# --------------------------------------------------------------------------- #
# fixtures
# --------------------------------------------------------------------------- #
def _series(rows: list[tuple[float, float, float, float]], symbol: str = "FIX") -> PriceSeries:
    """``(open, high, low, close)`` bars on consecutive calendar days."""
    d = date(2022, 1, 3)
    out = []
    for o, h, lo, c in rows:
        out.append((d, o, h, lo, c, 2_000_000.0))
        d += timedelta(days=1)
    return PriceSeries.from_bars(symbol, out)


def _rich_fixture(n: int = 900, seed: int = 11) -> PriceSeries:
    """A long, deterministic series with cycling volatility phases and
    alternating drift, so both the long and the short branch fire repeatedly
    and every grid axis has something to bite on.

    Seeded ``numpy`` Generator: byte-for-byte reproducible (S4)."""
    rng = np.random.default_rng(seed)
    rows: list[tuple[date, float, float, float, float, float]] = []
    d = date(2016, 1, 4)
    c = 100.0
    for i in range(n):
        vol = (0.25, 0.5, 1.6, 0.8)[(i // 17) % 4]
        drift = 0.10 if (i // 43) % 2 == 0 else -0.10
        c = max(5.0, c + float(rng.normal(drift, vol)))
        o = c - float(rng.normal(0, vol * 0.3))
        h = max(o, c) + abs(float(rng.normal(0, vol))) + 0.02
        lo = min(o, c) - abs(float(rng.normal(0, vol))) - 0.02
        rows.append((d, o, h, lo, c, 2_000_000.0))
        d += timedelta(days=1)
    return PriceSeries.from_bars("FIX", rows)


def _signals(
    series: PriceSeries,
    params: BreakoutParams,
    *,
    regime: RegimeState = BULL,
    allow_short: bool = False,
) -> dict[int, tuple[Direction, float, float, int]]:
    """Every bar's signal, keyed by ``t``. Compares the *signal*, not just the
    bar index, so a change in stop/target/time-stop counts as movement."""
    strat = VolatilityBreakout(Horizon.SHORT_SWING, params)
    ctx = StrategyContext(regime=regime, allow_short=allow_short)
    out: dict[int, tuple[Direction, float, float, int]] = {}
    for t in range(len(series)):
        sig = strat.evaluate(series, t, ctx)
        if sig is not None:
            out[t] = (
                sig.direction,
                round(sig.stop_price, 9),
                round(sig.target_price or float("nan"), 9),
                sig.time_stop_bars or 0,
            )
    return out


# --------------------------------------------------------------------------- #
# the v0.1.0 reference implementation
# --------------------------------------------------------------------------- #
def _v010_evaluate(
    series: PriceSeries, t: int, ctx: StrategyContext, p: BreakoutParams
) -> EntrySignal | None:
    """`VolatilityBreakout.evaluate` exactly as it stood at v0.1.0.

    Kept here, not imported: ``VERSION`` is module-level, so after the bump
    the shipped class can no longer produce v0.1.0 behaviour from its own
    defaults. Copied verbatim from the pre-change source so the identity test
    below compares against the real predecessor rather than a paraphrase."""
    contraction = atr_contraction(series, t, 10, 50)
    dc_hi = donchian_high(series, t, p.channel)
    dc_lo = donchian_low(series, t, p.channel)
    a = atr(series, t, p.atr_window)
    if any(math.isnan(x) for x in (contraction, dc_hi, dc_lo, a)) or a <= 0:
        return None
    if contraction > p.contraction_max:
        return None
    close = float(series.close[t])
    time_stop = p.time_stop_short  # SHORT_SWING

    if close > dc_hi and not ctx.regime.risk_off:
        return EntrySignal(
            direction=Direction.LONG,
            stop_price=close - p.stop_atr * a,
            target_price=close + p.target_atr * a,
            time_stop_bars=time_stop,
            reason="",
        )
    if ctx.allow_short and close < dc_lo and ctx.regime.trend is Trend.BEAR:
        return EntrySignal(
            direction=Direction.SHORT,
            stop_price=close + p.stop_atr * a,
            target_price=close - p.target_atr * a,
            time_stop_bars=time_stop,
            reason="",
        )
    return None


def _v010_signals(
    series: PriceSeries,
    *,
    regime: RegimeState = BULL,
    allow_short: bool = False,
) -> dict[int, tuple[Direction, float, float, int]]:
    p = BreakoutParams()
    ctx = StrategyContext(regime=regime, allow_short=allow_short)
    out: dict[int, tuple[Direction, float, float, int]] = {}
    for t in range(len(series)):
        sig = _v010_evaluate(series, t, ctx, p)
        if sig is not None:
            out[t] = (
                sig.direction,
                round(sig.stop_price, 9),
                round(sig.target_price or float("nan"), 9),
                sig.time_stop_bars or 0,
            )
    return out


# --------------------------------------------------------------------------- #
# §12.3 item 1 — degenerate identity
# --------------------------------------------------------------------------- #
def test_version_is_a_new_string_not_a_mutation_of_v010() -> None:
    """R3/R7: the behaviour change ships as a new version, so strategy
    version id 6's rows and sealed tests are never reinterpreted."""
    assert VERSION == "0.2.0"


@pytest.mark.parametrize(
    ("regime", "allow_short"), [(BULL, False), (BEAR, True)], ids=["long-branch", "short-branch"]
)
def test_degenerate_cell_reproduces_v010_signal_set_exactly(
    regime: RegimeState, allow_short: bool
) -> None:
    """`squeeze_lag=0, release_min=0.0` is v0.1.0, for EVERY t — set equality,
    not just matching counts.

    This is what the ``release_min > 0.0`` gate of §2.3 buys. Placing the
    ``base`` NaN/``<= 0`` check unconditionally in the shared guard would
    require ``t >= 51`` where v0.1.0 requires only ``t >= 50``
    (``daily.py:47-48``), making the degenerate cell a strict SUBSET of
    v0.1.0 rather than an identity — and Stage A's E01 baseline is computed
    through exactly this cell, so a subset would silently bias the
    comparison."""
    series = _rich_fixture()
    v010 = _v010_signals(series, regime=regime, allow_short=allow_short)
    v020 = _signals(series, DEGENERATE, regime=regime, allow_short=allow_short)
    assert v010, "fixture produces no v0.1.0 signals — the identity test would be vacuous"
    assert set(v010) == set(v020)  # the signal SET, bar for bar
    assert v010 == v020  # and the signals themselves
    assert not set(v010).symmetric_difference(set(v020))


def test_degenerate_cell_differs_from_the_v020_defaults() -> None:
    """Guards the test above from passing because nothing changed at all."""
    series = _rich_fixture()
    assert _signals(series, DEGENERATE) != _signals(series, BreakoutParams())


# --------------------------------------------------------------------------- #
# §12.3 item 2 — the lag test
# --------------------------------------------------------------------------- #
def _lag_series() -> PriceSeries:
    """Contrived so ``contraction(t) > 0.75`` but ``contraction(t-5) <= 0.75``.

    Bars 0-59 wide (TR 4), 60-84 tight (TR 1), 85-89 wide again (TR 8) so the
    squeeze has already released by the break bar, then the break at t = 90.
    """
    rows: list[tuple[float, float, float, float]] = []
    for _ in range(60):  # 0..59  wide, TR = 4
        rows.append((100.0, 102.0, 98.0, 100.0))
    for _ in range(25):  # 60..84 tight, TR = 1
        rows.append((100.0, 100.5, 99.5, 100.0))
    for _ in range(5):  # 85..89 wide again, TR = 8
        rows.append((100.0, 104.0, 96.0, 100.0))
    rows.append((100.0, 108.0, 100.0, 106.0))  # 90: break, TR = 8, close > 20d high
    return _series(rows)


def test_squeeze_lag_shifts_which_bar_the_contraction_is_read_at() -> None:
    series = _lag_series()
    t = 90
    # the contrived precondition, stated as an assertion
    assert atr_contraction(series, t, 10, 50) > 0.75
    assert atr_contraction(series, t - 5, 10, 50) <= 0.75

    at_lag5 = VolatilityBreakout(Horizon.SHORT_SWING, BreakoutParams(squeeze_lag=5)).evaluate(
        series, t, StrategyContext(regime=BULL)
    )
    at_lag0 = VolatilityBreakout(Horizon.SHORT_SWING, BreakoutParams(squeeze_lag=0)).evaluate(
        series, t, StrategyContext(regime=BULL)
    )

    assert at_lag5 is not None and at_lag5.direction is Direction.LONG
    assert at_lag0 is None


# --------------------------------------------------------------------------- #
# §12.3 item 3 — the release test
# --------------------------------------------------------------------------- #
def _release_series() -> PriceSeries:
    """A break bar whose true range is exactly ``0.9 x ATR(50, t-1)``.

    Bars 0-59 wide (TR 4), 60-89 tight (TR 1) so ATR(50, 89) = 2.2 exactly;
    the break bar at t = 90 has TR = 1.98 = 0.9 x 2.2 and closes above the
    20-day Donchian high (100.5)."""
    rows: list[tuple[float, float, float, float]] = []
    for _ in range(60):  # 0..59  wide, TR = 4
        rows.append((100.0, 102.0, 98.0, 100.0))
    for _ in range(30):  # 60..89 tight, TR = 1
        rows.append((100.0, 100.5, 99.5, 100.0))
    rows.append((100.0, 101.98, 100.0, 101.5))  # 90: TR = 1.98, close 101.5 > 100.5
    return _series(rows)


def test_release_min_rejects_a_break_bar_whose_range_is_below_the_threshold() -> None:
    series = _release_series()
    t = 90
    base = atr(series, t - 1, 50)
    tr = float(series.high[t]) - float(series.low[t])
    assert base == pytest.approx(2.2)
    assert tr / base == pytest.approx(0.9)  # exactly the contrived ratio
    assert atr_contraction(series, t - 5, 10, 50) <= 0.75  # the squeeze itself is fine

    ctx = StrategyContext(regime=BULL)
    rejected = VolatilityBreakout(Horizon.SHORT_SWING, BreakoutParams(release_min=1.0)).evaluate(
        series, t, ctx
    )
    accepted = VolatilityBreakout(Horizon.SHORT_SWING, BreakoutParams(release_min=0.8)).evaluate(
        series, t, ctx
    )

    assert rejected is None
    assert accepted is not None and accepted.direction is Direction.LONG


def test_release_filter_is_switched_off_entirely_at_zero() -> None:
    """`release_min = 0.0` must skip the whole block, base NaN check included
    — that is the §2.3 gate, and the identity test depends on it."""
    series = _release_series()
    off = VolatilityBreakout(
        Horizon.SHORT_SWING, BreakoutParams(squeeze_lag=5, release_min=0.0)
    ).evaluate(series, 90, StrategyContext(regime=BULL))
    assert off is not None


# --------------------------------------------------------------------------- #
# §12.3 item 4 — warm-up, and no negative-index reads
# --------------------------------------------------------------------------- #
def _early_break_series() -> PriceSeries:
    """A break at t = 54: inside v0.1.0's warm-up-satisfied range (t >= 50)
    but before lag 5's first evaluable bar (t = 55)."""
    rows: list[tuple[float, float, float, float]] = []
    for _ in range(45):  # 0..44 wide, TR = 4
        rows.append((100.0, 102.0, 98.0, 100.0))
    for _ in range(9):  # 45..53 tight, TR = 1
        rows.append((100.0, 100.5, 99.5, 100.0))
    rows.append((100.0, 106.0, 100.0, 105.0))  # 54: break, TR = 6
    return _series(rows)


def test_no_signal_before_t_55_at_lag_5_even_when_lag_0_fires() -> None:
    series = _early_break_series()
    ctx = StrategyContext(regime=BULL)
    lag0 = VolatilityBreakout(Horizon.SHORT_SWING, BreakoutParams(squeeze_lag=0))
    lag5 = VolatilityBreakout(Horizon.SHORT_SWING, BreakoutParams(squeeze_lag=5))
    assert lag0.evaluate(series, 54, ctx) is not None  # the test is not vacuous
    assert all(lag5.evaluate(series, t, ctx) is None for t in range(len(series)))


def test_lagged_contraction_is_nan_not_a_wrapped_read_before_the_warm_up() -> None:
    """Negative indices must produce NaN, never a silent wrap to the end of
    the array. ``atr`` returns NAN on the ``t + 1 < window + 1`` guard before
    it ever indexes, so ``t - 5`` at ``t = 0`` reads nothing at all."""
    series = _rich_fixture(n=200)
    lag = 5
    for t in range(lag + 50):  # every t < 55
        assert math.isnan(atr_contraction(series, t - lag, 10, 50)), t
    assert not math.isnan(atr_contraction(series, 55 - lag, 10, 50))
    # and the strategy is silent over exactly that range
    strat = VolatilityBreakout(Horizon.SHORT_SWING, BreakoutParams(squeeze_lag=lag))
    ctx = StrategyContext(regime=BULL)
    assert all(strat.evaluate(series, t, ctx) is None for t in range(55))


def test_negative_index_reads_are_nan_for_every_grid_lag() -> None:
    series = _rich_fixture(n=200)
    for lag in (3, 5, 10):
        assert math.isnan(atr_contraction(series, 0 - lag, 10, 50))
        assert math.isnan(atr_contraction(series, (lag + 49) - lag, 10, 50))
        assert not math.isnan(atr_contraction(series, (lag + 50) - lag, 10, 50))
    assert math.isnan(atr(series, -1, 50))  # the release branch's own base read


# --------------------------------------------------------------------------- #
# §12.3 item 5 — leakage, the four functions gate 8 now checks
# --------------------------------------------------------------------------- #
V020_LEAKAGE_NAMES = (
    "atr_contraction(10,50)",
    "atr_contraction(10,50) @ t-5",
    "donchian_high(20)",
    "true_range",
)


def test_gate8_already_declares_the_four_v020_entry_features() -> None:
    """Confirmation, not an edit: the hardening already added all four to
    ``LEAKAGE_FEATURE_CHECKS``, so v0.2.0 adds nothing here."""
    from signalforge.research.promotion import LEAKAGE_FEATURE_CHECKS

    names = {name for name, _fn in LEAKAGE_FEATURE_CHECKS}
    assert set(V020_LEAKAGE_NAMES) <= names


@pytest.mark.parametrize("name", V020_LEAKAGE_NAMES)
def test_v020_entry_features_are_look_ahead_free(name: str) -> None:
    """`assert_no_lookahead` over each of the four on a long fixture series.

    A failure here is a finding about ``features/daily.py`` — which the two
    already-approved strategies also depend on — not about this version."""
    from signalforge.backtest.leakage import assert_no_lookahead
    from signalforge.research.promotion import LEAKAGE_FEATURE_CHECKS

    checks = dict(LEAKAGE_FEATURE_CHECKS)
    assert_no_lookahead(checks[name], _rich_fixture(n=300))


def test_the_whole_evaluate_rule_is_look_ahead_free() -> None:
    """The composed rule, not only its parts: truncating the series at ``t``
    must not change what the strategy decides at ``t``."""
    series = _rich_fixture(n=300)
    strat = VolatilityBreakout(Horizon.SHORT_SWING)
    ctx = StrategyContext(regime=BEAR, allow_short=True)
    full = {t: strat.evaluate(series, t, ctx) for t in range(len(series))}
    for t in range(55, len(series)):
        got = strat.evaluate(series.head(t), t, ctx)  # only bars 0..t visible
        assert (got is None) == (full[t] is None), t
        if got is not None and full[t] is not None:
            assert got.stop_price == pytest.approx(full[t].stop_price)  # type: ignore[union-attr]


# --------------------------------------------------------------------------- #
# §12.3 item 6 — grid plumbing
# --------------------------------------------------------------------------- #
def test_the_family_grid_is_four_axes_and_eighty_one_combinations() -> None:
    import itertools

    from signalforge.research.promotion import _sensitivity_plan

    plan = _sensitivity_plan(VolatilityBreakout())
    assert plan is not None
    _factory, grid = plan
    assert set(grid) == {"contraction_max", "stop_atr", "squeeze_lag", "release_min"}
    # the shipped axes are untouched, byte for byte (R4 floor)
    assert grid["contraction_max"] == [0.65, 0.75, 0.85]
    assert grid["stop_atr"] == [1.5, 1.75, 2.0]
    # the declared axes, defaults at the centre of each
    assert grid["squeeze_lag"] == [3, 5, 10]
    assert grid["release_min"] == [0.8, 1.0, 1.2]
    assert grid["squeeze_lag"][1] == BreakoutParams().squeeze_lag
    assert grid["release_min"][1] == BreakoutParams().release_min
    assert len(list(itertools.product(*grid.values()))) == 81


def test_the_grid_factory_accepts_both_new_keys() -> None:
    """`dataclasses.replace` must take them, or the grid dies mid-run."""
    from signalforge.research.promotion import _sensitivity_plan

    plan = _sensitivity_plan(VolatilityBreakout())
    assert plan is not None
    factory, grid = plan
    built = factory(
        {"contraction_max": 0.85, "stop_atr": 2.0, "squeeze_lag": 10, "release_min": 1.2}
    )
    assert isinstance(built, VolatilityBreakout)
    assert built.params.squeeze_lag == 10
    assert built.params.release_min == 1.2
    assert built.params.contraction_max == 0.85
    assert built.params.stop_atr == 2.0
    assert built.key == "volatility_breakout.short_swing"
    # every grid point must be constructible
    for cm in grid["contraction_max"]:
        for sa in grid["stop_atr"]:
            for sl in grid["squeeze_lag"]:
                for rm in grid["release_min"]:
                    factory(
                        {
                            "contraction_max": cm,
                            "stop_atr": sa,
                            "squeeze_lag": sl,
                            "release_min": rm,
                        }
                    )


def test_the_grid_stays_under_the_sensitivity_cap() -> None:
    from signalforge.research.sensitivity import MAX_GRID_POINTS

    assert MAX_GRID_POINTS >= 81


# --------------------------------------------------------------------------- #
# §12.3 item 7 — the no-op guard (K5 in unit form)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("axis", "value"),
    [
        ("contraction_max", 0.65),
        ("contraction_max", 0.85),
        ("stop_atr", 1.5),
        ("stop_atr", 2.0),
        ("squeeze_lag", 3),
        ("squeeze_lag", 10),
        ("release_min", 0.8),
        ("release_min", 1.2),
    ],
)
def test_every_grid_axis_moves_the_signal_set_or_the_exits(axis: str, value: float) -> None:
    """K5 in unit form. An axis that changes nothing has tested nothing, and
    would let gate 5 report 100% positive having perturbed no behaviour at
    all. Checked on both branches of the rule."""
    series = _rich_fixture()
    perturbed = BreakoutParams(**{axis: value})  # type: ignore[arg-type]
    long_base = _signals(series, BreakoutParams())
    long_off = _signals(series, perturbed)
    short_base = _signals(series, BreakoutParams(), regime=BEAR, allow_short=True)
    short_off = _signals(series, perturbed, regime=BEAR, allow_short=True)
    assert (long_base != long_off) or (short_base != short_off), (axis, value)


def test_the_two_new_axes_move_the_signal_set_itself_not_only_the_exits() -> None:
    """`stop_atr` can only move stop prices; `squeeze_lag` and `release_min`
    must move WHICH bars fire, which is the claim v0.2.0 rests on."""
    series = _rich_fixture()
    base = set(_signals(series, BreakoutParams()))
    for axis, values in (("squeeze_lag", (3, 10)), ("release_min", (0.8, 1.2))):
        moved = [
            set(_signals(series, BreakoutParams(**{axis: v}))) != base  # type: ignore[arg-type]
            for v in values
        ]
        assert any(moved), axis


# --------------------------------------------------------------------------- #
# the R7 guard
# --------------------------------------------------------------------------- #
# The two spec_json_hashes the LIVE approvals of strategy versions 2 and 5 are
# recorded under. Pinned from tests/research/test_promotion.py (HV2 / HV5);
# public content hashes, not secrets. If either moves, scan_scope_matches
# returns False forever and both PAPER_APPROVED strategies fall permanently
# out of scope.
HV2 = "2ed9743170bd3bbdb450ea03a004a7ffaeb64ccbbe6075db312ffd544072f382"  # pragma: allowlist secret
HV5 = "dfe696b662dd02b8fa3a02ce5b987c6eade84a40d88c1a2d8d52e206cb6f6c32"  # pragma: allowlist secret


def test_v020_does_not_disturb_the_live_spec_hashes_of_versions_2_and_5() -> None:
    """R7 / §12.4 item 6. Bumping this strategy's VERSION, adding two
    ``BreakoutParams`` fields and declaring two gate-5 axes must leave the
    other families' specs byte-identical — the axes live on the CLASS, never
    on ``StrategySpec``, exactly so ``spec_json_hash`` cannot move."""
    from signalforge.research.persistence import spec_json_hash
    from signalforge.research.strategies.relative_strength import RelativeStrength
    from signalforge.research.strategies.trend_continuation import TrendContinuation

    assert spec_json_hash(TrendContinuation().spec()) == HV2
    assert spec_json_hash(RelativeStrength().spec()) == HV5


def test_the_breakout_spec_text_records_both_new_parameters() -> None:
    """§2.4: text only, but the text must actually describe the rule that
    runs — the spec is the audit record of what was tested."""
    spec = VolatilityBreakout().spec()
    assert spec.version == "0.2.0"
    assert "squeeze_lag" in spec.entry_conditions
    assert "release_min" in spec.entry_conditions
    assert "t - 1" in spec.rule_definition
    assert any("release" in f for f in spec.feature_definitions)


def test_the_v020_spec_hash_differs_from_the_v010_shaped_spec() -> None:
    """Sanity: the spec really did change, so a stale v0.1.0 row could never
    be mistaken for this one."""
    from dataclasses import replace

    from signalforge.research.persistence import spec_json_hash

    spec = VolatilityBreakout().spec()
    assert spec_json_hash(spec) != spec_json_hash(replace(spec, version="0.1.0"))
