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


# ---------------------------------------------------------------------------
# Eval-mode diagnostic statistics
# ---------------------------------------------------------------------------

DIAGNOSTIC_SCRIPT = SCRIPT.with_name("kronos_eval_diagnostic.py")


def test_rank_average_and_spearman_known_values() -> None:
    assert study.rank_average([10.0, 30.0, 20.0, 30.0]) == [1.0, 3.5, 2.0, 3.5]
    assert study.spearman([1, 2, 3, 4], [10, 20, 30, 40]) == pytest.approx(1.0)
    assert study.spearman([1, 2, 3, 4], [4, 3, 2, 1]) == pytest.approx(-1.0)
    # Classic textbook case: d^2 sum = 2 over n = 5 -> 1 - 6*2/(5*24) = 0.9.
    assert study.spearman([1, 2, 3, 4, 5], [2, 1, 3, 4, 5]) == pytest.approx(0.9)
    # Ties use average ranks (Pearson on ranks), monotone transform invariant.
    x, y = [1.0, 2.0, 2.0, 5.0], [3.0, 1.0, 4.0, 4.0]
    assert study.spearman(x, y) == pytest.approx(study.spearman([v**3 for v in x], y))
    assert study.spearman([1, 1, 1], [1, 2, 3]) is None
    with pytest.raises(ValueError):
        study.spearman([1.0], [1.0])
    with pytest.raises(ValueError):
        study.rank_average([1.0, float("nan")])


def test_returns_and_vol_helpers() -> None:
    assert study.log_return(100.0, 110.0) == pytest.approx(math.log(1.1))
    assert study.daily_log_returns(100.0, [110.0, 121.0]) == pytest.approx([math.log(1.1)] * 2)
    assert study.sample_std([1.0, 3.0]) == pytest.approx(math.sqrt(2.0))
    ctx = [100.0 * math.exp(0.01 * i) for i in range(128)]
    assert study.trailing_vol(ctx, 20) == pytest.approx(0.0, abs=1e-12)
    alternating = [100.0 * math.exp(0.02 * (i % 2)) for i in range(128)]
    assert study.trailing_vol(alternating, 20) == pytest.approx(
        float(np.std([0.02, -0.02] * 10, ddof=1))
    )
    # Two paths: daily returns +1%,+1% and -1%,-1% pooled.
    up = [100 * math.exp(0.01), 100 * math.exp(0.02)]
    down = [100 * math.exp(-0.01), 100 * math.exp(-0.02)]
    assert study.predicted_daily_vol(100.0, [up, down]) == pytest.approx(
        float(np.std([0.01, 0.01, -0.01, -0.01], ddof=1))
    )
    with pytest.raises(ValueError):
        study.log_return(0.0, 1.0)
    with pytest.raises(ValueError):
        study.sample_std([1.0])
    with pytest.raises(ValueError):
        study.trailing_vol([1.0] * 20, 20)


def test_quantile_band_and_reference_coverage() -> None:
    lo, hi = study.quantile_band([float(v) for v in range(1, 11)])
    assert lo == pytest.approx(1.9) and hi == pytest.approx(9.1)
    assert study.quantile_band([5.0]) == (5.0, 5.0)
    assert study.quantile_band_reference_coverage(10) == pytest.approx(0.8 * 9 / 11)
    assert study.quantile_band_reference_coverage(3) == pytest.approx(0.4)
    # Monte Carlo: calibrated 10-draw ensembles cover about 65.5%, not 80%.
    rng = np.random.default_rng(1)
    draws = rng.normal(size=(40_000, 11))
    q = np.quantile(draws[:, :10], [0.1, 0.9], axis=1)
    covered = np.mean((q[0] <= draws[:, 10]) & (draws[:, 10] <= q[1]))
    assert covered == pytest.approx(0.8 * 9 / 11, abs=0.01)
    with pytest.raises(ValueError):
        study.quantile_band([])
    with pytest.raises(ValueError):
        study.quantile_band([1.0], 0.9, 0.1)


