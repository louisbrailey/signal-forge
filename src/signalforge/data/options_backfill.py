"""Bounded historical options-aggregates backfill (education / simulation only).

Fills ``option_aggregate_daily`` with settled daily bars for a *small, bounded*
set of contracts on the approved liquid underlying universe. Never "every
contract": the selection is capped, before any per-contract fetch, on

* number of underlyings         (caller passes the list)
* nearest N expirations         (``caps.expirations_per_underlying``)
* ATM-ranked strike band        (``caps.strike_pct_band``)
* contracts per underlying      (``caps.contracts_per_underlying``)
* total bars across the run     (``caps.max_total_bars`` — a hard storage ceiling)

Whatever a cap forces the run to drop is recorded on the ``IngestionRun``
(``gaps_json`` + ``notes``) and logged — never silently truncated.

Properties, mirroring the equities pipeline:
* **idempotent**   — a contract already covered to the window end is skipped;
  re-inserting an existing ``(option_ticker, session_date, source)`` is a no-op.
* **resumable**    — ``resume_run_id`` re-enters a ``running`` row and skips the
  underlyings already in ``symbols_ok``; per-contract idempotency handles a
  partially-done underlying. An underlying is marked ``symbols_ok`` only if
  every contract it attempted actually succeeded — a transient per-contract
  fetch failure leaves it retryable on the next ``--resume``, never silently
  marked complete. (A cap-trimmed underlying with no fetch errors *is* marked
  done: caps are a deliberate policy choice, not a failure to retry.)
* **labelled**     — every row is ``latency_category = HISTORICAL`` and carries
  the provider name. These are settled bars, never live or delayed.

No recommendations, no alerts, no execution — this only populates a local table
the learning UI and offline validation read.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import date, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from signalforge.data.adapters.base import AdapterError
from signalforge.data.adapters.massive_options import MassiveOptionsAdapter, OptionAggregateRow
from signalforge.data.calendar import sessions as _sessions
from signalforge.data.options_cycles import (
    BASIS_NONE,
    CYCLE_EXPIRY_ADJUSTMENT,
    CYCLE_RULE_MONTHLY_THIRD_FRIDAY,
    EXCL_BAR_BUDGET_EXHAUSTED,
    EXCL_CONTRACT_FETCH_FAILED,
    EXCL_LADDER_INCOMPLETE,
    EXCL_NO_BAR_ON_OR_BEFORE,
    EXCL_NO_CONTRACTS_RETURNED,
    EXCL_NO_INSTRUMENT,
    EXCL_REFERENCE_OUTSIDE_LADDER,
    EXCL_REFERENCE_STALE,
    EXCL_SHARES_PER_CONTRACT_NOT_100,
    EXCL_STRIKE_NOT_LISTED_AS_OF_ENTRY,
    LADDER_17,
    LADDER_ID,
    brackets_reference,
    entry_as_of,
    fetch_span,
    monthly_cycles,
    resolve_strike_listing_basis,
    select_ladder,
)
from signalforge.db.models import IngestionRun, OHLCVDaily, OptionAggregateDaily, OptionContract
from signalforge.db.models.market import Instrument
from signalforge.db.session import set_write_intent
from signalforge.db.types import utcnow
from signalforge.domain import FeedType
from signalforge.killswitch import KillSwitchEngaged
from signalforge.observability import get_logger

_log = get_logger("options.backfill")

# a defensive per-contract ceiling: one option contract can never have more daily
# bars than there are trading days in a couple of years.
_MAX_BARS_PER_CONTRACT = 800


@dataclass(frozen=True, slots=True)
class BackfillCaps:
    lookback_days: int = 365
    expirations_per_underlying: int = 4
    contracts_per_underlying: int = 40
    strike_pct_band: float = 0.15
    max_total_bars: int = 200_000

    @classmethod
    def from_config(cls, opt: object) -> BackfillCaps:
        return cls(
            lookback_days=int(getattr(opt, "backfill_lookback_days", 365)),
            expirations_per_underlying=int(getattr(opt, "backfill_expirations_per_underlying", 4)),
            contracts_per_underlying=int(getattr(opt, "backfill_contracts_per_underlying", 40)),
            strike_pct_band=float(getattr(opt, "backfill_strike_pct_band", 0.15)),
            max_total_bars=int(getattr(opt, "backfill_max_total_bars", 200_000)),
        )


def _reference_price(session: Session, underlying: str) -> float | None:
    """Most recent stored daily close for the underlying — no extra API call."""
    inst = session.scalar(select(Instrument).where(Instrument.symbol == underlying.upper()))
    if inst is None:
        return None
    row = session.execute(
        select(OHLCVDaily.close)
        .where(OHLCVDaily.instrument_id == inst.id)
        .order_by(OHLCVDaily.session_date.desc())
        .limit(1)
    ).first()
    return float(row[0]) if row else None


@dataclass(frozen=True, slots=True)
class ReferencePrice:
    """The band centre for one (underlying, cycle), with its own provenance."""

    price: float
    priced_on: date
    staleness_sessions: int
    source: str


def reference_price(
    session: Session,
    underlying: str,
    as_of_date: date,
    *,
    max_staleness_sessions: int = 3,
    source: str = "massive",
) -> tuple[ReferencePrice | None, str | None]:
    """Point-in-time close for ``underlying`` as at ``as_of_date`` (D1 §2.2).

    Returns ``(price, None)`` or ``(None, reason)`` — **never a fallback value**.
    Every ``None`` is a counted exclusion in the coverage summary.

    Three clauses, each load-bearing:

    * ``session_date <= as_of_date`` is the whole point-in-time guarantee. The
      shipped ``_reference_price`` takes no date at all and returns the most
      recent stored close, which over a three-year window centres 2023 chains on
      a 2026 price and asks the vendor for strikes that were never near the
      money.
    * the source is pinned to ``massive``. The same symbols also carry a bulk
      ``massive_grouped`` overlay; mixing them would make the band depend on
      which bulk sessions happen to be archived, and gate 0.b already requires
      the unblended source — pinning it here makes the band and the gate agree
      by construction.
    * a reference more than ``max_staleness_sessions`` stale is refused, not
      silently used.
    """
    inst = session.scalar(select(Instrument).where(Instrument.symbol == underlying.upper()))
    if inst is None:
        return None, EXCL_NO_INSTRUMENT
    row = session.execute(
        select(OHLCVDaily.close, OHLCVDaily.session_date)
        .where(
            OHLCVDaily.instrument_id == inst.id,
            OHLCVDaily.source == source,
            OHLCVDaily.is_simulated.is_(False),
            OHLCVDaily.session_date <= as_of_date,
        )
        .order_by(OHLCVDaily.session_date.desc())
        .limit(1)
    ).first()
    if row is None:
        return None, EXCL_NO_BAR_ON_OR_BEFORE
    close, priced_on = float(row[0]), row[1]
    staleness = max(0, len(_sessions(priced_on, as_of_date)) - 1)
    if staleness > max_staleness_sessions:
        return None, EXCL_REFERENCE_STALE
    return ReferencePrice(close, priced_on, staleness, source), None


@dataclass(frozen=True, slots=True)
class _Selection:
    carriers: list[OptionContract]
    expirations: list[str]
    expirations_dropped: int  # expirations discarded by expirations_per_underlying
    contracts_dropped: int  # ATM-ranked tail discarded by contracts_per_underlying


def _select_contracts(
    adapter: MassiveOptionsAdapter,
    underlying: str,
    *,
    start: date,
    end: date,
    caps: BackfillCaps,
    ref_price: float | None,
) -> _Selection:
    """Bounded contract set for one underlying + how much the selection caps dropped.

    Contracts whose expiration falls in ``[start, end + 150d]`` (so they had
    tradeable history inside the window), the nearest ``expirations_per_underlying``
    expiries, strikes within ``strike_pct_band`` of ``ref_price`` (if known),
    then ATM-ranked and truncated to ``contracts_per_underlying``. Both cap-driven
    truncations are counted so the caller can record what was dropped.
    """
    lo = start
    hi = end + timedelta(days=150)
    strike_lo = ref_price * (1 - caps.strike_pct_band) if ref_price else None
    strike_hi = ref_price * (1 + caps.strike_pct_band) if ref_price else None
    rows = adapter.fetch_contracts(
        underlying,
        expiration_gte=lo,
        expiration_lte=hi,
        strike_gte=strike_lo,
        strike_lte=strike_hi,
        limit=1000,
    )
    if not rows:
        return _Selection([], [], 0, 0)
    all_exps = sorted({r.expiration_date for r in rows})
    keep_exps = all_exps[: caps.expirations_per_underlying]
    exp_set = set(keep_exps)
    pool = [r for r in rows if r.expiration_date in exp_set]
    if ref_price is not None:
        pool.sort(
            key=lambda r: (abs(r.strike_price - ref_price), r.expiration_date, r.strike_price)
        )
    else:
        pool.sort(key=lambda r: (r.expiration_date, r.strike_price))
    pool_before = len(pool)
    pool = pool[: caps.contracts_per_underlying]
    # hand back lightweight OptionContract-shaped carriers (not persisted here)
    carriers = [
        OptionContract(
            option_ticker=r.option_ticker,
            underlying_symbol=underlying.upper(),
            contract_type=r.contract_type,
            strike_price=r.strike_price,
            expiration_date=r.expiration_date,
            exercise_style=r.exercise_style,
            shares_per_contract=r.shares_per_contract,
            source=adapter.provider_name,
            ingested_at=utcnow(),
        )
        for r in pool
    ]
    return _Selection(
        carriers,
        [d.isoformat() for d in sorted(exp_set)],
        expirations_dropped=len(all_exps) - len(keep_exps),
        contracts_dropped=pool_before - len(pool),
    )


def _existing_dates(session: Session, option_ticker: str, source: str) -> set[date]:
    return {
        d
        for (d,) in session.execute(
            select(OptionAggregateDaily.session_date).where(
                OptionAggregateDaily.option_ticker == option_ticker,
                OptionAggregateDaily.source == source,
            )
        )
    }


def _upsert_contract_meta(session: Session, carrier: OptionContract) -> None:
    exists = session.scalar(
        select(OptionContract.id).where(
            OptionContract.option_ticker == carrier.option_ticker,
            OptionContract.source == carrier.source,
        )
    )
    if exists is None:
        session.add(carrier)
        session.flush()


def backfill_option_aggregates(
    session: Session,
    adapter: MassiveOptionsAdapter,
    underlyings: Sequence[str],
    *,
    start: date,
    end: date,
    caps: BackfillCaps,
    resume_run_id: int | None = None,
) -> IngestionRun:
    """Run (or resume) a bounded historical options-aggregates backfill.

    Returns the ``IngestionRun`` recording requested window, caps, per-underlying
    coverage, cap-driven drops, and failures.
    """
    syms = [u.upper().strip() for u in underlyings if u.strip()]
    # The window is EXPLICIT: whatever the caller asked for. It used to be
    # re-clamped here to ``today() - caps.lookback_days``, which silently capped
    # every run at one year no matter what ``--since`` said and left a source
    # edit as the only way to reach three — not acceptable provenance for a
    # promotion-grade dataset (blocker D1). ``lookback_days`` still supplies the
    # CLI's DEFAULT start, so a run that passes neither ``--since`` nor
    # ``--lookback-days`` fetches exactly what it fetched before.
    win_start = start
    win_end = min(end, date.today())
    expected_per_contract = max(1, len(_sessions(win_start, win_end)))

    if resume_run_id is not None:
        run = session.get(IngestionRun, resume_run_id)
        if run is None:
            raise ValueError(f"ingestion_run {resume_run_id} not found")
    else:
        run = IngestionRun(
            provider=adapter.provider_name,
            feed_type=FeedType.OPTIONS_CHAIN,
            kind="options_agg_backfill",
            requested_start=win_start,
            requested_end=win_end,
            adjusted=True,
            symbols_requested=list(syms),
            status="running",
            started_at=utcnow(),
            notes=(
                f"caps: <={caps.expirations_per_underlying} expiries/underlying, "
                f"<={caps.contracts_per_underlying} contracts/underlying, "
                f"strike +/-{caps.strike_pct_band:.0%}, total bar ceiling "
                f"{caps.max_total_bars:,}; latency=HISTORICAL"
            ),
        )
        session.add(run)
        session.flush()

    ok: list[str] = list(run.symbols_ok or [])
    failed: dict[str, str] = dict(run.symbols_failed or {})
    detail: dict[str, object] = dict(run.gaps_json or {})
    written = int(run.bars_written or 0)
    skipped = int(run.bars_skipped or 0)
    cov_first: date | None = run.coverage_first
    cov_last: date | None = run.coverage_last

    for u in syms:
        if u in ok:
            continue
        # a prior partial/failed pass may have left stale per-contract failure
        # keys for this underlying; drop them so a clean retry clears status,
        # and so this pass's own failures (if any) are what's recorded.
        if failed:
            for k in [k for k in failed if k == u or k.startswith(f"{u}:")]:
                failed.pop(k, None)

        try:
            ref = _reference_price(session, u)
            sel = _select_contracts(
                adapter, u, start=win_start, end=win_end, caps=caps, ref_price=ref
            )
        except AdapterError as exc:
            failed[u] = f"contract selection failed: {exc}"[:200]
            run.symbols_failed = failed
            session.flush()
            continue

        carriers, kept_exps = sel.carriers, sel.expirations
        selection_dropped = sel.contracts_dropped  # already trimmed by expirations/contracts caps
        if selection_dropped:
            _log.warning(
                "options.backfill.selection_cap_hit",
                underlying=u,
                dropped_contracts=selection_dropped,
                dropped_expirations=sel.expirations_dropped,
            )

        if not carriers:
            detail[u] = {
                "contracts": 0,
                "bars": 0,
                "dropped_by_cap": selection_dropped,
                "dropped_expirations": sel.expirations_dropped,
                "bars_clamped": 0,
                "expirations": kept_exps,
            }
            ok.append(u)
            run.symbols_ok = list(ok)
            run.gaps_json = detail
            session.flush()
            continue

        # ---- global total-bar cap: a pre-fetch estimate trims the attempt list
        # (avoids wasted requests); the per-bar check below is the AUTHORITATIVE
        # ceiling — it holds even if a contract returns more bars than estimated.
        budget_left = max(0, caps.max_total_bars - written)
        room_for = budget_left // expected_per_contract if expected_per_contract else 0
        est_dropped = 0
        if len(carriers) > room_for:
            est_dropped = len(carriers) - room_for
            carriers = carriers[:room_for]
            _log.warning(
                "options.backfill.cap_hit",
                underlying=u,
                dropped_contracts=est_dropped,
                total_bar_ceiling=caps.max_total_bars,
                bars_so_far=written,
            )

        u_bars = 0
        u_contracts = 0
        u_contract_failures = 0
        clamped_bars = 0
        processed = 0
        cap_stop = False
        for carrier in carriers:
            if written >= caps.max_total_bars:
                cap_stop = True
                break
            processed += 1
            _upsert_contract_meta(session, carrier)
            hard_end = min(win_end, carrier.expiration_date)
            have = _existing_dates(session, carrier.option_ticker, adapter.provider_name)
            # bound the "already covered" check to in-window dates so a single
            # out-of-range row (a vendor glitch) can never permanently freeze
            # this contract's future coverage.
            covered = {d for d in have if win_start <= d <= hard_end}
            if covered and max(covered) >= hard_end - timedelta(days=4):
                continue  # already covered to the window end for this contract
            fetch_from = max(
                win_start, (max(covered) + timedelta(days=1)) if covered else win_start
            )
            try:
                bars = adapter.fetch_option_aggregates(
                    carrier.option_ticker, start=fetch_from, end=hard_end, adjusted=True
                )
            except AdapterError as exc:
                failed[f"{u}:{carrier.option_ticker}"] = str(exc)[:160]
                u_contract_failures += 1
                continue
            if len(bars) > _MAX_BARS_PER_CONTRACT:  # defensive: a vendor bug can't flood the table
                clamped_bars += len(bars) - _MAX_BARS_PER_CONTRACT
                _log.warning(
                    "options.backfill.contract_bar_clamp",
                    option_ticker=carrier.option_ticker,
                    returned=len(bars),
                    kept=_MAX_BARS_PER_CONTRACT,
                )
                bars = bars[:_MAX_BARS_PER_CONTRACT]
            u_contracts += 1
            for b in bars:
                if written >= caps.max_total_bars:
                    cap_stop = True
                    break
                # reject anything outside [window start, min(window end, expiry)]
                # in one guard — covers post-expiry, pre-window, and future rows.
                if b.session_date > hard_end or b.session_date < win_start:
                    continue
                if b.session_date in have:
                    skipped += 1
                    continue
                session.add(
                    OptionAggregateDaily(
                        option_ticker=b.option_ticker,
                        underlying_symbol=u,
                        session_date=b.session_date,
                        open=b.open,
                        high=b.high,
                        low=b.low,
                        close=b.close,
                        volume=b.volume,
                        vwap=b.vwap,
                        transactions=b.transactions,
                        source=b.source,
                        latency_category=b.latency_category,
                        ingested_at=utcnow(),
                        quality_flags=[],
                    )
                )
                have.add(b.session_date)
                written += 1
                u_bars += 1
                cov_first = b.session_date if cov_first is None else min(cov_first, b.session_date)
                cov_last = b.session_date if cov_last is None else max(cov_last, b.session_date)
            # checkpoint after every contract
            run.bars_written = written
            run.bars_skipped = skipped
            run.coverage_first = cov_first
            run.coverage_last = cov_last
            run.symbols_failed = failed
            session.flush()
            if cap_stop:
                break

        not_attempted = len(carriers) - processed if cap_stop else 0
        total_dropped = selection_dropped + est_dropped + not_attempted
        notes_add = []
        if cap_stop:
            notes_add.append(f"total-bar ceiling ({caps.max_total_bars:,}) hit mid-fetch for {u}")
        if clamped_bars:
            notes_add.append(
                f"per-contract bar clamp dropped {clamped_bars} bar(s) for {u} "
                f"(vendor returned > {_MAX_BARS_PER_CONTRACT}/contract)"
            )
        if notes_add:
            run.notes = (run.notes + "; " if run.notes else "") + "; ".join(notes_add)

        detail[u] = {
            "contracts": u_contracts,
            "bars": u_bars,
            "dropped_by_cap": total_dropped,
            "dropped_expirations": sel.expirations_dropped,
            "bars_clamped": clamped_bars,
            "expirations": kept_exps,
        }
        run.gaps_json = detail
        run.symbols_failed = failed
        # Only mark the underlying done when nothing that a later --resume
        # could actually fix was left undone:
        #  - a per-contract failure (e.g. a transient 5xx) must stay retryable;
        #  - budget-driven trimming (est_dropped / cap_stop) must ALSO stay
        #    retryable — a resume with a higher --max-total-bars is exactly how
        #    an operator recovers that coverage, and marking it done here would
        #    make that recovery permanently impossible (`if u in ok: continue`).
        # A trim from the selection caps (expirations_per_underlying /
        # contracts_per_underlying) is a deterministic policy choice, not a
        # budget shortfall — retrying without changing those caps would just
        # reselect the same contracts, so it's fine to mark done.
        budget_limited = est_dropped > 0 or cap_stop
        if u_contract_failures == 0 and not budget_limited:
            ok.append(u)
            run.symbols_ok = list(ok)
        session.flush()

    run.status = "ok" if not failed else ("partial" if ok else "failed")
    run.finished_at = utcnow()
    session.flush()
    _log.info(
        "options.backfill.done",
        provider=adapter.provider_name,
        underlyings=len(syms),
        bars_written=written,
        bars_skipped=skipped,
        status=run.status,
    )
    return run


# =========================================================================== #
# Per-cycle (monthly) backfill — the shape D1 fixes.
#
# Additive and OFF by default: the legacy nearest-N-expiries path above is
# untouched and every existing caller reaches it unchanged. Nothing here runs
# unless a caller asks for it explicitly.
# =========================================================================== #
_CYCLE_KIND = "options_cycle_backfill"
_RUN_PROVENANCE_KEY = "__run__"
# Exclusions a later --resume could genuinely fix (a transient fetch failure, a
# budget shortfall recoverable by raising the ceiling). Everything else is a
# deterministic property of the data and re-running would only reproduce it.
_RETRYABLE_EXCLUSIONS = frozenset({EXCL_CONTRACT_FETCH_FAILED, EXCL_BAR_BUDGET_EXHAUSTED})
# What decision 6 raised the global bar ceiling FROM. Kept next to the code that
# records it so a run's provenance says not just "2,000,000" but "2,000,000,
# raised from 200,000, by this decision".
_MAX_TOTAL_BARS_PRIOR = 200_000

# Terminal statuses for a pass that ended before the window was complete. Both
# are distinct from ``failed``/``partial`` on purpose: neither is a data
# problem, both are resumable by id, and neither should read as an ingest
# failure to anything that watches run status.
RUN_STATUS_KILLED = "killed"  # the kill switch was engaged mid-run
RUN_STATUS_STOPPED = "stopped"  # a pre-set --max-cycles / --max-minutes bound
_STOP_KEY = "stopped"  # inside the run provenance blob


@dataclass(frozen=True, slots=True)
class RunBounds:
    """Bounds on ONE PASS of a resumable run — never on the dataset.

    A ~29,000-request backfill is ~99 hours at the only pacing this repo knows,
    so it is scheduled in overnight windows that must not overlap the 17:30-19:00
    ET EOD / universe / grid jobs. Neither bound changes what the dataset will
    eventually contain: the pass stops at a **committed (underlying, cycle)
    boundary**, records why, and the next pass resumes from exactly there.

    Both are checked between cycles, never inside one. One (underlying, cycle)
    unit is up to ``2 x len(ladder) + pages`` paced requests — about seven
    minutes at 12.1 s — so a pass may overrun ``max_minutes`` by at most one
    cycle. Size the window with that slack, rather than cutting a cycle in half.
    """

    max_cycles: int | None = None
    max_minutes: float | None = None

    def deadline(self, started_monotonic: float) -> float | None:
        if self.max_minutes is None:
            return None
        return started_monotonic + self.max_minutes * 60.0

    def reached(self, *, units_done: int, now: float, deadline: float | None) -> str | None:
        """The bound that has been reached, as a recordable string, or None."""
        if self.max_cycles is not None and units_done >= self.max_cycles:
            return f"max_cycles={self.max_cycles}"
        if deadline is not None and now >= deadline:
            return f"max_minutes={self.max_minutes:g}"
        return None


class _Phases:
    """Write-lock discipline for a long, paced run (D1 §7.7 fix 1, blocker D16).

    The shipped path ran the whole backfill inside one ``session_scope(write=True)``
    — on SQLite a ``BEGIN IMMEDIATE`` held for the lifetime of the scope. At
    ~99 hours that is a four-day write lock against the file the paper probation
    worker is writing to, and ``session_scope`` rolls back on any exception, so
    a kill switch engaged on day three discarded every bar **and** the
    ``IngestionRun`` row that a ``--resume`` needs.

    This class makes the three phases explicit and non-overlapping:

    * :meth:`read` — plain ``BEGIN``; never blocks the worker.
    * network — **no transaction at all**; every paced request happens here.
    * :meth:`write` — ``BEGIN IMMEDIATE``, one short burst, then :meth:`commit`.

    :meth:`write` is idempotent so a cycle's bars and that cycle's provenance
    checkpoint land in ONE transaction: a committed cycle is always a cycle
    whose coverage record was committed with it.
    """

    def __init__(self, session: Session) -> None:
        self._session = session
        self._mode = ""

    def read(self) -> None:
        self.commit()
        set_write_intent(self._session, False)
        self._mode = "read"

    def write(self) -> None:
        if self._mode == "write":
            return  # already inside the write phase; do NOT split the transaction
        self.commit()
        set_write_intent(self._session, True)
        self._mode = "write"

    def commit(self) -> None:
        if self._session.in_transaction():
            self._session.commit()

    def abandon(self) -> None:
        """Discard an interrupted cycle's uncommitted work, keeping every
        committed one. Called at the loop boundary, never inside a cycle."""
        if self._session.in_transaction():
            self._session.rollback()


@dataclass(frozen=True, slots=True)
class CycleBackfillCaps:
    """Per-(underlying, cycle) caps. The ladder decides coverage, not a cap."""

    window_start: date
    window_end: date
    cycle_rule: str = CYCLE_RULE_MONTHLY_THIRD_FRIDAY
    dte_entry_min: int = 21
    dte_entry_max: int = 60
    strike_band_pct: float = 0.15
    ladder: tuple[float, ...] = LADDER_17
    min_rungs_per_side: int = 7
    pre_entry_buffer_sessions: int = 5
    rights: tuple[str, ...] = ("call", "put")
    # A RUNAWAY GUARD, never the selector: the ladder is bounded at
    # ``2 x len(ladder)`` contracts per cycle by construction, so tripping this
    # means the ladder was reconfigured beyond the guard. That fails the run
    # loudly rather than truncating a cycle to an arbitrary slice — silent
    # under-coverage is the failure mode this whole module exists to remove.
    max_contracts_per_cycle: int = 40
    max_total_bars: int = 2_000_000
    reference_max_staleness_sessions: int = 3
    ladder_bracket_min_rungs: int = 3
    listing_include_expired: bool = True
    listing_as_of_enabled: bool = True

    @classmethod
    def from_config(cls, opt: object, *, window_start: date, window_end: date) -> CycleBackfillCaps:
        return cls(
            window_start=window_start,
            window_end=window_end,
            cycle_rule=str(getattr(opt, "cycle_rule", CYCLE_RULE_MONTHLY_THIRD_FRIDAY)),
            dte_entry_min=int(getattr(opt, "dte_entry_min", 21)),
            dte_entry_max=int(getattr(opt, "dte_entry_max", 60)),
            strike_band_pct=float(getattr(opt, "backfill_strike_pct_band", 0.15)),
            min_rungs_per_side=int(getattr(opt, "min_rungs_per_side", 7)),
            pre_entry_buffer_sessions=int(getattr(opt, "pre_entry_buffer_sessions", 5)),
            max_contracts_per_cycle=int(getattr(opt, "max_contracts_per_cycle", 40)),
            max_total_bars=int(getattr(opt, "backfill_max_total_bars", 2_000_000)),
            reference_max_staleness_sessions=int(
                getattr(opt, "reference_max_staleness_sessions", 3)
            ),
            ladder_bracket_min_rungs=int(getattr(opt, "ladder_bracket_min_rungs", 3)),
            listing_include_expired=bool(getattr(opt, "listing_include_expired", True)),
            listing_as_of_enabled=bool(getattr(opt, "listing_as_of_enabled", True)),
        )


@dataclass(frozen=True, slots=True)
class OptionsCoverageSummary:
    """COUNTS AND COMPLETENESS ONLY — the one thing a backfill may expose
    before the strategy pre-registration is committed.

    Every field is a count, a fraction, a date or an identity. There is no field
    that can hold a price, an IV, a greek, a return, a credit or a P&L, and none
    that can hold a volume — **by construction**, so no script can print one by
    accident and no reviewer has to trust that one didn't. ``assert_price_free``
    is the mechanical statement of that property.

    Note a deliberate tightening against D1 §10.2, which permits the per-cycle
    reference price here: it is an equity close and would be permissible, but
    keeping it out is what lets "no field can hold a price" be checked by a
    machine rather than argued. It stays fully auditable on the run's
    ``gaps_json``.
    """

    provider: str
    run_id: int | None
    window_start: date
    window_end: date
    cycle_rule: str
    ladder_id: str
    strike_listing_basis: str
    underlyings: tuple[str, ...]
    cycles_total: int
    cycles_covered: int
    cycles_excluded: int
    exclusions_by_reason: tuple[tuple[str, int], ...]
    contracts_selected: int
    contracts_fetched: int
    bars_written: int
    bars_skipped: int
    sessions_expected: int
    shares_per_contract_refusals: int
    ladder_incomplete_cycles: int
    underlyings_ok: tuple[str, ...]
    underlyings_failed: tuple[str, ...]
    earliest_available_date: date | None
    max_total_bars: int
    max_total_bars_prior: int
    pacing_s: float
    status: str
    # Why the last pass ended early, if it did: a kill switch, or a pre-set
    # ``--max-cycles`` / ``--max-minutes`` window bound. An identity string, so
    # an operator reading a nightly summary can tell "the window closed" from
    # "the data ran out" without opening the run row.
    stopped_reason: str = ""

    # Any field name containing one of these could carry an outcome. The check
    # is on NAMES, so it fires when a field is added, not when one is populated.
    _FORBIDDEN_TOKENS = (
        "price",
        "open",
        "high",
        "low",
        "close",
        "vwap",
        "iv",
        "greek",
        "delta",
        "vega",
        "theta",
        "gamma",
        "return",
        "pnl",
        "credit",
        "premium",
        "volume",
        "transactions",
        "quote",
    )

    @property
    def bar_continuity_fraction(self) -> float:
        """Bars actually written as a fraction of the sessions the cycles span."""
        return (self.bars_written / self.sessions_expected) if self.sessions_expected else 0.0

    @property
    def cycles_bracket_fraction(self) -> float:
        return (self.cycles_covered / self.cycles_total) if self.cycles_total else 0.0

    @classmethod
    def assert_price_free(cls) -> None:
        """Raise if any field name could hold an outcome. Called at import of
        the report path and asserted directly by the test suite."""
        import dataclasses as _dc

        bad = []
        for f in _dc.fields(cls):
            name = f.name.lower()
            for tok in cls._FORBIDDEN_TOKENS:
                # "earliest_available_date" etc. are dates; the tokens above are
                # substrings of outcome-bearing names only.
                if tok in name:
                    bad.append((f.name, tok))
        if bad:
            raise AssertionError(
                "OptionsCoverageSummary must stay counts-and-completeness only; "
                f"outcome-bearing field name(s): {bad}"
            )


def coverage_summary(
    run: IngestionRun, *, underlyings: Sequence[str] | None = None
) -> OptionsCoverageSummary:
    """Derive the coverage summary from a cycle run's own provenance.

    Reads ``IngestionRun`` only. It never touches ``option_aggregate_daily``,
    so it cannot see a price even if someone later asks it to.

    ``underlyings`` restricts the summary to that subset of the run — the form
    a dataset snapshot's coverage pre-flight needs, because a snapshot may hold
    fewer underlyings than the run that fetched them (IO2 runbook §6: dropping
    an underlying is one of the two permitted responses to a shortfall). Every
    count is then taken from the per-cycle records of those underlyings alone,
    **including** ``bars_written``: the run-level counter cannot be apportioned,
    so the restricted form sums each cycle's own ``bars_written``. That sum is
    never larger than the true count — a cycle re-attempted after a retryable
    failure records only the bars its last attempt added — so the restricted
    continuity fraction errs low, the conservative direction for a floor.
    ``bars_skipped`` is not recorded per cycle and is reported as 0 there.
    """
    detail = dict(run.gaps_json or {})
    prov = dict(detail.pop(_RUN_PROVENANCE_KEY, {}) or {})
    wanted: frozenset[str] | None = None
    if underlyings is not None:
        wanted = frozenset(u.upper().strip() for u in underlyings if u.strip())
        detail = {k: v for k, v in detail.items() if str(k).upper() in wanted}
    bars_from_cycles = 0
    cycles_total = cycles_covered = cycles_excluded = 0
    contracts_selected = contracts_fetched = 0
    sessions_expected = refusals = ladder_incomplete = 0
    reasons: dict[str, int] = {}
    for payload in detail.values():
        if not isinstance(payload, dict):
            continue
        for cyc in (payload.get("cycles") or {}).values():
            cycles_total += 1
            reason = cyc.get("excluded")
            if reason:
                cycles_excluded += 1
                reasons[reason] = reasons.get(reason, 0) + 1
                if reason == EXCL_LADDER_INCOMPLETE:
                    ladder_incomplete += 1
            else:
                cycles_covered += 1
            contracts_selected += int(cyc.get("selected_calls", 0)) + int(
                cyc.get("selected_puts", 0)
            )
            contracts_fetched += int(cyc.get("contracts_fetched", 0))
            sessions_expected += int(cyc.get("sessions_expected", 0)) * int(
                cyc.get("contracts_fetched", 0)
            )
            refusals += int(cyc.get("shares_per_contract_refusals", 0))
            bars_from_cycles += int(cyc.get("bars_written", 0))

    def _keep(names: Sequence[str]) -> tuple[str, ...]:
        return tuple(n for n in names if wanted is None or str(n).upper() in wanted)

    return OptionsCoverageSummary(
        provider=run.provider,
        run_id=run.id,
        window_start=run.requested_start,
        window_end=run.requested_end,
        cycle_rule=str(prov.get("cycle_rule", "")),
        ladder_id=str(prov.get("ladder_id", "")),
        strike_listing_basis=str(prov.get("strike_listing_basis", "")),
        underlyings=_keep(run.symbols_requested or []),
        cycles_total=cycles_total,
        cycles_covered=cycles_covered,
        cycles_excluded=cycles_excluded,
        exclusions_by_reason=tuple(sorted(reasons.items())),
        contracts_selected=contracts_selected,
        contracts_fetched=contracts_fetched,
        bars_written=int(run.bars_written or 0) if wanted is None else bars_from_cycles,
        bars_skipped=int(run.bars_skipped or 0) if wanted is None else 0,
        sessions_expected=sessions_expected,
        shares_per_contract_refusals=refusals,
        ladder_incomplete_cycles=ladder_incomplete,
        underlyings_ok=_keep(run.symbols_ok or []),
        underlyings_failed=_keep(sorted(run.symbols_failed or {})),
        earliest_available_date=run.earliest_available_date,
        max_total_bars=int(prov.get("max_total_bars", 0)),
        max_total_bars_prior=int(prov.get("max_total_bars_prior", 0)),
        pacing_s=float(prov.get("pacing_s", 0.0)),
        status=run.status,
        stopped_reason=str((prov.get(_STOP_KEY) or {}).get("reason", "")),
    )


@dataclass(frozen=True, slots=True)
class _CycleSelection:
    """One cycle's resolved contract set, or the reason it was excluded."""

    carriers: tuple[OptionContract, ...] = ()
    excluded: str | None = None
    ladder_rungs_seen: int = 0
    ladder_min_strike: float | None = None
    ladder_max_strike: float | None = None
    selected_calls: int = 0
    selected_puts: int = 0
    rungs_per_side: tuple[int, int] = (0, 0)
    pages_walked: int = 0
    next_url_exhausted: bool = False
    rows_unparseable: int = 0
    refusals: int = 0


