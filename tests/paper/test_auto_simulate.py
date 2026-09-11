"""Auto-simulation: SIMULATED paper acceptance of qualified candidates, gated by
the same deterministic guard as a manual acceptance, idempotent, capped, and
fully audited — and inert unless the operator setting is ON."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from signalforge.db.models import (
    AuditLog,
    Candidate,
    DataSnapshot,
    Instrument,
    OHLCVDaily,
    PaperAccount,
    PaperPosition,
    PaperTrade,
    ScanRun,
    Strategy,
    StrategyPromotionEvaluation,
    StrategyVersion,
)
from signalforge.domain import (
    Direction,
    Horizon,
    LatencyCategory,
    PaperDecision,
    QualityGate,
    StrategyStatus,
)
from signalforge.paper.auto_simulate import (
    AUDIT_ACTION,
    AUTO_SIM_ACTOR,
    AUTO_SIM_CAP_KEY,
    auto_simulate_scan_runs,
)
from signalforge.research import approval_scope as scope_mod
from signalforge.settings_store import set_setting

SPEC_HASH = "spec-hash-under-test"


def _bars(session: Session, inst: Instrument) -> None:
    d = date(2026, 8, 1)
    for i in range(30):
        session.add(
            OHLCVDaily(
                instrument_id=inst.id,
                session_date=date.fromordinal(d.toordinal() + i),
                open=100.0,
                high=101.0,
                low=99.0,
                close=100.0,
                volume=5_000_000,
                adj_close=100.0,
                source="massive",
                latency_category=LatencyCategory.HISTORICAL,
                is_simulated=True,
                ingested_at=datetime.now(UTC),
                quality_flags=[],
            )
        )


def _seed(
    session: Session,
    *,
    status: StrategyStatus = StrategyStatus.PAPER_APPROVED,
    approved_scope: bool = True,
    symbols: tuple[str, ...] = ("AAPL",),
) -> tuple[ScanRun, list[Candidate]]:
    session.add(PaperAccount(name="default", initial_cash=30_000, cash=30_000))
    strat = Strategy(name="s", horizon=Horizon.SHORT_SWING, status=status)
    session.add(strat)
    session.flush()
    ver = StrategyVersion(
        strategy_id=strat.id, version="0.1.0", status=status, spec_json={}, git_sha="test"
    )
    snap = DataSnapshot(key="universe_test", symbols_json=list(symbols))
    session.add_all([ver, snap])
    session.flush()
    if approved_scope:
        session.add(
            StrategyPromotionEvaluation(
                strategy_version_id=ver.id,
                dataset_snapshot_id=snap.id,
                evaluated_at=datetime.now(UTC),
                config_hash="cfg",
                spec_json_hash=SPEC_HASH,
                universe_json=list(symbols),
                window_start=date(2025, 1, 1),
                window_end=date(2026, 8, 1),
                data_provenance_json={"sources": ["massive"]},
                passed=True,
                verdict="PAPER_APPROVED",
            )
        )
    run = ScanRun(
        horizon=Horizon.SHORT_SWING,
        started_at=datetime.now(UTC),
        finished_at=datetime.now(UTC),
        config_hash="cfg",
        source="massive",
        dataset_snapshot_id=snap.id,
        # the scan's own symbol set is part of the approved scope now: an
        # approval is granted over exactly these symbols and no others
        universe_json=list(symbols),
        universe_size=len(symbols),
    )
    session.add(run)
    session.flush()
    cands: list[Candidate] = []
    for rank, sym in enumerate(symbols, start=1):
        inst = Instrument(symbol=sym, name=sym, instrument_type="stock", sector="tech")
        session.add(inst)
        session.flush()
        _bars(session, inst)
        cand = Candidate(
            scan_run_id=run.id,
            instrument_id=inst.id,
            strategy_version_id=ver.id,
            horizon=Horizon.SHORT_SWING,
            direction=Direction.LONG,
            entry_zone_low=99.0,
            entry_zone_high=101.0,
            invalidation_level=95.0,
            target_level=112.0,
            target_logic="x",
            time_stop_days=10,
            reward_risk_estimate=2.4,
            risk_dollars=150.0,
            risk_pct_of_account=0.5,
            liquidity_json={"last_price": 100.0},
            slippage_assumption_json={"bps": 3},
            event_risk_json={"upcoming_earnings": []},
            portfolio_context_json={},
            data_freshness_json={"fresh": True},
            ranking_json={"score": 0.4},
            reasons_qualify=["test"],
            reasons_fail=["could gap down"],
            quality_gate_status=QualityGate.PASSED,
            failed_gates=[],
            rank_in_horizon=rank,
        )
        session.add(cand)
        cands.append(cand)
    session.flush()
    return run, cands


@pytest.fixture
def scope_matches(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(scope_mod, "current_spec_json_hash", lambda _s, _v: SPEC_HASH)


def _counts(session: Session) -> tuple[int, int, int]:
    return (
        int(session.scalar(select(func.count()).select_from(PaperTrade)) or 0),
        int(session.scalar(select(func.count()).select_from(PaperPosition)) or 0),
        int(
            session.scalar(
                select(func.count()).select_from(AuditLog).where(AuditLog.action == AUDIT_ACTION)
            )
            or 0
        ),
    )


def test_inert_unless_setting_is_on(session: Session, scope_matches: None) -> None:
    run, _ = _seed(session)
    rep = auto_simulate_scan_runs(session, [run.id])
    assert rep.enabled is False and rep.accepted == [] and rep.considered == 0
    assert _counts(session) == (0, 0, 0)


def test_accepts_once_with_full_evidence_and_audit(session: Session, scope_matches: None) -> None:
    run, (cand,) = _seed(session)
    set_setting(session, "auto_simulate_qualified_signals", True)

    rep = auto_simulate_scan_runs(session, [run.id])
    assert rep.enabled and rep.considered == 1
    assert len(rep.accepted) == 1 and rep.rejected == [] and rep.watched == []
    trade = session.get(PaperTrade, rep.accepted[0])
    assert trade is not None and trade.decision is PaperDecision.ACCEPTED
    assert trade.candidate_id == cand.id and trade.position_id is not None
    snap = trade.signal_snapshot_json
    assert snap["decision"]["actor"] == AUTO_SIM_ACTOR and snap["decision"]["automatic"] is True
    assert "no order was placed" in snap["decision"]["note"]
    assert snap["approval_scope"]["matched"] is True
    for key in ("failed_gates", "reasons_fail", "scan", "strategy", "code_version"):
        assert key in snap
    audit = session.scalar(select(AuditLog).where(AuditLog.action == AUDIT_ACTION))
    assert audit is not None and audit.actor == AUTO_SIM_ACTOR
    assert audit.after_json["simulated"] is True and audit.after_json["symbol"] == "AAPL"

    # Idempotent: a retried job never double-accepts.
    again = auto_simulate_scan_runs(session, [run.id])
    assert again.accepted == [] and again.skipped == [
        (cand.id, "candidate already has a paper decision")
    ]
    assert _counts(session) == (1, 1, 1)


def test_guard_refusal_is_recorded_as_immutable_rejection(session: Session) -> None:
    run, (cand,) = _seed(session, status=StrategyStatus.EXPERIMENTAL, approved_scope=False)
    set_setting(session, "auto_simulate_qualified_signals", True)

    rep = auto_simulate_scan_runs(session, [run.id])
    assert rep.accepted == [] and len(rep.rejected) == 1
    cid, reason = rep.rejected[0]
    assert cid == cand.id and "not PAPER_APPROVED" in reason
    trade = session.scalar(select(PaperTrade).where(PaperTrade.candidate_id == cand.id))
    assert trade is not None and trade.decision is PaperDecision.REJECTED
    assert trade.signal_snapshot_json["decision"]["note"] == reason
    assert trade.position_id is None
    assert session.scalar(select(func.count()).select_from(PaperPosition)) == 0


def test_scope_mismatch_is_refused_even_when_approved(session: Session) -> None:
    # No monkeypatch: the live spec hash cannot match the stored one.
    run, (cand,) = _seed(session)
    set_setting(session, "auto_simulate_qualified_signals", True)
    rep = auto_simulate_scan_runs(session, [run.id])
    assert rep.accepted == [] and [c for c, _ in rep.rejected] == [cand.id]
    assert "approved scope" in rep.rejected[0][1]


def test_daily_cap_and_one_open_position_per_instrument(
    session: Session, scope_matches: None
) -> None:
    run, cands = _seed(session, symbols=("AAPL", "MSFT", "NVDA"))
    set_setting(session, "auto_simulate_qualified_signals", True)
    set_setting(session, AUTO_SIM_CAP_KEY, 2)

    rep = auto_simulate_scan_runs(session, [run.id])
    assert len(rep.accepted) == 2
    assert rep.watched == [(cands[2].id, "auto-simulation daily cap (2) reached — not taken")]
    watched = session.scalar(select(PaperTrade).where(PaperTrade.candidate_id == cands[2].id))
    assert watched is not None and watched.decision is PaperDecision.WATCH

    # A fresh candidate on an instrument with an open paper position is refused.
    run2 = ScanRun(
        horizon=Horizon.SHORT_SWING,
        started_at=datetime.now(UTC),
        finished_at=datetime.now(UTC),
        config_hash="cfg",
        source="massive",
        dataset_snapshot_id=run.dataset_snapshot_id,
    )
    session.add(run2)
    session.flush()
    first = cands[0]
    dup = Candidate(
        **{
            k: getattr(first, k)
            for k in (
                "instrument_id",
                "strategy_version_id",
                "horizon",
                "direction",
                "entry_zone_low",
                "entry_zone_high",
                "invalidation_level",
                "target_level",
                "target_logic",
                "time_stop_days",
                "reward_risk_estimate",
                "risk_dollars",
                "risk_pct_of_account",
                "liquidity_json",
                "slippage_assumption_json",
                "event_risk_json",
                "portfolio_context_json",
                "data_freshness_json",
                "ranking_json",
                "reasons_qualify",
                "reasons_fail",
                "quality_gate_status",
                "failed_gates",
                "rank_in_horizon",
            )
        },
        scan_run_id=run2.id,
    )
    session.add(dup)
    session.flush()
    set_setting(session, AUTO_SIM_CAP_KEY, 10)
    rep2 = auto_simulate_scan_runs(session, [run2.id])
    assert rep2.accepted == []
    assert rep2.rejected == [
        (dup.id, "auto-simulation refused: an open paper position already exists")
    ]


def test_kill_switch_blocks_auto_simulation(
    session: Session, scope_matches: None, isolated_data_dir: object
) -> None:
    from signalforge.killswitch import KillSwitchEngaged, get_kill_switch

    run, _ = _seed(session)
    set_setting(session, "auto_simulate_qualified_signals", True)
    get_kill_switch().engage("test")
    try:
        with pytest.raises(KillSwitchEngaged):
            auto_simulate_scan_runs(session, [run.id])
    finally:
        get_kill_switch().release("test")
    assert _counts(session) == (0, 0, 0)
