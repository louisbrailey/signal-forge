"""The scheduled approved-scope scan for a supervised paper probation.

Scans, **per PAPER_APPROVED strategy version**, EXACTLY the dataset that
version's own approval was granted on — its newest passing evaluation's
``DataSnapshot`` (that snapshot's exact symbol set), with that evaluation's
single recorded source — so the resulting candidates can pass
``research.approval_scope``'s five-part scope match. Versions that share a
``(dataset snapshot, horizon, source)`` are scanned together, once.

Approval scope is per ``StrategyVersion``, not global: two approved versions
can legitimately live on two different snapshots (a 24-symbol universe and a
150-symbol one, say). Scanning one fixed dataset for everything — as this
module used to — meant a version approved on any OTHER snapshot could never
produce an in-scope candidate, and therefore never an alert or a simulated
paper trade. A routine scan of the default watchlist cannot produce
in-scope candidates either: they are blocked at alert time because they do
not match the approved scope.

Hard gates, in order — any failure blocks the affected universe and records
why (a stale or incomplete universe blocks only ITS OWN scans, never
another universe's):

1. no stale data feed (``data.feeds.feed_status_report``);
2. the last daily-bar ingestion run finished recently and did not fail for
   any of THIS universe's symbols (``_ingest_run_blocks``);
3. the approved universe actually has a completed daily bar for the latest
   session (>= 90% of symbols on the newest bar date, and that date is not
   older than five calendar days).

The ingest that feeds gate 3 is itself derived from here: ``ingest_scope``
returns the union of the configured universe and every approved universe on
the ingest source, which ``scheduler.job_ingest`` fetches. Before that the
scheduled ingest covered only ``settings.research.universe``, so a strategy
approved on a larger snapshot was blocked by gate 3 every single session — the
data it needed was never fetched (observed 2026-09-14 on snapshot 11).

Read-only research: creates ScanRun/Candidate rows only. Never an alert,
never a paper position, never options, never a brokerage call. INTRADAY is
excluded unless the operator has turned intraday operation on
(``research.intraday.operating_enabled``, default off) — the one flag every
policy surface reads, via ``research.intraday_policy``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from signalforge.config.research import ResearchConfig
from signalforge.data.feeds import feed_status_report
from signalforge.db.models import (
    AuditLog,
    DataSnapshot,
    IngestionRun,
    Instrument,
    OHLCVDaily,
    ScanRun,
    Strategy,
    StrategyVersion,
)
from signalforge.db.retry import retry_on_lock
from signalforge.domain import FeedType, Horizon, StrategyStatus
from signalforge.observability import get_logger
from signalforge.research.approval_scope import approved_scopes
from signalforge.research.candidates import persist_scan
from signalforge.research.scan import ScanResult, run_scan
from signalforge.settings_store import effective_research_config

_log = get_logger("research.approved_scope_scan")

MAX_INGEST_AGE = timedelta(hours=24)
MAX_BAR_AGE_DAYS = 5
MIN_BAR_COVERAGE = 0.90
AUDIT_COMPLETED = "approved_scope_scan.completed"
AUDIT_BLOCKED = "approved_scope_scan.blocked"


@dataclass(frozen=True, slots=True)
class ApprovedScanGroup:
    """One scan to run: every PAPER_APPROVED version that shares a horizon,
    an approved dataset snapshot, and an approved source."""

    horizon: Horizon
    dataset_snapshot_id: int
    dataset_key: str
    source: str
    symbols: tuple[str, ...]
    strategy_version_ids: tuple[int, ...]

    @property
    def universe_key(self) -> tuple[int, str]:
        """The (snapshot, source) pair the data-readiness gate applies to."""
        return (self.dataset_snapshot_id, self.source)


@dataclass(frozen=True, slots=True)
class ApprovedUniverse:
    """One distinct approved (dataset snapshot, source) pair — the unit the
    data-readiness and daily-bar-freshness gates are evaluated over."""

    dataset_snapshot_id: int
    dataset_key: str
    source: str
    symbols: tuple[str, ...]
    horizons: tuple[str, ...]
    strategy_version_ids: tuple[int, ...]


@dataclass(slots=True)
class ApprovedScopeScanReport:
    ran: bool
    blocked_reason: str | None = None
    horizons: list[str] = field(default_factory=list)
    # Report-level snapshot identity stays populated for the common
    # single-universe case; with more than one approved universe it is None
    # and the per-group entries in ``runs`` carry the real identities.
    dataset_snapshot_id: int | None = None
    dataset_key: str | None = None
    # Distinct symbols across every approved universe that was scanned or
    # would have been (identical to the universe size when there is one).
    n_symbols: int = 0
    live_config_hash: str | None = None
    runs: list[dict[str, Any]] = field(default_factory=list)
    # One entry per approved universe the readiness gate blocked; the other
    # universes still run.
    blocked_universes: list[dict[str, Any]] = field(default_factory=list)
    # PAPER_APPROVED versions with no usable approved scope (and why).
    skipped_versions: list[dict[str, Any]] = field(default_factory=list)

    @property
    def total_candidates(self) -> int:
        return sum(int(r["candidates"]) for r in self.runs)


def approved_horizons(session: Session, cfg: ResearchConfig | None = None) -> list[Horizon]:
    """Distinct horizons of every PAPER_APPROVED strategy, filtered by the
    intraday operating policy.

    INTRADAY is excluded unless ``research.intraday.operating_enabled`` is on —
    the same single flag every other policy surface consults
    (``research.intraday_policy``). It used to be excluded by a hard-coded
    condition here, which is why the four surfaces could disagree.

    A coarse "is there anything at all to scan?" question — the scan itself
    works from ``approved_scan_groups``, which additionally requires each
    version to carry a usable approved scope."""
    from signalforge.research.intraday_policy import operating_horizons

    if cfg is None:
        cfg = effective_research_config(session)
    rows = session.execute(
        select(Strategy.horizon).where(Strategy.status == StrategyStatus.PAPER_APPROVED).distinct()
    ).all()
    found = sorted({h for (h,) in rows}, key=lambda h: h.value)
    return operating_horizons(cfg, found)


def approved_scan_groups(
    session: Session, cfg: ResearchConfig | None = None
) -> tuple[list[ApprovedScanGroup], list[dict[str, Any]]]:
    """Every scan the approved-scope scan should run, plus the PAPER_APPROVED
    versions it must skip and why.

    One group per ``(dataset_snapshot_id, horizon, source)``: the versions in
    a group are scanned together because a single ``run_scan`` over that
    snapshot's exact symbol set, from that source, produces candidates that
    are in scope for all of them. The source is part of the key because
    ``scan_scope_matches`` demands the scan's source equal the approval's
    single source — two approvals on the same snapshot from different
    sources genuinely need two scans.

    Only the NEWEST approved scope of each version counts (``approved_scopes``
    returns them newest-first): an older evaluation on a superseded dataset
    must not keep pulling a scan onto stale data.

    A version is skipped — never silently scanned on someone else's data —
    when its newest scope cannot produce an in-scope candidate at all:
    no passing evaluation, no dataset snapshot, a snapshot row that no
    longer exists or is empty, no single source, or a recorded universe that
    disagrees with the snapshot's own symbols.

    Which horizons may be acted on at all is the intraday operating policy's
    answer, not a hard-coded one here (``research.intraday_policy``): with
    ``research.intraday.operating_enabled`` off — the default — an INTRADAY
    version is out of scope and produces no group.
    """
    from signalforge.research.intraday_policy import operating_horizons

    if cfg is None:
        cfg = effective_research_config(session)
    operable = set(operating_horizons(cfg, list(Horizon)))
    rows = [
        (strat, ver)
        for strat, ver in session.execute(
            select(Strategy, StrategyVersion)
            .join(StrategyVersion, StrategyVersion.strategy_id == Strategy.id)
            .where(
                Strategy.status == StrategyStatus.PAPER_APPROVED,
                StrategyVersion.status == StrategyStatus.PAPER_APPROVED,
            )
            .order_by(StrategyVersion.id)
        ).all()
        if strat.horizon in operable
    ]

    grouped: dict[tuple[int, Horizon, str], dict[str, Any]] = {}
    skipped: list[dict[str, Any]] = []

    def _skip(strat: Strategy, ver: StrategyVersion, reason: str) -> None:
        skipped.append(
            {
                "strategy_version_id": ver.id,
                "strategy": strat.name,
                "version": ver.version,
                "reason": reason,
            }
        )

    for strat, ver in rows:
        scopes = approved_scopes(session, ver.id)
        if not scopes:
            _skip(strat, ver, "no passing promotion evaluation — nothing defines its scope")
            continue
        scope = scopes[0]  # newest passing evaluation
        if scope.dataset_snapshot_id is None:
            _skip(
                strat,
                ver,
                f"newest approved scope (evaluation {scope.evaluation_id}) has no "
                "dataset snapshot — it can never match a live scan",
            )
            continue
        if len(scope.sources) != 1:
            _skip(
                strat,
                ver,
                f"newest approved scope has {len(scope.sources)} sources "
                f"{sorted(scope.sources)} — a scan has exactly one",
            )
            continue
        source = next(iter(scope.sources))
        if not source:
            _skip(strat, ver, "newest approved scope records an empty source")
            continue
        snap = session.get(DataSnapshot, scope.dataset_snapshot_id)
        if snap is None:
            _skip(
                strat,
                ver,
                f"approved dataset snapshot {scope.dataset_snapshot_id} no longer " "exists",
            )
            continue
        symbols = [str(s) for s in (snap.symbols_json or ())]
        if not symbols:
            _skip(strat, ver, f"approved dataset snapshot {snap.id} ({snap.key!r}) has no symbols")
            continue
        if frozenset(s.upper() for s in symbols) != scope.universe:
            _skip(
                strat,
                ver,
                f"approved universe ({len(scope.universe)} symbols) disagrees with "
                f"dataset snapshot {snap.id} ({snap.key!r}, {len(symbols)} symbols)",
            )
            continue

        key = (snap.id, strat.horizon, source)
        entry = grouped.setdefault(
            key,
            {"dataset_key": snap.key, "symbols": tuple(symbols), "version_ids": []},
        )
        entry["version_ids"].append(ver.id)

    groups = [
        ApprovedScanGroup(
            horizon=horizon,
            dataset_snapshot_id=snap_id,
            dataset_key=str(entry["dataset_key"]),
            source=source,
            symbols=tuple(entry["symbols"]),
            strategy_version_ids=tuple(entry["version_ids"]),
        )
        for (snap_id, horizon, source), entry in grouped.items()
    ]
    groups.sort(key=lambda g: (g.dataset_snapshot_id, g.horizon.value, g.source))
    return groups, skipped


def approved_universes(
    session: Session, cfg: ResearchConfig | None = None
) -> tuple[list[ApprovedUniverse], list[dict[str, Any]]]:
    """The distinct approved (dataset snapshot, source) universes the scan
    covers — what the data-readiness and daily-bar-freshness gates must be
    evaluated over, one by one. Also returns the skipped versions, so a
    caller reporting readiness can say why a version is absent."""
    groups, skipped = approved_scan_groups(session, cfg)
    by_universe: dict[tuple[int, str], dict[str, Any]] = {}
    for g in groups:
        entry = by_universe.setdefault(
            g.universe_key,
            {
                "dataset_key": g.dataset_key,
                "symbols": g.symbols,
                "horizons": [],
                "version_ids": [],
            },
        )
        entry["horizons"].append(g.horizon.value)
        entry["version_ids"].extend(g.strategy_version_ids)
    universes = [
        ApprovedUniverse(
            dataset_snapshot_id=snap_id,
            dataset_key=str(entry["dataset_key"]),
            source=source,
            symbols=tuple(entry["symbols"]),
            horizons=tuple(sorted(set(entry["horizons"]))),
            strategy_version_ids=tuple(sorted(set(entry["version_ids"]))),
        )
        for (snap_id, source), entry in by_universe.items()
    ]
    universes.sort(key=lambda u: (u.dataset_snapshot_id, u.source))
    return universes, skipped


# --------------------------------------------------------------------------- #
# What the DAILY INGEST must cover (W6a)
# --------------------------------------------------------------------------- #
# Reserved, non-symbol key inside ``IngestionRun.gaps_json``. The column is
# otherwise ``symbol -> [ranges]``; the options backfill already established the
# dunder-key convention for run-level provenance ("__run__"), and a real ticker
# can never collide with it.
INGEST_PROVENANCE_KEY = "__approved_scope__"
INGEST_NOTE = "scheduled daily incremental top-up (job_ingest)"


@dataclass(frozen=True, slots=True)
class IngestContribution:
    """One approved universe's contribution to the daily ingest symbol set."""

    dataset_snapshot_id: int
    dataset_key: str
    source: str
    symbols: tuple[str, ...]  # every symbol of that approved snapshot
    added: tuple[str, ...]  # the ones the configured universe does not already cover
    horizons: tuple[str, ...]
    strategy_version_ids: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class IngestScope:
    """The exact symbol set one scheduled daily ingest must fetch, plus the
    provenance of every symbol that is not in the configured universe."""

    source: str
    configured: tuple[str, ...]
    symbols: tuple[str, ...]
    contributions: tuple[IngestContribution, ...]
    # Approved universes deliberately NOT ingested here, because their approval
    # was granted on a different source than the one this adapter writes.
    other_source: tuple[dict[str, Any], ...]
    skipped_versions: tuple[dict[str, Any], ...]

    @property
    def added(self) -> tuple[str, ...]:
        """Symbols this scope adds on top of the configured universe."""
        configured = set(self.configured)
        return tuple(s for s in self.symbols if s not in configured)

    def provenance(self) -> dict[str, Any]:
        """The ``gaps_json`` payload: which symbols came from which approved
        snapshot, and which approved universes were deliberately left out."""
        return {
            INGEST_PROVENANCE_KEY: {
                "configured": list(self.configured),
                "source": self.source,
                "snapshots": [
                    {
                        "dataset_snapshot_id": c.dataset_snapshot_id,
                        "dataset_key": c.dataset_key,
                        "source": c.source,
                        "n_symbols": len(c.symbols),
                        "added": list(c.added),
                        "horizons": list(c.horizons),
                        "strategy_version_ids": list(c.strategy_version_ids),
                    }
                    for c in self.contributions
                ],
                "excluded_other_source": [dict(u) for u in self.other_source],
                "skipped_versions": [dict(s) for s in self.skipped_versions],
            }
        }

    def note(self) -> str:
        """``IngestionRun.notes``. Byte-identical to the pre-W6a note when no
        approved universe contributes, so the routine row reads exactly as it
        always has; the suffix appears only when there is something to say."""
        if not self.contributions:
            return INGEST_NOTE
        parts = "; ".join(
            f"snapshot {c.dataset_snapshot_id} ({c.dataset_key}/{c.source}) "
            f"+{len(c.added)} of {len(c.symbols)}"
            for c in self.contributions
        )
        return f"{INGEST_NOTE} + approved scope: {parts}"


