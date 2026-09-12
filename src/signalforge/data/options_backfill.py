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

from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import date, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from signalforge.data.adapters.base import AdapterError
from signalforge.data.adapters.massive_options import MassiveOptionsAdapter
from signalforge.data.calendar import sessions as _sessions
from signalforge.data.options_cycles import (
    BASIS_NONE,
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
from signalforge.db.types import utcnow
from signalforge.domain import FeedType
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


def coverage_summary(run: IngestionRun) -> OptionsCoverageSummary:
    """Derive the coverage summary from a cycle run's own provenance.

    Reads ``IngestionRun`` only. It never touches ``option_aggregate_daily``,
    so it cannot see a price even if someone later asks it to.
    """
    detail = dict(run.gaps_json or {})
    prov = dict(detail.pop(_RUN_PROVENANCE_KEY, {}) or {})
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
    return OptionsCoverageSummary(
        provider=run.provider,
        run_id=run.id,
        window_start=run.requested_start,
        window_end=run.requested_end,
        cycle_rule=str(prov.get("cycle_rule", "")),
        ladder_id=str(prov.get("ladder_id", "")),
        strike_listing_basis=str(prov.get("strike_listing_basis", "")),
        underlyings=tuple(run.symbols_requested or []),
        cycles_total=cycles_total,
        cycles_covered=cycles_covered,
        cycles_excluded=cycles_excluded,
        exclusions_by_reason=tuple(sorted(reasons.items())),
        contracts_selected=contracts_selected,
        contracts_fetched=contracts_fetched,
        bars_written=int(run.bars_written or 0),
        bars_skipped=int(run.bars_skipped or 0),
        sessions_expected=sessions_expected,
        shares_per_contract_refusals=refusals,
        ladder_incomplete_cycles=ladder_incomplete,
        underlyings_ok=tuple(run.symbols_ok or []),
        underlyings_failed=tuple(sorted(run.symbols_failed or {})),
        earliest_available_date=run.earliest_available_date,
        max_total_bars=int(prov.get("max_total_bars", 0)),
        max_total_bars_prior=int(prov.get("max_total_bars_prior", 0)),
        pacing_s=float(prov.get("pacing_s", 0.0)),
        status=run.status,
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
            expired=caps.listing_include_expired or None,
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


def _fetch_cycle_bars(
    session: Session,
    adapter: MassiveOptionsAdapter,
    sel: _CycleSelection,
    *,
    underlying: str,
    span: tuple[date, date],
    bars_left: int,
) -> tuple[int, int, int, date | None, date | None, str | None]:
    """Fetch and store one cycle's bars.

    ``(written, skipped, contracts_fetched, first, last, failure_reason)``. The
    per-contract range is the CYCLE'S OWN trade window, not the whole backfill
    window — the shipped path fetches every contract from the window start,
    which is ~10x the bars needed and is what puts a three-year run over the
    ceiling.
    """
    fetch_start, fetch_end = span
    written = skipped = fetched = 0
    first: date | None = None
    last: date | None = None
    failure: str | None = None
    for carrier in sel.carriers:
        if written >= bars_left:
            return written, skipped, fetched, first, last, EXCL_BAR_BUDGET_EXHAUSTED
        _upsert_contract_meta(session, carrier)
        hard_end = min(fetch_end, carrier.expiration_date)
        have = _existing_dates(session, carrier.option_ticker, adapter.provider_name)
        covered = {d for d in have if fetch_start <= d <= hard_end}
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
            if written >= bars_left:
                return written, skipped, fetched, first, last, EXCL_BAR_BUDGET_EXHAUSTED
            if b.session_date > hard_end or b.session_date < fetch_start:
                continue
            if b.session_date in have:
                skipped += 1
                continue
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
                    ingested_at=utcnow(),
                    quality_flags=[],
                )
            )
            have.add(b.session_date)
            written += 1
            first = b.session_date if first is None else min(first, b.session_date)
            last = b.session_date if last is None else max(last, b.session_date)
    return written, skipped, fetched, first, last, failure


