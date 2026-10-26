#!/usr/bin/env python3
"""Resolve bounded shadow diagnostics; source market database stays read-only."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from signalforge.data.calendar import last_closed_session
from signalforge.db.models import Instrument, OHLCVDaily
from signalforge.kronos.outcomes import evaluate


def run(source: Path, ledger: Path, limit: int = 250) -> dict[str, int]:
    if source.resolve() == ledger.resolve() or not source.is_file() or not ledger.is_file():
        raise ValueError("Existing separate source and ledger required")
    if not 1 <= limit <= 1000 or ledger.stat().st_size > 256 * 1024 * 1024:
        raise ValueError("Evaluation bounds exceeded")
    engine = create_engine("sqlite:///" + source.resolve().as_uri() + "?mode=ro&uri=true")
    counts: dict[str, int] = {}
    try:
        with sqlite3.connect(ledger, timeout=1) as db, Session(engine) as session:
            page_size = db.execute("PRAGMA page_size").fetchone()[0]
            db.execute(f"PRAGMA max_page_count={256 * 1024 * 1024 // page_size}")
            db.execute(
                "CREATE TABLE IF NOT EXISTS outcomes (symbol TEXT, origin TEXT, "
                "horizon INTEGER, evaluated_at TEXT, payload TEXT, PRIMARY "
                "KEY(symbol,origin,horizon))"
            )
            rows = db.execute(
                "SELECT f.symbol,f.origin,f.horizon,f.generated_at,f.payload FROM forecasts f "
                "LEFT JOIN outcomes o USING(symbol,origin,horizon) "
                "WHERE f.status='complete' AND o.symbol IS NULL "
                "ORDER BY f.generated_at LIMIT ?",
                (limit,),
            ).fetchall()
            completed = last_closed_session(datetime.now(UTC))
            for symbol, origin, horizon, generated, raw in rows:
                if ledger.stat().st_size > 255 * 1024 * 1024:
                    break
                try:
                    payload = json.loads(raw)
                    dates = payload.get("dates", [])
                    bars = []
                    if dates and len(dates) <= 20:
                        for b in session.scalars(
                            select(OHLCVDaily)
                            .join(Instrument)
                            .where(
                                Instrument.symbol == symbol,
                                OHLCVDaily.source == "massive",
                                OHLCVDaily.session_date >= datetime.fromisoformat(dates[0]).date(),
                                OHLCVDaily.session_date
                                <= min(completed, datetime.fromisoformat(dates[-1]).date()),
                            )
                            .order_by(OHLCVDaily.session_date)
                            .limit(21)
                        ):
                            bars.append(
                                {
                                    "date": str(b.session_date),
                                    "open": b.open,
                                    "close": b.close,
                                    "source": b.source,
                                    "simulated": b.is_simulated,
                                    "adjusted": b.is_adjusted,
                                    "flags": b.quality_flags,
                                }
                            )
                    result = evaluate(payload, generated, bars)
                except (ValueError, TypeError, AttributeError):
                    result = {"status": "excluded", "reason": "malformed_record"}
                status = result["status"]
                counts[status] = counts.get(status, 0) + 1
                if status != "pending":
                    db.execute(
                        "INSERT OR IGNORE INTO outcomes VALUES (?,?,?,?,?)",
                        (
                            symbol,
                            origin,
                            horizon,
                            datetime.now(UTC).isoformat(),
                            json.dumps(result),
                        ),
                    )
    finally:
        engine.dispose()
    return counts
