"""Data-quality validation over the normalized daily store.

Read-only. Produces a structured report (persisted as ``DataValidationReport``)
covering chronological continuity, duplicates, missing sessions vs the XNYS
calendar, symbol coverage, OHLCV sanity, split/dividend-adjustment behaviour, and
timezone/date consistency. Callers gate ingestion / backtests on ``passed``.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from itertools import pairwise

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from signalforge.data.calendar import sessions
from signalforge.db.models import (
    DataValidationReport,
    Instrument,
    OHLCVDaily,
    OptionAggregateDaily,
    OptionContract,
)
from signalforge.db.types import utcnow
from signalforge.domain import LatencyCategory


@dataclass(slots=True)
class Check:
    name: str
    passed: bool
    detail: str = ""


@dataclass(slots=True)
class ValidationResult:
    provider: str
    symbols: list[str]
    checks: list[Check] = field(default_factory=list)
    findings: list[str] = field(default_factory=list)
    coverage: dict[str, dict[str, object]] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks)

    def to_row(self) -> DataValidationReport:
        return DataValidationReport(
            provider=self.provider,
            symbols=self.symbols,
            ran_at=utcnow(),
            passed=self.passed,
            checks_json={c.name: {"passed": c.passed, "detail": c.detail} for c in self.checks},
            findings_json=self.findings,
        )


# tolerance: >0.5% median-relative drift in close/adj_close on a NON-split day is odd
_ADJ_DRIFT_TOL = 0.005
_MISSING_SESSION_TOL_PCT = 2.0  # allow up to 2% missing sessions (holidays vendors skip, halts)


def validate_daily(
    session: Session,
    symbols: list[str],
    *,
    source: str,
    persist: bool = True,
) -> ValidationResult:
    res = ValidationResult(provider=source, symbols=list(symbols))
    today = date.today()

    rows_by_sym: dict[str, list[OHLCVDaily]] = defaultdict(list)
    for sym in symbols:
        inst = session.scalar(select(Instrument).where(Instrument.symbol == sym))
        if inst is None:
            res.findings.append(f"{sym}: no instrument row")
            continue
        rows_by_sym[sym] = list(
            session.scalars(
                select(OHLCVDaily)
                .where(OHLCVDaily.instrument_id == inst.id, OHLCVDaily.source == source)
                .order_by(OHLCVDaily.session_date)
            )
        )

    covered = [s for s in symbols if rows_by_sym.get(s)]
    res.checks.append(
        Check(
            "symbol_coverage",
            passed=len(covered) == len(symbols),
            detail=f"{len(covered)}/{len(symbols)} symbols have {source} data"
            + (
                f"; missing: {sorted(set(symbols) - set(covered))}"
                if len(covered) != len(symbols)
                else ""
            ),
        )
    )

    # --- per-symbol coverage summary ---
    for sym in covered:
        rows = rows_by_sym[sym]
        res.coverage[sym] = {
            "first": rows[0].session_date.isoformat(),
            "last": rows[-1].session_date.isoformat(),
            "n_bars": len(rows),
        }

    # --- chronological continuity + duplicates (per symbol) ---
    disorder, dupes = [], []
    for sym in covered:
        ds = [r.session_date for r in rows_by_sym[sym]]
        if any(b <= a for a, b in pairwise(ds)):
            disorder.append(sym)
        if len(ds) != len(set(ds)):
            dupes.append(sym)
    res.checks.append(
        Check("chronological_order", not disorder, f"out-of-order/dup dates: {disorder or 'none'}")
    )
    res.checks.append(
        Check("no_duplicate_sessions", not dupes, f"duplicate session dates: {dupes or 'none'}")
    )

    # DB-level duplicate guard (unique constraint should make this impossible)
    dup_count = session.scalar(
        select(func.count()).select_from(
            select(OHLCVDaily.instrument_id, OHLCVDaily.session_date, OHLCVDaily.source)
            .where(OHLCVDaily.source == source)
            .group_by(OHLCVDaily.instrument_id, OHLCVDaily.session_date, OHLCVDaily.source)
            .having(func.count() > 1)
            .subquery()
        )
    )
    res.checks.append(
        Check(
            "db_unique_bars",
            (dup_count or 0) == 0,
            f"{dup_count} (instrument,date,source) groups have >1 row",
        )
    )

    # --- missing sessions vs XNYS calendar ---
    missing_detail = []
    for sym in covered:
        rows = rows_by_sym[sym]
        have = {r.session_date for r in rows}
        expected = set(sessions(rows[0].session_date, min(rows[-1].session_date, today)))
        miss = sorted(expected - have)
        pct = 100.0 * len(miss) / max(len(expected), 1)
        if pct > _MISSING_SESSION_TOL_PCT:
            missing_detail.append(f"{sym}: {len(miss)} missing ({pct:.1f}%) e.g. {miss[:3]}")
    res.checks.append(
        Check(
            "session_completeness",
            not missing_detail,
            "; ".join(missing_detail) or "within tolerance",
        )
    )

    # --- OHLCV sanity ---
    bad_ohlcv = []
    for sym in covered:
        n_bad = sum(
            1
            for r in rows_by_sym[sym]
            if min(r.open, r.high, r.low, r.close) <= 0
            or r.volume < 0
            or r.high < max(r.open, r.close)
            or r.low > min(r.open, r.close)
            or r.high < r.low
        )
        if n_bad:
            bad_ohlcv.append(f"{sym}:{n_bad}")
    res.checks.append(
        Check("ohlcv_sanity", not bad_ohlcv, f"rows failing OHLC relations: {bad_ohlcv or 'none'}")
    )

    # --- split/dividend adjustment behaviour ---
    adj_findings = []
    for sym in covered:
        rows = rows_by_sym[sym]
        with_adj = [r for r in rows if r.adj_close is not None and r.close]
        if not with_adj:
            adj_findings.append(f"{sym}: no adj_close on any row")
            continue
        ratios = [r.adj_close / r.close for r in with_adj]  # type: ignore[operator]
        # ratio should be <= ~1 and change only at split/div dates (few jumps)
        jumps = sum(
            1 for a, b in pairwise(ratios) if abs(b - a) / max(abs(a), 1e-9) > _ADJ_DRIFT_TOL
        )
        if max(ratios) > 1.02:
            adj_findings.append(f"{sym}: adj_close exceeds close (ratio max {max(ratios):.3f})")
        # a huge number of jumps means adj_close is noisy / not a clean back-adjustment
        if jumps > max(12, len(ratios) // 40):
            adj_findings.append(
                f"{sym}: {jumps} adj-ratio jumps (> expected corporate-action count)"
            )
    res.checks.append(
        Check(
            "adjustment_behaviour",
            not adj_findings,
            "; ".join(adj_findings) or "clean back-adjustment",
        )
    )

    # --- timezone / date consistency ---
    tz_bad = []
    for sym in covered:
        rows = rows_by_sym[sym]
        if any(r.session_date > today for r in rows):
            tz_bad.append(f"{sym}: future-dated bar")
        ing = [r.ingested_at for r in rows if r.ingested_at is not None]
        if ing and any(t.tzinfo is None for t in ing):
            tz_bad.append(f"{sym}: naive ingested_at timestamp")
    res.checks.append(
        Check(
            "timezone_consistency",
            not tz_bad,
            "; ".join(tz_bad) or "session_date tz-naive dates, ingested_at UTC-aware",
        )
    )

    if persist:
        session.add(res.to_row())
        session.flush()
    return res


def latest_validation(session: Session, source: str) -> DataValidationReport | None:
    return session.scalar(
        select(DataValidationReport)
        .where(DataValidationReport.provider == source)
        .order_by(DataValidationReport.ran_at.desc())
        .limit(1)
    )


def _utcnow_iso() -> str:
    return datetime.now(UTC).isoformat()


_OPTION_AGG_SOURCE = "massive_options"


def validate_option_aggregates(
    session: Session,
    underlyings: list[str],
    *,
    source: str = _OPTION_AGG_SOURCE,
    start: date | None = None,
    end: date | None = None,
    caps: object | None = None,
    persist: bool = True,
) -> ValidationResult:
    """Data-quality validation over ``option_aggregate_daily`` for a backfill.

    Independent of the ingester (which only drops post-expiry and malformed
    rows), so these checks bite on real vendor data: chronological continuity,
    duplicate bars, OHLC sanity, no bar past a contract's expiration, every
    session is an XNYS trading day, every row labelled ``HISTORICAL`` (never
    live/delayed), the window is respected, and the per-underlying / total-bar
    caps were honoured.
    """
    syms = [u.upper() for u in underlyings]
    res = ValidationResult(provider=f"{source}_agg", symbols=syms)

    rows = list(
        session.execute(
            select(
                OptionAggregateDaily.option_ticker,
                OptionAggregateDaily.underlying_symbol,
                OptionAggregateDaily.session_date,
                OptionAggregateDaily.open,
                OptionAggregateDaily.high,
                OptionAggregateDaily.low,
                OptionAggregateDaily.close,
                OptionAggregateDaily.volume,
                OptionAggregateDaily.latency_category,
            ).where(
                OptionAggregateDaily.source == source,
                OptionAggregateDaily.underlying_symbol.in_(syms),
            )
            # order by id (insertion order), NOT session_date — the whole point
            # of the chronological_order check below is to catch dates arriving
            # out of order, which a session_date ORDER BY would silently mask.
            .order_by(OptionAggregateDaily.option_ticker, OptionAggregateDaily.id)
        )
    )
    res.coverage = {
        "rows": {"count": len(rows)},
        "contracts": {"count": len({r[0] for r in rows})},
        "underlyings": {"present": sorted({r[1] for r in rows})},
    }
    if not rows:
        res.checks.append(
            Check("has_rows", False, "no option_aggregate_daily rows for these underlyings")
        )
        if persist:
            session.add(res.to_row())
            session.flush()
        return res

    # 1. chronological continuity, per contract, in the order bars actually
    # arrived (insertion order — see the ORDER BY note above). A literal
    # duplicate (ticker, date) pair cannot occur here: it's excluded by the
    # UNIQUE(option_ticker, session_date, source) constraint and re-verified
    # independently by no_duplicate_bars below.
    by_ticker: dict[str, list[date]] = defaultdict(list)
    for r in rows:
        by_ticker[r[0]].append(r[2])
    disordered = [t for t, ds in by_ticker.items() if ds != sorted(ds)]
    res.checks.append(
        Check(
            "chronological_order",
            not disordered,
            f"contracts with bars inserted out of date order: {disordered[:5] or 'none'}",
        )
    )

    # 2. DB-level uniqueness on (option_ticker, session_date, source)
    distinct_keys = session.scalar(
        select(func.count()).select_from(
            select(OptionAggregateDaily.option_ticker, OptionAggregateDaily.session_date)
            .where(OptionAggregateDaily.source == source)
            .distinct()
            .subquery()
        )
    )
    total = session.scalar(
        select(func.count())
        .select_from(OptionAggregateDaily)
        .where(OptionAggregateDaily.source == source)
    )
    res.checks.append(
        Check(
            "no_duplicate_bars",
            distinct_keys == total,
            f"{total} rows, {distinct_keys} distinct keys",
        )
    )

    # 3. OHLC sanity — all four prices must be positive, not just open
    bad_ohlc = [
        f"{r[0]}@{r[2]}"
        for r in rows
        if not (r[5] <= r[3] <= r[4] and r[5] <= r[6] <= r[4] and r[5] <= r[4])
        or min(r[3], r[4], r[5], r[6]) <= 0
        or r[7] < 0
    ]
    res.checks.append(
        Check(
            "ohlcv_sanity", not bad_ohlc, f"rows failing OHLC relations: {bad_ohlc[:5] or 'none'}"
        )
    )

    # 4. no bar dated after the contract's own expiration
    exp_by_ticker: dict[str, date] = {
        str(t): e
        for t, e in session.execute(
            select(OptionContract.option_ticker, OptionContract.expiration_date).where(
                OptionContract.option_ticker.in_(list(by_ticker))
            )
        ).all()
    }
    post_expiry = [
        f"{t}>{exp_by_ticker[t]}"
        for t, ds in by_ticker.items()
        if t in exp_by_ticker and max(ds) > exp_by_ticker[t]
    ]
    res.checks.append(
        Check("no_post_expiry_bars", not post_expiry, f"post-expiry: {post_expiry[:5] or 'none'}")
    )

    # 5. every session_date is an XNYS trading day
    lo = start or min(r[2] for r in rows)
    hi = end or max(r[2] for r in rows)
    trading = set(sessions(lo, hi))
    non_trading = sorted({r[2].isoformat() for r in rows if r[2] not in trading})
    res.checks.append(
        Check(
            "sessions_are_trading_days",
            not non_trading,
            f"non-trading-day bars: {non_trading[:5] or 'none'}",
        )
    )

    # 6. latency label — must be HISTORICAL, never live/delayed
    bad_latency = sorted({str(r[8]) for r in rows if r[8] is not LatencyCategory.HISTORICAL})
    res.checks.append(
        Check(
            "latency_labelled_historical",
            not bad_latency,
            f"non-HISTORICAL latency labels: {bad_latency or 'none'}",
        )
    )

    # 7. window respected
    out_of_window = [
        r[2].isoformat() for r in rows if (start and r[2] < start) or (end and r[2] > end)
    ]
    res.checks.append(
        Check(
            "within_window", not out_of_window, f"out-of-window bars: {out_of_window[:5] or 'none'}"
        )
    )

    # 8. caps honoured (per-underlying contract count + total bars)
    if caps is not None:
        max_contracts = int(getattr(caps, "contracts_per_underlying", 10**9))
        max_bars = int(getattr(caps, "max_total_bars", 10**18))
        per_u: dict[str, set[str]] = defaultdict(set)
        for r in rows:
            per_u[r[1]].add(r[0])
        over = {u: len(cs) for u, cs in per_u.items() if len(cs) > max_contracts}
        res.checks.append(
            Check(
                "caps_respected",
                not over and len(rows) <= max_bars,
                f"per-underlying over cap: {over or 'none'}; total bars {len(rows)} <= {max_bars}",
            )
        )

    if persist:
        session.add(res.to_row())
        session.flush()
    return res
