"""CRYPTO-H1: pre-registered hourly, round-the-clock crypto rules.

Pre-registration: ``docs/research/PREREGISTRATION_CRYPTO-H1_2026-10-27.md``.
Bars are hours (``crypto_bar_intraday``). The series' ``dates`` are timezone-aware
UTC datetimes, which the walk-forward, metrics and sealed-window helpers handle
unchanged (all arithmetic is via ``timedelta``). Costs and gates are CRYPTO-1's.
Research only: nothing here can reach paper, alerts or execution (contract S17).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict
from datetime import UTC
from typing import Any

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from signalforge.backtest.engine import EntrySignal
from signalforge.data.series import PriceSeries
from signalforge.db.models import CryptoBarIntraday
from signalforge.domain import Direction
from signalforge.research.fx.harness import (
    CRYPTO_MARKET,
    FxGates,
    evaluate_strategy,
    sealed_start,
)
from signalforge.research.fx.strategies import FxStrategy, atr

CRYPTO_H1_VERSION = "CRYPTO-H1"
# Refinement round 1 (pre-registered 2026-11-02, PREREGISTRATION_universe_program §7.3):
# the SAME three hourly rules on a 6-pair universe. A different universe is a
# different version, so its report and any future sealed look carry their own label.
CRYPTO_H2_VERSION = "CRYPTO-H2"
# Round 2 hourly variants pre-registered 2026-11-03 in
# PREREGISTRATION_round2_hourly_H4_2026-11-03.md: the baseline hourly Donchian plus two
# declared variants (120h trail; ATR(24)>=ATR(168) entry filter) on zero-gap pairs.
# "CRYPTO-H3" is reserved by PREREGISTRATION_round2_2026-11-03.md for a different family.
CRYPTO_H4_VERSION = "CRYPTO-H4"
# CRYPTO-H3: the two NEW hourly rules of PREREGISTRATION_round2_2026-11-03.md R2-H
# (quiet-tape filter; two-week channel). The H1 baseline is NOT part of this set.
CRYPTO_H3_VERSION = "CRYPTO-H3"
HOURLY_VERSIONS = (CRYPTO_H1_VERSION, CRYPTO_H2_VERSION, CRYPTO_H3_VERSION, CRYPTO_H4_VERSION)
SOURCE = "massive_crypto"
BAR_SIZE = "1h"


def load_hourly_series(session: Session, pair: str) -> PriceSeries:
    rows = session.execute(
        select(
            CryptoBarIntraday.bar_start,
            CryptoBarIntraday.open,
            CryptoBarIntraday.high,
            CryptoBarIntraday.low,
            CryptoBarIntraday.close,
        )
        .where(
            CryptoBarIntraday.pair == pair,
            CryptoBarIntraday.bar_size == BAR_SIZE,
            CryptoBarIntraday.source == SOURCE,
        )
        .order_by(CryptoBarIntraday.bar_start)
    ).all()
    return PriceSeries.from_bars(
        pair,
        [(t if t.tzinfo else t.replace(tzinfo=UTC), o, h, lo, c, 0.0) for t, o, h, lo, c in rows],
    )


# --- 1. 168h Donchian breakout, 72h trailing exit ----------------------------- #
_DON_N, _DON_ATR, _DON_STOP, _DON_TRAIL, _DON_SAFETY = 168, 24, 2.0, 72, 720


def _h_donchian(series: PriceSeries, t: int) -> EntrySignal | None:
    if len(series) < _DON_N + 2:
        return None
    c = float(series.close[-1])
    hi = float(series.high[-_DON_N - 1 : -1].max())
    lo = float(series.low[-_DON_N - 1 : -1].min())
    a = atr(series, _DON_ATR)
    if not np.isfinite(a) or a <= 0:
        return None
    if c > hi:
        return EntrySignal(Direction.LONG, c - _DON_STOP * a, _DON_SAFETY, reason="168h high")
    if c < lo:
        return EntrySignal(Direction.SHORT, c + _DON_STOP * a, _DON_SAFETY, reason="168h low")
    return None


# --- 2. 72h momentum, SMA(168) cross ----------------------------------------- #
_MOM_LB, _MOM_MA, _MOM_ATR, _MOM_STOP, _MOM_TIME = 72, 168, 24, 3.0, 48


def _h_tsmom(series: PriceSeries, t: int) -> EntrySignal | None:
    if len(series) < _MOM_MA + 2:
        return None
    c, prev = float(series.close[-1]), float(series.close[-2])
    ma = float(series.close[-_MOM_MA:].mean())
    ma_prev = float(series.close[-_MOM_MA - 1 : -1].mean())
    mom = c / float(series.close[-_MOM_LB - 1]) - 1.0
    a = atr(series, _MOM_ATR)
    if not np.isfinite(a) or a <= 0:
        return None
    if mom > 0 and prev <= ma_prev and c > ma:
        return EntrySignal(Direction.LONG, c - _MOM_STOP * a, _MOM_TIME, reason="72h mom+ cross")
    if mom < 0 and prev >= ma_prev and c < ma:
        return EntrySignal(Direction.SHORT, c + _MOM_STOP * a, _MOM_TIME, reason="72h mom- cross")
    return None


# --- 3. 48h z-score fade ------------------------------------------------------ #
_MR_N, _MR_Z, _MR_ATR, _MR_STOP, _MR_TIME = 48, 2.5, 24, 1.5, 12


def _h_zfade(series: PriceSeries, t: int) -> EntrySignal | None:
    if len(series) < _MR_N + 2:
        return None
    win = series.close[-_MR_N:]
    mu, sd = float(win.mean()), float(win.std(ddof=1))
    if sd <= 0:
        return None
    c = float(series.close[-1])
    z = (c - mu) / sd
    a = atr(series, _MR_ATR)
    if not np.isfinite(a) or a <= 0:
        return None
    if z <= -_MR_Z:
        return EntrySignal(
            Direction.LONG, c - _MR_STOP * a, _MR_TIME, target_price=mu, reason="z<=-2.5"
        )
    if z >= _MR_Z:
        return EntrySignal(
            Direction.SHORT, c + _MR_STOP * a, _MR_TIME, target_price=mu, reason="z>=2.5"
        )
    return None


CRYPTO_H1_STRATEGIES: tuple[FxStrategy, ...] = (
    FxStrategy(
        "crypto_h_donchian168_trail72",
        "Close beyond the prior 168h high/low; 2xATR(24) stop; exit on a close back through the "
        "prior 72h channel; 720h safety stop.",
        {
            "channel": _DON_N,
            "atr_n": _DON_ATR,
            "stop_atr": _DON_STOP,
            "trail": _DON_TRAIL,
            "safety_time": _DON_SAFETY,
        },
        warmup=_DON_N + 2,
        signal=_h_donchian,
        trail_channel=_DON_TRAIL,
    ),
    FxStrategy(
        "crypto_h_tsmom72_sma168",
        "Close crosses SMA(168) in the direction of the 72h return; 3xATR(24) stop; 48h time stop.",
        {
            "lookback": _MOM_LB,
            "ma": _MOM_MA,
            "atr_n": _MOM_ATR,
            "stop_atr": _MOM_STOP,
            "time": _MOM_TIME,
        },
        warmup=_MOM_MA + 2,
        signal=_h_tsmom,
    ),
    FxStrategy(
        "crypto_h_zfade48",
        "Fade a close 2.5 standard deviations from its 48h mean; target the mean; 1.5xATR(24) "
        "stop; 12h time stop.",
        {"window": _MR_N, "z": _MR_Z, "atr_n": _MR_ATR, "stop_atr": _MR_STOP, "time": _MR_TIME},
        warmup=_MR_N + 2,
        signal=_h_zfade,
    ),
)


# --- CRYPTO-H4 variants (pre-registered 2026-11-03) ------------------------- #
_DON_TRAIL_LONG = 120  # 5-day exit channel instead of 72h
_VOLX_FAST, _VOLX_SLOW = 24, 168  # enter only when ATR(24) >= ATR(168)


def _h_donchian_trail120(series: PriceSeries, t: int) -> EntrySignal | None:
    return _h_donchian(series, t)  # same entry/stop; the harness applies trail_channel=120


def _h_donchian_volx(series: PriceSeries, t: int) -> EntrySignal | None:
    sig = _h_donchian(series, t)
    if sig is None:
        return None
    fast, slow = atr(series, _VOLX_FAST), atr(series, _VOLX_SLOW)
    if not (np.isfinite(fast) and np.isfinite(slow)) or slow <= 0 or fast < slow:
        return None
    return EntrySignal(
        sig.direction, sig.stop_price, sig.time_stop_bars, reason=sig.reason + "; ATR24>=ATR168"
    )


CRYPTO_H4_STRATEGIES: tuple[FxStrategy, ...] = (
    CRYPTO_H1_STRATEGIES[0],  # unchanged baseline, look #4 for this rule (disclosed)
    FxStrategy(
        "crypto_h_donchian168_trail120",
        "Close beyond the prior 168h high/low; 2xATR(24) stop; exit on a close back through the "
        "prior 120h channel; 720h safety stop.",
        {
            "channel": _DON_N,
            "atr_n": _DON_ATR,
            "stop_atr": _DON_STOP,
            "trail": _DON_TRAIL_LONG,
            "safety_time": _DON_SAFETY,
        },
        warmup=_DON_N + 2,
        signal=_h_donchian_trail120,
        trail_channel=_DON_TRAIL_LONG,
    ),
    FxStrategy(
        "crypto_h_donchian168_trail72_volx",
        "Baseline 168h Donchian entry only when ATR(24) >= ATR(168); 2xATR(24) stop; exit on a "
        "close back through the prior 72h channel; 720h safety stop.",
        {
            "channel": _DON_N,
            "atr_n": _DON_ATR,
            "stop_atr": _DON_STOP,
            "trail": _DON_TRAIL,
            "safety_time": _DON_SAFETY,
            "vol_fast": _VOLX_FAST,
            "vol_slow": _VOLX_SLOW,
        },
        warmup=_VOLX_SLOW + 2,
        signal=_h_donchian_volx,
        trail_channel=_DON_TRAIL,
    ),
)
# --- CRYPTO-H3 rules (pre-registered 2026-11-03 by the concurrent session, R2-H) --- #
_QUIET_ATR, _QUIET_LOOKBACK = 24, 240  # ATR(24)/close at or below its median over the prior 240h
_WIDE_N, _WIDE_TRAIL, _WIDE_SAFETY = 336, 168, 1440


def _atr_over_close_history(series: PriceSeries, n: int, lookback: int) -> np.ndarray | None:
    """ATR(n)/close for each of the ``lookback`` bars BEFORE the last bar (the
    signal bar itself excluded), computed from true ranges only — no future bar."""
    need = lookback + n + 1
    if len(series) < need + 1:
        return None
    h = series.high[-need - 1 : -1]
    lo = series.low[-need - 1 : -1]
    c_prev = series.close[-need - 2 : -2]
    c = series.close[-need - 1 : -1]
    tr = np.maximum(h - lo, np.maximum(np.abs(h - c_prev), np.abs(lo - c_prev)))
    atr_series = np.convolve(tr, np.ones(n) / n, mode="valid")  # ATR ending at each bar
    closes = c[n - 1 :]
    ratio = atr_series / closes
    return ratio[-lookback:]


def _h_donchian_quiet(series: PriceSeries, t: int) -> EntrySignal | None:
    sig = _h_donchian(series, t)
    if sig is None:
        return None
    hist = _atr_over_close_history(series, _QUIET_ATR, _QUIET_LOOKBACK)
    a = atr(series, _QUIET_ATR)
    c = float(series.close[-1])
    if hist is None or not np.isfinite(a) or c <= 0:
        return None
    if a / c <= float(np.median(hist)):
        return EntrySignal(
            sig.direction, sig.stop_price, sig.time_stop_bars, reason=sig.reason + "; quiet tape"
        )
    return None


def _h_donchian_wide(series: PriceSeries, t: int) -> EntrySignal | None:
    if len(series) < _WIDE_N + 2:
        return None
    c = float(series.close[-1])
    hi = float(series.high[-_WIDE_N - 1 : -1].max())
    lo = float(series.low[-_WIDE_N - 1 : -1].min())
    a = atr(series, _DON_ATR)
    if not np.isfinite(a) or a <= 0:
        return None
    if c > hi:
        return EntrySignal(Direction.LONG, c - _DON_STOP * a, _WIDE_SAFETY, reason="336h high")
    if c < lo:
        return EntrySignal(Direction.SHORT, c + _DON_STOP * a, _WIDE_SAFETY, reason="336h low")
    return None


CRYPTO_H3_STRATEGIES: tuple[FxStrategy, ...] = (
    FxStrategy(
        "crypto_h_donchian168_trail72_quiet",
        "Close beyond the prior 168h high/low only when ATR(24)/close is at or below its median "
        "over the prior 240h; 2xATR(24) stop; exit on a close back through the prior 72h channel; "
        "720h safety stop.",
        {
            "channel": _DON_N,
            "atr_n": _DON_ATR,
            "stop_atr": _DON_STOP,
            "trail": _DON_TRAIL,
            "safety_time": _DON_SAFETY,
            "quiet_lookback": _QUIET_LOOKBACK,
        },
        warmup=_QUIET_LOOKBACK + _QUIET_ATR + 3,
        signal=_h_donchian_quiet,
        trail_channel=_DON_TRAIL,
    ),
    FxStrategy(
        "crypto_h_donchian336_trail168",
        "Close beyond the prior 336h high/low; 2xATR(24) stop; exit on a close back through the "
        "prior 168h channel; 1440h safety stop.",
        {
            "channel": _WIDE_N,
            "atr_n": _DON_ATR,
            "stop_atr": _DON_STOP,
            "trail": _WIDE_TRAIL,
            "safety_time": _WIDE_SAFETY,
        },
        warmup=_WIDE_N + 2,
        signal=_h_donchian_wide,
        trail_channel=_WIDE_TRAIL,
    ),
)
HOURLY_STRATEGIES: dict[str, tuple[FxStrategy, ...]] = {
    CRYPTO_H1_VERSION: CRYPTO_H1_STRATEGIES,
    CRYPTO_H2_VERSION: CRYPTO_H1_STRATEGIES,
    CRYPTO_H3_VERSION: CRYPTO_H3_STRATEGIES,
    CRYPTO_H4_VERSION: CRYPTO_H4_STRATEGIES,
}


def run_crypto_hourly_research(
    session: Session,
    pairs: Sequence[str],
    *,
    gates: FxGates | None = None,
    strategies: Sequence[FxStrategy] | None = None,
    version: str = CRYPTO_H1_VERSION,
) -> dict[str, Any]:
    if version not in HOURLY_VERSIONS:
        raise ValueError(f"unknown hourly version {version!r}; expected one of {HOURLY_VERSIONS}")
    strategies = strategies if strategies is not None else HOURLY_STRATEGIES[version]
    gates = gates or FxGates()
    series_by_pair = {p: load_hourly_series(session, p) for p in pairs}
    series_by_pair = {p: s for p, s in series_by_pair.items() if len(s)}
    if not series_by_pair:
        raise ValueError(
            "no hourly crypto history for the requested pairs; run crypto-hourly-ingest"
        )
    seal_from = sealed_start(series_by_pair, gates.sealed_days)
    results = [
        evaluate_strategy(s, series_by_pair, seal_from=seal_from, gates=gates, market=CRYPTO_MARKET)
        for s in strategies
    ]
    absent = sorted(set(pairs) - set(series_by_pair))
    if absent:
        for result in results:
            result.reasons.append(f"data availability: no history for requested pairs {absent}")
            result.verdict = "DEV_FAIL"
    return {
        "market": "Crypto (hourly)",
        "version": version,
        "gates": asdict(gates),
        "spread_bps": {p: CRYPTO_MARKET.spread(p) for p in series_by_pair},
        "history": {
            p: {"first": s.dates[0].isoformat(), "last": s.dates[-1].isoformat(), "bars": len(s)}
            for p, s in sorted(series_by_pair.items())
        },
        "sealed_from": seal_from.isoformat(),
        "tests_run": len(strategies) * len(series_by_pair),
        "strategies": [asdict(r) for r in results],
        "notice": (
            "Development-window research only. Sealed final year not evaluated. Spot-style "
            "costs; no funding or exchange risk modelled. No order was placed."
        ),
    }
