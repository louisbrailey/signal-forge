"""Market-regime labelling for segmenting backtest results.

A per-session label derived from a broad-market proxy series (SPY by default):
* trend:      bull / bear      — 200-session SMA slope
* volatility: highvol / lowvol — 20-session realised vol vs its trailing median
* range:      range_bound      — price inside a tight band around the SMA

Segmentation uses the label on each trade's *entry* date so there is no
look-ahead into how the regime later evolved.
"""

from __future__ import annotations

from datetime import date

import numpy as np

from signalforge.data.series import PriceSeries

TREND_LOOKBACK = 200
VOL_LOOKBACK = 20
RANGE_BAND = 0.03  # +/- 3% of the SMA


def label_regimes(proxy: PriceSeries) -> dict[date, str]:
    close = proxy.close
    n = len(close)
    out: dict[date, str] = {}
    if n == 0:
        return out

    logret = np.zeros(n)
    logret[1:] = np.diff(np.log(np.maximum(close, 1e-9)))

    for i in range(n):
        if i < TREND_LOOKBACK:
            out[proxy.dates[i]] = "warmup"
            continue
        sma_now = float(close[i - TREND_LOOKBACK + 1 : i + 1].mean())
        sma_prev = float(close[i - TREND_LOOKBACK : i].mean())
        trend = "bull" if sma_now >= sma_prev else "bear"

        window_vol = float(np.std(logret[i - VOL_LOOKBACK + 1 : i + 1]))
        hist = logret[max(0, i - 252) : i + 1]
        med_vol = (
            float(
                np.median(
                    [
                        np.std(hist[j : j + VOL_LOOKBACK])
                        for j in range(0, max(1, len(hist) - VOL_LOOKBACK), 5)
                    ]
                )
            )
            if len(hist) > VOL_LOOKBACK
            else window_vol
        )
        vol = "highvol" if window_vol > med_vol else "lowvol"

        if abs(close[i] - sma_now) / sma_now <= RANGE_BAND:
            out[proxy.dates[i]] = "range_bound"
        else:
            out[proxy.dates[i]] = f"{trend}_{vol}"
    return out


def segment_key(label: str) -> list[str]:
    """Map a compound label to the coarse segments used in reports."""
    segs = ["all"]
    if label.startswith("bull"):
        segs.append("bull")
    elif label.startswith("bear"):
        segs.append("bear")
    if label.endswith("highvol"):
        segs.append("highvol")
    elif label.endswith("lowvol"):
        segs.append("lowvol")
    if label == "range_bound":
        segs.append("range")
    return segs
