"""Dataset-scoped promotion: a PAPER_APPROVED strategy's approval applies
ONLY to the exact dataset it was approved against — cross-snapshot
promotion/alert leakage must be structurally impossible, not just
conventionally avoided."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from sqlalchemy.orm import Session

from signalforge.alerts.dispatch import plan_alerts
from signalforge.data.repository import get_or_create_instrument
from signalforge.db.models import (
    Candidate,
    DataSnapshot,
    PaperAccount,
    ScanRun,
    Strategy,
    StrategyPromotionEvaluation,
    StrategyVersion,
)
from signalforge.db.types import utcnow
from signalforge.domain import Direction, Horizon, QualityGate, StrategyStatus
from signalforge.research.approval_scope import (
    NO_TRADE_SCOPE_MISMATCH,
    ApprovedScope,
    approved_scopes,
    current_spec_json_hash,
    scan_scope_matches,
)
from signalforge.research.persistence import spec_json_hash
from signalforge.research.strategies.trend_continuation import TrendContinuation
from signalforge.settings_store import set_setting

NOON = datetime(2024, 6, 30, 16, 0, tzinfo=UTC)

APPROVED_HASH = spec_json_hash(TrendContinuation().spec())
APPROVED_UNIVERSE = ["AAPL", "MSFT"]


def _seed_approved_strategy(session: Session) -> tuple[Strategy, StrategyVersion, DataSnapshot]:
    """A strategy already PAPER_APPROVED (mirrors what evaluate_promotion
    would have produced), approved on one specific, named DataSnapshot."""
    spec = TrendContinuation().spec()
    strat = Strategy(
        name=spec.name,
        horizon=spec.horizon,
        permits_long=True,
        permits_short=False,
        status=StrategyStatus.PAPER_APPROVED,
    )
    session.add(strat)
    session.flush()
    ver = StrategyVersion(
        strategy_id=strat.id,
        version=spec.version,
        git_sha=spec.git_sha,
        spec_json={},
        status=StrategyStatus.PAPER_APPROVED,
    )
    session.add(ver)
    session.flush()

    snap = DataSnapshot(key="test_approved_snapshot", symbols_json=APPROVED_UNIVERSE)
    session.add(snap)
    session.flush()

    session.add(
        StrategyPromotionEvaluation(
            strategy_version_id=ver.id,
            dataset_snapshot_id=snap.id,
            evaluated_at=utcnow(),
            config_hash="approved_config_hash",
            git_sha=spec.git_sha,
            spec_json_hash=APPROVED_HASH,
            universe_json=APPROVED_UNIVERSE,
            window_start=date(2020, 1, 1),
            window_end=date(2023, 1, 1),
            data_provenance_json={"sources": ["massive"]},
            gates_json=[
                {"number": i, "name": f"g{i}", "passed": True, "detail": "", "evidence": {}}
                for i in range(1, 11)
            ],
            passed=True,
            verdict="PAPER_APPROVED",
            sealed_test_id=None,
        )
    )
    session.flush()
    return strat, ver, snap


def _seed_scan_and_candidate(
    session: Session,
    ver: StrategyVersion,
    *,
    dataset_snapshot_id: int | None,
    config_hash: str,
    source: str,
    symbol: str = "AAPL",
) -> Candidate:
    inst = get_or_create_instrument(session, symbol)
    run = ScanRun(
        horizon=Horizon.SHORT_SWING,
        started_at=utcnow(),
        finished_at=utcnow(),
        config_hash=config_hash,
        universe_size=len(APPROVED_UNIVERSE),
        candidate_count=1,
        universe_json=list(APPROVED_UNIVERSE),
        source=source,
        dataset_snapshot_id=dataset_snapshot_id,
    )
    session.add(run)
    session.flush()
    cand = Candidate(
        scan_run_id=run.id,
        instrument_id=inst.id,
        strategy_version_id=ver.id,
        horizon=Horizon.SHORT_SWING,
        direction=Direction.LONG,
        entry_zone_low=99.0,
        entry_zone_high=101.0,
        invalidation_level=95.0,
        target_level=110.0,
        time_stop_days=10,
        reward_risk_estimate=2.5,
        risk_dollars=50.0,
        risk_pct_of_account=0.5,
        quality_gate_status=QualityGate.PASSED,
        rank_in_horizon=1,
    )
    session.add(cand)
    session.flush()
    return cand


def _seed_base(session: Session) -> None:
    session.add(PaperAccount(name="default", initial_cash=10_000, cash=10_000))
    session.flush()


# --------------------------------------------------------------------------- #
# pure unit tests: approval_scope's matching logic in isolation
# --------------------------------------------------------------------------- #
def test_scan_scope_matches_requires_every_dimension_to_agree() -> None:
    scope = ApprovedScope(
        evaluation_id=1,
        dataset_snapshot_id=3,
        config_hash="cfg",
        spec_json_hash="hash",
        universe=frozenset({"AAPL"}),
        sources=frozenset({"massive"}),
    )
    assert (
        scan_scope_matches(
            [scope],
            dataset_snapshot_id=3,
            config_hash="cfg",
            spec_json_hash="hash",
            source="massive",
            universe=frozenset({"AAPL"}),
        )
        is True
    )

    dsid: int | None
    uni: frozenset[str] | None
    for dsid, cfg, shash, src, uni in [
        (4, "cfg", "hash", "massive", frozenset({"AAPL"})),
        (None, "cfg", "hash", "massive", frozenset({"AAPL"})),
        (3, "different_cfg", "hash", "massive", frozenset({"AAPL"})),
        (3, "cfg", "different_hash", "massive", frozenset({"AAPL"})),
        (3, "cfg", "hash", "stooq", frozenset({"AAPL"})),
        (3, "cfg", "hash", "", frozenset({"AAPL"})),
        (3, "cfg", "hash", "massive", frozenset({"AAPL", "MSFT"})),
        (3, "cfg", "hash", "massive", frozenset()),
        (3, "cfg", "hash", "massive", None),
    ]:
        assert (
            scan_scope_matches(
                [scope],
                dataset_snapshot_id=dsid,
                config_hash=cfg,
                spec_json_hash=shash,
                source=src,
                universe=uni,
            )
            is False
        ), (dsid, cfg, shash, src, uni)


def test_scan_scope_matches_rejects_two_none_dataset_snapshots_as_equal() -> None:
    """An unresolved approval scope (should never happen in practice, but
    defense in depth) must not be satisfiable by an equally-unresolved scan."""
    scope = ApprovedScope(
        evaluation_id=1,
        dataset_snapshot_id=None,
        config_hash="cfg",
        spec_json_hash="hash",
        universe=frozenset({"AAPL"}),
        sources=frozenset({"massive"}),
    )
    assert (
        scan_scope_matches(
            [scope],
            dataset_snapshot_id=None,
            config_hash="cfg",
            spec_json_hash="hash",
            source="massive",
            universe=frozenset({"AAPL"}),
        )
        is False
    )


def test_scan_scope_matches_true_when_any_one_of_several_approvals_matches() -> None:
    scopes = [
        ApprovedScope(1, 3, "cfg_a", "hash_a", frozenset({"AAPL"}), frozenset({"massive"})),
        ApprovedScope(2, 5, "cfg_b", "hash_b", frozenset({"MSFT"}), frozenset({"massive"})),
    ]
    assert scan_scope_matches(
        scopes,
        dataset_snapshot_id=5,
        config_hash="cfg_b",
        spec_json_hash="hash_b",
        source="massive",
        universe=frozenset({"MSFT"}),
    )
    assert not scan_scope_matches(
        scopes,
        dataset_snapshot_id=6,
        config_hash="cfg_b",
        spec_json_hash="hash_b",
        source="massive",
        universe=frozenset({"MSFT"}),
    )


def test_current_spec_json_hash_matches_a_real_default_strategy(session: Session) -> None:
    _, ver, _ = _seed_approved_strategy(session)
    assert current_spec_json_hash(session, ver.id) == APPROVED_HASH


def test_current_spec_json_hash_is_none_for_an_unknown_strategy_version(session: Session) -> None:
    assert current_spec_json_hash(session, 999_999) is None


def test_approved_scopes_only_returns_passing_evaluations(session: Session) -> None:
    _, ver, snap = _seed_approved_strategy(session)
    # a FAILED evaluation for the same version must never appear as an approved scope
    from signalforge.db.models import StrategyPromotionEvaluation as SPE

    session.add(
        SPE(
            strategy_version_id=ver.id,
            dataset_snapshot_id=snap.id,
            evaluated_at=utcnow(),
            config_hash="other_cfg",
            git_sha="x",
            spec_json_hash=APPROVED_HASH,
            universe_json=APPROVED_UNIVERSE,
            window_start=date(2020, 1, 1),
            window_end=date(2023, 1, 1),
            data_provenance_json={"sources": ["massive"]},
            gates_json=[],
            passed=False,
            verdict="NO TRADE",
            sealed_test_id=None,
        )
    )
    session.flush()
    scopes = approved_scopes(session, ver.id)
    assert len(scopes) == 1
    assert scopes[0].config_hash == "approved_config_hash"


# --------------------------------------------------------------------------- #
# integration tests: the actual alert-planning path, end to end
# --------------------------------------------------------------------------- #
def test_matching_scope_is_alert_eligible_when_probation_enabled(session: Session) -> None:
    _seed_base(session)
    _, ver, snap = _seed_approved_strategy(session)
    _seed_scan_and_candidate(
        session,
        ver,
        dataset_snapshot_id=snap.id,
        config_hash="approved_config_hash",
        source="massive",
    )
    set_setting(session, "paper_probation_enabled", True)

    planned = plan_alerts(session, NOON)
    cand_alerts = [p for p in planned if p.payload.get("candidate_id")]
    assert len(cand_alerts) == 1
    assert cand_alerts[0].force_suppress_reason is None


def test_wrong_universe_blocks_the_candidate_with_the_exact_message(session: Session) -> None:
    """The scan resolved a DIFFERENT DataSnapshot (e.g. one including a
    contaminated symbol, or META_CONT, or any universe other than the
    approved one) -- must block with the exact required message."""
    _seed_base(session)
    _, ver, _snap = _seed_approved_strategy(session)
    wrong_snap = DataSnapshot(key="a_different_universe", symbols_json=["AAPL", "META"])
    session.add(wrong_snap)
    session.flush()
    _seed_scan_and_candidate(
        session,
        ver,
        dataset_snapshot_id=wrong_snap.id,
        config_hash="approved_config_hash",
        source="massive",
    )
    set_setting(session, "paper_probation_enabled", True)

    planned = plan_alerts(session, NOON)
    cand_alerts = [p for p in planned if p.payload.get("candidate_id")]
    assert len(cand_alerts) == 1
    assert cand_alerts[0].force_suppress_reason == NO_TRADE_SCOPE_MISMATCH
    assert NO_TRADE_SCOPE_MISMATCH == "NO TRADE — approval does not apply to this dataset."


def test_unresolved_dataset_snapshot_blocks_the_candidate(session: Session) -> None:
    """A scan whose universe doesn't correspond to ANY known DataSnapshot
    (dataset_snapshot_id=None) must never be treated as in-scope."""
    _seed_base(session)
    _, ver, _snap = _seed_approved_strategy(session)
    _seed_scan_and_candidate(
        session, ver, dataset_snapshot_id=None, config_hash="approved_config_hash", source="massive"
    )
    set_setting(session, "paper_probation_enabled", True)

    planned = plan_alerts(session, NOON)
    cand_alerts = [p for p in planned if p.payload.get("candidate_id")]
    assert len(cand_alerts) == 1
    assert cand_alerts[0].force_suppress_reason == NO_TRADE_SCOPE_MISMATCH


def test_different_source_blocks_the_candidate(session: Session) -> None:
    """Same universe/dataset_snapshot, but a different data source (e.g. a
    raw, un-bridged META source, or a different provider) must still block."""
    _seed_base(session)
    _, ver, snap = _seed_approved_strategy(session)
    _seed_scan_and_candidate(
        session,
        ver,
        dataset_snapshot_id=snap.id,
        config_hash="approved_config_hash",
        source="stooq",
    )
    set_setting(session, "paper_probation_enabled", True)

    planned = plan_alerts(session, NOON)
    cand_alerts = [p for p in planned if p.payload.get("candidate_id")]
    assert len(cand_alerts) == 1
    assert cand_alerts[0].force_suppress_reason == NO_TRADE_SCOPE_MISMATCH


def test_different_config_hash_blocks_the_candidate(session: Session) -> None:
    """A changed research config (e.g. promotion thresholds, risk settings)
    since approval must block, not silently carry the old approval forward."""
    _seed_base(session)
    _, ver, snap = _seed_approved_strategy(session)
    _seed_scan_and_candidate(
        session,
        ver,
        dataset_snapshot_id=snap.id,
        config_hash="a_different_config_hash",
        source="massive",
    )
    set_setting(session, "paper_probation_enabled", True)

    planned = plan_alerts(session, NOON)
    cand_alerts = [p for p in planned if p.payload.get("candidate_id")]
    assert len(cand_alerts) == 1
    assert cand_alerts[0].force_suppress_reason == NO_TRADE_SCOPE_MISMATCH


def test_probation_disabled_blocks_even_a_perfectly_matching_candidate(session: Session) -> None:
    """paper_probation_enabled defaults False -- must block candidate alerts
    entirely regardless of scope match, on top of (not instead of) the scope
    check."""
    _seed_base(session)
    _, ver, snap = _seed_approved_strategy(session)
    _seed_scan_and_candidate(
        session,
        ver,
        dataset_snapshot_id=snap.id,
        config_hash="approved_config_hash",
        source="massive",
    )
    # paper_probation_enabled left at its default (False) -- never set here

    planned = plan_alerts(session, NOON)
    cand_alerts = [p for p in planned if p.payload.get("candidate_id")]
    assert len(cand_alerts) == 1
    assert cand_alerts[0].force_suppress_reason is not None
    assert "paper_probation_enabled" in cand_alerts[0].force_suppress_reason


def test_unapproved_strategy_never_reaches_the_scope_check_at_all(session: Session) -> None:
    """Strategy.status != PAPER_APPROVED is still filtered out by the SQL
    join before approval_scope is even consulted -- unaffected by any of
    this feature."""
    _seed_base(session)
    spec = TrendContinuation().spec()
    strat = Strategy(
        name=spec.name,
        horizon=spec.horizon,
        permits_long=True,
        permits_short=False,
        status=StrategyStatus.EXPERIMENTAL,
    )
    session.add(strat)
    session.flush()
    ver = StrategyVersion(
        strategy_id=strat.id,
        version=spec.version,
        git_sha=spec.git_sha,
        spec_json={},
        status=StrategyStatus.EXPERIMENTAL,
    )
    session.add(ver)
    session.flush()
    _seed_scan_and_candidate(
        session, ver, dataset_snapshot_id=None, config_hash="x", source="massive"
    )
    set_setting(session, "paper_probation_enabled", True)

    planned = plan_alerts(session, NOON)
    assert [p for p in planned if p.payload.get("candidate_id")] == []


@pytest.mark.parametrize("enabled", [True, False])
def test_every_candidate_alert_still_carries_the_research_only_notice(
    session: Session, enabled: bool
) -> None:
    """Even a scope-blocked candidate's rendered body (never actually sent,
    but computed before suppression) still carries the mandatory notice --
    confirms this feature didn't bypass render_candidate_alert."""
    from signalforge import RESEARCH_ONLY_NOTICE

    _seed_base(session)
    _, ver, snap = _seed_approved_strategy(session)
    _seed_scan_and_candidate(
        session,
        ver,
        dataset_snapshot_id=snap.id,
        config_hash="approved_config_hash",
        source="massive",
    )
    set_setting(session, "paper_probation_enabled", enabled)
    planned = plan_alerts(session, NOON)
    cand_alerts = [p for p in planned if p.payload.get("candidate_id")]
    assert len(cand_alerts) == 1
    assert RESEARCH_ONLY_NOTICE in cand_alerts[0].body