def ingest_scope(
    session: Session,
    configured: list[str],
    *,
    source: str,
    cfg: ResearchConfig | None = None,
) -> IngestScope:
    """The union of the configured universe and every PAPER_APPROVED strategy
    version's approved-scope universe, for ONE source.

    Why this exists: ``data_readiness`` demands a completed daily bar for the
    latest session across the approved snapshot's *exact* symbol set, but the
    scheduled ingest used to fetch only ``settings.research.universe``. A
    version approved on a 150-symbol snapshot was therefore blocked every
    session by its own readiness gate — the data it needed was never fetched.
    Ingesting the union closes that loop, and deriving the extra symbols from
    ``approved_universes`` (the very function that drives the scan) makes the
    two definitionally impossible to drift apart.

    **Source filter.** Only approved universes whose approval source equals
    ``source`` are added. Bars are stored tagged with the writing adapter's
    ``provider_name`` and ``data_readiness`` counts bars ``WHERE source = the
    approved source``, so fetching a foreign-source universe with this adapter
    would write rows that can never satisfy the gate they were fetched for. The
    excluded universes are recorded, not silently dropped.

    **Order** is deterministic and deliberate: the configured universe first, in
    its own order, then each approved snapshot's additional symbols sorted,
    snapshots in id order. The ingest commits per symbol, so a run cut short by
    a provider outage, a kill switch or a laptop lid has still topped up the
    configured watchlist — the set every non-approved-scope scan reads.
    """
    seen: set[str] = set()
    ordered: list[str] = []
    for raw in configured:
        sym = str(raw).upper()
        if sym not in seen:
            seen.add(sym)
            ordered.append(sym)
    configured_norm = tuple(ordered)
    configured_set = set(seen)

    universes, skipped = approved_universes(session, cfg)
    contributions: list[IngestContribution] = []
    other_source: list[dict[str, Any]] = []
    for u in universes:
        if u.source != source:
            other_source.append(
                {
                    "dataset_snapshot_id": u.dataset_snapshot_id,
                    "dataset_key": u.dataset_key,
                    "source": u.source,
                    "n_symbols": len(u.symbols),
                    "reason": f"approved source {u.source!r} is not the ingest source {source!r}",
                }
            )
            continue
        snap_symbols = tuple(sorted({str(s).upper() for s in u.symbols}))
        added = tuple(s for s in snap_symbols if s not in configured_set)
        for sym in snap_symbols:
            if sym not in seen:
                seen.add(sym)
                ordered.append(sym)
        contributions.append(
            IngestContribution(
                dataset_snapshot_id=u.dataset_snapshot_id,
                dataset_key=u.dataset_key,
                source=u.source,
                symbols=snap_symbols,
                added=added,
                horizons=tuple(u.horizons),
                strategy_version_ids=tuple(u.strategy_version_ids),
            )
        )

    return IngestScope(
        source=source,
        configured=configured_norm,
        symbols=tuple(ordered),
        contributions=tuple(contributions),
        other_source=tuple(other_source),
        skipped_versions=tuple(skipped),
    )


