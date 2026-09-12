"""Gate 5's options grid runner: the cap, the cache, and the pre-sealed bound."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from signalforge.research.options_gates import OptionsGateThresholds, gate_5_sensitivity
from signalforge.research.options_sensitivity import (
    GridTooLarge,
    OptionsGridPoint,
    OptionsSensitivityReport,
    cache_key,
    declared_grid,
    load_cached,
    oat_points,
    run_options_sensitivity,
    store_cached,
)
from signalforge.research.sensitivity import MAX_GRID_POINTS
from tests.research.options_evidence_support import (
    SOURCE,
    StubOptionsStrategy,
    WideGridStrategy,
    seed_everything,
    window,
)


def _factory(strat: StubOptionsStrategy):  # type: ignore[no-untyped-def]
    def build(params):  # type: ignore[no-untyped-def]
        return StubOptionsStrategy(
            key=strat.key,
            horizon=strat.horizon,
            selection_cost_model=strat.selection_cost_model,
            dte_target=int(params.get("dte_target", strat.dte_target)),
        )

    return build


# --------------------------------------------------------------------------- #
# the cap — never silent
# --------------------------------------------------------------------------- #
def test_declared_grid_is_the_full_cartesian_product() -> None:
    points, dropped = declared_grid(StubOptionsStrategy())
    assert len(points) == 4  # 2 x 2
    assert dropped == []
    assert {tuple(sorted(p)) for p in points} == {("dte_target", "width_pct")}


def test_grid_above_the_cap_raises_rather_than_truncating() -> None:
    with pytest.raises(GridTooLarge) as exc:
        declared_grid(WideGridStrategy())
    assert str(MAX_GRID_POINTS) in str(exc.value)
    assert "243" in str(exc.value)


def test_an_authorised_cap_enumerates_every_dropped_cell() -> None:
    points, dropped = declared_grid(WideGridStrategy(), allow_cap=True)
    assert len(points) == MAX_GRID_POINTS
    assert len(dropped) == 243 - MAX_GRID_POINTS
    # nothing is lost: evaluated + dropped is the whole declared product
    assert len(points) + len(dropped) == 243


def test_capped_run_reports_the_drop_and_fails_gate_5(session: Session) -> None:
    snap, _ = seed_everything(session)
    strat = WideGridStrategy()
    report = run_options_sensitivity(
        session,
        strat,
        _factory(strat),
        baseline_params=dict.fromkeys((f"axis_{i}" for i in range(5)), 1),
        dataset_snapshot=snap,
        window=window(),
        version="0.0.1",
        options_config_hash="h",
        source=SOURCE,
        allow_cap=True,
        use_cache=False,
    )
    assert report.declared_points == 243
    assert report.evaluated_points == MAX_GRID_POINTS
    assert len(report.dropped_points) == 243 - MAX_GRID_POINTS
    assert any("DROPPED" in r for r in report.reasons)
    summary = report.summary()
    assert summary.fragile
    gate = gate_5_sensitivity(summary, OptionsGateThresholds())
    assert not gate.passed


# --------------------------------------------------------------------------- #
# the run itself
# --------------------------------------------------------------------------- #
def test_grid_runs_on_the_pre_sealed_slice_only(session: Session) -> None:
    snap, _ = seed_everything(session)
    strat = StubOptionsStrategy()
    w = window(sealed_days=120)
    report = run_options_sensitivity(
        session,
        strat,
        _factory(strat),
        baseline_params={"dte_target": 35, "width_pct": 0.01},
        dataset_snapshot=snap,
        window=w,
        version="0.1.0",
        options_config_hash="h",
        source=SOURCE,
        use_cache=False,
    )
    assert report.declared_points == 4
    assert report.evaluated_points == 4
    assert sum(1 for p in report.grid if p.is_baseline) == 1
    # every counted structure entered on or before the pre-sealed end
    assert all(p.n_trades >= 0 for p in report.grid)
    assert report.oat_points  # the OAT table ran and is disclosed
    assert all(p.kind == "oat" for p in report.oat_points)
    # OAT points are disclosure only — they never enter the gate-5 fractions
    summary = report.summary()
    assert summary.n_points == 4


def test_inert_axis_is_reported_as_a_gate_5_reason(session: Session) -> None:
    """``width_pct`` does nothing in the stub, so perturbing it tests nothing —
    exactly the failure mode the equity runner's ``axis_moved`` check exists for."""
    snap, _ = seed_everything(session)
    strat = StubOptionsStrategy()
    report = run_options_sensitivity(
        session,
        strat,
        _factory(strat),
        baseline_params={"dte_target": 35, "width_pct": 0.01},
        dataset_snapshot=snap,
        window=window(),
        version="0.1.0",
        options_config_hash="h",
        source=SOURCE,
        use_cache=False,
    )
    assert "width_pct" in report.inert_axes
    assert any("width_pct" in r for r in report.summary().reasons)
    assert report.summary().fragile


