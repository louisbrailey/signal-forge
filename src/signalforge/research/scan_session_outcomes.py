"""One explicit outcome per approved scope per completed session.

Incident 2026-10-08..11-06: ``trend_continuation.short_swing`` (approved scope
on snapshot 3) got a real scan on only 13 of 22 sessions. Of the nine gaps,
three (10-14, 10-19, 10-20) carried an ``approved_scope_scan.completed`` row
with nothing scanned, and two (10-21, 11-05) had no attempt and no record at
all. Two causes:

* an ``approved_scope_scan.completed`` audit row was written even when the
  scan's own gates excluded every symbol (``scanned=0``), so a session nothing
  was scanned on looked scanned;
* ``scheduler.missed_sessions`` only owed sessions AFTER the newest completed
  row, so a later session's scan landing first moved the start point past an
  earlier gap and that session was passed over silently.

This module is the per-session ledger that closes both. Each approved scope
(one ``(dataset snapshot, horizon, source)`` scan group) gets exactly ONE
``approved_scope_scan.session_outcome`` audit row per completed session in its
approved window, once that session can no longer be scanned (a later
session's bar is the one any scan now requires): either ``scanned`` or
``skipped`` with a reason — ``readiness_blocked``, ``data_hold`` (the scan ran
but excluded every symbol, mostly for stale or missing data), ``all_excluded``
(the scan ran but its other gates — liquidity, earnings window, no strategy
for the horizon — excluded every symbol), ``scan_failed`` or ``missed`` (no
attempt at all: worker asleep or stopped, EOD chain failed before the scan,
kill switch).

Bound: the guarantee holds within the scheduler's look-back
(``catch_up_lookback_sessions``, default 10 sessions). A session that closed
more than that many sessions before the worker next ran (a stop or kill
switch of more than about two weeks) is never written; the read-only CLI
still shows it, marked ``UNRECORDED``, from the evidence on record.

A scope's approved window is read from the attempt rows themselves: it runs
from the first attempt that lists the scope to the first full attempt that
does not (the scope left the approved set). A scope that has since left the
approved set is still closed out for the sessions inside its window. A session
with no attempt at all between the scope's last listing and the attempt that
dropped it is counted inside the window (the drop time is not on record), so
the gap is recorded as ``missed`` rather than passed over.

The outcome is DERIVED from evidence already on record (attempt audit rows and
job runs), never produced by running anything. A past session is NEVER
scanned after the fact: an as-of scan is not point-in-time safe and paper must
never act on a stale signal (see the ``scheduler`` multi-session catch-up note).
A skipped session gets a record, not a scan.

Session attribution: an attempt at time ``t`` belongs to
``data.calendar.last_closed_session(t)`` — the exact ``required_bar_date`` the
scan's own stale-data gate demanded, so a ``scanned`` attribution is the bar
that was really scanned.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from signalforge.data.calendar import last_closed_session, rth_bounds_utc, sessions
from signalforge.db.models import AuditLog, JobRun, ScanRun
from signalforge.observability import get_logger
from signalforge.research.approved_scope_scan import (
    AUDIT_BLOCKED,
    AUDIT_COMPLETED,
    AUDIT_NOTHING_SCANNED,
    ApprovedScanGroup,
    approved_scan_groups,
)
from signalforge.research.scan import Exclusion

_log = get_logger("research.scan_session_outcomes")

SESSION_OUTCOME_ACTION = "approved_scope_scan.session_outcome"
ATTEMPT_ACTIONS = (AUDIT_COMPLETED, AUDIT_NOTHING_SCANNED, AUDIT_BLOCKED)

# Job names owned by ``signalforge.scheduler`` (which imports this module, so
# they are repeated here; a test pins them to the scheduler's constants).
SCAN_JOBS = ("approved_scope_scan", "catchup_approved_scope_scan")
MISSED_SKIP_JOB = "scan_skipped_missed_session"
CONTEXT_JOBS = (
    "daily_eod_update",
    "catch_up",
    "catchup_ingest",
    "catchup_scan",
    "catch_up_missed_sessions",
    "catchup_ingest_session",
    *SCAN_JOBS,
)

SCANNED = "scanned"
SKIPPED = "skipped"
OPEN = "open"  # display only: the session whose bar is still the one to scan
NOT_IN_SCOPE = "not_in_scope"  # display only: outside the scope's approved window
REASON_READINESS = "readiness_blocked"
REASON_DATA_HOLD = "data_hold"
REASON_ALL_EXCLUDED = "all_excluded"
REASON_FAILED = "scan_failed"
REASON_MISSED = "missed"

# Exclusions that mean "the data was not there" — when these make up most of
# a nothing-scanned run's exclusions the session is a data hold; otherwise the
# scan's other gates (liquidity, earnings window, no strategy) emptied it.
DATA_EXCLUSIONS = frozenset({Exclusion.STALE_DATA.value, Exclusion.MISSING_DATA.value})

NOT_IN_SCOPE_DETAIL = (
    "outside this scope's approved window: not in the approved set on this session, "
    "or before its first approved-scope attempt"
)

RECORD_NOTE = (
    "record only — a past session is never scanned after the fact (an as-of scan is not "
    "point-in-time safe and paper must never act on a stale signal)"
)


@dataclass(frozen=True, slots=True, order=True)
class ScopeKey:
    """One approved-scope scan group's identity."""

    dataset_snapshot_id: int
    horizon: str
    source: str

    @property
    def token(self) -> str:
        return f"{self.dataset_snapshot_id}:{self.horizon}:{self.source}"

    @classmethod
    def of(cls, group: ApprovedScanGroup) -> ScopeKey:
        return cls(group.dataset_snapshot_id, group.horizon.value, group.source)

    @classmethod
    def parse(cls, snapshot: Any, horizon: Any, source: Any) -> ScopeKey | None:
        if snapshot is None or not horizon or not source:
            return None
        try:
            return cls(int(snapshot), str(horizon), str(source))
        except (TypeError, ValueError):
            return None


