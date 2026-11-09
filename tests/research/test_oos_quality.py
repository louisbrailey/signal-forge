"""Malformed evidence fails closed; valid threshold comparisons stay unchanged."""

from __future__ import annotations

import pytest

from signalforge.config.research import QualityThresholds
from signalforge.research.scan import _oos_metric_failures


@pytest.mark.parametrize(
    ("metrics", "intervals", "reason"),
    [
        ({"n_trades": 200, "expectancy_r": 0.5}, {}, "CI"),
        ({"n_trades": 200, "expectancy_r": 0.5}, {"expectancy_r": []}, "CI"),
        ({"n_trades": 200, "expectancy_r": 0.5}, None, "CI"),
        ({"n_trades": 200, "expectancy_r": 0.5}, {"expectancy_r": {"low": 1, "high": 0}}, "CI"),
        (
            {"n_trades": 200, "expectancy_r": 0.5},
            {"expectancy_r": {"low": float("nan"), "high": 1}},
            "CI",
        ),
        ({"n_trades": 200, "expectancy_r": 0.5}, {"expectancy_r": {"low": "bad", "high": 1}}, "CI"),
        ({"n_trades": float("inf"), "expectancy_r": 0.5}, {}, "trades"),
        ({"n_trades": 1.5, "expectancy_r": 0.5}, {}, "trades"),
        ({"n_trades": True, "expectancy_r": 0.5}, {}, "trades"),
        ({"n_trades": 200, "expectancy_r": float("inf")}, {}, "expectancy"),
        ({"n_trades": 200, "expectancy_r": float("nan")}, {}, "expectancy"),
        ({"n_trades": 200, "expectancy_r": None}, {}, "expectancy"),
        (None, {}, "trades"),
    ],
)
def test_missing_or_invalid_evidence_fails_closed(metrics, intervals, reason):
    failures = _oos_metric_failures(metrics, intervals, QualityThresholds())
    assert failures and any(reason in failure for failure in failures)


def test_valid_comparisons_preserve_every_configured_threshold():
    q = QualityThresholds()
    assert (
        _oos_metric_failures(
            {"n_trades": q.min_oos_trades, "expectancy_r": q.min_oos_expectancy_r + 0.1},
            {"expectancy_r": {"low": q.min_oos_ci_low_r, "high": 0.9}},
            q,
        )
        == []
    )
    failed = _oos_metric_failures(
        {"n_trades": q.min_oos_trades - 1, "expectancy_r": q.min_oos_expectancy_r},
        {"expectancy_r": {"low": q.min_oos_ci_low_r - 0.1, "high": 0.9}},
        q,
    )
    assert len(failed) == 3
