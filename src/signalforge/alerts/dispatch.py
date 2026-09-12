"""Alert policy engine + dispatch (ARCHITECTURE.md §Alerts).

Default policy:
* All channels OFF until the user enables ``alerts_enabled`` in Settings.
* <= N high-priority candidate alerts per day (default 2); only for
  ``paper_approved`` strategies on a fresh feed.
* One daily research briefing.
* Nothing when data is stale or a strategy is disabled.
* Nothing during quiet hours **except** DATA_ISSUE (stale feed / ingestion
  failure) and SYSTEM_HEALTH (a scheduled job or the DB itself failed).
* Candidate alerts stay off until >= 1 strategy reaches PAPER_APPROVED through
  ``research.promotion`` — enforced structurally by the join below, not a
  separate toggle.
* No option-trade alerts (there is no code path).
* Every alert body carries "Research signal only — no order was placed." and a
  link to the local evidence page.
"""

from __future__ import annotations

import hashlib
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime
from datetime import timedelta as _td
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from signalforge.alerts.channels import available_channels
from signalforge.alerts.render import (
    render_briefing_alert,
    render_candidate_alert,
    render_data_issue_alert,
    render_system_health_alert,
)
from signalforge.data.feeds import feed_status_report
from signalforge.db.models import (
    AlertLog,
    AuditLog,
    Candidate,
    IngestionRun,
    Instrument,
    ScanRun,
    Strategy,
    StrategyVersion,
)
from signalforge.db.types import utcnow
from signalforge.domain import (
    AlertChannel,
    AlertStatus,
    AlertType,
    QualityGate,
    StrategyStatus,
)
from signalforge.killswitch import ensure_not_engaged
from signalforge.observability import get_logger
from signalforge.research.candidates import not_universe_scan
from signalforge.settings_store import effective_research_config, get_setting, set_setting

_log = get_logger("alerts.dispatch")


@dataclass
class PlannedAlert:
    alert_type: AlertType
    dedupe_key: str
    subject: str
    body: str
    overnight_ok: bool = False
    payload: dict[str, Any] = field(default_factory=dict)
    # Set only for a candidate whose originating scan does not match the
    # strategy's approved dataset scope (research.approval_scope). Checked
    # BEFORE quiet-hours/cap suppression in run_alert_cycle so the exact,
    # required reason is what gets logged -- this is a hard block, never a
    # scheduling deferral like the other suppression reasons.
    force_suppress_reason: str | None = None


@dataclass
class AlertCycleResult:
    enabled: bool
    planned: int = 0
    sent: int = 0
    suppressed: list[str] = field(default_factory=list)


def _in_quiet_hours(session: Session, now: datetime) -> bool:
    qh = get_setting(session, "quiet_hours", {"start": 21, "end": 7}) or {}
    start, end = int(qh.get("start", 21)), int(qh.get("end", 7))
    h = now.astimezone().hour
    return (start <= h or h < end) if start > end else (start <= h < end)


def _sent_today(session: Session, alert_type: AlertType, now: datetime) -> int:
    start = now.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    return int(
        session.scalar(
            select(func.count())
            .select_from(AlertLog)
            .where(
                AlertLog.alert_type == alert_type,
                AlertLog.status == AlertStatus.SENT,
                AlertLog.created_at >= start,
            )
        )
        or 0
    )


def _reasons_digest(reasons: list[str]) -> str:
    """Full-width, order-independent digest for a dedupe key — a 16-bit
    ``hash() & 0xffff`` truncation lets two genuinely different reason sets
    collide into the same key on the same day, silently dropping a real new
    alert as "already logged". Sorted so equivalent sets in a different query
    order can't spuriously produce a different key."""
    return hashlib.sha256("|".join(sorted(reasons)).encode()).hexdigest()[:32]


def _already_logged(session: Session, dedupe_key: str) -> bool:
    return session.scalar(select(AlertLog.id).where(AlertLog.dedupe_key == dedupe_key)) is not None


_LAST_INGESTION_CHECK_KEY = "last_ingestion_failure_check_ts"
_LAST_JOB_CHECK_KEY = "last_job_failure_check_ts"


