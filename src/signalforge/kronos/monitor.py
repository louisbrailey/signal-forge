"""Bounded, read-only dashboard access to the separate shadow ledger."""

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from signalforge.config.paths import data_dir


def shadow_status(path: Path | None = None) -> dict[str, Any]:
    path = path or data_dir() / "kronos-shadow-daily.sqlite"
    report: dict[str, Any] = {"status": "not_started", "heartbeat": None, "rows": [], "counts": {}}
    if not path.is_file():
        return report
    try:
        with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=1) as db:
            db.execute("PRAGMA query_only=ON")
            try:
                heartbeat = db.execute("SELECT checked_at FROM health WHERE id=1").fetchone()
            except sqlite3.OperationalError:
                heartbeat = None
            report["heartbeat"] = heartbeat[0] if heartbeat else None
            age = (
                (datetime.now(UTC) - datetime.fromisoformat(heartbeat[0])).total_seconds()
                if heartbeat
                else None
            )
            report["status"] = (
                "running" if age is not None and 0 <= age < 600 else "not_running_or_stale"
            )
            report["counts"] = dict(
                db.execute("SELECT status, COUNT(*) FROM forecasts GROUP BY status")
            )
            try:
                report["outcomes"] = dict(
                    db.execute(
                        "SELECT json_extract(payload, '$.status'), COUNT(*) FROM outcomes "
                        "GROUP BY 1"
                    )
                )
                report["recent_outcomes"] = [
                    {"symbol": s, "horizon": h, **json.loads(p)}
                    for s, h, p in db.execute(
                        "SELECT symbol,horizon,payload FROM outcomes ORDER BY evaluated_at "
                        "DESC LIMIT 25"
                    )
                ]
            except sqlite3.OperationalError:
                report["outcomes"] = {}
                report["recent_outcomes"] = []
            report["attempts_today"] = db.execute(
                "SELECT COUNT(*) FROM forecasts WHERE generated_at LIKE ?",
                (datetime.now(UTC).date().isoformat() + "%",),
            ).fetchone()[0]
            try:
                report["exclusions"] = [
                    dict(zip(("symbol", "reason", "latest", "expected"), r, strict=True))
                    for r in db.execute(
                        "SELECT symbol,reason,latest,expected FROM input_checks "
                        "ORDER BY symbol LIMIT 250"
                    )
                ]
            except sqlite3.OperationalError:
                report["exclusions"] = []
            for symbol, origin, generated, status, raw in db.execute(
                "SELECT symbol,origin,generated_at,status,substr(payload,1,131072) "
                "FROM forecasts ORDER BY generated_at DESC LIMIT 25"
            ):
                payload = json.loads(raw)
                report["rows"].append(
                    {
                        "symbol": symbol,
                        "origin": origin,
                        "generated": generated,
                        "status": status,
                        "mode": payload.get("mode", "legacy_unclassified"),
                        "reason": payload.get("reason", payload.get("error_category", "")),
                        "source": payload.get("source", "not recorded"),
                        "latency": payload.get("latency", "not recorded"),
                        "stale": payload.get("data_stale", "unknown"),
                    }
                )
    except (sqlite3.Error, ValueError, TypeError, AttributeError):
        report.update(status="unavailable_or_invalid", rows=[])
    return report
