"""Independent forward-research collector. No paper account, alert or broker writes."""

import argparse
import fcntl
import json
import os
from datetime import date, timedelta
from pathlib import Path

from action_replay_report import read_metadata
from dotenv import dotenv_values

from signalforge.backtest.actions import TickerChange
from signalforge.data.accounting_snapshot import fetch_accounting_snapshot
from signalforge.data.adapters.massive import MassiveAdapter, completed_session_cutoff
from signalforge.killswitch import ensure_not_engaged
from signalforge.research.action_replay import compare, load_dataset
from signalforge.research.prospective_funded import (
    freeze,
    record_collection,
    review_readiness,
    validate_plan,
    write_once,
)


def _collect(root, env_file):
    from signalforge.data.calendar import sessions

    plan = validate_plan(root)
    cutoff = completed_session_cutoff()
    available = sessions(cutoff - timedelta(days=10), cutoff)
    through = available[-1]
    if through < date.fromisoformat(plan["first_observation_session"]):
        return {
            "status": "WAITING_FOR_FIRST_FUTURE_SESSION",
            "first_entry_session": plan["first_entry_session"],
        }
    if (root / "collections" / f"{through}.json").exists():
        return {"status": "ALREADY_COLLECTED", "through": str(through)}
    if sum(p.stat().st_size for p in root.rglob("*") if p.is_file()) > plan["cache_cap_bytes"]:
        raise ValueError("Study storage cap reached")
    values = dotenv_values(env_file)
    os.environ.setdefault(
        "SIGNALFORGE_DATA_DIR", values.get("SIGNALFORGE_DATA_DIR") or str(env_file.parent / "data")
    )
    key = values.get("MARKET_DATA_API_KEY")
    if not key:
        raise ValueError("MARKET_DATA_API_KEY is not set")
    cache = root / "cache" / str(through)
    ensure_not_engaged()
    manifest = fetch_accounting_snapshot(
        MassiveAdapter(api_key=key, min_request_spacing_s=12.1),
        cache,
        plan["symbols"],
        date.fromisoformat(plan["history_start"]),
        through,
        max_bytes=plan["cache_cap_bytes"]
        - sum(p.stat().st_size for p in root.rglob("*") if p.is_file() and cache not in p.parents)
        - 16 * 1024**2,
    )
    write_once(root / "manifests" / f"{through}.json", manifest)
    changes = tuple(
        TickerChange(
            c["old"], c["new"], date.fromisoformat(c["effective"]), c["source"], c["evidence"]
        )
        for c in plan["ticker_changes"]
    )
    ensure_not_engaged()
    report = compare(
        load_dataset(cache, changes),
        plan["metadata"],
        entry_start=date.fromisoformat(plan["first_entry_session"]),
        evaluation_start=date.fromisoformat(plan["first_observation_session"]),
        prospective=True,
    )
    ensure_not_engaged()
    saved = record_collection(root, through, report)
    return {
        "status": saved["status"],
        "through": saved["through"],
        "books": len(report["books"]) * 2,
        "observed_sessions": saved["observed_sessions"],
    }


def collect(root, env_file):
    root.mkdir(parents=True, exist_ok=True)
    with (root / "collector.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return _collect(root, env_file)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("command", choices=["freeze", "collect", "status"])
    p.add_argument("root", type=Path)
    p.add_argument("--env-file", type=Path)
    p.add_argument("--database", type=Path)
    p.add_argument("--since", type=date.fromisoformat, default=date(2016, 10, 17))
    p.add_argument("--symbols", nargs="+")
    p.add_argument("--listing-evidence", type=Path)
    a = p.parse_args()
    if a.command == "freeze":
        if not a.database or not a.symbols:
            p.error("freeze requires --database and --symbols")
        meta, changes = read_metadata(a.database, a.listing_evidence)
        plan = freeze(a.root, meta, changes, a.symbols, a.since)
        print(
            json.dumps(
                {"status": "FROZEN_NEW_STUDY", "first_entry_session": plan["first_entry_session"]}
            )
        )
    elif a.command == "status":
        print(json.dumps(review_readiness(a.root), indent=2))
    else:
        if not a.env_file:
            p.error("collect requires --env-file")
        try:
            status = collect(a.root, a.env_file)
            print(json.dumps(status))
            a.root.mkdir(parents=True, exist_ok=True)
            tmp = a.root / "status.tmp"
            tmp.write_text(json.dumps(status))
            tmp.replace(a.root / "status.json")
        except Exception as exc:
            # Never log exception bodies/provider responses, keys or request headers.
            # Only fixed, locally defined categories; never provider exception text.
            categories = {
                "Frozen forward code": "code_changed",
                "Missing prospective session": "missed_session",
                "Previously collected": "input_or_decision_revision",
                "Snapshot storage": "storage_cap",
                "Study storage": "storage_cap",
                "Fractional split": "cash_in_lieu_missing",
            }
            category = next(
                (v for k, v in categories.items() if str(exc).startswith(k)), type(exc).__name__
            )
            status = {"status": "BLOCKED", "error_category": category}
            print(json.dumps(status))
            a.root.mkdir(parents=True, exist_ok=True)
            tmp = a.root / "status.tmp"
            tmp.write_text(json.dumps(status))
            tmp.replace(a.root / "status.json")
            raise SystemExit(1) from None
