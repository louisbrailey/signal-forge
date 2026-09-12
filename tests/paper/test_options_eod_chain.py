"""The scheduled options paper EOD chain (W3c): off is byte-identical, on is ordered.

Three things are pinned here and nothing else:

1. **Off writes nothing.** With the flag off, or with the flag on and no options
   account, ``job_options_paper_eod`` returns before it opens a write
   transaction: not one row in any options table, not one ``audit_log`` row, not
   one setting touched. The off path is the live state of this box, so it is
   tested first and hardest.
2. **On runs mark -> reconcile -> expiry -> auto-simulate, in that order**, and
   the order is observed through recording fakes rather than inferred from
   source layout.
3. **The order is load-bearing, not decorative.** With the reconcile step
   removed, the second guard's condition AA refuses the acceptance — which is
   exactly why I-O6 refused to schedule the auto-simulation on its own.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

import signalforge.paper.options_auto_simulate as auto_mod
import signalforge.paper.options_eod as eod
import signalforge.paper.options_marks as marks_mod
import signalforge.scheduler as sched
from signalforge.db.models import (
    AuditLog,
    OptionsCollateralEntry,
    OptionsMark,
    OptionsPosition,
    OptionsReconcileReport,
    OptionsTrade,
    ScanRun,
)
from signalforge.domain import PaperDecision
from signalforge.paper.options_ledger import (
    OPTIONS_AUTO_SIM_CAP_KEY,
    OPTIONS_AUTO_SIM_ENABLED_KEY,
)
from signalforge.settings_store import RESEARCH_OVERRIDES_KEY, set_setting
from tests.paper import options_support as fx

#: 2026-02-17 (Tue) -> 2026-02-18 (Wed): signal at t, fill at t+1 (D3 §6.0).
SIGNAL_SCAN_STARTED = datetime(2026, 2, 17, 22, 30, tzinfo=UTC)


def _enable_chain(session: Session, *, on: bool = True) -> None:
    set_setting(session, RESEARCH_OVERRIDES_KEY, {"options": {"paper_eod_enabled": on}})


def _pin_sessions(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the chain's fill session to the fixture's, so the calendar's real
    previous-session walk lands on the fixture's signal session."""
    monkeypatch.setattr(eod, "last_completed_session", lambda: fx.FILL_SESSION)


def _pin_pricing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Use the fixture's explicit, non-defaulted pricing context.

    ``_options_eod_pricing`` has its own tests below; pinning it here keeps these
    tests about ORDERING and the guard, not about sourcing a dividend yield.
    """
    monkeypatch.setattr(
        eod, "_options_eod_pricing", lambda session, *, underlyings, as_of: fx.pricing()
    )


def _row_counts(session: Session) -> dict[str, int]:
    return {
        model.__name__: int(session.scalar(select(func.count()).select_from(model)) or 0)
        for model in (
            OptionsPosition,
            OptionsMark,
            OptionsTrade,
            OptionsCollateralEntry,
            OptionsReconcileReport,
            AuditLog,
        )
    }


# --------------------------------------------------------------------------- #
# 1. Off is byte-identical
# --------------------------------------------------------------------------- #
def test_the_flag_is_off_by_default_and_is_not_in_the_approval_scope_hash() -> None:
    from signalforge.config.research import ResearchConfig

    base = ResearchConfig()
    assert base.options.paper_eod_enabled is False
    flipped = base.model_copy(
        update={"options": base.options.model_copy(update={"paper_eod_enabled": True})}
    )
    # Flipping an OPERATING switch must not un-scope a live PAPER_APPROVED
    # equity strategy (the 2026-09-11 agents-section incident).
    assert "options" not in ResearchConfig.SCOPE_HASH_FIELDS
    assert flipped.config_hash == base.config_hash
    # ...and it is not part of an options EVALUATION's identity either.
    assert flipped.full_config_hash != base.full_config_hash  # but it IS audited


def test_off_writes_nothing_at_all(session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    """The default path on every deployment that has not opted in."""
    fx.options_account(session)
    session.commit()
    before = _row_counts(session)

    _pin_sessions(monkeypatch)
    eod.job_options_paper_eod()

    session.expire_all()
    assert _row_counts(session) == before
    assert before == {
        "OptionsPosition": 0,
        "OptionsMark": 0,
        "OptionsTrade": 0,
        "OptionsCollateralEntry": 0,
        "OptionsReconcileReport": 0,
        "AuditLog": 0,
    }


def test_off_never_takes_the_sqlite_write_lock(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Rule 3 of docs/SQLITE_CONCURRENCY.md: ``write=True`` takes BEGIN IMMEDIATE
    up front. A job that has opted out must never take it — on this box the
    worker shares the writer with the live equity chain."""
    import signalforge.db.session as db_session

    fx.options_account(session)
    session.commit()
    intents: list[bool] = []
    real = db_session.session_scope

    def _spy(*, write: bool = False):  # type: ignore[no-untyped-def]
        intents.append(write)
        return real(write=write)

    monkeypatch.setattr(db_session, "session_scope", _spy)
    _pin_sessions(monkeypatch)
    eod.job_options_paper_eod()
    assert intents == [False], "the off path opens exactly one plain reader"


