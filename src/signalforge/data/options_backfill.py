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
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from signalforge.data.adapters.base import AdapterError
from signalforge.data.adapters.massive_options import MassiveOptionsAdapter
from signalforge.data.calendar import sessions as _sessions
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
    win_start = max(start, date.today() - timedelta(days=caps.lookback_days))
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
