"""Bounded cross-asset context. Never an input to trading or risk decisions."""

from __future__ import annotations

import hashlib
import json
import math
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from signalforge.config import get_settings
from signalforge.data.entitlements import _classify, _get
from signalforge.db.models import RawPayloadCache
from signalforge.db.session import session_scope
from signalforge.killswitch import ensure_not_engaged

PROVIDER = "massive_context"
SYMBOLS = ("C:EURUSD", "C:USDJPY", "C:XAUUSD", "I:SPX", "I:VIX", "ESZ6")
MAX_BYTES = 65536


def normalize(body: dict[str, Any]) -> list[dict[str, Any]]:
    """Reject malformed/duplicate/out-of-order bars; no invented volume for indices."""
    rows = body.get("results", [])
    if isinstance(rows, list) and rows and "window_start" in rows[0]:
        rows = [
            {
                "t": r["window_start"] / 1_000_000,
                **{
                    k: r[v] for k, v in (("o", "open"), ("h", "high"), ("l", "low"), ("c", "close"))
                },
            }
            for r in rows
        ]
    if not isinstance(rows, list) or len(rows) > 10:
        raise ValueError("invalid bar count")
    result = []
    previous = -1.0
    for bar in rows:
        values = [float(bar[k]) for k in ("t", "o", "h", "l", "c")]
        t, o, h, lo, c = values
        if not all(math.isfinite(x) for x in values) or t <= previous:
            raise ValueError("invalid timestamp/order")
        if min(o, h, lo, c) <= 0 or not lo <= min(o, c) <= max(o, c) <= h:
            raise ValueError("invalid OHLC")
        previous = t
        result.append({"timestamp": datetime.fromtimestamp(t / 1000, UTC).isoformat(), "close": c})
    return result


def refresh() -> int:
    """At most six small requests per UTC day; bounded audit storage (one row/feed/day)."""
    ensure_not_engaged()
    key = get_settings().market_data_api_key.get_secret_value()
    if not key:
        raise ValueError("MARKET_DATA_API_KEY is not set")
    now = datetime.now(UTC)
    start, end = (now - timedelta(days=7)).date(), (now - timedelta(days=1)).date()
    written = 0
    requested = False
    with httpx.Client() as client:
        for symbol in SYMBOLS:
            ensure_not_engaged()
            endpoint = f"/v2/aggs/ticker/{symbol}/range/1/day/{start}/{end}"
            if symbol == "ESZ6":
                endpoint = "/futures/v1/aggs/ESZ6"
            digest = hashlib.sha256(f"{now.date()}:{endpoint}".encode()).hexdigest()
            with session_scope() as reader:
                exists = reader.scalar(
                    select(RawPayloadCache.id).where(
                        RawPayloadCache.provider == PROVIDER, RawPayloadCache.request_hash == digest
                    )
                )
            if exists:
                continue
            if requested:
                for _ in range(121):
                    ensure_not_engaged()
                    time.sleep(0.1)
            requested = True
            query = (
                "?resolution=1session&limit=5&sort=window_start.asc"
                f"&window_start.gte={start}&window_start.lte={end}"
                if symbol == "ESZ6"
                else "?sort=asc&limit=10"
            )
            status, body = _get(client, endpoint + query, key)
            ok, error = _classify(status, body)
            payload = json.dumps(body or {})
            if key in payload or len(payload.encode()) > MAX_BYTES:
                ok, error, payload = False, "unsafe_or_oversize", "{}"
            if ok:
                try:
                    if not normalize(body or {}):
                        ok, error = False, "empty"
                except (ValueError, KeyError, TypeError, OverflowError):
                    ok, error = False, "invalid_bars"
            ensure_not_engaged()
            with session_scope(write=True) as session:
                # Recheck under write lock; concurrent refresh must not duplicate rows.
                if session.scalar(
                    select(RawPayloadCache.id).where(
                        RawPayloadCache.provider == PROVIDER, RawPayloadCache.request_hash == digest
                    )
                ):
                    continue
                session.add(
                    RawPayloadCache(
                        provider=PROVIDER,
                        endpoint=endpoint,
                        request_hash=digest,
                        status="ok" if ok else "error",
                        http_status=status,
                        payload=payload if ok else json.dumps({"error_category": error}),
                        received_at=now,
                    )
                )
            written += 1
    return written


def read_context(session: Session, *, as_of: datetime | None = None) -> list[dict[str, Any]]:
    result = []
    now = as_of or datetime.now(UTC)
    for symbol in SYMBOLS:
        row = session.scalar(
            select(RawPayloadCache)
            .where(
                RawPayloadCache.provider == PROVIDER,
                RawPayloadCache.received_at <= now,
                RawPayloadCache.endpoint.like(
                    "/futures/v1/aggs/ESZ6" if symbol == "ESZ6" else f"/v2/aggs/ticker/{symbol}/%"
                ),
            )
            .order_by(RawPayloadCache.received_at.desc())
            .limit(1)
        )
        item: dict[str, Any] = {
            "symbol": symbol,
            "source": "massive",
            "latency": "END_OF_DAY",
            "status": "unavailable",
            "timestamp": None,
            "close": None,
            "change_pct": None,
            "error_category": None,
        }
        if row:
            item["retrieved_at"] = row.received_at.isoformat()
            if row.status != "ok":
                item["error_category"] = json.loads(row.payload).get(
                    "error_category", "unavailable"
                )
            if row.status == "ok":
                try:
                    bars = normalize(json.loads(row.payload))
                    if bars:
                        last = bars[-1]
                        age = now - datetime.fromisoformat(last["timestamp"])
                        if age < timedelta(0):
                            item["status"] = "invalid"
                            result.append(item)
                            continue
                        item.update(
                            last, status="stale" if age > timedelta(days=4) else "available"
                        )
                        if len(bars) > 1:
                            item["change_pct"] = 100 * (last["close"] / bars[-2]["close"] - 1)
                except (ValueError, KeyError, TypeError, OverflowError):
                    item["status"] = "invalid"
        result.append(item)
    return result
