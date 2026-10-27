#!/usr/bin/env python3
"""Resume one existing intraday research backfill, never start a new run."""

from __future__ import annotations

import argparse
import fcntl
import os
import sys

from signalforge.config import get_settings, paths
from signalforge.db.models import IngestionRun
from signalforge.db.session import session_scope
from signalforge.domain import FeedType
from signalforge.killswitch import KillSwitchEngaged, ensure_not_engaged


def resume(run_id: int, bar_size: str) -> int:
    """Hold a local nonblocking lock across the child so polls cannot overlap."""
    if run_id <= 0 or bar_size not in {"5m", "15m", "30m", "1h"}:
        raise ValueError("Invalid run ID or bar size")
    lock_path = paths.data_dir() / f"intraday-backfill-{run_id}.lock"
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("Backfill already running; skipping overlapping poll.")
            return 0
        try:
            ensure_not_engaged()
        except KillSwitchEngaged:
            print("Emergency stop active; backfill paused.")
            return 0
        with session_scope(write=False) as session:
            run = session.get(IngestionRun, run_id)
            if run is None or run.feed_type != FeedType.BAR_INTRADAY:
                raise ValueError("Requested intraday backfill does not exist")
            if run.provider != get_settings().market_data_provider:
                raise ValueError("Configured provider does not match the recorded run")
            if not (run.notes or "").startswith(f"intraday {bar_size} RTH-only backfill"):
                raise ValueError("Bar size does not match the recorded run")
            symbols = list(run.symbols_requested or [])
            if not symbols or not run.requested_start or not run.requested_end:
                raise ValueError("Recorded backfill scope is incomplete")
            if run.status == "ok" and set(symbols) <= set(run.symbols_ok or []):
                print(f"Backfill {run_id} complete; no request made.")
                return 0
            start, end = run.requested_start.isoformat(), run.requested_end.isoformat()
        command = [
            sys.executable,
            "-m",
            "signalforge.cli",
            "ingest-intraday",
            "--bar-size",
            bar_size,
            "--since",
            start,
            "--until",
            end,
            "--symbols",
            ",".join(symbols),
            "--resume-run-id",
            str(run_id),
        ]
        # Retain the lock across process replacement, including abnormal exits.
        os.set_inheritable(lock.fileno(), True)
        os.execv(sys.executable, command)  # noqa: S606 - fixed local Python CLI, argument array
        raise RuntimeError("execv unexpectedly returned")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", type=int, required=True)
    parser.add_argument("--bar-size", required=True)
    args = parser.parse_args()
    return resume(args.run_id, args.bar_size)


if __name__ == "__main__":
    raise SystemExit(main())
