"""The scheduled approved-scope scan: hard per-universe data-readiness gate,
each PAPER_APPROVED strategy version scanned on EXACTLY its own approved
dataset, EOD-only, and an audit row either way."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from signalforge.db.models import (
    AuditLog,
    Candidate,
    DataFeedStatus,
    DataSnapshot,
    IngestionRun,
    Instrument,
    OHLCVDaily,
    ScanRun,
    Strategy,
    StrategyPromotionEvaluation,
    StrategyVersion,
)
from signalforge.domain import FeedType, Horizon, LatencyCategory, StrategyStatus
from signalforge.research import approved_scope_scan as mod
from signalforge.research.approved_scope_scan import (
    AUDIT_BLOCKED,
    AUDIT_COMPLETED,
    approved_horizons,
    approved_scan_groups,
    approved_universes,
    data_readiness,
    run_approved_scope_scan,
    universe_readiness,
)

# Clock-RELATIVE, deliberately: data_readiness takes an explicit ``now`` but
# the feed-staleness gate underneath it (data.feeds.feed_status_report) reads
# the real wall clock, so a hard-coded NOW turns every readiness test into a
# time bomb that starts failing a couple of days after it was written.
NOW = datetime.now(UTC)
TODAY = NOW.date()
SYMS = ["AAA", "BBB", "CCC", "DDD"]
OTHER_SYMS = ["EEE", "FFF", "GGG", "HHH", "III", "JJJ"]
SRC = "massive"


def _feed(session: Session, *, stale: bool, provider: str = SRC) -> None:
    session.add(
        DataFeedStatus(
            provider=provider,
            feed_type=FeedType.BAR_DAILY,
            latency_category=LatencyCategory.END_OF_DAY,
            last_success_at=NOW - (timedelta(days=3) if stale else timedelta(hours=1)),
            updated_at=NOW,
        )
    )
    session.flush()


def _ingest(session: Session, *, status: str = "ok", age: timedelta = timedelta(hours=1)) -> None:
    session.add(
        IngestionRun(
            provider=SRC,
            feed_type=FeedType.BAR_DAILY,
            requested_start=TODAY - timedelta(days=40),
            requested_end=TODAY,
            status=status,
            started_at=NOW - age - timedelta(minutes=5),
            finished_at=NOW - age,
        )
    )
    session.flush()


def _bars(
    session: Session,
    latest: dict[str, date] | None = None,
    *,
    symbols: list[str] | None = None,
) -> None:
    latest = latest or {}
    for sym in symbols or SYMS:
        inst = session.scalar(select(Instrument).where(Instrument.symbol == sym))
        if inst is None:
            inst = Instrument(symbol=sym, name=sym)
            session.add(inst)
            session.flush()
        newest = latest.get(sym, TODAY)
        for d in (newest - timedelta(days=20), newest):
            session.add(
                OHLCVDaily(
                    instrument_id=inst.id,
                    session_date=d,
                    open=1,
                    high=1,
                    low=1,
                    close=1,
                    volume=100,
                    source=SRC,
                    latency_category=LatencyCategory.END_OF_DAY,
                    ingested_at=NOW,
                )
            )
    session.flush()


def _ready(session: Session) -> None:
    _feed(session, stale=False)
    _ingest(session)
    _bars(session, {})
    session.flush()


def _snapshot(session: Session, key: str, symbols: list[str]) -> DataSnapshot:
    snap = DataSnapshot(key=key, symbols_json=list(symbols))
    session.add(snap)
    session.flush()
    return snap


def _approve(
    session: Session,
    *,
    name: str,
    horizon: Horizon,
    snapshot: DataSnapshot | None,
    version: str = "0.1.0",
    source: str | None = SRC,
    config_hash: str = "cfg-hash",
    spec_hash: str | None = None,
    universe: list[str] | None = None,
    passed: bool = True,
    evaluated_at: datetime | None = None,
    with_evaluation: bool = True,
) -> StrategyVersion:
    """A PAPER_APPROVED strategy version plus the passing promotion
    evaluation that defines its approved scope."""
    strat = session.scalar(select(Strategy).where(Strategy.name == name))
    if strat is None:
        strat = Strategy(name=name, horizon=horizon, status=StrategyStatus.PAPER_APPROVED)
        session.add(strat)
        session.flush()
    ver = StrategyVersion(
        strategy_id=strat.id,
        version=version,
        git_sha="0" * 40,
        spec_json={},
        status=StrategyStatus.PAPER_APPROVED,
    )
    session.add(ver)
    session.flush()
    if with_evaluation:
        session.add(
            StrategyPromotionEvaluation(
                strategy_version_id=ver.id,
                dataset_snapshot_id=snapshot.id if snapshot is not None else None,
                evaluated_at=evaluated_at or NOW,
                config_hash=config_hash,
                spec_json_hash=spec_hash or f"spec-{name}",
                universe_json=(
                    universe
                    if universe is not None
                    else (list(snapshot.symbols_json) if snapshot is not None else [])
                ),
                window_start=date(2020, 1, 1),
                window_end=date(2026, 1, 1),
                data_provenance_json={"sources": [source] if source is not None else []},
                passed=passed,
            )
        )
        session.flush()
    return ver


# --------------------------------------------------------------------------
# data readiness (per universe)
# --------------------------------------------------------------------------


def test_readiness_ok_when_fresh_and_complete(session: Session) -> None:
    _ready(session)
    assert data_readiness(session, SYMS, source=SRC, now=NOW) is None


def test_readiness_blocks_on_no_feed(session: Session) -> None:
    assert "feed registered yet" in (data_readiness(session, SYMS, source=SRC, now=NOW) or "")


def test_readiness_blocks_on_stale_feed(session: Session) -> None:
    _feed(session, stale=True)
    _ingest(session)
    _bars(session, {})
    reason = data_readiness(session, SYMS, source=SRC, now=NOW)
    assert reason is not None and reason.startswith("stale feed")


def test_readiness_blocks_on_failed_or_old_ingest(session: Session) -> None:
    _feed(session, stale=False)
    _bars(session, {})
    _ingest(session, status="partial")
    assert "not ok" in (data_readiness(session, SYMS, source=SRC, now=NOW) or "")

    # the same latest run, ok but finished too long ago, is still a block
    latest = session.scalar(select(IngestionRun).order_by(IngestionRun.started_at.desc()))
    assert latest is not None
    latest.status = "ok"
    latest.finished_at = NOW - timedelta(hours=30)
    session.flush()
    assert "older than" in (data_readiness(session, SYMS, source=SRC, now=NOW) or "")


def test_readiness_blocks_on_incomplete_bars(session: Session) -> None:
    _feed(session, stale=False)
    _ingest(session)
    # two of four symbols never got the newest session's bar -> 50% coverage
    _bars(session, {"CCC": TODAY - timedelta(days=1), "DDD": TODAY - timedelta(days=1)})
    reason = data_readiness(session, SYMS, source=SRC, now=NOW) or ""
    assert reason.startswith("incomplete data") and "CCC" in reason and "DDD" in reason


def test_readiness_blocks_on_old_bars(session: Session) -> None:
    _feed(session, stale=False)
    _ingest(session)
    _bars(session, dict.fromkeys(SYMS, TODAY - timedelta(days=8)))
    assert "older than 5 days" in (data_readiness(session, SYMS, source=SRC, now=NOW) or "")


def test_readiness_ignores_an_unrelated_stale_feed(session: Session) -> None:
    """Only the source's daily-bar feed gates this scan; a stale options feed
    must not block it forever (the alert dispatcher's any-feed gate is separate)."""
    _ready(session)
    session.add(
        DataFeedStatus(
            provider="massive_options",
            feed_type=FeedType.OPTIONS_CHAIN,
            latency_category=LatencyCategory.DELAYED,
            last_success_at=NOW - timedelta(days=30),
            updated_at=NOW,
        )
    )
    session.flush()
    assert data_readiness(session, SYMS, source=SRC, now=NOW) is None


def test_readiness_is_independent_per_universe(session: Session) -> None:
    """A stale/incomplete universe must never block a healthy one — the gate
    is evaluated over each approved universe's OWN symbols."""
    _feed(session, stale=False)
    _ingest(session)
    _bars(session, {})  # SYMS current
    _bars(session, dict.fromkeys(OTHER_SYMS, TODAY - timedelta(days=40)), symbols=OTHER_SYMS)
    assert data_readiness(session, SYMS, source=SRC, now=NOW) is None
    assert "older than 5 days" in (data_readiness(session, OTHER_SYMS, source=SRC, now=NOW) or "")


# --------------------------------------------------------------------------
# grouping: per strategy version, by (snapshot, horizon, source)
# --------------------------------------------------------------------------


def test_approved_horizons_excludes_intraday(session: Session) -> None:
    for h, st in (
        (Horizon.INTRADAY, StrategyStatus.PAPER_APPROVED),
        (Horizon.SHORT_SWING, StrategyStatus.PAPER_APPROVED),
        (Horizon.MEDIUM_SWING, StrategyStatus.EXPERIMENTAL),
    ):
        session.add(Strategy(name=f"s_{h.value}", horizon=h, status=st))
    session.flush()
    assert approved_horizons(session) == [Horizon.SHORT_SWING]


def test_groups_follow_the_intraday_operating_policy(session: Session) -> None:
    """INTRADAY is excluded by research.intraday_policy's single flag (default
    off), not by a hard-coded condition here — the same answer every other
    policy surface gives."""
    from signalforge.config.research import ResearchConfig

    off = ResearchConfig()
    on = off.model_copy(
        update={"intraday": off.intraday.model_copy(update={"operating_enabled": True})}
    )
    snap = _snapshot(session, "u4", SYMS)
    intra = _approve(session, name="intra", horizon=Horizon.INTRADAY, snapshot=snap)
    swing = _approve(session, name="swing", horizon=Horizon.SHORT_SWING, snapshot=snap)

    groups, skipped = approved_scan_groups(session, off)
    assert [g.strategy_version_ids for g in groups] == [(swing.id,)]
    assert skipped == []  # an INTRADAY version is out of scope, not "skipped"

    groups_on, _ = approved_scan_groups(session, on)
    assert {g.horizon for g in groups_on} == {Horizon.INTRADAY, Horizon.SHORT_SWING}
    assert {g.strategy_version_ids for g in groups_on} == {(intra.id,), (swing.id,)}


def test_versions_sharing_a_snapshot_and_horizon_are_one_group(session: Session) -> None:
    snap = _snapshot(session, "u4", SYMS)
    a = _approve(session, name="a", horizon=Horizon.SHORT_SWING, snapshot=snap)
    b = _approve(session, name="b", horizon=Horizon.SHORT_SWING, snapshot=snap)
    c = _approve(session, name="c", horizon=Horizon.MEDIUM_SWING, snapshot=snap)
    groups, _ = approved_scan_groups(session)
    assert len(groups) == 2
    by_horizon = {g.horizon: g for g in groups}
    assert by_horizon[Horizon.SHORT_SWING].strategy_version_ids == (a.id, b.id)
    assert by_horizon[Horizon.MEDIUM_SWING].strategy_version_ids == (c.id,)
    assert all(g.dataset_snapshot_id == snap.id for g in groups)
    assert all(list(g.symbols) == SYMS for g in groups)


def test_two_snapshots_make_two_groups_each_on_its_own_universe(session: Session) -> None:
    small = _snapshot(session, "u4", SYMS)
    big = _snapshot(session, "u6", OTHER_SYMS)
    a = _approve(session, name="a", horizon=Horizon.MEDIUM_SWING, snapshot=small)
    b = _approve(session, name="b", horizon=Horizon.MEDIUM_SWING, snapshot=big)
    groups, _ = approved_scan_groups(session)
    by_snap = {g.dataset_snapshot_id: g for g in groups}
    assert set(by_snap) == {small.id, big.id}
    assert by_snap[small.id].strategy_version_ids == (a.id,)
    assert list(by_snap[small.id].symbols) == SYMS
    assert by_snap[big.id].strategy_version_ids == (b.id,)
    assert list(by_snap[big.id].symbols) == OTHER_SYMS


def test_only_the_newest_approved_scope_decides_the_universe(session: Session) -> None:
    """An older passing evaluation on a superseded dataset must not keep
    pulling the scan back onto the old universe."""
    old = _snapshot(session, "old", SYMS)
    new = _snapshot(session, "new", OTHER_SYMS)
    ver = _approve(
        session,
        name="a",
        horizon=Horizon.SHORT_SWING,
        snapshot=old,
        evaluated_at=NOW - timedelta(days=30),
    )
    session.add(
        StrategyPromotionEvaluation(
            strategy_version_id=ver.id,
            dataset_snapshot_id=new.id,
            evaluated_at=NOW,
            config_hash="cfg-hash",
            spec_json_hash="spec-a",
            universe_json=list(OTHER_SYMS),
            window_start=date(2020, 1, 1),
            window_end=date(2026, 1, 1),
            data_provenance_json={"sources": [SRC]},
            passed=True,
        )
    )
    session.flush()
    groups, _ = approved_scan_groups(session)
    assert len(groups) == 1
    assert groups[0].dataset_snapshot_id == new.id and list(groups[0].symbols) == OTHER_SYMS


@pytest.mark.parametrize(
    ("kwargs", "fragment"),
    [
        ({"with_evaluation": False}, "no passing promotion evaluation"),
        ({"passed": False}, "no passing promotion evaluation"),
        ({"snapshot": None}, "no dataset snapshot"),
        ({"source": None}, "0 sources"),
        ({"universe": ["ZZZ"]}, "disagrees with dataset snapshot"),
    ],
)
def test_a_version_whose_scope_can_never_match_is_skipped_with_a_reason(
    session: Session, kwargs: dict[str, Any], fragment: str
) -> None:
    snap = _snapshot(session, "u4", SYMS)
    ver = _approve(
        session, name="a", horizon=Horizon.SHORT_SWING, **{"snapshot": snap, **kwargs}  # type: ignore[arg-type]
    )
    groups, skipped = approved_scan_groups(session)
    assert groups == []
    assert len(skipped) == 1
    assert skipped[0]["strategy_version_id"] == ver.id
    assert fragment in skipped[0]["reason"]


def test_an_empty_snapshot_is_skipped(session: Session) -> None:
    snap = _snapshot(session, "empty", [])
    _approve(session, name="a", horizon=Horizon.SHORT_SWING, snapshot=snap)
    groups, skipped = approved_scan_groups(session)
    assert groups == [] and "has no symbols" in skipped[0]["reason"]


def test_approved_universes_collapse_horizons_of_one_dataset(session: Session) -> None:
    snap = _snapshot(session, "u4", SYMS)
    _approve(session, name="a", horizon=Horizon.SHORT_SWING, snapshot=snap)
    _approve(session, name="b", horizon=Horizon.MEDIUM_SWING, snapshot=snap)
    universes, _ = approved_universes(session)
    assert len(universes) == 1
    assert universes[0].dataset_snapshot_id == snap.id
    assert universes[0].horizons == ("MEDIUM_SWING", "SHORT_SWING")


# --------------------------------------------------------------------------
# running the scan
# --------------------------------------------------------------------------


class _FakeResult:
    def __init__(self, horizon: Horizon, symbols: list[str], source: str) -> None:
        self.horizon = horizon
        self.scanned = list(symbols)
        self.universe = list(symbols)
        self.source = source


class _FakeRun:
    def __init__(self, result: _FakeResult, snapshot_id: int | None, run_id: int = 7) -> None:
        self.id = run_id
        self.candidate_count = 0
        self.no_trade_count = len(result.scanned)
        self.dataset_snapshot_id = snapshot_id
        self.source = result.source
        self.universe_json = list(result.universe)


def _fake_scan(
    monkeypatch: pytest.MonkeyPatch, snapshots: dict[frozenset[str], int]
) -> list[_FakeResult]:
    """Record every run_scan call and persist it onto the snapshot its exact
    symbol set resolves to — what the real get_or_create_dataset_snapshot does."""
    seen: list[_FakeResult] = []
    counter = {"n": 100}

    def fake_run_scan(
        sess: Session, horizon: Horizon, *, symbols: list[str], source: str
    ) -> _FakeResult:
        res = _FakeResult(horizon, symbols, source)
        seen.append(res)
        return res

    def fake_persist(sess: Session, res: _FakeResult) -> _FakeRun:
        counter["n"] += 1
        return _FakeRun(res, snapshots.get(frozenset(res.universe)), run_id=counter["n"])

    monkeypatch.setattr(mod, "run_scan", fake_run_scan)
    monkeypatch.setattr(mod, "persist_scan", fake_persist)
    return seen


def test_run_with_no_approved_strategy_is_blocked(session: Session) -> None:
    report = run_approved_scope_scan(session, now=NOW)
    assert report.ran is False and "no PAPER_APPROVED" in (report.blocked_reason or "")
    row = session.scalar(select(AuditLog).where(AuditLog.action == AUDIT_BLOCKED))
    assert row is not None and row.after_json["reason"] == report.blocked_reason


def test_run_blocked_when_no_approved_version_has_a_usable_scope(session: Session) -> None:
    _approve(session, name="a", horizon=Horizon.SHORT_SWING, snapshot=None, with_evaluation=False)
    report = run_approved_scope_scan(session, now=NOW)
    assert report.ran is False
    assert "usable approved scope" in (report.blocked_reason or "")
    assert len(report.skipped_versions) == 1


def test_run_records_blocked_audit_without_scanning(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    snap = _snapshot(session, "u4", SYMS)
    _approve(session, name="a", horizon=Horizon.SHORT_SWING, snapshot=snap)
    seen = _fake_scan(monkeypatch, {frozenset(SYMS): snap.id})

    report = run_approved_scope_scan(session, now=NOW)  # no feed -> blocked
    assert report.ran is False and report.blocked_reason
    assert seen == []
    row = session.scalar(select(AuditLog).where(AuditLog.action == AUDIT_BLOCKED))
    assert row is not None and row.after_json["reason"] == report.blocked_reason
    assert row.after_json["dataset_snapshot_id"] == snap.id


def test_run_scans_exact_dataset_when_ready(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Single-snapshot behaviour: exactly one scan, on the approved symbols."""
    _ready(session)
    snap = _snapshot(session, "u4", SYMS)
    ver = _approve(session, name="a", horizon=Horizon.SHORT_SWING, snapshot=snap)
    seen = _fake_scan(monkeypatch, {frozenset(SYMS): snap.id})

    report = run_approved_scope_scan(session, now=NOW)
    assert report.ran is True
    assert len(seen) == 1
    assert seen[0].horizon is Horizon.SHORT_SWING
    assert seen[0].universe == SYMS and seen[0].source == SRC
    # report shape: the single-universe fields stay populated as before
    assert report.dataset_snapshot_id == snap.id and report.dataset_key == "u4"
    assert report.n_symbols == len(SYMS) and report.horizons == ["SHORT_SWING"]
    assert report.blocked_universes == [] and report.skipped_versions == []
    assert report.runs[0] == {
        "horizon": "SHORT_SWING",
        "scan_run_id": 101,
        "scanned": 4,
        "candidates": 0,
        "no_trade": 4,
        "dataset_snapshot_id": snap.id,
        "dataset_key": "u4",
        "n_symbols": 4,
        "source": SRC,
        "strategy_version_ids": [ver.id],
    }
    row = session.scalar(select(AuditLog).where(AuditLog.action == AUDIT_COMPLETED))
    assert row is not None and row.after_json["runs"][0]["horizon"] == "SHORT_SWING"


def test_two_snapshots_are_each_scanned_on_their_own_symbols(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _feed(session, stale=False)
    _ingest(session)
    _bars(session, {})
    _bars(session, {}, symbols=OTHER_SYMS)
    small = _snapshot(session, "u4", SYMS)
    big = _snapshot(session, "u6", OTHER_SYMS)
    v_small = _approve(session, name="a", horizon=Horizon.SHORT_SWING, snapshot=small)
    v_big = _approve(session, name="b", horizon=Horizon.MEDIUM_SWING, snapshot=big)
    seen = _fake_scan(monkeypatch, {frozenset(SYMS): small.id, frozenset(OTHER_SYMS): big.id})

    report = run_approved_scope_scan(session, now=NOW)
    assert report.ran is True and len(report.runs) == 2
    assert {tuple(r.universe) for r in seen} == {tuple(SYMS), tuple(OTHER_SYMS)}
    by_snap = {r["dataset_snapshot_id"]: r for r in report.runs}
    assert by_snap[small.id]["strategy_version_ids"] == [v_small.id]
    assert by_snap[small.id]["n_symbols"] == 4 and by_snap[small.id]["horizon"] == "SHORT_SWING"
    assert by_snap[big.id]["strategy_version_ids"] == [v_big.id]
    assert by_snap[big.id]["n_symbols"] == 6 and by_snap[big.id]["horizon"] == "MEDIUM_SWING"
    # two universes -> no single report-level snapshot identity
    assert report.dataset_snapshot_id is None and report.dataset_key is None
    assert report.n_symbols == len(SYMS) + len(OTHER_SYMS)
    assert sorted(report.horizons) == ["MEDIUM_SWING", "SHORT_SWING"]
    # every group's scan run id is reported, so auto_simulate sees them all
    assert sorted(int(r["scan_run_id"]) for r in report.runs) == [101, 102]


def test_a_blocked_universe_does_not_block_the_other(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _feed(session, stale=False)
    _ingest(session)
    _bars(session, {})  # SYMS current
    # OTHER_SYMS stale: their newest bar is far older than MAX_BAR_AGE_DAYS
    _bars(session, dict.fromkeys(OTHER_SYMS, TODAY - timedelta(days=40)), symbols=OTHER_SYMS)
    small = _snapshot(session, "u4", SYMS)
    big = _snapshot(session, "u6", OTHER_SYMS)
    v_small = _approve(session, name="a", horizon=Horizon.SHORT_SWING, snapshot=small)
    _approve(session, name="b", horizon=Horizon.MEDIUM_SWING, snapshot=big)
    seen = _fake_scan(monkeypatch, {frozenset(SYMS): small.id, frozenset(OTHER_SYMS): big.id})

    report = run_approved_scope_scan(session, now=NOW)
    assert report.ran is True
    assert [tuple(r.universe) for r in seen] == [tuple(SYMS)]
    assert [r["strategy_version_ids"] for r in report.runs] == [[v_small.id]]
    assert len(report.blocked_universes) == 1
    blocked = report.blocked_universes[0]
    assert blocked["dataset_snapshot_id"] == big.id and blocked["dataset_key"] == "u6"
    assert "older than 5 days" in blocked["reason"]
    # both audit rows exist: the blocked universe AND the completed scan
    actions = set(session.scalars(select(AuditLog.action)).all())
    assert {AUDIT_BLOCKED, AUDIT_COMPLETED} <= actions


def test_every_universe_blocked_means_not_run(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _feed(session, stale=False)
    _ingest(session)
    _bars(session, dict.fromkeys(SYMS, TODAY - timedelta(days=40)))
    _bars(session, dict.fromkeys(OTHER_SYMS, TODAY - timedelta(days=40)), symbols=OTHER_SYMS)
    small = _snapshot(session, "u4", SYMS)
    big = _snapshot(session, "u6", OTHER_SYMS)
    _approve(session, name="a", horizon=Horizon.SHORT_SWING, snapshot=small)
    _approve(session, name="b", horizon=Horizon.MEDIUM_SWING, snapshot=big)
    seen = _fake_scan(monkeypatch, {frozenset(SYMS): small.id, frozenset(OTHER_SYMS): big.id})

    report = run_approved_scope_scan(session, now=NOW)
    assert report.ran is False and seen == []
    assert len(report.blocked_universes) == 2
    assert "u4" in (report.blocked_reason or "") and "u6" in (report.blocked_reason or "")


def test_enforce_readiness_false_scans_a_stale_universe(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    snap = _snapshot(session, "u4", SYMS)
    _approve(session, name="a", horizon=Horizon.SHORT_SWING, snapshot=snap)
    seen = _fake_scan(monkeypatch, {frozenset(SYMS): snap.id})
    report = run_approved_scope_scan(session, now=NOW, enforce_readiness=False)
    assert report.ran is True and len(seen) == 1 and report.blocked_universes == []


def test_run_refuses_a_scan_that_resolved_a_different_snapshot(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The scan's own snapshot resolution must land on the approved row —
    otherwise every candidate would silently fail the scope match later."""
    _ready(session)
    snap = _snapshot(session, "u4", SYMS)
    _approve(session, name="a", horizon=Horizon.SHORT_SWING, snapshot=snap)
    _fake_scan(monkeypatch, {frozenset(SYMS): 999})  # resolves somewhere else

    with pytest.raises(RuntimeError, match=f"expected approved snapshot {snap.id}"):
        run_approved_scope_scan(session, now=NOW)
    row = session.scalar(
        select(AuditLog)
        .where(AuditLog.action == AUDIT_BLOCKED)
        .order_by(AuditLog.id.desc())
        .limit(1)
    )
    assert row is not None and "dataset_snapshot_id=999" in row.after_json["reason"]


def test_run_refuses_a_scan_that_recorded_a_different_source(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ready(session)
    snap = _snapshot(session, "u4", SYMS)
    _approve(session, name="a", horizon=Horizon.SHORT_SWING, snapshot=snap)
    _fake_scan(monkeypatch, {frozenset(SYMS): snap.id})

    def wrong_source(sess: Session, res: _FakeResult) -> _FakeRun:
        run = _FakeRun(res, snap.id)
        run.source = "some_other_provider"
        return run

    monkeypatch.setattr(mod, "persist_scan", wrong_source)
    with pytest.raises(RuntimeError, match="expected the approved source"):
        run_approved_scope_scan(session, now=NOW)


def test_universe_readiness_reports_one_row_per_universe(session: Session) -> None:
    _feed(session, stale=False)
    _ingest(session)
    _bars(session, {})
    _bars(session, dict.fromkeys(OTHER_SYMS, TODAY - timedelta(days=40)), symbols=OTHER_SYMS)
    small = _snapshot(session, "u4", SYMS)
    big = _snapshot(session, "u6", OTHER_SYMS)
    _approve(session, name="a", horizon=Horizon.SHORT_SWING, snapshot=small)
    _approve(session, name="b", horizon=Horizon.MEDIUM_SWING, snapshot=big)
    rows = universe_readiness(session, approved_universes(session)[0], now=NOW)
    assert [(r["dataset_key"], r["ready"]) for r in rows] == [("u4", True), ("u6", False)]
    assert rows[0]["n_symbols"] == 4 and rows[1]["n_symbols"] == 6


# --------------------------------------------------------------------------
# end-to-end: the candidates really do match their own version's scope
# --------------------------------------------------------------------------


def _ingest_fixture_universe(session: Session, symbols: list[str]) -> tuple[str, datetime, date]:
    from signalforge.data.adapters.fixture import FixtureMarketDataAdapter
    from signalforge.data.ingest import ingest_universe

    adapter = FixtureMarketDataAdapter()
    as_of = date(2024, 6, 30)
    now = datetime(2024, 7, 1, 21, 45, tzinfo=UTC)
    ingest_universe(session, adapter, symbols, as_of - timedelta(days=365 * 3), as_of)
    return adapter.provider_name, now, as_of


def test_real_run_scan_resolves_the_approved_snapshot_end_to_end(session: Session) -> None:
    """Integration: the un-mocked run_scan/persist_scan on the approved symbol
    set resolves the SAME DataSnapshot row the approval was keyed on."""
    from signalforge.research.promotion import get_or_create_dataset_snapshot

    universe = ["SPY", "AAPL", "MSFT", "NVDA", "XOM"]
    src, now, as_of = _ingest_fixture_universe(session, universe)
    session.add(
        IngestionRun(
            provider=src,
            feed_type=FeedType.BAR_DAILY,
            requested_start=as_of - timedelta(days=365 * 3),
            requested_end=as_of,
            status="ok",
            started_at=now - timedelta(hours=2),
            finished_at=now - timedelta(hours=1),
        )
    )
    snap = get_or_create_dataset_snapshot(session, key="universe_5_test", symbols=universe)
    _approve(
        session, name="s", horizon=Horizon.SHORT_SWING, snapshot=snap, source=src, universe=universe
    )
    assert data_readiness(session, universe, source=src, now=now) is None

    report = run_approved_scope_scan(session, now=now)
    assert report.ran is True and report.runs
    assert all(r["dataset_snapshot_id"] == snap.id for r in report.runs)
    assert all(r["source"] == src for r in report.runs)


def test_each_versions_candidates_match_only_its_own_scope(session: Session) -> None:
    """Two approved versions on two different dataset snapshots: every scan
    run (and every candidate on it) must satisfy research.approval_scope's
    five-part match for ITS OWN version and fail it for the other one."""
    from signalforge.research.approval_scope import approved_scopes, scan_scope_matches
    from signalforge.research.persistence import spec_json_hash, upsert_strategy_version
    from signalforge.research.promotion import get_or_create_dataset_snapshot
    from signalforge.research.strategies import default_strategies
    from signalforge.settings_store import effective_research_config

    universe_a = ["SPY", "AAPL", "MSFT", "NVDA", "XOM"]
    universe_b = ["KO", "PEP", "JNJ", "PG", "MRK", "CVX", "WMT"]
    src, now, as_of = _ingest_fixture_universe(session, universe_a + universe_b)
    session.add(
        IngestionRun(
            provider=src,
            feed_type=FeedType.BAR_DAILY,
            requested_start=as_of - timedelta(days=365 * 3),
            requested_end=as_of,
            status="ok",
            started_at=now - timedelta(hours=2),
            finished_at=now - timedelta(hours=1),
        )
    )
    snap_a = get_or_create_dataset_snapshot(session, key="snap_a", symbols=universe_a)
    snap_b = get_or_create_dataset_snapshot(session, key="snap_b", symbols=universe_b)
    live_config_hash = effective_research_config(session).config_hash

    # Two REAL strategies, so current_spec_json_hash resolves to a live spec:
    # one approved on snapshot A, the other on snapshot B.
    specs = {s.spec().name: s.spec() for s in default_strategies()}
    plan = [
        ("trend_continuation.short_swing", snap_a, universe_a),
        ("relative_strength.medium_swing", snap_b, universe_b),
    ]
    version_ids: dict[int, int] = {}  # dataset_snapshot_id -> strategy_version_id
    for name, snap, universe in plan:
        spec = specs[name]
        ver = upsert_strategy_version(session, spec)
        ver.status = StrategyStatus.PAPER_APPROVED
        strat = session.get(Strategy, ver.strategy_id)
        assert strat is not None
        strat.status = StrategyStatus.PAPER_APPROVED
        session.add(
            StrategyPromotionEvaluation(
                strategy_version_id=ver.id,
                dataset_snapshot_id=snap.id,
                evaluated_at=now,
                config_hash=live_config_hash,
                spec_json_hash=spec_json_hash(spec),
                universe_json=list(universe),
                window_start=date(2021, 1, 1),
                window_end=as_of,
                data_provenance_json={"sources": [src]},
                passed=True,
            )
        )
        session.flush()
        version_ids[snap.id] = ver.id

    report = run_approved_scope_scan(session, now=now)
    assert report.ran is True and len(report.runs) == 2

    def _matches(run: ScanRun, version_id: int) -> bool:
        from signalforge.research.approval_scope import current_spec_json_hash

        live_spec = current_spec_json_hash(session, version_id)
        assert live_spec is not None
        return scan_scope_matches(
            approved_scopes(session, version_id),
            dataset_snapshot_id=run.dataset_snapshot_id,
            config_hash=run.config_hash,
            spec_json_hash=live_spec,
            source=run.source,
            universe=frozenset(x.upper() for x in (run.universe_json or ())),
        )

    for entry in report.runs:
        run = session.get(ScanRun, int(entry["scan_run_id"]))
        assert run is not None
        own = version_ids[int(entry["dataset_snapshot_id"])]
        other = next(v for k, v in version_ids.items() if v != own)
        assert _matches(run, own) is True, f"run {run.id} is out of scope for its own version"
        assert _matches(run, other) is False, f"run {run.id} wrongly matched the other version"
        # and every candidate this run produced for one of the two approved
        # versions inherits exactly that verdict
        approved_ids = set(version_ids.values())
        for cand in session.scalars(select(Candidate).where(Candidate.scan_run_id == run.id)):
            if cand.strategy_version_id in approved_ids:
                assert _matches(run, cand.strategy_version_id) is (cand.strategy_version_id == own)
