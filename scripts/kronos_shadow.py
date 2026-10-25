#!/usr/bin/env python3
"""Bounded prospective shadow recorder. Main DB is opened read-only; no trade creation."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import sqlite3
import time
from datetime import UTC, date, datetime
from pathlib import Path

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from signalforge.data.calendar import last_closed_session
from signalforge.db.models import Candidate, Instrument, OHLCVDaily
from signalforge.kronos.shadow import forecast, inputs, partition


def stopped(path: Path) -> bool:
    try:
        return json.loads(path.read_text()).get("active", True) is not False
    except FileNotFoundError:
        return False  # project convention: initial missing file means not engaged
    except (OSError, ValueError, AttributeError, TypeError):
        return True


def run(args) -> int:
    output = args.output_db.resolve()
    if output == args.source_db.resolve():
        raise ValueError("shadow output must be separate")
    if output.exists() and output.stat().st_size > 256 * 1024 * 1024:
        raise ValueError("shadow storage cap reached; archive before restarting")
    output.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(output) + ".lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("Shadow queue already running")
            return 0
        return _run(args)


def _run(args) -> int:
    source, output = args.source_db.resolve(), args.output_db.resolve()
    if not source.is_file() or output == source:
        raise ValueError("source must exist and shadow DB must be separate")
    if len(args.symbols) > 250 or not 1 <= args.max_calls <= 25:
        raise ValueError("limit: 250 explicit symbols, at most 25 model calls per UTC day")
    if stopped(args.kill_switch):
        print("Shadow research stopped: kill switch engaged, missing or invalid")
        return 0
    output.parent.mkdir(parents=True, exist_ok=True)
    ledger = sqlite3.connect(output)
    ledger.execute("""CREATE TABLE IF NOT EXISTS forecasts (
        symbol TEXT, origin TEXT, horizon INTEGER, generated_at TEXT, status TEXT,
        payload TEXT, PRIMARY KEY(symbol, origin, horizon))""")
    today = datetime.now(UTC).date().isoformat()
    calls = ledger.execute(
        "SELECT COUNT(*) FROM forecasts WHERE generated_at LIKE ?", (today + "%",)
    ).fetchone()[0]
    engine = create_engine(f"sqlite+pysqlite:///file:{source}?mode=ro&uri=true")
    calendar_cutoff = last_closed_session(datetime.now(UTC))
    try:
        # Check independently generated candidates first; this never accepts/rejects one.
        with Session(engine) as session:
            candidate_symbols = set(
                session.scalars(
                    select(Instrument.symbol)
                    .join(Candidate)
                    .where(
                        Candidate.created_at
                        >= datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
                    )
                ).all()
            )
        symbols = sorted(
            set(args.symbols), key=lambda s: (s not in candidate_symbols, partition(s), s)
        )
        for symbol in symbols:
            if calls >= args.max_calls or stopped(args.kill_switch):
                break
            with Session(engine) as session:
                instrument = session.scalar(
                    select(Instrument).where(Instrument.symbol == symbol)
                )
                cutoff = session.scalar(
                    select(func.max(OHLCVDaily.session_date)).where(
                        OHLCVDaily.instrument_id == instrument.id if instrument else False,
                        OHLCVDaily.source == "massive",
                        OHLCVDaily.session_date <= calendar_cutoff,
                    )
                )
            # Tests and replay callers may provide a synthetic input function
            # without persisted bars; the real input validator still rejects
            # missing history before inference.
            if not isinstance(cutoff, date):
                cutoff = calendar_cutoff
            if ledger.execute(
                "SELECT 1 FROM forecasts WHERE symbol=? AND origin=? AND horizon=?",
                (symbol, str(cutoff), args.horizon),
            ).fetchone():
                continue
            # Reserve before inference: crashes count toward budget, never silently rerun.
            stamp = datetime.now(UTC).isoformat()
            ledger.execute(
                "INSERT INTO forecasts VALUES (?,?,?,?,?,?)",
                (symbol, str(cutoff), args.horizon, stamp, "started", "{}"),
            )
            ledger.commit()
            calls += 1
            try:
                with Session(engine) as session:
                    history = inputs(session, symbol, cutoff)
                if stopped(args.kill_switch):
                    raise ValueError("kill switch engaged")
                result = forecast(
                    history, symbol, args.horizon, cancelled=lambda: stopped(args.kill_switch)
                )
                result["existing_strategy_candidate"] = symbol in candidate_symbols
                result["lane"] = "strategy_check" if symbol in candidate_symbols else "discovery"
                result["worker_code_sha256"] = hashlib.sha256(
                    (Path(__file__).parents[1] / "src/signalforge/kronos/worker.py").read_bytes()
                ).hexdigest()
                result["model_revision"] = "unverified_cached_weights"
                result["independent_confirmation"] = False
                result["history"] = history
                result["source"] = "massive"
                result["latency"] = "END_OF_DAY"
                status = "complete"
            except Exception as exc:
                # Never record exception text or provider credentials.
                result, status = {
                    "error_category": type(exc).__name__,
                    "trade_approved": False,
                }, "failed"
            ledger.execute(
                "UPDATE forecasts SET status=?, payload=? "
                "WHERE symbol=? AND origin=? AND horizon=?",
                (status, json.dumps(result), symbol, str(cutoff), args.horizon),
            )
            ledger.commit()
            print(f"{symbol}: {status}; research signal only — no order was placed.")
    finally:
        engine.dispose()
        ledger.close()
    return calls


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-db", type=Path, required=True)
    parser.add_argument("--output-db", type=Path, required=True)
    parser.add_argument("--kill-switch", type=Path, required=True)
    parser.add_argument("--symbols", nargs="+", required=True)
    parser.add_argument("--horizon", type=int, choices=(5, 20), default=5)
    parser.add_argument("--max-calls", type=int, default=25)
    parser.add_argument(
        "--watch", action="store_true", help="Poll every five minutes; new completed bars only"
    )
    args = parser.parse_args()
    while True:
        run(args)
        if not args.watch or stopped(args.kill_switch):
            break
        for _ in range(300):
            if stopped(args.kill_switch):
                return
            time.sleep(1)


if __name__ == "__main__":
    main()
