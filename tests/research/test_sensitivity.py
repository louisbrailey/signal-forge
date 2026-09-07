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
