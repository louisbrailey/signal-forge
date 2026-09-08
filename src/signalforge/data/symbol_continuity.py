"""Explicit, versioned, auditable symbol continuity across a corporate action
that changes a ticker (and/or company name) — e.g. FB -> META on 2022-06-09.

Two hard rules, both enforced structurally, not by convention:

1. This module NEVER mutates ``old_symbol``'s or ``new_symbol``'s own
   ``Instrument``/``OHLCVDaily`` rows. Backfilling the predecessor symbol's
   history goes through the normal :func:`signalforge.data.ingest.ingest_symbol`
   path, into its OWN instrument — the successor symbol's already-ingested
   bars are read, never written.
2. A bridged series is materialized ONLY when :func:`build_and_validate_mapping`
   found ``validation_status == "verified"`` — and even then, into a NEW,
   separately-labelled derived instrument (``mapping.derived_symbol``), never
   by rewriting bars under ``new_symbol`` itself. If validation fails, no
   bridge is created; the caller (the promotion pipeline / CLI) is expected to
   exclude the affected symbol from any backtest or evaluation rather than
   silently trade a two-headed series.

Every mapping is immutable once persisted: re-running validation inserts a
new, higher ``version`` row for the same ``(old_symbol, new_symbol)`` pair —
it never edits or deletes a prior one, so every past evaluation stays
traceable to the exact mapping (and its exact evidence) it used.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from signalforge import audit
from signalforge.data.adapters.base import MarketDataAdapter
from signalforge.data.calendar import sessions as nyse_sessions
from signalforge.data.ingest import SymbolIngestResult, ingest_symbol
from signalforge.data.repository import get_daily_bars, get_or_create_instrument
from signalforge.db.models import Instrument, OHLCVDaily, SymbolContinuityMapping
from signalforge.db.types import utcnow
from signalforge.observability import get_logger

_log = get_logger("data.symbol_continuity")

# A same-session close(old) -> open(new) move beyond this is suspicious
# enough that continuity cannot be verified without an explicit, sourced
# split/reverse-split ratio — plain 1:1 continuity does not cover it.
MAX_UNEXPLAINED_JUMP_PCT = 15.0


def backfill_predecessor_symbol(
    session: Session,
    adapter: MarketDataAdapter,
    old_symbol: str,
    start: date,
    end: date,
) -> SymbolIngestResult:
    """Ingest ``old_symbol``'s own history through the normal ingestion path
    (same bar caps, quality flags, dedup, and source tagging as every other
    symbol). Writes only to ``old_symbol``'s own instrument."""
    return ingest_symbol(session, adapter, old_symbol, start, end)


@dataclass(slots=True)
class ContinuityCheck:
    name: str
    passed: bool
    detail: str


@dataclass(slots=True)
class ContinuityValidation:
    passed: bool
    checks: list[ContinuityCheck] = field(default_factory=list)
    # non-gating disclosures — facts worth surfacing even though they do not
    # by themselves block the bridge (e.g. contaminating data the bridge
    # simply excludes rather than uses).
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "checks": [
                {"name": c.name, "passed": c.passed, "detail": c.detail} for c in self.checks
            ],
            "diagnostics": self.diagnostics,
        }