@dataclass(frozen=True, slots=True)
class _Fact:
    ts: datetime
    kind: str  # "scan" | "blocked" | "failed"
    scanned: int = 0
    detail: str = ""
    audit_id: int | None = None
    scan_run_id: int | None = None
    job_run_id: int | None = None
    excluded: tuple[tuple[str, int], ...] | None = None  # per-reason counts, when on record


@dataclass(slots=True)
class _Run:
    """One continuous stretch of a scope in the approved set, in sessions."""

    start: date
    last_seen: date
    absent_from: date | None = None  # session of the first full attempt without the scope

    def covers(self, day: date) -> bool:
        if day < self.start:
            return False
        return self.absent_from is None or day < self.absent_from or day <= self.last_seen


@dataclass(slots=True)
class _ScopeHistory:
    runs: list[_Run] = field(default_factory=list)
    dataset_key: str = ""
    strategy_version_ids: tuple[int, ...] = ()

    def covers(self, day: date) -> bool:
        return any(r.covers(day) for r in self.runs)

    def after_last_listing(self, day: date) -> bool:
        """Inside a CLOSED run but after its last listing: the scope was
        dropped some time between, so its approval on ``day`` is inferred."""
        return any(
            r.covers(day) and r.absent_from is not None and day > r.last_seen for r in self.runs
        )


