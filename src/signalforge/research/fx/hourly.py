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


def run_crypto_hourly_research(
    session: Session,
    pairs: Sequence[str],
    *,
    gates: FxGates | None = None,
    strategies: Sequence[FxStrategy] = CRYPTO_H1_STRATEGIES,
) -> dict[str, Any]:
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
    return {
        "market": "Crypto (hourly)",
        "version": CRYPTO_H1_VERSION,
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
