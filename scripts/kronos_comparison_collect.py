#!/usr/bin/env python3
"""One bounded poll of isolated books. No operating scheduler registration or writes."""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import json
import os
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from signalforge.data.calendar import last_closed_session, rth_bounds_utc
from signalforge.db.models import AuditLog, JobRun, ScanRun
from signalforge.experiments.comparison import ROOT, advance, open_books, source_engine

JOBS = ("approved_scope_scan", "catchup_approved_scope_scan")


def trigger(directory: Path, now: datetime) -> dict[str, Any]:
    """Read-only readiness evidence; zero candidates is still a completed scan."""
    engine, manifest = open_books(directory)
    try:
        stop = Path(manifest["kill_switch_path"])
        try:
            if json.loads(stop.read_text())["active"] is not False:
                return {"status": "blocked_emergency_stop"}
        except FileNotFoundError:
            # Match the pinned runner: no state file is the initial OFF state.
            # Do not initialize or otherwise write the operating kill switch.
            pass
        except (OSError, ValueError, KeyError):
            return {"status": "blocked_emergency_stop_unavailable"}
        with Session(engine) as books:
            if books.scalar(text("SELECT COUNT(*) FROM comparison_final")):
                return {"status": "finalized"}
            pending = books.scalar(
                text(
                    "SELECT day FROM comparison_batch WHERE status!='complete' ORDER BY day LIMIT 1"
                )
            )
            if pending:
                return {"status": "ready", "reason": "resume_captured_batch", "day": pending}
            origin = last_closed_session(now)
            day = str(origin)
            if day < manifest["study_days"][0] or origin != now.date():
                return {"status": "waiting_for_postclose_window"}
            if books.scalar(
                text("SELECT COUNT(*) FROM comparison_batch WHERE day=:day AND status='complete'"),
                {"day": day},
            ):
                return {"status": "already_collected", "day": day}
        bounds = rth_bounds_utc(origin)
        assert bounds is not None
        close = max(bounds[1], datetime.fromisoformat(manifest["frozen_at"]))
        src = source_engine(Path(manifest["source"]))
        try:
            with Session(src) as s:
                jobs = list(
                    s.scalars(
                        select(JobRun)
                        .where(
                            JobRun.name.in_(JOBS),
                            JobRun.started_at >= close,
                        )
                        .order_by(JobRun.started_at.desc(), JobRun.id.desc())
                        .limit(1)
                    )
                )
                for job in jobs:
                    if (
                        job.status != "ok"
                        or job.finished_at is None
                        or not close <= job.started_at <= job.finished_at <= now
                    ):
                        return {"status": "waiting_for_successful_scan_job", "day": day}
                    audits = s.scalars(
                        select(AuditLog)
                        .where(
                            AuditLog.action == "approved_scope_scan.completed",
                            AuditLog.actor == "scheduler",
                            AuditLog.ts >= job.started_at,
                            AuditLog.ts <= job.finished_at,
                        )
                        .order_by(AuditLog.ts.desc())
                        .limit(32)
                    )
                    for audit in audits:
                        payload = audit.after_json
                        if (
                            not isinstance(payload, dict)
                            or payload.get("readiness_enforced") is not True
                        ):
                            continue
                        covered: set[str] = set()
                        ids = []
                        for item in payload.get("runs", []):
                            if (
                                not isinstance(item, dict)
                                or item.get("horizon") != manifest["horizon"]
                            ):
                                continue
                            versions = item.get("strategy_version_ids")
                            if (
                                item.get("source") != "massive"
                                or not isinstance(versions, list)
                                or not versions
                                or any(type(v) is not int for v in versions)
                                or type(item.get("scan_run_id")) is not int
                            ):
                                continue
                            scan = s.get(ScanRun, item["scan_run_id"])
                            if (
                                scan is None
                                or scan.dataset_snapshot_id != item.get("dataset_snapshot_id")
                                or scan.source != "massive"
                                or scan.horizon.value != manifest["horizon"]
                                or scan.finished_at is None
                                or not close <= scan.started_at <= scan.finished_at <= audit.ts
                            ):
                                continue
                            covered.update(str(v) for v in item.get("strategy_version_ids", []))
                            ids.append(scan.id)
                        if set(manifest["versions"]).issubset(covered):
                            return {
                                "status": "ready",
                                "day": day,
                                "job_id": job.id,
                                "audit_id": audit.id,
                                "scan_ids": ids,
                            }
                return {"status": "waiting_for_completed_approved_scan", "day": day}
        finally:
            src.dispose()
    finally:
        engine.dispose()