@dataclass(slots=True)
class _Evidence:
    by_scope: dict[tuple[date, ScopeKey], list[_Fact]] = field(default_factory=dict)
    failed: dict[date, list[_Fact]] = field(default_factory=dict)
    attempted: set[date] = field(default_factory=set)
    context: dict[date, list[JobRun]] = field(default_factory=dict)
    skip_rows: dict[date, int] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SessionOutcome:
    session_date: date
    scope: ScopeKey
    dataset_key: str
    strategy_version_ids: tuple[int, ...]
    outcome: str  # scanned | skipped (| open | not_in_scope for display)
    reason: str
    detail: str
    evidence: dict[str, Any]
    recorded: bool = False
    record_id: int | None = None
    approved_now: bool = True

    def payload(self) -> dict[str, Any]:
        return {
            "session": self.session_date.isoformat(),
            "scope": self.scope.token,
            "dataset_snapshot_id": self.scope.dataset_snapshot_id,
            "dataset_key": self.dataset_key,
            "horizon": self.scope.horizon,
            "source": self.scope.source,
            "strategy_version_ids": list(self.strategy_version_ids),
            "outcome": self.outcome,
            "reason": self.reason,
            "detail": self.detail,
            "evidence": self.evidence,
            "note": RECORD_NOTE,
        }


# --------------------------------------------------------------------------- #
# session arithmetic
# --------------------------------------------------------------------------- #
def _one_line(text: object) -> str:
    return " ".join(str(text or "").split())


def _aware(ts: datetime) -> datetime:
    return ts if ts.tzinfo is not None else ts.replace(tzinfo=UTC)


def attempt_session(ts: datetime) -> date:
    """The session whose bar an attempt at ``ts`` required (the scan's own
    ``required_bar_date``)."""
    return last_closed_session(_aware(ts))


def _close_utc(day: date) -> datetime:
    bounds = rth_bounds_utc(day)
    if bounds is None:  # not a session: fall back to midnight UTC of that day
        return datetime(day.year, day.month, day.day, tzinfo=UTC)
    return bounds[1]


def closed_sessions(now: datetime, n: int) -> list[date]:
    """The ``n`` most recent sessions that can no longer be scanned at
    ``now`` (strictly before the session whose bar a scan now requires),
    oldest first."""
    if n <= 0:
        return []
    current = attempt_session(now)
    window = [d for d in sessions(current - timedelta(days=n * 2 + 14), current) if d < current]
    return window[-n:]


# --------------------------------------------------------------------------- #
# evidence
# --------------------------------------------------------------------------- #
def _excluded_counts(raw: Any) -> tuple[tuple[str, int], ...] | None:
    if not isinstance(raw, dict):
        return None
    out = []
    for reason, v in sorted(raw.items()):
        try:
            out.append((str(reason), int(v)))
        except (TypeError, ValueError):
            continue
    return tuple(out)


def _facts_from_audit(row: AuditLog) -> tuple[list[tuple[ScopeKey, _Fact]], bool]:
    """Per-scope facts in one attempt audit row, and whether the row counts
    as a readiness-enforced attempt at all."""
    payload = row.after_json or {}
    ts = _aware(row.ts)
    out: list[tuple[ScopeKey, _Fact]] = []
    if row.action in (AUDIT_COMPLETED, AUDIT_NOTHING_SCANNED):
        if not payload.get("readiness_enforced", True):
            return [], False  # a manual --force run is not evidence for a session
        for r in payload.get("runs") or []:
            key = ScopeKey.parse(r.get("dataset_snapshot_id"), r.get("horizon"), r.get("source"))
            if key is None:
                continue
            out.append(
                (
                    key,
                    _Fact(
                        ts,
                        "scan",
                        scanned=int(r.get("scanned") or 0),
                        audit_id=row.id,
                        scan_run_id=r.get("scan_run_id"),
                        excluded=_excluded_counts(r.get("excluded")),
                    ),
                )
            )
        blocked_rows: Iterable[dict[str, Any]] = payload.get("blocked_universes") or []
    else:  # AUDIT_BLOCKED
        if "scan_run_id" in payload:
            # post-scan scope verification refused the run and raised: the job
            # failed, and its failed JobRun carries the outcome
            return [], False
        blocked_rows = [payload]
    for b in blocked_rows:
        for horizon in b.get("horizons") or []:
            key = ScopeKey.parse(b.get("dataset_snapshot_id"), horizon, b.get("source"))
            if key is not None:
                out.append(
                    (key, _Fact(ts, "blocked", detail=str(b.get("reason") or ""), audit_id=row.id))
                )
    return out, True


