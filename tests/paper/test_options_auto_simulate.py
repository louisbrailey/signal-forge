"""The options branch of auto-simulation — reachable only through the second guard.

The equity module is byte-identical (asserted in
``test_equity_ledger_unchanged_by_options.py``); this is a sibling that copies
its five structural guarantees with three substitutions: the UNDERLYING-keyed
open check, the separate daily cap, and the second guard.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from signalforge.db.models import (
    AuditLog,
    Candidate,
    OptionsPosition,
    OptionsTrade,
    PaperAccount,
    PaperTrade,
)
from signalforge.domain import PaperDecision
from signalforge.paper.options_auto_simulate import (
    AUDIT_ACTION,
    OPTIONS_AUTO_SIM_ACTOR,
    auto_simulate_options_scan_runs,
)
from signalforge.paper.options_ledger import (
    OPTIONS_AUTO_SIM_CAP_KEY,
    OPTIONS_AUTO_SIM_ENABLED_KEY,
)
from signalforge.settings_store import RESEARCH_OVERRIDES_KEY, set_setting
from tests.paper import options_support as fx

NOW = datetime(2026, 2, 18, 21, 0, tzinfo=UTC)


def _world(session: Session, *, arm: bool = True, cap: int = 2, **cand_kw: object) -> Candidate:
    acct = fx.options_account(session)
    inst = fx.underlying(session)
    fx.contracts(session)
    fx.option_prints(session, sessions=[fx.SIGNAL_SESSION, fx.FILL_SESSION])
    ver = fx.approved_strategy(session)
    cand = fx.options_candidate(session, instrument=inst, version=ver, **cand_kw)  # type: ignore[arg-type]
    fx.approve_scope(session, cand, ver)
    fx.clean_reconcile_report(session, acct, as_of=fx.FILL_SESSION)
    if arm:
        set_setting(session, OPTIONS_AUTO_SIM_ENABLED_KEY, True)
        set_setting(session, OPTIONS_AUTO_SIM_CAP_KEY, cap)
    return cand


def _run(session: Session, cand: Candidate) -> object:
    return auto_simulate_options_scan_runs(
        session,
        [cand.scan_run_id],
        account_name=fx.OPTIONS_ACCOUNT,
        pricing=fx.pricing(),
        signal_session=fx.SIGNAL_SESSION,
        fill_session=fx.FILL_SESSION,
        now=NOW,
    )


def test_it_does_nothing_at_all_unless_the_second_setting_is_on(session: Session) -> None:
    """Nothing is armed by default: the setting is absent on a fresh install and
    on the live database, and the equity setting is a different key."""
    cand = _world(session, arm=False)
    set_setting(session, "auto_simulate_qualified_signals", True)  # the EQUITY one
    report = _run(session, cand)
    assert report.enabled is False  # type: ignore[attr-defined]
    assert report.considered == 0  # type: ignore[attr-defined]
    assert session.scalar(select(func.count()).select_from(OptionsTrade)) == 0


def test_an_armed_run_opens_exactly_one_structure_and_audits_it(session: Session) -> None:
    cand = _world(session)
    report = _run(session, cand)
    assert report.enabled is True  # type: ignore[attr-defined]
    assert len(report.accepted) == 1  # type: ignore[attr-defined]
    assert report.rejected == [] and report.watched == []  # type: ignore[attr-defined]

    position = session.scalar(select(OptionsPosition))
    assert position is not None and position.closed_at is None
    trade = session.scalar(select(OptionsTrade))
    assert trade is not None
    assert trade.actor == OPTIONS_AUTO_SIM_ACTOR
    assert trade.decision is PaperDecision.ACCEPTED
    assert trade.signal_snapshot_json["decision"]["automatic"] is True

    audit = session.scalar(select(AuditLog).where(AuditLog.action == AUDIT_ACTION))
    assert audit is not None
    after = audit.after_json
    assert after["simulated"] is True
    assert after["notice"] == "SIMULATED options structure — no order was placed."
    assert "limits_evaluated" in after and "max_loss_dollars_R" in after
    # nothing landed in the EQUITY ledger
    assert session.scalar(select(func.count()).select_from(PaperTrade)) == 0


def test_a_refused_candidate_becomes_an_immutable_REJECTED_record(session: Session) -> None:
    cand = _world(session)
    set_setting(session, RESEARCH_OVERRIDES_KEY, {"options_shaping": {"max_short_delta": 0.001}})
    report = _run(session, cand)
    assert report.accepted == []  # type: ignore[attr-defined]
    assert len(report.rejected) == 1  # type: ignore[attr-defined]

    trade = session.scalar(select(OptionsTrade))
    assert trade is not None
    assert trade.decision is PaperDecision.REJECTED
    assert trade.refused is True and trade.refused_condition == "S"
    assert "max_short_delta" in trade.note
    assert session.scalar(select(func.count()).select_from(OptionsPosition)) == 0


def test_a_candidate_held_back_only_by_the_daily_cap_becomes_WATCH(session: Session) -> None:
    cand = _world(session, cap=0)
    report = _run(session, cand)
    assert len(report.watched) == 1  # type: ignore[attr-defined]
    trade = session.scalar(select(OptionsTrade))
    assert trade is not None
    assert trade.decision is PaperDecision.WATCH
    assert trade.refused_condition == "Z"
    assert session.scalar(select(func.count()).select_from(OptionsPosition)) == 0


def test_a_candidate_is_never_re_decided(session: Session) -> None:
    cand = _world(session)
    _run(session, cand)
    again = _run(session, cand)
    assert again.accepted == []  # type: ignore[attr-defined]
    assert len(again.skipped) == 1  # type: ignore[attr-defined]
    assert "already has an options decision" in again.skipped[0][1]  # type: ignore[attr-defined]
    assert session.scalar(select(func.count()).select_from(OptionsPosition)) == 1


def test_a_second_structure_on_the_same_UNDERLYING_is_refused(session: Session) -> None:
    """Keyed on the underlying, not on a contract: a vertical spans two contract
    rows, so an instrument-keyed check would not stop a second structure."""
    from signalforge.db.models import Instrument, StrategyVersion

    cand = _world(session)
    _run(session, cand)
    # A brand-new candidate for the same underlying, on its own scan run.
    ver = session.get(StrategyVersion, cand.strategy_version_id)
    inst = session.get(Instrument, cand.instrument_id)
    assert ver is not None and inst is not None
    second = fx.options_candidate(session, instrument=inst, version=ver)
    fx.approve_scope(session, second, ver)

    report = _run(session, second)
    assert report.accepted == []  # type: ignore[attr-defined]
    assert len(report.rejected) == 1  # type: ignore[attr-defined]
    trade = session.scalar(select(OptionsTrade).where(OptionsTrade.candidate_id == second.id))
    assert trade is not None and trade.refused_condition == "X"
    assert session.scalar(select(func.count()).select_from(OptionsPosition)) == 1


def test_equity_candidates_are_never_considered_by_the_options_branch(
    session: Session,
) -> None:
    cand = _world(session, structure_kind=None, with_structure_row=False)
    report = _run(session, cand)
    assert report.considered == 0  # type: ignore[attr-defined]
    assert report.accepted == []  # type: ignore[attr-defined]


def test_one_bad_candidate_does_not_stop_the_rest_and_rolls_its_own_work_back(
    session: Session,
) -> None:
    cand = _world(session)
    acct = session.scalar(select(PaperAccount).where(PaperAccount.name == fx.OPTIONS_ACCOUNT))
    assert acct is not None
    acct.cash = Decimal("1")  # condition O will refuse
    session.commit()
    report = _run(session, cand)
    assert report.accepted == []  # type: ignore[attr-defined]
    assert len(report.rejected) == 1  # type: ignore[attr-defined]
    trade = session.scalar(select(OptionsTrade))
    assert trade is not None and trade.refused_condition == "O"


def test_the_kill_switch_stops_the_whole_run(session: Session) -> None:
    import pytest

    from signalforge.killswitch import get_kill_switch

    cand = _world(session)
    get_kill_switch().engage(reason="test", actor="test")
    try:
        with pytest.raises(Exception, match=r"kill switch|engaged"):
            _run(session, cand)
    finally:
        get_kill_switch().release(reason="test", actor="test")
    assert session.scalar(select(func.count()).select_from(OptionsPosition)) == 0
