"""Regressions for the 2026-10-14..24 paper-trading stall.

Three defects kept the paper books from trading for most of two weeks:

1. The scanner treated a session as "current" from 17:30 ET while paper
   acceptance used the 16:00 close. A catch-up scan at 17:28 ET produced six
   candidates on the previous session that acceptance then refused, and those
   refusals are immutable — the day's signals were spent.
2. The provider published the day's bars hours after the 17:30 EOD job. The
   ingest fetched every symbol, wrote 0 bars, recorded ``ok``, and catch-up
   then treated the session as covered, so nothing retried until the next day.
3. ``universe_update`` fired alongside the EOD unit after a wake, spent the same
   provider rate limit (HTTP 429) and held the SQLite write lock, so the EOD
   ingest failed with "database is locked".

No network; the autouse ``isolated_data_dir`` fixture isolates every DB.
"""

from __future__ import annotations

import threading
import types
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

import signalforge.scheduler as sched
from signalforge.data.adapters.base import DailyBar, LatencyCategory, Provenance
from signalforge.data.calendar import last_closed_session
from signalforge.db.models import IngestionRun, JobRun
from signalforge.db.session import session_scope
from signalforge.paper.ledger import _completed_market_date

pytestmark = pytest.mark.safety


def _et(y: int, m: int, d: int, hh: int, mm: int) -> datetime:
    return datetime(y, m, d, hh, mm, tzinfo=ZoneInfo("America/New_York")).astimezone(UTC)


# --------------------------------------------------------------------------- #
# 1. One definition of the current completed session
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (_et(2024, 6, 12, 15, 59), date(2024, 6, 11)),  # before the close
        (_et(2024, 6, 12, 16, 0), date(2024, 6, 12)),  # at the close
        (_et(2024, 6, 12, 17, 28), date(2024, 6, 12)),  # the incident window
        (_et(2024, 6, 15, 12, 0), date(2024, 6, 14)),  # Saturday -> Friday
        (_et(2024, 11, 29, 13, 30), date(2024, 11, 29)),  # early close at 13:00
        (_et(2024, 7, 4, 18, 0), date(2024, 7, 3)),  # holiday -> previous session
    ],
)
def test_last_closed_session(now: datetime, expected: date) -> None:
    assert last_closed_session(now) == expected


def test_paper_acceptance_uses_the_shared_session_definition() -> None:
    now = _et(2024, 6, 12, 9, 0)
    for _ in range(48):  # every 30 minutes across a full day
        assert _completed_market_date(now) == last_closed_session(now)
        now += timedelta(minutes=30)