def _load_evidence(session: Session, days: list[date], now: datetime) -> _Evidence:
    ev = _Evidence()
    if not days:
        return ev
    wanted = set(days)
    lo = _close_utc(min(days))
    for row in session.scalars(
        select(AuditLog)
        .where(AuditLog.action.in_(ATTEMPT_ACTIONS), AuditLog.ts >= lo, AuditLog.ts <= now)
        .order_by(AuditLog.ts, AuditLog.id)
    ):
        day = attempt_session(row.ts)
        if day not in wanted:
            continue
        facts, attempted = _facts_from_audit(row)
        if attempted:
            ev.attempted.add(day)
        for key, fact in facts:
            ev.by_scope.setdefault((day, key), []).append(fact)
    for job in session.scalars(
        select(JobRun)
        .where(
            JobRun.name.in_((*CONTEXT_JOBS, MISSED_SKIP_JOB)),
            JobRun.started_at >= lo,
            JobRun.started_at <= now,
        )
        .order_by(JobRun.started_at, JobRun.id)
    ):
        if job.name == MISSED_SKIP_JOB:
            head = str(job.detail or "").split(":", 1)[0].strip()
            if head.startswith("session="):
                try:
                    tagged = date.fromisoformat(head[len("session=") :])
                except ValueError:
                    continue
                if tagged in wanted:
                    ev.skip_rows.setdefault(tagged, int(job.id))
            continue
        day = attempt_session(job.started_at)
        if day not in wanted:
            continue
        if job.name in SCAN_JOBS and job.status == "failed":
            ev.attempted.add(day)
            ev.failed.setdefault(day, []).append(
                _Fact(
                    _aware(job.started_at),
                    "failed",
                    detail=_one_line(job.detail)[:200],
                    job_run_id=int(job.id),
                )
            )
        if job.status not in ("ok", "running"):
            ev.context.setdefault(day, []).append(job)
    return ev


def attempted_sessions(session: Session, days: list[date], now: datetime) -> set[date]:
    """Sessions among ``days`` with any readiness-enforced approved-scope scan
    attempt on record (scanned, nothing scanned, blocked, or a failed scan
    job) — i.e. NOT silently missed. Used by ``scheduler.missed_sessions``."""
    return _load_evidence(session, days, now).attempted


def first_completed_scan_ts(session: Session, now: datetime) -> datetime | None:
    """The oldest readiness-enforced ``completed`` approved-scope scan — the
    start of the history a session can be owed against."""
    for row in session.scalars(
        select(AuditLog)
        .where(AuditLog.action == AUDIT_COMPLETED, AuditLog.ts <= now)
        .order_by(AuditLog.ts, AuditLog.id)
    ):
        if (row.after_json or {}).get("readiness_enforced", True):
            return _aware(row.ts)
    return None


def _is_full_attempt(row: AuditLog) -> bool:
    """Whether the row lists EVERY scope the attempt considered — so a scope
    missing from it was not in the approved set. ``completed`` /
    ``nothing_scanned`` rows list scanned groups AND blocked universes; a
    ``blocked`` row for "no PAPER_APPROVED strategy" means no scope at all.
    A per-universe ``blocked`` row speaks only for its own universe."""
    if row.action in (AUDIT_COMPLETED, AUDIT_NOTHING_SCANNED):
        return True
    payload = row.after_json or {}
    return "dataset_snapshot_id" not in payload and "scan_run_id" not in payload


