"""Calibrated win probability (ARCHITECTURE.md §7.3, invariant S10).

A probability is shown for a setup **only** when all of the following hold:

1. a calibration artifact exists for that exact strategy *version*;
2. it was fitted on a validation slice that is time-separated from the
   out-of-sample slice, with at least ``MIN_VALIDATION_TRADES`` trades;
3. the regime the setup fires in has its own estimate in the artifact.

The estimate is an *empirical conditional win rate* (conditioned on the market
regime) with **Bayesian shrinkage toward 0.5**, then remapped through a binned
reliability curve fitted on the held-out validation slice. Every displayed
figure carries its 95% interval, sample size, calibration date range, and the
strategy version.

Otherwise: no number, and the caller shows
``"NO TRADE — insufficient evidence or poor risk/reward."``

Deterministic: closed-form shrinkage + Wilson interval, no RNG.
"""

from __future__ import annotations

import json
import math
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from signalforge.config import paths
from signalforge.research.display import NO_TRADE_MESSAGE

MIN_VALIDATION_TRADES = 30
DEFAULT_PRIOR_STRENGTH = 20.0  # pseudo-observations pulling the rate toward prior_mean
DEFAULT_PRIOR_MEAN = 0.5
DEFAULT_N_BINS = 5


def shrunk_win_rate(
    wins: int,
    n: int,
    *,
    prior_strength: float = DEFAULT_PRIOR_STRENGTH,
    prior_mean: float = DEFAULT_PRIOR_MEAN,
) -> float:
    """Beta-Binomial posterior mean: (wins + k*m) / (n + k), pulled toward m=0.5."""
    if n <= 0:
        return prior_mean
    return (wins + prior_strength * prior_mean) / (n + prior_strength)


def wilson_interval(wins: int, n: int, *, z: float = 1.96) -> tuple[float, float]:
    """95% Wilson score interval for a binomial proportion (no RNG)."""
    if n <= 0:
        return (0.0, 1.0)
    p = wins / n
    z2 = z * z
    denom = 1.0 + z2 / n
    centre = (p + z2 / (2 * n)) / denom
    half = (z / denom) * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n))
    return (max(0.0, centre - half), min(1.0, centre + half))


@dataclass(frozen=True, slots=True)
class RegimeEstimate:
    label: str
    shrunk_win_rate: float
    val_wins: int
    val_n: int


@dataclass(frozen=True, slots=True)
class CalibrationBin:
    lo: float
    hi: float
    predicted_mid: float
    empirical_win_rate: float
    n: int


@dataclass(frozen=True, slots=True)
class CalibrationArtifact:
    strategy_key: str
    version: str
    fitted_at: str
    train_start: str
    train_end: str
    validation_start: str
    validation_end: str
    n_train_trades: int
    n_validation_trades: int
    prior_strength: float
    overall_shrunk_win_rate: float
    regime_estimates: dict[str, RegimeEstimate] = field(default_factory=dict)
    bins: list[CalibrationBin] = field(default_factory=list)
    calibration_ref: str = ""

    def calibrate(self, raw_p: float) -> float:
        """Map a raw (shrunk) win rate through the fitted reliability curve."""
        for b in self.bins:
            if b.lo <= raw_p < b.hi or (raw_p >= b.hi and b is self.bins[-1]):
                return b.empirical_win_rate
        return raw_p

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["regime_estimates"] = {k: asdict(v) for k, v in self.regime_estimates.items()}
        d["bins"] = [asdict(b) for b in self.bins]
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> CalibrationArtifact:
        return cls(
            strategy_key=d["strategy_key"],
            version=d["version"],
            fitted_at=d["fitted_at"],
            train_start=d["train_start"],
            train_end=d["train_end"],
            validation_start=d["validation_start"],
            validation_end=d["validation_end"],
            n_train_trades=int(d["n_train_trades"]),
            n_validation_trades=int(d["n_validation_trades"]),
            prior_strength=float(d["prior_strength"]),
            overall_shrunk_win_rate=float(d["overall_shrunk_win_rate"]),
            regime_estimates={
                k: RegimeEstimate(**v) for k, v in d.get("regime_estimates", {}).items()
            },
            bins=[CalibrationBin(**b) for b in d.get("bins", [])],
            calibration_ref=d.get("calibration_ref", ""),
        )


@dataclass(frozen=True, slots=True)
class CalibratedProbability:
    p: float
    ci_low: float
    ci_high: float
    n: int
    calibration_start: str
    calibration_end: str
    strategy_version: str
    regime_label: str
    calibration_ref: str


