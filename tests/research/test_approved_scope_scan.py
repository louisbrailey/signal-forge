"""The scheduled approved-scope scan: hard data-readiness gate, exact
approved dataset, EOD-only, and an audit row either way."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from signalforge.db.models import (
    AuditLog,
    DataFeedStatus,
    IngestionRun,
    Instrument,
    OHLCVDaily,
    Strategy,
)
from signalforge.domain import FeedType, Horizon, LatencyCategory, StrategyStatus
from signalforge.research import approved_scope_scan as mod
from signalforge.research.approved_scope_scan import (
    AUDIT_BLOCKED,
    AUDIT_COMPLETED,
    approved_horizons,
    data_readiness,
    run_approved_scope_scan,
)

NOW = datetime(2026, 9, 9, 22, 0, tzinfo=UTC)
SYMS = ["AAA", "BBB", "CCC", "DDD"]
SRC = "massive"


def _feed(session: Session, *, stale: bool) -> None:
    session.add(
        DataFeedStatus(
            provider=SRC,
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
            requested_start=date(2026, 8, 1),
            requested_end=date(2026, 9, 9),
            status=status,
            started_at=NOW - age - timedelta(minutes=5),
            finished_at=NOW - age,
        )
    )
    session.flush()


def _bars(session: Session, latest: dict[str, date]) -> None:
    for sym in SYMS:
        inst = Instrument(symbol=sym, name=sym)
        session.add(inst)
        session.flush()
        for d in (date(2026, 8, 20), latest.get(sym, date(2026, 9, 9))):
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
    # two of four symbols never got the 09-09 bar -> 50% coverage
    _bars(session, {"CCC": date(2026, 9, 8), "DDD": date(2026, 9, 8)})
    reason = data_readiness(session, SYMS, source=SRC, now=NOW) or ""
    assert reason.startswith("incomplete data") and "CCC" in reason and "DDD" in reason


def test_readiness_blocks_on_old_bars(session: Session) -> None:
    _feed(session, stale=False)
    _ingest(session)
    _bars(session, dict.fromkeys(SYMS, date(2026, 9, 1)))
    assert "older than 5 days" in (data_readiness(session, SYMS, source=SRC, now=NOW) or "")


def test_approved_horizons_excludes_intraday(session: Session) -> None:
    for h, st in (
        (Horizon.INTRADAY, StrategyStatus.PAPER_APPROVED),
        (Horizon.SHORT_SWING, StrategyStatus.PAPER_APPROVED),
        (Horizon.MEDIUM_SWING, StrategyStatus.EXPERIMENTAL),
    ):
        session.add(Strategy(name=f"s_{h.value}", horizon=h, status=st))
    session.flush()
    assert approved_horizons(session) == [Horizon.SHORT_SWING]


def test_run_records_blocked_audit_without_scanning(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    session.add(
        Strategy(name="s", horizon=Horizon.SHORT_SWING, status=StrategyStatus.PAPER_APPROVED)
    )
    session.flush()
    monkeypatch.setattr(mod, "resolve_variant", lambda s, *, variant: (SYMS, _FakeSnap()))
    called: list[str] = []
    monkeypatch.setattr(mod, "run_scan", lambda *a, **k: called.append("scan"))

    report = run_approved_scope_scan(session, source=SRC, now=NOW)  # no feed -> blocked
    assert report.ran is False and report.blocked_reason
    assert called == []
    row = session.scalar(select(AuditLog).where(AuditLog.action == AUDIT_BLOCKED))
    assert row is not None and row.after_json["reason"] == report.blocked_reason


def test_run_scans_exact_dataset_when_ready(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ready(session)
    session.add(
        Strategy(name="s", horizon=Horizon.SHORT_SWING, status=StrategyStatus.PAPER_APPROVED)
    )
    session.flush()
    monkeypatch.setattr(mod, "resolve_variant", lambda s, *, variant: (SYMS, _FakeSnap()))
    seen: dict[str, object] = {}

    def fake_run_scan(sess, horizon, *, symbols, source):
        seen.update(horizon=horizon, symbols=list(symbols), source=source)
        return _FakeResult()

    monkeypatch.setattr(mod, "run_scan", fake_run_scan)
    monkeypatch.setattr(mod, "persist_scan", lambda sess, res: _FakeRun())

    report = run_approved_scope_scan(session, source=SRC, now=NOW)
    assert report.ran is True
    assert seen == {"horizon": Horizon.SHORT_SWING, "symbols": SYMS, "source": SRC}
    assert report.dataset_snapshot_id == 42 and report.dataset_key == "universe_ex_meta"
    row = session.scalar(select(AuditLog).where(AuditLog.action == AUDIT_COMPLETED))
    assert row is not None and row.after_json["runs"][0]["horizon"] == "SHORT_SWING"


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


def test_run_refuses_a_scan_that_resolved_a_different_snapshot(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The scan's own snapshot resolution must land on the approved row —
    otherwise every candidate would silently fail the scope match later."""
    _ready(session)
    session.add(
        Strategy(name="s", horizon=Horizon.SHORT_SWING, status=StrategyStatus.PAPER_APPROVED)
    )
    session.flush()
    monkeypatch.setattr(mod, "resolve_variant", lambda s, *, variant: (SYMS, _FakeSnap()))
    monkeypatch.setattr(mod, "run_scan", lambda *a, **k: _FakeResult())

    class _WrongRun(_FakeRun):
        dataset_snapshot_id = 99

    monkeypatch.setattr(mod, "persist_scan", lambda sess, res: _WrongRun())
    with pytest.raises(RuntimeError, match="expected approved snapshot 42"):
        run_approved_scope_scan(session, source=SRC, now=NOW)
    row = session.scalar(select(AuditLog).where(AuditLog.action == AUDIT_BLOCKED))
    assert row is not None and "dataset_snapshot_id=99" in row.after_json["reason"]