def _validate_seam(
    *,
    old_symbol: str,
    new_symbol: str,
    old_bars: list[OHLCVDaily],
    new_bars: list[OHLCVDaily],
    source: str,
    old_sources_all: set[str],
    new_sources_all: set[str],
) -> ContinuityValidation:
    """Validate sessions, prices, volume, split adjustment, dates, duplicate
    prevention, and source provenance around the seam between the two legs.

    ``new_bars`` must already be scoped to sessions strictly after
    ``old_bars[-1]`` — see :func:`build_and_validate_mapping`, which is the
    only intended caller and does that scoping (and separately discloses any
    ``new_symbol`` bars found *before* that point, e.g. a ticker held by an
    unrelated prior entity, as a diagnostic rather than folding it into this
    function's own duplicate check).

    ``old_sources_all``/``new_sources_all`` must be the set of EVERY distinct
    ``source`` tag either symbol has *anywhere* in its history — unfiltered,
    not the ``source``-filtered ``old_bars``/``new_bars``. Checking provenance
    against the same filter used to fetch the bars would be tautologically
    true by construction and could never catch a real mismatch."""
    checks: list[ContinuityCheck] = []
    old_last, new_first = old_bars[-1], new_bars[0]

    # --- duplicate prevention / chronological ordering: no session_date
    # appears on both sides, and old ends strictly before new begins.
    old_dates = {b.session_date for b in old_bars}
    new_dates = {b.session_date for b in new_bars}
    dupes = sorted(old_dates & new_dates)
    ordered = old_last.session_date < new_first.session_date and not dupes
    checks.append(
        ContinuityCheck(
            "dates_ordered_no_duplicates",
            ordered,
            (
                f"last {old_symbol} session {old_last.session_date} < first {new_symbol} "
                f"session {new_first.session_date}, zero overlapping dates"
                if ordered
                else f"overlap/misorder: duplicate dates {dupes[:5]}, last {old_symbol} "
                f"{old_last.session_date}, first {new_symbol} {new_first.session_date}"
            ),
        )
    )

    # --- sessions: no NYSE trading session strictly between the two legs
    # that neither symbol accounts for.
    gap_sessions: tuple[date, ...] = ()
    if old_last.session_date < new_first.session_date:
        gap_lo = old_last.session_date + timedelta(days=1)
        gap_hi = new_first.session_date - timedelta(days=1)
        if gap_lo <= gap_hi:
            gap_sessions = nyse_sessions(gap_lo, gap_hi)
    checks.append(
        ContinuityCheck(
            "no_unexplained_session_gap",
            len(gap_sessions) == 0,
            (
                "no NYSE session falls strictly between the two legs"
                if not gap_sessions
                else f"{len(gap_sessions)} NYSE session(s) covered by neither symbol: "
                f"{[d.isoformat() for d in gap_sessions[:5]]}"
            ),
        )
    )

    # --- price continuity: no unexplained jump (would imply a hidden split).
    jump_pct = (
        abs(new_first.open - old_last.close) / old_last.close * 100 if old_last.close else 100.0
    )
    checks.append(
        ContinuityCheck(
            "price_continuity",
            jump_pct <= MAX_UNEXPLAINED_JUMP_PCT,
            f"{old_symbol} close {old_last.close:.4f} -> {new_symbol} open {new_first.open:.4f} "
            f"({jump_pct:+.2f}% move; tolerance {MAX_UNEXPLAINED_JUMP_PCT:.0f}%)",
        )
    )

    # --- volume sanity: both sides real, non-placeholder trading.
    checks.append(
        ContinuityCheck(
            "volume_sane",
            old_last.volume > 0 and new_first.volume > 0,
            f"{old_symbol} volume {old_last.volume:,.0f}, "
            f"{new_symbol} volume {new_first.volume:,.0f}",
        )
    )

    # --- split-adjustment status: no unadjusted split lurking on either leg
    # (a real split here would need its own ratio, not plain 1:1 continuity).
    checks.append(
        ContinuityCheck(
            "split_factor_unity",
            old_last.split_factor == 1.0 and new_first.split_factor == 1.0,
            f"{old_symbol} split_factor={old_last.split_factor}, "
            f"{new_symbol} split_factor={new_first.split_factor} (need both == 1.0)",
        )
    )

    # --- source provenance: both legs have EVERY bar in their whole recorded
    # history tagged with the SAME licensed provider the caller asked to
    # validate against — not just the two boundary bars (which are already
    # guaranteed to match by the query that fetched them). A symbol carrying
    # bars from more than one provider anywhere is a genuine, independent
    # provenance red flag worth surfacing before trusting its continuity.
    extra_old = old_sources_all - {source}
    extra_new = new_sources_all - {source}
    same_source = not extra_old and not extra_new
    checks.append(
        ContinuityCheck(
            "same_source_provenance",
            same_source,
            (
                f"both {old_symbol} and {new_symbol} carry bars ONLY from {source!r} "
                "across their entire recorded history"
                if same_source
                else f"{old_symbol} also has bars from {sorted(extra_old)!r}, "
                f"{new_symbol} also has bars from {sorted(extra_new)!r} (expected only {source!r})"
            ),
        )
    )

    return ContinuityValidation(passed=all(c.passed for c in checks), checks=checks)


