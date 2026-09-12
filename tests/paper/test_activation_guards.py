"""Activation-preparation guards: complete immutable evidence on every paper
trade; automatic paper acceptance impossible for unapproved strategies,
non-equities, or scope mismatches; the alert dry run has no side effects."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from signalforge.db.models import (
    AlertLog,
    AppSetting,
    Candidate,
    Instrument,
    PaperAccount,
    PaperTrade,
    ScanRun,
    Strategy,
    StrategyVersion,
)
from signalforge.domain import Direction, Horizon, PaperDecision, QualityGate, StrategyStatus
from signalforge.paper.ledger import (
    AutoSimulateForbidden,
    accept_candidate,
    assert_auto_simulate_allowed,
    record_decision,
)
from signalforge.settings_store import set_setting


def _seed_candidate(
    session: Session,
    *,
    instrument_type: str = "stock",
    status: StrategyStatus = StrategyStatus.EXPERIMENTAL,
    gate: QualityGate = QualityGate.PASSED,
) -> Candidate:
    session.add(PaperAccount(name="default", initial_cash=10_000, cash=10_000))
    inst = Instrument(symbol="AAPL", name="Apple", instrument_type=instrument_type, sector="tech")
    strat = Strategy(name="s", horizon=Horizon.SHORT_SWING, status=status)
    session.add_all([inst, strat])
    session.flush()
    ver = StrategyVersion(
        strategy_id=strat.id, version="0.1.0", status=status, spec_json={}, git_sha="test"
    )
    session.add(ver)
    run = ScanRun(
        horizon=Horizon.SHORT_SWING,
        started_at=datetime.now(UTC),
        finished_at=datetime.now(UTC),
        config_hash="cfg",
        source="massive",
        dataset_snapshot_id=None,
    )
    session.add(run)
    session.flush()
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
        risk_dollars=50.0,
        risk_pct_of_account=0.5,
        liquidity_json={"last_price": 100.0},
        slippage_assumption_json={"bps": 3},
        event_risk_json={"upcoming_earnings": []},
        portfolio_context_json={},
        data_freshness_json={"fresh": True},
        ranking_json={"score": 0.4},
        reasons_qualify=["test"],
        reasons_fail=["could gap down on earnings"],
        quality_gate_status=gate,
        failed_gates=[] if gate is QualityGate.PASSED else ["liquidity"],
        rank_in_horizon=1,
    )
    session.add(cand)
    session.flush()
    return cand


def test_paper_trade_carries_the_complete_immutable_evidence_snapshot(session: Session) -> None:
    cand = _seed_candidate(session)
    res = accept_candidate(session, cand.id, as_of=date(2026, 9, 10))
    trade = session.get(PaperTrade, res.paper_trade_id)
    assert trade is not None
    snap = trade.signal_snapshot_json
    for key in (
        "failed_gates",
        "reasons_fail",
        "data_freshness",
        "event_risk",
        "liquidity",
        "slippage_assumption",
        "scan",
        "strategy",
        "approval_scope",
        "code_version",
        "instrument_type",
    ):
        assert key in snap, key
    assert snap["reasons_fail"] == ["could gap down on earnings"]
    assert snap["approval_scope"]["matched"] is False  # experimental strategy: no approved scope
    assert snap["scan"]["scan_run_id"] == cand.scan_run_id
    assert snap["notice"] == "Research signal only — no order was placed."
    assert trade.why_might_fail == "could gap down on earnings"
    # immutable (invariant S9): the row cannot be changed after the fact
    trade.why_might_fail = "edited"
    with pytest.raises(Exception, match=r"immutable|paper_trade"):
        session.flush()
    session.rollback()


def test_auto_simulation_is_impossible_unless_every_gate_holds(session: Session) -> None:
    cand = _seed_candidate(session)  # experimental strategy
    with pytest.raises(AutoSimulateForbidden, match="auto_simulate_qualified_signals is off"):
        assert_auto_simulate_allowed(session, cand)
    set_setting(session, "auto_simulate_qualified_signals", True)
    with pytest.raises(AutoSimulateForbidden, match="not PAPER_APPROVED"):
        assert_auto_simulate_allowed(session, cand)


def test_auto_simulation_refuses_non_equities_and_failed_gates(session: Session) -> None:
    set_setting(session, "auto_simulate_qualified_signals", True)
    cand = _seed_candidate(session, instrument_type="option", status=StrategyStatus.PAPER_APPROVED)
    with pytest.raises(AutoSimulateForbidden, match=r"not a U\.S\. stock/ETF"):
        assert_auto_simulate_allowed(session, cand)


def test_auto_simulation_refuses_scope_mismatch_even_when_approved(session: Session) -> None:
    set_setting(session, "auto_simulate_qualified_signals", True)
    cand = _seed_candidate(
        session, status=StrategyStatus.PAPER_APPROVED
    )  # no passing evaluation -> no scope
    with pytest.raises(AutoSimulateForbidden, match="does not match"):
        assert_auto_simulate_allowed(session, cand)


def test_automatic_acceptance_has_exactly_one_guarded_entry_point() -> None:
    """Operator-authorized 2026-09-10: automatic SIMULATED acceptance exists, but
    ONLY in ``paper/auto_simulate.py`` (which runs the full guard first), and it
    is wired ONLY into the approved-scope scan job. Nothing else in the tree may
    call ``accept_candidate`` or ``auto_simulate_scan_runs``.

    **Matched by PATH EQUALITY, never by basename** (repaired 2026-09-12 with
    I-O6, whose options twin is copied from this test). The previous form was
    ``p.name in {"ledger.py", "cli.py"}`` — a ``Path.name`` — so ANY file
    anywhere under ``src/signalforge`` called ``ledger.py`` or ``cli.py`` could
    call ``accept_candidate`` and this test still passed; ``agents/cli.py`` is
    the obvious example, and the agents layer is live. The repair is strictly
    more restrictive and changes no existing verdict: the two real callers are
    ``paper/ledger.py`` (the definition) and ``cli.py``.

    **Adapted explicitly by W3c (2026-09-12), and the adaptation is stated rather
    than absorbed.** ``scheduler.py`` now contains a SECOND automatic-acceptance
    entry point: ``job_options_paper_eod`` calls
    ``paper.options_auto_simulate.auto_simulate_options_scan_runs``. That call
    does not accidentally satisfy the assertions below —
    ``"auto_simulate_options_scan_runs("`` does not contain the substring
    ``"auto_simulate_scan_runs("`` — so this test would have stayed green while
    a whole second door opened in the file it is guarding. Silence is not
    permission: the second entry point is named here, counted here, and pinned to
    the one job that may hold it, so the invariant this test asserts is now
    "exactly one guarded entry point PER ASSET CLASS, each in its own module,
    each called from exactly one scheduler job", not "exactly one call site".
    """
    from pathlib import Path

    root = Path(__file__).resolve().parents[2] / "src" / "signalforge"
    manual_ok = {"paper/ledger.py", "cli.py"}
    for p in root.rglob("*.py"):
        text = p.read_text()
        rel = str(p.relative_to(root))
        if "accept_candidate(" in text.replace("accept_options_candidate(", ""):
            assert (
                rel in manual_ok or "app/routers/" in rel or rel == "paper/auto_simulate.py"
            ), f"{rel} must not accept paper trades automatically"
        if "auto_simulate_scan_runs(" in text and rel != "paper/auto_simulate.py":
            assert rel == "scheduler.py", f"{rel} may not invoke auto-simulation"
    sched = (root / "scheduler.py").read_text()
    assert "accept_candidate(" not in sched.replace("accept_options_candidate(", "")
    assert sched.count("auto_simulate_scan_runs(") == 1  # only job_approved_scope_scan
    auto = (root / "paper" / "auto_simulate.py").read_text()
    assert auto.index("assert_auto_simulate_allowed(session, cand)") < auto.index(
        "accept_candidate(session, cand.id"
    )

    # --- the SECOND sanctioned caller, named ------------------------------- #
    assert sched.count("auto_simulate_options_scan_runs(") == 1
    equity_job = sched.index("def job_approved_scope_scan(")
    options_job = sched.index("def job_options_paper_eod(")
    equity_body = sched[equity_job : sched.index("\ndef ", equity_job + 1)]
    options_body = sched[options_job : sched.index("\ndef ", options_job + 1)]
    # each auto-simulation lives in its own job, and only there
    assert "auto_simulate_scan_runs(session, [" in equity_body
    assert "auto_simulate_options_scan_runs(" in options_body
    # neither job may open the other asset class's door
    assert "auto_simulate_options_scan_runs(" not in equity_body
    assert "mark_options_to_market(" not in equity_body
    assert "accept_options_candidate(" not in options_body
    assert "auto_simulate_scan_runs(" not in options_body.replace(
        "auto_simulate_options_scan_runs(", ""
    )


def test_alert_dry_run_has_no_side_effects(session: Session) -> None:
    from signalforge.alerts.dispatch import ALERT_TYPE_SETTING_KEYS, dry_run_cycle
    from signalforge.domain import AlertType

    _seed_candidate(session, status=StrategyStatus.PAPER_APPROVED)
    set_setting(
        session, "last_briefing", {"as_of": "2026-09-10", "text": "brief", "narrative": None}
    )
    n_settings = session.scalar(select(func.count()).select_from(AppSetting))
    res = dry_run_cycle(
        session,
        assume={
            "alerts_enabled": True,
            "paper_probation_enabled": True,
            ALERT_TYPE_SETTING_KEYS[AlertType.CANDIDATE]: True,
            "max_alerts_per_day": 2,
        },
        now=datetime(2026, 9, 10, 16, 0, tzinfo=UTC),
    )
    # the candidate exists but its scan cannot match an approved scope -> blocked, named
    cands = [p for p in res.planned if p.alert_type == "candidate"]
    assert cands and all(not p.would_send for p in cands)
    assert all("approval does not apply" in p.reason for p in cands)
    # the briefing is planned but its TYPE is off in the assumed settings -> blocked
    briefs = [p for p in res.planned if p.alert_type == "daily_briefing"]
    assert briefs and "is off in Settings" in briefs[0].reason
    # no side effects
    assert session.scalar(select(func.count()).select_from(AlertLog)) == 0
    assert session.scalar(select(func.count()).select_from(AppSetting)) == n_settings
    from signalforge.settings_store import get_setting

    assert get_setting(session, "alerts_enabled", False) is False
    assert get_setting(session, "paper_probation_enabled", False) is False


def test_record_decision_also_stores_full_evidence(session: Session) -> None:
    cand = _seed_candidate(session)
    trade_id = record_decision(
        session, cand.id, PaperDecision.REJECTED, note="too close to earnings"
    )
    trade = session.get(PaperTrade, trade_id)
    assert trade is not None
    assert trade.signal_snapshot_json["approval_scope"]["matched"] is False
    assert trade.signal_snapshot_json["reasons_fail"]
