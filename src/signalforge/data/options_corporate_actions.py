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

import hashlib
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from functools import partial

from sqlalchemy import select
from sqlalchemy.orm import Session

from signalforge.data import calendar
from signalforge.data.adapters.base import AdapterError
from signalforge.data.adapters.massive_options import MassiveOptionsAdapter
from signalforge.data.repository import get_daily_bars
from signalforge.db.models import DividendEvent, DividendYieldDaily, IngestionRun, SplitEvent
from signalforge.db.retry import retry_on_lock
from signalforge.db.types import utcnow
from signalforge.domain import FeedType
from signalforge.observability import get_logger

_log = get_logger("options.corporate_actions")

_KIND = "options_q_reference"
_SERIES_KIND = "options_q_series"
_TRAILING_DAYS = 365

#: The ``source`` every derived ``DividendYieldDaily`` row carries, and the
#: ``q_source`` the short-vertical strategy records on each entry it takes from
#: it.  One constant so the two can never drift apart.
Q_SERIES_SOURCE = "vendor_dividends"

#: ``(symbol, session_date) -> q | None``.  Structurally identical to
#: ``research.options_strategies.short_vertical.QLookup``; declared here so the
#: data layer never imports the research stack.
QLookup = Callable[[str, date], float | None]


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


@dataclass(frozen=True, slots=True)
class _SymbolDerivation:
    """One underlying's derivation outcome — counts and dates only."""

    written: int = 0
    skipped: int = 0
    first: date | None = None
    last: date | None = None
    detail: dict[str, object] | None = None
    error: str | None = None


