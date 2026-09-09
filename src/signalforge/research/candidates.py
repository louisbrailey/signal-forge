"""Persist a scan result: one ``scan_run`` row + one ``candidate`` row per draft.

NO-TRADE drafts are persisted too — a NO TRADE with its failed gate(s) is a
first-class recorded outcome, not a silent drop.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import ColumnElement
from sqlalchemy.orm import Session

from signalforge.db.models import Candidate, ScanRun
from signalforge.db.types import utcnow
from signalforge.domain import QualityGate
from signalforge.research.scan import CandidateDraft, ScanResult


def _draft_to_row(draft: CandidateDraft, scan_run_id: int) -> Candidate:
    return Candidate(
        scan_run_id=scan_run_id,
        instrument_id=draft.instrument_id,
        strategy_version_id=draft.strategy_version_id,
        horizon=draft.horizon,
        direction=draft.direction,
        entry_zone_low=draft.entry_zone_low,
        entry_zone_high=draft.entry_zone_high,
        invalidation_level=draft.invalidation_level,
        target_level=draft.target_level,
        target_logic=draft.target_logic,
        time_stop_days=draft.time_stop_days,
        reward_risk_estimate=draft.reward_risk_estimate,
        probability_calibrated=draft.probability_calibrated,
        calibration_ref=draft.calibration_ref,
        risk_dollars=draft.risk_dollars,
        risk_pct_of_account=draft.risk_pct_of_account,
        liquidity_json=draft.liquidity,
        slippage_assumption_json={"model": "slippage_bps + half spread"},
        event_risk_json=draft.event_risk,
        portfolio_context_json={},
        data_freshness_json=draft.data_freshness,
        ranking_json=draft.ranking,
        reasons_qualify=draft.reasons_qualify,
        reasons_fail=draft.reasons_fail,
        quality_gate_status=draft.quality_gate_status,
        failed_gates=draft.failed_gates,
        rank_in_horizon=draft.rank_in_horizon,
    )


def persist_scan(session: Session, result: ScanResult) -> ScanRun:
    passing = [d for d in result.candidates if d.quality_gate_status is QualityGate.PASSED]

    run = ScanRun(
        horizon=result.horizon,
        started_at=datetime.fromisoformat(result.started_at),
        finished_at=utcnow(),
        config_hash=result.config_hash,
        universe_size=len(result.universe),
        scanned_count=len(result.scanned),
        excluded_count=result.excluded_count,
        no_trade_count=len(result.no_trade),
        candidate_count=len(passing),
        exclusions_json={
            reason: {"count": len(syms), "symbols": syms}
            for reason, syms in result.excluded.items()
        },
        data_snapshot_ref="",
        universe_json=list(result.universe),
        source=result.source,
        dataset_snapshot_id=result.dataset_snapshot_id,
    )
    session.add(run)
    session.flush()

    for draft in result.candidates:
        session.add(_draft_to_row(draft, run.id))
    session.flush()
    return run


def not_universe_scan(session: Session) -> ColumnElement[bool]:
    """Filter that keeps the research/promotion scans and EXCLUDES the liquid-
    universe pipeline's research scans (source == its normalized_source).
    Those are discovery-universe scans on as-of-adjusted bulk data — they must
    never become "the latest scan" for the alert planner, the overview, the
    scanner page, or the catch-up staleness check."""
    from signalforge.settings_store import effective_research_config

    src = effective_research_config(session).universe_pipeline.normalized_source
    return ScanRun.source != src
