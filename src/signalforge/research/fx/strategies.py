"""Pre-registered daily FX strategies (version FX-1).

Three classic, low-parameter rules chosen BEFORE any FX result was seen, with
fixed parameters. Changing any parameter is a new version, never a tune: the
evaluation counts every (strategy, pair) test it runs so the multiple-testing
burden is visible.

Each rule sees only ``series.head(t)`` (enforced by the engine) and returns an
``EntrySignal`` with a mandatory stop; the engine fills at the next open.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

from signalforge.backtest.engine import EntrySignal
from signalforge.data.series import PriceSeries
from signalforge.domain import Direction

FX_STRATEGY_VERSION = "FX-1"


def atr(series: PriceSeries, n: int) -> float:
    """Average true range over the last ``n`` bars ending at the last bar."""
    if len(series) < n + 1:
        return float("nan")
    h, lo, c = series.high[-n:], series.low[-n:], series.close[-n - 1 : -1]
    tr = np.maximum(h - lo, np.maximum(np.abs(h - c), np.abs(lo - c)))
    return float(tr.mean())


@dataclass(frozen=True, slots=True)
class FxStrategy:
    key: str
    description: str
    params: dict[str, float]
    warmup: int
    signal: Callable[[PriceSeries, int], EntrySignal | None]


# --- 1. Donchian channel breakout (trend) ---------------------------------- #
_DON_N, _DON_ATR_N, _DON_STOP_ATR, _DON_TIME = 55, 20, 2.0, 40


def _donchian(series: PriceSeries, t: int) -> EntrySignal | None:
    if len(series) < _DON_N + 2:
        return None
    c = float(series.close[-1])
    prior_hi = float(series.high[-_DON_N - 1 : -1].max())
    prior_lo = float(series.low[-_DON_N - 1 : -1].min())
    a = atr(series, _DON_ATR_N)
    if not np.isfinite(a) or a <= 0:
        return None
    if c > prior_hi:
        return EntrySignal(Direction.LONG, c - _DON_STOP_ATR * a, _DON_TIME, reason="55d high")
    if c < prior_lo:
        return EntrySignal(Direction.SHORT, c + _DON_STOP_ATR * a, _DON_TIME, reason="55d low")
    return None


# --- 2. Time-series momentum with MA pullback re-entry --------------------- #
_MOM_LOOKBACK, _MOM_MA, _MOM_ATR_N, _MOM_STOP_ATR, _MOM_TIME = 126, 50, 20, 3.0, 20


def _tsmom(series: PriceSeries, t: int) -> EntrySignal | None:
    if len(series) < _MOM_LOOKBACK + 2:
        return None
    c, prev = float(series.close[-1]), float(series.close[-2])
    ma, ma_prev = float(series.close[-_MOM_MA:].mean()), float(
        series.close[-_MOM_MA - 1 : -1].mean()
    )
    mom = c / float(series.close[-_MOM_LOOKBACK - 1]) - 1.0
    a = atr(series, _MOM_ATR_N)
    if not np.isfinite(a) or a <= 0:
        return None
    # enter only on the cross of the MA in the direction of 6-month momentum
    if mom > 0 and prev <= ma_prev and c > ma:
        return EntrySignal(Direction.LONG, c - _MOM_STOP_ATR * a, _MOM_TIME, reason="mom+ MA cross")
    if mom < 0 and prev >= ma_prev and c < ma:
        return EntrySignal(
            Direction.SHORT, c + _MOM_STOP_ATR * a, _MOM_TIME, reason="mom- MA cross"
        )
    return None


# --- 3. Short-horizon mean reversion (z-score fade) ------------------------ #
_MR_N, _MR_Z, _MR_ATR_N, _MR_STOP_ATR, _MR_TIME = 20, 2.0, 20, 1.5, 5


def _zfade(series: PriceSeries, t: int) -> EntrySignal | None:
    if len(series) < _MR_N + 2:
        return None
    win = series.close[-_MR_N:]
    mu, sd = float(win.mean()), float(win.std(ddof=1))
    if sd <= 0:
        return None
    c = float(series.close[-1])
    z = (c - mu) / sd
    a = atr(series, _MR_ATR_N)
    if not np.isfinite(a) or a <= 0:
        return None
    if z <= -_MR_Z:
        return EntrySignal(
            Direction.LONG, c - _MR_STOP_ATR * a, _MR_TIME, target_price=mu, reason="z<=-2"
        )
    if z >= _MR_Z:
        return EntrySignal(
            Direction.SHORT, c + _MR_STOP_ATR * a, _MR_TIME, target_price=mu, reason="z>=2"
        )
    return None


FX_STRATEGIES: tuple[FxStrategy, ...] = (
    FxStrategy(
        "fx_donchian_55",
        "Close beyond the prior 55-day high/low; 2xATR(20) stop; 40-bar time stop.",
        {"channel": _DON_N, "atr_n": _DON_ATR_N, "stop_atr": _DON_STOP_ATR, "time": _DON_TIME},
        warmup=_DON_N + 2,
        signal=_donchian,
    ),
    FxStrategy(
        "fx_tsmom_126_ma50",
        "Close crosses the 50-day MA in the direction of 126-day return; "
        "3xATR(20) stop; 20-bar time stop.",
        {
            "lookback": _MOM_LOOKBACK,
            "ma": _MOM_MA,
            "atr_n": _MOM_ATR_N,
            "stop_atr": _MOM_STOP_ATR,
            "time": _MOM_TIME,
        },
        warmup=_MOM_LOOKBACK + 2,
        signal=_tsmom,
    ),
    FxStrategy(
        "fx_zfade_20",
        "Fade a close 2 standard deviations from its 20-day mean; target the mean; "
        "1.5xATR(20) stop; 5-bar time stop.",
        {
            "window": _MR_N,
            "z": _MR_Z,
            "atr_n": _MR_ATR_N,
            "stop_atr": _MR_STOP_ATR,
            "time": _MR_TIME,
        },
        warmup=_MR_N + 2,
        signal=_zfade,
    ),
)
