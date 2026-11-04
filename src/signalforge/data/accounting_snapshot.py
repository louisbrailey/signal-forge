"""Isolated raw-price/action cache. Never writes the operating or study databases."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from signalforge.data.adapters.massive import MassiveAdapter


def fetch_accounting_snapshot(
    adapter: MassiveAdapter,
    root: Path,
    symbols: list[str],
    start: date,
    end: date,
    *,
    max_bytes: int = 256 * 1024**2,
) -> dict[str, Any]:
    """One atomic cache checkpoint per endpoint. A partial page is a hard failure.

    Limit to 30 named symbols and 12 years; no bulk universe or unbounded paging.
    Reuse requires matching request identity and content hash, not file existence.
    """
    if (
        not symbols
        or len(symbols) > 30
        or len(set(symbols)) != len(symbols)
        or any(not re.fullmatch(r"[A-Z][A-Z0-9.]{0,9}", s) for s in symbols)
        or not 0 < (end - start).days <= 366 * 12
    ):
        raise ValueError("Bounded symbols and date window required")
    root.mkdir(parents=True, exist_ok=True)
    records = []
    for symbol in sorted(symbols):
        paths = {
            "bars": f"/v2/aggs/ticker/{symbol}/range/1/day/{start}/{end}"
            "?adjusted=false&sort=asc&limit=50000",
            "splits": f"/stocks/v1/splits?ticker={symbol}&execution_date.gte={start}"
            f"&execution_date.lte={end}&sort=execution_date.asc&limit=5000",
            "dividends": f"/stocks/v1/dividends?ticker={symbol}&ex_dividend_date.gte={start}"
            f"&ex_dividend_date.lte={end}&sort=ex_dividend_date.asc&limit=5000",
        }
        for kind, endpoint in paths.items():
            identity = hashlib.sha256(endpoint.encode()).hexdigest()
            path = root / f"{symbol}-{kind}-{identity[:16]}.json"
            if path.exists():
                record = json.loads(path.read_text())
                if (
                    record["endpoint"] != endpoint
                    or record["sha256"] != hashlib.sha256(record["raw"].encode()).hexdigest()
                ):
                    raise ValueError("Cached request or content hash mismatch")
            else:
                raw = adapter._request(endpoint)
                payload = json.loads(raw)
                if (
                    payload.get("status") not in ("OK", "DELAYED")
                    or payload.get("next_url")
                    or not isinstance(payload.get("results", []), list)
                    or (kind == "bars" and payload.get("adjusted") is not False)
                ):
                    raise ValueError(f"{symbol} {kind}: incomplete or invalid response")
                record = {
                    "symbol": symbol,
                    "kind": kind,
                    "endpoint": endpoint,
                    "source": "massive",
                    "latency": "END_OF_DAY",
                    "retrieved_at": datetime.now(UTC).isoformat(),
                    "requested_start": str(start),
                    "requested_end": str(end),
                    "adjusted": False,
                    "raw": raw,
                    "sha256": hashlib.sha256(raw.encode()).hexdigest(),
                }
                content = json.dumps(record, sort_keys=True)
                used = sum(p.stat().st_size for p in root.iterdir() if p.is_file())
                if used + len(content.encode()) + 1024**2 > max_bytes:
                    raise ValueError("Snapshot storage cap reached")
                tmp = path.with_suffix(".tmp")
                tmp.write_text(content)
                tmp.replace(path)
            records.append({k: v for k, v in record.items() if k != "raw"} | {"file": path.name})
    manifest = {
        "schema": "raw-actions-v1",
        "start": str(start),
        "end": str(end),
        "records": records,
    }
    tmp = root / "manifest.tmp"
    tmp.write_text(json.dumps(manifest, sort_keys=True, indent=2))
    tmp.replace(root / "manifest.json")
    return manifest