def _lookback_since(
    session: Session, now: datetime, watermark_key: str, *, default_hours: int
) -> datetime:
    """The rolling lookback start, widened backward to the last time this
    failure category was actually checked, if that check was longer ago than
    the default window. Without this, a failure whose only record is a rolling
    N-hour window can permanently vanish from every future alert cycle the
    moment it turns N hours old — including while the scheduler itself was
    down (a laptop asleep, per this module's own docstring) for longer than
    the window, which is exactly when a missed alert matters most."""
    default_since = now.astimezone(UTC) - _td(hours=default_hours)
    watermark = get_setting(session, watermark_key, None)
    if watermark:
        try:
            return min(default_since, datetime.fromisoformat(watermark))
        except (TypeError, ValueError):
            pass
    return default_since


def _recent_ingestion_failures(session: Session, now: datetime, *, hours: int = 24) -> list[str]:
    """Ingestion runs that failed or only partially completed since the later
    of ``hours`` ago or the last time this check ran — a data issue distinct
    from (but as urgent as) a stale feed."""
    since = _lookback_since(session, now, _LAST_INGESTION_CHECK_KEY, default_hours=hours)
    rows = session.execute(
        select(IngestionRun.provider, IngestionRun.kind, IngestionRun.status, IngestionRun.notes)
        .where(IngestionRun.status.in_(("failed", "partial")), IngestionRun.started_at >= since)
        .order_by(IngestionRun.started_at.desc())
        .limit(10)
    ).all()
    return [f"{provider}/{kind} {status}" for provider, kind, status, _notes in rows]


def _recent_job_failures(session: Session, now: datetime, *, hours: int = 6) -> list[str]:
    """Scheduled-job exceptions recorded by ``scheduler.guarded`` since the
    later of ``hours`` ago or the last time this check ran — a system failure
    distinct from a data-freshness problem."""
    since = _lookback_since(session, now, _LAST_JOB_CHECK_KEY, default_hours=hours)
    rows = session.execute(
        select(AuditLog.entity, AuditLog.after_json)
        .where(AuditLog.action == "job.failed", AuditLog.ts >= since)
        .order_by(AuditLog.ts.desc())
        .limit(10)
    ).all()
    return [
        f"job {entity} failed: {(after or {}).get('error', 'see logs')[:120]}"
        for entity, after in rows
    ]


