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

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import TYPE_CHECKING

from signalforge.db.retry import DEFAULT_ATTEMPTS, DEFAULT_BACKOFF_S, retry_on_lock
from signalforge.jobspec import JobSpec
from signalforge.observability import get_logger
from signalforge.paper.options_marks import UnderlyingNotPriceable

if TYPE_CHECKING:  # pragma: no cover - typing only, never imported at runtime
    from sqlalchemy.orm import Session

    from signalforge.paper.options_marks import ResolvedPricing

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


#: The chain refuses to price rather than guess an input.
#:
#: Decision 11 forbids a silent ``q = 0``; D2 §7.4 forbids a zero-cost model.
#: When an input cannot be SOURCED the refusal is raised rather than absorbed.
#:
#: W5b turned this from a CHAIN-level failure into a PER-UNDERLYING one, and the
#: name is kept pointing at the class that now carries it
#: (``paper.options_marks.UnderlyingNotPriceable``) so callers catching
#: ``OptionsEodUnpriceable`` still catch exactly the refusal they meant. What
#: changed is the blast radius: one name that cannot be sourced no longer takes
#: the whole run down with it. Its structures are left unmarked and named, the
#: rest of the book is marked, the session's reconciliation is dirty because of
#: the hole (reconcile check 11), and the second guard's condition AA therefore
#: refuses every acceptance on that session — which is the outcome the old
#: whole-run failure was reaching for, without giving up the marks.
OptionsEodUnpriceable = UnderlyingNotPriceable


@dataclass(frozen=True, slots=True)
class OptionsEodPlan:
    """What one EOD run must price, and what it will offer the second guard."""

    account_name: str
    #: underlyings of OPEN structures (mark + expiry) and of options CANDIDATES
    #: (auto-simulation), unioned. Each is resolved INDEPENDENTLY (W5b): a name
    #: that cannot be sourced is refused by name and the others are still priced.
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
) -> ResolvedPricing:
    """Resolve a pricing context PER UNDERLYING, or refuse that name (W5b).

    Three inputs, none of them defaulted into existence:

    * ``cost_model`` — D5 §2.4's frozen, pre-registered model at BASELINE spread
      (``spread_multiplier = 1.0``). D2 §7.4 forbids a zero-cost model. The same
      model for every name, because it is a model of the SPREAD convention and
      not a property of an underlying.
    * ``risk_free_rate`` — ``OptionsEvaluationConfig``'s recorded constant, with
      its own ``r_source``; it is hashed into ``options_config_hash``. The same
      for every name, and the same place the backtest engine reads it, so the
      paper marks and the evaluations that approved the strategy cannot drift.
    * ``dividend_yield`` — decision 11 rank 1 ONLY (the trailing twelve-month
      declared yield), sourced **per underlying** from that name's own recorded
      ``dividend_event`` series. Rank 2 (put-call parity) is not built and a
      silent ``q = 0`` is forbidden, so a name whose ``q`` cannot be sourced is
      refused BY NAME.

    A multi-underlying book is priceable, and that is the W5b change: the
    previous cut applied one context to a whole call, so one ``q`` would have
    reached every name, and it refused the entire run rather than do that.
    Nothing here raises. A refused name is carried in
    :attr:`ResolvedPricing.unpriceable` and refuses only when it is asked for —
    so the rest of the book is marked, the hole is recorded under the name it
    belongs to, and reconcile check 11 turns the unmarked structure into a
    finding that condition AA will not open against. (``q`` reaches the IV
    inversion and the greeks, never a fill price — but a wrong greek is a wrong
    cap evaluation, which is why substituting one is not an option.)
    """
    from signalforge.config.research import OptionsEvaluationConfig
    from signalforge.paper.options_marks import (
        resolve_pricing_by_underlying,
        resolve_underlying_sources,
    )
    from signalforge.research.options_strategies.short_vertical import PREREGISTERED_COST_MODEL

    evaluation = OptionsEvaluationConfig()
    # The spot's bar source, PER NAME, from what is recorded: open structures'
    # ``underlying_source`` and the signal session's candidate scans. Two labels
    # for one name is a blend and refuses that name; nothing recorded falls back
    # to the stored bars only when exactly ONE source holds them.
    sources = resolve_underlying_sources(
        session,
        underlyings,
        as_of=as_of,
        account_name=_options_account_name(session),
        signal_session=_previous_trading_session(as_of),
    )
    # An empty survey resolves to an EMPTY resolver, not to a context carrying a
    # placeholder number. Nothing is open and no options candidate exists, so no
    # leg is ever quoted; if some future caller did ask it for a name it would be
    # refused by name rather than handed a NaN it could mistake for a reading.
    return resolve_pricing_by_underlying(
        session,
        underlyings,
        as_of,
        cost_model=PREREGISTERED_COST_MODEL,
        risk_free_rate=evaluation.risk_free_rate,
        sources=sources,
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

    Pricing is resolved PER UNDERLYING in the survey reader and then used by all
    four steps (W5b, decision 11). A multi-name book is priced; a name whose
    ``q`` or close cannot be sourced is named in the log, its structures are left
    UNMARKED, and the reconciliation for the session is dirty because of them
    (reconcile check 11) — so the auto-simulation step still runs and condition
    AA still refuses every acceptance. The refusal is scoped to the session, not
    to the name: a hole anywhere in the book means the book's collateral and
    capacity cannot be trusted, and opening against it is what must not happen.

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
    if pricing.unpriceable:
        # Named, at error level, BEFORE anything is written. The run continues:
        # every other name is marked, and the hole this leaves behind is what
        # reconcile check 11 refuses to call a clean session.
        _log.error(
            "options_eod.unpriceable_underlyings",
            as_of=as_of.isoformat(),
            underlyings=list(pricing.unpriceable_underlyings),
            reasons=dict(pricing.unpriceable),
        )

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
        unpriceable=marks.unpriceable,
        unpriceable_underlyings=marks.unpriceable_underlyings,
        mark_refused=marks.mark_refused,
        refused_position_ids=marks.refused_position_ids,
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
        unpriceable=expiries.unpriceable,
        unpriceable_underlyings=expiries.unpriceable_underlyings,
        mark_refused=expiries.mark_refused,
        refused_position_ids=expiries.refused_position_ids,
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