def _scope_histories(session: Session, now: datetime) -> dict[ScopeKey, _ScopeHistory]:
    """Every scope's approved windows, read from readiness-enforced attempt
    rows (oldest first): a run opens at the first attempt that lists the
    scope and closes at the first FULL attempt that does not. Metadata
    (dataset key, strategy versions) comes from the newest listing."""
    hist: dict[ScopeKey, _ScopeHistory] = {}
    for row in session.scalars(
        select(AuditLog)
        .where(AuditLog.action.in_(ATTEMPT_ACTIONS), AuditLog.ts <= now)
        .order_by(AuditLog.ts, AuditLog.id)
    ):
        facts, attempted = _facts_from_audit(row)
        if not attempted:
            continue
        day = attempt_session(row.ts)
        present = {k for k, _f in facts}
        for k in present:
            h = hist.setdefault(k, _ScopeHistory())
            if not h.runs or h.runs[-1].absent_from is not None:
                h.runs.append(_Run(start=day, last_seen=day))
            else:
                h.runs[-1].last_seen = day
        payload = row.after_json or {}
        meta_rows = [*(payload.get("runs") or []), *(payload.get("blocked_universes") or [])]
        if row.action == AUDIT_BLOCKED:
            meta_rows.append(payload)
        for r in meta_rows:
            for horizon in [r.get("horizon"), *(r.get("horizons") or [])]:
                key = ScopeKey.parse(r.get("dataset_snapshot_id"), horizon, r.get("source"))
                if key is None or key not in hist:
                    continue
                if r.get("dataset_key"):
                    hist[key].dataset_key = str(r["dataset_key"])
                if r.get("strategy_version_ids"):
                    hist[key].strategy_version_ids = tuple(
                        int(v) for v in r["strategy_version_ids"]
                    )
        if _is_full_attempt(row):
            for k, h in hist.items():
                if k not in present and h.runs and h.runs[-1].absent_from is None:
                    h.runs[-1].absent_from = day
    return hist


def _recorded(session: Session, days: list[date]) -> dict[tuple[date, str], AuditLog]:
    out: dict[tuple[date, str], AuditLog] = {}
    if not days:
        return out
    for row in session.scalars(
        select(AuditLog)
        .where(AuditLog.action == SESSION_OUTCOME_ACTION, AuditLog.ts >= _close_utc(min(days)))
        .order_by(AuditLog.id)
    ):
        payload = row.after_json or {}
        try:
            day = date.fromisoformat(str(payload.get("session")))
        except ValueError:
            continue
        out.setdefault((day, str(payload.get("scope"))), row)
    return out


# --------------------------------------------------------------------------- #
# derivation
# --------------------------------------------------------------------------- #
def _exclusions(session: Session, fact: _Fact) -> dict[str, int]:
    """Per-reason exclusion counts of a nothing-scanned run: from the attempt
    row when it carries them, else from the ScanRun itself."""
    if fact.excluded is not None:
        return dict(fact.excluded)
    run = session.get(ScanRun, fact.scan_run_id) if fact.scan_run_id is not None else None
    if run is None:
        return {}
    out: dict[str, int] = {}
    for reason, v in (run.exclusions_json or {}).items():
        entry = v if isinstance(v, dict) else {}
        out[str(reason)] = int(entry.get("count", len(entry.get("symbols") or [])))
    return out


def _nothing_scanned_reason(counts: dict[str, int]) -> str:
    """``data_hold`` only when stale/missing data make up most of the
    exclusions; a run emptied by liquidity, earnings or strategy gates is
    ``all_excluded`` (as is one whose exclusions are not on record)."""
    total = sum(counts.values())
    data = sum(n for k, n in counts.items() if k in DATA_EXCLUSIONS)
    return REASON_DATA_HOLD if total > 0 and data * 2 > total else REASON_ALL_EXCLUDED