def _select_cycle(
    adapter: MassiveOptionsAdapter,
    underlying: str,
    *,
    expiry: date,
    entry: date,
    ref: float,
    caps: CycleBackfillCaps,
    strike_listing_basis: str,
) -> _CycleSelection:
    """Resolve one (underlying, cycle) against its own point-in-time ladder."""
    if strike_listing_basis == BASIS_NONE:
        # An end-of-life ladder preferentially offers well-placed short strikes
        # in the direction the underlying already moved. That is favourable
        # selection on realised outcomes — a lookahead in the selection rule
        # itself. Without a point-in-time instrument the ladder may not be used
        # for selection at all.
        return _CycleSelection(excluded=EXCL_STRIKE_NOT_LISTED_AS_OF_ENTRY)
    try:
        page = adapter.fetch_contracts_page(
            underlying,
            expiration_gte=expiry,
            expiration_lte=expiry,
            limit=1000,  # the parameter DEFAULTS to 250; a deep chain needs 4x the pages at that
            # Vendor semantics measured 2026-09-12 (D1 Appendix P, probe P6): ``as_of``
            # pins the listing to the contracts LIVE on that date, so ``expired`` is
            # judged relative to ``as_of`` — ``expired=true&as_of=<entry>`` asks for
            # contracts already expired at entry and returns ZERO rows for every
            # cycle (Stage A pass 1 excluded all 102 units this way). ``as_of`` alone
            # returned the 490-contract point-in-time ladder of an expired series.
            # ``expired=true`` is therefore sent only for an end-of-life listing.
            expired=(
                (caps.listing_include_expired or None) if not caps.listing_as_of_enabled else None
            ),
            as_of=entry if caps.listing_as_of_enabled else None,
        )
    except AdapterError:
        return _CycleSelection(excluded=EXCL_CONTRACT_FETCH_FAILED)

    base = _CycleSelection(
        pages_walked=page.pages_walked,
        next_url_exhausted=page.next_url_exhausted,
        rows_unparseable=page.rows_unparseable,
        ladder_rungs_seen=len({r.strike_price for r in page.rows}),
        ladder_min_strike=min((r.strike_price for r in page.rows), default=None),
        ladder_max_strike=max((r.strike_price for r in page.rows), default=None),
    )
    if not page.rows:
        return replace(base, excluded=EXCL_NO_CONTRACTS_RETURNED)
    if not page.is_complete:
        # A truncated or row-dropped ladder is indistinguishable from a complete
        # one, and the bracket check below is computed from exactly that set.
        return replace(base, excluded=EXCL_LADDER_INCOMPLETE)
    if not brackets_reference(
        (r.strike_price for r in page.rows), ref, min_rungs=caps.ladder_bracket_min_rungs
    ):
        return replace(base, excluded=EXCL_REFERENCE_OUTSIDE_LADDER)

    carriers: list[OptionContract] = []
    counts = {"call": 0, "put": 0}
    rungs = (0, 0)
    refusals = 0
    for right in caps.rights:
        side_rows = [r for r in page.rows if r.contract_type == right]
        sel = select_ladder(
            [r.strike_price for r in side_rows],
            ref,
            strike_band_pct=caps.strike_band_pct,
            min_rungs_per_side=caps.min_rungs_per_side,
            ladder=caps.ladder,
        )
        if not sel.ok:
            return replace(base, excluded=sel.excluded)
        rungs = (max(rungs[0], sel.rungs_below), max(rungs[1], sel.rungs_above))
        wanted = set(sel.strikes)
        seen: set[float] = set()
        for r in side_rows:
            if r.strike_price not in wanted or r.strike_price in seen:
                continue
            if r.shares_per_contract != 100:
                # Gate 0.h, mechanically. A non-100 deliverable is the
                # machine-readable signature of an OCC adjustment; every "x 100"
                # downstream is then wrong, on exactly the contracts a split
                # exclusion is meant to remove.
                refusals += 1
                continue
            seen.add(r.strike_price)
            counts[right] = counts.get(right, 0) + 1
            carriers.append(
                OptionContract(
                    option_ticker=r.option_ticker,
                    underlying_symbol=underlying.upper(),
                    contract_type=r.contract_type,
                    strike_price=r.strike_price,
                    expiration_date=r.expiration_date,
                    exercise_style=r.exercise_style,
                    shares_per_contract=r.shares_per_contract,
                    source=adapter.provider_name,
                    ingested_at=utcnow(),
                )
            )
    if refusals and not carriers:
        return replace(base, excluded=EXCL_SHARES_PER_CONTRACT_NOT_100, refusals=refusals)
    if len(carriers) > caps.max_contracts_per_cycle:
        # Loud, not truncating: the guard exists to catch a misconfigured
        # ladder, and silently keeping an arbitrary slice is precisely the
        # behaviour this module replaces.
        raise ValueError(
            f"ladder for {underlying} {expiry.isoformat()} resolved to {len(carriers)} contracts, "
            f"above max_contracts_per_cycle={caps.max_contracts_per_cycle}. The ladder decides "
            "coverage, never the cap — raise the guard deliberately or pre-register a coarser "
            "rung set; do not truncate the cycle."
        )
    return replace(
        base,
        carriers=tuple(carriers),
        selected_calls=counts["call"],
        selected_puts=counts["put"],
        rungs_per_side=rungs,
        refusals=refusals,
    )


