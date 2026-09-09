"""Eligibility screen over the bulk archive — exact, per-symbol exclusion
reasons and stage counts. Pure computation on already-archived data; the
only network-free step of the pipeline."""

from __future__ import annotations

import hashlib
import statistics
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from signalforge.config.research import UniversePipelineConfig
from signalforge.db.models import (
    BulkFile,
    SymbolContinuityMapping,
    UniverseMember,
    UniverseScreenRun,
    UniverseTicker,
)
from signalforge.observability import get_logger
from signalforge.research.promotion import get_or_create_dataset_snapshot
from signalforge.universe.bulk import DEFAULT_SOURCE, load_bulk_rows

_log = get_logger("universe.screen")

# Exclusion reasons (stable strings — they are persisted and reported)
R_TYPE = "security_type_out_of_scope"
R_INACTIVE = "inactive_listing"
R_NO_DATA = "no_bulk_data"
R_PRICE = "price_below_min"
R_ADV = "adv_dollar_volume_below_min"
R_CAP = "market_cap_below_min"
R_HISTORY = "insufficient_history"
R_LISTING = "listing_too_recent"
R_QUALITY = "data_quality"
R_CONTINUITY = "corporate_action_continuity"
R_SECTOR = "sector_concentration"
# Flags (informational, never excluding)
F_CAP_UNKNOWN = "market_cap_unavailable"
F_SPREAD = "spread_filter_not_licensed"
F_HISTORY_PARTIAL = "history_partially_verified"


@dataclass(slots=True)
class SymbolMetrics:
    ticker: str
    closes: list[tuple[date, float]] = field(default_factory=list)
    dollar_volumes: list[float] = field(default_factory=list)
    zero_volume_days: int = 0


@dataclass(slots=True)
class ScreenReport:
    run_id: int
    screen_date: date
    sessions_used: int
    discovered: int
    in_scope: int
    excluded_by_reason: dict[str, int]
    eligible: int
    eligible_symbols: list[str]
    flags: dict[str, int]
    dataset_snapshot_id: int | None
    seconds: float


def _metrics_from_archive(files: list[BulkFile]) -> tuple[dict[str, SymbolMetrics], list[date]]:
    """Parse the archived sessions (oldest -> newest) into per-symbol series."""
    per: dict[str, SymbolMetrics] = {}
    dates: list[date] = []
    for bf in sorted(files, key=lambda b: b.session_date):
        dates.append(bf.session_date)
        for r in load_bulk_rows(bf):
            tk = str(r.get("T") or "").upper()
            if not tk:
                continue
            close = r.get("c")
            if not isinstance(close, (int, float)) or close <= 0:
                continue
            vol_raw = r.get("v")
            vol = float(vol_raw) if isinstance(vol_raw, (int, float)) else 0.0
            vw_raw = r.get("vw")
            vw = float(vw_raw) if isinstance(vw_raw, (int, float)) and vw_raw > 0 else float(close)
            m = per.setdefault(tk, SymbolMetrics(tk))
            m.closes.append((bf.session_date, float(close)))
            m.dollar_volumes.append(vol * vw)
            if vol <= 0:
                m.zero_volume_days += 1
    return per, dates


def _quality_ok(m: SymbolMetrics, cfg: UniversePipelineConfig) -> bool:
    if m.closes and m.zero_volume_days / len(m.closes) > cfg.max_zero_volume_share:
        return False
    prev: float | None = None
    for _, c in m.closes:
        if prev and abs(c / prev - 1.0) > cfg.max_abs_daily_return:
            return False
        prev = c
    return True