def plan_alerts(session: Session, now: datetime) -> list[PlannedAlert]:
    planned: list[PlannedAlert] = []
    feeds = feed_status_report(session, now=now)
    stale_reasons = [
        f"{f['provider']}/{f['feed_type']} stale" for f in feeds["feeds"] if f["is_stale"]
    ]
    ingestion_reasons = _recent_ingestion_failures(session, now)
    data_reasons = stale_reasons + ingestion_reasons
    job_reasons = _recent_job_failures(session, now)

    # --- data issue: stale feed or a recent ingestion failure (overnight ok) ---
    if data_reasons:
        subj, body = render_data_issue_alert(data_reasons)
        planned.append(
            PlannedAlert(
                AlertType.DATA_ISSUE,
                dedupe_key=f"data_issue:{now.date()}:{_reasons_digest(data_reasons)}",
                subject=subj,
                body=body,
                overnight_ok=True,
            )
        )

    # --- system health: a scheduled job or the DB itself failed (overnight ok) ---
    if job_reasons:
        subj, body = render_system_health_alert(job_reasons)
        planned.append(
            PlannedAlert(
                AlertType.SYSTEM_HEALTH,
                dedupe_key=f"sys_health:{now.date()}:{_reasons_digest(job_reasons)}",
                subject=subj,
                body=body,
                overnight_ok=True,
            )
        )

    if stale_reasons:
        return planned  # a stale feed specifically => no candidate/briefing alerts

    # --- daily briefing ---
    briefing = get_setting(session, "last_briefing", None)
    if briefing:
        subj, body = render_briefing_alert(briefing)
        planned.append(
            PlannedAlert(
                AlertType.DAILY_BRIEFING,
                dedupe_key=f"briefing:{briefing['as_of']}",
                subject=subj,
                body=body,
            )
        )

    # --- candidate alerts: paper_approved strategy + PASSED + latest scan,
    # gated further by an explicit paper_probation_enabled flag and by an
    # exact dataset-scope match (research.approval_scope) -- Strategy.status
    # alone says a strategy passed promotion on SOME dataset; it says nothing
    # about whether THIS scan used that exact dataset.
    probation_enabled = bool(_setting(session, "paper_probation_enabled", False))
    cfg = effective_research_config(session)
    # INTRADAY is alerted on only when the operator has turned intraday
    # operation on (research.intraday.operating_enabled, default off) — the one
    # flag every policy surface reads. It used to be skipped by a hard-coded
    # condition here, which is why "EOD-only" could not be read off any single
    # place, or reversed in one.
    from signalforge.research.intraday_policy import operating_horizons

    for h in operating_horizons(cfg, cfg.enabled_horizons):
        run = session.scalar(
            select(ScanRun)
            .where(ScanRun.horizon == h, not_universe_scan(session))
            .order_by(ScanRun.started_at.desc())
            .limit(1)
        )
        if run is None:
            continue
        stmt = (
            select(Candidate, Instrument, Strategy.name, Strategy.status, StrategyVersion.version)
            .join(Instrument, Candidate.instrument_id == Instrument.id)
            .join(StrategyVersion, Candidate.strategy_version_id == StrategyVersion.id)
            .join(Strategy, StrategyVersion.strategy_id == Strategy.id)
            .where(
                Candidate.scan_run_id == run.id,
                Candidate.quality_gate_status == QualityGate.PASSED,
                Strategy.status == StrategyStatus.PAPER_APPROVED,
            )
            .order_by(Candidate.rank_in_horizon)
        )
        for cand, inst, strat_name, _status, version in session.execute(stmt):
            scope_reason: str | None = None
            if not probation_enabled:
                scope_reason = (
                    "paper_probation_enabled is off — see approval_scope for how to enable it"
                )
            else:
                from signalforge.research.approval_scope import (
                    NO_TRADE_SCOPE_MISMATCH,
                    approved_scopes,
                    current_spec_json_hash,
                    scan_scope_matches,
                )

                live_hash = current_spec_json_hash(session, cand.strategy_version_id)
                in_scope = live_hash is not None and scan_scope_matches(
                    approved_scopes(session, cand.strategy_version_id),
                    dataset_snapshot_id=run.dataset_snapshot_id,
                    config_hash=run.config_hash,
                    spec_json_hash=live_hash,
                    source=run.source,
                    universe=frozenset(x.upper() for x in (run.universe_json or ())),
                )
                if not in_scope:
                    scope_reason = NO_TRADE_SCOPE_MISMATCH
            c = {
                "id": cand.id,
                "symbol": inst.symbol,
                "sector": inst.sector or "unknown",
                "horizon": cand.horizon.value,
                "strategy": strat_name,
                "strategy_version": version,
                "direction": cand.direction.value,
                "entry_low": cand.entry_zone_low,
                "entry_high": cand.entry_zone_high,
                "stop": cand.invalidation_level,
                "target": cand.target_level,
                "reward_risk": cand.reward_risk_estimate,
                "risk_dollars": cand.risk_dollars,
                "risk_pct": cand.risk_pct_of_account,
                "reference_price": (cand.liquidity_json or {}).get("last_price"),
                "as_of": run.started_at.isoformat(),
                "event_risk": cand.event_risk_json or {},
                "data_freshness": cand.data_freshness_json or {},
                "reasons_qualify": cand.reasons_qualify,
                "reasons_fail": cand.reasons_fail,
            }
            subj, body = render_candidate_alert(c)
            planned.append(
                PlannedAlert(
                    AlertType.CANDIDATE,
                    dedupe_key=f"cand:{cand.id}:{run.started_at.date()}",
                    subject=subj,
                    body=body,
                    force_suppress_reason=scope_reason,
                    payload={"candidate_id": cand.id},
                )
            )
    return planned


# Per-alert-type switches — every type OFF by default, on top of the global
# ``alerts_enabled`` gate. Keys are stable strings so Settings, /ops and the
# CLI all read the same rows.
ALERT_TYPE_SETTING_KEYS: dict[AlertType, str] = {
    AlertType.SYSTEM_HEALTH: "alert_type_enabled:system_health",
    AlertType.DATA_ISSUE: "alert_type_enabled:data_issue",
    AlertType.DAILY_BRIEFING: "alert_type_enabled:daily_briefing",
    AlertType.CANDIDATE: "alert_type_enabled:candidate",
}