def _cycle_provenance(
    adapter: MassiveOptionsAdapter,
    caps: CycleBackfillCaps,
    *,
    strike_listing_basis: str,
    options_config_hash: str,
) -> dict[str, object]:
    """The run's own parameters, structurally — not as prose in ``notes``.

    A free-text note cannot be compared between runs, and a dataset built under
    a different ceiling, pacing, ladder or listing basis must be
    distinguishable from one built under another.
    """
    return {
        "window_start": caps.window_start.isoformat(),
        "window_end": caps.window_end.isoformat(),
        "cycle_rule": caps.cycle_rule,
        "cycle_expiry_adjustment": CYCLE_EXPIRY_ADJUSTMENT,
        "dte_entry_min": caps.dte_entry_min,
        "dte_entry_max": caps.dte_entry_max,
        "strike_band_pct": caps.strike_band_pct,
        "ladder_id": LADDER_ID,
        "ladder_offsets": list(caps.ladder),
        "min_rungs_per_side": caps.min_rungs_per_side,
        "pre_entry_buffer_sessions": caps.pre_entry_buffer_sessions,
        "rights": list(caps.rights),
        "max_contracts_per_cycle": caps.max_contracts_per_cycle,
        "reference_source": "massive",
        "reference_max_staleness_sessions": caps.reference_max_staleness_sessions,
        "ladder_bracket_min_rungs": caps.ladder_bracket_min_rungs,
        "listing_include_expired": caps.listing_include_expired,
        "listing_as_of_enabled": caps.listing_as_of_enabled,
        "strike_listing_basis": strike_listing_basis,
        "require_shares_per_contract": 100,
        # Decision 6, recorded WITH the run as decision 6 itself requires: the
        # ceiling that applied, and the value it was raised from.
        "max_total_bars": caps.max_total_bars,
        "max_total_bars_prior": _MAX_TOTAL_BARS_PRIOR,
        "max_total_bars_raise_decision": (
            "decision 6, docs/research/DECISIONS_2026-09-12_options_execution.md"
        ),
        "pacing_s": adapter.min_request_spacing_s,
        "provider": adapter.provider_name,
        "options_config_hash": options_config_hash,
    }


