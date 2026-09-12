"""Acceptance, the collateral ledger, marks, expiry and reconciliation (I-O6).

Every figure asserted here is arithmetic over fixture prints the test chose, so a
reader can check it on paper. Nothing reads a real price, a real contract or the
live database.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from signalforge.db.models import (
    Candidate,
    OptionsCollateralEntry,
    OptionsMark,
    OptionsPosition,
    OptionsReconcileReport,
    OptionsTrade,
    PaperAccount,
)
from signalforge.domain import PaperDecision
from signalforge.paper.options_ledger import (
    OPTIONS_AUTO_SIM_CAP_KEY,
    OPTIONS_AUTO_SIM_ENABLED_KEY,
    OptionExpiryUnhandled,
    OptionsAutoSimulateForbidden,
    accept_options_candidate,
    assert_options_auto_simulate_allowed,
    collateral_basis,
    record_options_decision,
    structure_from_position,
)
from signalforge.paper.options_marks import (
    mark_options_to_market,
    options_portfolio_snapshot,
    process_option_expiries,
    reconcile_options_collateral,
)
from signalforge.settings_store import RESEARCH_OVERRIDES_KEY, set_setting
from tests.paper import options_support as fx


def _world(session: Session, **cand_kw: object) -> tuple[Candidate, PaperAccount]:
    acct = fx.options_account(session)
    inst = fx.underlying(session)
    fx.contracts(session)
    fx.option_prints(session, sessions=[fx.SIGNAL_SESSION, fx.FILL_SESSION])
    ver = fx.approved_strategy(session)
    cand = fx.options_candidate(session, instrument=inst, version=ver, **cand_kw)  # type: ignore[arg-type]
    fx.approve_scope(session, cand, ver)
    fx.clean_reconcile_report(session, acct, as_of=fx.FILL_SESSION)
    set_setting(session, OPTIONS_AUTO_SIM_ENABLED_KEY, True)
    set_setting(session, OPTIONS_AUTO_SIM_CAP_KEY, 2)
    return cand, acct


def _open(session: Session, cand: Candidate, *, actor: str = "local-user") -> object:
    plan = assert_options_auto_simulate_allowed(
        session,
        cand,
        account_name=fx.OPTIONS_ACCOUNT,
        pricing=fx.pricing(),
        signal_session=fx.SIGNAL_SESSION,
        fill_session=fx.FILL_SESSION,
    )
    return accept_options_candidate(
        session,
        cand.id,
        account_name=fx.OPTIONS_ACCOUNT,
        plan=plan,
        pricing=fx.pricing(),
        actor=actor,
        note="test open",
    )


# --------------------------------------------------------------------------- #
# Acceptance
# --------------------------------------------------------------------------- #


def test_an_acceptance_writes_the_structure_its_legs_and_the_immutable_trade(
    session: Session,
) -> None:
    cand, acct = _world(session)
    res = _open(session, cand)

    position = session.get(OptionsPosition, res.position_id)  # type: ignore[attr-defined]
    assert position is not None
    assert position.account_id == acct.id
    assert position.underlying_symbol == fx.UNDERLYING
    assert position.structure_type == "vertical_credit"
    assert position.expiration_date == fx.EXPIRY
    assert position.signal_session == fx.SIGNAL_SESSION
    assert position.fill_session == fx.FILL_SESSION
    assert len(position.legs) == 2
    # The multiplier is COPIED from the contract row at entry, so the x100
    # arithmetic in R and in the collateral basis is auditable on the row.
    assert {leg.shares_per_contract for leg in position.legs} == {100}
    assert {leg.exercise_style for leg in position.legs} == {"american"}

    trade = session.get(OptionsTrade, res.options_trade_id)  # type: ignore[attr-defined]
    assert trade is not None
    assert trade.decision is PaperDecision.ACCEPTED
    assert trade.options_position_id == position.id
    snap = trade.signal_snapshot_json
    opts = snap["options"]
    for key in (
        "legs",
        "fills",
        "entry_net_premium",
        "entry_costs",
        "max_loss_dollars_R",
        "collateral_reserved",
        "collateral_basis",
        "limits_evaluated",
        "credit_to_width",
        "short_leg_delta",
        "net_delta_notional",
        "net_vega_per_vol_pt",
        "theta_credit_after_costs_to_R",
        "signal_session",
        "fill_session",
        "fill_model",
        "cost_model",
        "iv_source",
        "q_source",
        "greeks_source",
        "disclosures",
        "options_scope_hash",
    ):
        assert key in opts, key
    # the equity snapshot's candidate-level keys are still present, unchanged
    for key in ("approval_scope", "scan", "strategy", "code_version", "reasons_fail"):
        assert key in snap, key
    assert opts["notice"] == "SIMULATED options structure — no order was placed."
    assert any("NBBO unavailable" in d for d in opts["disclosures"])
    assert any("IN THE STRATEGY'S FAVOUR" in d for d in opts["disclosures"])


def test_the_options_trade_is_immutable(session: Session) -> None:
    """Invariant S9, by the same mechanism as ``paper_trade``: a pair of SQLite
    BEFORE triggers, not an ORM exception class."""
    cand, _ = _world(session)
    res = _open(session, cand)
    session.commit()
    trade = session.get(OptionsTrade, res.options_trade_id)  # type: ignore[attr-defined]
    assert trade is not None
    trade.note = "edited"
    with pytest.raises(Exception, match=r"immutable|options_trade"):
        session.flush()
    session.rollback()


def test_the_collateral_entry_and_the_mark_are_immutable(session: Session) -> None:
    from sqlalchemy import text

    cand, _ = _world(session)
    _open(session, cand)
    nxt = _sessions_after(fx.FILL_SESSION, 1)[0]
    fx.option_prints(session, sessions=[nxt])
    mark_options_to_market(
        session, account_name=fx.OPTIONS_ACCOUNT, as_of=nxt, pricing=fx.resolver()
    )
    reconcile_options_collateral(session, account_name=fx.OPTIONS_ACCOUNT, as_of=nxt)
    session.commit()
    for table in ("options_collateral_entry", "options_mark", "options_reconcile_report"):
        assert session.execute(text(f"SELECT count(*) FROM {table}")).scalar() > 0, table
        with pytest.raises(Exception, match=r"append-only|immutable"):
            session.execute(text(f"UPDATE {table} SET id = id"))
        session.rollback()
        with pytest.raises(Exception, match=r"append-only|immutable"):
            session.execute(text(f"DELETE FROM {table}"))
        session.rollback()


def test_the_credit_lands_in_cash_and_spendable_falls_by_exactly_R(session: Session) -> None:
    """D3 §8.0's stated invariant. The GROSS requirement is reserved; the credit
    lands in cash; the net effect on buying power is the structure's max loss."""
    cand, acct = _world(session)
    before_cash = acct.cash
    before_spendable = acct.spendable_cash
    res = _open(session, cand)
    position = session.get(OptionsPosition, res.position_id)  # type: ignore[attr-defined]
    assert position is not None
    r = float(position.r_dollars)

    assert float(acct.cash) > float(before_cash)  # the credit landed
    assert float(acct.collateral_reserved) == pytest.approx(200.0)  # width 2 x 100 x 1
    assert float(before_spendable - acct.spendable_cash) == pytest.approx(r, abs=1e-4)


