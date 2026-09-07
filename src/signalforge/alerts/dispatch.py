"""Alert policy engine + dispatch (ARCHITECTURE.md §Alerts).

Default policy:
* All channels OFF until the user enables ``alerts_enabled`` in Settings.
* <= N high-priority candidate alerts per day (default 2); only for
  ``paper_approved`` strategies on a fresh feed.
* One daily research briefing.
* Nothing when data is stale or a strategy is disabled.
* Nothing during quiet hours **except** system-health failures.
* No option-trade alerts (there is no code path).
* Every alert body carries "Research signal only — no order was placed." and a
  link to the local evidence page.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from signalforge.alerts.channels import available_channels
from signalforge.alerts.render import (
    render_briefing_alert,
    render_candidate_alert,
    render_health_alert,
)
from signalforge.data.feeds import feed_status_report
from signalforge.db.models import (
    AlertLog,
    Candidate,
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
    Horizon,
    QualityGate,
    StrategyStatus,
)
from signalforge.killswitch import ensure_not_engaged
from signalforge.observability import get_logger
from signalforge.settings_store import effective_research_config, get_setting

_log = get_logger("alerts.dispatch")


@dataclass
class PlannedAlert:
    alert_type: AlertType
    dedupe_key: str
    subject: str
    body: str
    overnight_ok: bool = False
    payload: dict[str, Any] = field(default_factory=dict)


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


def _already_logged(session: Session, dedupe_key: str) -> bool:
    return session.scalar(select(AlertLog.id).where(AlertLog.dedupe_key == dedupe_key)) is not None


def plan_alerts(session: Session, now: datetime) -> list[PlannedAlert]:
    planned: list[PlannedAlert] = []
    feeds = feed_status_report(session)
    stale_reasons = [
        f"{f['provider']}/{f['feed_type']} stale" for f in feeds["feeds"] if f["is_stale"]
    ]

    # --- system health (allowed overnight) ---
    if stale_reasons:
        subj, body = render_health_alert(stale_reasons)
        planned.append(
            PlannedAlert(
                AlertType.SYSTEM_HEALTH,
                dedupe_key=f"health:{now.date()}:{hash(tuple(stale_reasons)) & 0xffff}",
                subject=subj,
                body=body,
                overnight_ok=True,
            )
        )

    if stale_reasons:
        return planned  # stale feed => no candidate/briefing alerts

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

    # --- candidate alerts: paper_approved strategy + PASSED + latest scan ---
    cfg = effective_research_config(session)
    for h in cfg.enabled_horizons:
        if h is Horizon.INTRADAY:
            continue  # never alert on intraday signals (EOD-only operation)
        run = session.scalar(
            select(ScanRun).where(ScanRun.horizon == h).order_by(ScanRun.started_at.desc()).limit(1)
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
                    payload={"candidate_id": cand.id},
                )
            )
    return planned


def run_alert_cycle(session: Session, now: datetime | None = None) -> AlertCycleResult:
    ensure_not_engaged()
    now = now or utcnow()
    enabled = bool(get_setting(session, "alerts_enabled", False))
    result = AlertCycleResult(enabled=enabled)
    planned = plan_alerts(session, now)
    result.planned = len(planned)
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
        if quiet and not pa.overnight_ok:
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
            session.flush()
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
        session.flush()
        if ok_any:
            result.sent += 1
    _log.info("alerts.cycle", planned=result.planned, sent=result.sent, enabled=enabled)
    return result
