"""Independent forward-research collector. No paper account, alert or broker writes."""

import argparse
import fcntl
import json
import os
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

if __package__:
    from .action_replay_report import read_metadata
else:
    from action_replay_report import read_metadata
from dotenv import dotenv_values

from signalforge import study_registry as registry
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
from signalforge.research.strategy_scope import resolve_strategy_scope


def _collect(root, env_file, *, check_only=False):
    from signalforge.data.calendar import sessions

    plan = validate_plan(root)
    resolve_strategy_scope(plan["strategies"])
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
    if check_only:
        return {"status": "READY_FOR_COLLECTION", "through": str(through)}
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
        strategy_specs=plan["strategies"],
    )
    ensure_not_engaged()
    saved = record_collection(root, through, report)
    return {
        "status": saved["status"],
        "through": saved["through"],
        "books": len(report["books"]) * 2,
        "observed_sessions": saved["observed_sessions"],
    }


def collect(root, env_file, *, check_only=False):
    root.mkdir(parents=True, exist_ok=True)
    with (root / "collector.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return _collect(root, env_file, check_only=check_only)


def run_collection(root, env_file, *, registry_path=None, generation=None, check_only=False):
    snapshot = None
    if registry_path is not None:
        if generation is None:
            raise ValueError("Active collector requires --expected-generation")
        snapshot = registry.pin_collector(registry_path, generation, "forward", [root])
    elif (root / "refresh-lineage.json").exists():
        raise ValueError("Versioned forward study requires an active registry")
    root.mkdir(parents=True, exist_ok=True)
    with (root / "collector.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if snapshot and (root / "status.json").exists():
            previous = registry.read_json(root / "status.json")
            if (
                previous.get("generation") != generation
                or previous.get("registry_hash") != snapshot["hash"]
            ):
                raise ValueError("Forward collector state belongs to another generation")
        error = None
        try:
            status = _collect(root, env_file, check_only=check_only)
        except Exception as exc:
            error = exc
            status = {"status": "BLOCKED", "error_category": type(exc).__name__}
        status.update(checked_at=datetime.now(UTC).isoformat(), study_name=root.name)
        if snapshot:
            status.update(generation=generation, registry_hash=snapshot["hash"])
            registry.publish_current(
                registry_path, snapshot, lambda: registry.atomic_json(root / "status.json", status)
            )
        else:
            registry.atomic_json(root / "status.json", status)
        if error:
            raise error
        return status


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("command", choices=["freeze", "collect", "status"])
    p.add_argument("root", type=Path)
    p.add_argument("--env-file", type=Path)
    p.add_argument("--database", type=Path)
    p.add_argument("--since", type=date.fromisoformat, default=date(2016, 10, 17))
    p.add_argument("--symbols", nargs="+")
    p.add_argument("--listing-evidence", type=Path)
    p.add_argument("--registry", type=Path)
    p.add_argument("--expected-generation", type=int)
    p.add_argument("--check-only", action="store_true")
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
            status = run_collection(
                a.root,
                a.env_file,
                registry_path=a.registry,
                generation=a.expected_generation,
                check_only=a.check_only,
            )
            print(json.dumps(status))
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
            raise SystemExit(1) from None