def test_the_collateral_basis_records_every_input_and_re_evaluates(session: Session) -> None:
    cand, acct = _world(session)
    res = _open(session, cand)
    entry = session.scalar(
        select(OptionsCollateralEntry).where(
            OptionsCollateralEntry.position_id == res.position_id  # type: ignore[attr-defined]
        )
    )
    assert entry is not None
    assert entry.event == "reserve"
    basis = entry.basis_json
    assert basis["formula"] == "strike_width * M * contracts"
    assert basis["shares_per_contract"] == 100
    assert basis["strike_width"] == pytest.approx(2.0)
    assert float(entry.balance_after) == pytest.approx(float(acct.collateral_reserved))
    from signalforge.paper.options_ledger import reevaluate_basis

    assert reevaluate_basis(basis) == pytest.approx(float(entry.amount))


def test_a_debit_vertical_reserves_nothing_because_the_cash_already_left(
    session: Session,
) -> None:
    """One consistent rule across every formula: spendable_cash falls by exactly
    R. Reserving the debit again would tie up 2R."""
    from signalforge.paper.options_ledger import LegSpec, StructureSpec

    structure = StructureSpec(
        structure_type="vertical_debit",
        underlying_symbol=fx.UNDERLYING,
        contracts=1,
        legs=(
            LegSpec(fx.SHORT_TICKER, "put", 430.0, fx.EXPIRY, 1, 100, "american"),
            LegSpec(fx.LONG_TICKER, "put", 428.0, fx.EXPIRY, -1, 100, "american"),
        ),
    )
    basis = collateral_basis(structure, net_credit_received=-50.0, entry_costs=2.0)
    assert basis["formula"] == "cash_settled_at_entry"
    assert basis["amount"] == 0.0


def test_the_acceptance_refuses_a_wrong_account_even_with_a_valid_plan(
    session: Session,
) -> None:
    cand, _ = _world(session)
    fx.equity_account(session)
    plan = assert_options_auto_simulate_allowed(
        session,
        cand,
        account_name=fx.OPTIONS_ACCOUNT,
        pricing=fx.pricing(),
        signal_session=fx.SIGNAL_SESSION,
        fill_session=fx.FILL_SESSION,
    )
    with pytest.raises(OptionsAutoSimulateForbidden) as exc:
        accept_options_candidate(
            session, cand.id, account_name="default", plan=plan, pricing=fx.pricing()
        )
    assert exc.value.condition == "N"
    # and nothing was written against the equity account
    equity = session.scalar(select(PaperAccount).where(PaperAccount.name == "default"))
    assert equity is not None
    assert equity.collateral_reserved == Decimal("0")
    assert session.scalar(select(func.count()).select_from(OptionsPosition)) == 0


def test_the_acceptance_refuses_a_candidate_that_is_not_an_options_candidate(
    session: Session,
) -> None:
    cand, _ = _world(session)
    plan = assert_options_auto_simulate_allowed(
        session,
        cand,
        account_name=fx.OPTIONS_ACCOUNT,
        pricing=fx.pricing(),
        signal_session=fx.SIGNAL_SESSION,
        fill_session=fx.FILL_SESSION,
    )
    cand.structure_kind = None
    session.flush()
    with pytest.raises(OptionsAutoSimulateForbidden) as exc:
        accept_options_candidate(
            session, cand.id, account_name=fx.OPTIONS_ACCOUNT, plan=plan, pricing=fx.pricing()
        )
    assert exc.value.condition == "C"


def test_a_refusal_is_recorded_as_immutable_evidence_not_dropped(session: Session) -> None:
    cand, _ = _world(session)
    trade_id = record_options_decision(
        session,
        cand.id,
        PaperDecision.REJECTED,
        account_name=fx.OPTIONS_ACCOUNT,
        note="options auto-simulation refused: S: |short leg delta| too high",
        actor="options_auto_simulate",
        refused_condition="S",
    )
    trade = session.get(OptionsTrade, trade_id)
    assert trade is not None
    assert trade.refused is True
    assert trade.refused_condition == "S"
    opts = trade.signal_snapshot_json["options"]
    assert opts["refused"] is True
    assert opts["refused_condition"] == "S"
    assert "REFUSED" in opts["notice"]
    assert session.scalar(select(func.count()).select_from(OptionsPosition)) == 0


# --------------------------------------------------------------------------- #
# Marks
# --------------------------------------------------------------------------- #


def _sessions_after(start: date, n: int) -> list[date]:
    from signalforge.data import calendar

    out: list[date] = []
    d = start + timedelta(days=1)
    while len(out) < n:
        if calendar.is_session(d):
            out.append(d)
        d += timedelta(days=1)
    return out