def derive_dividend_yield_series(
    session: Session,
    symbols: Sequence[str],
    start: date,
    end: date,
    *,
    source: str = "massive",
    dividend_source: str = MassiveOptionsAdapter.provider_name,
    trailing_days: int = _TRAILING_DAYS,
    commit_per_symbol: bool = False,
) -> IngestionRun:
    """Derive the per-session trailing-twelve-month ``q`` series for ``symbols``.

    For every XNYS session ``S`` in ``[start, end]`` with a stored ``source``
    daily close, ``q(S) = sum(cash_amount for ex-dates in (S - trailing_days, S])
    / close(S)``.  Exactly ``trailing_dividend_yield``'s rule, applied to every
    session instead of one ``as_of``, and with the same refusal: a session with
    **no** dividend history inside its window writes NO row.  ``q = 0.0`` is
    never written as a fallback — it is the assumption gate 0.g refuses.

    Point-in-time by construction: an ex-date after ``S`` cannot enter ``q(S)``.
    Idempotent on ``(symbol, session_date, source)``: a re-run rewrites the same
    rows in place (the close or a late-ingested dividend may have changed) and
    reports them as skipped when nothing changed.

    Reads ``DividendEvent`` and ``OHLCVDaily`` only — no network, no adapter.
    Records an ``IngestionRun`` of kind ``options_q_series`` so every row is
    traceable to the derivation that wrote it.

    ``commit_per_symbol=True`` makes each underlying its own short write
    transaction (the run row, each symbol, then the final status), each retried
    as a whole on transient SQLite lock contention — the per-unit rule of
    docs/SQLITE_CONCURRENCY.md — instead of one write lock held for the whole
    pass.  The default leaves the transaction to the caller, unchanged.
    """
    syms = [s.upper().strip() for s in symbols if s.strip()]
    run = IngestionRun(
        provider=dividend_source,
        feed_type=FeedType.CORP_ACTION,
        kind=_SERIES_KIND,
        requested_start=start,
        requested_end=end,
        adjusted=False,
        symbols_requested=list(syms),
        status="running",
        started_at=utcnow(),
        notes=(
            f"trailing-{trailing_days}d dividend yield per (underlying, session), derived from "
            f"dividend_event[{dividend_source}] / ohlcv_daily[{source}] close. No row where "
            "there is no dividend history in the window — never a 0.0 fallback (gate 0.g)."
        ),
    )

    def _unit[T](fn: Callable[[], T]) -> T:
        """Run ``fn`` as one unit of work: its own committed transaction, retried
        whole on a transient lock, when ``commit_per_symbol``; inline otherwise."""
        if not commit_per_symbol:
            return fn()

        def attempt() -> T:
            try:
                out = fn()
                session.commit()
                return out
            except Exception:
                session.rollback()
                raise

        return retry_on_lock(attempt, label="options.q_series")

    def _open_run() -> None:
        session.add(run)
        session.flush()

    _unit(_open_run)

    ok: list[str] = []
    failed: dict[str, str] = {}
    detail: dict[str, object] = {}
    written = 0
    skipped = 0
    cov_first: date | None = None
    cov_last: date | None = None

    def _derive_symbol(sym: str) -> _SymbolDerivation:
        bars = get_daily_bars(session, sym, start, end, source=source)
        if not bars:
            return _SymbolDerivation(error=f"no {source} daily bars in {start}..{end}")
        events = list(
            session.execute(
                select(DividendEvent.ex_dividend_date, DividendEvent.cash_amount).where(
                    DividendEvent.symbol == sym,
                    DividendEvent.source == dividend_source,
                    DividendEvent.ex_dividend_date > start - timedelta(days=trailing_days),
                    DividendEvent.ex_dividend_date <= end,
                )
            )
        )
        existing = {
            row.session_date: row
            for row in session.scalars(
                select(DividendYieldDaily).where(
                    DividendYieldDaily.symbol == sym,
                    DividendYieldDaily.source == Q_SERIES_SOURCE,
                    DividendYieldDaily.session_date >= start,
                    DividendYieldDaily.session_date <= end,
                )
            )
        }
        n_written = 0
        n_skipped = 0
        n_no_history = 0
        n_non_session = 0
        first: date | None = None
        last: date | None = None
        for bar in bars:
            s_date = bar.session_date
            if not calendar.is_session(s_date):
                n_non_session += 1
                continue
            if bar.close <= 0:
                n_no_history += 1
                continue
            window_start = s_date - timedelta(days=trailing_days)
            in_window = [float(amount) for (ex, amount) in events if window_start < ex <= s_date]
            if not in_window:
                n_no_history += 1
                continue
            q = sum(in_window) / float(bar.close)
            payments = len(in_window)
            row = existing.get(s_date)
            if row is not None:
                if (
                    row.q == q
                    and row.payments == payments
                    and row.reference_close == float(bar.close)
                    and row.window_start == window_start
                ):
                    n_skipped += 1
                else:
                    row.q = q
                    row.payments = payments
                    row.reference_close = float(bar.close)
                    row.window_start = window_start
                    row.derived_from_run_id = run.id
                    n_written += 1
            else:
                session.add(
                    DividendYieldDaily(
                        symbol=sym,
                        session_date=s_date,
                        q=q,
                        source=Q_SERIES_SOURCE,
                        payments=payments,
                        window_start=window_start,
                        reference_close=float(bar.close),
                        derived_from_run_id=run.id,
                    )
                )
                n_written += 1
            first = s_date if first is None else first
            last = s_date
        return _SymbolDerivation(
            written=n_written,
            skipped=n_skipped,
            first=first,
            last=last,
            detail={
                "sessions_with_close": len(bars) - n_non_session,
                "sessions_written": n_written,
                "sessions_unchanged": n_skipped,
                "sessions_without_history": n_no_history,
                "first_session": first.isoformat() if first else None,
                "last_session": last.isoformat() if last else None,
                "dividends_in_scope": len(events),
            },
        )

    def _one(sym: str) -> _SymbolDerivation:
        res = _derive_symbol(sym)
        # Progress is recorded in the SAME unit as the rows it describes, so
        # a committed symbol is never missing from its run row.
        if res.error is None:
            run.symbols_ok = [*ok, sym]
            run.gaps_json = {**detail, sym: res.detail}
            run.bars_written = written + res.written
            run.bars_skipped = skipped + res.skipped
        else:
            run.symbols_failed = {**failed, sym: res.error}
        session.flush()
        return res

    for sym in syms:
        res = _unit(partial(_one, sym))
        if res.error is not None:
            failed[sym] = res.error
            continue
        written += res.written
        skipped += res.skipped
        if res.first is not None:
            cov_first = res.first if cov_first is None or res.first < cov_first else cov_first
            cov_last = (
                res.last if cov_last is None or (res.last and res.last > cov_last) else cov_last
            )
        detail[sym] = res.detail
        ok.append(sym)

    def _close_run() -> None:
        run.symbols_ok = list(ok)
        run.symbols_failed = dict(failed)
        run.gaps_json = dict(detail)
        run.bars_written = written
        run.bars_skipped = skipped
        run.coverage_first = cov_first
        run.coverage_last = cov_last
        run.status = "ok" if not failed else ("partial" if ok else "failed")
        run.finished_at = utcnow()
        session.flush()

    _unit(_close_run)
    _log.info(
        "options.q_series.done",
        symbols=len(syms),
        rows_written=written,
        rows_unchanged=skipped,
        status=run.status,
    )
    return run


