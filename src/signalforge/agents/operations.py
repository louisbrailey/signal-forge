"""Operations agent (read-only).

Reports the operator-facing facts already recorded by the scheduler, the
kill switch, and the audit log: worker liveness, per-job last outcomes,
daily-bar freshness / catch-up status, the kill switch's current state,
backups, and audit-log integrity. Never starts, stops, or reconfigures
anything.

Import-boundary note (S14, ``pyproject.toml``): this module deliberately does
NOT import ``signalforge.scheduler``, ``signalforge.app.views``, or
``signalforge.killswitch``. ``signalforge.killswitch`` is forbidden outright;
``signalforge.scheduler`` imports it directly (plus ``signalforge.research.scan``,
``signalforge.data.ingest``, ``signalforge.paper.ledger``, and more); and
``signalforge.app.views`` imports both ``signalforge.killswitch`` and
``signalforge.research.persistence`` at module level. All three would break
import-linter contract S14 if imported here, even though the specific facts
this agent needs from them (a heartbeat row, a job's last outcome, "is a
catch-up owed", the kill switch's current state) are themselves read-only.
Those facts are read directly instead: DB rows via ``signalforge.db.models``,
and the kill-switch state via its own JSON state file (located with
``signalforge.config.paths``, never via ``signalforge.killswitch``).
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from signalforge.agents.base import ResearchAgent
from signalforge.config import get_settings, paths
from signalforge.data.feeds import feed_status_report
from signalforge.db.models import AuditLog, IngestionRun, JobRun, WorkerHeartbeat
from signalforge.domain import FeedType

# The constants below mirror signalforge.scheduler's own values. They are
# duplicated, not imported — see the module docstring for why.
_HEARTBEAT_INTERVAL_S = 30
_WORKER_STALE_AFTER_S = 3 * _HEARTBEAT_INTERVAL_S
_EOD_CRON = (17, 30)  # America/New_York
_CATCH_UP_RETRY_BACKOFF = timedelta(hours=2)


def _last_completed_session(now: datetime) -> date:
    """Reproduces ``signalforge.scheduler.last_completed_session`` — see
    ``signalforge.agents.data_quality`` for the same helper and why it is
    duplicated instead of imported."""
    n = now.astimezone(ZoneInfo("America/New_York"))
    d = n.date()
    if n.weekday() >= 5 or (n.hour, n.minute) < _EOD_CRON:
        d -= timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def _session_cutoff_utc(session_date: date) -> datetime:
    """Reproduces ``signalforge.scheduler._session_cutoff_utc``."""
    return datetime(
        session_date.year,
        session_date.month,
        session_date.day,
        _EOD_CRON[0],
        _EOD_CRON[1],
        tzinfo=ZoneInfo("America/New_York"),
    ).astimezone(UTC)


def _read_kill_switch_state(path: Path, now: datetime) -> dict[str, Any]:
    """Reads the kill switch's own JSON state file directly. Deliberately NOT
    ``signalforge.killswitch.KillSwitch.state()`` (forbidden import, S14) —
    same fail-safe semantics (a missing/unreadable/corrupt file reads as "not
    engaged"), reproduced by hand against the plain JSON payload."""
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {
            "active": False,
            "reason": "no kill-switch state file on disk (never engaged)",
            "actor": None,
            "changed_at": None,
            "source": "filesystem:kill_switch.json",
            "as_of": now.isoformat(),
        }
    except OSError as exc:
        return {
            "active": False,
            "reason": f"kill-switch state file unreadable: {exc}",
            "actor": None,
            "changed_at": None,
            "source": "filesystem:kill_switch.json",
            "as_of": now.isoformat(),
        }
    try:
        data = json.loads(raw)
        return {
            "active": bool(data["active"]),
            "reason": str(data.get("reason", "")),
            "actor": str(data.get("actor", "unknown")),
            "changed_at": data.get("changed_at"),
            "source": "filesystem:kill_switch.json",
            "as_of": now.isoformat(),
        }
    except (json.JSONDecodeError, KeyError, ValueError):
        return {
            "active": False,
            "reason": "kill-switch state file corrupt (treated as not engaged)",
            "actor": None,
            "changed_at": None,
            "source": "filesystem:kill_switch.json",
            "as_of": now.isoformat(),
        }


class OperationsAgent(ResearchAgent):
    """A short operator digest built entirely from already-recorded rows and
    the kill switch's own state file. Never starts/stops a job, never
    engages/releases the kill switch, never writes a setting."""

    name = "operations"
    role = "Operations agent"
    allowed_inputs = (
        "signalforge.db.models.WorkerHeartbeat",
        "signalforge.db.models.JobRun",
        "signalforge.db.models.AuditLog",
        "signalforge.db.models.IngestionRun",
        "signalforge.data.feeds.feed_status_report",
        "signalforge.config.paths (kill_switch_state_path, data_dir)",
    )
    outputs = (
        "operator_digest",
        "job_outcomes",
        "kill_switch_state",
        "backup_status",
        "audit_log_integrity",
    )
    prohibited = (
        "start_job",
        "stop_job",
        "engage_kill_switch",
        "release_kill_switch",
        "restart_worker",
        "write_setting",
    )
    llm_narrative = False

    def collect(self, session: Session) -> dict[str, Any]:
        now = datetime.now(UTC)
        missing: list[str] = []

        # --- worker heartbeat --------------------------------------------
        hb = session.scalar(select(WorkerHeartbeat).where(WorkerHeartbeat.worker == "scheduler"))
        next_runs: dict[str, Any] = {}
        if hb is None:
            missing.append(
                "no worker heartbeat recorded yet — the scheduler may never have started"
            )
            worker: dict[str, Any] = {
                "seen": False,
                "running": False,
                "host": None,
                "pid": None,
                "started_at": None,
                "last_beat_at": None,
                "beat_age_s": None,
                "detail": "",
                "source": "signalforge.db.models.WorkerHeartbeat",
                "as_of": now.isoformat(),
            }
        else:
            beat_age = (now - hb.last_beat_at).total_seconds()
            next_runs = dict(hb.next_runs_json or {})
            worker = {
                "seen": True,
                "running": beat_age <= _WORKER_STALE_AFTER_S,
                "host": hb.host,
                "pid": hb.pid,
                "started_at": hb.started_at.isoformat(),
                "last_beat_at": hb.last_beat_at.isoformat(),
                "beat_age_s": round(beat_age),
                "detail": hb.detail,
                "source": "signalforge.db.models.WorkerHeartbeat",
                "as_of": now.isoformat(),
            }

        # --- per-job last outcome ------------------------------------------
        job_names = sorted(set(session.scalars(select(JobRun.name).distinct())))
        if not job_names:
            missing.append("no job runs recorded yet")
        jobs: list[dict[str, Any]] = []
        failed_jobs: list[str] = []
        for jn in job_names:
            last = session.scalar(
                select(JobRun).where(JobRun.name == jn).order_by(JobRun.started_at.desc()).limit(1)
            )
            if last is None:
                continue
            last_ok = session.scalar(
                select(JobRun)
                .where(JobRun.name == jn, JobRun.status == "ok")
                .order_by(JobRun.started_at.desc())
                .limit(1)
            )
            if last.status == "failed":
                failed_jobs.append(jn)
            jobs.append(
                {
                    "name": jn,
                    "status": last.status,
                    "started_at": last.started_at.isoformat(),
                    "finished_at": last.finished_at.isoformat() if last.finished_at else None,
                    "detail": last.detail if last.status in ("failed", "skipped") else "",
                    "last_success_at": last_ok.started_at.isoformat() if last_ok else None,
                    "next_run": next_runs.get(jn),
                    "source": "signalforge.db.models.JobRun",
                    "as_of": last.started_at.isoformat(),
                }
            )

        # --- daily-bar freshness + catch-up pending (independent, --------
        # --- simplified recomputation; see module docstring) --------------
        settings = get_settings()
        provider = settings.market_data_provider or "fixture"
        expected_session = _last_completed_session(now)
        cutoff = _session_cutoff_utc(expected_session)
        last_ok_ingest = session.scalar(
            select(IngestionRun.finished_at)
            .where(IngestionRun.feed_type == FeedType.BAR_DAILY, IngestionRun.status == "ok")
            .order_by(IngestionRun.finished_at.desc())
            .limit(1)
        )
        last_failed_eod = session.scalar(
            select(JobRun)
            .where(JobRun.name.in_(("daily_eod_update", "catch_up")), JobRun.status == "failed")
            .order_by(JobRun.started_at.desc())
            .limit(1)
        )
        if last_ok_ingest is not None and last_ok_ingest >= cutoff:
            catch_up = {
                "pending": False,
                "reason": f"daily bars ingested at {last_ok_ingest.isoformat()}",
            }
        elif (
            last_failed_eod is not None
            and now - last_failed_eod.started_at < _CATCH_UP_RETRY_BACKOFF
        ):
            catch_up = {
                "pending": False,
                "reason": (
                    f"owed for {expected_session.isoformat()} but backing off after a failed "
                    f"attempt at {last_failed_eod.started_at.isoformat()}"
                ),
            }
        else:
            catch_up = {
                "pending": True,
                "reason": (
                    f"no OK daily-bar ingestion since the {expected_session.isoformat()} close"
                ),
            }
        catch_up["note"] = (
            "independent, simplified recomputation of signalforge.scheduler.catch_up_pending "
            "(that module cannot be imported here under contract S14)"
        )
        catch_up["source"] = "signalforge.db.models.IngestionRun/JobRun"
        catch_up["as_of"] = now.isoformat()

        # --- kill switch state ----------------------------------------------
        kill_switch = _read_kill_switch_state(paths.kill_switch_state_path(), now)

        # --- stale feeds --------------------------------------------------
        feeds = feed_status_report(session)
        if not feeds["feeds"]:
            missing.append("no data feeds registered yet")
        stale_feeds = [f"{f['provider']}/{f['feed_type']}" for f in feeds["feeds"] if f["is_stale"]]

        # --- backups --------------------------------------------------------
        backups_path = paths.data_dir() / "backups"
        if backups_path.is_dir():
            entries = sorted(backups_path.iterdir())
            newest_mtime = max((e.stat().st_mtime for e in entries), default=None)
            backups = {
                "path": str(backups_path),
                "count": len(entries),
                "newest_mtime": (
                    datetime.fromtimestamp(newest_mtime, tz=UTC).isoformat()
                    if newest_mtime is not None
                    else None
                ),
                "source": "filesystem:backups",
                "as_of": now.isoformat(),
            }
            if not entries:
                missing.append("backups directory exists but is empty")
        else:
            missing.append("no backups directory")
            backups = {
                "path": str(backups_path),
                "count": 0,
                "newest_mtime": None,
                "source": "filesystem:backups",
                "as_of": now.isoformat(),
            }

        # --- audit-log integrity ---------------------------------------------
        day_ago = now - timedelta(hours=24)
        count_24h = int(
            session.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.ts >= day_ago))
            or 0
        )
        max_id = session.scalar(select(func.max(AuditLog.id)))
        job_failed_24h = int(
            session.scalar(
                select(func.count())
                .select_from(AuditLog)
                .where(AuditLog.action == "job.failed", AuditLog.ts >= day_ago)
            )
            or 0
        )
        last_rows = list(session.scalars(select(AuditLog).order_by(AuditLog.id.desc()).limit(200)))
        last_rows.sort(key=lambda r: r.id)
        monotonic = True
        prev_ts: datetime | None = None
        for row in last_rows:
            if prev_ts is not None and row.ts < prev_ts:
                monotonic = False
                break
            prev_ts = row.ts
        if max_id is None:
            missing.append("audit_log is empty")
        audit_integrity = {
            "count_last_24h": count_24h,
            "max_id": max_id,
            "job_failed_last_24h": job_failed_24h,
            "ts_monotonic_last_200": monotonic,
            "rows_checked": len(last_rows),
            "source": "signalforge.db.models.AuditLog",
            "as_of": now.isoformat(),
        }

        # --- worker.lock presence ---------------------------------------------
        lock_path = paths.data_dir() / "worker.lock"
        worker_lock = {
            "present": lock_path.exists(),
            "path": str(lock_path),
            "source": "filesystem:worker.lock",
            "as_of": now.isoformat(),
        }

        readiness = {
            "worker_running": worker["running"],
            "kill_switch_engaged": kill_switch["active"],
            "any_stale_feed": bool(stale_feeds),
            "catch_up_pending": catch_up["pending"],
            "any_job_last_run_failed": bool(failed_jobs),
        }

        return {
            "as_of": now.isoformat(),
            "worker": worker,
            "jobs": jobs,
            "failed_jobs": failed_jobs,
            "freshness": {
                "provider": provider,
                "expected_session": expected_session.isoformat(),
            },
            "catch_up": catch_up,
            "kill_switch": kill_switch,
            "stale_feeds": stale_feeds,
            "backups": backups,
            "audit_integrity": audit_integrity,
            "worker_lock": worker_lock,
            "readiness": readiness,
            "missing_data": missing,
        }

    def summarize(self, evidence: dict[str, Any]) -> str:
        lines: list[str] = [f"Operator digest as of {evidence['as_of']}."]

        w = evidence["worker"]
        if w["seen"]:
            state = "running" if w["running"] else f"STALE (last beat {w['beat_age_s']}s ago)"
            lines.append(f"Scheduler worker: {state} (host={w['host']}, pid={w['pid']}).")
        else:
            lines.append("Scheduler worker: no heartbeat recorded — it may never have started.")

        ks = evidence["kill_switch"]
        ks_state = "ENGAGED" if ks["active"] else "not engaged"
        lines.append(f"Kill switch: {ks_state} ({ks['reason']}).")

        if evidence["failed_jobs"]:
            lines.append(
                f"Jobs whose last run FAILED ({len(evidence['failed_jobs'])}): "
                + ", ".join(evidence["failed_jobs"])
                + "."
            )
        elif evidence["jobs"]:
            lines.append(f"All {len(evidence['jobs'])} tracked job(s) last ran without failure.")
        else:
            lines.append("No job runs have been recorded yet.")

        cu = evidence["catch_up"]
        cu_state = "PENDING" if cu["pending"] else "not pending"
        lines.append(f"Daily EOD catch-up: {cu_state} ({cu['reason']}).")

        if evidence["stale_feeds"]:
            stale_names = ", ".join(evidence["stale_feeds"])
            lines.append(f"Stale feeds ({len(evidence['stale_feeds'])}): {stale_names}.")
        else:
            lines.append("No feeds are currently flagged stale.")

        b = evidence["backups"]
        lines.append(
            f"Backups: {b['count']} file(s) under {b['path']} (newest: {b['newest_mtime']})."
        )

        ai = evidence["audit_integrity"]
        lines.append(
            f"Audit log: {ai['count_last_24h']} event(s) in the last 24h, "
            f"{ai['job_failed_last_24h']} job.failed, timestamps "
            f"{'monotonic' if ai['ts_monotonic_last_200'] else 'NOT MONOTONIC'} over the last "
            f"{ai['rows_checked']} row(s)."
        )

        lines.append(f"worker.lock present: {evidence['worker_lock']['present']}.")

        if evidence["missing_data"]:
            lines.append(
                f"Missing data ({len(evidence['missing_data'])}): "
                + "; ".join(evidence["missing_data"])
                + "."
            )

        return "\n".join(lines)