def run_screen(
    session: Session,
    cfg: UniversePipelineConfig,
    *,
    source: str = DEFAULT_SOURCE,
    now: datetime | None = None,
) -> ScreenReport:
    t0 = time.monotonic()
    now = now or datetime.now(UTC)
    files = list(
        session.scalars(
            select(BulkFile)
            .where(BulkFile.source == source, BulkFile.status == "ok")
            .order_by(BulkFile.session_date.desc())
            .limit(cfg.backfill_sessions)
        )
    )
    if not files:
        raise ValueError("no archived bulk sessions — run the backfill first")
    per, dates = _metrics_from_archive(files)
    screen_date = max(dates)
    sessions_used = len(dates)

    tickers = list(session.scalars(select(UniverseTicker)))
    discovered = len(tickers)
    continuity: set[str] = set()
    for cm in session.scalars(select(SymbolContinuityMapping)):
        for sym in (cm.old_symbol, cm.new_symbol, cm.derived_symbol):
            if sym:
                continuity.add(str(sym).upper())

    run = UniverseScreenRun(
        screen_date=screen_date,
        started_at=now,
        status="running",
        config_json=cfg.model_dump(mode="json"),
        sessions_used=sessions_used,
        archive_first=min(dates),
        archive_last=screen_date,
        discovered=discovered,
    )
    session.add(run)
    session.flush()

    excluded: dict[str, int] = defaultdict(int)
    flags_count: dict[str, int] = defaultdict(int)
    members: list[UniverseMember] = []
    survivors: list[tuple[UniverseTicker, float, str]] = []  # (ticker row, adv, sic group)
    in_scope = 0
    history_required = min(cfg.min_history_sessions, sessions_used)
    if sessions_used < cfg.min_history_sessions:
        flags_count[F_HISTORY_PARTIAL] += 1  # run-level flag

    for t in tickers:
        reasons: list[str] = []
        flags: list[str] = [F_SPREAD]
        if t.security_type not in cfg.security_types or t.locale != "us":
            excluded[R_TYPE] += 1
            continue  # out-of-scope types are counted, not persisted per symbol
        if not t.active:
            excluded[R_INACTIVE] += 1
            continue
        in_scope += 1
        m = per.get(t.ticker)
        last_close = m.closes[-1][1] if m and m.closes else None
        adv = (
            statistics.mean(m.dollar_volumes[-cfg.adv_sessions :])
            if m and m.dollar_volumes
            else None
        )
        present = len(m.closes) if m else 0
        sic_group = (t.sic_code or "")[:2]

        if m is None:
            reasons.append(R_NO_DATA)
        else:
            if last_close is not None and last_close < cfg.min_price:
                reasons.append(R_PRICE)
            if adv is not None and adv < cfg.min_avg_dollar_volume:
                reasons.append(R_ADV)
            if t.security_type == "CS":
                if t.market_cap is None:
                    flags.append(F_CAP_UNKNOWN)
                elif t.market_cap < cfg.min_market_cap:
                    reasons.append(R_CAP)
            if present < history_required * cfg.min_session_coverage:
                reasons.append(R_HISTORY)
            if t.list_date and (now.date() - t.list_date) < timedelta(
                days=cfg.min_listing_age_days
            ):
                reasons.append(R_LISTING)
            if not _quality_ok(m, cfg):
                reasons.append(R_QUALITY)
        if t.ticker in continuity:
            reasons.append(R_CONTINUITY)
        if sessions_used < cfg.min_history_sessions:
            flags.append(F_HISTORY_PARTIAL)

        for r in reasons:
            excluded[r] += 1
        for f in flags:
            flags_count[f] += 1
        members.append(
            UniverseMember(
                run_id=run.id,
                ticker=t.ticker,
                security_type=t.security_type,
                last_close=last_close,
                avg_dollar_volume=adv,
                market_cap=t.market_cap,
                sessions_present=present,
                sic_group=sic_group,
                eligible=not reasons,
                exclusion_reasons=reasons,
                flags=flags,
            )
        )
        if not reasons:
            survivors.append((t, adv or 0.0, sic_group))

    # sector concentration: no 2-digit SIC group may exceed max_sector_share of
    # the eligible set (ETFs have no SIC and are exempt) — drop lowest-ADV first.
    cs_survivors = [s for s in survivors if s[0].security_type == "CS" and s[2]]
    cap = int(len(survivors) * cfg.max_sector_share)
    by_group: dict[str, list[tuple[UniverseTicker, float, str]]] = defaultdict(list)
    for s in cs_survivors:
        by_group[s[2]].append(s)
    dropped: set[str] = set()
    for _grp, rows in by_group.items():
        if len(rows) > cap > 0:
            rows.sort(key=lambda s: s[1])
            for t, _adv, _g in rows[: len(rows) - cap]:
                dropped.add(t.ticker)
    if dropped:
        for mem in members:
            if mem.ticker in dropped:
                mem.eligible = False
                mem.exclusion_reasons = [*mem.exclusion_reasons, R_SECTOR]
        excluded[R_SECTOR] += len(dropped)

    session.add_all(members)
    eligible_symbols = sorted(mem.ticker for mem in members if mem.eligible)
    digest = hashlib.sha256(",".join(eligible_symbols).encode()).hexdigest()[:8]
    snap = get_or_create_dataset_snapshot(
        session,
        key=f"liquid_us_{screen_date.isoformat()}_{digest}",
        symbols=eligible_symbols,
        description=(
            f"Liquid U.S. research universe screened on {screen_date.isoformat()} from "
            f"{sessions_used} archived grouped-daily sessions. Split-adjusted AS OF the fetch "
            "date (NOT point-in-time); discovery is active-only (NOT survivorship-free). "
            "Discovery/screening universe — never a promotion universe."
        ),
        source_note=f"{source} grouped daily; END_OF_DAY",
    )
    snap.reusable_by_new_evaluations = False
    run.in_scope_types = in_scope
    run.excluded_by_reason = dict(excluded)
    run.eligible = len(eligible_symbols)
    run.dataset_snapshot_id = snap.id
    run.status = "ok"
    run.finished_at = datetime.now(UTC)
    run.runtime_seconds = round(time.monotonic() - t0, 1)
    session.flush()
    _log.info(
        "universe.screen",
        run_id=run.id,
        discovered=discovered,
        in_scope=in_scope,
        eligible=len(eligible_symbols),
        sessions=sessions_used,
    )
    return ScreenReport(
        run_id=run.id,
        screen_date=screen_date,
        sessions_used=sessions_used,
        discovered=discovered,
        in_scope=in_scope,
        excluded_by_reason=dict(excluded),
        eligible=len(eligible_symbols),
        eligible_symbols=eligible_symbols,
        flags=dict(flags_count),
        dataset_snapshot_id=snap.id,
        seconds=run.runtime_seconds,
    )