def test_scan_between_close_and_publication_emits_no_candidates_on_the_old_session(
    session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fixture bars end Friday 2024-06-28. At Monday 17:00 ET Monday's session
    has closed, so a live scan must exclude every symbol as stale rather than
    rank Friday's bars (the old 17:30 rule required only Friday's bar)."""
    import signalforge.research.scan as scan_module
    from signalforge.config import get_settings
    from signalforge.domain import Horizon
    from signalforge.research.scan import run_scan
    from tests.research.test_scan import UNIVERSE, _seed

    _seed(session, oos_expectancy_r=0.5)
    settings = get_settings().model_copy(update={"market_data_provider": "massive"})
    monkeypatch.setattr(
        scan_module,
        "gate_for_horizon",
        lambda *a, **k: types.SimpleNamespace(fresh=True, reasons=[]),
    )

    monkeypatch.setattr(scan_module, "utcnow", lambda: _et(2024, 7, 1, 17, 0))
    after_close = run_scan(session, Horizon.SHORT_SWING, settings=settings, symbols=UNIVERSE)
    assert after_close.excluded.get("stale_or_unavailable_feed") == UNIVERSE
    assert not after_close.candidates

    # Control: before Monday's close Friday IS the current session.
    monkeypatch.setattr(scan_module, "utcnow", lambda: _et(2024, 7, 1, 15, 0))
    before_close = run_scan(session, Horizon.SHORT_SWING, settings=settings, symbols=UNIVERSE)
    assert "stale_or_unavailable_feed" not in before_close.excluded


# --------------------------------------------------------------------------- #
# 2. Publication probe
# --------------------------------------------------------------------------- #
class _ProbeAdapter:
    provider_name = "massive"

    def __init__(self, newest: date | None) -> None:
        self.newest = newest
        self.calls: list[tuple[str, date, date]] = []

    def fetch_daily_bars(self, symbol: str, start: date, end: date) -> list[DailyBar]:
        self.calls.append((symbol, start, end))
        if self.newest is None:
            return []
        prov = Provenance(
            source="massive",
            latency_category=LatencyCategory.END_OF_DAY,
            retrieved_at=datetime.now(UTC),
        )
        return [DailyBar(symbol, self.newest, 1.0, 1.0, 1.0, 1.0, 1.0, prov)]


_EVENING = _et(2024, 6, 12, 19, 0)  # after the 17:30 cutoff: 2024-06-12 is owed


@pytest.mark.parametrize("newest", [None, date(2024, 6, 11)])
def test_probe_refuses_when_the_session_is_not_published(newest: date | None) -> None:
    adapter = _ProbeAdapter(newest)
    with pytest.raises(sched.ProviderBarsNotPublished, match="2024-06-12"):
        sched._require_session_published(adapter, _EVENING)
    assert len(adapter.calls) == 1  # one request, not a full pass
    assert adapter.calls[0][0] == sched.PUBLICATION_PROBE_SYMBOL


def test_probe_passes_once_the_session_is_published() -> None:
    sched._require_session_published(_ProbeAdapter(date(2024, 6, 12)), _EVENING)


def test_probe_is_skipped_for_the_fixture_adapter() -> None:
    adapter = _ProbeAdapter(None)
    adapter.provider_name = "fixture"
    sched._require_session_published(adapter, _EVENING)
    assert adapter.calls == []


def test_job_ingest_fetches_and_records_nothing_when_unpublished(
    db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = _ProbeAdapter(None)
    monkeypatch.setattr(
        "signalforge.data.adapters.registry.get_primary_adapter", lambda settings: adapter
    )
    full_pass: list[object] = []
    monkeypatch.setattr(
        "signalforge.data.ingest.ingest_universe", lambda *a, **k: full_pass.append(a)
    )
    with pytest.raises(sched.ProviderBarsNotPublished):
        sched.job_ingest()
    assert full_pass == []
    with session_scope() as session:
        assert session.query(IngestionRun).count() == 0


def _failed_eod(started: datetime, detail: str) -> None:
    with session_scope(write=True) as session:
        session.add(
            JobRun(
                name="daily_eod_update",
                started_at=started,
                finished_at=started + timedelta(seconds=2),
                status="failed",
                detail=detail,
            )
        )


def test_catch_up_retries_soon_after_an_unpublished_probe(db_url: str) -> None:
    _failed_eod(
        _EVENING - timedelta(minutes=30),
        "ProviderBarsNotPublished('massive has not published the 2024-06-12 daily bar yet')",
    )
    pending, reason = sched.catch_up_pending(_EVENING)
    assert pending is True, reason


def test_catch_up_still_backs_off_after_a_real_failure(db_url: str) -> None:
    _failed_eod(_EVENING - timedelta(minutes=30), "AdapterError('HTTP 500')")
    pending, reason = sched.catch_up_pending(_EVENING)
    assert pending is False
    assert "backing off" in reason


# --------------------------------------------------------------------------- #
# 3. universe_update never overlaps the EOD unit
# --------------------------------------------------------------------------- #
def _disabled_pipeline(monkeypatch: pytest.MonkeyPatch) -> None:
    research = types.SimpleNamespace(universe_pipeline=types.SimpleNamespace(enabled=False))
    monkeypatch.setattr(
        "signalforge.settings_store.effective_research_config", lambda sess: research
    )


def test_universe_update_gives_up_while_the_eod_unit_holds_the_lock(
    db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    _disabled_pipeline(monkeypatch)
    monkeypatch.setattr(sched, "UNIVERSE_WAIT_FOR_EOD_S", 0.05)
    assert sched._EOD_UPDATE_LOCK.acquire(blocking=False)
    try:
        with pytest.raises(RuntimeError, match="EOD update still running"):
            sched.job_universe_update()
    finally:
        sched._EOD_UPDATE_LOCK.release()


def test_universe_update_waits_for_the_eod_unit_then_runs(
    db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    _disabled_pipeline(monkeypatch)
    assert sched._EOD_UPDATE_LOCK.acquire(blocking=False)
    threading.Timer(0.1, sched._EOD_UPDATE_LOCK.release).start()
    sched.job_universe_update()  # blocks until the timer releases the lock
    assert not sched._EOD_UPDATE_LOCK.locked()