def _ingest_run_blocks(run: IngestionRun, symbols: list[str]) -> str | None:
    """Does the last daily-bar ingestion run block a scan of THESE symbols?

    The gate used to be global — ``status != "ok"`` blocked every approved
    universe. Once one ingest covers the union of the configured universe and
    every approved snapshot (W6a), that is far too coarse: a single delisted
    watchlist ticker would turn the run ``partial`` and silence a 150-symbol
    approved scope whose own data arrived intact.

    ``partial`` is exactly the state that CAN be attributed — it means some
    symbols succeeded and ``symbols_failed`` names the ones that did not — so
    it blocks only the universes that actually contain a failed symbol. Every
    other non-ok state (``running``, ``failed``, ``killed``, ``stopped``) is
    unattributable or means nothing succeeded, and still blocks everything.

    A ``partial`` run with an EMPTY ``symbols_failed`` fails closed: the run is
    telling us something went wrong without saying what, and guessing that it
    missed this universe would be the one wrong way to be wrong.
    """
    status = str(run.status)
    if status == "ok":
        return None
    if status != "partial":
        return f"last ingestion run is {status!r}, not ok"
    failed = {str(s).upper(): str(e) for s, e in (run.symbols_failed or {}).items()}
    if not failed:
        return (
            "last ingestion run is 'partial', not ok, and names no failed symbol — "
            "it cannot be attributed to a universe"
        )
    mine = sorted(s for s in {str(x).upper() for x in symbols} if s in failed)
    if not mine:
        return None
    return (
        f"last ingestion run is 'partial' and failed for {len(mine)}/{len(symbols)} of this "
        f"universe's symbols ({', '.join(mine[:8])}{'…' if len(mine) > 8 else ''})"
    )