# Dry-run overlay: a dict of setting overrides consulted BEFORE the database
# so an operator can see what a cycle WOULD do with settings that are not yet
# enabled — without changing a setting, logging an alert, or sending anything.
_ASSUMED: ContextVar[dict[str, Any] | None] = ContextVar("assumed_settings", default=None)


def _setting(session: Session, key: str, default: Any) -> Any:
    """Setting read that honours the dry-run overlay. ONLY for ``plan_alerts``
    and ``dry_run_cycle``; the real cycle reads ``get_setting`` directly."""
    assumed = _ASSUMED.get()
    if assumed is not None and key in assumed:
        return assumed[key]
    return get_setting(session, key, default)


def _assert_no_assumed_settings() -> None:
    """Fail fast if the real send path ever runs under a dry-run overlay."""
    if _ASSUMED.get() is not None:
        raise RuntimeError(
            "run_alert_cycle called inside a dry-run settings overlay — refusing to dispatch"
        )


def alert_type_enabled(session: Session, alert_type: AlertType) -> bool:
    """Persisted per-type switch (never the dry-run overlay)."""
    return bool(get_setting(session, ALERT_TYPE_SETTING_KEYS[alert_type], False))


def _assumed_alert_type_enabled(session: Session, alert_type: AlertType) -> bool:
    """Per-type switch as the dry run assumes it."""
    return bool(_setting(session, ALERT_TYPE_SETTING_KEYS[alert_type], False))


def alert_type_states(session: Session) -> dict[str, bool]:
    return {t.value: alert_type_enabled(session, t) for t in ALERT_TYPE_SETTING_KEYS}


def run_alert_cycle(session: Session, now: datetime | None = None) -> AlertCycleResult:
    ensure_not_engaged()
    _assert_no_assumed_settings()
    now = now or utcnow()
    # Persisted settings ONLY — the dry-run overlay must never gate a real send.
    enabled = bool(get_setting(session, "alerts_enabled", False))
    result = AlertCycleResult(enabled=enabled)
    planned = plan_alerts(session, now)
    result.planned = len(planned)
    # Advance the failure-lookback watermarks now that this cycle has checked
    # for them — independent of `enabled`/dispatch, so a failure is never
    # missed just because it was checked while alerts happened to be off.
    set_setting(session, _LAST_INGESTION_CHECK_KEY, now.astimezone(UTC).isoformat())
    set_setting(session, _LAST_JOB_CHECK_KEY, now.astimezone(UTC).isoformat())
    if not enabled:
        result.suppressed = ["alerts_enabled is off (complete setup in Settings)"] * len(planned)
        return result

    channels = available_channels()
    max_candidate = int(
        get_setting(session, "max_alerts_per_day", None)
        or effective_research_config(session).max_high_priority_alerts_per_day
    )
    quiet = _in_quiet_hours(session, now)

    for pa in planned:
        if _already_logged(session, pa.dedupe_key):
            continue
        reason: str | None = None
        if pa.force_suppress_reason:
            reason = pa.force_suppress_reason
        elif not alert_type_enabled(session, pa.alert_type):
            reason = f"alert type {pa.alert_type.value} is off in Settings"
        elif quiet and not pa.overnight_ok:
            reason = "quiet hours"
        elif (
            pa.alert_type is AlertType.CANDIDATE
            and _sent_today(session, AlertType.CANDIDATE, now) >= max_candidate
        ):
            reason = f"daily candidate-alert cap ({max_candidate}) reached"
        elif (
            pa.alert_type is AlertType.DAILY_BRIEFING
            and _sent_today(session, AlertType.DAILY_BRIEFING, now) >= 1
        ):
            reason = "briefing already sent today"

        if reason:
            session.add(
                AlertLog(
                    alert_type=pa.alert_type,
                    channel=AlertChannel.LOCAL,
                    dedupe_key=pa.dedupe_key,
                    status=AlertStatus.SUPPRESSED,
                    suppressed_reason=reason,
                    payload_json=pa.payload,
                )
            )
            session.commit()
            result.suppressed.append(f"{pa.alert_type.value}: {reason}")
            continue

        ok_any = False
        for ch in channels:
            ok = ch.send(pa.subject, pa.body)
            ok_any = ok_any or ok
            session.add(
                AlertLog(
                    alert_type=pa.alert_type,
                    channel=ch.channel,
                    dedupe_key=(
                        pa.dedupe_key
                        if ch.channel is AlertChannel.LOCAL
                        else f"{pa.dedupe_key}:{ch.channel.value}"
                    ),
                    status=AlertStatus.SENT if ok else AlertStatus.FAILED,
                    payload_json=pa.payload,
                    sent_at=utcnow() if ok else None,
                )
            )
            # COMMIT per dispatched alert: the send already happened and cannot
            # be undone, so its AlertLog must survive any later failure in this
            # cycle — otherwise a retried cycle would re-send it.
            session.commit()
        if ok_any:
            result.sent += 1
    _log.info("alerts.cycle", planned=result.planned, sent=result.sent, enabled=enabled)
    return result


