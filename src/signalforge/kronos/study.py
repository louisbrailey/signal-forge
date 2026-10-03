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
# Eval-mode diagnostic (return-space, rank, quantile and volatility metrics)
# ---------------------------------------------------------------------------


def rank_average(values: Sequence[float]) -> list[float]:
    """1-based ranks with ties given their average rank."""
    x = np.asarray(values, dtype=float)
    if x.ndim != 1 or x.size == 0 or not np.all(np.isfinite(x)):
        raise ValueError("rank_average needs a non-empty finite 1-D array")
    order = np.argsort(x, kind="mergesort")
    ranks = np.empty(x.size)
    i = 0
    while i < x.size:
        j = i
        while j + 1 < x.size and x[order[j + 1]] == x[order[i]]:
            j += 1
        ranks[order[i : j + 1]] = (i + j) / 2 + 1
        i = j + 1
    return [float(r) for r in ranks]


def spearman(x: Sequence[float], y: Sequence[float]) -> float | None:
    """Spearman rank correlation (average ranks); ``None`` if either side is constant."""
    if len(x) != len(y) or len(x) < 2:
        raise ValueError("spearman needs two parallel arrays of length >= 2")
    rx = np.asarray(rank_average(x))
    ry = np.asarray(rank_average(y))
    sx, sy = float(np.std(rx)), float(np.std(ry))
    if sx == 0 or sy == 0:
        return None
    return float(np.mean((rx - rx.mean()) * (ry - ry.mean())) / (sx * sy))


def log_return(start: float, end: float) -> float:
    if not (math.isfinite(start) and math.isfinite(end)) or start <= 0 or end <= 0:
        raise ValueError("log_return needs finite positive prices")
    return math.log(end / start)


def daily_log_returns(close_t: float, closes: Sequence[float]) -> list[float]:
    """Daily log returns of ``closes``, the first taken from ``close_t``."""
    series = np.asarray([close_t, *closes], dtype=float)
    if series.size < 2 or not np.all(np.isfinite(series)) or np.any(series <= 0):
        raise ValueError("daily_log_returns needs finite positive prices")
    return [float(v) for v in np.diff(np.log(series))]


def sample_std(values: Sequence[float]) -> float:
    x = np.asarray(values, dtype=float)
    if x.ndim != 1 or x.size < 2 or not np.all(np.isfinite(x)):
        raise ValueError("sample_std needs at least two finite values")
    return float(np.std(x, ddof=1))


def predicted_daily_vol(close_t: float, paths: Sequence[Sequence[float]]) -> float:
    """Sample std of predicted daily log returns pooled over every path and step."""
    pooled: list[float] = []
    for path in paths:
        pooled.extend(daily_log_returns(close_t, path))
    return sample_std(pooled)


def trailing_vol(context_closes: Sequence[float], window: int = 20) -> float:
    """Sample std of the last ``window`` daily log returns of the context."""
    if window < 2 or len(context_closes) < window + 1:
        raise ValueError("trailing_vol needs window+1 context closes")
    tail = list(context_closes[-(window + 1) :])
    return sample_std(daily_log_returns(tail[0], tail[1:]))


def quantile_band(
    values: Sequence[float], lower_q: float = 0.1, upper_q: float = 0.9
) -> tuple[float, float]:
    """``lower_q``/``upper_q`` quantiles (numpy linear interpolation) of sampled values."""
    x = np.asarray(values, dtype=float)
    if x.ndim != 1 or x.size == 0 or not np.all(np.isfinite(x)):
        raise ValueError("quantile_band needs a non-empty finite 1-D array")
    if not 0 <= lower_q < upper_q <= 1:
        raise ValueError("quantile_band needs 0 <= lower_q < upper_q <= 1")
    lo, hi = np.quantile(x, [lower_q, upper_q])
    return float(lo), float(hi)


