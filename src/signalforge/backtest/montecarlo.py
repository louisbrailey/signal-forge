"""Bootstrap confidence intervals for backtest statistics.

Resamples the per-trade R sequence with replacement to get a distribution for
expectancy, win rate, and profit factor. Seeded, so results are reproducible
(invariant S4).
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np


def bootstrap_ci(
    returns_r: Sequence[float],
    *,
    n_resamples: int = 2_000,
    seed: int = 20240101,
    ci: float = 0.95,
) -> dict[str, dict[str, float]]:
    arr = np.asarray(list(returns_r), dtype=np.float64)
    if arr.size == 0:
        return {
            "expectancy_r": {"low": 0.0, "point": 0.0, "high": 0.0},
            "win_rate": {"low": 0.0, "point": 0.0, "high": 0.0},
            "profit_factor": {"low": 0.0, "point": 0.0, "high": 0.0},
        }

    rng = np.random.default_rng(seed)
    idx = rng.integers(0, arr.size, size=(n_resamples, arr.size))
    samples = arr[idx]

    exp = samples.mean(axis=1)
    win = (samples > 0).mean(axis=1)
    gains = np.where(samples > 0, samples, 0.0).sum(axis=1)
    losses = -np.where(samples <= 0, samples, 0.0).sum(axis=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        pf = np.where(losses > 0, gains / losses, np.inf)
    pf = pf[np.isfinite(pf)]

    lo_q = (1 - ci) / 2 * 100
    hi_q = (1 - (1 - ci) / 2) * 100

    def _finite_point(vals: np.ndarray, fallback: float) -> float:
        return float(np.median(vals)) if vals.size else fallback

    return {
        "expectancy_r": {
            "low": float(np.percentile(exp, lo_q)),
            "point": float(arr.mean()),
            "high": float(np.percentile(exp, hi_q)),
        },
        "win_rate": {
            "low": float(np.percentile(win, lo_q)),
            "point": float((arr > 0).mean()),
            "high": float(np.percentile(win, hi_q)),
        },
        "profit_factor": {
            "low": float(np.percentile(pf, lo_q)) if pf.size else 0.0,
            "point": _finite_point(pf, 0.0),
            "high": float(np.percentile(pf, hi_q)) if pf.size else 0.0,
        },
    }
