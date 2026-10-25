"""Prospective, read-only shadow forecasts. No candidate, risk or trading writes."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable
from datetime import date, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from signalforge.data.calendar import sessions
from signalforge.db.models import Instrument, OHLCVDaily
from signalforge.kronos.runtime import infer

WORKERS = 25
NOTICE = "Unvalidated shadow forecast. Research signal only — no order was placed."


def partition(symbol: str) -> int:
    return int(hashlib.sha256(symbol.encode()).hexdigest(), 16) % WORKERS


def inputs(session: Session, symbol: str, cutoff: date) -> list[dict[str, Any]]:
    """Only completed, continuous real equity/ETF bars; no invented cross-asset features."""
    instrument = session.scalar(select(Instrument).where(Instrument.symbol == symbol))
    if not instrument or instrument.instrument_type.lower() not in ("stock", "etf"):
        raise ValueError("unsupported instrument; only stocks/ETFs currently validated as inputs")
    rows = list(
        reversed(
            session.scalars(
                select(OHLCVDaily)
                .where(
                    OHLCVDaily.instrument_id == instrument.id,
                    OHLCVDaily.source == "massive",
                    OHLCVDaily.session_date <= cutoff,
                )
                .order_by(OHLCVDaily.session_date.desc())
                .limit(128)
            ).all()
        )
    )
    if len(rows) != 128 or rows[-1].session_date != cutoff:
        raise ValueError("insufficient or stale history")
    if (cutoff - rows[0].session_date).days > 730:
        raise ValueError("sparse history")
    if [r.session_date for r in rows] != list(sessions(rows[0].session_date, cutoff)):
        raise ValueError("missing or duplicated sessions")
    result = []
    for r in rows:
        values = [r.open, r.high, r.low, r.close, r.volume]
        if (
            r.is_simulated
            or not r.is_adjusted
            or r.quality_flags
            or not all(math.isfinite(x) and abs(x) <= 1e15 for x in values)
            or min(values[:4]) <= 0
            or r.volume < 0
            or not r.low <= min(r.open, r.close) <= max(r.open, r.close) <= r.high
        ):
            raise ValueError("unsuitable price history")
        result.append(
            {
                "date": r.session_date.isoformat(),
                "open": r.open,
                "high": r.high,
                "low": r.low,
                "close": r.close,
                "volume": r.volume,
            }
        )
    return result


def forecast(
    history: list[dict[str, Any]],
    symbol: str,
    horizon: int = 5,
    *,
    cancelled: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    if horizon not in (5, 20) or len(history) != 128:
        raise ValueError("unsupported dimensions")
    cutoff = date.fromisoformat(history[-1]["date"])
    future = [
        d.isoformat() for d in sessions(cutoff + timedelta(days=1), cutoff + timedelta(days=60))
    ][:horizon]
    if len(future) != horizon:
        raise ValueError("future calendar unavailable")
    paths = infer(history, future, cancelled=cancelled)
    if (
        len(paths) != 3
        or any(len(p) != horizon for p in paths)
        or any(not math.isfinite(x) or not 0 < x <= 1e15 for p in paths for x in p)
    ):
        raise ValueError("invalid forecast output")
    return {
        "symbol": symbol,
        "worker": partition(symbol),
        "input_end": str(cutoff),
        "input_hash": hashlib.sha256(json.dumps(history, sort_keys=True).encode()).hexdigest(),
        "horizon": horizon,
        "dates": future,
        "paths": paths,
        "unchanged_baseline": history[-1]["close"],
        "model": "NeoQuasar/Kronos-small",
        "probability_of_profit": None,
        "trade_approved": False,
        "notice": NOTICE,
    }