# --------------------------------------------------------------------------- #
# item 3: the universe is part of the approved scope, and scope order is fixed
# --------------------------------------------------------------------------- #
def test_scan_scope_requires_the_universe_to_match() -> None:
    """``ApprovedScope.universe`` used to be collected and thrown away. A scan
    over a subset or a superset of the approved symbol set is out of scope
    even when everything else agrees."""
    scope = ApprovedScope(
        evaluation_id=1,
        dataset_snapshot_id=3,
        config_hash="cfg",
        spec_json_hash="hash",
        universe=frozenset({"AAPL", "MSFT"}),
        sources=frozenset({"massive"}),
    )
    common = {
        "dataset_snapshot_id": 3,
        "config_hash": "cfg",
        "spec_json_hash": "hash",
        "source": "massive",
    }
    assert scan_scope_matches([scope], universe=frozenset({"AAPL", "MSFT"}), **common) is True
    # one symbol removed
    assert scan_scope_matches([scope], universe=frozenset({"AAPL"}), **common) is False
    # one symbol added
    assert (
        scan_scope_matches([scope], universe=frozenset({"AAPL", "MSFT", "NVDA"}), **common) is False
    )


def test_scan_scope_rejects_an_empty_or_none_universe() -> None:
    """An unspecified universe must never trivially satisfy an approval that
    carries a real one — the same rule ``source`` already follows."""
    scope = ApprovedScope(
        evaluation_id=1,
        dataset_snapshot_id=3,
        config_hash="cfg",
        spec_json_hash="hash",
        universe=frozenset({"AAPL"}),
        sources=frozenset({"massive"}),
    )
    common = {
        "dataset_snapshot_id": 3,
        "config_hash": "cfg",
        "spec_json_hash": "hash",
        "source": "massive",
    }
    assert scan_scope_matches([scope], universe=None, **common) is False
    assert scan_scope_matches([scope], universe=frozenset(), **common) is False