def _existing_dates_many(
    session: Session, tickers: Sequence[str], source: str
) -> dict[str, set[date]]:
    """One query for a whole cycle's stored sessions, instead of one per contract.

    The per-contract query is what the shipped path did between paced fetches,
    which is exactly the read-then-fetch-then-write interleaving the write-lock
    discipline forbids. Reading the cycle's coverage up front lets the whole
    network phase run with no transaction open at all.
    """
    if not tickers:
        return {}
    out: dict[str, set[date]] = {t: set() for t in tickers}
    for tk, d in session.execute(
        select(OptionAggregateDaily.option_ticker, OptionAggregateDaily.session_date).where(
            OptionAggregateDaily.option_ticker.in_(list(tickers)),
            OptionAggregateDaily.source == source,
        )
    ):
        out.setdefault(tk, set()).add(d)
    return out


@dataclass(frozen=True, slots=True)
class _CycleBars:
    written: int = 0
    skipped: int = 0
    fetched: int = 0
    first: date | None = None
    last: date | None = None
    failure: str | None = None


def _fetch_cycle_bars(
    session: Session,
    adapter: MassiveOptionsAdapter,
    sel: _CycleSelection,
    *,
    underlying: str,
    span: tuple[date, date],
    bars_left: int,
    phases: _Phases,
) -> _CycleBars:
    """Fetch and store one cycle's bars in three non-overlapping phases.

    READ: which sessions this cycle's contracts already have. NETWORK: every
    paced request, with **no transaction open** — the project rule, and the one
    the shipped path broke by holding ``BEGIN IMMEDIATE`` across the whole run.
    WRITE: one short ``BEGIN IMMEDIATE`` that inserts the cycle. It is left
    OPEN on return so the caller's provenance checkpoint commits in the same
    transaction as the bars it describes.

    The per-contract range is the CYCLE'S OWN trade window, not the whole
    backfill window — the shipped path fetches every contract from the window
    start, which is ~10x the bars needed and is what puts a three-year run over
    the ceiling.
    """
    fetch_start, fetch_end = span

    phases.read()
    have = _existing_dates_many(
        session, [c.option_ticker for c in sel.carriers], adapter.provider_name
    )
    phases.commit()  # end the read transaction: no snapshot is held across the fetch

    pending: list[OptionAggregateRow] = []
    skipped = fetched = 0
    failure: str | None = None
    for carrier in sel.carriers:
        if len(pending) >= bars_left:
            failure = EXCL_BAR_BUDGET_EXHAUSTED
            break
        stored = have.setdefault(carrier.option_ticker, set())
        hard_end = min(fetch_end, carrier.expiration_date)
        covered = {d for d in stored if fetch_start <= d <= hard_end}
        if covered and max(covered) >= hard_end:
            continue  # already covered to this cycle's end for this contract
        resume_from = (max(covered) + timedelta(days=1)) if covered else fetch_start
        fetch_from = max(fetch_start, resume_from)
        if fetch_from > hard_end:
            continue
        try:
            bars = adapter.fetch_option_aggregates(
                carrier.option_ticker, start=fetch_from, end=hard_end, adjusted=True
            )
        except AdapterError:
            failure = EXCL_CONTRACT_FETCH_FAILED
            continue
        if len(bars) > _MAX_BARS_PER_CONTRACT:
            bars = bars[:_MAX_BARS_PER_CONTRACT]
        fetched += 1
        for b in bars:
            if len(pending) >= bars_left:
                failure = EXCL_BAR_BUDGET_EXHAUSTED
                break
            if b.session_date > hard_end or b.session_date < fetch_start:
                continue
            if b.session_date in stored:
                skipped += 1
                continue
            stored.add(b.session_date)
            pending.append(b)
        if failure == EXCL_BAR_BUDGET_EXHAUSTED:
            break

    phases.write()
    # Contract metadata for every SELECTED contract, including one whose bar
    # fetch failed: the selection is evidence about the ladder even when the
    # aggregates behind it are not yet there.
    for carrier in sel.carriers:
        _upsert_contract_meta(session, carrier)
    now = utcnow()
    for b in pending:
        session.add(
            OptionAggregateDaily(
                option_ticker=b.option_ticker,
                underlying_symbol=underlying,
                session_date=b.session_date,
                open=b.open,
                high=b.high,
                low=b.low,
                close=b.close,
                volume=b.volume,
                vwap=b.vwap,
                transactions=b.transactions,
                source=b.source,
                latency_category=b.latency_category,
                ingested_at=now,
                quality_flags=[],
            )
        )
    dates = [b.session_date for b in pending]
    return _CycleBars(
        written=len(pending),
        skipped=skipped,
        fetched=fetched,
        first=min(dates) if dates else None,
        last=max(dates) if dates else None,
        failure=failure,
    )


