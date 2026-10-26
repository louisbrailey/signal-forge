#!/usr/bin/env python3
"""Bounded prospective shadow recorder. Main DB is opened read-only; no trade creation."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import sqlite3
import time
from dataclasses import asdict
from datetime import UTC, date, datetime
from pathlib import Path

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from signalforge.backtest.costs import CostModel
from signalforge.data.calendar import last_closed_session
from signalforge.db.models import Candidate, Instrument, OHLCVDaily
from signalforge.domain import Horizon
from signalforge.kronos.outcomes import PROTOCOL
from signalforge.kronos.shadow import forecast, inputs, partition
from signalforge.settings_store import effective_research_config


def stopped(path: Path) -> bool:
    try:
        return json.loads(path.read_text()).get("active", True) is not False
    except FileNotFoundError:
        return False  # project convention: initial missing file means not engaged
    except (OSError, ValueError, AttributeError, TypeError):
        return True


def run(args: argparse.Namespace) -> int:
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
        result = _run(args)
        if not stopped(args.kill_switch):
            from signalforge.kronos.outcome_store import run as resolve_outcomes

            resolve_outcomes(args.source_db, args.output_db)
        return result


def _run(args: argparse.Namespace) -> int:
    source, output = args.source_db.resolve(), args.output_db.resolve()
    if not source.is_file() or output == source:
        raise ValueError("source must exist and shadow DB must be separate")
    if len(args.symbols or []) > 250 or not 1 <= args.max_calls <= 25:
        raise ValueError("limit: 250 explicit symbols, at most 25 model calls per UTC day")
    if any(not re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,14}", s) for s in args.symbols or []):
        raise ValueError("Each symbol must be a separate valid uppercase ticker")
    if stopped(args.kill_switch):
        print("Shadow research stopped: kill switch engaged, missing or invalid")
        return 0
    output.parent.mkdir(parents=True, exist_ok=True)
    ledger = sqlite3.connect(output)
    ledger.execute("""CREATE TABLE IF NOT EXISTS forecasts (
        symbol TEXT, origin TEXT, horizon INTEGER, generated_at TEXT, status TEXT,
        payload TEXT, PRIMARY KEY(symbol, origin, horizon))""")
    ledger.execute("CREATE TABLE IF NOT EXISTS health (id INTEGER PRIMARY KEY, checked_at TEXT)")
    ledger.execute(
        "CREATE TABLE IF NOT EXISTS input_checks "
        "(symbol TEXT PRIMARY KEY, checked_at TEXT, reason TEXT, latest TEXT, expected TEXT)"
    )
    ledger.execute("INSERT OR REPLACE INTO health VALUES (1, ?)", (datetime.now(UTC).isoformat(),))
    ledger.commit()
    today = datetime.now(UTC).date().isoformat()
    calls = ledger.execute(
        "SELECT COUNT(*) FROM forecasts WHERE generated_at LIKE ?", (today + "%",)
    ).fetchone()[0]
    engine = create_engine(f"sqlite+pysqlite:///file:{source}?mode=ro&uri=true")
    calendar_cutoff = last_closed_session(datetime.now(UTC))
    try:
        # Check independently generated candidates first; this never accepts/rejects one.
        with Session(engine) as session:
            requested_symbols = args.symbols or list(effective_research_config(session).universe)
            if len(requested_symbols) > 250:
                raise ValueError("Configured watchlist exceeds 250-symbol cap")
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
            set(requested_symbols), key=lambda s: (s not in candidate_symbols, partition(s), s)
        )
        for symbol in symbols:
            if calls >= args.max_calls or stopped(args.kill_switch):
                break
            if output.stat().st_size > 256 * 1024 * 1024:
                break
            ledger.execute(
                "INSERT OR REPLACE INTO health VALUES (1, ?)", (datetime.now(UTC).isoformat(),)
            )
            ledger.commit()
            with Session(engine) as session:
                instrument = session.scalar(select(Instrument).where(Instrument.symbol == symbol))
                latest = session.scalar(
                    select(func.max(OHLCVDaily.session_date)).where(
                        OHLCVDaily.instrument_id == (instrument.id if instrument else -1),
                        OHLCVDaily.source == "massive",
                        OHLCVDaily.session_date <= calendar_cutoff,
                    )
                )
            replay_mode = getattr(args, "replay_latest", False)
            cutoff = latest if replay_mode and isinstance(latest, date) else calendar_cutoff
            # Missing publication is retryable on the next cycle. It is not a model
            # attempt and must not reserve/dedupe this origin before its bars arrive.
            try:
                with Session(engine) as session:
                    history = inputs(session, symbol, cutoff)
            except ValueError:
                reason = (
                    "missing_history"
                    if latest is None
                    else (
                        "stale_history"
                        if latest < calendar_cutoff and not replay_mode
                        else "invalid_or_incomplete_history"
                    )
                )
                ledger.execute(
                    "INSERT OR REPLACE INTO input_checks VALUES (?,?,?,?,?)",
                    (
                        symbol,
                        datetime.now(UTC).isoformat(),
                        reason,
                        str(latest) if latest else None,
                        str(calendar_cutoff),
                    ),
                )
                ledger.commit()
                print(f"{symbol}: excluded ({reason}); Research signal only — no order was placed.")
                continue
            ledger.execute("DELETE FROM input_checks WHERE symbol=?", (symbol,))
            ledger.commit()
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
                    snapshots = [
                        {
                            "id": c.id,
                            "strategy_version_id": c.strategy_version_id,
                            "created_at": c.created_at.isoformat(),
                            "direction": c.direction.value,
                            "gate": c.quality_gate_status.value,
                            "horizon": c.horizon.value,
                            "failed_gates": c.failed_gates,
                        }
                        for c in session.scalars(
                            select(Candidate)
                            .join(Instrument)
                            .where(
                                Instrument.symbol == symbol,
                                Candidate.structure_kind.is_(None),
                                Candidate.horizon
                                == (
                                    Horizon.SHORT_SWING
                                    if args.horizon == 5
                                    else Horizon.MEDIUM_SWING
                                ),
                                Candidate.created_at <= datetime.fromisoformat(stamp),
                                Candidate.created_at
                                >= datetime.fromisoformat(stamp).replace(
                                    hour=0, minute=0, second=0, microsecond=0
                                ),
                            )
                            .order_by(Candidate.id)
                            .limit(1001)
                        )
                    ]
                if len(snapshots) > 1000:
                    raise ValueError("candidate snapshot cap exceeded")
                if stopped(args.kill_switch):
                    raise ValueError("kill switch engaged")
                result = forecast(
                    history, symbol, args.horizon, cancelled=lambda: stopped(args.kill_switch)
                )
                result["evaluation_protocol"] = PROTOCOL
                result["candidate_snapshot"] = snapshots
                result["evaluation_costs"] = {"model": asdict(CostModel()), "spread_bps": 5.0}
                result["completed_at"] = datetime.now(UTC).isoformat()
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
                result["mode"] = "historical_replay" if replay_mode else "prospective_shadow"
                result["data_stale"] = cutoff < calendar_cutoff
                result["latest_available_session"] = str(latest) if latest else None
                result["expected_session"] = str(calendar_cutoff)
                status = "complete"
            except Exception as exc:
                # Never record exception text or provider credentials.
                result, status = {
                    "error_category": type(exc).__name__,
                    "reason": (
                        "missing_history"
                        if latest is None
                        else (
                            "stale_history"
                            if latest < calendar_cutoff and not replay_mode
                            else "input_validation_or_runtime_failure"
                        )
                    ),
                    "latest_available_session": str(latest) if latest else None,
                    "expected_session": str(calendar_cutoff),
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-db", type=Path, required=True)
    parser.add_argument("--output-db", type=Path, required=True)
    parser.add_argument("--kill-switch", type=Path, required=True)
    parser.add_argument("--symbols", nargs="+", help="Defaults to the configured watchlist")
    parser.add_argument(
        "--replay-latest",
        action="store_true",
        help="Explicit historical mode; permits old inputs, never prospective evidence",
    )
    parser.add_argument("--horizon", type=int, choices=(5, 20), default=5)
    parser.add_argument("--max-calls", type=int, default=25)
    parser.add_argument(
        "--watch", action="store_true", help="Poll every five minutes; new completed bars only"
    )
    args = parser.parse_args()
    if args.replay_latest and args.watch:
        parser.error("Historical replay cannot run as a prospective watch service")
    while True:
        if not stopped(args.kill_switch):
            run(args)
        if not args.watch:
            break
        for _ in range(300):
            time.sleep(1)


if __name__ == "__main__":
    main()
