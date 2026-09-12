"""Declared dividends and executed splits — reference data for options pricing.

Why this exists at all, stated plainly: the Black-Scholes path takes a
continuous dividend yield ``q`` **defaulted to 0.0**, and there is no dividend
series anywhere in this repo — ``corporate_action`` is empty and the equities
adapter's ``fetch_corporate_actions`` returns ``()``. At ``q = 0`` on a
dividend-paying underlying, puts are underpriced and calls overpriced by roughly
the present value of the dividends over the option's life. For a put-*selling*
strategy that is not noise: the modelled credit received on entry is below the
true one and the buy-back is charged too little — **a one-directional bias in
the strategy's own favour**. Decision 11 therefore sources and records ``q``
rather than restricting the underlying set, so SPY and IWM stay in scope, and a
run that used ``q = 0.0`` by default fails gate 0.g outright.

Splits are here for a second, independent reason (D1 §2.3): stored equity bars
are back-adjusted with no marker while option **strikes are not**, so the
point-in-time reference price for a pre-split cycle is off by the split factor
and the band computed from it asks for strikes that never existed — a failure
that is invisible because the band filter is applied server-side and simply
looks like "that cycle had no contracts".

Read-only reference data. No prices, no snapshots, no decision path.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from signalforge.data.adapters.base import AdapterError
from signalforge.data.adapters.massive_options import MassiveOptionsAdapter
from signalforge.db.models import DividendEvent, IngestionRun, SplitEvent
from signalforge.db.types import utcnow
from signalforge.domain import FeedType
from signalforge.observability import get_logger

_log = get_logger("options.corporate_actions")

_KIND = "options_q_reference"
_TRAILING_DAYS = 365


@dataclass(frozen=True, slots=True)
class CorporateActionCoverage:
    """Counts only — this path never reports an amount, only how many it wrote."""

    symbol: str
    dividends_seen: int = 0
    dividends_written: int = 0
    splits_seen: int = 0
    splits_written: int = 0
    first_ex_date: date | None = None
    last_ex_date: date | None = None
    error: str | None = None


def ingest_dividends_and_splits(
    session: Session,
    adapter: MassiveOptionsAdapter,
    symbols: Sequence[str],
    *,
    resume_run_id: int | None = None,
) -> IngestionRun:
    """Fetch and store declared dividends + executed splits for ``symbols``.

    Idempotent on ``(symbol, date, source)`` and resumable per symbol: a symbol
    already in ``symbols_ok`` is skipped, and a symbol whose fetch failed stays
    retryable rather than being silently marked complete.

    Writes a real ``IngestionRun``. A data path that leaves no trace cannot be
    audited, and provenance is a gate-8 input.
    """
    syms = [s.upper().strip() for s in symbols if s.strip()]
    if resume_run_id is not None:
        run = session.get(IngestionRun, resume_run_id)
        if run is None:
            raise ValueError(f"ingestion_run {resume_run_id} not found")
    else:
        run = IngestionRun(
            provider=adapter.provider_name,
            feed_type=FeedType.CORP_ACTION,
            kind=_KIND,
            requested_start=date(1970, 1, 1),
            requested_end=date.today(),
            adjusted=False,  # declared amounts and executed ratios, never adjusted
            symbols_requested=list(syms),
            status="running",
            started_at=utcnow(),
            notes=(
                "declared dividends + executed splits; the rank-1 source for the "
                "continuous dividend yield q (decision 11). q=0.0 by default is "
                "never permitted — gate 0.g fails a run that used it."
            ),
        )
        session.add(run)
        session.flush()

    ok: list[str] = list(run.symbols_ok or [])
    failed: dict[str, str] = dict(run.symbols_failed or {})
    detail: dict[str, object] = dict(run.gaps_json or {})
    written = int(run.bars_written or 0)
    skipped = int(run.bars_skipped or 0)
    now = utcnow()

    for sym in syms:
        if sym in ok:
            continue
        failed.pop(sym, None)
        cov = CorporateActionCoverage(symbol=sym)
        try:
            divs = adapter.fetch_dividends(sym)
            splits = adapter.fetch_splits(sym)
        except AdapterError as exc:
            failed[sym] = str(exc)[:200]
            run.symbols_failed = failed
            session.flush()
            continue

        have_div = {
            d
            for (d,) in session.execute(
                select(DividendEvent.ex_dividend_date).where(
                    DividendEvent.symbol == sym, DividendEvent.source == adapter.provider_name
                )
            )
        }
        n_div = 0
        for d in divs:
            if d.ex_dividend_date in have_div:
                skipped += 1
                continue
            session.add(
                DividendEvent(
                    symbol=sym,
                    ex_dividend_date=d.ex_dividend_date,
                    cash_amount=d.cash_amount,
                    declaration_date=d.declaration_date,
                    record_date=d.record_date,
                    pay_date=d.pay_date,
                    frequency=d.frequency,
                    dividend_type=d.dividend_type[:8],
                    currency=d.currency[:8],
                    source=adapter.provider_name,
                    ingested_at=now,
                )
            )
            have_div.add(d.ex_dividend_date)
            n_div += 1
            written += 1

        have_split = {
            d
            for (d,) in session.execute(
                select(SplitEvent.execution_date).where(
                    SplitEvent.symbol == sym, SplitEvent.source == adapter.provider_name
                )
            )
        }
        n_split = 0
        for s in splits:
            if s.execution_date in have_split:
                skipped += 1
                continue
            session.add(
                SplitEvent(
                    symbol=sym,
                    execution_date=s.execution_date,
                    split_from=s.split_from,
                    split_to=s.split_to,
                    source=adapter.provider_name,
                    ingested_at=now,
                )
            )
            have_split.add(s.execution_date)
            n_split += 1
            written += 1

        ex_dates = [d.ex_dividend_date for d in divs]
        cov = CorporateActionCoverage(
            symbol=sym,
            dividends_seen=len(divs),
            dividends_written=n_div,
            splits_seen=len(splits),
            splits_written=n_split,
            first_ex_date=min(ex_dates) if ex_dates else None,
            last_ex_date=max(ex_dates) if ex_dates else None,
        )
        detail[sym] = {
            "dividends_seen": cov.dividends_seen,
            "dividends_written": cov.dividends_written,
            "splits_seen": cov.splits_seen,
            "splits_written": cov.splits_written,
            "first_ex_date": cov.first_ex_date.isoformat() if cov.first_ex_date else None,
            "last_ex_date": cov.last_ex_date.isoformat() if cov.last_ex_date else None,
        }
        ok.append(sym)
        run.symbols_ok = list(ok)
        run.symbols_failed = failed
        run.gaps_json = dict(detail)
        run.bars_written = written
        run.bars_skipped = skipped
        session.flush()

    run.status = "ok" if not failed else ("partial" if ok else "failed")
    run.finished_at = utcnow()
    session.flush()
    _log.info(
        "options.corporate_actions.done",
        provider=adapter.provider_name,
        symbols=len(syms),
        rows_written=written,
        status=run.status,
    )
    return run


@dataclass(frozen=True, slots=True)
class DividendYield:
    q: float
    source: str
    payments: int
    window_start: date
    window_end: date


def trailing_dividend_yield(
    session: Session,
    symbol: str,
    as_of: date,
    *,
    reference_close: float,
    source: str = "massive_options",
    trailing_days: int = _TRAILING_DAYS,
) -> DividendYield | None:
    """Trailing-12-month declared yield as at ``as_of`` — rank 1 for ``q``.

    Point-in-time by construction: only ex-dates **on or before** ``as_of`` are
    summed, so a dividend declared after the decision cannot leak into it. A
    21-60 DTE horizon does not need a term structure of ``q``; a trailing
    twelve-month yield is sufficient and is what decision 11 specifies.

    Returns ``None`` when there is no dividend history to rest on — the caller
    must then fall to rank 2 (put-call parity) or fail gate 0.g. It never
    returns 0.0 as a fallback: ``q = 0`` is not a measurement, it is the
    assumption that biases a short-premium result in its own favour.
    """
    if reference_close <= 0:
        return None
    window_start = as_of - timedelta(days=trailing_days)
    rows = list(
        session.execute(
            select(DividendEvent.cash_amount).where(
                DividendEvent.symbol == symbol.upper(),
                DividendEvent.source == source,
                DividendEvent.ex_dividend_date > window_start,
                DividendEvent.ex_dividend_date <= as_of,
            )
        )
    )
    if not rows:
        return None
    total = sum(float(r[0]) for r in rows)
    return DividendYield(
        q=total / reference_close,
        source="vendor_dividends",
        payments=len(rows),
        window_start=window_start,
        window_end=as_of,
    )


def splits_between(
    session: Session,
    symbol: str,
    start: date,
    end: date,
    *,
    source: str = "massive_options",
) -> list[SplitEvent]:
    """Executed splits in ``(start, end]`` — a cycle crossing one is excluded.

    Named exclusion, not a guess: the ladder-bracket check detects a split's
    *effect* but cannot name the event or its date, so an excluded cycle is
    otherwise indistinguishable from a genuinely empty chain.
    """
    return list(
        session.scalars(
            select(SplitEvent)
            .where(
                SplitEvent.symbol == symbol.upper(),
                SplitEvent.source == source,
                SplitEvent.execution_date > start,
                SplitEvent.execution_date <= end,
            )
            .order_by(SplitEvent.execution_date)
        )
    )
