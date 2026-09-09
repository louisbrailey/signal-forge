"""The scheduled approved-scope scan for a supervised paper probation.

Scans ONLY the horizons that have a PAPER_APPROVED strategy, using EXACTLY
that strategy's approved dataset (the ``ex_meta`` variant — same universe,
same source, resolved to the same ``DataSnapshot`` row the promotion
evaluation was approved on) so that the resulting candidates can pass
``research.approval_scope``'s five-way scope match. A routine scan of the
default watchlist cannot: its candidates for an approved strategy are
blocked at alert time because they do not match the approved scope.

Hard gates, in order — any failure blocks the scan and records why:

1. no stale data feed (``data.feeds.feed_status_report``);
2. the last ingestion run finished OK, recently;
3. the approved universe actually has a completed daily bar for the latest
   session (>= 90% of symbols on the newest bar date, and that date is not
   older than five calendar days).

Read-only research: creates ScanRun/Candidate rows only. Never an alert,
never a paper position, never intraday, never options, never a brokerage
call. INTRADAY is excluded explicitly even if a strategy were ever approved
on it (EOD-only operation).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from signalforge.config import get_settings
from signalforge.data.feeds import feed_status_report
from signalforge.db.models import (
    AuditLog,
    IngestionRun,
    Instrument,
    OHLCVDaily,
    ScanRun,
    Strategy,
)
from signalforge.db.retry import retry_on_lock
from signalforge.domain import FeedType, Horizon, StrategyStatus
from signalforge.observability import get_logger
from signalforge.research.candidates import persist_scan
from signalforge.research.fb_meta_universe_comparison import resolve_variant
from signalforge.research.scan import ScanResult, run_scan

_log = get_logger("research.approved_scope_scan")

APPROVED_VARIANT = "ex_meta"
MAX_INGEST_AGE = timedelta(hours=24)
MAX_BAR_AGE_DAYS = 5
MIN_BAR_COVERAGE = 0.90
AUDIT_COMPLETED = "approved_scope_scan.completed"
AUDIT_BLOCKED = "approved_scope_scan.blocked"


@dataclass(slots=True)
class ApprovedScopeScanReport:
    ran: bool
    blocked_reason: str | None = None
    horizons: list[str] = field(default_factory=list)
    dataset_snapshot_id: int | None = None
    dataset_key: str | None = None
    n_symbols: int = 0
    runs: list[dict[str, Any]] = field(default_factory=list)

    @property
    def total_candidates(self) -> int:
        return sum(int(r["candidates"]) for r in self.runs)


def approved_horizons(session: Session) -> list[Horizon]:
    """Distinct horizons of every PAPER_APPROVED strategy, INTRADAY excluded."""
    rows = session.execute(
        select(Strategy.horizon).where(Strategy.status == StrategyStatus.PAPER_APPROVED).distinct()
    ).all()
    return sorted({h for (h,) in rows if h is not Horizon.INTRADAY}, key=lambda h: h.value)


def data_readiness(
    session: Session,
    symbols: list[str],
    *,
    source: str,
    now: datetime | None = None,
) -> str | None:
    """Return a human-readable block reason, or ``None`` when the data is fresh
    and complete enough to scan on."""
    now = now or datetime.now(UTC)

    # The daily-bar feed of the source this scan reads from. (The alert
    # dispatcher separately blocks on ANY stale feed at alert time — that
    # broader gate is unchanged; this one must not be blocked forever by an
    # unrelated options/news/secondary feed nobody is using.)
    feeds = [
        f
        for f in feed_status_report(session)["feeds"]
        if f["provider"] == source and f["feed_type"] == FeedType.BAR_DAILY.value
    ]
    if not feeds:
        return (
            f"no {source}/{FeedType.BAR_DAILY.value} feed registered yet — run an ingestion first"
        )
    stale = [f"{f['provider']}/{f['feed_type']}" for f in feeds if f["is_stale"]]
    if stale:
        return "stale feed: " + ", ".join(stale)

    # The DAILY-BAR ingestion specifically — an options backfill or a news
    # poll finishing "ok" says nothing about whether today's closes are in.
    last_ingest = session.scalar(
        select(IngestionRun)
        .where(IngestionRun.feed_type == FeedType.BAR_DAILY)
        .order_by(IngestionRun.started_at.desc())
        .limit(1)
    )
    if last_ingest is None:
        return "no daily-bar ingestion run recorded yet"
    if last_ingest.status != "ok":
        return f"last ingestion run is {last_ingest.status!r}, not ok"
    finished = last_ingest.finished_at or last_ingest.started_at
    if now - finished > MAX_INGEST_AGE:
        return f"last ok ingestion finished {finished.isoformat()} — older than {MAX_INGEST_AGE}"

    if not symbols:
        return "approved universe is empty"
    latest_by_symbol: dict[str, date] = {
        str(sym): d
        for sym, d in session.execute(
            select(Instrument.symbol, func.max(OHLCVDaily.session_date))
            .join(OHLCVDaily, OHLCVDaily.instrument_id == Instrument.id)
            .where(Instrument.symbol.in_(symbols), OHLCVDaily.source == source)
            .group_by(Instrument.symbol)
        ).all()
        if d is not None
    }
    if not latest_by_symbol:
        return f"no daily bars from {source!r} for any approved-universe symbol"
    newest: date = max(latest_by_symbol.values())
    if (now.date() - newest).days > MAX_BAR_AGE_DAYS:
        return f"newest daily bar is {newest.isoformat()} — older than {MAX_BAR_AGE_DAYS} days"
    on_newest = len([d for d in latest_by_symbol.values() if d == newest])
    coverage = on_newest / len(symbols)
    if coverage < MIN_BAR_COVERAGE:
        missing = sorted(s for s in symbols if latest_by_symbol.get(s) != newest)
        return (
            f"incomplete data: only {on_newest}/{len(symbols)} approved symbols have a bar for "
            f"{newest.isoformat()} (missing: {', '.join(missing[:8])}"
            f"{'…' if len(missing) > 8 else ''})"
        )
    return None


def _audit(session: Session, action: str, payload: dict[str, Any]) -> None:
    session.add(
        AuditLog(
            ts=datetime.now(UTC),
            actor="scheduler",
            action=action,
            entity="approved_scope_scan",
            before_json={},
            after_json=payload,
        )
    )
    session.flush()


def run_approved_scope_scan(
    session: Session,
    *,
    source: str | None = None,
    now: datetime | None = None,
    enforce_readiness: bool = True,
) -> ApprovedScopeScanReport:
    """Run the approved-scope scan (or record exactly why it was blocked)."""
    source = source or get_settings().market_data_provider
    horizons = approved_horizons(session)
    if not horizons:
        report = ApprovedScopeScanReport(ran=False, blocked_reason="no PAPER_APPROVED strategy")
        _audit(session, AUDIT_BLOCKED, {"reason": report.blocked_reason})
        return report

    symbols, snap = resolve_variant(session, variant=APPROVED_VARIANT)
    report = ApprovedScopeScanReport(
        ran=False,
        horizons=[h.value for h in horizons],
        dataset_snapshot_id=snap.id,
        dataset_key=snap.key,
        n_symbols=len(symbols),
    )

    if enforce_readiness:
        reason = data_readiness(session, symbols, source=source, now=now)
        if reason is not None:
            report.blocked_reason = reason
            _log.warning("approved_scope_scan.blocked", reason=reason)
            _audit(
                session,
                AUDIT_BLOCKED,
                {"reason": reason, "dataset_snapshot_id": snap.id, "horizons": report.horizons},
            )
            return report

    for h in horizons:

        def _one(hz: Horizon = h) -> tuple[ScanResult, ScanRun]:
            res = run_scan(session, hz, symbols=symbols, source=source)
            return res, persist_scan(session, res)

        # per-horizon lock retry: never re-run an already-persisted horizon
        result, run = retry_on_lock(_one, label=f"approved_scope_scan:{h.value}")
        # run_scan resolves its own DataSnapshot (by exact symbol set). It must
        # be the very row the strategies were approved on — otherwise every
        # candidate would silently fail the scope match at alert time. Refuse
        # loudly instead of trusting it.
        if run.dataset_snapshot_id != snap.id:
            reason = (
                f"scan for {h.value} resolved dataset_snapshot_id={run.dataset_snapshot_id}, "
                f"expected approved snapshot {snap.id} ({snap.key!r})"
            )
            _audit(session, AUDIT_BLOCKED, {"reason": reason, "scan_run_id": run.id})
            raise RuntimeError(reason)
        report.runs.append(
            {
                "horizon": h.value,
                "scan_run_id": run.id,
                "scanned": len(result.scanned),
                "candidates": run.candidate_count,
                "no_trade": run.no_trade_count,
                "dataset_snapshot_id": run.dataset_snapshot_id,
            }
        )
    report.ran = True
    _audit(
        session,
        AUDIT_COMPLETED,
        {
            "dataset_snapshot_id": snap.id,
            "dataset_key": snap.key,
            "n_symbols": len(symbols),
            "source": source,
            "readiness_enforced": enforce_readiness,
            "runs": report.runs,
        },
    )
    _log.info(
        "approved_scope_scan.done",
        horizons=report.horizons,
        candidates=report.total_candidates,
        dataset_snapshot_id=snap.id,
    )
    return report
