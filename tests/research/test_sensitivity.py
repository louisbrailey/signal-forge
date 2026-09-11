"""Parameter-sensitivity grid: fragility detection + determinism."""

from __future__ import annotations

from dataclasses import asdict
from datetime import date, timedelta

from sqlalchemy.orm import Session

from signalforge.data.adapters.fixture import FixtureMarketDataAdapter
from signalforge.data.ingest import ingest_universe
from signalforge.domain import Horizon
from signalforge.research.sensitivity import (
    MAX_GRID_POINTS,
    _is_neighbour,
    run_parameter_sensitivity,
)
from signalforge.research.strategies.trend_continuation import TrendContinuation, TrendParams

SYMS = ["SPY", "AAPL", "MSFT", "NVDA"]


def _seed(session: Session) -> tuple[date, date]:
    end = date(2024, 6, 30)
    start = end - timedelta(days=365 * 3)
    ingest_universe(session, FixtureMarketDataAdapter(), SYMS, start, end)
    session.flush()
    return start, end


def _factory(p: dict[str, object]) -> TrendContinuation:
    return TrendContinuation(Horizon.SHORT_SWING, TrendParams(**p))  # type: ignore[arg-type]


def test_is_neighbour_is_one_step_on_one_axis() -> None:
    grid = {"a": [1, 2, 3], "b": [10, 20, 30]}
    base = {"a": 2, "b": 20}
    assert _is_neighbour({"a": 1, "b": 20}, base, grid) is True
    assert _is_neighbour({"a": 3, "b": 20}, base, grid) is True
    assert _is_neighbour({"a": 1, "b": 10}, base, grid) is False  # two axes differ
    assert _is_neighbour({"a": 2, "b": 20}, base, grid) is False  # the baseline itself
    grid_wide = {"a": [1, 2, 3, 4, 5]}
    assert _is_neighbour({"a": 4}, {"a": 2}, grid_wide) is False  # two steps


def test_grid_point_cap_is_enforced(session: Session) -> None:
    start, end = _seed(session)
    big = {"sma_fast": list(range(MAX_GRID_POINTS + 2))}
    try:
        run_parameter_sensitivity(
            session,
            strategy_key="trend_continuation.short_swing",
            version="0.1.0",
            factory=_factory,
            baseline_params=asdict(TrendParams()),
            grid=big,
            symbols=SYMS,
            start=start,
            end=end,
        )
    except ValueError as exc:
        assert "cap is" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected the grid-size cap to trip")


def test_sensitivity_report_is_deterministic_and_well_formed(session: Session) -> None:
    start, end = _seed(session)
    grid = {"sma_fast": [15, 20, 25], "vol_mult": [1.1, 1.3, 1.5]}

    def _run() -> object:
        return run_parameter_sensitivity(
            session,
            strategy_key="trend_continuation.short_swing",
            version="0.1.0",
            factory=_factory,
            baseline_params=asdict(TrendParams()),
            grid=grid,
            symbols=SYMS,
            start=start,
            end=end,
            min_trades=1,
        )

    a = _run()
    b = _run()
    assert a.to_dict() == b.to_dict()  # S4: deterministic
    assert a.n_points == 9
    assert any(p.is_baseline for p in a.grid)
    assert 0.0 <= a.positive_fraction <= 1.0
    # On fixture random-walk data the trend edge does not survive the grid.
    assert a.fragile is True
    assert a.reasons


# --------------------------------------------------------------------------- #
# item 2: the per-axis no-op check — an axis that moves nothing tested nothing
# --------------------------------------------------------------------------- #
def _ignoring_factory(p: dict[str, object]) -> TrendContinuation:
    """A factory that silently drops the 'ignored' axis — the exact shape of a
    retained-but-unused parameter, which makes every grid point along that
    axis identical."""
    q = {k: v for k, v in p.items() if k != "ignored"}
    return TrendContinuation(Horizon.SHORT_SWING, TrendParams(**q))  # type: ignore[arg-type]


def test_inert_axis_is_detected_and_makes_the_report_fragile(session: Session) -> None:
    start, end = _seed(session)
    report = run_parameter_sensitivity(
        session,
        strategy_key="trend_continuation.short_swing",
        version="0.1.0",
        factory=_ignoring_factory,
        baseline_params={**asdict(TrendParams()), "ignored": 2},
        grid={"sma_fast": [15, 20, 25], "ignored": [1, 2, 3]},
        symbols=SYMS,
        start=start,
        end=end,
        min_trades=1,
    )

    assert report.inert_axes == ["ignored"]
    assert report.axis_moved == {"sma_fast": True, "ignored": False}
    assert report.fragile is True
    assert any("does not change OOS trade count or expectancy" in r for r in report.reasons)
    assert report.to_dict()["inert_axes"] == ["ignored"]
    assert report.to_dict()["axis_moved"]["ignored"] is False


def test_a_live_axis_is_not_flagged_inert(session: Session) -> None:
    """The shipped two-axis grids must not be disturbed by the new check: an
    axis that moves the trade count or the expectancy is never flagged."""
    start, end = _seed(session)
    report = run_parameter_sensitivity(
        session,
        strategy_key="trend_continuation.short_swing",
        version="0.1.0",
        factory=_factory,
        baseline_params=asdict(TrendParams()),
        grid={"sma_fast": [15, 20, 25], "stop_atr": [1.2, 1.5, 1.8]},
        symbols=SYMS,
        start=start,
        end=end,
        min_trades=1,
    )
    assert report.inert_axes == []
    assert report.axis_moved == {"sma_fast": True, "stop_atr": True}
    assert not any("tested nothing" in r for r in report.reasons)


def test_three_axis_grid_neighbour_fraction_counts_all_axes(session: Session) -> None:
    """The engine was already N-axis capable; a declared third axis must widen
    the neighbour denominator from 4 to 6 rather than be quietly ignored."""
    start, end = _seed(session)
    report = run_parameter_sensitivity(
        session,
        strategy_key="trend_continuation.short_swing",
        version="0.1.0",
        factory=_factory,
        baseline_params=asdict(TrendParams()),
        grid={
            "sma_fast": [15, 20, 25],
            "stop_atr": [1.2, 1.5, 1.8],
            "time_stop_bars": [5, 10, 20],
        },
        symbols=SYMS,
        start=start,
        end=end,
        min_trades=0,
    )
    assert report.n_points == 27
    assert sum(1 for p in report.grid if p.is_neighbour) == 6
    assert set(report.axis_moved) == {"sma_fast", "stop_atr", "time_stop_bars"}