def test_a_mark_values_the_structure_and_records_the_honesty_counters(
    session: Session,
) -> None:
    cand, _ = _world(session)
    _open(session, cand)
    nxt = _sessions_after(fx.FILL_SESSION, 1)[0]
    fx.option_prints(session, sessions=[nxt])

    res = mark_options_to_market(
        session, account_name=fx.OPTIONS_ACCOUNT, as_of=nxt, pricing=fx.resolver()
    )
    assert res.checked == 1 and res.closed == 0
    assert res.synthetic_marked == 0 and res.iv_unavailable == 0
    mark = session.scalar(select(OptionsMark).where(OptionsMark.as_of == nxt))
    assert mark is not None
    assert mark.legs_priced == 2 and mark.legs_total == 2
    assert mark.synthetic is False
    # net premium is the COST TO CLOSE from unadjusted prints: (1.20-0.70)*100
    assert float(mark.net_premium) == pytest.approx(50.0)
    assert mark.short_leg_delta is not None and mark.short_leg_delta < 0


def test_a_missing_leg_print_marks_synthetic_and_never_fills(session: Session) -> None:
    cand, _ = _world(session)
    _open(session, cand)
    nxt = _sessions_after(fx.FILL_SESSION, 1)[0]
    fx.option_prints(session, sessions=[nxt], skip=(fx.LONG_TICKER,))

    res = mark_options_to_market(
        session, account_name=fx.OPTIONS_ACCOUNT, as_of=nxt, pricing=fx.resolver()
    )
    assert res.synthetic_marked == 1
    assert res.closed == 0
    mark = session.scalar(select(OptionsMark).where(OptionsMark.as_of == nxt))
    assert mark is not None and mark.legs_priced == 1 and mark.synthetic is True


def test_a_profit_target_is_observed_at_the_close_and_filled_at_t_plus_1(
    session: Session,
) -> None:
    """The backtest engine's convention, byte for byte: a close-basis trigger is
    observed at ``u`` and actionable at ``u+1``. There is no resting stop order
    anywhere in this design."""
    cand, _ = _world(session)
    _open(session, cand)
    s1, s2 = _sessions_after(fx.FILL_SESSION, 2)
    # the spread collapses: cost to close falls to 25% of the credit received
    fx.option_prints(session, sessions=[s1, s2], short_close=0.30, long_close=0.20)

    first = mark_options_to_market(
        session, account_name=fx.OPTIONS_ACCOUNT, as_of=s1, pricing=fx.resolver()
    )
    assert first.closed == 0  # observed, not filled
    position = session.scalar(select(OptionsPosition))
    assert position is not None
    assert position.exit_signalled_at == s1
    assert position.closed_at is None

    second = mark_options_to_market(
        session, account_name=fx.OPTIONS_ACCOUNT, as_of=s2, pricing=fx.resolver()
    )
    assert second.closed == 1
    session.refresh(position)
    assert position.exit_reason == "target"
    assert position.closed_at is not None
    assert position.pnl_r is not None


def test_a_stop_is_struck_against_the_credit_received_not_the_underlying(
    session: Session,
) -> None:
    cand, _ = _world(session)
    _open(session, cand)
    s1, s2 = _sessions_after(fx.FILL_SESSION, 2)
    # cost to close more than doubles: 2x the credit received is the stop
    fx.option_prints(session, sessions=[s1, s2], short_close=3.00, long_close=0.50)

    mark_options_to_market(
        session, account_name=fx.OPTIONS_ACCOUNT, as_of=s1, pricing=fx.resolver()
    )
    position = session.scalar(select(OptionsPosition))
    assert position is not None and position.exit_signalled_at == s1
    mark_options_to_market(
        session, account_name=fx.OPTIONS_ACCOUNT, as_of=s2, pricing=fx.resolver()
    )
    session.refresh(position)
    assert position.exit_reason == "stop"
    assert float(position.realized_pnl) < 0


def test_an_exit_fill_DEFERS_when_a_leg_stops_printing(session: Session) -> None:
    """A synthetic mark may trigger a signal; it may never set a fill price. The
    deferral is a cost that is borne, recorded, and reported."""
    cand, _ = _world(session)
    _open(session, cand)
    s1, s2, s3 = _sessions_after(fx.FILL_SESSION, 3)
    fx.option_prints(session, sessions=[s1], short_close=0.30, long_close=0.20)
    fx.option_prints(session, sessions=[s2], short_close=0.30, skip=(fx.LONG_TICKER,))
    fx.option_prints(session, sessions=[s3], short_close=0.30, long_close=0.20)

    mark_options_to_market(
        session, account_name=fx.OPTIONS_ACCOUNT, as_of=s1, pricing=fx.resolver()
    )
    deferred = mark_options_to_market(
        session, account_name=fx.OPTIONS_ACCOUNT, as_of=s2, pricing=fx.resolver()
    )
    assert deferred.deferred == 1 and deferred.closed == 0
    position = session.scalar(select(OptionsPosition))
    assert position is not None and position.exit_deferred_sessions == 1
    assert position.closed_at is None

    filled = mark_options_to_market(
        session, account_name=fx.OPTIONS_ACCOUNT, as_of=s3, pricing=fx.resolver()
    )
    assert filled.closed == 1
    session.refresh(position)
    assert position.exit_deferred_sessions == 1  # the deferral stays on the record


def test_a_time_stop_fills_on_its_own_session_because_it_is_calendar_knowable(
    session: Session,
) -> None:
    cand, _ = _world(session)
    _open(session, cand)
    position = session.scalar(select(OptionsPosition))
    assert position is not None
    # A DTE inside the time stop, without touching the profit/stop levels.
    on = fx.EXPIRY - timedelta(days=position.time_stop_dte)
    fx.option_prints(session, sessions=[on])
    res = mark_options_to_market(
        session, account_name=fx.OPTIONS_ACCOUNT, as_of=on, pricing=fx.resolver()
    )
    assert res.closed == 1
    session.refresh(position)
    assert position.exit_reason == "time_stop"