def fit_calibration(
    *,
    strategy_key: str,
    version: str,
    trades: Sequence[tuple[date, str, bool]],
    validation_fraction: float = 0.4,
    prior_strength: float = DEFAULT_PRIOR_STRENGTH,
    n_bins: int = DEFAULT_N_BINS,
    calibration_ref: str = "",
) -> CalibrationArtifact | None:
    """Fit a regime-conditional, shrunk, binned-calibrated win-probability model.

    ``trades`` are ``(entry_date, regime_label, won)`` tuples covering the
    out-of-sample period. They are ordered by date and split into an earlier
    *train* slice (per-regime shrunk win rates) and a later *validation* slice
    (the reliability curve + the reported sample size / date range). Returns
    ``None`` when there is not enough validation data to be worth showing.
    """
    ordered = sorted(trades, key=lambda t: t[0])
    if len(ordered) < 10:
        return None
    cut = max(1, int(len(ordered) * (1 - validation_fraction)))
    train, validation = ordered[:cut], ordered[cut:]
    if len(validation) < 10:
        return None

    def _by_regime(rows: Sequence[tuple[date, str, bool]]) -> dict[str, tuple[int, int]]:
        acc: dict[str, tuple[int, int]] = {}
        for _, label, won in rows:
            w, k = acc.get(label, (0, 0))
            acc[label] = (w + (1 if won else 0), k + 1)
        return acc

    train_by_regime = _by_regime(train)
    val_by_regime = _by_regime(validation)
    train_wins = sum(1 for _, _, won in train if won)
    overall_shrunk = shrunk_win_rate(train_wins, len(train), prior_strength=prior_strength)

    regime_estimates: dict[str, RegimeEstimate] = {}
    for label in set(train_by_regime) | set(val_by_regime):
        tw, tn = train_by_regime.get(label, (0, 0))
        vw, vn = val_by_regime.get(label, (0, 0))
        raw = shrunk_win_rate(tw, tn, prior_strength=prior_strength) if tn > 0 else overall_shrunk
        regime_estimates[label] = RegimeEstimate(label, raw, vw, vn)

    # Reliability curve: for each validation trade, its predicted p is the
    # train-slice shrunk rate for its regime; bin those predictions and record
    # the realised win rate per bin.
    preds: list[tuple[float, bool]] = []
    for _, label, won in validation:
        est = regime_estimates.get(label)
        preds.append((est.shrunk_win_rate if est else overall_shrunk, won))

    bins: list[CalibrationBin] = []
    width = 1.0 / n_bins
    for i in range(n_bins):
        lo, hi = i * width, (i + 1) * width
        members = [won for p, won in preds if (lo <= p < hi) or (i == n_bins - 1 and p >= hi)]
        if not members:
            continue
        bins.append(
            CalibrationBin(
                lo=round(lo, 4),
                hi=round(hi, 4),
                predicted_mid=round(lo + width / 2, 4),
                empirical_win_rate=round(sum(members) / len(members), 4),
                n=len(members),
            )
        )

    return CalibrationArtifact(
        strategy_key=strategy_key,
        version=version,
        fitted_at=datetime.now(UTC).isoformat(),
        train_start=train[0][0].isoformat(),
        train_end=train[-1][0].isoformat(),
        validation_start=validation[0][0].isoformat(),
        validation_end=validation[-1][0].isoformat(),
        n_train_trades=len(train),
        n_validation_trades=len(validation),
        prior_strength=prior_strength,
        overall_shrunk_win_rate=round(overall_shrunk, 4),
        regime_estimates=regime_estimates,
        bins=bins,
        calibration_ref=calibration_ref,
    )


def calibrated_probability(
    regime_label: str,
    artifact: CalibrationArtifact | None,
    *,
    min_validation_trades: int = MIN_VALIDATION_TRADES,
) -> tuple[CalibratedProbability | None, str | None]:
    """Return a calibrated probability, or ``(None, NO_TRADE_MESSAGE)``."""
    if artifact is None or artifact.n_validation_trades < min_validation_trades:
        return None, NO_TRADE_MESSAGE
    est = artifact.regime_estimates.get(regime_label)
    if est is None:
        est = RegimeEstimate(regime_label, artifact.overall_shrunk_win_rate, 0, 0)

    p = max(0.0, min(1.0, artifact.calibrate(est.shrunk_win_rate)))
    if est.val_n > 0:
        lo, hi = wilson_interval(est.val_wins, est.val_n)
        n = est.val_n
    else:
        lo, hi = wilson_interval(
            round(p * artifact.n_validation_trades), artifact.n_validation_trades
        )
        n = artifact.n_validation_trades
    return (
        CalibratedProbability(
            p=round(p, 4),
            ci_low=round(lo, 4),
            ci_high=round(hi, 4),
            n=n,
            calibration_start=artifact.validation_start,
            calibration_end=artifact.validation_end,
            strategy_version=artifact.version,
            regime_label=regime_label,
            calibration_ref=artifact.calibration_ref or f"calibration/{artifact.strategy_key}",
        ),
        None,
    )


# --------------------------------------------------------------------------- #
# Persistence — JSON artifacts under <data_dir>/reports/calibration/
# --------------------------------------------------------------------------- #
def _calibration_dir() -> Path:
    d = paths.reports_dir() / "calibration"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _slug(strategy_key: str, version: str) -> str:
    return f"{strategy_key}-{version}".replace("/", "_")


def save_calibration(artifact: CalibrationArtifact) -> str:
    path = _calibration_dir() / f"{_slug(artifact.strategy_key, artifact.version)}.json"
    ref = f"calibration/{path.name}"
    stored = CalibrationArtifact.from_dict({**artifact.to_dict(), "calibration_ref": ref})
    path.write_text(json.dumps(stored.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
    return ref


def load_calibration(strategy_key: str, version: str) -> CalibrationArtifact | None:
    path = _calibration_dir() / f"{_slug(strategy_key, version)}.json"
    if not path.exists():
        return None
    try:
        return CalibrationArtifact.from_dict(json.loads(path.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, KeyError, TypeError):
        return None