def test_real_run_scan_resolves_the_approved_snapshot_end_to_end(session: Session) -> None:
    """Integration: the un-mocked run_scan/persist_scan on the approved symbol
    set resolves the SAME DataSnapshot row the approval was keyed on."""
    from signalforge.data.adapters.fixture import FixtureMarketDataAdapter
    from signalforge.data.ingest import ingest_universe
    from signalforge.research.fb_meta_universe_comparison import resolve_variant
    from signalforge.research.promotion import get_or_create_dataset_snapshot

    adapter = FixtureMarketDataAdapter()
    src = adapter.provider_name
    universe = ["SPY", "AAPL", "MSFT", "NVDA", "XOM"]
    as_of = date(2024, 6, 30)
    now = datetime(2024, 7, 1, 21, 45, tzinfo=UTC)
    ingest_universe(session, adapter, universe, as_of - timedelta(days=365 * 3), as_of)
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
    session.add(
        Strategy(name="s", horizon=Horizon.SHORT_SWING, status=StrategyStatus.PAPER_APPROVED)
    )
    session.flush()
    snap = get_or_create_dataset_snapshot(session, key="universe_5_test", symbols=universe)
    assert data_readiness(session, universe, source=src, now=now) is None

    # the real resolve_variant needs the configured universe; pin it for this test
    real = resolve_variant

    def _pinned(s: Session, *, variant: str):  # type: ignore[no-untyped-def]
        assert variant == "ex_meta"
        return universe, snap

    mod.resolve_variant = _pinned  # type: ignore[assignment]
    try:
        report = run_approved_scope_scan(session, source=src, now=now)
    finally:
        mod.resolve_variant = real  # type: ignore[assignment]
    assert report.ran is True and report.runs
    assert all(r["dataset_snapshot_id"] == snap.id for r in report.runs)


def test_run_with_no_approved_strategy_is_blocked(session: Session) -> None:
    report = run_approved_scope_scan(session, source=SRC, now=NOW)
    assert report.ran is False and "no PAPER_APPROVED" in (report.blocked_reason or "")


class _FakeSnap:
    id = 42
    key = "universe_ex_meta"


class _FakeResult:
    scanned = SYMS


class _FakeRun:
    id = 7
    candidate_count = 0
    no_trade_count = 4
    dataset_snapshot_id = 42