def test_closing_works_while_the_kill_switch_is_engaged(session: Session) -> None:
    """Closing is protective: the switch blocks opening and never blocks closing."""
    from signalforge.killswitch import get_kill_switch

    cand, _ = _world(session)
    _open(session, cand)
    s1, s2 = _sessions_after(fx.FILL_SESSION, 2)
    fx.option_prints(session, sessions=[s1, s2], short_close=0.30, long_close=0.20)
    get_kill_switch().engage(reason="test", actor="test")
    try:
        mark_options_to_market(
            session, account_name=fx.OPTIONS_ACCOUNT, as_of=s1, pricing=fx.resolver()
        )
        res = mark_options_to_market(
            session, account_name=fx.OPTIONS_ACCOUNT, as_of=s2, pricing=fx.resolver()
        )
        assert res.closed == 1
        rec = reconcile_options_collateral(session, account_name=fx.OPTIONS_ACCOUNT, as_of=s2)
        assert rec.clean
        # but opening refuses
        with pytest.raises(Exception, match=r"kill switch|engaged"):
            assert_options_auto_simulate_allowed(
                session,
                cand,
                account_name=fx.OPTIONS_ACCOUNT,
                pricing=fx.pricing(),
                signal_session=fx.SIGNAL_SESSION,
                fill_session=fx.FILL_SESSION,
            )
    finally:
        get_kill_switch().release(reason="test", actor="test")


# --------------------------------------------------------------------------- #
# Expiry
# --------------------------------------------------------------------------- #


def test_a_structure_force_closes_at_expiry_minus_one(session: Session) -> None:
    from signalforge.data import options_calendar

    cand, acct = _world(session)
    _open(session, cand)
    fc = options_calendar.force_close_session(fx.EXPIRY)
    fx.option_prints(session, sessions=[fc], short_close=0.05, long_close=0.02)

    report = process_option_expiries(
        session, account_name=fx.OPTIONS_ACCOUNT, as_of=fc, pricing=fx.resolver()
    )
    assert report.force_closed == 1
    assert report.forced_close_no_print == 0
    position = session.scalar(select(OptionsPosition))
    assert position is not None
    assert position.exit_reason == "forced_pre_expiry"
    assert position.closed_at is not None
    assert acct.collateral_reserved == Decimal("0")


def test_a_force_close_with_no_print_settles_at_the_intrinsic_floor_and_is_flagged(
    session: Session,
) -> None:
    """It is NOT excluded from the sample: a paper stream that drops its
    inconvenient trades is not a confirming test."""
    from signalforge.data import options_calendar

    cand, _ = _world(session)
    _open(session, cand)
    fc = options_calendar.force_close_session(fx.EXPIRY)  # no option prints at all

    report = process_option_expiries(
        session, account_name=fx.OPTIONS_ACCOUNT, as_of=fc, pricing=fx.resolver()
    )
    assert report.force_closed == 1 and report.forced_close_no_print == 1
    position = session.scalar(select(OptionsPosition))
    assert position is not None
    assert position.forced_close_no_print is True
    assert position.exit_reason == "forced_pre_expiry"


def test_a_structure_that_reaches_expiry_out_of_the_money_expires_worthless(
    session: Session,
) -> None:
    from signalforge.data import options_calendar

    cand, _ = _world(session)
    _open(session, cand)
    last = options_calendar.last_trade_session(fx.EXPIRY)
    # SPY closes at 450: both 430/428 puts are far out of the money.
    report = process_option_expiries(
        session, account_name=fx.OPTIONS_ACCOUNT, as_of=last, pricing=fx.resolver()
    )
    assert report.expired_worthless == 1 and report.assigned == 0
    position = session.scalar(select(OptionsPosition))
    assert position is not None
    assert position.exit_reason == "expired_worthless"
    assert float(position.exit_net_premium or 0) == pytest.approx(0.0)
    # the whole credit is kept, less the entry costs
    assert float(position.realized_pnl) > 0


def test_a_short_leg_in_the_money_at_expiry_is_settled_at_intrinsic_and_flagged(
    session: Session,
) -> None:
    """Phase 1 models no exercise/assignment PROCESS; it settles at intrinsic and
    says so on the record rather than guessing at an assignment path."""
    from signalforge.data import options_calendar
    from signalforge.db.models import Instrument, OHLCVDaily

    cand, _ = _world(session)
    _open(session, cand)
    last = options_calendar.last_trade_session(fx.EXPIRY)
    inst = session.scalar(select(Instrument).where(Instrument.symbol == fx.UNDERLYING))
    assert inst is not None
    for bar in session.scalars(
        select(OHLCVDaily).where(
            OHLCVDaily.instrument_id == inst.id, OHLCVDaily.session_date == last
        )
    ):
        bar.close = 429.0  # inside the spread: the short 430 put is ITM
    session.flush()

    report = process_option_expiries(
        session, account_name=fx.OPTIONS_ACCOUNT, as_of=last, pricing=fx.resolver()
    )
    assert report.assigned == 1 and report.expired_worthless == 0
    position = session.scalar(select(OptionsPosition))
    assert position is not None
    assert position.exit_reason == "assigned"
    assert position.assignment_risk_flag is True
    # intrinsic of the 430 short put at 429 is $1.00 x 100 = $100 to close
    assert float(position.exit_net_premium or 0) == pytest.approx(100.0)


def test_an_unresolvable_expiry_raises_rather_than_guessing(session: Session) -> None:
    from signalforge.data import options_calendar
    from signalforge.db.models import Instrument, OHLCVDaily

    cand, _ = _world(session)
    _open(session, cand)
    last = options_calendar.last_trade_session(fx.EXPIRY)
    inst = session.scalar(select(Instrument).where(Instrument.symbol == fx.UNDERLYING))
    assert inst is not None
    for bar in session.scalars(
        select(OHLCVDaily).where(
            OHLCVDaily.instrument_id == inst.id,
            OHLCVDaily.session_date >= last - timedelta(days=30),
        )
    ):
        session.delete(bar)
    session.flush()
    with pytest.raises(OptionExpiryUnhandled, match="does not guess"):
        process_option_expiries(
            session, account_name=fx.OPTIONS_ACCOUNT, as_of=last, pricing=fx.resolver()
        )