# Provenance fields that DECIDE WHAT THE DATASET IS. A resume that changed one
# of these would splice two different datasets under one provenance blob, and
# the blob would describe only the last pass — over ten nightly passes that is
# an unrecoverable identity problem, discovered (if ever) long after the fetch.
# ``max_total_bars`` is deliberately absent: raising the ceiling to recover
# budget-limited coverage is a supported, recorded operator action, and
# ``pacing_s`` is absent because it legitimately varies between passes and is
# accumulated instead.
_IDENTITY_KEYS: frozenset[str] = frozenset(
    {
        "window_start",
        "window_end",
        "cycle_rule",
        "cycle_expiry_adjustment",
        "dte_entry_min",
        "dte_entry_max",
        "strike_band_pct",
        "ladder_id",
        "ladder_offsets",
        "min_rungs_per_side",
        "pre_entry_buffer_sessions",
        "rights",
        "reference_source",
        "reference_max_staleness_sessions",
        "ladder_bracket_min_rungs",
        "listing_include_expired",
        "listing_as_of_enabled",
        "strike_listing_basis",
        "require_shares_per_contract",
        "options_config_hash",
        "provider",
    }
)


def _refuse_parameter_drift(run: IngestionRun, provenance: dict[str, object]) -> None:
    """A resume must continue the same dataset, not start a different one."""
    stored = dict((run.gaps_json or {}).get(_RUN_PROVENANCE_KEY, {}) or {})
    if not stored:
        return  # a run from before provenance was recorded structurally
    # ``cycle_expiry_adjustment`` is compared even when the stored blob predates
    # it: a run keyed on unadjusted calendar Fridays has a different cycle set
    # (its holiday cycles came back ``no_contracts_returned``), so continuing it
    # under the adjusted rule would splice two datasets.
    drift = {
        k: (stored.get(k), provenance.get(k))
        for k in _IDENTITY_KEYS
        if (k in stored or k == "cycle_expiry_adjustment") and stored.get(k) != provenance.get(k)
    }
    if drift:
        raise ValueError(
            f"ingestion_run {run.id} was built with different parameters and resuming it would "
            f"splice two datasets under one provenance record: {drift}. Start a NEW run for the "
            "new parameters — a changed window, ladder, listing basis or options_config_hash is "
            "a different dataset, not a continuation."
        )


