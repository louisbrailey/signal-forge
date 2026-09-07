"""Calibrated win probability: shrinkage, Wilson CI, validation-fit gate (S10)."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from signalforge.research.display import NO_TRADE_MESSAGE
from signalforge.research.probability import (
    MIN_VALIDATION_TRADES,
    CalibrationArtifact,
    calibrated_probability,
    fit_calibration,
    load_calibration,
    save_calibration,
    shrunk_win_rate,
    wilson_interval,
)


def test_shrinkage_pulls_toward_one_half() -> None:
    # 10/10 wins, prior of 20 pseudo-obs at 0.5 -> (10 + 10) / (10 + 20)
    assert shrunk_win_rate(10, 10, prior_strength=20.0) == 0.6666666666666666
    assert shrunk_win_rate(0, 0) == 0.5
    # more data -> closer to the raw rate
    assert shrunk_win_rate(80, 100) > shrunk_win_rate(8, 10)


def test_wilson_interval_brackets_and_is_bounded() -> None:
    lo, hi = wilson_interval(6, 10)
    assert 0.0 <= lo <= 0.6 <= hi <= 1.0
    wide_lo, wide_hi = wilson_interval(3, 5)
    tight_lo, tight_hi = wilson_interval(300, 500)
    assert (wide_hi - wide_lo) > (tight_hi - tight_lo)
    assert wilson_interval(0, 0) == (0.0, 1.0)


def _trades(n_bull_win: int, n_bull_loss: int, n_bear_win: int, n_bear_loss: int):
    d = date(2022, 1, 3)
    rows = []
    spec = [
        ("bull/low", True, n_bull_win),
        ("bull/low", False, n_bull_loss),
        ("bear/high", True, n_bear_win),
        ("bear/high", False, n_bear_loss),
    ]
    for label, won, count in spec:
        for _ in range(count):
            rows.append((d, label, won))
            d += timedelta(days=1)
    return rows


def test_fit_calibration_needs_enough_trades() -> None:
    assert fit_calibration(strategy_key="s", version="0.1.0", trades=_trades(2, 2, 1, 1)) is None


def test_fit_and_gate_round_trip(isolated_data_dir: Path) -> None:
    rows = _trades(40, 20, 15, 35)  # 110 trades; bull wins ~2/3, bear wins ~3/10
    art = fit_calibration(
        strategy_key="trend_continuation.short_swing", version="0.1.0", trades=rows
    )
    assert art is not None
    assert art.n_validation_trades >= MIN_VALIDATION_TRADES
    assert set(art.regime_estimates) == {"bull/low", "bear/high"}
    assert art.validation_start <= art.validation_end

    ref = save_calibration(art)
    assert ref.startswith("calibration/")
    reloaded = load_calibration("trend_continuation.short_swing", "0.1.0")
    assert isinstance(reloaded, CalibrationArtifact)
    assert reloaded.to_dict() == art.to_dict() | {"calibration_ref": reloaded.calibration_ref}

    prob, msg = calibrated_probability("bull/low", reloaded)
    assert msg is None and prob is not None
    assert 0.0 <= prob.ci_low <= prob.p <= prob.ci_high <= 1.0
    assert prob.n >= 1
    assert prob.strategy_version == "0.1.0"
    assert prob.calibration_start == reloaded.validation_start


def test_no_artifact_or_thin_validation_yields_no_trade(isolated_data_dir: Path) -> None:
    assert calibrated_probability("bull/low", None) == (None, NO_TRADE_MESSAGE)

    thin = fit_calibration(strategy_key="s", version="0.1.0", trades=_trades(6, 6, 6, 6))
    # 48 trades -> validation slice ~19, below the MIN_VALIDATION_TRADES gate
    assert thin is not None
    p, m = calibrated_probability("bull/low", thin)
    assert p is None and m == NO_TRADE_MESSAGE
