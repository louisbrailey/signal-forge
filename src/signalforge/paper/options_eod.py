"""The SIMULATED options paper end-of-day chain, and its scheduler registration.

One job, ``options_paper_eod`` (18:30 America/New_York), that runs in this order
and no other::

    mark_options_to_market -> reconcile_options_collateral
        -> process_option_expiries -> auto_simulate_options_scan_runs

**Why it lives in the paper layer and not in ``signalforge.scheduler``.** This is
the registration rule D6 §2 established for the execution cycle, applied to the
second decision path that needs it. ``signalforge.app`` imports the scheduler
(``app.main`` at import time, ``app.views`` inside ``ops_status_context``), and
contract **S16** forbids the app layer from reaching the options paper decision
path — reporting INDIRECT chains, and seeing imports inside function bodies as
well as at module level. A single ``from signalforge.paper.options_marks import
...`` inside ``scheduler.py`` therefore puts every app view one hop from
``accept_options_candidate``. (It did: the first cut of this chain lived in the
scheduler and broke S16 three ways.)

So the spec is injected from **exactly one place —
``signalforge.cli``** — which passes it to ``build_scheduler(specs=...)``.
``scheduler.default_job_specs()`` stays byte-identical to what it was before this
module existed; only ``NO_JOB_LEVEL_LOCK_RETRY`` names the job, as a plain string
with no import, because ``guarded()`` looks a job's retry policy up by name.

**The operator-visible consequence, stated rather than discovered later:** the
options EOD chain exists only in the CLI-launched worker
(``signalforge run-scheduler``). Started from the app process with
``APP_RUN_SCHEDULER=true`` there is no options job at all — no marks, no
reconciliation, no expiry processing, no options auto-simulation. That is the
same trade the execution cycle already makes, and it is the right way round: the
process that must not be able to reach the door does not carry the key.

Nothing here is armed. The chain is config-gated OFF
(``research.options.paper_eod_enabled``), and the auto-simulation step inside it
needs a THIRD switch of its own (``auto_simulate_options_enabled``, off, cap
0/day). SIMULATED options structures only — no order was placed.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import TYPE_CHECKING

from signalforge.db.retry import DEFAULT_ATTEMPTS, DEFAULT_BACKOFF_S, retry_on_lock
from signalforge.jobspec import JobSpec
from signalforge.observability import get_logger

if TYPE_CHECKING:  # pragma: no cover - typing only, never imported at runtime
    from sqlalchemy.orm import Session

    from signalforge.paper.options_ledger import OptionsPricingContext

_log = get_logger("paper.options_eod")

#: 18:30 America/New_York. The slot, against its cron neighbours in
#: ``scheduler.default_job_specs()``:
#:
#: * AFTER 17:30 (``daily_eod_update``), which chains the equity approved-scope
#:   scan and the live equity auto-simulation inside itself. The options chain
#:   must never straddle that: they share the SQLite writer, and the combined
#:   delta cap the second guard evaluates reads the EQUITY book, which is not
#:   final until the equity auto-simulation has committed. A full hour of margin,
#:   on a job whose long phase is a paced provider ingest.
#: * AFTER 18:15 (``universe_update``) started, and deliberately not before it:
#:   that job is config-gated OFF, and when on it is budgeted and commits per
#:   unit, so the two interleave under the busy timeout rather than starving each
#:   other. 15 minutes is the same gap the 18:45/18:50 pair already accepts.
#: * BEFORE 18:45 (``agents_daily``) and 18:50 (``grid_daily``), so the read-only
#:   agent reports and the grid's own cycle see a book that has been marked,
#:   reconciled and expiry-processed for this session rather than yesterday's.
#: * Inside the 17:30-19:00 ET window IO2_RUNBOOK.md reserves — the nightly
#:   options backfill is forbidden from running in it precisely so the EOD jobs
#:   own the writer here.
OPTIONS_EOD_CRON = (18, 30)
OPTIONS_EOD_TZ = "America/New_York"
OPTIONS_EOD_DESCRIPTION = (
    "SIMULATED options paper EOD chain: mark -> reconcile -> expiry -> "
    "auto-simulate (config-gated OFF; auto-simulation needs its own second setting)"
)

# --------------------------------------------------------------------------- #
OPTIONS_EOD_JOB = "options_paper_eod"


class OptionsEodUnpriceable(RuntimeError):
    """The chain refuses to price rather than guess an input.

    Decision 11 forbids a silent ``q = 0``; D2 §7.4 forbids a zero-cost model.
    When an input for a structure or candidate that is actually in play cannot
    be SOURCED, the job fails loudly and leaves a named ``JobRun`` failure — it
    never marks a book against an assumed number.
    """


@dataclass(frozen=True, slots=True)
class OptionsEodPlan:
    """What one EOD run must price, and what it will offer the second guard."""

    account_name: str
    #: underlyings of OPEN structures (mark + expiry) and of options CANDIDATES
    #: (auto-simulation), unioned: one pricing context serves the whole run, so
    #: every one of them has to resolve or none of them is priced.
    underlyings: frozenset[str]
    #: scan runs of ``signal_session`` that actually carry an options candidate.
    #: EMPTY on the live database today, and that is correct:
    #: ``job_approved_scope_scan`` is equity-only by construction ("Never
    #: options") and no options scan pipeline exists yet. The step is still
    #: invoked with the empty list — a wiring only exercised once candidates
    #: appear is a wiring nobody has tested.
    scan_run_ids: tuple[int, ...]


def _options_account_name(session: Session) -> str:
    from signalforge.settings_store import effective_research_config

    return effective_research_config(session).options_risk.paper_account_name


def _options_eod_plan(session: Session, *, signal_session: date) -> OptionsEodPlan:
    """Read-only survey of what this run has to handle. No write intent."""
    from sqlalchemy import select

    from signalforge.db.models import (
        Candidate,
        CandidateOptionStructure,
        OptionsPosition,
        PaperAccount,
        ScanRun,
    )
    from signalforge.paper.options_ledger import OPTIONS_STRUCTURE_KIND

    account_name = _options_account_name(session)
    open_underlyings = set(
        session.scalars(
            select(OptionsPosition.underlying_symbol)
            .join(PaperAccount, OptionsPosition.account_id == PaperAccount.id)
            .where(PaperAccount.name == account_name, OptionsPosition.closed_at.is_(None))
        )
    )
    day_start = datetime.combine(signal_session, time.min, tzinfo=UTC)
    options_candidates = (
        select(Candidate.id, Candidate.scan_run_id)
        .join(ScanRun, Candidate.scan_run_id == ScanRun.id)
        .where(
            Candidate.structure_kind == OPTIONS_STRUCTURE_KIND,
            ScanRun.started_at >= day_start,
            ScanRun.started_at < day_start + timedelta(days=1),
        )
        .subquery()
    )
    scan_run_ids = sorted(
        {int(v) for v in session.scalars(select(options_candidates.c.scan_run_id))}
    )
    candidate_underlyings = set(
        session.scalars(
            select(CandidateOptionStructure.underlying_symbol).where(
                CandidateOptionStructure.candidate_id.in_(select(options_candidates.c.id))
            )
        )
    )
    return OptionsEodPlan(
        account_name=account_name,
        underlyings=frozenset(open_underlyings | candidate_underlyings),
        scan_run_ids=tuple(scan_run_ids),
    )


def _options_eod_pricing(
    session: Session, *, underlyings: frozenset[str], as_of: date
) -> OptionsPricingContext:
    """Build the run's single pricing context, or refuse.

    Three inputs, none of them defaulted into existence:

    * ``cost_model`` — D5 §2.4's frozen, pre-registered model at BASELINE spread
      (``spread_multiplier = 1.0``). D2 §7.4 forbids a zero-cost model.
    * ``risk_free_rate`` — ``OptionsEvaluationConfig``'s recorded constant, with
      its own ``r_source``; it is hashed into ``options_config_hash``.
    * ``dividend_yield`` — decision 11 rank 1 ONLY (the trailing twelve-month
      declared yield). Rank 2 (put-call parity) is not built; a silent ``q = 0``
      is forbidden, so an unresolvable ``q`` RAISES.

    Phase 1 limitation, enforced rather than assumed: ``mark_options_to_market``,
    ``process_option_expiries`` and ``auto_simulate_options_scan_runs`` each take
    ONE pricing context for the whole call, so one ``q`` would be applied to every
    underlying in play. A book spanning more than one underlying therefore cannot
    be priced honestly here and is REFUSED, loudly, instead of being marked
    against another name's dividend yield. (``q`` reaches the IV inversion and the
    greeks, never a fill price — but a wrong greek is a wrong cap evaluation.)
    """
    from signalforge.config.research import OptionsEvaluationConfig
    from signalforge.data.options_corporate_actions import trailing_dividend_yield
    from signalforge.data.repository import get_daily_bars
    from signalforge.paper.options_ledger import OptionsPricingContext
    from signalforge.research.options_strategies.short_vertical import PREREGISTERED_COST_MODEL

    evaluation = OptionsEvaluationConfig()
    if not underlyings:
        # Nothing is priced on this path: no structure is open and no options
        # candidate exists, so no leg is ever quoted. NaN rather than 0.0 so
        # that a future caller which DID consult it could not mistake it for a
        # measurement — every greek derived from it would be NaN on its face.
        return OptionsPricingContext(
            cost_model=PREREGISTERED_COST_MODEL,
            risk_free_rate=evaluation.risk_free_rate,
            dividend_yield=math.nan,
            q_source="unused:no_underlying_in_play",
        )
    if len(underlyings) > 1:
        raise OptionsEodUnpriceable(
            "one pricing context cannot honestly price "
            f"{sorted(underlyings)} — a single dividend yield would be applied to "
            "every one of them (D3 Phase 1 limitation; decision 11 forbids a "
            "substituted q)"
        )
    symbol = next(iter(underlyings))
    bars = get_daily_bars(session, symbol, as_of - timedelta(days=10), as_of)
    spot = float(bars[-1].close) if bars else 0.0
    if spot <= 0.0:
        raise OptionsEodUnpriceable(f"no underlying close for {symbol} on {as_of.isoformat()}")
    q = trailing_dividend_yield(session, symbol, as_of, reference_close=spot)
    if q is None:
        raise OptionsEodUnpriceable(
            f"no trailing dividend history for {symbol} at {as_of.isoformat()} — decision 11 "
            "rank 1 unresolved and rank 2 (put-call parity) is not built; q = 0 is forbidden"
        )
    return OptionsPricingContext(
        cost_model=PREREGISTERED_COST_MODEL,
        risk_free_rate=evaluation.risk_free_rate,
        dividend_yield=q.q,
        q_source=q.source,
    )


def last_completed_session(now: datetime | None = None) -> date:
    """The latest XNYS session at or before today (ET) — this run's MARK and FILL
    session.

    Deliberately the **calendar's** answer, not ``scheduler.last_completed_
    session``'s. That helper says so itself: it does not model exchange holidays,
    so on a holiday it expects a session that never happened, which it accepts as
    "a conservative, visible error rather than a silent one" for an equity ingest.
    The options chain cannot accept it: the second guard's condition **AB** asks
    ``options_calendar`` whether the fill session is a real XNYS session, and a
    chain that marked and reconciled against a date the calendar rejects would
    write a dated reconciliation report the guard can never match. One module
    answers "which session is this", and it is the same one the guard asks.

    The job fires at 18:30 ET, two and a half hours after the 16:00 close, so
    "at or before today" is a COMPLETED session and never an in-flight one.

    It also does not import ``signalforge.scheduler``: nothing in
    ``signalforge.paper`` may, because the scheduler reaches the briefing and
    agent layers and therefore the LLM layer, which contract S3 forbids the paper
    layer from touching.
    """
    from zoneinfo import ZoneInfo

    from signalforge.data import options_calendar

    today = (now or datetime.now(UTC)).astimezone(ZoneInfo(OPTIONS_EOD_TZ)).date()
    return options_calendar.last_trade_session(today)


def _previous_trading_session(as_of: date) -> date:
    """The XNYS session before ``as_of`` — the SIGNAL session for a fill at
    ``as_of`` (D3 §6.0: signal at t, fill at t+1)."""
    from signalforge.data import options_calendar

    return options_calendar.last_trade_session(as_of - timedelta(days=1))


def job_options_paper_eod() -> None:
    """The SIMULATED options paper end-of-day chain, in this order and no other::

        mark_options_to_market -> reconcile_options_collateral
            -> process_option_expiries -> auto_simulate_options_scan_runs

    **Off by default, and off means byte-identical.** The job returns before it
    opens a single write transaction unless BOTH hold:

    * ``research.options.paper_eod_enabled`` is true (new, default False), and
    * the configured options paper account EXISTS.

    Neither check writes: they run inside one plain reader, so a deployment that
    has not opted in never takes ``BEGIN IMMEDIATE`` and writes no mark, no
    reconciliation report, no collateral entry and no audit row. (It does leave
    the one ``JobRun`` row every guarded job leaves, once a day — the cost of
    being *visible* on the Operational Status page. That is why this job is a
    daily cron and not the 15-minute shape ``_intraday_scan_spec`` refused.)

    The auto-simulation step needs a THIRD switch on top of those two —
    ``auto_simulate_options_enabled``, default OFF with a cap of 0/day — and it
    enforces it itself (``auto_simulate_options_scan_runs`` returns
    ``enabled=False`` before it touches anything). Turning the chain on therefore
    buys marks, reconciliation and expiry handling, all of which are protective
    or read-mostly, and buys **nothing that can open a structure**.

    Ordering is not a convention here, it is a precondition (D3 §6, §8):

    1. **mark** first, so exits signalled at this session's close are acted on
       against this session's prints;
    2. **reconcile** second, so the collateral ledger is checked against a book
       that has already been marked and closed down — and so that the dated,
       clean ``OptionsReconcileReport`` the second guard's condition **AA**
       requires exists for the fill session *before* any acceptance is offered;
    3. **expiry** third, so it acts on a reconciled book (options_marks' own
       module contract);
    4. **auto-simulation** last, and only then, because condition AA refuses
       without step 2's report for exactly this fill session.

    Sessions: ``as_of`` is the last completed session, which is both the MARK
    session and the FILL session; ``signal_session`` is the XNYS session before
    it. A candidate signalled at yesterday's close fills at today's close, on
    today's reconciliation — which is what makes condition AA satisfiable at all.

    SQLite (docs/SQLITE_CONCURRENCY.md): one SHORT ``session_scope(write=True)``
    per unit of the chain, each retried on lock contention per unit, and no write
    lock is held across the survey or the pricing resolution. The job is in
    ``NO_JOB_LEVEL_LOCK_RETRY`` because every unit persists records of its own —
    a job-level retry would re-run a mark that already wrote its ``OptionsMark``
    rows. (Marking and expiry are idempotent per ``(position, as_of)``, the
    reconcile report is unique per ``(account, as_of)``, and auto-simulation
    commits per candidate; the per-unit retry is still the correct granularity.)

    SIMULATED options structures only — no order was placed.
    """
    from sqlalchemy import select

    from signalforge.db.models import PaperAccount
    from signalforge.db.session import session_scope
    from signalforge.settings_store import effective_research_config

    # --- the off path: one plain reader, no write intent, no rows ------------
    with session_scope() as session:
        cfg = effective_research_config(session)
        if not cfg.options.paper_eod_enabled:
            _log.info("options_eod.skipped_disabled", flag="research.options.paper_eod_enabled")
            return
        account_name = cfg.options_risk.paper_account_name
        if session.scalar(select(PaperAccount.id).where(PaperAccount.name == account_name)) is None:
            _log.warning("options_eod.skipped_no_account", account=account_name)
            return

    as_of = last_completed_session()
    signal_session = _previous_trading_session(as_of)

    # --- survey + pricing: still read-only, still no write lock --------------
    with session_scope() as session:
        plan = _options_eod_plan(session, signal_session=signal_session)
        pricing = _options_eod_pricing(session, underlyings=plan.underlyings, as_of=as_of)

    def _unit[T](label: str, fn: Callable[[Session], T]) -> T:
        """One short write transaction, retried per unit (rule 5)."""

        def _run() -> T:
            with session_scope(write=True) as session:
                return fn(session)

        return retry_on_lock(
            _run,
            attempts=DEFAULT_ATTEMPTS,
            backoff_s=DEFAULT_BACKOFF_S,
            label=f"{OPTIONS_EOD_JOB}.{label}",
        )

    from signalforge.paper.options_auto_simulate import auto_simulate_options_scan_runs
    from signalforge.paper.options_marks import (
        mark_options_to_market,
        process_option_expiries,
        reconcile_options_collateral,
    )

    marks = _unit(
        "mark",
        lambda s: mark_options_to_market(
            s, account_name=plan.account_name, as_of=as_of, pricing=pricing
        ),
    )
    _log.info(
        "options_eod.marked",
        checked=marks.checked,
        closed=marks.closed,
        deferred=marks.deferred,
        synthetic=marks.synthetic_marked,
        iv_unavailable=marks.iv_unavailable,
    )

    recon = _unit(
        "reconcile",
        lambda s: reconcile_options_collateral(s, account_name=plan.account_name, as_of=as_of),
    )
    _log.info(
        "options_eod.reconciled",
        as_of=as_of.isoformat(),
        clean=recon.clean,
        findings=[f["check"] for f in recon.findings],
        open_structures=recon.open_structures,
    )

    expiries = _unit(
        "expiry",
        lambda s: process_option_expiries(
            s, account_name=plan.account_name, as_of=as_of, pricing=pricing
        ),
    )
    _log.info(
        "options_eod.expiries",
        checked=expiries.checked,
        force_closed=expiries.force_closed,
        expired_worthless=expiries.expired_worthless,
        assigned=expiries.assigned,
        forced_close_no_print=expiries.forced_close_no_print,
    )

    sim = _unit(
        "auto_simulate",
        lambda s: auto_simulate_options_scan_runs(
            s,
            list(plan.scan_run_ids),
            account_name=plan.account_name,
            pricing=pricing,
            signal_session=signal_session,
            fill_session=as_of,
        ),
    )
    _log.info(
        "options_eod.auto_simulate",
        enabled=sim.enabled,
        considered=sim.considered,
        accepted=len(sim.accepted),
        rejected=len(sim.rejected),
        watched=len(sim.watched),
        skipped=len(sim.skipped),
    )


def options_paper_eod_spec() -> JobSpec | None:
    """The chain's ``JobSpec``, or ``None`` — resolved in ``signalforge.cli``.

    Deliberately NOT the ``execution_job_specs`` / ``_intraday_scan_spec`` shape
    of "return [] when the config flag is off", and the difference is worth
    stating. Those two are high-cadence (30 s, 15 min): always registering them
    would write hundreds of ``JobRun`` rows per session for a deployment that has
    not opted in, which changes what the Operational Status page shows. This job
    is a DAILY cron, so registering it while it is off costs exactly one
    ``JobRun`` row a day — and that row is the point. "The options chain ran at
    18:30 and did nothing, because the flag is off" is an operator-visible fact;
    silence is not.

    It returns ``None`` only when there is no options paper ACCOUNT, because then
    the job has nothing it could ever act on and its daily row would be noise
    about a book that does not exist.

    Best-effort config read, matching both precedents: the scheduler must still
    start if the database is momentarily unavailable, and the safe answer there
    is "not scheduled".
    """
    try:
        from sqlalchemy import select

        from signalforge.db.models import PaperAccount
        from signalforge.db.session import session_scope
        from signalforge.settings_store import effective_research_config

        with session_scope() as session:
            name = effective_research_config(session).options_risk.paper_account_name
            exists = (
                session.scalar(select(PaperAccount.id).where(PaperAccount.name == name)) is not None
            )
    except Exception as exc:  # pragma: no cover - DB unavailable at startup
        _log.warning("options_eod.spec_unavailable", error=repr(exc)[:160])
        return None
    if not exists:
        _log.info("options_eod.not_scheduled_no_account", account=name)
        return None
    return JobSpec(
        OPTIONS_EOD_JOB,
        job_options_paper_eod,
        24 * 60,
        OPTIONS_EOD_DESCRIPTION,
        cron_hour=OPTIONS_EOD_CRON[0],
        cron_minute=OPTIONS_EOD_CRON[1],
        cron_tz=OPTIONS_EOD_TZ,
    )


__all__ = [
    "OPTIONS_EOD_CRON",
    "OPTIONS_EOD_DESCRIPTION",
    "OPTIONS_EOD_JOB",
    "OPTIONS_EOD_TZ",
    "OptionsEodPlan",
    "OptionsEodUnpriceable",
    "job_options_paper_eod",
    "options_paper_eod_spec",
]