def q_series_digest(
    session: Session,
    symbols: Sequence[str],
    start: date,
    end: date,
    source: str = Q_SERIES_SOURCE,
) -> str:
    """Deterministic sha256 of the derived ``q`` series a run would price on.

    Hashes the ordered ``(symbol, session_date, repr(q), source)`` rows for
    ``symbols`` on ``[start, end]``.  The series is MUTABLE (a re-derivation
    rewrites rows in place) and lives outside every snapshot key, so anything
    that caches or records a result priced on it must carry this digest: two
    evaluations with the same digest read the same ``q`` on every session, and
    a series that was absent, re-derived or extended yields a different one.

    The row count is part of the preimage, so a missing/empty series has its
    own digest (``rows=0``) that no populated series can share.  Symbols are
    upper-cased, de-duplicated and sorted — the digest does not depend on the
    order or case the caller listed them in.
    """
    syms = sorted({s.upper().strip() for s in symbols if s.strip()})
    rows: list[tuple[str, date, float]] = []
    if syms:
        rows = [
            (str(sym), s_date, float(q))
            for sym, s_date, q in session.execute(
                select(
                    DividendYieldDaily.symbol,
                    DividendYieldDaily.session_date,
                    DividendYieldDaily.q,
                )
                .where(
                    DividendYieldDaily.symbol.in_(syms),
                    DividendYieldDaily.source == source,
                    DividendYieldDaily.session_date >= start,
                    DividendYieldDaily.session_date <= end,
                )
                .order_by(DividendYieldDaily.symbol, DividendYieldDaily.session_date)
            )
        ]
    h = hashlib.sha256()
    h.update(f"q-series-v1|rows={len(rows)}\n".encode())
    for sym, s_date, q in rows:
        h.update(f"{sym}|{s_date.isoformat()}|{q!r}|{source}\n".encode())
    return h.hexdigest()


def latest_q_series_run_id(session: Session) -> int | None:
    """Id of the most recent ``options_q_series`` derivation, or ``None``."""
    run_id = session.scalar(
        select(IngestionRun.id)
        .where(IngestionRun.kind == _SERIES_KIND)
        .order_by(IngestionRun.id.desc())
        .limit(1)
    )
    return int(run_id) if run_id is not None else None


def build_q_lookup(
    session: Session,
    symbols: Sequence[str],
    *,
    source: str = Q_SERIES_SOURCE,
) -> QLookup:
    """Preload the derived ``q`` series for ``symbols`` and return a lookup.

    The callable answers ``(symbol, session_date) -> q`` on an EXACT session
    match and ``None`` otherwise.  ``None`` is deliberate and load-bearing: the
    short-vertical strategy treats it as a non-entry on that session, which is
    how a gap in the dividend series stays a gap instead of becoming ``q = 0``.
    No carry-forward, no interpolation — a nearest-session fill would be a
    value the evidence never recorded.
    """
    syms = {s.upper().strip() for s in symbols if s.strip()}
    table: dict[tuple[str, date], float] = {}
    if syms:
        for sym, s_date, q in session.execute(
            select(
                DividendYieldDaily.symbol, DividendYieldDaily.session_date, DividendYieldDaily.q
            ).where(
                DividendYieldDaily.symbol.in_(sorted(syms)), DividendYieldDaily.source == source
            )
        ):
            table[(sym, s_date)] = float(q)

    def lookup(symbol: str, session_date: date) -> float | None:
        return table.get((symbol.upper(), session_date))

    return lookup