def quantile_band_reference_coverage(n: int, lower_q: float = 0.1, upper_q: float = 0.9) -> float:
    """Expected coverage of the interpolated band of ``n`` exchangeable draws.

    Under linear interpolation the q-quantile sits at order-statistic position
    ``1 + (n-1)q``, whose expected probability level is ``(1 + (n-1)q) / (n+1)``; the
    band therefore covers ``(upper_q - lower_q)(n-1)/(n+1)`` when the ensemble is
    perfectly calibrated, which is below the nominal ``upper_q - lower_q``.
    """
    if n < 1:
        raise ValueError("n must be positive")
    return (upper_q - lower_q) * (n - 1) / (n + 1)


def diagnostic_window_metrics(
    *,
    context_closes: Sequence[float],
    actual: Sequence[float],
    paths: Sequence[Sequence[float]],
) -> dict[str, Any]:
    """Per-call return-space metrics of the pre-registered eval-mode diagnostic."""
    horizon = len(actual)
    if horizon < 2 or not paths or any(len(p) != horizon for p in paths):
        raise ValueError("diagnostic_window_metrics needs parallel paths of the horizon length")
    close_t = float(context_closes[-1])
    ends = [float(p[-1]) for p in paths]
    predicted_end = float(np.mean(ends))
    r_hat = log_return(close_t, predicted_end)
    r = log_return(close_t, float(actual[-1]))
    q_lo, q_hi = quantile_band(ends)
    return {
        "horizon": horizon,
        "n_paths": len(paths),
        "close_t": close_t,
        "predicted_end": predicted_end,
        "actual_end": float(actual[-1]),
        "r_hat": r_hat,
        "r": r,
        "abs_err_model": abs(r_hat - r),
        "abs_err_unchanged": abs(r),
        "direction_hit": int(_sign(r_hat) == _sign(r) != 0),
        "r_sign": _sign(r),
        "q10_end": q_lo,
        "q90_end": q_hi,
        "covered_10_90": int(q_lo <= float(actual[-1]) <= q_hi),
        "vol_predicted": predicted_daily_vol(close_t, paths),
        "vol_trailing20": trailing_vol(context_closes, 20),
        "vol_realised": sample_std(daily_log_returns(close_t, actual)),
    }


def bootstrap_cluster_indices(
    n_clusters: int, *, n_boot: int = 10_000, seed: int = 20261003, block: int = 1
) -> np.ndarray:
    """``(n_boot, n_clusters)`` resampled cluster indices.

    ``block == 1`` is the ordinary cluster bootstrap. ``block > 1`` is a moving-block
    bootstrap over consecutive clusters (clusters must be in time order): blocks of
    ``block`` consecutive indices are drawn with replacement and truncated to
    ``n_clusters``.
    """
    if n_clusters <= 0 or n_boot <= 0 or block <= 0 or block > n_clusters:
        raise ValueError("bootstrap_cluster_indices needs positive sizes and block <= clusters")
    rng = np.random.default_rng(seed)
    if block == 1:
        return np.asarray(rng.integers(0, n_clusters, size=(n_boot, n_clusters)))
    n_blocks = math.ceil(n_clusters / block)
    starts = rng.integers(0, n_clusters - block + 1, size=(n_boot, n_blocks))
    idx = (starts[:, :, None] + np.arange(block)[None, None, :]).reshape(n_boot, -1)
    return np.asarray(idx[:, :n_clusters])


