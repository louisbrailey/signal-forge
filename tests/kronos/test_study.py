"""Hermetic checks of the study statistics on synthetic data; no model, DB or provider."""

from __future__ import annotations

import ast
import math
from pathlib import Path

import numpy as np
import pytest

from signalforge.kronos import study

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "kronos_skill_study.py"
FORBIDDEN = (
    "signalforge.paper",
    "signalforge.execution",
    "signalforge.risk",
    "signalforge.alerts",
    "signalforge.llm",
    "signalforge.research.scan",
)


def test_baselines_known_values() -> None:
    ctx = [100.0 * math.exp(0.01 * i) for i in range(128)]  # constant log-return 1%
    b = study.baselines(ctx, 5)
    assert b["unchanged"] == [ctx[-1]] * 5
    for k, v in enumerate(b["drift"], 1):
        assert v == pytest.approx(ctx[-1] * math.exp(0.01 * k))
    assert b["sma20"] == [pytest.approx(float(np.mean(ctx[-20:])))] * 5
    assert study.unchanged_baseline(50.0, 3) == [50.0, 50.0, 50.0]
    with pytest.raises(ValueError):
        study.drift_baseline([100.0, -1.0], 5)


def test_window_metrics_perfect_and_direction() -> None:
    ctx = [100.0] * 128
    actual = [101.0, 102.0, 103.0]
    m = study.window_metrics(
        context_closes=ctx,
        actual=actual,
        predicted=actual,
        lower=[100.5, 101.5, 102.5],
        upper=[101.5, 102.5, 103.5],
    )
    assert m["mae"] == 0 and m["mape"] == 0 and m["relative_mae"] == 0
    assert m["directional_accuracy_end"] == 1 and m["per_bar_hit_rate"] == 1.0
    assert m["coverage_per_bar"] == [1, 1, 1] and m["coverage_end"] == 1
    assert m["mean_band_width_rel"] == pytest.approx(0.01)
    assert m["band_degenerate"] is False
    assert m["baselines"]["unchanged"]["mae"] == pytest.approx(2.0)
    assert m["baselines"]["unchanged"]["mae_ratio"] == 0.0
    assert m["baselines"]["unchanged"]["log_mae_ratio"] is None
    down = study.window_metrics(
        context_closes=ctx,
        actual=actual,
        predicted=[99.0, 98.0, 97.0],
        lower=[99.0] * 3,
        upper=[99.0] * 3,
    )
    assert down["directional_accuracy_end"] == 0 and down["per_bar_hit_rate"] == 0.0
    assert down["band_degenerate"] is True
    assert down["coverage_rate"] == 0.0


def test_mae_ratio_matches_definition() -> None:
    ctx = list(np.linspace(90, 100, 128))
    actual = [101.0, 99.0, 100.0, 102.0, 98.0]
    predicted = [100.5, 99.5, 100.5, 101.0, 99.0]
    m = study.window_metrics(
        context_closes=ctx, actual=actual, predicted=predicted, lower=predicted, upper=predicted
    )
    drift = study.drift_baseline(ctx, 5)
    expected = study.mae(actual, predicted) / study.mae(actual, drift)
    assert m["baselines"]["drift"]["mae_ratio"] == pytest.approx(expected)
    assert m["baselines"]["drift"]["log_mae_ratio"] == pytest.approx(math.log(expected))


def test_holm_known_vector() -> None:
    # Classic textbook example: p = (0.01, 0.04, 0.03, 0.005), m = 4.
    adj = study.holm_adjust([0.01, 0.04, 0.03, 0.005])
    assert adj == pytest.approx([0.03, 0.06, 0.06, 0.02])
    assert study.holm_adjust([]) == []
    with pytest.raises(ValueError):
        study.holm_adjust([1.5])


def test_benjamini_hochberg_known_vector() -> None:
    adj = study.benjamini_hochberg_adjust([0.01, 0.04, 0.03, 0.005])
    assert adj == pytest.approx([0.02, 0.04, 0.04, 0.02])
    assert study.benjamini_hochberg_adjust([0.5]) == [0.5]
    assert all(a <= b for a, b in zip(sorted(adj), sorted(adj)[1:], strict=False))


def test_sign_flip_permutation_constructed_case() -> None:
    # All five values negative: the observed mean is the most extreme in each tail.
    t = study.sign_flip_permutation_test([-0.1, -0.2, -0.15, -0.05, -0.3], alternative="less")
    assert t["exact"] and t["permutations"] == 32
    assert t["p_value"] == pytest.approx(1 / 32)
    two = study.sign_flip_permutation_test([-0.1, -0.2, -0.15, -0.05, -0.3])
    assert two["p_value"] == pytest.approx(2 / 32)
    assert two["ci"][0] <= two["mean"] <= two["ci"][1]
    # Symmetric values: mean 0, p = 1.
    null = study.sign_flip_permutation_test([-1.0, 1.0, -2.0, 2.0])
    assert null["mean"] == 0 and null["p_value"] == 1.0
    with pytest.raises(ValueError):
        study.sign_flip_permutation_test([0.1] * 21)


def test_cluster_bootstrap_deterministic_and_covers_mean() -> None:
    clusters = [[0.1, 0.2], [-0.1, 0.0], [0.05, 0.15], [0.3, 0.1]]
    a = study.cluster_bootstrap_mean(clusters, n_boot=500)
    b = study.cluster_bootstrap_mean(clusters, n_boot=500)
    assert a == b
    assert a["clusters"] == 4 and a["n"] == 8
    assert a["ci"][0] <= a["mean"] <= a["ci"][1]


def test_binomial_exact_known_values() -> None:
    r = study.binomial_test_exact(9, 12, 0.5)
    assert r["p_greater"] == pytest.approx(299 / 4096)
    assert r["p_two_sided"] == pytest.approx(2 * 299 / 4096)
    assert study.binomial_test_exact(6, 12, 0.5)["p_two_sided"] == 1.0
    assert study.binomial_test_exact(12, 12, 0.5)["p_two_sided"] == pytest.approx(2 / 4096)
    with pytest.raises(ValueError):
        study.binomial_test_exact(13, 12)


def test_band_coverage_rules() -> None:
    flags, end = study.band_coverage([1.0, 2.0, 3.0], [0.5, 2.5, 2.0], [1.5, 3.0, 4.0])
    assert flags == [1, 0, 1] and end == 1
    with pytest.raises(ValueError):
        study.band_coverage([1.0], [2.0], [1.0])


def test_sha256_of_tree(tmp_path: Path) -> None:
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "w.bin").write_bytes(b"weights")
    first = study.sha256_of_tree([tmp_path / "a"])
    assert set(first["files"]) == {"a/w.bin"}
    assert first == study.sha256_of_tree([tmp_path / "a"])
    (tmp_path / "a" / "w.bin").write_bytes(b"other")
    assert study.sha256_of_tree([tmp_path / "a"])["combined_sha256"] != first["combined_sha256"]
    assert study.sha256_of_tree([tmp_path / "missing"])["combined_sha256"] is None


def test_study_script_imports_no_trading_surface() -> None:
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"), filename=str(SCRIPT))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
            imported.extend(f"{node.module}.{alias.name}" for alias in node.names)
    offenders = [name for name in imported if name.startswith(FORBIDDEN)]
    assert not offenders, offenders
    assert "signalforge.db.session" not in imported  # read-only engine only, never get_engine