def test_expiry_processing_is_idempotent(session: Session) -> None:
    from signalforge.data import options_calendar

    cand, _ = _world(session)
    _open(session, cand)
    last = options_calendar.last_trade_session(fx.EXPIRY)
    first = process_option_expiries(
        session, account_name=fx.OPTIONS_ACCOUNT, as_of=last, pricing=fx.resolver()
    )
    second = process_option_expiries(
        session, account_name=fx.OPTIONS_ACCOUNT, as_of=last, pricing=fx.resolver()
    )
    assert first.checked == 1 and second.checked == 0
    assert session.scalar(select(func.count()).select_from(OptionsPosition)) == 1


# --------------------------------------------------------------------------- #
# Reconciliation
# --------------------------------------------------------------------------- #


def test_reconciliation_is_clean_on_a_healthy_book_and_round_trips_to_zero(
    session: Session,
) -> None:
    from signalforge.data import options_calendar

    cand, acct = _world(session)
    _open(session, cand)
    open_report = reconcile_options_collateral(
        session, account_name=fx.OPTIONS_ACCOUNT, as_of=fx.FILL_SESSION
    )
    assert open_report.clean and open_report.open_structures == 1
    assert open_report.collateral_reserved_observed == pytest.approx(200.0)

    fc = options_calendar.force_close_session(fx.EXPIRY)
    fx.option_prints(session, sessions=[fc], short_close=0.05, long_close=0.02)
    process_option_expiries(
        session, account_name=fx.OPTIONS_ACCOUNT, as_of=fc, pricing=fx.resolver()
    )
    closed_report = reconcile_options_collateral(session, account_name=fx.OPTIONS_ACCOUNT, as_of=fc)
    assert closed_report.clean
    assert closed_report.collateral_reserved_observed == pytest.approx(0.0)
    assert acct.collateral_reserved == Decimal("0")
    reserves = list(session.scalars(select(OptionsCollateralEntry)))
    assert [e.event for e in reserves] == ["reserve", "release"]
    assert reserves[0].amount == reserves[1].amount


def test_the_reconciler_REPORTS_and_does_not_repair(session: Session) -> None:
    cand, acct = _world(session)
    _open(session, cand)
    acct.collateral_reserved = acct.collateral_reserved + Decimal("13")  # forced divergence
    session.flush()

    report = reconcile_options_collateral(
        session, account_name=fx.OPTIONS_ACCOUNT, as_of=fx.FILL_SESSION
    )
    assert not report.clean
    checks = {f["check"] for f in report.findings}
    assert "1_balance_matches_ledger" in checks
    assert "2_balance_matches_open_structures" in checks
    # NOT repaired: a reconciler that silently repairs hides the bug it found.
    assert acct.collateral_reserved == Decimal("213")


def test_check_5_catches_a_closed_structure_with_collateral_still_reserved(
    session: Session,
) -> None:
    """The CONSERVATIVE crash window (D3 §8 step 4): write-then-release leaves a
    closed structure holding capacity, which blocks rather than fails open."""
    from signalforge.db.types import utcnow

    cand, _acct = _world(session)
    res = _open(session, cand)
    position = session.get(OptionsPosition, res.position_id)  # type: ignore[attr-defined]
    assert position is not None
    position.closed_at = utcnow()  # closed, but no release was written
    position.exit_reason = "stop"
    session.flush()

    report = reconcile_options_collateral(
        session, account_name=fx.OPTIONS_ACCOUNT, as_of=fx.FILL_SESSION
    )
    assert not report.clean
    checks = {f["check"] for f in report.findings}
    assert "5_closed_has_no_unreleased_reserve" in checks


def test_check_6_catches_the_FAIL_OPEN_ordering_at_the_highest_severity(
    session: Session,
) -> None:
    """Collateral freed while the structure is still open inflates spendable_cash
    and re-opens capacity under conditions O / P / R."""
    cand, acct = _world(session)
    res = _open(session, cand)
    position = session.get(OptionsPosition, res.position_id)  # type: ignore[attr-defined]
    assert position is not None
    session.add(
        OptionsCollateralEntry(
            account_id=acct.id,
            position_id=position.id,
            event="release",
            amount=position.collateral_reserved,
            basis_json={"formula": "release_of_reserve", "amount": 200.0},
            balance_after=Decimal("0"),
            as_of=fx.FILL_SESSION,
        )
    )
    session.flush()

    report = reconcile_options_collateral(
        session, account_name=fx.OPTIONS_ACCOUNT, as_of=fx.FILL_SESSION
    )
    assert not report.clean
    finding = next(f for f in report.findings if f["check"] == "6_open_has_no_release")
    assert finding["severity"] == "critical"


def test_a_second_release_is_refused_and_the_audit_figure_survives_the_close(
    session: Session,
) -> None:
    """A double release is the FAIL-OPEN direction — free capacity with no
    structure behind it — so it is refused at the ledger, not merely made
    unlikely by control flow. The structure keeps its ``collateral_reserved``
    figure after the close: that is the number reconcile check 4 compares."""
    from signalforge.data import options_calendar
    from signalforge.paper.options_ledger import release_collateral

    cand, acct = _world(session)
    res = _open(session, cand)
    fc = options_calendar.force_close_session(fx.EXPIRY)
    fx.option_prints(session, sessions=[fc], short_close=0.05, long_close=0.02)
    process_option_expiries(
        session, account_name=fx.OPTIONS_ACCOUNT, as_of=fc, pricing=fx.resolver()
    )
    position = session.get(OptionsPosition, res.position_id)  # type: ignore[attr-defined]
    assert position is not None
    assert position.closed_at is not None
    assert float(position.collateral_reserved) == pytest.approx(200.0)  # kept, for audit
    assert acct.collateral_reserved == Decimal("0")

    assert release_collateral(session, acct, position, as_of=fc) is None
    assert acct.collateral_reserved == Decimal("0")  # not driven negative
    releases = [e for e in session.scalars(select(OptionsCollateralEntry)) if e.event == "release"]
    assert len(releases) == 1
    assert reconcile_options_collateral(session, account_name=fx.OPTIONS_ACCOUNT, as_of=fc).clean