def test_diagnostic_window_metrics_known_case() -> None:
    ctx = [100.0] * 128
    actual = [101.0, 102.0, 103.0, 104.0, 105.0]
    paths = [[100.0, 100.0, 100.0, 100.0, 102.0 + i] for i in range(10)]  # ends 102..111
    m = study.diagnostic_window_metrics(context_closes=ctx, actual=actual, paths=paths)
    assert m["n_paths"] == 10 and m["horizon"] == 5
    assert m["predicted_end"] == pytest.approx(106.5)
    assert m["r_hat"] == pytest.approx(math.log(1.065)) and m["r"] == pytest.approx(math.log(1.05))
    assert m["abs_err_model"] == pytest.approx(abs(math.log(1.065) - math.log(1.05)))
    assert m["abs_err_unchanged"] == pytest.approx(math.log(1.05))
    assert m["direction_hit"] == 1 and m["r_sign"] == 1
    assert (m["q10_end"], m["q90_end"]) == pytest.approx((102.9, 110.1))
    assert m["covered_10_90"] == 1
    assert m["vol_trailing20"] == 0.0
    assert m["vol_realised"] == pytest.approx(
        study.sample_std(study.daily_log_returns(100.0, actual))
    )
    low = study.diagnostic_window_metrics(
        context_closes=ctx, actual=[99.0] * 5, paths=[[101.0] * 5] * 3
    )
    assert low["direction_hit"] == 0 and low["covered_10_90"] == 0 and low["r_sign"] == -1
    flat = study.diagnostic_window_metrics(
        context_closes=ctx, actual=[101.0, 100.0], paths=[[101.0, 100.0]] * 3
    )
    assert flat["direction_hit"] == 0 and flat["abs_err_unchanged"] == 0.0  # zero is a miss
    with pytest.raises(ValueError):
        study.diagnostic_window_metrics(context_closes=ctx, actual=actual, paths=[[1.0] * 4])


def test_cluster_bootstrap_log_ratio() -> None:
    same = study.cluster_bootstrap_log_ratio([1.0, 2.0, 3.0], [1.0, 2.0, 3.0], n_boot=500)
    assert same["ratio"] == 1.0 and same["ratio_ci"] == [1.0, 1.0]
    assert same["p_two_sided"] == 1.0
    num, den = [2.0, 4.1, 5.9, 8.2], [1.0, 2.0, 3.0, 4.0]
    worse = study.cluster_bootstrap_log_ratio(num, den, n_boot=500)
    assert worse["ratio"] == pytest.approx(20.2 / 10.0)
    assert worse["ratio_ci"][0] > 1.0 and worse["p_two_sided"] == pytest.approx(1 / 500)
    assert worse["ratio_ci"][0] <= worse["ratio"] <= worse["ratio_ci"][1]
    assert worse == study.cluster_bootstrap_log_ratio(num, den, n_boot=500)
    with pytest.raises(ValueError):
        study.cluster_bootstrap_log_ratio([1.0, 0.0], [1.0, 1.0])
    with pytest.raises(ValueError):
        study.cluster_bootstrap_log_ratio([1.0], [1.0, 1.0])


def test_bootstrap_indices_and_summary() -> None:
    idx = study.bootstrap_cluster_indices(7, n_boot=50, seed=3)
    assert idx.shape == (50, 7) and idx.min() >= 0 and idx.max() <= 6
    blocks = study.bootstrap_cluster_indices(10, n_boot=200, seed=3, block=4)
    assert blocks.shape == (200, 10) and blocks.min() >= 0 and blocks.max() <= 9
    assert np.all(np.diff(blocks[:, :4], axis=1) == 1)  # consecutive inside a block
    assert np.all(np.diff(blocks[:, 4:8], axis=1) == 1)
    with pytest.raises(ValueError):
        study.bootstrap_cluster_indices(3, block=4)
    s = study.bootstrap_summary(0.5, np.linspace(0.1, 0.9, 81))
    assert s["ci"][0] == pytest.approx(0.12) and s["ci"][1] == pytest.approx(0.88)
    assert s["p_two_sided"] == pytest.approx(1 / 81)
    centred = study.bootstrap_summary(0.0, np.array([-1.0, 1.0, -2.0, 2.0]))
    assert centred["p_two_sided"] == 1.0


def test_rank_ic_summary() -> None:
    s = study.rank_ic_summary([0.1, 0.3, -0.1, 0.5])
    assert s["mean"] == pytest.approx(0.2) and s["share_positive"] == 0.75
    sd = float(np.std([0.1, 0.3, -0.1, 0.5], ddof=1))
    assert s["t_stat"] == pytest.approx(0.2 / (sd / 2))
    assert study.rank_ic_summary([0.2, 0.2])["t_stat"] is None
    with pytest.raises(ValueError):
        study.rank_ic_summary([0.1])


def test_diagnostic_script_imports_no_trading_surface_and_is_study_only() -> None:
    source = DIAGNOSTIC_SCRIPT.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(DIAGNOSTIC_SCRIPT))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
            imported.extend(f"{node.module}.{alias.name}" for alias in node.names)
    offenders = [name for name in imported if name.startswith(FORBIDDEN)]
    assert not offenders, offenders
    assert "signalforge.db.session" not in imported
    assert "mode=ro" in source