@dataclass(slots=True)
class DryRunAlert:
    alert_type: str
    subject: str
    dedupe_key: str
    would_send: bool
    reason: str
    candidate_id: int | None


@dataclass(slots=True)
class DryRunResult:
    now: str
    assumed_settings: dict[str, Any]
    channels: list[str]
    quiet_hours: bool
    already_sent_today: int
    planned: list[DryRunAlert] = field(default_factory=list)

    @property
    def would_send(self) -> int:
        return sum(1 for p in self.planned if p.would_send)


def dry_run_cycle(
    session: Session,
    *,
    assume: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> DryRunResult:
    """What ``run_alert_cycle`` WOULD do under ``assume`` (setting overrides),
    with NO side effects: nothing is written to alert_log or app_setting, no
    watermark is advanced, and no channel is contacted. Every gate that the
    real cycle applies is evaluated: per-candidate approval-scope match,
    probation flag, per-type switch, quiet hours, the daily candidate cap,
    the once-per-day briefing, and dedupe against alerts already logged."""
    now = now or utcnow()
    assumed = dict(assume or {})
    token = _ASSUMED.set(assumed)
    try:
        enabled = bool(_setting(session, "alerts_enabled", False))
        planned = plan_alerts(session, now)
        max_candidate = int(
            _setting(session, "max_alerts_per_day", None)
            or effective_research_config(session).max_high_priority_alerts_per_day
        )
        quiet = _in_quiet_hours(session, now)
        sent_today = _sent_today(session, AlertType.CANDIDATE, now)
        result = DryRunResult(
            now=now.isoformat(),
            assumed_settings=assumed,
            channels=[ch.channel.value for ch in available_channels()],
            quiet_hours=quiet,
            already_sent_today=sent_today,
        )
        budget = max(0, max_candidate - sent_today)
        for pa in planned:
            reason: str | None = None
            if not enabled:
                reason = "alerts_enabled is off"
            elif _already_logged(session, pa.dedupe_key):
                reason = "already logged (dedupe)"
            elif pa.force_suppress_reason:
                reason = pa.force_suppress_reason
            elif not _assumed_alert_type_enabled(session, pa.alert_type):
                reason = f"alert type {pa.alert_type.value} is off in Settings"
            elif quiet and not pa.overnight_ok:
                reason = "quiet hours"
            elif pa.alert_type is AlertType.CANDIDATE and budget <= 0:
                reason = f"daily candidate-alert cap ({max_candidate}) reached"
            elif (
                pa.alert_type is AlertType.DAILY_BRIEFING
                and _sent_today(session, AlertType.DAILY_BRIEFING, now) >= 1
            ):
                reason = "briefing already sent today"
            would = reason is None
            if would and pa.alert_type is AlertType.CANDIDATE:
                budget -= 1
            result.planned.append(
                DryRunAlert(
                    alert_type=pa.alert_type.value,
                    subject=pa.subject,
                    dedupe_key=pa.dedupe_key,
                    would_send=would,
                    reason=reason or "would send",
                    candidate_id=(pa.payload or {}).get("candidate_id"),
                )
            )
        return result
    finally:
        _ASSUMED.reset(token)