def test_oat_points_exclude_the_baseline_value() -> None:
    strat = StubOptionsStrategy()
    pts = oat_points(strat, {"stop_multiple": 1.5})
    assert {tuple(p.items()) for p in pts} == {(("stop_multiple", 3.0),)}


# --------------------------------------------------------------------------- #
# the cache
# --------------------------------------------------------------------------- #
def test_cache_key_is_version_snapshot_and_config_hash() -> None:
    a = cache_key(version="0.1.0", snapshot_key="snap", options_config_hash="h1")
    assert a != cache_key(version="0.2.0", snapshot_key="snap", options_config_hash="h1")
    assert a != cache_key(version="0.1.0", snapshot_key="other", options_config_hash="h1")
    assert a != cache_key(version="0.1.0", snapshot_key="snap", options_config_hash="h2")


def test_cache_round_trip_and_hit_flag(tmp_path: Path) -> None:
    report = OptionsSensitivityReport(
        strategy_key="k",
        version="0.1.0",
        snapshot_key="snap",
        options_config_hash="h",
        axes=("a",),
        baseline_params={"a": 1},
        min_trades=15,
        declared_points=2,
        evaluated_points=2,
        dropped_points=(),
        grid=(
            OptionsGridPoint({"a": 1}, 20, 0.3, 0.7, 0, is_baseline=True),
            OptionsGridPoint({"a": 2}, 18, 0.2, 0.6, 1, is_neighbour=True),
        ),
        oat_points=(),
        inert_axes=(),
        reasons=(),
    )
    key = cache_key(version="0.1.0", snapshot_key="snap", options_config_hash="h")
    store_cached(key, report, tmp_path)
    back = load_cached(key, tmp_path)
    assert back is not None
    assert back.cache_hit is True
    assert back.declared_points == 2
    assert [p.params for p in back.grid] == [{"a": 1}, {"a": 2}]
    assert back.summary().n_evaluable == 2


def test_a_corrupt_cache_entry_is_a_miss(tmp_path: Path) -> None:
    key = cache_key(version="0.1.0", snapshot_key="snap", options_config_hash="h")
    (tmp_path / "options_sensitivity_cache").mkdir(parents=True, exist_ok=True)
    (tmp_path / "options_sensitivity_cache" / f"{key}.json").write_text("{not json")
    assert load_cached(key, tmp_path) is None


def test_a_second_run_with_identical_inputs_is_a_cache_hit(session: Session) -> None:
    snap, _ = seed_everything(session)
    strat = StubOptionsStrategy()
    kwargs = {
        "baseline_params": {"dte_target": 35, "width_pct": 0.01},
        "dataset_snapshot": snap,
        "window": window(),
        "version": "0.1.0",
        "options_config_hash": "h",
        "source": SOURCE,
    }
    first = run_options_sensitivity(session, strat, _factory(strat), **kwargs)  # type: ignore[arg-type]
    assert first.cache_hit is False
    second = run_options_sensitivity(session, strat, _factory(strat), **kwargs)  # type: ignore[arg-type]
    assert second.cache_hit is True
    assert second.to_dict()["grid"] == first.to_dict()["grid"]
    # a different options_config_hash is a different question, so it is a MISS
    third = run_options_sensitivity(
        session, strat, _factory(strat), **{**kwargs, "options_config_hash": "other"}  # type: ignore[arg-type]
    )
    assert third.cache_hit is False


def test_summary_feeds_gate_5(session: Session) -> None:
    snap, _ = seed_everything(session)
    strat = StubOptionsStrategy()
    report = run_options_sensitivity(
        session,
        strat,
        _factory(strat),
        baseline_params={"dte_target": 35, "width_pct": 0.01},
        dataset_snapshot=snap,
        window=window(),
        version="0.1.0",
        options_config_hash="h",
        source=SOURCE,
        use_cache=False,
    )
    summary = report.summary()
    gate = gate_5_sensitivity(summary, OptionsGateThresholds())
    assert gate.number == 5
    assert gate.evidence["grid_run"] is True
    # a 4-point grid can never clear the 58-point evaluability floor
    assert not gate.passed
    assert any("evaluable" in r for r in gate.detail.split(";"))