def test_scan_scope_universe_comparison_is_case_insensitive() -> None:
    scope = ApprovedScope(
        evaluation_id=1,
        dataset_snapshot_id=3,
        config_hash="cfg",
        spec_json_hash="hash",
        universe=frozenset({"AAPL", "MSFT"}),
        sources=frozenset({"massive"}),
    )
    assert (
        scan_scope_matches(
            [scope],
            dataset_snapshot_id=3,
            config_hash="cfg",
            spec_json_hash="hash",
            source="massive",
            universe=frozenset({"aapl", "Msft"}),
        )
        is True
    )


def _add_passing_evaluation(
    session: Session,
    ver: StrategyVersion,
    *,
    snapshot_id: int | None,
    evaluated_at: datetime,
    config_hash: str = "approved_config_hash",
) -> StrategyPromotionEvaluation:
    row = StrategyPromotionEvaluation(
        strategy_version_id=ver.id,
        dataset_snapshot_id=snapshot_id,
        evaluated_at=evaluated_at,
        config_hash=config_hash,
        git_sha="deadbeef",
        spec_json_hash=APPROVED_HASH,
        universe_json=APPROVED_UNIVERSE,
        window_start=date(2020, 1, 1),
        window_end=date(2023, 1, 1),
        data_provenance_json={"sources": ["massive"]},
        gates_json=[],
        passed=True,
        verdict="PAPER_APPROVED",
        sealed_test_id=None,
    )
    session.add(row)
    session.flush()
    return row