def test_check_7_catches_a_basis_that_does_not_re_evaluate(session: Session) -> None:
    cand, acct = _world(session)
    res = _open(session, cand)
    # A second reserve whose basis cannot produce its own amount.
    session.add(
        OptionsCollateralEntry(
            account_id=acct.id,
            position_id=res.position_id,  # type: ignore[attr-defined]
            event="reserve",
            amount=Decimal("999"),
            basis_json={
                "formula": "strike_width * M * contracts",
                "strike_width": 2.0,
                "shares_per_contract": 100,
                "contracts": 1,
            },
            balance_after=Decimal("1199"),
            as_of=fx.FILL_SESSION,
        )
    )
    session.flush()
    report = reconcile_options_collateral(
        session, account_name=fx.OPTIONS_ACCOUNT, as_of=fx.FILL_SESSION
    )
    checks = {f["check"] for f in report.findings}
    assert "7_basis_reevaluates" in checks


def test_check_9_catches_a_book_above_the_collateral_cap(session: Session) -> None:
    cand, _ = _world(session)
    _open(session, cand)
    set_setting(session, RESEARCH_OVERRIDES_KEY, {"options_risk": {"collateral_cap_dollars": 10.0}})
    report = reconcile_options_collateral(
        session, account_name=fx.OPTIONS_ACCOUNT, as_of=fx.FILL_SESSION
    )
    checks = {f["check"] for f in report.findings}
    assert "9_collateral_within_cap" in checks


def test_check_10_catches_a_post_entry_multiplier_change(session: Session) -> None:
    cand, _ = _world(session)
    res = _open(session, cand)
    position = session.get(OptionsPosition, res.position_id)  # type: ignore[attr-defined]
    assert position is not None
    position.legs[0].shares_per_contract = 10  # an OCC adjustment after entry
    session.flush()
    report = reconcile_options_collateral(
        session, account_name=fx.OPTIONS_ACCOUNT, as_of=fx.FILL_SESSION
    )
    checks = {f["check"] for f in report.findings}
    assert "10_shares_per_contract_still_100" in checks


def test_a_divergent_reconciliation_blocks_OPENING_and_never_closing(
    session: Session,
) -> None:
    cand, acct = _world(session)
    _open(session, cand)
    acct.collateral_reserved = acct.collateral_reserved + Decimal("7")
    session.flush()
    s1, s2 = _sessions_after(fx.FILL_SESSION, 2)
    reconcile_options_collateral(session, account_name=fx.OPTIONS_ACCOUNT, as_of=s1)
    row = session.scalar(select(OptionsReconcileReport).where(OptionsReconcileReport.as_of == s1))
    assert row is not None and row.clean is False

    # closing still works
    fx.option_prints(session, sessions=[s1, s2], short_close=0.30, long_close=0.20)
    mark_options_to_market(
        session, account_name=fx.OPTIONS_ACCOUNT, as_of=s1, pricing=fx.resolver()
    )
    res = mark_options_to_market(
        session, account_name=fx.OPTIONS_ACCOUNT, as_of=s2, pricing=fx.resolver()
    )
    assert res.closed == 1


# --------------------------------------------------------------------------- #
# Determinism and reporting
# --------------------------------------------------------------------------- #


def test_the_same_inputs_produce_the_same_structure_R_collateral_and_snapshot(
    session: Session,
) -> None:
    """Invariant S4. Deterministic: pure arithmetic over the input rows, no RNG."""
    import json

    cand, _ = _world(session)
    plan_a = assert_options_auto_simulate_allowed(
        session,
        cand,
        account_name=fx.OPTIONS_ACCOUNT,
        pricing=fx.pricing(),
        signal_session=fx.SIGNAL_SESSION,
        fill_session=fx.FILL_SESSION,
    )
    plan_b = assert_options_auto_simulate_allowed(
        session,
        cand,
        account_name=fx.OPTIONS_ACCOUNT,
        pricing=fx.pricing(),
        signal_session=fx.SIGNAL_SESSION,
        fill_session=fx.FILL_SESSION,
    )
    assert plan_a.r_dollars == plan_b.r_dollars
    assert plan_a.collateral_required == plan_b.collateral_required
    assert plan_a.greeks == plan_b.greeks
    assert json.dumps(plan_a.limits.to_dict(), sort_keys=True) == json.dumps(
        plan_b.limits.to_dict(), sort_keys=True
    )


def test_the_status_snapshot_reports_both_books_side_by_side_never_merged(
    session: Session,
) -> None:
    cand, _ = _world(session)
    _open(session, cand)
    nxt = _sessions_after(fx.FILL_SESSION, 1)[0]
    fx.option_prints(session, sessions=[nxt])
    mark_options_to_market(
        session, account_name=fx.OPTIONS_ACCOUNT, as_of=nxt, pricing=fx.resolver()
    )
    reconcile_options_collateral(session, account_name=fx.OPTIONS_ACCOUNT, as_of=nxt)

    snap = options_portfolio_snapshot(session, account_name=fx.OPTIONS_ACCOUNT, as_of=nxt)
    assert snap["exists"] is True
    assert snap["account"] == fx.OPTIONS_ACCOUNT
    assert snap["n_open"] == 1
    assert snap["collateral_reserved"] == pytest.approx(200.0)
    assert snap["spendable_cash"] == pytest.approx(snap["cash"] - snap["collateral_reserved"])
    g = snap["greeks"]
    # the equity book is reported separately and the combined figure is its own
    # block — never a merged equity figure.
    assert set(g) == {
        "options_net_delta_notional",
        "options_net_vega_per_vol_pt",
        "equity_net_delta_notional",
        "combined_net_delta_notional",
    }
    assert snap["reconciliation"]["clean"] is True
    assert snap["auto_simulate"]["setting_key"] == OPTIONS_AUTO_SIM_ENABLED_KEY
    assert snap["notice"] == "SIMULATED options structure — no order was placed."
    assert any("SEPARATE populations" in d for d in snap["disclosures"])