def _carry_pacing_history(run: IngestionRun, provenance: dict[str, object]) -> dict[str, object]:
    """Keep every pacing a multi-pass run actually used, not just the last.

    D1 §7.5 requires the pacing ACTUALLY used to be recorded so a later run at a
    different rate is distinguishable. Over ten nightly passes, overwriting it
    would leave the record describing only the final night.
    """
    stored = dict((run.gaps_json or {}).get(_RUN_PROVENANCE_KEY, {}) or {})
    history = list(stored.get("pacing_s_passes") or [])
    for value in (stored.get("pacing_s"), provenance.get("pacing_s")):
        if value is not None and value not in history:
            history.append(value)
    return {**provenance, "pacing_s_passes": history}


@dataclass(slots=True)
class _Totals:
    """Run-level counters carried across cycles (and across resumes)."""

    written: int = 0
    skipped: int = 0
    cov_first: date | None = None
    cov_last: date | None = None
    earliest: date | None = None


def _run_one_cycle(
    session: Session,
    adapter: MassiveOptionsAdapter,
    *,
    underlying: str,
    expiry: date,
    caps: CycleBackfillCaps,
    basis: str,
    phases: _Phases,
    totals: _Totals,
) -> dict[str, object]:
    """Resolve, fetch and store ONE (underlying, cycle); return its record.

    On return the write transaction is **open** and holds this cycle's bars.
    The caller writes the run-level checkpoint into the same transaction and
    commits it, so a committed cycle is always a cycle whose coverage record
    was committed with it — there is no state in which bars exist that the
    provenance does not describe.
    """
    record: dict[str, object] = {
        "strike_listing_basis": basis,
        "print_time_known": False,
        "excluded": None,
    }
    entry = entry_as_of(expiry, dte_entry_max=caps.dte_entry_max)
    span = fetch_span(
        expiry,
        dte_entry_max=caps.dte_entry_max,
        pre_entry_buffer_sessions=caps.pre_entry_buffer_sessions,
        window_start=caps.window_start,
        window_end=caps.window_end,
    )
    record["entry_as_of"] = entry.isoformat() if entry else None
    if entry is None or span is None:
        record["excluded"] = EXCL_NO_BAR_ON_OR_BEFORE
        return record

    phases.read()
    ref, why = reference_price(
        session, underlying, entry, max_staleness_sessions=caps.reference_max_staleness_sessions
    )
    phases.commit()  # the listing call below is network: no transaction may be open
    if ref is None:
        record["excluded"] = why
        return record
    record["reference_price"] = ref.price
    record["reference_priced_on"] = ref.priced_on.isoformat()
    record["reference_staleness_sessions"] = ref.staleness_sessions

    sel = _select_cycle(
        adapter,
        underlying,
        expiry=expiry,
        entry=entry,
        ref=ref.price,
        caps=caps,
        strike_listing_basis=basis,
    )
    record.update(
        {
            "ladder_rungs_seen": sel.ladder_rungs_seen,
            "ladder_min_strike": sel.ladder_min_strike,
            "ladder_max_strike": sel.ladder_max_strike,
            "pages_walked": sel.pages_walked,
            "next_url_exhausted": sel.next_url_exhausted,
            "rows_unparseable": sel.rows_unparseable,
            "selected_calls": sel.selected_calls,
            "selected_puts": sel.selected_puts,
            "rungs_per_side": list(sel.rungs_per_side),
            "shares_per_contract_refusals": sel.refusals,
            "brackets_band": sel.excluded is None,
        }
    )
    if sel.excluded is not None:
        record["excluded"] = sel.excluded
        return record

    bars = _fetch_cycle_bars(
        session,
        adapter,
        sel,
        underlying=underlying,
        span=span,
        bars_left=max(0, caps.max_total_bars - totals.written),
        phases=phases,
    )
    totals.written += bars.written
    totals.skipped += bars.skipped
    if bars.first is not None:
        totals.cov_first = (
            bars.first if totals.cov_first is None else min(totals.cov_first, bars.first)
        )
        # Discovered provider depth: the earliest session any contract actually
        # returned. Never hard-coded — a later run at a deeper entitlement is
        # distinguishable from this one.
        totals.earliest = (
            bars.first if totals.earliest is None else min(totals.earliest, bars.first)
        )
    if bars.last is not None:
        totals.cov_last = bars.last if totals.cov_last is None else max(totals.cov_last, bars.last)
    record.update(
        {
            "contracts_fetched": bars.fetched,
            "bars_written": bars.written,
            "sessions_expected": len(_sessions(*span)),
            "fetch_start": span[0].isoformat(),
            "fetch_end": span[1].isoformat(),
        }
    )
    if bars.failure is not None:
        record["excluded"] = bars.failure
    return record