def bootstrap_summary(
    estimate: float, draws: np.ndarray, *, null: float = 0.0, ci_level: float = 0.95
) -> dict[str, Any]:
    """Percentile CI and two-sided bootstrap p of ``estimate`` against ``null``.

    ``p = 2 * min(share of draws <= null, share >= null)``, floored at ``1/len(draws)``
    and capped at 1.
    """
    d = np.asarray(draws, dtype=float)
    if d.ndim != 1 or d.size == 0 or not np.all(np.isfinite(d)):
        raise ValueError("bootstrap_summary needs finite draws")
    alpha = 1.0 - ci_level
    lo, hi = np.quantile(d, [alpha / 2, 1 - alpha / 2])
    p = 2.0 * min(float(np.mean(d <= null)), float(np.mean(d >= null)))
    return {
        "estimate": float(estimate),
        "ci_level": ci_level,
        "ci": [float(lo), float(hi)],
        "p_two_sided": float(min(1.0, max(p, 1.0 / d.size))),
        "n_boot": int(d.size),
    }


def cluster_bootstrap_log_ratio(
    numerators: Sequence[float],
    denominators: Sequence[float],
    *,
    n_boot: int = 10_000,
    seed: int = 20261003,
    ci_level: float = 0.95,
    block: int = 1,
) -> dict[str, Any]:
    """Bootstrap of ``ln(sum(numerators) / sum(denominators))`` over clusters.

    Each entry is one cluster's (origin's) summed numerator and denominator, e.g. summed
    absolute errors of the model and of the baseline across symbols. The output carries
    the log ratio, its percentile CI, the two-sided p against 0 and the same on the
    ratio scale.
    """
    num = np.asarray(numerators, dtype=float)
    den = np.asarray(denominators, dtype=float)
    if num.shape != den.shape or num.ndim != 1 or num.size == 0:
        raise ValueError("cluster_bootstrap_log_ratio needs parallel non-empty 1-D arrays")
    if not (np.all(np.isfinite(num)) and np.all(np.isfinite(den))):
        raise ValueError("cluster_bootstrap_log_ratio needs finite sums")
    if np.any(num <= 0) or np.any(den <= 0):
        raise ValueError("cluster_bootstrap_log_ratio needs positive cluster sums")
    idx = bootstrap_cluster_indices(num.size, n_boot=n_boot, seed=seed, block=block)
    draws = np.log(num[idx].sum(axis=1) / den[idx].sum(axis=1))
    estimate = math.log(float(num.sum()) / float(den.sum()))
    out = bootstrap_summary(estimate, draws, ci_level=ci_level)
    out.update(
        {
            "clusters": int(num.size),
            "seed": seed,
            "block": block,
            "log_ratio": out["estimate"],
            "ratio": math.exp(out["estimate"]),
            "ratio_ci": [math.exp(out["ci"][0]), math.exp(out["ci"][1])],
        }
    )
    return out


def rank_ic_summary(ics: Sequence[float]) -> dict[str, Any]:
    """Mean, t-statistic (sample sd) and share positive of per-origin rank ICs."""
    x = np.asarray(ics, dtype=float)
    if x.ndim != 1 or x.size < 2 or not np.all(np.isfinite(x)):
        raise ValueError("rank_ic_summary needs at least two finite ICs")
    sd = float(np.std(x, ddof=1))
    mean = float(np.mean(x))
    return {
        "n": int(x.size),
        "mean": mean,
        "sd": sd,
        "t_stat": mean / (sd / math.sqrt(x.size)) if sd > 0 else None,
        "share_positive": float(np.mean(x > 0)),
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
    "bootstrap_cluster_indices",
    "bootstrap_summary",
    "cluster_bootstrap_log_ratio",
    "cluster_bootstrap_mean",
    "daily_log_returns",
    "diagnostic_window_metrics",
    "directional_accuracy_end",
    "drift_baseline",
    "holm_adjust",
    "log_return",
    "mae",
    "mape",
    "mean_band_width",
    "per_bar_hit_rate",
    "predicted_daily_vol",
    "quantile_band",
    "quantile_band_reference_coverage",
    "rank_average",
    "rank_ic_summary",
    "sample_std",
    "sha256_of_tree",
    "sign_flip_permutation_test",
    "sma_flat_baseline",
    "spearman",
    "trailing_vol",
    "unchanged_baseline",
    "window_metrics",
]