def build_and_validate_mapping(
    session: Session,
    *,
    old_symbol: str,
    new_symbol: str,
    source: str,
    corporate_action_type: str = "ticker_and_name_change",
    created_by: str = "symbol_continuity_investigation",
) -> SymbolContinuityMapping:
    """Determine the effective date and last predecessor session empirically
    from already-ingested bars (never from an assumed/hardcoded date),
    validate continuity around the seam, and persist a NEW versioned mapping
    row. Never edits an existing row for this ``(old_symbol, new_symbol)``
    pair — always inserts the next version.

    Raises ``ValueError`` if either symbol has no ``source``-tagged bars
    ingested yet — call :func:`backfill_predecessor_symbol` first.
    """
    old_symbol, new_symbol = old_symbol.upper(), new_symbol.upper()
    old_inst = session.scalar(select(Instrument).where(Instrument.symbol == old_symbol))
    new_inst = session.scalar(select(Instrument).where(Instrument.symbol == new_symbol))
    if old_inst is None or new_inst is None:
        raise ValueError(f"both {old_symbol} and {new_symbol} must be ingested before mapping")

    old_bars = get_daily_bars(session, old_symbol, date(1990, 1, 1), date.today(), source=source)
    new_bars_all = get_daily_bars(
        session, new_symbol, date(1990, 1, 1), date.today(), source=source
    )
    if not old_bars:
        raise ValueError(f"no {source!r}-sourced bars ingested for {old_symbol}")
    if not new_bars_all:
        raise ValueError(f"no {source!r}-sourced bars ingested for {new_symbol}")

    # Unfiltered (every source, not just `source`) — used only by the
    # same_source_provenance check below, which would otherwise be
    # tautologically true against the already-`source`-filtered bars above.
    old_sources_all = {
        b.source for b in get_daily_bars(session, old_symbol, date(1990, 1, 1), date.today())
    }
    new_sources_all = {
        b.source for b in get_daily_bars(session, new_symbol, date(1990, 1, 1), date.today())
    }

    # Scope the "new" leg to sessions strictly AFTER old_symbol's own last
    # session. This must NOT simply be new_bars_all[0]: if new_symbol was
    # itself already ingested for a range that starts before old_symbol's
    # last session (e.g. a different entity held that ticker earlier, or an
    # overly-wide ingest window), the globally-earliest new_symbol bar is not
    # the corporate action's effective date at all.
    old_last_date = old_bars[-1].session_date
    new_bars_after = [b for b in new_bars_all if b.session_date > old_last_date]
    contaminating_bars = [b for b in new_bars_all if b.session_date <= old_last_date]
    if not new_bars_after:
        raise ValueError(
            f"{new_symbol} has no bars after {old_symbol}'s last session {old_last_date} — "
            "nothing to bridge to"
        )

    validation = _validate_seam(
        old_symbol=old_symbol,
        new_symbol=new_symbol,
        old_bars=old_bars,
        new_bars=new_bars_after,
        source=source,
        old_sources_all=old_sources_all,
        new_sources_all=new_sources_all,
    )
    validation.diagnostics["pre_transition_contamination"] = (
        {
            "found": True,
            "n_bars": len(contaminating_bars),
            "first_date": contaminating_bars[0].session_date.isoformat(),
            "last_date": contaminating_bars[-1].session_date.isoformat(),
            "note": (
                f"{len(contaminating_bars)} bar(s) exist under {new_symbol} dated on/before "
                f"{old_symbol}'s last session ({old_last_date}) — evidence the {new_symbol} "
                f"ticker was held by a different, unrelated entity before this corporate "
                f"action. EXCLUDED from the bridge, which uses only {new_symbol} bars "
                f"strictly after {old_last_date}. Those raw bars remain in {new_symbol}'s own "
                "instrument, untouched — the derived/bridged instrument never includes them."
            ),
        }
        if contaminating_bars
        else {
            "found": False,
            "note": f"no {new_symbol} bars exist before {old_symbol}'s last session — clean",
        }
    )

    next_version = (
        session.scalar(
            select(func.max(SymbolContinuityMapping.version)).where(
                SymbolContinuityMapping.old_symbol == old_symbol,
                SymbolContinuityMapping.new_symbol == new_symbol,
            )
        )
        or 0
    ) + 1

    verified = validation.passed
    derived_symbol = _derived_symbol_name(new_symbol) if verified else ""
    row = SymbolContinuityMapping(
        old_symbol=old_symbol,
        new_symbol=new_symbol,
        version=next_version,
        corporate_action_type=corporate_action_type,
        effective_date=new_bars_after[0].session_date,
        last_old_session=old_bars[-1].session_date,
        ratio=1.0,
        source=source,
        adjustment_status=(
            "unadjusted 1:1 continuity verified from licensed source data — no split ratio applied"
            if verified
            else "validation FAILED — no bridge materialized; symbols must be treated as separate "
            "(or the new symbol excluded) rather than silently blended"
        ),
        validation_status="verified" if verified else "failed",
        validation_evidence_json=validation.to_dict(),
        derived_symbol=derived_symbol,
        notes=(
            f"{old_symbol} last close {old_bars[-1].close} on {old_bars[-1].session_date} -> "
            f"{new_symbol} first open {new_bars_after[0].open} on {new_bars_after[0].session_date}"
            + (
                f"; {len(contaminating_bars)} pre-transition {new_symbol} bar(s) excluded "
                f"({contaminating_bars[0].session_date}..{contaminating_bars[-1].session_date})"
                if contaminating_bars
                else ""
            )
        ),
        created_by=created_by,
    )
    session.add(row)
    session.flush()
    audit.record(
        "symbol_continuity.mapping_created",
        actor=created_by,
        entity=f"{old_symbol}->{new_symbol} v{next_version}",
        validation_status=row.validation_status,
        evidence=validation.to_dict(),
    )
    _log.warning(
        "symbol_continuity.mapping_created",
        old_symbol=old_symbol,
        new_symbol=new_symbol,
        version=next_version,
        validation_status=row.validation_status,
    )
    return row