def backfill_option_cycles(
    session: Session,
    adapter: MassiveOptionsAdapter,
    underlyings: Sequence[str],
    *,
    caps: CycleBackfillCaps,
    options_config_hash: str = "",
    resume_run_id: int | None = None,
    bounds: RunBounds | None = None,
) -> IngestionRun:
    """Per-(underlying, monthly cycle) historical options backfill.

    Every cycle is centred on its OWN point-in-time reference price, selected by
    the pre-registered moneyness ladder against the true (unfiltered) vendor
    strike set for that single expiry, and fetched over its own trade window.
    Anything the run cannot serve is **excluded and counted by reason** — never
    silently shortened.

    Resumable at (underlying, cycle) granularity: a cycle already recorded is
    skipped, an exclusion that a later run could genuinely fix (a transient
    fetch failure, a bar-budget shortfall) is retried, and a deterministic
    exclusion is not re-attempted.

    Run-control properties, all of which the ~99-hour real run depends on
    (D1 §7.7, blockers D9 and D16):

    * **the ``IngestionRun`` row is committed before the first network call**,
      so a resume id survives an abort of any kind — including the kind a
      multi-day run actually takes;
    * **one transaction per (underlying, cycle)**, holding that cycle's bars and
      its coverage record together, with every paced request issued outside any
      transaction;
    * ``KillSwitchEngaged`` is caught at the **loop boundary**: the interrupted
      cycle is discarded, every earlier cycle stays committed, and the run ends
      ``killed`` — terminal, never retried, but never destructive;
    * ``bounds`` stops the pass at a cycle boundary so a run can be scheduled in
      windows that never overlap the live EOD / universe / grid jobs.
    """
    syms = [u.upper().strip() for u in underlyings if u.strip()]
    basis = resolve_strike_listing_basis(
        as_of_sent=caps.listing_as_of_enabled, first_bar_proxy_available=False
    )
    cycles = monthly_cycles(caps.window_start, caps.window_end, dte_entry_max=caps.dte_entry_max)
    provenance = _cycle_provenance(
        adapter, caps, strike_listing_basis=basis, options_config_hash=options_config_hash
    )
    limits = bounds or RunBounds()
    phases = _Phases(session)
    phases.write()

    if resume_run_id is not None:
        run = session.get(IngestionRun, resume_run_id)
        if run is None:
            raise ValueError(f"ingestion_run {resume_run_id} not found")
        _refuse_parameter_drift(run, provenance)
        provenance = _carry_pacing_history(run, provenance)
        # A re-entered run is running again; a previous pass's terminal status
        # and finish time would otherwise outlive the pass that set them.
        run.status = "running"
        run.finished_at = None
    else:
        run = IngestionRun(
            provider=adapter.provider_name,
            feed_type=FeedType.OPTIONS_CHAIN,
            kind=_CYCLE_KIND,
            requested_start=caps.window_start,
            requested_end=caps.window_end,
            adjusted=True,
            symbols_requested=list(syms),
            status="running",
            started_at=utcnow(),
            gaps_json={_RUN_PROVENANCE_KEY: provenance},
            notes=(
                f"{caps.cycle_rule}, {len(cycles)} cycles, DTE "
                f"{caps.dte_entry_min}-{caps.dte_entry_max}, {LADDER_ID}, band "
                f"+/-{caps.strike_band_pct:.0%}, bar ceiling {caps.max_total_bars:,} "
                f"(raised from {_MAX_TOTAL_BARS_PRIOR:,} by decision 6), pacing "
                f"{adapter.min_request_spacing_s}s, strike_listing_basis={basis}; "
                "latency=HISTORICAL"
            ),
        )
        session.add(run)
        session.flush()

    ok: list[str] = list(run.symbols_ok or [])
    failed: dict[str, str] = dict(run.symbols_failed or {})
    detail: dict[str, object] = dict(run.gaps_json or {})
    detail[_RUN_PROVENANCE_KEY] = provenance
    run.gaps_json = dict(detail)
    totals = _Totals(
        written=int(run.bars_written or 0),
        skipped=int(run.bars_skipped or 0),
        cov_first=run.coverage_first,
        cov_last=run.coverage_last,
        earliest=run.earliest_available_date,
    )
    # COMMITTED BEFORE THE FIRST NETWORK CALL. Without this the run row lives
    # only in a transaction that any abort rolls back, and a multi-day job
    # leaves no id to --resume (blocker D16).
    phases.commit()

    started = time.monotonic()
    deadline = limits.deadline(started)
    units = 0
    stop_status = ""
    stop_reason = ""

    for u in syms:
        if stop_status:
            break
        if u in ok:
            continue
        stored = detail.get(u)
        prior: dict[str, Any] = stored if isinstance(stored, dict) else {}
        per_cycle: dict[str, object] = dict(prior.get("cycles", {}) or {})
        failed.pop(u, None)

        for expiry in cycles:
            key = expiry.isoformat()
            done = per_cycle.get(key)
            if isinstance(done, dict) and done.get("excluded") not in _RETRYABLE_EXCLUSIONS:
                continue  # already covered, or deterministically excluded
            hit = limits.reached(units_done=units, now=time.monotonic(), deadline=deadline)
            if hit:
                stop_status, stop_reason = RUN_STATUS_STOPPED, hit
                break
            try:
                record = _run_one_cycle(
                    session,
                    adapter,
                    underlying=u,
                    expiry=expiry,
                    caps=caps,
                    basis=basis,
                    phases=phases,
                    totals=totals,
                )
            except KillSwitchEngaged as exc:
                # THE LOOP BOUNDARY. Every earlier cycle is already committed;
                # this one's partial work is discarded; the run keeps its id.
                # Terminal — the kill switch is never retried — but never
                # destructive (blocker D16).
                phases.abandon()
                stop_status, stop_reason = RUN_STATUS_KILLED, str(exc)[:180]
                break
            units += 1
            per_cycle[key] = record
            phases.write()  # no-op when the cycle already opened it: ONE transaction
            if totals.earliest is not None and run.earliest_probe_at is None:
                run.earliest_probe_at = utcnow()
            run.bars_written = totals.written
            run.bars_skipped = totals.skipped
            run.coverage_first = totals.cov_first
            run.coverage_last = totals.cov_last
            run.earliest_available_date = totals.earliest
            detail[u] = _cycle_rollup(per_cycle, len(cycles))
            run.gaps_json = dict(detail)
            phases.commit()

        phases.write()
        detail[u] = _cycle_rollup(per_cycle, len(cycles))
        run.gaps_json = dict(detail)
        retryable_left = any(
            isinstance(rec, dict) and rec.get("excluded") in _RETRYABLE_EXCLUSIONS
            for rec in per_cycle.values()
        )
        if stop_status:
            # The pass ended inside this underlying: it is neither done nor
            # broken, and marking it ok would make `if u in ok: continue` skip
            # the cycles this pass never reached.
            failed[u] = f"pass ended before this underlying completed ({stop_reason})"[:200]
        elif retryable_left:
            failed[u] = "retryable cycle exclusions remain (fetch failure or bar budget)"
        else:
            ok.append(u)
        run.symbols_ok = list(ok)
        run.symbols_failed = dict(failed)
        phases.commit()

    phases.write()
    if stop_status:
        provenance[_STOP_KEY] = {
            "status": stop_status,
            "reason": stop_reason,
            "at": utcnow().isoformat(),
            "cycles_this_pass": units,
            "resume_with": run.id,
        }
        detail[_RUN_PROVENANCE_KEY] = provenance
        run.gaps_json = dict(detail)
        run.notes = (run.notes + "; " if run.notes else "") + (
            f"pass ended {stop_status} after {units} cycle(s): {stop_reason}; "
            f"resume with --resume {run.id}"
        )
        run.status = stop_status
    else:
        provenance.pop(_STOP_KEY, None)
        detail[_RUN_PROVENANCE_KEY] = provenance
        run.gaps_json = dict(detail)
        run.status = "ok" if not failed else ("partial" if ok else "failed")
    run.symbols_ok = list(ok)
    run.symbols_failed = dict(failed)
    run.finished_at = utcnow()
    phases.commit()
    _log.info(
        "options.cycle_backfill.done",
        provider=adapter.provider_name,
        underlyings=len(syms),
        cycles=len(cycles),
        cycles_this_pass=units,
        bars_written=totals.written,
        status=run.status,
        stopped=stop_reason,
        strike_listing_basis=basis,
    )
    return run


