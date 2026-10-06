"""Options marks, expiry processing, and collateral reconciliation (D3 §3.4, §6, §8).

Three jobs, run in this order and no other::

    mark_options_to_market  ->  reconcile_options_collateral  ->  process_option_expiries

Expiry processing runs **last** so it acts on a reconciled book.

None of the three calls ``ensure_not_engaged``. Closing is protective and must
work with the kill switch engaged; only *opening* is blocked, which is the same
asymmetry ``paper.ledger.mark_to_market`` already establishes and the same
asymmetry the reconciler's failure policy uses (a divergence blocks opening and
never blocks closing — a book that cannot be reconciled must still be able to
get flat).

The mark firewall (map §2.4(3), D2 §6.4): a synthetic mark may **trigger** a
signal and may **never set a fill price**. When an exit is signalled on a session
where any leg lacks a print, the structure records ``exit_signalled_at`` and
``exit_deferred_sessions`` increments each session until every leg prints. The
deferral is a cost that is borne, recorded, and reported — never assumed away.

**Pricing is resolved PER UNDERLYING (W5b, decision 11).** These jobs take a
:class:`PricingContextResolver`, not one :class:`OptionsPricingContext`: ``q`` is
a property of a NAME, so one context for a whole call would apply SPY's dividend
yield to every other underlying in the book. The resolver answers per
``(underlying, as_of)`` or refuses that underlying by name
(:class:`UnderlyingNotPriceable`) — it never substitutes another name's ``q`` and
never defaults to ``0.0``. A refusal is scoped to the structures on that name:
everything else is still marked, and the refusal is recorded rather than
absorbed. An unmarked structure then makes the session's reconciliation dirty
(check 11), which is what keeps the second guard's condition AA from offering an
acceptance against a book that could not be valued.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from math import isfinite
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from signalforge.backtest.options_costs import OptionCostModel
from signalforge.data import options_calendar
from signalforge.data.options_corporate_actions import trailing_dividend_yield
from signalforge.db.models import (
    AuditLog,
    Candidate,
    CandidateOptionStructure,
    Instrument,
    OHLCVDaily,
    OptionsCollateralEntry,
    OptionsMark,
    OptionsPosition,
    OptionsReconcileReport,
    OptionsTrade,
    PaperAccount,
    ScanRun,
)
from signalforge.db.types import utcnow
from signalforge.domain import PaperDecision
from signalforge.observability import get_logger
from signalforge.paper.options_ledger import (
    NOTICE,
    OPTIONS_AUTO_SIM_ENABLED_KEY,
    LegQuote,
    OptionExpiryUnhandled,
    OptionsPricingContext,
    PriceSourceUnresolved,
    StructureSpec,
    _money,
    _underlying_close,
    fill_structure,
    leg_quote,
    open_positions,
    options_auto_simulate_enabled,
    options_auto_simulate_max_per_day,
    reevaluate_basis,
    release_collateral,
    resolve_options_account,
    structure_from_position,
    structure_greeks,
)
from signalforge.settings_store import effective_research_config

__all__ = [
    "ExpiryReport",
    "OptionsMarkResult",
    "PricingContextResolver",
    "ReconcileReport",
    "ResolvedPricing",
    "UnderlyingNotPriceable",
    "UnderlyingSources",
    "mark_options_to_market",
    "options_portfolio_snapshot",
    "process_option_expiries",
    "reconcile_options_collateral",
    "resolve_pricing_by_underlying",
    "resolve_underlying_pricing",
    "resolve_underlying_sources",
]

_log = get_logger("paper.options_marks")

_PHASE1_SHARES_PER_CONTRACT = 100

#: ``audit_log.action`` of a mark (or expiry step) REFUSED because the structure's
#: price reads could not name ONE source. The refusal is a row, not a log line:
#: a structure that was not valued must be visible on the record, and reconcile
#: check 11 then turns the missing mark into a finding.
MARK_REFUSED_ACTION = "paper.options_mark_refused"


# --------------------------------------------------------------------------- #
# Per-underlying pricing (W5b, decision 11: "source and record q per underlying")
# --------------------------------------------------------------------------- #


class UnderlyingNotPriceable(RuntimeError):
    """ONE underlying's pricing inputs cannot be SOURCED — named, never guessed.

    Raised instead of returning a context built on a substituted ``q``, on a
    defaulted ``q = 0.0``, or on another name's dividend yield. It names the
    underlying because "the book is unpriceable" is not actionable and "SPY has
    no recorded dividend series at 2026-02-18" is.

    Scope is deliberately ONE name: the caller marks every other structure and
    records this one, rather than abandoning a whole book over one gap.
    """

    def __init__(self, underlying: str, reason: str) -> None:
        self.underlying = underlying
        self.reason = reason
        super().__init__(f"{underlying}: {reason}")


class PricingContextResolver(Protocol):
    """``(underlying, as_of) -> OptionsPricingContext``, or a named refusal.

    Structural on purpose: the EOD chain passes a :class:`ResolvedPricing` frozen
    over one session's survey, and a caller that has its own sourcing may pass
    any callable of this shape. What it may NOT do is hand one context to a
    multi-name book — that is the defect this protocol replaces.
    """

    def __call__(self, underlying: str, as_of: date) -> OptionsPricingContext: ...


def resolve_underlying_pricing(
    session: Session,
    underlying: str,
    as_of: date,
    *,
    cost_model: OptionCostModel,
    risk_free_rate: float,
    underlying_source: str,
    beta_to_spy: float = 1.0,
) -> OptionsPricingContext:
    """Source ONE underlying's pricing context from the recorded series.

    Four inputs, none of them defaulted into existence:

    * ``underlying_source`` — the ONE ``ohlcv_daily.source`` label the close is
      read under, and the label the context then carries so every greek taken
      at this spot can be checked against the structure's recorded source.
      Required: the live database holds the same symbol's bars under two labels,
      so an unfiltered read is a guess. Empty -> refuse, by name.
    * the underlying's **close** for that session, from ``ohlcv_daily`` under
      that source (the reference price the trailing yield is expressed against,
      and the spot every greek is taken at). Absent -> refuse, by name.
    * ``q`` — decision 11 **rank 1** only: the trailing twelve-month declared
      yield from the recorded ``dividend_event`` series for THIS name. Rank 2
      (put-call parity) is not built, and ``q = 0.0`` is forbidden, so an
      unresolvable ``q`` refuses by name rather than borrowing a number.
    * ``risk_free_rate`` — passed in by the caller from the same place the
      backtest engine reads it (``OptionsEvaluationConfig.risk_free_rate``, whose
      ``r_source`` is recorded and hashed into ``options_config_hash``), so the
      paper marks and the evaluations that approved the strategy cannot drift
      apart silently.
    """
    source = str(underlying_source or "").strip()
    if not source:
        raise UnderlyingNotPriceable(
            underlying,
            "no underlying-bar source was named for the close; the spot is never read "
            "unfiltered and the highest id never wins",
        )
    spot = _underlying_close(session, underlying, as_of, source=source)
    if spot is None or spot <= 0.0:
        raise UnderlyingNotPriceable(
            underlying,
            f"no ohlcv_daily close on or before {as_of.isoformat()} under source {source!r}; "
            "a structure cannot be valued against an unknown spot",
        )
    q = trailing_dividend_yield(session, underlying, as_of, reference_close=spot)
    if q is None:
        raise UnderlyingNotPriceable(
            underlying,
            f"no recorded dividend series at {as_of.isoformat()} — decision 11 rank 1 "
            "unresolved and rank 2 (put-call parity) is not built; q = 0.0 is forbidden "
            "because it biases a short-premium result in its own favour",
        )
    return OptionsPricingContext(
        cost_model=cost_model,
        risk_free_rate=risk_free_rate,
        dividend_yield=q.q,
        q_source=q.source,
        underlying_source=source,
        beta_to_spy=beta_to_spy,
    )


@dataclass(frozen=True, slots=True)
class UnderlyingSources:
    """Per underlying, the ONE ``ohlcv_daily.source`` its spot is read under — or why not.

    ``resolved`` maps a name to its label; ``refused`` maps a name to the named
    reason no single label could be established. A name is in exactly one.
    """

    resolved: Mapping[str, str]
    refused: Mapping[str, str]


def resolve_underlying_sources(
    session: Session,
    underlyings: frozenset[str],
    *,
    as_of: date,
    account_name: str,
    signal_session: date,
) -> UnderlyingSources:
    """Which bar source each name's spot is read from. RECORDED, never guessed.

    Two recorded witnesses per name, in this order, and they must agree:

    1. the ``underlying_source`` recorded on every OPEN structure on that name in
       the options account (written at entry from the scan's ``scan_run.source``);
    2. the ``source`` of every ``signal_session`` scan run carrying an options
       candidate on that name (what the auto-simulation step would open from).

    Exactly one label across both -> resolved. Two or more -> refused by name:
    a book that would need two spots for one name is a blend, and no structure
    on it is marked (``paper.options_mark_refused``). An empty recorded label
    refuses the same way.

    When NEITHER witness exists (nothing open and nothing proposed on the name —
    the case a caller hits only when it prices a name outside the EOD plan) the
    stored bars themselves are consulted: if exactly ONE ``ohlcv_daily.source``
    holds a bar for the name in the mark window that label is the answer, since
    there is nothing to choose between; if two or more do, the name is refused —
    which is exactly what the live database does for SPY (``massive`` and
    ``massive_grouped``). A stored-only resolution is never a fallback for a
    recorded one: once anything is open or proposed, only the record counts.
    """
    account_id = session.scalar(select(PaperAccount.id).where(PaperAccount.name == account_name))
    day_start = datetime.combine(signal_session, time.min, tzinfo=UTC)
    resolved: dict[str, str] = {}
    refused: dict[str, str] = {}
    for symbol in sorted(underlyings):
        recorded: set[str] = set()
        blank = False
        if account_id is not None:
            for label in session.scalars(
                select(OptionsPosition.underlying_source).where(
                    OptionsPosition.account_id == account_id,
                    OptionsPosition.underlying_symbol == symbol,
                    OptionsPosition.closed_at.is_(None),
                )
            ):
                if str(label or "").strip():
                    recorded.add(str(label).strip())
                else:
                    blank = True
        for label in session.scalars(
            select(ScanRun.source)
            .join(Candidate, Candidate.scan_run_id == ScanRun.id)
            .join(CandidateOptionStructure, CandidateOptionStructure.candidate_id == Candidate.id)
            .where(
                CandidateOptionStructure.underlying_symbol == symbol,
                ScanRun.started_at >= day_start,
                ScanRun.started_at < day_start + timedelta(days=1),
            )
            .distinct()
        ):
            if str(label or "").strip():
                recorded.add(str(label).strip())
            else:
                blank = True
        if blank:
            refused[symbol] = (
                "an open structure or a candidate scan on this name records NO bar source; "
                "the spot is never read unfiltered"
            )
            continue
        if len(recorded) > 1:
            refused[symbol] = (
                f"open structures / candidate scans on this name record {sorted(recorded)} as "
                "bar sources; one name is never priced off two vendors' closes"
            )
            continue
        if len(recorded) == 1:
            resolved[symbol] = next(iter(recorded))
            continue
        stored = sorted(
            str(s)
            for s in session.scalars(
                select(OHLCVDaily.source)
                .join(Instrument, OHLCVDaily.instrument_id == Instrument.id)
                .where(
                    Instrument.symbol == symbol,
                    OHLCVDaily.session_date >= as_of - timedelta(days=10),
                    OHLCVDaily.session_date <= as_of,
                )
                .distinct()
            )
        )
        if len(stored) == 1:
            resolved[symbol] = stored[0]
        elif not stored:
            refused[symbol] = (
                f"no ohlcv_daily close on or before {as_of.isoformat()} under any source; "
                "nothing recorded names one either"
            )
        else:
            refused[symbol] = (
                f"ohlcv_daily holds bars for this name under {stored} and nothing recorded "
                "names which one; the source is never guessed"
            )
    return UnderlyingSources(resolved=resolved, refused=refused)


@dataclass(frozen=True, slots=True)
class ResolvedPricing:
    """One session's per-underlying resolution, frozen into a resolver.

    The EOD chain resolves inside its read-only survey and then runs four SHORT
    write transactions (docs/SQLITE_CONCURRENCY.md rule 4), so the resolver must
    not hold a ``Session``: it carries the ANSWERS, per name, plus the named
    reason every refused name was refused for.

    ``as_of`` is pinned and checked. ``q`` and the spot it is expressed against
    are point-in-time measurements; silently reusing them for another session
    would be the same class of substitution this type exists to stop, so a
    mismatch is a loud ``ValueError`` rather than a refusal the caller absorbs.
    """

    as_of: date
    contexts: Mapping[str, OptionsPricingContext]
    unpriceable: Mapping[str, str]

    def __call__(self, underlying: str, as_of: date) -> OptionsPricingContext:
        if as_of != self.as_of:
            raise ValueError(
                f"pricing was resolved for {self.as_of.isoformat()} and was asked for "
                f"{as_of.isoformat()}; q and its reference close are point-in-time"
            )
        ctx = self.contexts.get(underlying)
        if ctx is not None:
            return ctx
        raise UnderlyingNotPriceable(
            underlying,
            self.unpriceable.get(underlying, "no pricing context was resolved for this underlying"),
        )

    @property
    def unpriceable_underlyings(self) -> tuple[str, ...]:
        return tuple(sorted(self.unpriceable))


def resolve_pricing_by_underlying(
    session: Session,
    underlyings: frozenset[str],
    as_of: date,
    *,
    cost_model: OptionCostModel,
    risk_free_rate: float,
    sources: UnderlyingSources,
    beta_to_spy: float = 1.0,
) -> ResolvedPricing:
    """Resolve every name INDEPENDENTLY; one refusal never refuses the others.

    A multi-underlying book is priceable — that is the whole point. Each name
    gets its own ``q`` from its own recorded series and its spot from its own
    recorded bar source (``sources``, from :func:`resolve_underlying_sources`),
    and a name that cannot be sourced — no ``q``, no close, or no ONE bar source
    — is carried as a named reason rather than as an exception that would take
    the rest of the book down with it.
    """
    contexts: dict[str, OptionsPricingContext] = {}
    unpriceable: dict[str, str] = {}
    for symbol in sorted(underlyings):
        if symbol in sources.refused:
            unpriceable[symbol] = sources.refused[symbol]
            _log.error(
                "paper.options_pricing_unsourceable",
                underlying=symbol,
                as_of=as_of.isoformat(),
                reason=sources.refused[symbol],
            )
            continue
        try:
            contexts[symbol] = resolve_underlying_pricing(
                session,
                symbol,
                as_of,
                cost_model=cost_model,
                risk_free_rate=risk_free_rate,
                underlying_source=sources.resolved.get(symbol, ""),
                beta_to_spy=beta_to_spy,
            )
        except UnderlyingNotPriceable as exc:
            unpriceable[symbol] = exc.reason
            _log.error(
                "paper.options_pricing_unsourceable",
                underlying=symbol,
                as_of=as_of.isoformat(),
                reason=exc.reason,
            )
    return ResolvedPricing(as_of=as_of, contexts=contexts, unpriceable=unpriceable)


def _q_record(pricing: OptionsPricingContext) -> dict[str, Any]:
    """What was used, on the row: the source AND the number it produced.

    ``dividend_yield`` is written as ``None`` when it is not finite. A NaN would
    serialise as the non-standard JSON token ``NaN``, and a reader that coerced
    it back to a float would have a number where there was a measurement's
    absence.
    """
    q = pricing.dividend_yield
    return {
        "q_source": pricing.q_source,
        "dividend_yield": round(q, 10) if isfinite(q) else None,
        "risk_free_rate": pricing.risk_free_rate,
        "iv_source": pricing.iv_source,
        "greeks_source": pricing.greeks_source,
        "underlying_source": pricing.underlying_source,
    }


@dataclass(slots=True)
class OptionsMarkResult:
    """Deliberately WIDER than ``MarkToMarketResult``.

    The five extra counters — deferrals, synthetic marks, unavailable IVs, the
    unpriced-leg count and the structures whose underlying could not be priced at
    all — are the honesty of the model and must not be summarised away into
    "checked / closed".
    """

    checked: int = 0
    closed: int = 0
    deferred: int = 0
    synthetic_marked: int = 0
    iv_unavailable: int = 0
    unpriceable: int = 0
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    net_delta_notional: float = 0.0
    net_vega_per_vol_pt: float = 0.0
    closed_position_ids: list[int] = field(default_factory=list)
    #: underlyings whose pricing inputs could not be sourced, BY NAME.
    unpriceable_underlyings: list[str] = field(default_factory=list)
    #: structures REFUSED a mark because their price reads could not name ONE
    #: source (``paper.options_mark_refused`` audit rows). Not marked, not closed.
    mark_refused: int = 0
    refused_position_ids: list[int] = field(default_factory=list)


@dataclass(slots=True)
class ExpiryReport:
    checked: int = 0
    force_closed: int = 0
    expired_worthless: int = 0
    assigned: int = 0
    forced_close_no_print: int = 0
    unpriceable: int = 0
    realized_pnl: float = 0.0
    closed_position_ids: list[int] = field(default_factory=list)
    unpriceable_underlyings: list[str] = field(default_factory=list)
    #: as on :class:`OptionsMarkResult`: refused for want of ONE named source.
    mark_refused: int = 0
    refused_position_ids: list[int] = field(default_factory=list)


@dataclass(slots=True)
class ReconcileReport:
    as_of: date
    clean: bool
    findings: list[dict[str, Any]] = field(default_factory=list)
    collateral_reserved_observed: float = 0.0
    collateral_reserved_expected: float = 0.0
    open_structures: int = 0


# --------------------------------------------------------------------------- #
# Marking
# --------------------------------------------------------------------------- #


def _quotes(
    session: Session,
    structure: StructureSpec,
    *,
    as_of: date,
    pricing: OptionsPricingContext,
) -> dict[str, LegQuote]:
    return {
        leg.option_ticker: leg_quote(
            session,
            leg,
            underlying_symbol=structure.underlying_symbol,
            as_of=as_of,
            pricing=pricing,
            option_source=structure.option_source,
            underlying_source=structure.underlying_source,
        )
        for leg in structure.legs
    }


def _assert_price_sources(structure: StructureSpec, pricing: OptionsPricingContext) -> None:
    """Every price read for ``structure`` can name its source, and the spot source
    is the one ``pricing`` was resolved under. Raises :class:`PriceSourceUnresolved`
    BEFORE any row is read; the caller refuses the mark and writes the audit row."""
    if not structure.option_source.strip():
        raise PriceSourceUnresolved(
            f"{structure.underlying_symbol} {structure.structure_type}: the position records no "
            "option-data source, so its legs' prints cannot be read from ONE named source"
        )
    if not structure.underlying_source.strip():
        raise PriceSourceUnresolved(
            f"{structure.underlying_symbol} {structure.structure_type}: the position records no "
            "underlying-bar source, so its spot cannot be read from ONE named source"
        )
    if structure.underlying_source != pricing.underlying_source:
        raise PriceSourceUnresolved(
            f"{structure.underlying_symbol} {structure.structure_type}: the position records "
            f"underlying source {structure.underlying_source!r} but this session's pricing "
            f"context read its spot from {pricing.underlying_source!r}"
        )


def _refuse_mark(
    session: Session,
    position: OptionsPosition,
    structure: StructureSpec,
    *,
    as_of: date,
    actor: str,
    stage: str,
    reason: str,
) -> None:
    """Record that ``position`` was NOT valued on ``as_of`` and why — as a row.

    Nothing else is written: no mark, no close, no release. The structure stays
    open and unmarked, which reconcile check 11 turns into a finding, so the
    second guard's condition AA opens nothing against the book until the
    provenance is repaired by an operator (never by code picking a row).
    """
    session.add(
        AuditLog(
            ts=utcnow(),
            actor=actor,
            action=MARK_REFUSED_ACTION,
            entity=f"options_position:{position.id}",
            before_json={},
            after_json={
                "position_id": position.id,
                "underlying": structure.underlying_symbol,
                "structure_type": structure.structure_type,
                "as_of": as_of.isoformat(),
                "stage": stage,
                "reason": reason,
                "option_source": structure.option_source,
                "underlying_source": structure.underlying_source,
                "simulated": True,
                "notice": NOTICE,
            },
        )
    )
    session.flush()
    _log.error(
        "paper.options_mark_refused",
        position=position.id,
        underlying=structure.underlying_symbol,
        as_of=as_of.isoformat(),
        stage=stage,
        reason=reason,
    )


def _net_premium_at_print(structure: StructureSpec, quotes: dict[str, LegQuote]) -> float | None:
    """The structure's net premium from unadjusted prints — the cost to close it.

    ``None`` when any leg did not print: absence is the answer, never a default.
    """
    total = 0.0
    for leg in structure.legs:
        q = quotes[leg.option_ticker]
        if q.print_close is None:
            return None
        total += leg.qty_signed * q.print_close * leg.shares_per_contract
    return -total * structure.contracts


def _exit_trigger(
    position: OptionsPosition,
    *,
    net_premium: float | None,
    as_of: date,
) -> str | None:
    """Exits struck against the STRUCTURE's net premium, never the underlying.

    The two levels are struck against the credit **actually received** — the
    number a trader who says "stop at 2x the credit" is multiplying — and
    compared against the net premium from unadjusted prints, per the mark
    firewall: a trigger may only ever read prints.
    """
    credit = float(position.entry_net_premium)
    if net_premium is not None and credit > 0:
        if net_premium >= position.stop_multiple_of_credit * credit:
            return "stop"
        if net_premium <= (1.0 - position.profit_target_pct_of_credit) * credit:
            return "target"
    if options_calendar.calendar_dte(as_of, position.expiration_date) <= position.time_stop_dte:
        return "time_stop"
    return None


def _close_position(
    session: Session,
    account: PaperAccount,
    position: OptionsPosition,
    structure: StructureSpec,
    *,
    exit_cash: float,
    exit_costs: float,
    exit_commission_fees: float,
    exit_net_premium: float,
    exit_reason: str,
    as_of: date,
    actor: str,
    pricing: OptionsPricingContext,
    note: str,
    forced_close_no_print: bool = False,
    pin_risk: bool = False,
    assignment_risk: bool = False,
) -> float:
    """Write the close, the immutable trade, THEN release the collateral.

    The ordering is the second line of defence behind the single transaction: a
    crash between the trade write and the release leaves a closed structure with
    its collateral still reserved — conservative, capacity-blocking, and caught by
    reconcile check 5. The opposite ordering is the fail-open one.

    ``pricing`` is the context resolved for THIS structure's underlying, and it is
    recorded in the immutable snapshot (``close.pricing``) whether or not ``q``
    entered the number: on an intrinsic settlement it did not, and a reader can
    see that from ``exit_reason`` — what a reader cannot reconstruct later is
    which ``q``, from which source, the session's greeks and exit trigger were
    computed under.
    """
    entry_comm = float(position.entry_costs) - _entry_spread_cost(position)
    realized = float(position.entry_net_premium) + exit_cash - entry_comm - exit_commission_fees
    r = float(position.r_dollars)
    position.exit_net_premium = _money(exit_net_premium)
    position.exit_costs = _money(exit_costs)
    position.closed_at = utcnow()
    position.exit_reason = exit_reason
    position.dte_at_exit = options_calendar.calendar_dte(as_of, position.expiration_date)
    position.realized_pnl = _money(realized)
    position.pnl_r = realized / r if r > 0 else None
    position.r_clamped = bool(position.pnl_r is not None and position.pnl_r < -1.0)
    position.forced_close_no_print = forced_close_no_print
    position.pin_risk_flag = pin_risk
    position.assignment_risk_flag = assignment_risk

    account.cash = account.cash + _money(exit_cash - exit_commission_fees)

    session.add(
        OptionsTrade(
            account_id=account.id,
            candidate_id=position.candidate_id,
            options_position_id=position.id,
            strategy_version_id=position.strategy_version_id,
            decision=PaperDecision.ACCEPTED,
            structure_type=position.structure_type,
            underlying_symbol=position.underlying_symbol,
            signal_snapshot_json={
                "close": {
                    "as_of": as_of.isoformat(),
                    "exit_reason": exit_reason,
                    "exit_net_premium": round(exit_net_premium, 6),
                    "exit_costs": round(exit_costs, 6),
                    "realized_pnl": round(realized, 6),
                    "pnl_r": position.pnl_r,
                    "r_clamped": position.r_clamped,
                    "r_dollars": r,
                    "forced_close_no_print": forced_close_no_print,
                    "pin_risk_flag": pin_risk,
                    "assignment_risk_flag": assignment_risk,
                    "exit_deferred_sessions": position.exit_deferred_sessions,
                    "collateral_released": float(position.collateral_reserved),
                    # Per UNDERLYING (decision 11), never one context per run.
                    "pricing": _q_record(pricing) | {"underlying": position.underlying_symbol},
                    "legs": [
                        {
                            "option_ticker": leg.option_ticker,
                            "exit_price": (
                                float(leg.exit_price) if leg.exit_price is not None else None
                            ),
                            "intrinsic_floor_applied": leg.exit_intrinsic_floor_applied,
                        }
                        for leg in sorted(position.legs, key=lambda x: x.option_ticker)
                    ],
                },
                "notice": NOTICE,
            },
            plan_json={"structure_type": position.structure_type, "exit_reason": exit_reason},
            r_dollars=position.r_dollars,
            collateral_reserved=position.collateral_reserved,
            actor=actor,
            note=note,
            created_at=utcnow(),
        )
    )
    session.flush()
    # LAST, and after the immutable trade is written. ``collateral_reserved`` is
    # deliberately LEFT on the row: it is the audit of what this structure held,
    # and it is the figure reconcile check 4 compares the release against. Only
    # OPEN structures are summed into the account balance, so keeping it changes
    # no invariant; ``release_collateral`` refuses a second release itself.
    release_collateral(session, account, position, as_of=as_of)
    session.flush()
    _log.info(
        "paper.options_close",
        position=position.id,
        reason=exit_reason,
        pnl=round(realized, 2),
        pnl_r=position.pnl_r,
    )
    return realized


def _entry_spread_cost(position: OptionsPosition) -> float:
    return float(sum(float(leg.entry_spread_cost) for leg in position.legs))


def mark_options_to_market(
    session: Session,
    *,
    account_name: str,
    as_of: date,
    pricing: PricingContextResolver,
    actor: str = "options_mtm",
) -> OptionsMarkResult:
    """Value every open structure and close the ones whose exit is due.

    Per structure, per session:

    0. Resolve the pricing context for **this structure's underlying** (decision
       11). A name whose ``q`` or whose close cannot be sourced is counted,
       named, and LEFT UNMARKED — never marked against another name's dividend
       yield. Every other structure in the book is still marked.
    1. Mark each leg from **its own print** (``OptionAggregateDaily.close``, a
       last-trade print, never a mid).
    2. No print means the mark is incomplete: record ``synthetic`` /
       ``iv_unavailable`` and do **not** extrapolate. Realised volatility is never
       a fallback.
    3. Value the STRUCTURE, never the underlying.
    4. Exits are evaluated against the structure's net premium: profit target as
       a fraction of the credit received, stop as a multiple of it, plus a DTE
       time stop.
    5. A stop or target observed at ``u``'s close fills at ``u+1`` (there is no
       resting stop order anywhere in this design); a time stop is
       calendar-knowable before the session opens and fills at its own session.
       This is byte-identical to the backtest engine's convention.
    6. Greeks are recomputed and stored on every mark, so the caps are evaluated
       against a current book and a breach is visible in the record even though
       the caps only gate *opening*.
    """
    account = resolve_options_account(session, account_name=account_name)
    result = OptionsMarkResult()
    for position in open_positions(session, account):
        result.checked += 1
        structure = structure_from_position(position)
        try:
            ctx = pricing(structure.underlying_symbol, as_of)
        except UnderlyingNotPriceable as exc:
            # NOT marked, NOT closed, NOT guessed. The structure stays open with
            # no mark for this session, which reconcile check 11 turns into a
            # finding — so the second guard's condition AA cannot offer an
            # acceptance against a book with a hole in it.
            result.unpriceable += 1
            if exc.underlying not in result.unpriceable_underlyings:
                result.unpriceable_underlyings.append(exc.underlying)
            _log.error(
                "paper.options_mark_unpriceable",
                position=position.id,
                underlying=exc.underlying,
                as_of=as_of.isoformat(),
                reason=exc.reason,
            )
            continue
        try:
            _assert_price_sources(structure, ctx)
            quotes = _quotes(session, structure, as_of=as_of, pricing=ctx)
        except PriceSourceUnresolved as exc:
            # NOT marked, NOT closed, NOT guessed — and RECORDED as a row.
            _refuse_mark(
                session,
                position,
                structure,
                as_of=as_of,
                actor=actor,
                stage="mark",
                reason=str(exc),
            )
            result.mark_refused += 1
            result.refused_position_ids.append(position.id)
            continue
        priced = [t for t, q in quotes.items() if q.priced]
        net_premium = _net_premium_at_print(structure, quotes)
        greeks = structure_greeks(structure, quotes, beta_to_spy=ctx.beta_to_spy)
        synthetic = len(priced) < len(structure.legs)
        iv_unavailable = not greeks.complete
        if synthetic:
            result.synthetic_marked += 1
        if iv_unavailable:
            result.iv_unavailable += 1
        unrealized = (
            float(position.entry_net_premium) - net_premium if net_premium is not None else 0.0
        )
        result.unrealized_pnl += unrealized
        result.net_delta_notional += greeks.net_delta_notional
        result.net_vega_per_vol_pt += greeks.net_vega_per_vol_pt

        trigger = position.exit_reason
        if position.exit_signalled_at is None:
            trigger = _exit_trigger(position, net_premium=net_premium, as_of=as_of)
            if trigger is not None:
                position.exit_signalled_at = as_of
        else:
            trigger = position.exit_reason or "stop"

        existing = session.scalar(
            select(OptionsMark).where(
                OptionsMark.position_id == position.id, OptionsMark.as_of == as_of
            )
        )
        if existing is None:
            session.add(
                OptionsMark(
                    position_id=position.id,
                    as_of=as_of,
                    net_premium=_money(net_premium if net_premium is not None else 0.0),
                    unrealized_pnl=_money(unrealized),
                    net_delta_shares=greeks.net_delta_shares,
                    net_delta_notional=greeks.net_delta_notional,
                    net_vega_per_vol_pt=greeks.net_vega_per_vol_pt,
                    short_leg_delta=greeks.short_leg_delta,
                    synthetic=synthetic,
                    iv_unavailable=iv_unavailable,
                    legs_priced=len(priced),
                    legs_total=len(structure.legs),
                    iv_source=ctx.iv_source if not iv_unavailable else "",
                    # Decision 11: which q, from which source, for THIS name.
                    # Recorded on every mark — including a synthetic one, whose
                    # greeks are exactly the ones a wrong q would distort.
                    q_source=ctx.q_source[:48],
                    dividend_yield=(ctx.dividend_yield if isfinite(ctx.dividend_yield) else None),
                    exit_reason=trigger,
                )
            )
            session.flush()

        if trigger is None:
            continue
        # A time stop is calendar-knowable and fills on its own session; a stop
        # or target is observed at the close and is actionable only at t+1.
        fills_today = trigger == "time_stop" or (
            position.exit_signalled_at is not None and position.exit_signalled_at < as_of
        )
        if not fills_today:
            position.exit_reason = trigger
            continue
        if synthetic:
            # The fill DEFERS until every leg prints. Never a synthetic fill.
            position.exit_reason = trigger
            position.exit_deferred_sessions += 1
            result.deferred += 1
            continue
        exit_fill = fill_structure(
            structure,
            quotes,
            cost_model=ctx.cost_model,
            as_of=as_of,
            opening=False,
            apply_intrinsic_floor=True,
        )
        _write_exit_legs(session, position, exit_fill, structure)
        realized = _close_position(
            session,
            account,
            position,
            structure,
            exit_cash=exit_fill.cash,
            exit_costs=exit_fill.transaction_costs,
            exit_commission_fees=exit_fill.commission + exit_fill.fees,
            exit_net_premium=exit_fill.net_premium_at_print,
            exit_reason=trigger,
            as_of=as_of,
            actor=actor,
            pricing=ctx,
            note=f"SIMULATED options close ({trigger}). {NOTICE}",
            assignment_risk=_assignment_risk(structure, quotes),
        )
        result.realized_pnl += realized
        result.closed += 1
        result.closed_position_ids.append(position.id)
    return result


def _write_exit_legs(
    session: Session,
    position: OptionsPosition,
    exit_fill: Any,
    structure: StructureSpec,
) -> None:
    sides = structure.contract_sides
    for leg in position.legs:
        f = exit_fill.fills.get(leg.option_ticker)
        if f is None:
            continue
        leg.exit_price = _money(f.price)
        leg.exit_intrinsic_floor_applied = f.intrinsic_floor_applied
        leg.exit_commission = _money(
            (exit_fill.commission + exit_fill.fees)
            * (abs(leg.qty_signed) * structure.contracts)
            / sides
            if sides
            else 0.0
        )
    session.flush()


def _assignment_risk(structure: StructureSpec, quotes: dict[str, LegQuote]) -> bool:
    """A short leg in the money on the close is assignment risk, recorded not modelled."""
    short = structure.short_leg
    if short is None:
        return False
    q = quotes.get(short.option_ticker)
    spot = q.underlying_close if q is not None else None
    if spot is None:
        return False
    return spot < short.strike if short.right_enum.value == "put" else spot > short.strike


# --------------------------------------------------------------------------- #
# Expiry (D3 §8)
# --------------------------------------------------------------------------- #


def process_option_expiries(
    session: Session,
    *,
    account_name: str,
    as_of: date,
    pricing: PricingContextResolver,
    actor: str = "options_expiry",
) -> ExpiryReport:
    """Force-close at ``expiry - 1``; settle anything that reached expiry.

    Phase 1 never holds through expiry. The three outcomes, all named:

    * **force close** — on the ``expiry - 1`` session, priced from that session's
      prints with the intrinsic floor applied to every leg being bought back. If
      any leg lacks a print the structure is closed at the **intrinsic floor with
      no print component**, flagged ``forced_close_no_print``, and reported
      separately. It is NOT excluded from the paper sample: a paper stream that
      drops its inconvenient trades is not a confirming test.
    * **expire worthless** — a structure found at or past its last trade session
      with every leg out of the money settles at zero.
    * **assignment** — a structure found at or past its last trade session with an
      in-the-money short leg settles at intrinsic and is flagged
      ``assignment_risk_flag``. Phase 1 models no exercise/assignment *process*;
      it settles at intrinsic and says so.

    Anything it cannot resolve — no underlying close on the settlement session —
    raises :class:`OptionExpiryUnhandled` rather than guessing a P&L.

    A structure whose UNDERLYING cannot be priced at all (decision 11: no
    sourceable ``q``, or no close) is counted, named and left alone — the same
    treatment ``mark_options_to_market`` gives it, for the same reason, and one
    name's gap never stops the other names from settling. That is a visible,
    recorded deferral, and the session's reconciliation is dirty because of it
    (check 11), so nothing opens on the back of it.

    Idempotent: keyed on ``(position, as_of)`` through ``closed_at``, so a re-run
    on the same session is a no-op. Both catch-up paths re-invoke this.
    """
    account = resolve_options_account(session, account_name=account_name)
    report = ExpiryReport()
    for position in open_positions(session, account):
        report.checked += 1
        structure = structure_from_position(position)
        try:
            ctx = pricing(structure.underlying_symbol, as_of)
        except UnderlyingNotPriceable as exc:
            report.unpriceable += 1
            if exc.underlying not in report.unpriceable_underlyings:
                report.unpriceable_underlyings.append(exc.underlying)
            _log.error(
                "paper.options_expiry_unpriceable",
                position=position.id,
                underlying=exc.underlying,
                as_of=as_of.isoformat(),
                reason=exc.reason,
            )
            continue
        try:
            _assert_price_sources(structure, ctx)
        except PriceSourceUnresolved as exc:
            # Settlement and force-close both read the spot and the prints; with
            # no ONE named source neither is attempted. Recorded, left open.
            _refuse_mark(
                session,
                position,
                structure,
                as_of=as_of,
                actor=actor,
                stage="expiry",
                reason=str(exc),
            )
            report.mark_refused += 1
            report.refused_position_ids.append(position.id)
            continue
        expiry = position.expiration_date
        try:
            last_trade = options_calendar.last_trade_session(expiry)
            force_close = options_calendar.force_close_session(expiry)
        except options_calendar.CalendarUnresolved as exc:
            raise OptionExpiryUnhandled(
                f"position {position.id} expires {expiry}, which this calendar "
                f"cannot resolve: {exc}"
            ) from None

        if as_of >= last_trade:
            report_kind = _settle_at_expiry(
                session, account, position, structure, as_of=as_of, pricing=ctx, actor=actor
            )
            if report_kind == "expired_worthless":
                report.expired_worthless += 1
            else:
                report.assigned += 1
            report.realized_pnl += float(position.realized_pnl)
            report.closed_position_ids.append(position.id)
            continue

        if as_of < force_close:
            continue

        quotes = _quotes(session, structure, as_of=as_of, pricing=ctx)
        if all(q.priced for q in quotes.values()):
            exit_fill = fill_structure(
                structure,
                quotes,
                cost_model=ctx.cost_model,
                as_of=as_of,
                opening=False,
                apply_intrinsic_floor=True,
            )
            _write_exit_legs(session, position, exit_fill, structure)
            realized = _close_position(
                session,
                account,
                position,
                structure,
                exit_cash=exit_fill.cash,
                exit_costs=exit_fill.transaction_costs,
                exit_commission_fees=exit_fill.commission + exit_fill.fees,
                exit_net_premium=exit_fill.net_premium_at_print,
                exit_reason="forced_pre_expiry",
                as_of=as_of,
                actor=actor,
                pricing=ctx,
                note=f"SIMULATED force close at expiry-1. {NOTICE}",
                pin_risk=_pin_risk(session, structure, as_of),
                assignment_risk=_assignment_risk(structure, quotes),
            )
        else:
            spot = _underlying_close(
                session, structure.underlying_symbol, as_of, source=structure.underlying_source
            )
            if spot is None:
                raise OptionExpiryUnhandled(
                    f"position {position.id} must force-close on {as_of} but neither its legs "
                    "nor its underlying printed; Phase 1 does not invent a settlement price"
                )
            cash, premium = _intrinsic_close(structure, spot)
            realized = _close_position(
                session,
                account,
                position,
                structure,
                exit_cash=cash,
                exit_costs=0.0,
                exit_commission_fees=0.0,
                exit_net_premium=premium,
                exit_reason="forced_pre_expiry",
                as_of=as_of,
                actor=actor,
                pricing=ctx,
                note=(
                    "SIMULATED force close at expiry-1 with NO PRINT on at least one leg; "
                    f"closed at the intrinsic floor. {NOTICE}"
                ),
                forced_close_no_print=True,
                pin_risk=_pin_risk(session, structure, as_of),
            )
            report.forced_close_no_print += 1
        report.force_closed += 1
        report.realized_pnl += realized
        report.closed_position_ids.append(position.id)
    return report


def _intrinsic_close(structure: StructureSpec, spot: float) -> tuple[float, float]:
    """``(signed cash to close, net premium)`` valuing every leg at intrinsic."""
    from signalforge.backtest.options_pricing import intrinsic_per_share

    premium = 0.0
    for leg in structure.legs:
        v = intrinsic_per_share(spot, leg.strike, leg.right_enum)
        premium += -leg.qty_signed * v * leg.shares_per_contract
    premium *= structure.contracts
    return -premium, premium


def _settle_at_expiry(
    session: Session,
    account: PaperAccount,
    position: OptionsPosition,
    structure: StructureSpec,
    *,
    as_of: date,
    pricing: OptionsPricingContext,
    actor: str,
) -> str:
    spot = _underlying_close(
        session, structure.underlying_symbol, as_of, source=structure.underlying_source
    )
    if spot is None:
        raise OptionExpiryUnhandled(
            f"position {position.id} reached its expiry {position.expiration_date} with no "
            f"underlying close on the settlement session under source "
            f"{structure.underlying_source!r}; Phase 1 has no assignment path and does not "
            "guess a settlement value"
        )
    cash, premium = _intrinsic_close(structure, spot)
    worthless = abs(premium) < 1e-9
    short = structure.short_leg
    assigned = not worthless and short is not None
    outcome_note = (
        "Every leg expired out of the money."
        if worthless
        else (
            "A short leg finished in the money; Phase 1 settles at intrinsic and "
            "models no exercise process."
        )
    )
    _close_position(
        session,
        account,
        position,
        structure,
        exit_cash=cash,
        exit_costs=0.0,
        exit_commission_fees=0.0,
        exit_net_premium=premium,
        exit_reason="expired_worthless" if worthless else "assigned",
        as_of=as_of,
        actor=actor,
        pricing=pricing,
        note=(
            f"SIMULATED expiry settlement at intrinsic (underlying close {spot}). "
            f"{outcome_note} {NOTICE}"
        ),
        assignment_risk=assigned,
        pin_risk=_pin_risk(session, structure, as_of),
    )
    return "expired_worthless" if worthless else "assigned"


def _has_mark(session: Session, position_id: int, as_of: date) -> bool:
    return (
        session.scalar(
            select(OptionsMark.id)
            .where(OptionsMark.position_id == position_id, OptionsMark.as_of == as_of)
            .limit(1)
        )
        is not None
    )


def _pin_risk(session: Session, structure: StructureSpec, as_of: date) -> bool:
    """The underlying closed inside the pin band around a short strike."""
    short = structure.short_leg
    if short is None:
        return False
    spot = _underlying_close(
        session, structure.underlying_symbol, as_of, source=structure.underlying_source
    )
    if spot is None:
        return False
    band = effective_research_config(session).options_shaping.pin_band_pct * spot
    return abs(spot - short.strike) <= band


# --------------------------------------------------------------------------- #
# Reconciliation (D3 §3.4)
# --------------------------------------------------------------------------- #


def reconcile_options_collateral(
    session: Session,
    *,
    account_name: str,
    as_of: date,
) -> ReconcileReport:
    """Eleven named checks over the book. READ-ONLY except its own row.

    Checks 1-10 are the collateral ledger (D3 §3.4). Check **11** is W5b's
    addition and is about VALUATION rather than collateral: a structure carried
    into this session that has no mark for it could not be valued, and a book
    with an unvalued structure in it is not a reconciled book. It is here rather
    than in the chain because this row is what the second guard's condition AA
    reads — putting the finding anywhere else would leave AA saying "clean" about
    a session in which a structure was never priced.

    A reconciler that silently repairs is a reconciler that hides the bug it
    found, so nothing here mutates a balance or a structure. The row it writes is
    the **positive, dated** precondition the second guard reads (condition AA):
    a missing row refuses exactly as a divergent row refuses.

    Divergence blocks **opening** and never blocks **closing** — the same
    asymmetry as the kill switch.
    """
    account = resolve_options_account(session, account_name=account_name)
    cfg = effective_research_config(session)
    findings: list[dict[str, Any]] = []

    def fail(check: str, detail: str, severity: str = "error") -> None:
        findings.append({"check": check, "detail": detail, "severity": severity})

    entries = list(
        session.scalars(
            select(OptionsCollateralEntry).where(OptionsCollateralEntry.account_id == account.id)
        )
    )
    signed = sum((e.amount if e.event == "reserve" else -e.amount) for e in entries) or Decimal("0")
    observed = account.collateral_reserved
    open_rows = open_positions(session, account)
    expected = sum((p.collateral_reserved for p in open_rows), Decimal("0"))

    # 1 — the account balance equals the signed sum of the ledger.
    if observed != signed:
        fail("1_balance_matches_ledger", f"account {observed} != ledger {signed}")
    # 2 — the account balance equals the sum of open structures' reservations.
    #     (D3 states this as "sum of R"; the recorded per-structure reservation is
    #     the honest comparand — see the module docstring of options_ledger on why
    #     the gross requirement, not R, is what is reserved.)
    if observed != expected:
        fail("2_balance_matches_open_structures", f"account {observed} != open sum {expected}")

    by_position: dict[int, list[OptionsCollateralEntry]] = {}
    for e in entries:
        by_position.setdefault(e.position_id, []).append(e)

    for position in open_rows:
        rows = by_position.get(position.id, [])
        reserves = [e for e in rows if e.event == "reserve"]
        releases = [e for e in rows if e.event == "release"]
        # 3 — every open structure has exactly one unreleased reserve.
        if len(reserves) != 1 or releases:
            fail(
                "3_open_has_one_unreleased_reserve",
                f"position {position.id}: {len(reserves)} reserve(s), {len(releases)} release(s)",
            )
        # 6 — no OPEN structure has a release. The FAIL-OPEN case: collateral
        #     freed while the structure is still open inflates spendable_cash and
        #     re-opens capacity under conditions O / P / R.
        if releases:
            fail(
                "6_open_has_no_release",
                f"position {position.id} is open but its collateral was released",
                severity="critical",
            )
        # 10 — every leg's shares_per_contract is still 100 (a post-entry OCC
        #      adjustment would silently change every x100 downstream).
        for leg in position.legs:
            if leg.shares_per_contract != _PHASE1_SHARES_PER_CONTRACT:
                fail(
                    "10_shares_per_contract_still_100",
                    f"position {position.id} leg {leg.option_ticker} carries "
                    f"shares_per_contract={leg.shares_per_contract}",
                )
        # 11 — every structure CARRIED INTO this session is marked for it (W5b).
        #      A structure opened ON this session is exempt: condition M required
        #      every leg to print on its fill session, so the entry IS its
        #      valuation and there is nothing a mark would add. Anything older
        #      with no mark could not be valued — the per-underlying pricing
        #      resolver refused its name — and an unvalued structure must not be
        #      reported as a reconciled one, because condition AA reads this row.
        opened_this_session = position.fill_session is not None and position.fill_session >= as_of
        if not opened_this_session and not _has_mark(session, position.id, as_of):
            fail(
                "11_open_structure_marked_this_session",
                f"position {position.id} on {position.underlying_symbol} carries no mark for "
                f"{as_of.isoformat()}; it could not be valued this session",
            )

    closed_rows = list(
        session.scalars(
            select(OptionsPosition).where(
                OptionsPosition.account_id == account.id,
                OptionsPosition.closed_at.is_not(None),
            )
        )
    )
    for position in closed_rows:
        rows = by_position.get(position.id, [])
        reserves = [e for e in rows if e.event == "reserve"]
        releases = [e for e in rows if e.event == "release"]
        # 4 — every closed structure has exactly one matching release.
        if len(reserves) != len(releases):
            fail(
                "4_closed_reserve_has_matching_release",
                f"position {position.id}: {len(reserves)} reserve(s) vs {len(releases)} release(s)",
            )
        elif reserves and releases and reserves[0].amount != releases[0].amount:
            fail(
                "4_closed_reserve_has_matching_release",
                f"position {position.id}: reserved {reserves[0].amount}, released "
                f"{releases[0].amount}",
            )
        # 5 — no CLOSED structure has an unreleased reserve. The conservative
        #     crash window: capacity-blocking rather than fail-open.
        if len(reserves) > len(releases):
            fail(
                "5_closed_has_no_unreleased_reserve",
                f"position {position.id} is closed with collateral still reserved",
            )

    # 7 — every basis_json re-evaluates to its own amount.
    for e in entries:
        if e.event != "reserve":
            continue
        try:
            recomputed = reevaluate_basis(e.basis_json)
        except ValueError as exc:
            fail("7_basis_reevaluates", f"entry {e.id}: {exc}")
            continue
        if abs(recomputed - float(e.amount)) > 1e-6:
            fail(
                "7_basis_reevaluates",
                f"entry {e.id}: basis recomputes to {recomputed}, row says {float(e.amount)}",
            )
    # 8 — spendable cash is never negative.
    if account.spendable_cash < 0:
        fail("8_spendable_cash_non_negative", f"spendable cash {account.spendable_cash}")
    # 9 — the collateral cap is respected.
    cap = cfg.options_risk.collateral_cap_dollars
    if float(observed) > cap + 1e-9:
        fail("9_collateral_within_cap", f"reserved {float(observed)} exceeds cap {cap}")
    # 12 — every open structure records the ONE source each of its price reads
    #      takes its rows from. A structure without them cannot be marked (the
    #      mark is refused, not guessed), so a book holding one is not reconciled.
    for p in open_rows:
        missing = [
            name
            for name, value in (
                ("option_source", p.option_source),
                ("underlying_source", p.underlying_source),
            )
            if not str(value or "").strip()
        ]
        if missing:
            fail(
                "12_price_sources_recorded",
                f"position {p.id} ({p.underlying_symbol}) records no {' / '.join(missing)}; "
                "its marks are refused rather than read from an unnamed source",
            )

    report = ReconcileReport(
        as_of=as_of,
        clean=not findings,
        findings=findings,
        collateral_reserved_observed=float(observed),
        collateral_reserved_expected=float(expected),
        open_structures=len(open_rows),
    )
    existing = session.scalar(
        select(OptionsReconcileReport).where(
            OptionsReconcileReport.account_id == account.id,
            OptionsReconcileReport.as_of == as_of,
        )
    )
    if existing is None:
        session.add(
            OptionsReconcileReport(
                account_id=account.id,
                as_of=as_of,
                clean=report.clean,
                findings_json=findings,
                collateral_reserved_observed=observed,
                collateral_reserved_expected=expected,
                open_structures=len(open_rows),
            )
        )
        session.flush()
    if findings:
        _log.error(
            "paper.options_reconcile_divergence",
            account=account.name,
            as_of=as_of.isoformat(),
            findings=[f["check"] for f in findings],
        )
    return report


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #


def options_portfolio_snapshot(
    session: Session,
    *,
    account_name: str,
    as_of: date | None = None,
) -> dict[str, Any]:
    """The options book, reported SIDE BY SIDE with the equity one, never merged.

    The two accounts are separate populations by decision 13 and must read that
    way. The combined net delta is reported as its own block so the operator can
    see the headroom rather than infer it from an absence of refusals.
    """
    on = as_of or date.today()
    cfg = effective_research_config(session)
    limits = cfg.options_risk
    acct = session.scalar(select(PaperAccount).where(PaperAccount.name == account_name))
    if acct is None:
        return {
            "exists": False,
            "account": account_name,
            "configured_account": limits.paper_account_name,
            "hint": (
                f"create it with `signalforge paper init --name {limits.paper_account_name} "
                f"--cash {limits.paper_account_initial_cash:,.0f}`"
            ),
            "notice": NOTICE,
        }

    open_rows = list(
        session.scalars(
            select(OptionsPosition).where(
                OptionsPosition.account_id == acct.id, OptionsPosition.closed_at.is_(None)
            )
        )
    )
    closed_rows = list(
        session.scalars(
            select(OptionsPosition).where(
                OptionsPosition.account_id == acct.id, OptionsPosition.closed_at.is_not(None)
            )
        )
    )
    structures: list[dict[str, Any]] = []
    net_delta = 0.0
    net_vega = 0.0
    unrealized = 0.0
    for position in open_rows:
        mark = session.scalar(
            select(OptionsMark)
            .where(OptionsMark.position_id == position.id)
            .order_by(OptionsMark.as_of.desc(), OptionsMark.id.desc())
            .limit(1)
        )
        if mark is not None:
            net_delta += mark.net_delta_notional
            net_vega += mark.net_vega_per_vol_pt
            unrealized += float(mark.unrealized_pnl)
        structures.append(
            {
                "position_id": position.id,
                "underlying": position.underlying_symbol,
                "structure_type": position.structure_type,
                "contracts": position.contracts,
                "expiration": position.expiration_date.isoformat(),
                "dte": options_calendar.calendar_dte(on, position.expiration_date),
                "entry_net_premium": float(position.entry_net_premium),
                "r_dollars": float(position.r_dollars),
                "collateral_reserved": float(position.collateral_reserved),
                "last_mark": (
                    {
                        "as_of": mark.as_of.isoformat(),
                        "net_premium": float(mark.net_premium),
                        "unrealized_pnl": float(mark.unrealized_pnl),
                        "net_delta_notional": mark.net_delta_notional,
                        "net_vega_per_vol_pt": mark.net_vega_per_vol_pt,
                        "synthetic": mark.synthetic,
                        "iv_unavailable": mark.iv_unavailable,
                        "legs_priced": f"{mark.legs_priced}/{mark.legs_total}",
                        # Which q, from which source, for THIS name (decision 11).
                        "q_source": mark.q_source,
                        "dividend_yield": mark.dividend_yield,
                    }
                    if mark is not None
                    else None
                ),
                "exit_signalled_at": (
                    position.exit_signalled_at.isoformat() if position.exit_signalled_at else None
                ),
                "exit_deferred_sessions": position.exit_deferred_sessions,
            }
        )

    realized = float(sum(float(p.realized_pnl) for p in closed_rows))
    r_series = [p.pnl_r for p in closed_rows if p.pnl_r is not None]
    report = session.scalar(
        select(OptionsReconcileReport)
        .where(OptionsReconcileReport.account_id == acct.id)
        .order_by(OptionsReconcileReport.as_of.desc(), OptionsReconcileReport.id.desc())
        .limit(1)
    )
    equity_delta = _equity_delta_notional(session)
    return {
        "exists": True,
        "account": acct.name,
        "as_of": on.isoformat(),
        "initial_cash": float(acct.initial_cash),
        "cash": round(float(acct.cash), 2),
        "collateral_reserved": round(float(acct.collateral_reserved), 2),
        "spendable_cash": round(float(acct.spendable_cash), 2),
        "n_open": len(open_rows),
        "n_closed": len(closed_rows),
        "open_structures": structures,
        "open_max_loss_total": round(float(sum(float(p.r_dollars) for p in open_rows)), 2),
        "unrealized_pnl": round(unrealized, 2),
        "realized_pnl": round(realized, 2),
        "closed_pnl_r": r_series,
        "expectancy_r": round(sum(r_series) / len(r_series), 4) if r_series else None,
        "greeks": {
            "options_net_delta_notional": round(net_delta, 2),
            "options_net_vega_per_vol_pt": round(net_vega, 4),
            "equity_net_delta_notional": round(equity_delta, 2),
            "combined_net_delta_notional": round(net_delta + equity_delta, 2),
        },
        "limits": {
            "per_structure_max_loss_dollars": limits.per_structure_max_loss_dollars,
            "total_open_max_loss_dollars": limits.total_open_max_loss_dollars,
            "collateral_cap_dollars": limits.collateral_cap_dollars,
            "max_net_delta_notional_dollars": limits.max_net_delta_notional_dollars,
            "combined_max_net_delta_notional_dollars": (
                limits.combined_max_net_delta_notional_dollars
            ),
            "max_net_vega_dollars_per_vol_pt": limits.max_net_vega_dollars_per_vol_pt,
            "max_open_structures": limits.max_open_structures,
            "max_structures_per_underlying": limits.max_structures_per_underlying,
            "daily_order_cap": limits.daily_order_cap,
        },
        "reconciliation": (
            {
                "as_of": report.as_of.isoformat(),
                "clean": report.clean,
                "findings": [f["check"] for f in report.findings_json],
                "open_structures": report.open_structures,
            }
            if report is not None
            else None
        ),
        "auto_simulate": {
            "setting_key": OPTIONS_AUTO_SIM_ENABLED_KEY,
            "enabled": options_auto_simulate_enabled(session),
            "max_per_day": options_auto_simulate_max_per_day(session),
        },
        "disclosures": [
            "The options and equity paper accounts are SEPARATE populations "
            "(decision 13); these figures are never merged with the equity book.",
        ],
        "notice": NOTICE,
    }


def _equity_delta_notional(session: Session) -> float:
    from signalforge.db.models import PaperPosition
    from signalforge.domain import PositionSide

    total = 0.0
    for pos in session.scalars(select(PaperPosition).where(PaperPosition.closed_at.is_(None))):
        d = 1 if pos.side is PositionSide.LONG else -1
        total += d * pos.qty * float(pos.avg_price)
    return total