def runtime_busy() -> bool:
    """Avoid starting a batch while another local Kronos call owns the runtime.

    This is only a preflight. The frozen runtime still owns its actual lock;
    races/failures remain unavailable observations and are never re-drawn.
    """
    path = Path(tempfile.gettempdir()) / f"signalforge-kronos-{os.getuid()}.lock"
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        return False


def poll(
    directories: list[Path],
    *,
    now: datetime | None = None,
    collect: bool = True,
    previous: dict[str, dict] | None = None,
) -> list[dict]:
    results = []
    for directory in directories:
        prior = (previous or {}).get(directory.name, {})
        if prior.get("retry_after") and datetime.fromisoformat(prior["retry_after"]) > (
            now or datetime.now(UTC)
        ):
            results.append(prior)
            continue
        result: dict[str, Any] = {"experiment": directory.name}
        try:
            result.update(trigger(directory, now or datetime.now(UTC)))
            if result["status"] == "ready" and collect:
                if runtime_busy():
                    result["status"] = "waiting_for_kronos_runtime"
                else:
                    # The ledger may log fills. Keep daemon output to a fixed,
                    # non-sensitive operational schema, never traceback/env text.
                    with (
                        Path(os.devnull).open("w") as sink,
                        contextlib.redirect_stdout(sink),
                        contextlib.redirect_stderr(sink),
                    ):
                        outcome = advance(directory)
                    result["status"] = outcome["status"]
            result["checked_at"] = datetime.now(UTC).isoformat()
        except Exception as exc:
            result.update(
                status="blocked",
                error_category=type(exc).__name__,
                retry_after=((now or datetime.now(UTC)) + timedelta(minutes=5)).isoformat(),
                checked_at=datetime.now(UTC).isoformat(),
            )
        results.append(result)
    return results


def save_status(path: Path, results: list[dict]) -> None:
    """Bounded atomic status plus last 64 transitions; no outcomes or secrets."""
    previous = json.loads(path.read_text()) if path.exists() else {}
    history = previous.get("transitions", [])
    brief = [{k: v for k, v in r.items() if k != "checked_at"} for r in results]
    old = [{k: v for k, v in r.items() if k != "checked_at"} for r in previous.get("results", [])]
    if brief != old:
        history = [*history, {"at": datetime.now(UTC).isoformat(), "results": brief}][-64:]
    # Keep successful collection metadata after the transition ring rotates.
    # This contains no positions, forecasts, outcomes or performance values.
    successes = dict(previous.get("last_success", {}))
    for transition in history:
        for item in transition.get("results", []):
            if item.get("status") == "complete":
                successes[item["experiment"]] = {"at": transition["at"], "day": item["day"]}
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".status-")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(
                {
                    "checked_at": datetime.now(UTC).isoformat(),
                    "results": results,
                    "transitions": history,
                    "last_success": successes,
                },
                f,
                indent=2,
            )
            f.flush()
            os.fsync(f.fileno())
        Path(temporary).replace(path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkout", type=Path, required=True)
    parser.add_argument("--experiment", type=Path, action="append", required=True)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    if ROOT.resolve() != args.checkout.resolve():
        raise ValueError("Frozen import path mismatch")
    if not args.env_file.is_file():
        raise ValueError("Local configuration missing")
    from dotenv import load_dotenv

    load_dotenv(args.env_file, override=False)
    args.state_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
    with (args.state_dir / "collector.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return 0
        status_path = args.state_dir / "status.json"
        old = json.loads(status_path.read_text()) if status_path.exists() else {}
        previous = {r["experiment"]: r for r in old.get("results", [])}
        result = poll(args.experiment, collect=not args.check_only, previous=previous)
        save_status(args.state_dir / "status.json", result)
        print(json.dumps(result))
        return 1 if any(r["status"].startswith("blocked") for r in result) else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(json.dumps({"status": "blocked", "error_category": type(error).__name__}))
        raise SystemExit(1) from None