def _evidence_ids(facts: list[_Fact], skip_row: int | None) -> dict[str, Any]:
    ids: dict[str, Any] = {
        "audit_ids": sorted({f.audit_id for f in facts if f.audit_id is not None}),
        "scan_run_ids": sorted({f.scan_run_id for f in facts if f.scan_run_id is not None}),
        "job_run_ids": sorted({f.job_run_id for f in facts if f.job_run_id is not None}),
        "attempts": len({(f.ts, f.kind) for f in facts}),
    }
    if skip_row is not None:
        ids["missed_session_skip_job_run_id"] = skip_row
    return ids


def _derive(
    session: Session, day: date, key: ScopeKey, ev: _Evidence
) -> tuple[str, str, str, dict[str, Any]]:
    facts = sorted(
        [*ev.by_scope.get((day, key), []), *ev.failed.get(day, [])],
        key=lambda f: (f.ts, f.kind),
    )
    skip_row = ev.skip_rows.get(day)
    evidence = _evidence_ids(facts, skip_row)
    scanned = [f for f in facts if f.kind == "scan" and f.scanned > 0]
    if scanned:
        f = scanned[0]
        return (
            SCANNED,
            SCANNED,
            f"scan_run #{f.scan_run_id} scanned {f.scanned} symbol(s)",
            evidence,
        )
    if facts:
        last = facts[-1]
        if last.kind == "blocked":
            reason, detail = REASON_READINESS, f"readiness gate blocked the scope: {last.detail}"
        elif last.kind == "scan":
            counts = _exclusions(session, last)
            reason = _nothing_scanned_reason(counts)
            summary = ", ".join(f"{k}={n}" for k, n in sorted(counts.items()))
            detail = (
                f"scan_run #{last.scan_run_id} scanned nothing — the scan's own gates excluded "
                f"every symbol" + (f" ({summary})" if summary else "")
            )
        else:
            reason, detail = REASON_FAILED, f"approved-scope scan job failed: {last.detail}"
        if evidence["attempts"] > 1:
            detail += f" [last of {evidence['attempts']} attempts]"
        return SKIPPED, reason, detail, evidence
    detail = (
        "no approved-scope scan attempt while this session's bar was the newest "
        "(worker asleep or stopped, EOD chain failed before the scan, or kill switch)"
    )
    context = ev.context.get(day) or []
    if context:
        job = context[-1]
        detail += (
            f"; last related job: {job.name} {job.status} at "
            f"{_aware(job.started_at).isoformat(timespec='minutes')}"
            + (f": {_one_line(job.detail)[:120]}" if job.detail else "")
        )
        evidence["context_job_run_id"] = int(job.id)
    if skip_row is not None:
        detail += f"; catch-up recorded {MISSED_SKIP_JOB} (job_run #{skip_row})"
    return SKIPPED, REASON_MISSED, detail, evidence


