"""Enforce that a PAPER_APPROVED strategy's approval applies ONLY to the
exact dataset it was approved against — never to a different universe,
source, config, or parameter set that merely happens to share the same
strategy status.

``Strategy.status == PAPER_APPROVED`` is necessary but NOT sufficient for a
candidate to be alert-eligible: it says a strategy version passed the
promotion pipeline at some point, on SOME dataset — it says nothing about
which dataset the CURRENT candidate's scan actually used. This module closes
that gap: a candidate is in-scope only when the scan that produced it
matches, exactly, one of that strategy version's PASSING
``StrategyPromotionEvaluation`` rows on all of: dataset snapshot, config
hash, and live parameter hash (``research.persistence.spec_json_hash`` —
covers "strategy version" and "changed strategy parameters" together, since
a version string can go un-bumped while a strategy's live params drift).

Not enforced here, structurally guaranteed elsewhere: ``Strategy.status``
can only ever become ``PAPER_APPROVED`` via ``research.promotion`` (never a
manual action), and a dataset snapshot's own contents are immutable once
created (``research.promotion.get_or_create_dataset_snapshot``).
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from signalforge.db.models import Strategy, StrategyPromotionEvaluation, StrategyVersion

NO_TRADE_SCOPE_MISMATCH = "NO TRADE — approval does not apply to this dataset."


@dataclass(frozen=True, slots=True)
class ApprovedScope:
    evaluation_id: int
    dataset_snapshot_id: int | None
    config_hash: str
    spec_json_hash: str
    universe: frozenset[str]
    sources: frozenset[str]


def approved_scopes(session: Session, strategy_version_id: int) -> list[ApprovedScope]:
    """Every PASSING evaluation's exact scope for this strategy version — a
    strategy version can legitimately be approved on more than one
    independently-verified dataset; a live scan is in scope if it matches
    ANY one of them.

    **Ordered newest passing evaluation first**, with the evaluation id as a
    deterministic tiebreak when two share an ``evaluated_at``. The order is
    part of the contract, not an accident of what SQLite happens to return:
    ``research.paper_probation`` selects which sealed test to display via
    ``scopes[0].dataset_snapshot_id``, so once a strategy has passing
    evaluations on two different snapshots an unordered query would show an
    arbitrary one. Ordering changes no membership, so ``scan_scope_matches``'s
    ``any(...)`` verdict is unaffected by construction."""
    rows = session.scalars(
        select(StrategyPromotionEvaluation)
        .where(
            StrategyPromotionEvaluation.strategy_version_id == strategy_version_id,
            StrategyPromotionEvaluation.passed.is_(True),
        )
        .order_by(
            StrategyPromotionEvaluation.evaluated_at.desc(),
            StrategyPromotionEvaluation.id.desc(),
        )
    )
    return [
        ApprovedScope(
            evaluation_id=r.id,
            dataset_snapshot_id=r.dataset_snapshot_id,
            config_hash=r.config_hash,
            spec_json_hash=r.spec_json_hash,
            universe=frozenset(s.upper() for s in r.universe_json),
            sources=frozenset(r.data_provenance_json.get("sources") or ()),
        )
        for r in rows
    ]


def scan_scope_matches(
    scopes: list[ApprovedScope],
    *,
    dataset_snapshot_id: int | None,
    config_hash: str,
    spec_json_hash: str,
    source: str,
    universe: frozenset[str] | None,
) -> bool:
    """True iff a live scan's exact scope matches at least one approved
    scope: dataset snapshot, config hash, live parameter hash, source, AND
    the exact symbol set the approval was granted over.
    ``dataset_snapshot_id=None`` (an unresolved/ad hoc scan — e.g. one whose
    universe doesn't correspond to any known DataSnapshot) can never match:
    two ``None``s are not treated as equal, since that would let an
    arbitrary scan bypass the check simply by using a universe nobody has
    ever named. An empty/unspecified ``source`` never matches either — it
    would trivially satisfy an approval carrying a real, non-empty source
    set otherwise, and the same is true of an empty/unspecified ``universe``.

    The approval is scoped to *this exact symbol set*: a scan over a subset
    or a superset of the approved universe is OUT of scope even when it
    resolves to the same ``DataSnapshot`` id, because the evidence that
    earned the approval was measured over those symbols and no others.
    Symbols are compared upper-cased on both sides, matching how
    ``approved_scopes`` normalises them."""
    if dataset_snapshot_id is None or not source or not universe:
        return False
    scan_universe = frozenset(s.upper() for s in universe)
    return any(
        s.dataset_snapshot_id == dataset_snapshot_id
        and s.config_hash == config_hash
        and s.spec_json_hash == spec_json_hash
        and s.sources == frozenset({source})
        and s.universe == scan_universe
        for s in scopes
    )


def current_spec_json_hash(session: Session, strategy_version_id: int) -> str | None:
    """The parameter-hash a LIVE strategy instance would produce right now
    for this strategy_version_id, or ``None`` if no default strategy resolves
    to it (e.g. the version row is historical/orphaned). Deliberately reads
    ``default_strategies()`` fresh rather than trusting
    ``StrategyVersion.spec_json`` — that column is refreshed by
    ``upsert_strategy_version`` on every scan/backtest and does not, by
    itself, distinguish "matches what was approved" from "matches whatever
    last touched this row"; comparing freshly-computed hashes against the
    evaluation's stored hash is what actually does that."""
    from signalforge.research.persistence import spec_json_hash
    from signalforge.research.strategies import default_strategies

    for strat in default_strategies():
        spec = strat.spec()
        ver = session.scalar(
            select(StrategyVersion)
            .join(Strategy, StrategyVersion.strategy_id == Strategy.id)
            .where(Strategy.name == spec.name, StrategyVersion.version == spec.version)
        )
        if ver is not None and ver.id == strategy_version_id:
            return spec_json_hash(spec)
    return None