def data_readiness(
    session: Session,
    symbols: list[str],
    *,
    source: str,
    now: datetime | None = None,
) -> str | None:
    """Return a human-readable block reason, or ``None`` when the data is fresh
    and complete enough to scan on. Evaluated per approved universe: an
    incomplete 150-symbol universe must not block a complete 24-symbol one."""
    now = now or datetime.now(UTC)

    # The daily-bar feed of the source this scan reads from. (The alert
    # dispatcher separately blocks on ANY stale feed at alert time — that
    # broader gate is unchanged; this one must not be blocked forever by an
    # unrelated options/news/secondary feed nobody is using.)
    feeds = [
        f
        for f in feed_status_report(session, now=now)["feeds"]
        if f["provider"] == source and f["feed_type"] == FeedType.BAR_DAILY.value
    ]
    if not feeds:
        return (
            f"no {source}/{FeedType.BAR_DAILY.value} feed registered yet — run an ingestion first"
        )
    stale = [f"{f['provider']}/{f['feed_type']}" for f in feeds if f["is_stale"]]
    if stale:
        return "stale feed: " + ", ".join(stale)

    # The DAILY-BAR ingestion specifically — an options backfill or a news
    # poll finishing "ok" says nothing about whether today's closes are in.
    last_ingest = session.scalar(
        select(IngestionRun)
        .where(IngestionRun.feed_type == FeedType.BAR_DAILY)
        .order_by(IngestionRun.started_at.desc())
        .limit(1)
    )
    if last_ingest is None:
        return "no daily-bar ingestion run recorded yet"
    reason = _ingest_run_blocks(last_ingest, symbols)
    if reason is not None:
        return reason
    finished = last_ingest.finished_at or last_ingest.started_at
    if now - finished > MAX_INGEST_AGE:
        return f"last ok ingestion finished {finished.isoformat()} — older than {MAX_INGEST_AGE}"

    if not symbols:
        return "approved universe is empty"
    latest_by_symbol: dict[str, date] = {
        str(sym): d
        for sym, d in session.execute(
            select(Instrument.symbol, func.max(OHLCVDaily.session_date))
            .join(OHLCVDaily, OHLCVDaily.instrument_id == Instrument.id)
            .where(Instrument.symbol.in_(symbols), OHLCVDaily.source == source)
            .group_by(Instrument.symbol)
        ).all()
        if d is not None
    }
    if not latest_by_symbol:
        return f"no daily bars from {source!r} for any approved-universe symbol"
    newest: date = max(latest_by_symbol.values())
    if (now.date() - newest).days > MAX_BAR_AGE_DAYS:
        return f"newest daily bar is {newest.isoformat()} — older than {MAX_BAR_AGE_DAYS} days"
    on_newest = len([d for d in latest_by_symbol.values() if d == newest])
    coverage = on_newest / len(symbols)
    if coverage < MIN_BAR_COVERAGE:
        missing = sorted(s for s in symbols if latest_by_symbol.get(s) != newest)
        return (
            f"incomplete data: only {on_newest}/{len(symbols)} approved symbols have a bar for "
            f"{newest.isoformat()} (missing: {', '.join(missing[:8])}"
            f"{'…' if len(missing) > 8 else ''})"
        )
    return None