def session_outcomes(
    session: Session,
    *,
    now: datetime | None = None,
    n_sessions: int = 10,
    include_open: bool = True,
    groups: list[ApprovedScanGroup] | None = None,
) -> list[SessionOutcome]:
    """READ-ONLY: for every current approved scope, and every scope whose
    approved window reaches into the listed sessions though it has since left
    the approved set, the outcome of each of the last ``n_sessions`` closed
    sessions (the recorded row when there is one, else what the evidence
    says, ``recorded=False``) plus, with ``include_open``, the session whose
    bar is still the one to scan."""
    now = _aware(now or datetime.now(UTC))
    if groups is None:
        groups, _skipped = approved_scan_groups(session)
    days = closed_sessions(now, n_sessions)
    current = attempt_session(now)
    all_days = [*days, current] if include_open else days
    if not all_days:
        return []
    hist = _scope_histories(session, now)
    scopes: dict[ScopeKey, tuple[str, tuple[int, ...]]] = {
        ScopeKey.of(g): (g.dataset_key, tuple(g.strategy_version_ids)) for g in groups
    }
    approved_now = set(scopes)
    for key in sorted(hist):
        h = hist[key]
        if key not in approved_now and h.runs and h.runs[-1].absent_from is None:
            # dropped since its last listing, with no full attempt since to say
            # when: the current listing (approved_scan_groups) is the absence
            h.runs[-1].absent_from = current
        if key not in scopes and any(h.covers(d) for d in all_days):
            scopes[key] = (h.dataset_key, h.strategy_version_ids)
    if not scopes:
        return []
    ev = _load_evidence(session, all_days, now)
    recorded = _recorded(session, all_days)
    out: list[SessionOutcome] = []
    for key, (dataset_key, version_ids) in scopes.items():
        h = hist.get(key, _ScopeHistory())
        is_approved = key in approved_now
        for day in all_days:
            row = recorded.get((day, key.token))
            if row is not None:
                p = row.after_json or {}
                out.append(
                    SessionOutcome(
                        session_date=day,
                        scope=key,
                        dataset_key=str(p.get("dataset_key") or dataset_key),
                        strategy_version_ids=tuple(
                            int(v) for v in p.get("strategy_version_ids") or ()
                        ),
                        outcome=str(p.get("outcome")),
                        reason=str(p.get("reason")),
                        detail=str(p.get("detail") or ""),
                        evidence=dict(p.get("evidence") or {}),
                        recorded=True,
                        record_id=int(row.id),
                        approved_now=is_approved,
                    )
                )
                continue
            outcome, reason, detail, evidence = _derive(session, day, key, ev)
            if day == current:
                if outcome != SCANNED:
                    if is_approved:
                        outcome = reason = OPEN
                        detail = f"session still open for scanning; so far: {detail}"
                    else:
                        outcome = reason = NOT_IN_SCOPE
                        detail = "scope is no longer in the approved set"
            elif not h.covers(day):
                outcome, reason, detail = NOT_IN_SCOPE, NOT_IN_SCOPE, NOT_IN_SCOPE_DETAIL
            elif reason == REASON_MISSED and h.after_last_listing(day):
                detail += (
                    "; the scope left the approved set before its next listed attempt — "
                    "counted inside its approved window because the time it was dropped "
                    "is not on record"
                )
            out.append(
                SessionOutcome(
                    session_date=day,
                    scope=key,
                    dataset_key=dataset_key,
                    strategy_version_ids=version_ids,
                    outcome=outcome,
                    reason=reason,
                    detail=detail,
                    evidence=evidence,
                    approved_now=is_approved,
                )
            )
    return out


def pending_session_outcomes(
    session: Session, *, now: datetime | None = None, lookback: int = 10
) -> list[SessionOutcome]:
    """Closed sessions (within ``lookback``) in an approved scope's window —
    including a scope that has since left the approved set — that still have
    no outcome record: what ``record_session_outcomes`` would write. Sessions
    older than ``lookback`` are never owed. Read-only."""
    return [
        o
        for o in session_outcomes(session, now=now, n_sessions=lookback, include_open=False)
        if not o.recorded and o.outcome in (SCANNED, SKIPPED)
    ]


def record_session_outcomes(
    session: Session,
    *,
    now: datetime | None = None,
    lookback: int = 10,
    actor: str = "scheduler",
) -> list[SessionOutcome]:
    """Write the ONE outcome row each closed session still lacks, per
    approved scope, within ``lookback`` sessions. Idempotent: a session that
    already has a row is never written again. Records only — never scans."""
    stamp = _aware(now) if now is not None else datetime.now(UTC)
    written = pending_session_outcomes(session, now=now, lookback=lookback)
    for o in written:
        session.add(
            AuditLog(
                ts=stamp,
                actor=actor,
                action=SESSION_OUTCOME_ACTION,
                entity="approved_scope_scan",
                before_json={},
                after_json=o.payload(),
            )
        )
        log = _log.info if o.outcome == SCANNED else _log.warning
        log(
            "approved_scope_scan.session_outcome",
            session_date=o.session_date.isoformat(),
            scope=o.scope.token,
            outcome=o.outcome,
            reason=o.reason,
        )
    if written:
        session.flush()
    return written