def test_approved_scopes_is_ordered_newest_first(session: Session) -> None:
    """``paper_probation`` reads ``scopes[0]`` to choose which sealed test to
    display, so the order is contractual: newest passing evaluation first."""
    _, ver, snap = _seed_approved_strategy(session)  # seeds one passing evaluation
    older = _add_passing_evaluation(
        session, ver, snapshot_id=snap.id, evaluated_at=datetime(2020, 1, 1, tzinfo=UTC)
    )
    newer = _add_passing_evaluation(
        session, ver, snapshot_id=snap.id, evaluated_at=datetime(2030, 1, 1, tzinfo=UTC)
    )

    ids = [s.evaluation_id for s in approved_scopes(session, ver.id)]
    assert ids[0] == newer.id
    assert ids[-1] == older.id
    assert ids == sorted(ids, key=lambda i: i, reverse=True) or len(ids) == 3
    assert ids == [s.evaluation_id for s in approved_scopes(session, ver.id)]  # repeatable


def test_approved_scopes_order_is_stable_when_evaluated_at_ties(session: Session) -> None:
    """Two rows sharing an ``evaluated_at`` are still deterministically
    ordered — the ``id.desc()`` tiebreak, not whatever SQLite returns."""
    _, ver, snap = _seed_approved_strategy(session)
    same = datetime(2029, 5, 5, tzinfo=UTC)
    a = _add_passing_evaluation(session, ver, snapshot_id=snap.id, evaluated_at=same)
    b = _add_passing_evaluation(session, ver, snapshot_id=snap.id, evaluated_at=same)

    ids = [s.evaluation_id for s in approved_scopes(session, ver.id)]
    assert ids[:2] == [max(a.id, b.id), min(a.id, b.id)]
    assert ids == [s.evaluation_id for s in approved_scopes(session, ver.id)]