def universe_readiness(
    session: Session,
    universes: list[ApprovedUniverse],
    *,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """``data_readiness`` for every distinct approved universe, reported one
    row per universe — never collapsed into a single verdict, so a blocked
    universe is always attributable to the dataset that is actually stale."""
    rows: list[dict[str, Any]] = []
    for u in universes:
        reason = data_readiness(session, list(u.symbols), source=u.source, now=now)
        rows.append(
            {
                "dataset_snapshot_id": u.dataset_snapshot_id,
                "dataset_key": u.dataset_key,
                "source": u.source,
                "n_symbols": len(u.symbols),
                "horizons": list(u.horizons),
                "strategy_version_ids": list(u.strategy_version_ids),
                "ready": reason is None,
                "reason": reason or "fresh, complete daily data for the approved universe",
            }
        )
    return rows


def _audit(session: Session, action: str, payload: dict[str, Any]) -> None:
    session.add(
        AuditLog(
            ts=datetime.now(UTC),
            actor="scheduler",
            action=action,
            entity="approved_scope_scan",
            before_json={},
            after_json=payload,
        )
    )
    session.flush()


def _verify_run_scope(group: ApprovedScanGroup, run: ScanRun) -> str | None:
    """The persisted run must carry EXACTLY the approved scope, or every
    candidate it produced would silently fail the scope match at alert time.
    Returns a failure reason, or ``None`` when the run is in scope."""
    if run.dataset_snapshot_id != group.dataset_snapshot_id:
        return (
            f"scan for {group.horizon.value} resolved "
            f"dataset_snapshot_id={run.dataset_snapshot_id}, expected approved snapshot "
            f"{group.dataset_snapshot_id} ({group.dataset_key!r})"
        )
    if run.source != group.source:
        return (
            f"scan for {group.horizon.value} recorded source {run.source!r}, expected the "
            f"approved source {group.source!r}"
        )
    scanned_universe = frozenset(str(s).upper() for s in (run.universe_json or ()))
    if scanned_universe != frozenset(s.upper() for s in group.symbols):
        return (
            f"scan for {group.horizon.value} recorded {len(scanned_universe)} symbols, expected "
            f"the approved universe of {len(group.symbols)} symbols from snapshot "
            f"{group.dataset_snapshot_id} ({group.dataset_key!r})"
        )
    return None


def run_approved_scope_scan(
    session: Session,
    *,
    now: datetime | None = None,
    enforce_readiness: bool = True,
) -> ApprovedScopeScanReport:
    """Run the approved-scope scan (or record exactly why it was blocked).

    One scan per ``(approved dataset snapshot, horizon, source)`` group, on
    that snapshot's exact symbol set and that approval's own source. The
    data-readiness gate is applied per approved universe, so one stale
    universe blocks only its own scans.
    """
    groups, skipped = approved_scan_groups(session)
    report = ApprovedScopeScanReport(
        ran=False,
        horizons=sorted({g.horizon.value for g in groups}),
        skipped_versions=skipped,
    )
    if not groups:
        report.blocked_reason = (
            "no PAPER_APPROVED strategy version with a usable approved scope"
            if skipped
            else "no PAPER_APPROVED strategy"
        )
        _audit(
            session,
            AUDIT_BLOCKED,
            {"reason": report.blocked_reason, "skipped_versions": skipped},
        )
        return report

    universes = {g.universe_key: g for g in groups}
    all_symbols = {s.upper() for g in groups for s in g.symbols}
    report.n_symbols = len(all_symbols)
    if len(universes) == 1:
        only = next(iter(universes.values()))
        report.dataset_snapshot_id = only.dataset_snapshot_id
        report.dataset_key = only.dataset_key
    report.live_config_hash = effective_research_config(session).config_hash

    # Readiness per distinct universe — computed once, reused by every group
    # that scans it. A block here removes ONLY that universe's groups.
    blocked: dict[tuple[int, str], str] = {}
    if enforce_readiness:
        for key, g in universes.items():
            reason = data_readiness(session, list(g.symbols), source=g.source, now=now)
            if reason is None:
                continue
            blocked[key] = reason
            detail = {
                "reason": reason,
                "dataset_snapshot_id": g.dataset_snapshot_id,
                "dataset_key": g.dataset_key,
                "source": g.source,
                "n_symbols": len(g.symbols),
                "horizons": sorted({x.horizon.value for x in groups if x.universe_key == key}),
            }
            report.blocked_universes.append(detail)
            _log.warning(
                "approved_scope_scan.blocked",
                reason=reason,
                dataset_snapshot_id=g.dataset_snapshot_id,
            )
            _audit(session, AUDIT_BLOCKED, detail)

    runnable = [g for g in groups if g.universe_key not in blocked]
    if not runnable:
        reasons = [str(b["reason"]) for b in report.blocked_universes]
        report.blocked_reason = (
            reasons[0]
            if len(reasons) == 1
            else "; ".join(
                f"snapshot {b['dataset_snapshot_id']} ({b['dataset_key']}): {b['reason']}"
                for b in report.blocked_universes
            )
        )
        return report

    for g in runnable:

        def _one(grp: ApprovedScanGroup = g) -> tuple[ScanResult, ScanRun]:
            res = run_scan(session, grp.horizon, symbols=list(grp.symbols), source=grp.source)
            return res, persist_scan(session, res)

        # per-group lock retry: never re-run an already-persisted group
        label = f"approved_scope_scan:{g.horizon.value}:snapshot{g.dataset_snapshot_id}"
        result, run = retry_on_lock(_one, label=label)
        # run_scan resolves its own DataSnapshot (by exact symbol set). It must
        # be the very row these strategy versions were approved on — otherwise
        # every candidate would silently fail the scope match at alert time.
        # Refuse loudly instead of trusting it.
        reason = _verify_run_scope(g, run)
        if reason is not None:
            _audit(session, AUDIT_BLOCKED, {"reason": reason, "scan_run_id": run.id})
            raise RuntimeError(reason)
        report.runs.append(
            {
                "horizon": g.horizon.value,
                "scan_run_id": run.id,
                "scanned": len(result.scanned),
                "candidates": run.candidate_count,
                "no_trade": run.no_trade_count,
                "dataset_snapshot_id": run.dataset_snapshot_id,
                "dataset_key": g.dataset_key,
                "n_symbols": len(g.symbols),
                "source": g.source,
                "strategy_version_ids": list(g.strategy_version_ids),
            }
        )
    report.ran = True
    _audit(
        session,
        AUDIT_COMPLETED,
        {
            "dataset_snapshot_id": report.dataset_snapshot_id,
            "dataset_key": report.dataset_key,
            "n_symbols": report.n_symbols,
            "live_config_hash": report.live_config_hash,
            "readiness_enforced": enforce_readiness,
            "runs": report.runs,
            "blocked_universes": report.blocked_universes,
            "skipped_versions": report.skipped_versions,
        },
    )
    _log.info(
        "approved_scope_scan.done",
        horizons=report.horizons,
        candidates=report.total_candidates,
        groups=len(report.runs),
        blocked_universes=len(report.blocked_universes),
    )
    return report
