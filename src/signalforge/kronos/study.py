"""Pure statistics for the pre-registered Kronos forecast-skill study.

Everything here is deterministic, stdlib + numpy + hashlib only, and never
touches a database, a model, a provider or trading code. The study script
(``scripts/kronos_skill_study.py``) composes these functions; the dashboard
does not use them. Nothing in this module is a trading signal.

Conventions: ``close_t`` is the final context close (the forecast origin),
``context_closes`` are the 128 context closes ending at ``close_t``, ``actual``
and ``predicted`` are parallel per-bar close arrays over the held-out horizon,
and ``lower``/``upper`` are the sampled per-bar extrema.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Iterable, Sequence
from itertools import product
from pathlib import Path
from typing import Any

import numpy as np

# ---------------------------------------------------------------------------
# Baselines
# ---------------------------------------------------------------------------


def unchanged_baseline(close_t: float, horizon: int) -> list[float]:
    """Repeat the final context close across the horizon."""
    if horizon <= 0 or not math.isfinite(close_t) or close_t <= 0:
        raise ValueError("unchanged_baseline requires horizon>0 and a positive close")
    return [float(close_t)] * horizon


def drift_baseline(context_closes: Sequence[float], horizon: int) -> list[float]:
    """``close_T * exp(k * mean log-return over the context)`` for k = 1..horizon."""
    closes = np.asarray(context_closes, dtype=float)
    if horizon <= 0 or closes.ndim != 1 or closes.size < 2:
        raise ValueError("drift_baseline requires horizon>0 and at least two context closes")
    if not np.all(np.isfinite(closes)) or np.any(closes <= 0):
        raise ValueError("drift_baseline requires finite positive closes")
    mu = float(np.mean(np.diff(np.log(closes))))
    close_t = float(closes[-1])
    return [close_t * math.exp(k * mu) for k in range(1, horizon + 1)]


def sma_flat_baseline(
    context_closes: Sequence[float], horizon: int, window: int = 20
) -> list[float]:
    """Flat line at the trailing ``window``-close simple moving average."""
    closes = np.asarray(context_closes, dtype=float)
    if horizon <= 0 or window <= 0 or closes.size < window:
        raise ValueError("sma_flat_baseline requires enough context for the window")
    if not np.all(np.isfinite(closes)) or np.any(closes <= 0):
        raise ValueError("sma_flat_baseline requires finite positive closes")
    return [float(np.mean(closes[-window:]))] * horizon


def baselines(context_closes: Sequence[float], horizon: int) -> dict[str, list[float]]:
    close_t = float(context_closes[-1])
    return {
        "unchanged": unchanged_baseline(close_t, horizon),
        "drift": drift_baseline(context_closes, horizon),
        "sma20": sma_flat_baseline(context_closes, horizon, 20),
    }


# ---------------------------------------------------------------------------
# Per-window metrics
# ---------------------------------------------------------------------------


def mae(actual: Sequence[float], predicted: Sequence[float]) -> float:
    a, p = _pair(actual, predicted)
    return float(np.mean(np.abs(p - a)))


def mape(actual: Sequence[float], predicted: Sequence[float]) -> float:
    a, p = _pair(actual, predicted)
    if np.any(a == 0):
        raise ValueError("MAPE undefined when an actual close is zero")
    return float(np.mean(np.abs((p - a) / a)))


def directional_accuracy_end(
    close_t: float, actual: Sequence[float], predicted: Sequence[float]
) -> int:
    """1 if the forecast and the realised horizon-end move share a sign (0 counts as no)."""
    a, p = _pair(actual, predicted)
    return int(_sign(p[-1] - close_t) == _sign(a[-1] - close_t) != 0)


def per_bar_hit_rate(close_t: float, actual: Sequence[float], predicted: Sequence[float]) -> float:
    """Share of bars whose predicted and realised moves from ``close_t`` share a sign."""
    a, p = _pair(actual, predicted)
    hits = [
        int(_sign(pi - close_t) == _sign(ai - close_t) != 0) for ai, pi in zip(a, p, strict=True)
    ]
    return float(np.mean(hits))


def band_coverage(
    actual: Sequence[float], lower: Sequence[float], upper: Sequence[float]
) -> tuple[list[int], int]:
    """Per-bar inclusion flags and the horizon-end flag for ``lower <= actual <= upper``."""
    a = np.asarray(actual, dtype=float)
    lo = np.asarray(lower, dtype=float)
    hi = np.asarray(upper, dtype=float)
    if not (a.shape == lo.shape == hi.shape) or a.ndim != 1 or a.size == 0:
        raise ValueError("band_coverage requires parallel non-empty arrays")
    if np.any(lo > hi):
        raise ValueError("band_coverage requires lower <= upper")
    flags = [int(l_ <= x <= u) for x, l_, u in zip(a, lo, hi, strict=True)]
    return flags, flags[-1]


def mean_band_width(lower: Sequence[float], upper: Sequence[float], close_t: float) -> float:
    lo = np.asarray(lower, dtype=float)
    hi = np.asarray(upper, dtype=float)
    if close_t <= 0 or lo.shape != hi.shape or lo.ndim != 1:
        raise ValueError("mean_band_width requires a positive close and parallel arrays")
    return float(np.mean(hi - lo) / close_t)


def window_metrics(
    *,
    context_closes: Sequence[float],
    actual: Sequence[float],
    predicted: Sequence[float],
    lower: Sequence[float],
    upper: Sequence[float],
) -> dict[str, Any]:
    """All pre-registered per-window metrics for one (symbol, horizon, origin) call."""
    horizon = len(actual)
    close_t = float(context_closes[-1])
    base = baselines(context_closes, horizon)
    model_mae = mae(actual, predicted)
    flags, end_flag = band_coverage(actual, lower, upper)
    out: dict[str, Any] = {
        "horizon": horizon,
        "close_t": close_t,
        "mae": model_mae,
        "mape": mape(actual, predicted),
        "relative_mae": model_mae / close_t,
        "directional_accuracy_end": directional_accuracy_end(close_t, actual, predicted),
        "per_bar_hit_rate": per_bar_hit_rate(close_t, actual, predicted),
        "coverage_per_bar": flags,
        "coverage_rate": float(np.mean(flags)),
        "coverage_end": end_flag,
        "mean_band_width_rel": mean_band_width(lower, upper, close_t),
        "band_degenerate": bool(np.all(np.asarray(upper) == np.asarray(lower))),
        "baselines": {},
    }
    for name, series in base.items():
        b_mae = mae(actual, series)
        out["baselines"][name] = {
            "values": series,
            "mae": b_mae,
            "mae_ratio": model_mae / b_mae if b_mae > 0 else math.inf,
            "log_mae_ratio": math.log(model_mae / b_mae) if model_mae > 0 and b_mae > 0 else None,
            "directional_accuracy_end": directional_accuracy_end(close_t, actual, series),
        }
    return out


# ---------------------------------------------------------------------------
# Multiple-comparison corrections
# ---------------------------------------------------------------------------


def holm_adjust(p_values: Sequence[float]) -> list[float]:
    """Holm step-down adjusted p-values (monotone, capped at 1)."""
    p = np.asarray(p_values, dtype=float)
    _check_p(p)
    m = p.size
    if m == 0:
        return []
    order = np.argsort(p)
    adjusted = np.empty(m)
    running = 0.0
    for rank, idx in enumerate(order):
        running = max(running, (m - rank) * p[idx])
        adjusted[idx] = min(1.0, running)
    return [float(v) for v in adjusted]


def benjamini_hochberg_adjust(p_values: Sequence[float]) -> list[float]:
    """Benjamini-Hochberg step-up adjusted p-values (q-values), monotone, capped at 1."""
    p = np.asarray(p_values, dtype=float)
    _check_p(p)
    m = p.size
    if m == 0:
        return []
    order = np.argsort(p)
    adjusted = np.empty(m)
    running = 1.0
    for rank in range(m - 1, -1, -1):
        idx = order[rank]
        running = min(running, p[idx] * m / (rank + 1))
        adjusted[idx] = min(1.0, running)
    return [float(v) for v in adjusted]


# ---------------------------------------------------------------------------
# Tests of one sample
# ---------------------------------------------------------------------------


def sign_flip_permutation_test(
    values: Sequence[float], *, alternative: str = "two-sided", ci_level: float = 0.95
) -> dict[str, Any]:
    """Exact sign-flip test of H0: mean = 0 on paired differences (e.g. log-MAE-ratios).

    Enumerates all ``2**n`` sign assignments (n <= 20), so the p-value is exact.
    ``alternative`` is ``"two-sided"``, ``"less"`` (mean < 0) or ``"greater"``.
    The CI is the percentile interval of the sign-flipped mean distribution
    re-centred on the observed mean; it is a descriptive uncertainty band, not a
    calibrated frequentist interval, and is reported as such.
    """
    x = np.asarray(values, dtype=float)
    if x.ndim != 1 or x.size == 0 or x.size > 20 or not np.all(np.isfinite(x)):
        raise ValueError("sign_flip_permutation_test needs 1..20 finite paired values")
    if alternative not in {"two-sided", "less", "greater"}:
        raise ValueError("alternative must be two-sided, less or greater")
    n = x.size
    observed = float(np.mean(x))
    signs = np.array(list(product((-1.0, 1.0), repeat=n)))
    means = signs @ x / n
    if alternative == "two-sided":
        p = float(np.mean(np.abs(means) >= abs(observed) - 1e-12))
    elif alternative == "less":
        p = float(np.mean(means <= observed + 1e-12))
    else:
        p = float(np.mean(means >= observed - 1e-12))
    alpha = 1.0 - ci_level
    lo, hi = np.quantile(means, [alpha / 2, 1 - alpha / 2])
    return {
        "n": n,
        "mean": observed,
        "p_value": p,
        "alternative": alternative,
        "ci_level": ci_level,
        "ci": [observed + float(lo), observed + float(hi)],
        "exact": True,
        "permutations": int(2**n),
    }


def cluster_bootstrap_mean(
    clusters: Sequence[Sequence[float]],
    *,
    n_boot: int = 10_000,
    seed: int = 20261003,
    ci_level: float = 0.95,
) -> dict[str, Any]:
    """Percentile bootstrap of the pooled mean, resampling whole clusters (origins).

    Each cluster is the vector of paired values sharing one origin date. Values
    inside a cluster are kept together, so cross-sectional dependence between
    symbols at the same origin is respected.
    """
    groups = [np.asarray(c, dtype=float) for c in clusters if len(c) > 0]
    if not groups or n_boot <= 0:
        raise ValueError("cluster_bootstrap_mean needs non-empty clusters and n_boot>0")
    pooled = np.concatenate(groups)
    rng = np.random.default_rng(seed)
    g = len(groups)
    draws = np.empty(n_boot)
    for b in range(n_boot):
        pick = rng.integers(0, g, size=g)
        draws[b] = float(np.mean(np.concatenate([groups[i] for i in pick])))
    alpha = 1.0 - ci_level
    lo, hi = np.quantile(draws, [alpha / 2, 1 - alpha / 2])
    return {
        "clusters": g,
        "n": int(pooled.size),
        "mean": float(np.mean(pooled)),
        "ci_level": ci_level,
        "ci": [float(lo), float(hi)],
        "n_boot": n_boot,
        "seed": seed,
    }


def binomial_test_exact(successes: int, trials: int, p0: float = 0.5) -> dict[str, Any]:
    """Exact two-sided binomial test (minimum-likelihood method) plus one-sided tails."""
    if trials <= 0 or not 0 <= successes <= trials or not 0 < p0 < 1:
        raise ValueError("binomial_test_exact needs 0<=k<=n, n>0, 0<p0<1")
    pmf = np.array(
        [math.comb(trials, k) * p0**k * (1 - p0) ** (trials - k) for k in range(trials + 1)]
    )
    observed = pmf[successes]
    two_sided = float(min(1.0, np.sum(pmf[pmf <= observed * (1 + 1e-9)])))
    greater = float(np.sum(pmf[successes:]))
    less = float(np.sum(pmf[: successes + 1]))
    return {
        "successes": successes,
        "trials": trials,
        "p0": p0,
        "rate": successes / trials,
        "p_two_sided": two_sided,
        "p_greater": greater,
        "p_less": less,
    }


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------


def sha256_of_tree(directories: Iterable[Path]) -> dict[str, Any]:
    """Per-file and combined sha256 of every regular file under the given directories.

    Symlinks are resolved and read (HF snapshot files are symlinks into ``blobs``).
    Files are visited in sorted relative-path order so the combined digest is stable.
    """
    files: dict[str, str] = {}
    combined = hashlib.sha256()
    for directory in directories:
        root = Path(directory)
        if not root.is_dir():
            continue
        for path in sorted(p for p in root.rglob("*") if p.is_file()):
            digest = hashlib.sha256()
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1 << 20), b""):
                    digest.update(chunk)
            rel = f"{root.name}/{path.relative_to(root).as_posix()}"
            files[rel] = digest.hexdigest()
            combined.update(rel.encode())
            combined.update(files[rel].encode())
    return {"files": files, "combined_sha256": combined.hexdigest() if files else None}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _pair(actual: Sequence[float], predicted: Sequence[float]) -> tuple[np.ndarray, np.ndarray]:
    a = np.asarray(actual, dtype=float)
    p = np.asarray(predicted, dtype=float)
    if a.shape != p.shape or a.ndim != 1 or a.size == 0:
        raise ValueError("actual and predicted must be parallel non-empty 1-D arrays")
    if not (np.all(np.isfinite(a)) and np.all(np.isfinite(p))):
        raise ValueError("actual and predicted must be finite")
    return a, p


def _sign(value: float) -> int:
    v = float(value)
    return int(v > 0) - int(v < 0)


def _check_p(p: np.ndarray) -> None:
    if p.ndim != 1 or (p.size and (np.any(p < 0) or np.any(p > 1) or not np.all(np.isfinite(p)))):
        raise ValueError("p-values must be a 1-D array within [0, 1]")


__all__ = [
    "band_coverage",
    "baselines",
    "benjamini_hochberg_adjust",
    "binomial_test_exact",
    "cluster_bootstrap_mean",
    "directional_accuracy_end",
    "drift_baseline",
    "holm_adjust",
    "mae",
    "mape",
    "mean_band_width",
    "per_bar_hit_rate",
    "sha256_of_tree",
    "sign_flip_permutation_test",
    "sma_flat_baseline",
    "unchanged_baseline",
    "window_metrics",
]