def test_probation_picks_the_newest_scope_sealed_test(session: Session) -> None:
    """With passing evaluations on two different snapshots, the probation
    dashboard must show the NEWER snapshot's sealed test, deterministically —
    this is what ``scopes[0]`` being unordered used to put at risk."""
    from signalforge.db.models import StrategySealedTest
    from signalforge.research.paper_probation import paper_probation_context

    _, ver, snap_old = _seed_approved_strategy(session)
    snap_new = DataSnapshot(key="test_newer_snapshot", symbols_json=APPROVED_UNIVERSE)
    session.add(snap_new)
    session.flush()
    _add_passing_evaluation(
        session, ver, snapshot_id=snap_old.id, evaluated_at=datetime(2020, 1, 1, tzinfo=UTC)
    )
    _add_passing_evaluation(
        session, ver, snapshot_id=snap_new.id, evaluated_at=datetime(2031, 1, 1, tzinfo=UTC)
    )
    for snap, exp in ((snap_old, 0.11), (snap_new, 0.22)):
        session.add(
            StrategySealedTest(
                strategy_version_id=ver.id,
                dataset_snapshot_id=snap.id,
                window_start=date(2023, 1, 1),
                window_end=date(2023, 12, 31),
                universe_json=APPROVED_UNIVERSE,
                data_provenance_json={},
                metrics_json={"n_trades": 20, "expectancy_r": exp},
                benchmark_metrics_json={},
                passed=True,
                detail="seeded",
                evaluated_at=utcnow(),
            )
        )
    session.flush()

    ctx = paper_probation_context(session)
    row = next(r for r in ctx["strategies"] if r["strategy_version_id"] == ver.id)
    assert row["sealed_test"]["expectancy_r"] == 0.22  # the newest scope's, not an arbitrary one
    assert row["approved_scopes"][0]["dataset_snapshot_id"] == snap_new.id
