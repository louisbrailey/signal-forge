"""Read-only persisted-data replay API. Call from a dashboard worker thread."""

from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from signalforge.data.calendar import sessions as xnys_sessions
from signalforge.db.models.market import Instrument, OHLCVDaily

from .runtime import KronosError, KronosUnavailable, infer
from .runtime import runtime_status as _runtime_status

LOOKBACK = 128
MODEL = "NeoQuasar/Kronos-small"
NOTICE = (
    "Historical replay only, not advice or a trading instruction. Pretraining overlap is unknown; "
    "this is not verified out-of-sample model evaluation. Sampling spread is not a calibrated "
    "confidence interval. Price MAE is not investment performance and excludes costs. "
    "Persisted adjusted history may include later vendor revisions and corporate actions."
)


def runtime_status() -> dict[str, Any]:
    """Configuration check only; does not load weights, query data, or run inference."""
    return dict(
        _runtime_status(),
        model=MODEL,
        mode="historical_replay",
        lookback=LOOKBACK,
        horizons=[5, 20],
        notice=NOTICE,
    )


def replay(
    session: Session, symbol: str, horizon: int = 5, *, as_of: date | None = None
) -> dict[str, Any]:
    """Replay latest 128+horizon completed stored sessions at/before as_of.

    Does not flush, commit, fetch, persist a result, or mutate settings. Missing/flagged
    history fails closed. Route owns authentication, kill-switch gating and scheduling.
    """
    ticker = symbol
    if not isinstance(ticker, str) or not re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,14}", ticker):
        raise ValueError("Invalid ticker")
    if type(horizon) is not int or horizon not in (5, 20):
        raise ValueError("Horizon must be 5 or 20")
    today = datetime.now(UTC).date()
    if as_of is not None and (type(as_of) is not date or as_of >= today):
        raise ValueError("as_of must be a past session date")
    query = (
        select(OHLCVDaily)
        .join(Instrument)
        .where(
            Instrument.symbol == ticker,
            OHLCVDaily.source == "massive",
            OHLCVDaily.session_date < today,
        )
        .order_by(OHLCVDaily.session_date.desc())
        .limit(LOOKBACK + horizon)
    )
    if as_of is not None:
        query = query.where(OHLCVDaily.session_date <= as_of)
    try:
        with session.no_autoflush:
            rows = list(reversed(session.scalars(query).all()))
    except SQLAlchemyError:
        raise KronosUnavailable("Persisted daily history is unavailable") from None
    if len(rows) != LOOKBACK + horizon:
        raise KronosError("Insufficient persisted Massive daily history")
    bars: list[dict[str, Any]] = []
    for row in rows:
        values = [row.open, row.high, row.low, row.close, row.volume]
        if (
            row.is_simulated
            or not row.is_adjusted
            or row.quality_flags
            or any(not math.isfinite(v) or abs(v) > 1e15 for v in values)
            or min(values[:4]) <= 0
            or row.volume < 0
            or not row.low <= min(row.open, row.close) <= max(row.open, row.close) <= row.high
        ):
            raise KronosError("Persisted history contains unsuitable daily bars")
        bars.append(
            {
                "date": row.session_date.isoformat(),
                "open": row.open,
                "high": row.high,
                "low": row.low,
                "close": row.close,
                "volume": row.volume,
            }
        )
    dates = [b["date"] for b in bars]
    if len(set(dates)) != len(dates) or dates != sorted(dates):
        raise KronosError("Daily dates must be unique and increasing")
    # Bound calendar work even for corrupt or extremely sparse persisted history.
    if (rows[-1].session_date - rows[0].session_date).days > 730:
        raise KronosUnavailable("Daily history is not a continuous XNYS window")
    try:
        expected = [
            d.isoformat() for d in xnys_sessions(rows[0].session_date, rows[-1].session_date)
        ]
    except Exception:
        raise KronosUnavailable("XNYS session calendar is unavailable") from None
    if dates != expected:
        raise KronosUnavailable("Daily history has missing or non-XNYS sessions")
    history, actual = bars[:LOOKBACK], bars[LOOKBACK:]
    # Only held-out calendar labels cross the inference boundary, never their OHLCV.
    paths = infer(history, [b["date"] for b in actual])
    if (
        not isinstance(paths, list)
        or len(paths) != 3
        or any(not isinstance(p, list) or len(p) != horizon for p in paths)
        or any(
            type(v) not in (int, float) or not math.isfinite(v) or not 0 < v <= 1e15
            for p in paths
            for v in p
        )
    ):
        raise KronosError("Invalid model output")
    points: list[dict[str, Any]] = []
    for i, bar in enumerate(actual):
        values = [p[i] for p in paths]
        points.append(
            {
                "date": bar["date"],
                "actual": bar["close"],
                "predicted": sum(values) / 3,
                "low": min(values),
                "high": max(values),
                "baseline": history[-1]["close"],
            }
        )
    provenance = [
        {
            "date": r.session_date.isoformat(),
            "source": r.source,
            "latency_category": str(r.latency_category),
            "ingested_at": r.ingested_at.isoformat(),
            "is_simulated": r.is_simulated,
            "is_adjusted": r.is_adjusted,
        }
        for r in rows
    ]
    digest = hashlib.sha256(
        json.dumps(
            {"ticker": ticker, "bars": bars, "model": MODEL, "seed": 42}, sort_keys=True
        ).encode()
    ).hexdigest()
    return {
        "id": digest,
        "ticker": ticker,
        "model": MODEL,
        "mode": "historical_replay",
        "source": "Persisted Massive split-adjusted daily OHLCV (not dividend-adjusted)",
        "bar_size": "1d",
        "calendar": "XNYS",
        "latency_category": "HISTORICAL",
        "data_label": "Historical replay of completed daily bars; not a live feed",
        "source_latency_categories": sorted({str(r.latency_category) for r in rows}),
        "generated_at": datetime.now(UTC).isoformat(),
        "input_start": dates[0],
        "input_end": dates[LOOKBACK - 1],
        "heldout_start": dates[LOOKBACK],
        "heldout_end": dates[-1],
        "lookback": LOOKBACK,
        "horizon": horizon,
        "samples": 3,
        "seed": 42,
        "dates": [p["date"] for p in points],
        "actual": [p["actual"] for p in points],
        "predicted": [p["predicted"] for p in points],
        "baseline": [p["baseline"] for p in points],
        "lower": [p["low"] for p in points],
        "upper": [p["high"] for p in points],
        "notice": NOTICE,
        "pretraining_overlap": "unknown",
        "provenance": provenance,
        "history": history,
        "points": points,
        "mae": sum(abs(p["predicted"] - p["actual"]) for p in points) / horizon,
        "baseline_mae": sum(abs(p["baseline"] - p["actual"]) for p in points) / horizon,
    }


status = runtime_status
__all__ = ["KronosError", "KronosUnavailable", "replay", "runtime_status", "status"]
