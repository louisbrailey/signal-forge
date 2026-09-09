"""Orchestrates the post-close universe update under strict budgets:
discovery -> bulk backfill (resumable) -> screen -> normalize eligible ->
scan enabled swing horizons. Every stage's counts are returned and audited.
Never an alert, never a paper trade, never intraday, never options."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from signalforge.config import get_settings
from signalforge.config.research import UniversePipelineConfig
from signalforge.db.models import AuditLog, BulkFile, OHLCVDaily, ScanRun
from signalforge.domain import Horizon
from signalforge.observability import get_logger
from signalforge.research.candidates import persist_scan
from signalforge.research.scan import run_scan
from signalforge.settings_store import effective_research_config
from signalforge.universe.bulk import (
    BackfillReport,
    GroupedDailyClient,
    archive_bytes,
    archived_sessions,
    backfill,
)
from signalforge.universe.discovery import DiscoveryReport, enrich_market_caps, refresh_reference
from signalforge.universe.normalize import NormalizeReport, normalize_symbols
from signalforge.universe.screen import (
    ScreenReport,
    eligible_symbols_for,
    exclusion_examples,
    latest_screen,
    run_screen,
    snapshot_summary,
)

_log = get_logger("universe.pipeline")
AUDIT_ACTION = "universe.update"
_NORMALIZED_BYTES_PER_ROW = 280  # measured on this project's SQLite (table + indexes)


@dataclass(slots=True)
class ScanStage:
    horizon: str
    scan_run_id: int
    scanned: int
    excluded: int
    no_trade: int
    qualified: int


@dataclass(slots=True)
class UniverseUpdateReport:
    started_at: str
    seconds: float = 0.0
    stopped_reason: str = ""
    discovery: dict[str, Any] | None = None
    backfill: dict[str, Any] | None = None
    market_caps_enriched: int = 0
    screen: dict[str, Any] | None = None
    normalize: dict[str, Any] | None = None
    scans: list[dict[str, Any]] = field(default_factory=list)
    storage: dict[str, Any] = field(default_factory=dict)


def storage_usage(session: Session, cfg: UniversePipelineConfig) -> dict[str, Any]:
    normalized_rows = int(
        session.scalar(
            select(func.count())
            .select_from(OHLCVDaily)
            .where(OHLCVDaily.source == cfg.normalized_source)
        )
        or 0
    )
    archive = archive_bytes(session, source=cfg.normalized_source)
    est_normalized = normalized_rows * _NORMALIZED_BYTES_PER_ROW
    url = get_settings().database_url
    db_path = Path(url.split("///", 1)[-1]) if "sqlite" in url else None
    db_bytes = db_path.stat().st_size if db_path is not None and db_path.exists() else None
    return {
        "archive_bytes": archive,
        "archive_sessions": len(archived_sessions(session, source=cfg.normalized_source)),
        "normalized_rows": normalized_rows,
        "normalized_bytes_estimate": est_normalized,
        "budget_bytes": cfg.max_storage_bytes,
        "used_bytes": archive + est_normalized,
        "used_share": round((archive + est_normalized) / cfg.max_storage_bytes, 4),
        "db_file_bytes": db_bytes,
    }


def run_universe_update(
    session: Session,
    *,
    cfg: UniversePipelineConfig | None = None,
    client: GroupedDailyClient | None = None,
    now: datetime | None = None,
    do_scan: bool = True,
    market_cap_requests: int = 250,
) -> UniverseUpdateReport:
    cfg = cfg or effective_research_config(session).universe_pipeline
    client = client or GroupedDailyClient(spacing_s=cfg.request_spacing_s)
    now = now or datetime.now(UTC)
    t0 = time.monotonic()
    deadline = t0 + cfg.max_runtime_seconds
    rep = UniverseUpdateReport(started_at=now.isoformat())

    # 1) discovery (all types counted; CS/ETF in scope)
    disc: DiscoveryReport = refresh_reference(session, client, security_types=cfg.security_types)
    rep.discovery = asdict(disc)

    # 2) resumable bulk backfill under runtime + storage budgets
    bf: BackfillReport = backfill(
        session,
        client,
        sessions=cfg.backfill_sessions,
        runtime_budget_s=cfg.max_runtime_seconds,
        storage_budget_bytes=cfg.max_storage_bytes,
        source=cfg.normalized_source,
        now=now,
        deadline=deadline,
    )
    rep.backfill = asdict(bf)
    # The archive index must survive a failure in a later stage: commit it now
    # (the bulk files are already on disk; re-downloading them would be waste).
    session.commit()
    if bf.sessions_archived == 0:
        rep.stopped_reason = "no bulk sessions archived"
        rep.seconds = round(time.monotonic() - t0, 1)
        _audit(session, rep)
        return rep

    # 3) screen (pure computation on the archive)
    sc: ScreenReport = run_screen(session, cfg, source=cfg.normalized_source, now=now)
    rep.screen = {k: v for k, v in asdict(sc).items() if k != "eligible_symbols"}

    # 3b) fill current market caps for the price/ADV survivors that lack one
    # (resumable, bounded per run; CS only — ETFs have none)
    if time.monotonic() < deadline:
        rep.market_caps_enriched = enrich_market_caps(
            session, client, sc.eligible_symbols, max_requests=market_cap_requests
        )

    # 4) normalize eligible symbols only (+ SPY proxy) under the remaining budget
    nz: NormalizeReport = normalize_symbols(
        session, sc.eligible_symbols, cfg, source=cfg.normalized_source, deadline=deadline
    )
    rep.normalize = asdict(nz)

    # 5) post-close scan of the eligible universe on the bulk source — research
    # only; candidates cannot match any approved scope (different snapshot +
    # source) and so can never alert.
    if do_scan and time.monotonic() < deadline:
        for h in effective_research_config(session).enabled_horizons:
            if h is Horizon.INTRADAY:
                continue
            result = run_scan(session, h, symbols=sc.eligible_symbols, source=cfg.normalized_source)
            run = persist_scan(session, result)
            rep.scans.append(
                asdict(
                    ScanStage(
                        horizon=h.value,
                        scan_run_id=run.id,
                        scanned=run.scanned_count,
                        excluded=run.excluded_count,
                        no_trade=run.no_trade_count,
                        qualified=run.candidate_count,
                    )
                )
            )
    elif do_scan:
        rep.stopped_reason = "runtime budget reached before scan"

    rep.storage = storage_usage(session, cfg)
    rep.seconds = round(time.monotonic() - t0, 1)
    _audit(session, rep)
    _log.info(
        "universe.update.done",
        seconds=rep.seconds,
        eligible=sc.eligible,
        scans=[(s["horizon"], s["qualified"]) for s in rep.scans],
        stopped=rep.stopped_reason,
    )
    return rep


def report_payload(rep: UniverseUpdateReport) -> dict[str, Any]:
    """JSON-safe copy of the report (dates -> ISO strings)."""
    return json.loads(json.dumps(asdict(rep), default=str))


def _audit(session: Session, rep: UniverseUpdateReport) -> None:
    session.add(
        AuditLog(
            ts=datetime.now(UTC),
            actor="scheduler",
            action=AUDIT_ACTION,
            entity="universe_pipeline",
            before_json={},
            after_json=report_payload(rep),
        )
    )
    session.flush()


def universe_status(session: Session) -> dict[str, Any]:
    """Read-only status for the /universe page and the CLI."""
    cfg = effective_research_config(session).universe_pipeline
    run = latest_screen(session)
    last_update = session.scalar(
        select(AuditLog)
        .where(AuditLog.action == AUDIT_ACTION)
        .order_by(AuditLog.ts.desc())
        .limit(1)
    )
    scans: list[dict[str, Any]] = []
    for h in effective_research_config(session).enabled_horizons:
        sr = session.scalar(
            select(ScanRun)
            .where(ScanRun.horizon == h, ScanRun.source == cfg.normalized_source)
            .order_by(ScanRun.started_at.desc())
            .limit(1)
        )
        if sr is not None:
            scans.append(
                {
                    "horizon": h.value,
                    "started_at": sr.started_at.isoformat(),
                    "scanned": sr.scanned_count,
                    "excluded": sr.excluded_count,
                    "no_trade": sr.no_trade_count,
                    "qualified": sr.candidate_count,
                    "dataset_snapshot_id": sr.dataset_snapshot_id,
                }
            )
    failed_files = int(
        session.scalar(
            select(func.count()).select_from(BulkFile).where(BulkFile.status == "failed")
        )
        or 0
    )
    return {
        "enabled": cfg.enabled,
        "config": cfg.model_dump(mode="json"),
        "screen": snapshot_summary(run) if run else None,
        "exclusion_examples": exclusion_examples(session, run.id) if run else {},
        "eligible_preview": eligible_symbols_for(session, run.id)[:40] if run else [],
        "storage": storage_usage(session, cfg),
        "failed_bulk_files": failed_files,
        "scans": scans,
        "last_update": (
            {"at": last_update.ts.isoformat(), **(last_update.after_json or {})}
            if last_update
            else None
        ),
        "disclaimer": (
            "Discovery/screening universe: split-adjusted as of fetch date (NOT point-in-time), "
            "active-only (NOT survivorship-free), END-OF-DAY. Never a promotion universe; "
            "candidates here cannot match any approved scope and never alert."
        ),
    }