def _derived_symbol_name(new_symbol: str) -> str:
    name = f"{new_symbol}_CONT"
    if len(name) > 16:  # Instrument.symbol is String(16)
        raise ValueError(f"derived symbol {name!r} exceeds the 16-character column limit")
    return name


def materialize_continuous_series(
    session: Session, mapping: SymbolContinuityMapping
) -> tuple[Instrument, int]:
    """Build the derived bridge instrument's bars from the two verified legs.

    Only callable on a ``validation_status == "verified"`` mapping. Copies
    bars — never mutates ``old_symbol``'s or ``new_symbol``'s own rows —
    tagging every derived bar's ``source`` with this exact mapping id and
    version so it is traceable back to the evidence that authorized it.
    Idempotent per mapping: if the derived instrument already carries bars
    tagged for this mapping, returns immediately without rewriting them (the
    bridge, once built for a given mapping version, is itself immutable).

    Refuses (raises ``ValueError``) if the derived symbol already carries
    bars from a DIFFERENT mapping version — ``_derived_symbol_name`` has no
    version component, so silently materializing a second version onto the
    same derived instrument would duplicate every bridged session date under
    one symbol. Superseding an already-materialized bridge is a deliberate
    decision this function will not make on a caller's behalf.

    Returns ``(derived_instrument, bars_written)`` — ``bars_written == 0``
    means it was already materialized (for THIS mapping).
    """
    if mapping.validation_status != "verified":
        raise ValueError(
            f"mapping {mapping.old_symbol}->{mapping.new_symbol} v{mapping.version} is "
            f"{mapping.validation_status!r}, not 'verified' — refusing to materialize a bridge"
        )
    if not mapping.derived_symbol:
        raise ValueError("verified mapping is missing derived_symbol")

    tag = f"continuity_bridge:{mapping.id}"
    derived_inst = get_or_create_instrument(
        session,
        mapping.derived_symbol,
        name=(
            f"{mapping.new_symbol} continuity-bridged with {mapping.old_symbol} "
            f"(mapping v{mapping.version})"
        ),
    )

    existing_any = get_daily_bars(session, mapping.derived_symbol, date(1990, 1, 1), date.today())
    already_this_mapping = [b for b in existing_any if b.source == tag]
    if already_this_mapping:
        return derived_inst, 0
    other_tags = {b.source for b in existing_any if b.source != tag}
    if other_tags:
        raise ValueError(
            f"derived symbol {mapping.derived_symbol!r} already holds bars from a different "
            f"mapping ({sorted(other_tags)!r}) — materializing {mapping.old_symbol}->"
            f"{mapping.new_symbol} v{mapping.version} ({tag!r}) onto the same derived symbol "
            "would duplicate session dates under one instrument. If this version is meant to "
            "supersede the existing one, that is a deliberate decision to make explicitly "
            "(e.g. purge the superseded bridge's bars first) — not something this function "
            "will do silently."
        )

    old_bars = get_daily_bars(
        session,
        mapping.old_symbol,
        date(1990, 1, 1),
        mapping.last_old_session,
        source=mapping.source,
    )
    new_bars = get_daily_bars(
        session, mapping.new_symbol, mapping.effective_date, date.today(), source=mapping.source
    )
    if not old_bars and not new_bars:
        # The mapping validated successfully at build time, but the source
        # data it relied on is gone (purged, re-tagged) by the time this
        # runs — never silently report a fabricated "already materialized".
        raise ValueError(
            f"no {mapping.source!r}-sourced bars found for {mapping.old_symbol} or "
            f"{mapping.new_symbol} at materialize time — the mapping validated earlier, but "
            "its source data is no longer available; refusing to report a false success"
        )

    now = utcnow()
    rows = [
        OHLCVDaily(
            instrument_id=derived_inst.id,
            session_date=b.session_date,
            open=b.open,
            high=b.high,
            low=b.low,
            close=b.close,
            volume=b.volume,
            adj_close=b.adj_close,
            split_factor=b.split_factor,
            div_cash=b.div_cash,
            is_adjusted=b.is_adjusted,
            source=tag,
            latency_category=b.latency_category,
            is_simulated=False,
            ingested_at=now,
            quality_flags=list(b.quality_flags),
        )
        for b in (*old_bars, *new_bars)
    ]
    try:
        with session.begin_nested():  # SAVEPOINT: survive a concurrent materialize race
            for row in rows:
                session.add(row)
            session.flush()
    except IntegrityError:
        # a concurrent materialize_continuous_series() for this exact mapping
        # won the race and committed first — discard this attempt and report
        # the winner's state rather than raising or double-writing.
        winner = get_daily_bars(
            session, mapping.derived_symbol, date(1990, 1, 1), date.today(), source=tag
        )
        if winner:
            return derived_inst, 0
        raise
    written = len(rows)
    audit.record(
        "symbol_continuity.materialized",
        actor="symbol_continuity_investigation",
        entity=mapping.derived_symbol,
        mapping_id=mapping.id,
        mapping_version=mapping.version,
        bars_written=written,
    )
    _log.warning(
        "symbol_continuity.materialized",
        derived_symbol=mapping.derived_symbol,
        mapping_id=mapping.id,
        bars_written=written,
    )
    return derived_inst, written


def latest_mapping(
    session: Session, old_symbol: str, new_symbol: str
) -> SymbolContinuityMapping | None:
    """The highest-version mapping row for this pair, or ``None``."""
    return session.scalar(
        select(SymbolContinuityMapping)
        .where(
            SymbolContinuityMapping.old_symbol == old_symbol.upper(),
            SymbolContinuityMapping.new_symbol == new_symbol.upper(),
        )
        .order_by(SymbolContinuityMapping.version.desc())
        .limit(1)
    )