# =========================================================================== #
# The request plan — what a run WOULD cost, computed with zero network.
# =========================================================================== #
# How many listing pages one (underlying, cycle) costs. HYPOTHESIS, not FACT
# (D1 §3.4): the true vendor ladder's depth is what decides it, and only SPY's
# is established, only within +/-8%. Stage A measures it; until then 2 is the
# planning assumption, and it is reported as an assumption.
DEFAULT_LISTING_PAGES_PER_CYCLE = 2


@dataclass(frozen=True, slots=True)
class BackfillRequestPlan:
    """The exact request plan for a run, derived from pre-registered parameters.

    Counts, dates and identities only — the same discipline as
    :class:`OptionsCoverageSummary`, for the same reason: a plan is printed
    before the data exists, and nothing that reaches an operator's eye before
    the strategy pre-registration is committed may be an outcome.

    Every figure is an **upper bound with no retries**: the ladder de-duplicates
    downward (two adjacent rungs can resolve to one strike), an excluded cycle
    costs its listing call and no aggregate calls, and the adapter is allowed up
    to five attempts per request. A run never costs more than this; it commonly
    costs less.
    """

    underlyings: tuple[str, ...]
    cycles: tuple[date, ...]
    ladder_id: str
    ladder_rungs: int
    rights: tuple[str, ...]
    contracts_per_cycle_max: int
    listing_pages_assumed: int
    units_total: int
    units_done: int
    units_remaining: int
    listing_requests: int
    aggregate_requests: int
    requests_total: int
    pacing_s: float
    sessions_per_cycle_min: int
    sessions_per_cycle_max: int
    sessions_per_cycle_mean: float
    bars_max: int
    max_total_bars: int
    window_start: date
    window_end: date
    cycle_rule: str
    strike_listing_basis: str

    @property
    def hours_at_pacing(self) -> float:
        return self.requests_total * self.pacing_s / 3600.0

    @property
    def bars_fraction_of_ceiling(self) -> float:
        return (self.bars_max / self.max_total_bars) if self.max_total_bars else 0.0


def completed_cycle_units(run: IngestionRun) -> int:
    """(underlying, cycle) units a previous pass has already settled.

    A unit recorded with a RETRYABLE exclusion is not settled: the next pass
    re-attempts it, so it still costs requests and must stay in the plan.
    """
    detail = dict(run.gaps_json or {})
    detail.pop(_RUN_PROVENANCE_KEY, None)
    done = 0
    for payload in detail.values():
        if not isinstance(payload, dict):
            continue
        for rec in (payload.get("cycles") or {}).values():
            if isinstance(rec, dict) and rec.get("excluded") not in _RETRYABLE_EXCLUSIONS:
                done += 1
    return done


def plan_cycle_backfill(
    underlyings: Sequence[str],
    *,
    caps: CycleBackfillCaps,
    pacing_s: float,
    listing_pages: int = DEFAULT_LISTING_PAGES_PER_CYCLE,
    units_done: int = 0,
) -> BackfillRequestPlan:
    """What the run would ask the provider for — computed, never fetched.

    Pure arithmetic over the pre-registered parameters and the XNYS calendar.
    It issues no request, opens no session and constructs no adapter, so it is
    safe to run at any hour against any configuration, including one with no
    API key at all.
    """
    syms = tuple(u.upper().strip() for u in underlyings if u.strip())
    cycles = monthly_cycles(caps.window_start, caps.window_end, dte_entry_max=caps.dte_entry_max)
    spans = [
        fetch_span(
            e,
            dte_entry_max=caps.dte_entry_max,
            pre_entry_buffer_sessions=caps.pre_entry_buffer_sessions,
            window_start=caps.window_start,
            window_end=caps.window_end,
        )
        for e in cycles
    ]
    session_counts = [len(_sessions(*s)) for s in spans if s is not None]
    mean_sessions = (sum(session_counts) / len(session_counts)) if session_counts else 0.0
    per_cycle = len(caps.rights) * len(caps.ladder)
    units_total = len(syms) * len(cycles)
    remaining = max(0, units_total - max(0, units_done))
    listing = remaining * max(0, listing_pages)
    aggregate = remaining * per_cycle
    return BackfillRequestPlan(
        underlyings=syms,
        cycles=cycles,
        ladder_id=LADDER_ID,
        ladder_rungs=len(caps.ladder),
        rights=caps.rights,
        contracts_per_cycle_max=per_cycle,
        listing_pages_assumed=listing_pages,
        units_total=units_total,
        units_done=max(0, units_done),
        units_remaining=remaining,
        listing_requests=listing,
        aggregate_requests=aggregate,
        requests_total=listing + aggregate,
        pacing_s=pacing_s,
        sessions_per_cycle_min=min(session_counts) if session_counts else 0,
        sessions_per_cycle_max=max(session_counts) if session_counts else 0,
        sessions_per_cycle_mean=mean_sessions,
        bars_max=round(aggregate * mean_sessions),
        max_total_bars=caps.max_total_bars,
        window_start=caps.window_start,
        window_end=caps.window_end,
        cycle_rule=caps.cycle_rule,
        strike_listing_basis=resolve_strike_listing_basis(
            as_of_sent=caps.listing_as_of_enabled, first_bar_proxy_available=False
        ),
    )


def _cycle_rollup(per_cycle: dict[str, object], cycles_total: int) -> dict[str, object]:
    excluded: dict[str, int] = {}
    covered = 0
    for rec in per_cycle.values():
        if not isinstance(rec, dict):
            continue
        reason = rec.get("excluded")
        if reason:
            excluded[str(reason)] = excluded.get(str(reason), 0) + 1
        else:
            covered += 1
    return {
        "cycles": per_cycle,
        "cycles_total": cycles_total,
        "cycles_covered": covered,
        "cycles_excluded": excluded,
    }