def backfill_option_cycles(
    session: Session,
    adapter: MassiveOptionsAdapter,
    underlyings: Sequence[str],
    *,
    caps: CycleBackfillCaps,
    options_config_hash: str = "",
    resume_run_id: int | None = None,
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
    """
    syms = [u.upper().strip() for u in underlyings if u.strip()]
    basis = resolve_strike_listing_basis(
        as_of_sent=caps.listing_as_of_enabled, first_bar_proxy_available=False
    )
    cycles = monthly_cycles(caps.window_start, caps.window_end, dte_entry_max=caps.dte_entry_max)
    provenance = _cycle_provenance(
        adapter, caps, strike_listing_basis=basis, options_config_hash=options_config_hash
    )

    if resume_run_id is not None:
        run = session.get(IngestionRun, resume_run_id)
        if run is None:
            raise ValueError(f"ingestion_run {resume_run_id} not found")
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
    written = int(run.bars_written or 0)
    skipped = int(run.bars_skipped or 0)
    cov_first: date | None = run.coverage_first
    cov_last: date | None = run.coverage_last
    earliest: date | None = run.earliest_available_date

    for u in syms:
        if u in ok:
            continue
        stored = detail.get(u)
        prior: dict[str, Any] = stored if isinstance(stored, dict) else {}
        per_cycle: dict[str, object] = dict(prior.get("cycles", {}) or {})
        failed.pop(u, None)
        retryable_left = False

        for expiry in cycles:
            key = expiry.isoformat()
            done = per_cycle.get(key)
            if isinstance(done, dict) and done.get("excluded") not in _RETRYABLE_EXCLUSIONS:
                continue  # already covered, or deterministically excluded
            entry = entry_as_of(expiry, dte_entry_max=caps.dte_entry_max)
            span = fetch_span(
                expiry,
                dte_entry_max=caps.dte_entry_max,
                pre_entry_buffer_sessions=caps.pre_entry_buffer_sessions,
                window_start=caps.window_start,
                window_end=caps.window_end,
            )
            record: dict[str, object] = {
                "entry_as_of": entry.isoformat() if entry else None,
                "strike_listing_basis": basis,
                "print_time_known": False,
                "excluded": None,
            }
            if entry is None or span is None:
                record["excluded"] = EXCL_NO_BAR_ON_OR_BEFORE
                per_cycle[key] = record
                continue
            ref, why = reference_price(
                session,
                u,
                entry,
                max_staleness_sessions=caps.reference_max_staleness_sessions,
            )
            if ref is None:
                record["excluded"] = why
                per_cycle[key] = record
                continue
            record["reference_price"] = ref.price
            record["reference_priced_on"] = ref.priced_on.isoformat()
            record["reference_staleness_sessions"] = ref.staleness_sessions
            sel = _select_cycle(
                adapter,
                u,
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
                retryable_left = retryable_left or sel.excluded in _RETRYABLE_EXCLUSIONS
                per_cycle[key] = record
                session.flush()
                continue

            sessions_expected = len(_sessions(*span))
            w, s, fetched, first, last, failure = _fetch_cycle_bars(
                session,
                adapter,
                sel,
                underlying=u,
                span=span,
                bars_left=max(0, caps.max_total_bars - written),
            )
            written += w
            skipped += s
            cov_first = first if cov_first is None else min(cov_first, first or cov_first)
            cov_last = last if cov_last is None else max(cov_last, last or cov_last)
            if first is not None:
                # Discovered provider depth: the earliest session any contract
                # actually returned. Never hard-coded — a later run at a deeper
                # entitlement is distinguishable from this one.
                earliest = first if earliest is None else min(earliest, first)
                if run.earliest_probe_at is None:
                    run.earliest_probe_at = utcnow()
            record.update(
                {
                    "contracts_fetched": fetched,
                    "bars_written": w,
                    "sessions_expected": sessions_expected,
                    "fetch_start": span[0].isoformat(),
                    "fetch_end": span[1].isoformat(),
                }
            )
            if failure is not None:
                record["excluded"] = failure
                retryable_left = True
            per_cycle[key] = record
            run.bars_written = written
            run.bars_skipped = skipped
            run.coverage_first = cov_first
            run.coverage_last = cov_last
            run.earliest_available_date = earliest
            detail[u] = _cycle_rollup(per_cycle, len(cycles))
            run.gaps_json = dict(detail)
            session.flush()

        detail[u] = _cycle_rollup(per_cycle, len(cycles))
        run.gaps_json = dict(detail)
        run.symbols_failed = failed
        if not retryable_left:
            ok.append(u)
            run.symbols_ok = list(ok)
        else:
            failed[u] = "retryable cycle exclusions remain (fetch failure or bar budget)"
            run.symbols_failed = failed
        session.flush()

    run.status = "ok" if not failed else ("partial" if ok else "failed")
    run.finished_at = utcnow()
    session.flush()
    _log.info(
        "options.cycle_backfill.done",
        provider=adapter.provider_name,
        underlyings=len(syms),
        cycles=len(cycles),
        bars_written=written,
        status=run.status,
        strike_listing_basis=basis,
    )
    return run


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