def test_on_but_no_account_also_writes_nothing(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Both conditions are required, and the account one is checked in the same
    reader — a deployment that turned the flag on before creating the account
    gets a named warning, not a half-run chain."""
    _enable_chain(session)
    session.commit()
    before = _row_counts(session)

    _pin_sessions(monkeypatch)
    eod.job_options_paper_eod()

    session.expire_all()
    assert _row_counts(session) == before


def test_the_auto_simulation_step_needs_a_third_switch_of_its_own(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Turning the chain ON buys marks, reconciliation and expiry handling — all
    protective or read-mostly — and buys nothing that can open a structure."""
    cand = _world(session, arm=False)
    _enable_chain(session)
    session.commit()

    _pin_sessions(monkeypatch)
    _pin_pricing(monkeypatch)
    eod.job_options_paper_eod()

    session.expire_all()
    # the reconciliation DID run (protective, and condition AA's precondition)
    assert session.scalar(select(func.count()).select_from(OptionsReconcileReport)) == 1
    # ...and nothing was opened or even decided
    assert session.scalar(select(func.count()).select_from(OptionsTrade)) == 0
    assert session.scalar(select(func.count()).select_from(OptionsPosition)) == 0
    assert cand.id is not None


# --------------------------------------------------------------------------- #
# 2. On is ordered
# --------------------------------------------------------------------------- #
def test_on_runs_mark_then_reconcile_then_expiry_then_auto_simulate(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    fx.options_account(session)
    _enable_chain(session)
    session.commit()

    calls: list[str] = []

    def _mark(s, **kw):  # type: ignore[no-untyped-def]
        calls.append("mark")
        return marks_mod.OptionsMarkResult()

    def _reconcile(s, **kw):  # type: ignore[no-untyped-def]
        calls.append("reconcile")
        return marks_mod.ReconcileReport(as_of=kw["as_of"], clean=True)

    def _expiry(s, **kw):  # type: ignore[no-untyped-def]
        calls.append("expiry")
        return marks_mod.ExpiryReport()

    def _auto(s, ids, **kw):  # type: ignore[no-untyped-def]
        calls.append("auto_simulate")
        return auto_mod.OptionsAutoSimReport(enabled=False)

    monkeypatch.setattr(marks_mod, "mark_options_to_market", _mark)
    monkeypatch.setattr(marks_mod, "reconcile_options_collateral", _reconcile)
    monkeypatch.setattr(marks_mod, "process_option_expiries", _expiry)
    monkeypatch.setattr(auto_mod, "auto_simulate_options_scan_runs", _auto)
    _pin_sessions(monkeypatch)
    _pin_pricing(monkeypatch)

    eod.job_options_paper_eod()
    assert calls == ["mark", "reconcile", "expiry", "auto_simulate"]


def test_each_step_runs_in_its_own_short_write_transaction(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Rule 4 / rule 5: one short ``BEGIN IMMEDIATE`` per unit, so nothing holds
    the writer across the whole chain and a per-unit retry cannot duplicate a
    unit that already committed."""
    import signalforge.db.session as db_session

    fx.options_account(session)
    _enable_chain(session)
    session.commit()

    intents: list[bool] = []
    real = db_session.session_scope

    def _spy(*, write: bool = False):  # type: ignore[no-untyped-def]
        intents.append(write)
        return real(write=write)

    monkeypatch.setattr(db_session, "session_scope", _spy)
    _pin_sessions(monkeypatch)
    _pin_pricing(monkeypatch)
    eod.job_options_paper_eod()

    # two readers (the gate check, then the survey), then one writer per unit
    assert intents == [False, False, True, True, True, True]


def test_the_job_is_absent_from_default_job_specs_and_that_is_the_point(
    db_url: str, session: Session
) -> None:
    """``signalforge.app`` imports the scheduler and S16 reports indirect chains.

    So the scheduler must not reach the options paper layer at all, and the
    scheduler's own job list must therefore be byte-identical to what it was
    before this chain existed. Only the retry policy names the job, as a string.
    """
    fx.options_account(session)
    session.commit()
    assert "options_paper_eod" not in {s.name for s in sched.default_job_specs()}
    assert "options_paper_eod" in sched.NO_JOB_LEVEL_LOCK_RETRY


def test_the_spec_is_none_until_an_options_paper_account_exists(
    db_url: str, session: Session
) -> None:
    """With no options account the job has nothing it could ever act on, so the
    CLI-injected list is byte-identical to ``default_job_specs()``."""
    from signalforge.cli import _insert_options_eod

    assert eod.options_paper_eod_spec() is None
    base = sched.default_job_specs()
    assert [s.name for s in _insert_options_eod(base, None)] == [s.name for s in base]

    fx.options_account(session)
    session.commit()
    assert eod.options_paper_eod_spec() is not None


def test_the_cli_injected_list_carries_the_chain_in_the_18_30_slot(
    db_url: str, session: Session
) -> None:
    """What ``signalforge run-scheduler`` actually registers."""
    from signalforge.cli import _insert_options_eod

    fx.options_account(session)
    session.commit()

    spec = eod.options_paper_eod_spec()
    assert spec is not None
    ordered = _insert_options_eod(sched.default_job_specs(), spec)
    names = [s.name for s in ordered]
    specs = {s.name: s for s in ordered}

    assert names.index("catch_up") < names.index("options_paper_eod")
    assert names.index("options_paper_eod") < names.index("agents_daily")
    assert names.index("options_paper_eod") < names.index("paper_mtm")
    # 18:30 ET: an hour after the 17:30 equity chain, 15 min after the 18:15
    # universe update, 15 min before the 18:45 agents and 18:50 grid.
    assert (spec.cron_hour, spec.cron_minute, spec.cron_tz) == (18, 30, "America/New_York")
    assert specs["daily_eod_update"].cron_hour == 17
    assert (specs["agents_daily"].cron_hour, specs["agents_daily"].cron_minute) == (18, 45)
    assert (specs["grid_daily"].cron_hour, specs["grid_daily"].cron_minute) == (18, 50)
    # guarded exactly like every other job — unlike the execution cycle, this one
    # has no protective branch to preserve, so the kill switch simply stops it.
    assert spec.self_guarded is False
    assert spec.fn is eod.job_options_paper_eod

    # and the injected list registers cleanly on a real scheduler
    scheduler = sched.build_scheduler(specs=ordered)
    job = {j.id: j for j in scheduler.get_jobs()}["options_paper_eod"]
    assert type(job.trigger).__name__ == "CronTrigger"


def test_last_completed_session_is_the_calendars_answer_not_the_schedulers() -> None:
    """``scheduler.last_completed_session`` does not model exchange holidays and
    says so. The options chain cannot accept that: condition AB asks
    ``options_calendar`` whether the fill session is a real XNYS session, so a
    chain marking against a date the calendar rejects would write a dated
    reconciliation report the guard can never match."""
    from zoneinfo import ZoneInfo

    # 2026-02-16 is Presidents' Day. At 18:30 ET that evening the last COMPLETED
    # session is Friday the 13th, not "today".
    holiday_evening = datetime(2026, 2, 16, 18, 30, tzinfo=ZoneInfo("America/New_York"))
    assert eod.last_completed_session(holiday_evening) == date(2026, 2, 13)
    # ...and on a normal session evening it is that session.
    normal = datetime(2026, 2, 18, 18, 30, tzinfo=ZoneInfo("America/New_York"))
    assert eod.last_completed_session(normal) == fx.FILL_SESSION


def test_the_job_retries_per_unit_and_not_at_the_job_level() -> None:
    """It persists per-unit records; a job-level retry would re-run a mark that
    already wrote its ``options_mark`` rows. The name is a plain string in
    ``scheduler.py`` — ``guarded()`` looks a job's policy up by name, which is
    what lets the policy live there while the body does not."""
    assert eod.OPTIONS_EOD_JOB in sched.NO_JOB_LEVEL_LOCK_RETRY


# --------------------------------------------------------------------------- #
# 3. The order is load-bearing: condition AA
# --------------------------------------------------------------------------- #
def _world(session: Session, *, arm: bool = True, cap: int = 2):  # type: ignore[no-untyped-def]
    """A world in which the second guard would otherwise allow the open."""
    acct = fx.options_account(session)
    inst = fx.underlying(session)
    fx.contracts(session)
    fx.option_prints(session, sessions=[fx.SIGNAL_SESSION, fx.FILL_SESSION])
    ver = fx.approved_strategy(session)
    cand = fx.options_candidate(session, instrument=inst, version=ver)
    fx.approve_scope(session, cand, ver)
    run = session.get(ScanRun, cand.scan_run_id)
    assert run is not None
    run.started_at = SIGNAL_SCAN_STARTED  # the chain finds it by signal session
    if arm:
        set_setting(session, OPTIONS_AUTO_SIM_ENABLED_KEY, True)
        set_setting(session, OPTIONS_AUTO_SIM_CAP_KEY, cap)
    session.flush()
    assert acct.id is not None
    return cand


def test_the_chain_writes_the_dated_reconciliation_that_condition_aa_requires(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    cand = _world(session)
    _enable_chain(session)
    session.commit()

    _pin_sessions(monkeypatch)
    _pin_pricing(monkeypatch)
    eod.job_options_paper_eod()

    session.expire_all()
    report = session.scalar(select(OptionsReconcileReport))
    assert report is not None
    assert report.as_of == fx.FILL_SESSION and report.clean is True
    trade = session.scalar(select(OptionsTrade).where(OptionsTrade.candidate_id == cand.id))
    assert trade is not None and trade.decision is PaperDecision.ACCEPTED
    assert trade.refused_condition == ""


def test_condition_aa_still_refuses_without_a_same_session_reconciliation(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Remove step 2 and the acceptance refuses — by name, on condition AA.

    This is the assertion I-O6's ``test_there_is_no_scheduled_caller_yet``
    existed to protect: an auto-simulation wired in ahead of the reconciliation
    refuses everything. Safe, but not the same as wired correctly.
    """
    cand = _world(session)
    _enable_chain(session)
    session.commit()

    monkeypatch.setattr(
        marks_mod,
        "reconcile_options_collateral",
        lambda s, **kw: marks_mod.ReconcileReport(as_of=kw["as_of"], clean=True),
    )
    _pin_sessions(monkeypatch)
    _pin_pricing(monkeypatch)
    eod.job_options_paper_eod()

    session.expire_all()
    assert session.scalar(select(func.count()).select_from(OptionsReconcileReport)) == 0
    trade = session.scalar(select(OptionsTrade).where(OptionsTrade.candidate_id == cand.id))
    assert trade is not None
    assert trade.decision is PaperDecision.REJECTED
    assert trade.refused_condition == "AA"
    assert "reconciliation" in trade.note
    assert session.scalar(select(func.count()).select_from(OptionsPosition)) == 0


# --------------------------------------------------------------------------- #
# Pricing: refuse rather than guess
# --------------------------------------------------------------------------- #
def test_pricing_with_nothing_in_play_never_passes_a_number_off_as_a_measurement(
    session: Session,
) -> None:
    import math

    ctx = eod._options_eod_pricing(session, underlyings=frozenset(), as_of=fx.FILL_SESSION)
    assert math.isnan(ctx.dividend_yield)
    assert ctx.q_source == "unused:no_underlying_in_play"
    assert ctx.cost_model.spread_pct_of_last_print > 0.0  # never a zero-cost model


def test_pricing_refuses_a_book_spanning_more_than_one_underlying(session: Session) -> None:
    with pytest.raises(eod.OptionsEodUnpriceable, match="cannot honestly price"):
        eod._options_eod_pricing(
            session, underlyings=frozenset({"SPY", "QQQ"}), as_of=fx.FILL_SESSION
        )


def test_pricing_refuses_an_unsourceable_dividend_yield(session: Session) -> None:
    """Decision 11: ``q = 0`` is not a measurement, it is the assumption that
    biases a short-premium result in its own favour."""
    fx.underlying(session)
    session.flush()
    with pytest.raises(eod.OptionsEodUnpriceable, match="no trailing dividend history"):
        eod._options_eod_pricing(
            session, underlyings=frozenset({fx.UNDERLYING}), as_of=fx.FILL_SESSION
        )


def test_pricing_sources_q_from_the_rank_one_dividend_history(session: Session) -> None:
    from signalforge.db.models import DividendEvent

    fx.underlying(session)
    for month, day in ((3, 20), (6, 19), (9, 18), (12, 18)):
        session.add(
            DividendEvent(
                symbol=fx.UNDERLYING,
                ex_dividend_date=date(2025, month, day),
                cash_amount=1.50,
                source="massive_options",
                ingested_at=datetime.now(UTC),
            )
        )
    session.flush()
    ctx = eod._options_eod_pricing(
        session, underlyings=frozenset({fx.UNDERLYING}), as_of=fx.FILL_SESSION
    )
    # four quarterly $1.50 payments against a $450 close
    assert ctx.dividend_yield == pytest.approx(6.0 / fx.SPOT)
    assert ctx.q_source == "vendor_dividends"


def test_the_previous_trading_session_is_the_calendar_s_answer() -> None:
    # 2026-02-16 is Presidents' Day, so the session before Tuesday 2026-02-17
    # is Friday 2026-02-13 — not "yesterday".
    assert eod._previous_trading_session(fx.FILL_SESSION) == fx.SIGNAL_SESSION
    assert eod._previous_trading_session(fx.SIGNAL_SESSION) == date(2026, 2, 13)