def test_the_status_snapshot_says_how_to_create_a_missing_account(session: Session) -> None:
    snap = options_portfolio_snapshot(session, account_name=fx.OPTIONS_ACCOUNT)
    assert snap["exists"] is False
    assert "paper init --name options --cash 25,000" in snap["hint"].replace(",000", ",000")


def test_a_structure_from_a_position_round_trips_its_legs(session: Session) -> None:
    cand, _ = _world(session)
    res = _open(session, cand)
    position = session.get(OptionsPosition, res.position_id)  # type: ignore[attr-defined]
    assert position is not None
    structure = structure_from_position(position)
    assert structure.multiplier == 100
    assert structure.strike_width == pytest.approx(2.0)
    assert structure.short_leg is not None and structure.short_leg.strike == fx.SHORT_STRIKE
    assert structure.contract_sides == 2


# --------------------------------------------------------------------------- #
# W5b — pricing resolved PER UNDERLYING (decision 11)
# --------------------------------------------------------------------------- #


def _open_second_name(session: Session, first: Candidate) -> Candidate:
    """A second open structure, on a SECOND underlying, through the real door.

    Built with the guard and the acceptance rather than by hand: a position row
    conjured directly would carry no collateral entry and would make the
    reconciler fail for a reason that has nothing to do with what is under test.
    """
    from signalforge.db.models import StrategyVersion

    version = session.get(StrategyVersion, first.strategy_version_id)
    assert version is not None
    inst = fx.underlying(session, symbol=fx.UNDERLYING_2)
    fx.contracts(session, symbol=fx.UNDERLYING_2)
    fx.option_prints(session, sessions=[fx.SIGNAL_SESSION, fx.FILL_SESSION], symbol=fx.UNDERLYING_2)
    cand = fx.options_candidate(session, instrument=inst, version=version, symbol=fx.UNDERLYING_2)
    fx.approve_scope(session, cand, version, universe=(fx.UNDERLYING_2,))
    _open(session, cand)
    return cand


def test_a_multi_underlying_book_marks_each_name_with_ITS_OWN_q(session: Session) -> None:
    """The defect W5b repairs, stated as an assertion.

    Before this, one ``OptionsPricingContext`` served a whole call, so a two-name
    book would have been marked with one name's dividend yield applied to both —
    and the chain refused the whole run rather than do it. Now each structure is
    marked under the context resolved for ITS underlying, and the row says which.
    """
    first, _ = _world(session)
    _open(session, first)
    _open_second_name(session, first)

    nxt = _sessions_after(fx.FILL_SESSION, 1)[0]
    fx.option_prints(session, sessions=[nxt])
    fx.option_prints(session, sessions=[nxt], symbol=fx.UNDERLYING_2)

    res = mark_options_to_market(
        session,
        account_name=fx.OPTIONS_ACCOUNT,
        as_of=nxt,
        pricing=fx.resolver(
            contexts={
                fx.UNDERLYING: fx.pricing(dividend_yield=0.0130, q_source="fixture:spy_ttm"),
                fx.UNDERLYING_2: fx.pricing(dividend_yield=0.0750, q_source="fixture:iwm_ttm"),
            }
        ),
    )
    assert res.checked == 2 and res.unpriceable == 0
    assert res.unpriceable_underlyings == []

    marks = {}
    for position in session.scalars(select(OptionsPosition)):
        mark = session.scalar(
            select(OptionsMark).where(
                OptionsMark.position_id == position.id, OptionsMark.as_of == nxt
            )
        )
        assert mark is not None
        marks[position.underlying_symbol] = mark

    assert set(marks) == {fx.UNDERLYING, fx.UNDERLYING_2}
    assert marks[fx.UNDERLYING].dividend_yield == pytest.approx(0.0130)
    assert marks[fx.UNDERLYING_2].dividend_yield == pytest.approx(0.0750)
    assert marks[fx.UNDERLYING].q_source == "fixture:spy_ttm"
    assert marks[fx.UNDERLYING_2].q_source == "fixture:iwm_ttm"
    # ...and the greeks differ, which is the reason the q had to: same prints,
    # same strikes, same spot, different dividend yield.
    assert marks[fx.UNDERLYING].net_delta_shares != marks[fx.UNDERLYING_2].net_delta_shares


def test_a_name_with_no_dividend_series_is_REFUSED_BY_NAME_and_the_rest_is_marked(
    session: Session,
) -> None:
    first, _ = _world(session)
    _open(session, first)
    _open_second_name(session, first)

    nxt = _sessions_after(fx.FILL_SESSION, 1)[0]
    fx.option_prints(session, sessions=[nxt])
    fx.option_prints(session, sessions=[nxt], symbol=fx.UNDERLYING_2)

    res = mark_options_to_market(
        session,
        account_name=fx.OPTIONS_ACCOUNT,
        as_of=nxt,
        pricing=fx.resolver(
            contexts={fx.UNDERLYING_2: fx.pricing()},
            unpriceable={fx.UNDERLYING: "no recorded dividend series"},
        ),
    )
    assert res.checked == 2
    assert res.unpriceable == 1
    assert res.unpriceable_underlyings == [fx.UNDERLYING]

    marked = list(session.scalars(select(OptionsMark).where(OptionsMark.as_of == nxt)))
    assert len(marked) == 1, "the priceable name is still marked"
    position = session.get(OptionsPosition, marked[0].position_id)
    assert position is not None and position.underlying_symbol == fx.UNDERLYING_2