def latest_screen(session: Session) -> UniverseScreenRun | None:
    return session.scalar(
        select(UniverseScreenRun)
        .where(UniverseScreenRun.status == "ok")
        .order_by(UniverseScreenRun.started_at.desc())
        .limit(1)
    )


def eligible_symbols_for(session: Session, run_id: int) -> list[str]:
    return list(
        session.scalars(
            select(UniverseMember.ticker)
            .where(UniverseMember.run_id == run_id, UniverseMember.eligible.is_(True))
            .order_by(UniverseMember.ticker)
        )
    )


def exclusion_examples(session: Session, run_id: int, *, limit: int = 5) -> dict[str, list[str]]:
    out: dict[str, list[str]] = defaultdict(list)
    for mem in session.scalars(
        select(UniverseMember).where(
            UniverseMember.run_id == run_id, UniverseMember.eligible.is_(False)
        )
    ):
        for r in mem.exclusion_reasons:
            if len(out[r]) < limit:
                out[r].append(mem.ticker)
    return dict(out)


def snapshot_summary(run: UniverseScreenRun) -> dict[str, Any]:
    return {
        "run_id": run.id,
        "screen_date": run.screen_date.isoformat(),
        "sessions_used": run.sessions_used,
        "archive": f"{run.archive_first}..{run.archive_last}",
        "discovered": run.discovered,
        "in_scope_types": run.in_scope_types,
        "excluded_by_reason": run.excluded_by_reason,
        "eligible": run.eligible,
        "dataset_snapshot_id": run.dataset_snapshot_id,
        "adjustment_basis": run.adjustment_basis,
        "survivorship_note": run.survivorship_note,
        "runtime_seconds": run.runtime_seconds,
    }