def test_a_name_with_no_close_is_refused_by_the_recorded_series_resolver(
    session: Session,
) -> None:
    """``resolve_underlying_pricing`` is the production resolver, and it refuses
    on either missing input — naming which, and naming the underlying."""
    from signalforge.db.models import DividendEvent
    from signalforge.paper.options_marks import (
        UnderlyingNotPriceable,
        resolve_underlying_pricing,
    )

    session.add(
        DividendEvent(
            symbol=fx.UNDERLYING,
            ex_dividend_date=date(2025, 12, 18),
            cash_amount=1.50,
            source="massive_options",
            ingested_at=datetime.now(UTC),
        )
    )
    session.flush()
    with pytest.raises(UnderlyingNotPriceable, match=r"SPY: no ohlcv_daily close") as exc:
        resolve_underlying_pricing(
            session,
            fx.UNDERLYING,
            fx.FILL_SESSION,
            cost_model=fx.cost_model(),
            risk_free_rate=0.04,
        )
    assert exc.value.underlying == fx.UNDERLYING

    # with bars, the SAME call resolves and records the source it used
    fx.underlying(session)
    ctx = resolve_underlying_pricing(
        session,
        fx.UNDERLYING,
        fx.FILL_SESSION,
        cost_model=fx.cost_model(),
        risk_free_rate=0.04,
    )
    assert ctx.q_source == "vendor_dividends"
    assert ctx.dividend_yield == pytest.approx(1.50 / fx.SPOT)
    assert ctx.risk_free_rate == 0.04


def test_an_unmarked_structure_makes_the_session_reconciliation_dirty(session: Session) -> None:
    """Reconcile check 11, and the exemption that keeps it honest.

    A structure opened ON the session is exempt — condition M required every leg
    to print on its fill session, so the entry is its valuation. One carried into
    a later session with no mark could not be valued, and the report says so.
    """
    cand, _ = _world(session)
    _open(session, cand)

    # opened on the fill session: exempt, and the report is clean
    entry_day = reconcile_options_collateral(
        session, account_name=fx.OPTIONS_ACCOUNT, as_of=fx.FILL_SESSION
    )
    assert entry_day.clean

    nxt = _sessions_after(fx.FILL_SESSION, 1)[0]
    unmarked = reconcile_options_collateral(session, account_name=fx.OPTIONS_ACCOUNT, as_of=nxt)
    assert not unmarked.clean
    assert {f["check"] for f in unmarked.findings} == {"11_open_structure_marked_this_session"}
    assert fx.UNDERLYING in unmarked.findings[0]["detail"]

    # mark a LATER session and that session reconciles clean
    later = _sessions_after(nxt, 1)[0]
    fx.option_prints(session, sessions=[later])
    mark_options_to_market(
        session, account_name=fx.OPTIONS_ACCOUNT, as_of=later, pricing=fx.resolver()
    )
    assert reconcile_options_collateral(session, account_name=fx.OPTIONS_ACCOUNT, as_of=later).clean


def test_a_close_records_the_q_it_was_valued_under(session: Session) -> None:
    """The immutable trade carries the pricing block, per underlying."""
    cand, _ = _world(session)
    _open(session, cand)
    s1, s2 = _sessions_after(fx.FILL_SESSION, 2)
    fx.option_prints(session, sessions=[s1, s2], short_close=0.30, long_close=0.20)
    resolver = fx.resolver(
        contexts={fx.UNDERLYING: fx.pricing(dividend_yield=0.0211, q_source="fixture:spy_ttm")}
    )
    mark_options_to_market(session, account_name=fx.OPTIONS_ACCOUNT, as_of=s1, pricing=resolver)
    res = mark_options_to_market(
        session, account_name=fx.OPTIONS_ACCOUNT, as_of=s2, pricing=resolver
    )
    assert res.closed == 1

    trade = session.scalar(
        select(OptionsTrade)
        .where(OptionsTrade.decision == PaperDecision.ACCEPTED)
        .order_by(OptionsTrade.id.desc())
    )
    assert trade is not None
    block = trade.signal_snapshot_json["close"]["pricing"]
    assert block["underlying"] == fx.UNDERLYING
    assert block["q_source"] == "fixture:spy_ttm"
    assert block["dividend_yield"] == pytest.approx(0.0211)
    assert block["risk_free_rate"] == 0.04


def test_an_expiry_settlement_records_its_q_and_skips_an_unpriceable_name(
    session: Session,
) -> None:
    from signalforge.data import options_calendar

    cand, _ = _world(session)
    _open(session, cand)
    fc = options_calendar.force_close_session(fx.EXPIRY)
    fx.option_prints(session, sessions=[fc], short_close=0.05, long_close=0.02)

    # refused: nothing settles, and the name is reported
    refused = process_option_expiries(
        session,
        account_name=fx.OPTIONS_ACCOUNT,
        as_of=fc,
        pricing=fx.resolver(contexts={}, unpriceable={fx.UNDERLYING: "no dividend series"}),
    )
    assert refused.force_closed == 0
    assert refused.unpriceable == 1 and refused.unpriceable_underlyings == [fx.UNDERLYING]
    still_open = session.scalar(select(OptionsPosition))
    assert still_open is not None and still_open.closed_at is None

    # priceable: it settles, and the trade records the q it settled under
    ok = process_option_expiries(
        session,
        account_name=fx.OPTIONS_ACCOUNT,
        as_of=fc,
        pricing=fx.resolver(
            contexts={fx.UNDERLYING: fx.pricing(dividend_yield=0.019, q_source="fixture:spy_ttm")}
        ),
    )
    assert ok.force_closed == 1 and ok.unpriceable == 0
    trade = session.scalar(
        select(OptionsTrade)
        .where(OptionsTrade.decision == PaperDecision.ACCEPTED)
        .order_by(OptionsTrade.id.desc())
    )
    assert trade is not None
    assert trade.signal_snapshot_json["close"]["pricing"]["q_source"] == "fixture:spy_ttm"
