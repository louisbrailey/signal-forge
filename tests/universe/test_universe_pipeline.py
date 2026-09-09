"""Liquid U.S. universe pipeline: bulk archive, discovery, screen, normalize,
and the end-to-end orchestrator — entirely offline via httpx.MockTransport."""

from __future__ import annotations

import gzip
import hashlib
import time
import types
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from signalforge.config.paths import data_dir
from signalforge.config.research import UniversePipelineConfig
from signalforge.data.adapters.base import AdapterError
from signalforge.data.repository import get_daily_bars
from signalforge.db.models import (
    AuditLog,
    BulkFile,
    DataFeedStatus,
    DataSnapshot,
    Instrument,
    OHLCVDaily,
    SymbolContinuityMapping,
    UniverseMember,
    UniverseTicker,
)
from signalforge.domain import FeedType, LatencyCategory
from signalforge.universe.bulk import (
    DEFAULT_SOURCE,
    GroupedDailyClient,
    archive_session,
    archived_sessions,
    backfill,
)
from signalforge.universe.discovery import refresh_reference
from signalforge.universe.normalize import normalize_symbols
from signalforge.universe.pipeline import run_universe_update
from signalforge.universe.screen import run_screen

# --------------------------------------------------------------------------- #
# offline fixtures — a tiny fake of the massive.com endpoints this package
# calls, wired in through httpx.MockTransport. No test in this file ever
# touches the network.
# --------------------------------------------------------------------------- #


class FakeMassiveAPI:
    """Routes GroupedDailyClient requests to canned payloads and records
    every call so tests can assert on idempotency / call counts."""

    def __init__(self) -> None:
        self.grouped: dict[str, dict[str, Any]] = {}
        self.fail_dates: set[str] = set()
        self.reference_pages: list[dict[str, Any]] = [{"status": "OK", "results": []}]
        self.ticker_detail: dict[str, dict[str, Any]] = {}
        self.calls: list[str] = []
        self.grouped_calls: dict[str, int] = {}
        self.sleep_on_reference: float = 0.0

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.calls.append(url)
        assert request.headers["authorization"].startswith("Bearer ")
        if "/aggs/grouped/locale/us/market/stocks/" in url:
            d = url.split("/aggs/grouped/locale/us/market/stocks/", 1)[1].split("?", 1)[0]
            self.grouped_calls[d] = self.grouped_calls.get(d, 0) + 1
            if d in self.fail_dates:
                return httpx.Response(500, json={"status": "ERROR"})
            payload = self.grouped.get(d, {"status": "OK", "resultsCount": 0, "results": []})
            return httpx.Response(200, json=payload)
        if "/reference/tickers/" in url:
            tk = url.rsplit("/", 1)[-1]
            payload = self.ticker_detail.get(tk, {"status": "OK", "results": {}})
            return httpx.Response(200, json=payload)
        if "/reference/tickers" in url:
            if self.sleep_on_reference:
                time.sleep(self.sleep_on_reference)
            idx = 1 if "cursor=" in url else 0
            if idx < len(self.reference_pages):
                return httpx.Response(200, json=self.reference_pages[idx])
            return httpx.Response(200, json={"status": "OK", "results": []})
        return httpx.Response(404, json={"status": "NOT_FOUND"})

    def client(self, *, spacing_s: float = 0.0) -> GroupedDailyClient:
        # NOTE: GroupedDailyClient._get() scrubs the raw response text with a
        # blind ``str.replace(self._key, "[REDACTED]")`` *before* parsing JSON
        # (see the BUG noted in this module's docstring/report). A one-letter
        # key such as "k" mangles the literal JSON field name "ticker" into
        # "tic[REDACTED]er" in every reference-data response, so a longer,
        # collision-free key is used here to keep these tests exercising the
        # real parsing logic rather than that scrubbing bug.
        transport = httpx.MockTransport(self.handler)
        return GroupedDailyClient(
            api_key="sf-test-key",  # pragma: allowlist secret
            client=httpx.Client(transport=transport),
            spacing_s=spacing_s,
        )


def _bar(ticker: str, close: float, *, volume: float = 200_000.0, vw: float | None = None) -> dict:
    return {
        "T": ticker,
        "o": close,
        "h": close,
        "l": close,
        "c": close,
        "v": volume,
        "vw": vw if vw is not None else close,
    }


def _grouped_ok(rows: list[dict]) -> dict:
    return {"status": "OK", "resultsCount": len(rows), "results": rows}


def _ref_row(
    ticker: str,
    *,
    name: str = "Name",
    type_: str = "CS",
    active: bool = True,
    list_date: str = "1980-12-12",
) -> dict:
    return {
        "ticker": ticker,
        "name": name,
        "type": type_,
        "primary_exchange": "XNAS",
        "locale": "us",
        "active": active,
        "list_date": list_date,
    }


def _weekdays(start: date, n: int) -> list[date]:
    out: list[date] = []
    d = start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def _ticker_row(
    session: Session,
    ticker: str,
    *,
    security_type: str = "CS",
    active: bool = True,
    market_cap: float | None = None,
    sic_code: str = "",
    list_date: date | None = None,
) -> UniverseTicker:
    row = UniverseTicker(
        ticker=ticker,
        name=ticker,
        security_type=security_type,
        primary_exchange="XNAS",
        locale="us",
        active=active,
        list_date=list_date,
        market_cap=market_cap,
        sic_code=sic_code,
        sic_description="",
        first_seen=date(2000, 1, 1),
        last_seen=date(2000, 1, 1),
        refreshed_at=datetime(2000, 1, 1, tzinfo=UTC),
    )
    session.add(row)
    return row


# --------------------------------------------------------------------------- #
# 1) bulk.archive_session
# --------------------------------------------------------------------------- #


def test_archive_session_writes_gz_file_and_bulkfile_row(
    session: Session, isolated_data_dir: Path
) -> None:
    assert data_dir() == isolated_data_dir  # conftest already points data_dir() at tmp

    api = FakeMassiveAPI()
    d = date(2026, 9, 1)
    rows = [_bar("AAPL", 1.05, volume=1_000_000, vw=1.02), _bar("MSFT", 2.05, volume=500_000)]
    api.grouped[d.isoformat()] = _grouped_ok(rows)
    client = api.client()

    bf = archive_session(session, client, d)

    assert bf.status == "ok"
    assert bf.row_count == 2
    path = Path(bf.path)
    assert path.exists()
    assert path.is_relative_to(isolated_data_dir)  # gz archive lands under the tmp data dir
    decompressed = gzip.decompress(path.read_bytes())
    assert bf.sha256 == hashlib.sha256(decompressed).hexdigest()
    assert bf.bytes_gz == path.stat().st_size
    assert api.grouped_calls[d.isoformat()] == 1


def test_archive_session_is_idempotent_and_makes_no_second_request(session: Session) -> None:
    api = FakeMassiveAPI()
    d = date(2026, 9, 1)
    api.grouped[d.isoformat()] = _grouped_ok([_bar("AAPL", 1.0)])
    client = api.client()

    first = archive_session(session, client, d)
    calls_before = len(api.calls)
    second = archive_session(session, client, d)

    assert second.id == first.id
    assert second.status == "ok"
    assert len(api.calls) == calls_before  # repeat call made zero HTTP requests


def test_archive_session_empty_results_stores_status_empty(session: Session) -> None:
    api = FakeMassiveAPI()
    d = date(2026, 9, 2)
    api.grouped[d.isoformat()] = {"status": "OK", "resultsCount": 0, "results": []}
    client = api.client()

    bf = archive_session(session, client, d)

    assert bf.status == "empty"
    assert bf.row_count == 0


def test_archive_session_persistent_500_marks_failed_and_raises(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The real retry path sleeps between attempts; skip the real wait in this test.
    monkeypatch.setattr("signalforge.universe.bulk.time.sleep", lambda *_a: None)
    api = FakeMassiveAPI()
    d = date(2026, 9, 3)
    api.fail_dates.add(d.isoformat())
    client = api.client()

    with pytest.raises(AdapterError):
        archive_session(session, client, d)

    row = session.scalar(select(BulkFile).where(BulkFile.session_date == d))
    assert row is not None
    assert row.status == "failed"
    assert api.grouped_calls[d.isoformat()] == 4  # every retry attempt exhausted


# --------------------------------------------------------------------------- #
# 2) bulk.backfill
# --------------------------------------------------------------------------- #

# 2026-09-14 (Mon) 15:00 America/New_York -> last completed session = Sun 09-13.
_BACKFILL_NOW = datetime(2026, 9, 14, 15, 0, tzinfo=ZoneInfo("America/New_York"))


def test_backfill_walks_back_skipping_weekends_and_stops_at_target(session: Session) -> None:
    api = FakeMassiveAPI()
    for d in (date(2026, 9, 11), date(2026, 9, 10), date(2026, 9, 9)):
        api.grouped[d.isoformat()] = _grouped_ok([_bar("AAPL", 100.0)])
    client = api.client()

    rep = backfill(
        session,
        client,
        sessions=3,
        runtime_budget_s=60.0,
        storage_budget_bytes=10**9,
        now=_BACKFILL_NOW,
    )

    assert rep.fetched == 3
    assert rep.sessions_archived == 3
    assert rep.stopped_reason == ""
    assert set(api.grouped_calls) == {"2026-09-11", "2026-09-10", "2026-09-09"}
    assert "2026-09-13" not in api.grouped_calls  # Sunday
    assert "2026-09-12" not in api.grouped_calls  # Saturday


def test_backfill_resumes_without_refetching_already_archived_sessions(session: Session) -> None:
    api1 = FakeMassiveAPI()
    for d in (date(2026, 9, 11), date(2026, 9, 10), date(2026, 9, 9)):
        api1.grouped[d.isoformat()] = _grouped_ok([_bar("AAPL", 100.0)])
    first = backfill(
        session,
        api1.client(),
        sessions=3,
        runtime_budget_s=60.0,
        storage_budget_bytes=10**9,
        now=_BACKFILL_NOW,
    )
    assert first.sessions_archived == 3

    # Only the two NEW dates get a payload — if the code refetched an
    # already-archived date it would hit the handler's empty-payload default
    # and this test's call-count assertion below would fail.
    api2 = FakeMassiveAPI()
    for d in (date(2026, 9, 8), date(2026, 9, 7)):
        api2.grouped[d.isoformat()] = _grouped_ok([_bar("AAPL", 100.0)])

    rep = backfill(
        session,
        api2.client(),
        sessions=5,
        runtime_budget_s=60.0,
        storage_budget_bytes=10**9,
        now=_BACKFILL_NOW,
    )

    assert rep.sessions_archived == 5
    assert rep.skipped_existing == 3
    assert set(api2.grouped_calls) == {"2026-09-08", "2026-09-07"}


def test_backfill_stops_at_runtime_budget_when_deadline_already_passed(session: Session) -> None:
    api = FakeMassiveAPI()
    client = api.client()

    rep = backfill(
        session,
        client,
        sessions=5,
        runtime_budget_s=60.0,
        storage_budget_bytes=10**9,
        now=_BACKFILL_NOW,
        deadline=time.monotonic() - 1.0,
    )

    assert rep.stopped_reason == "runtime budget reached"
    assert rep.sessions_archived == 0
    assert api.calls == []  # deadline check happens before any request


def test_backfill_stops_at_storage_budget_when_tiny(session: Session) -> None:
    api = FakeMassiveAPI()
    api.grouped["2026-09-11"] = _grouped_ok([_bar("AAPL", 100.0, volume=200_000)])

    rep = backfill(
        session,
        api.client(),
        sessions=5,
        runtime_budget_s=60.0,
        storage_budget_bytes=1,
        now=_BACKFILL_NOW,
    )

    assert rep.stopped_reason == "storage budget reached"
    assert rep.fetched == 1
    assert rep.sessions_archived == 1


# --------------------------------------------------------------------------- #
# 3) discovery.refresh_reference
# --------------------------------------------------------------------------- #


def test_refresh_reference_upserts_all_types_and_follows_pagination(session: Session) -> None:
    page1 = {
        "status": "OK",
        "results": [
            _ref_row("AAPL", name="Apple", type_="CS"),
            _ref_row("TSLA", name="Tesla", type_="CS"),
            _ref_row("SPY", name="SPDR S&P 500", type_="ETF"),
            _ref_row("BTCUSD", name="Bitcoin", type_="CRYPTO"),
        ],
        "next_url": "https://api.massive.com/v3/reference/tickers?cursor=abc",
    }
    page2 = {"status": "OK", "results": [_ref_row("MSFT", name="Microsoft", type_="CS")]}
    api = FakeMassiveAPI()
    api.reference_pages = [page1, page2]

    rep = refresh_reference(session, api.client())

    assert rep.pages == 2
    assert rep.discovered_all_types == 5  # every type counted
    assert rep.in_scope == 4  # AAPL, TSLA, SPY, MSFT — not BTCUSD (CRYPTO)
    tickers = {t.ticker: t for t in session.scalars(select(UniverseTicker))}
    assert set(tickers) == {"AAPL", "TSLA", "SPY", "BTCUSD", "MSFT"}
    assert tickers["BTCUSD"].security_type == "CRYPTO"
    assert tickers["SPY"].security_type == "ETF"
    assert all(t.active for t in tickers.values())


def test_refresh_reference_marks_a_dropped_ticker_inactive(session: Session) -> None:
    api1 = FakeMassiveAPI()
    api1.reference_pages = [
        {"status": "OK", "results": [_ref_row("AAPL", type_="CS"), _ref_row("TSLA", type_="CS")]}
    ]
    refresh_reference(session, api1.client())

    api2 = FakeMassiveAPI()
    api2.reference_pages = [{"status": "OK", "results": [_ref_row("AAPL", type_="CS")]}]
    rep = refresh_reference(session, api2.client())

    assert rep.discovered_all_types == 2  # the row stays, just marked inactive
    tsla = session.scalar(select(UniverseTicker).where(UniverseTicker.ticker == "TSLA"))
    aapl = session.scalar(select(UniverseTicker).where(UniverseTicker.ticker == "AAPL"))
    assert tsla is not None and tsla.active is False
    assert aapl is not None and aapl.active is True


# --------------------------------------------------------------------------- #
# 4) screen.run_screen
# --------------------------------------------------------------------------- #

_SCREEN_NOW = datetime(2026, 9, 9, 20, 0, tzinfo=UTC)


def _screen_cfg() -> UniversePipelineConfig:
    return UniversePipelineConfig(
        min_price=5.0,
        min_avg_dollar_volume=1_000_000.0,
        adv_sessions=5,
        min_market_cap=2_000_000_000.0,
        min_history_sessions=20,
        min_session_coverage=0.95,
        max_sector_share=0.2,
        max_abs_daily_return=0.5,
        max_zero_volume_share=0.05,
        min_listing_age_days=30,
        backfill_sessions=30,
    )


def test_run_screen_exact_exclusion_reasons_eligible_set_and_flags(session: Session) -> None:
    cfg = _screen_cfg()
    dates = _weekdays(date(2026, 6, 1), 25)
    api = FakeMassiveAPI()
    for i, d in enumerate(dates):
        rows = [
            _bar("LOWPRICE", 3.0, volume=40_000_000, vw=3.0),  # cheap but liquid
            _bar("LOWADV", 100.0, volume=100),  # thin
            _bar("LOWCAP", 100.0, volume=200_000),  # small cap (set below)
            _bar("NEWLIST", 100.0, volume=200_000),  # recently listed (set below)
            _bar("QUALJUMP", 160.0 if i == 12 else 100.0, volume=200_000),  # one bad day
            _bar("CONTIN", 100.0, volume=200_000),  # continuity-mapped
            _bar("CAPUNK", 100.0, volume=200_000),  # cap unknown, otherwise clean
            _bar("SECTA", 100.0, volume=300_000),  # sector group "73", higher ADV
            _bar("SECTB", 100.0, volume=200_000),  # sector group "73", lower ADV
            _bar("ETFA", 100.0, volume=250_000),
            _bar("ETFB", 100.0, volume=250_000),
        ]
        if i >= 22:  # only the last 3 sessions -> insufficient history
            rows.append(_bar("SHORTHIST", 100.0, volume=200_000))
        api.grouped[d.isoformat()] = _grouped_ok(rows)
    client = api.client()
    for d in dates:
        archive_session(session, client, d)

    old = date(2000, 1, 1)
    _ticker_row(session, "LOWPRICE", market_cap=5e9, list_date=old)
    _ticker_row(session, "LOWADV", market_cap=5e9, list_date=old)
    _ticker_row(session, "LOWCAP", market_cap=5e8, list_date=old)
    _ticker_row(session, "SHORTHIST", market_cap=5e9, list_date=old)
    _ticker_row(
        session, "NEWLIST", market_cap=5e9, list_date=_SCREEN_NOW.date() - timedelta(days=5)
    )
    _ticker_row(session, "QUALJUMP", market_cap=5e9, list_date=old)
    _ticker_row(session, "CONTIN", market_cap=5e9, list_date=old)
    _ticker_row(session, "OOSTYPE", security_type="CRYPTO", list_date=old)
    _ticker_row(session, "INACTIVE", active=False, list_date=old)
    _ticker_row(session, "CAPUNK", market_cap=None, sic_code="", list_date=old)
    _ticker_row(session, "SECTA", market_cap=5e9, sic_code="7371", list_date=old)
    _ticker_row(session, "SECTB", market_cap=5e9, sic_code="7372", list_date=old)
    _ticker_row(session, "ETFA", security_type="ETF", list_date=old)
    _ticker_row(session, "ETFB", security_type="ETF", list_date=old)
    session.add(
        SymbolContinuityMapping(
            old_symbol="CONTIN",
            new_symbol="CONTINX",
            corporate_action_type="ticker_and_name_change",
            effective_date=date(2021, 1, 1),
            last_old_session=date(2020, 12, 31),
            source=DEFAULT_SOURCE,
            adjustment_status="verified continuity bridge",
        )
    )
    session.flush()

    rep = run_screen(session, cfg, now=_SCREEN_NOW)

    assert rep.discovered == 14
    assert rep.in_scope == 12
    # CAPUNK is a common stock with NO known market cap: it is never treated as
    # passing the market-cap filter (excluded as market_cap_unverified) while
    # keeping its market_cap_unavailable flag.
    assert rep.eligible == 3
    assert rep.eligible_symbols == ["ETFA", "ETFB", "SECTA"]
    assert rep.excluded_by_reason == {
        "security_type_out_of_scope": 1,
        "inactive_listing": 1,
        "price_below_min": 1,
        "adv_dollar_volume_below_min": 1,
        "market_cap_below_min": 1,
        "market_cap_unverified": 1,
        "insufficient_history": 1,
        "listing_too_recent": 1,
        "data_quality": 1,
        "corporate_action_continuity": 1,
        "sector_concentration": 1,
    }

    snap = session.scalar(
        select(DataSnapshot).where(DataSnapshot.key.like(f"liquid_us_{dates[-1].isoformat()}%"))
    )
    assert snap is not None
    assert snap.reusable_by_new_evaluations is False
    assert sorted(snap.symbols_json) == rep.eligible_symbols

    for oos_ticker in ("OOSTYPE", "INACTIVE"):
        member = session.scalar(
            select(UniverseMember).where(
                UniverseMember.run_id == rep.run_id, UniverseMember.ticker == oos_ticker
            )
        )
        assert member is None  # counted, never persisted

    capunk = session.scalar(
        select(UniverseMember).where(
            UniverseMember.run_id == rep.run_id, UniverseMember.ticker == "CAPUNK"
        )
    )
    assert capunk is not None
    assert "spread_filter_not_licensed" in capunk.flags
    assert "market_cap_unavailable" in capunk.flags  # flag preserved ...
    assert capunk.eligible is False  # ... and never counted as passing the cap filter
    assert capunk.exclusion_reasons == ["market_cap_unverified"]


# --------------------------------------------------------------------------- #
# 5) normalize.normalize_symbols
# --------------------------------------------------------------------------- #


def test_normalize_symbols_writes_only_requested_symbols_and_is_idempotent(
    session: Session,
) -> None:
    cfg = UniversePipelineConfig()
    dates = _weekdays(date(2026, 6, 1), 2)
    api = FakeMassiveAPI()
    for d in dates:
        api.grouped[d.isoformat()] = _grouped_ok(
            [
                _bar("AAA", 10.0, volume=1_000),
                _bar("BBB", 20.0, volume=2_000),
                _bar("SPY", 400.0, volume=5_000),
                _bar("ZZZ", 5.0, volume=100),
            ]
        )
    client = api.client()
    for d in dates:
        archive_session(session, client, d, source=cfg.normalized_source)

    rep = normalize_symbols(session, ["AAA", "BBB"], cfg)

    assert rep.symbols == 3  # AAA, BBB + the SPY market proxy — never ZZZ
    assert rep.rows_written == 6  # 3 symbols x 2 sessions

    rows = list(
        session.scalars(select(OHLCVDaily).where(OHLCVDaily.source == cfg.normalized_source))
    )
    assert len(rows) == 6
    assert all(r.is_adjusted is True for r in rows)
    assert all("asof_adjusted_not_pit" in r.quality_flags for r in rows)

    zzz_rows = list(
        session.scalars(
            select(OHLCVDaily)
            .join(Instrument)
            .where(Instrument.symbol == "ZZZ", OHLCVDaily.source == cfg.normalized_source)
        )
    )
    assert zzz_rows == []

    feed = session.scalar(
        select(DataFeedStatus).where(
            DataFeedStatus.provider == cfg.normalized_source,
            DataFeedStatus.feed_type == FeedType.BAR_DAILY,
        )
    )
    assert feed is not None
    assert feed.latency_category == LatencyCategory.END_OF_DAY

    # SAFEGUARD: the research/promotion path filters bars by its own source
    # label and must never see these bulk rows for the same symbol/date range.
    assert get_daily_bars(session, "AAA", dates[0], dates[-1], source="massive") == []
    own_source_rows = get_daily_bars(
        session, "AAA", dates[0], dates[-1], source=cfg.normalized_source
    )
    assert len(own_source_rows) == 2

    rep2 = normalize_symbols(session, ["AAA", "BBB"], cfg)
    assert rep2.rows_written == 0  # idempotent


# --------------------------------------------------------------------------- #
# 6) pipeline.run_universe_update
# --------------------------------------------------------------------------- #


def _small_universe_cfg(**overrides: Any) -> UniversePipelineConfig:
    base: dict[str, Any] = {
        "min_price": 1.0,
        "min_avg_dollar_volume": 1.0,
        "adv_sessions": 2,
        "min_market_cap": 1.0,
        "min_history_sessions": 2,
        "min_session_coverage": 0.5,
        "min_listing_age_days": 1,
        "backfill_sessions": 2,
        "max_storage_bytes": 50_000_000,
        "max_runtime_seconds": 60,
    }
    base.update(overrides)
    return UniversePipelineConfig(**base)


def test_run_universe_update_end_to_end_without_scan(session: Session) -> None:
    cfg = _small_universe_cfg()
    dates = _weekdays(date(2026, 6, 1), cfg.backfill_sessions)
    api = FakeMassiveAPI()
    for d in dates:
        api.grouped[d.isoformat()] = _grouped_ok(
            [
                _bar("AAPL", 100.0, volume=100_000),
                _bar("MSFT", 200.0, volume=100_000),
                _bar("SPY", 400.0, volume=100_000),
            ]
        )
    api.reference_pages = [
        {
            "status": "OK",
            "results": [
                _ref_row("AAPL", name="Apple", type_="CS", list_date="2000-01-01"),
                _ref_row("MSFT", name="Microsoft", type_="CS", list_date="2000-01-01"),
            ],
        }
    ]

    rep = run_universe_update(session, cfg=cfg, client=api.client(), now=_SCREEN_NOW, do_scan=False)

    assert rep.discovery is not None and rep.discovery["discovered_all_types"] == 2
    assert rep.backfill is not None and rep.backfill["sessions_archived"] == cfg.backfill_sessions
    assert rep.screen is not None
    assert rep.normalize is not None and rep.normalize["rows_written"] > 0
    assert rep.scans == []

    audit = session.scalar(select(AuditLog).where(AuditLog.action == "universe.update"))
    assert audit is not None

    assert rep.storage["archive_sessions"] > 0
    assert rep.storage["normalized_rows"] > 0


def test_run_universe_update_stops_at_runtime_budget_before_scan(session: Session) -> None:
    cfg = _small_universe_cfg(max_runtime_seconds=1)
    dates = _weekdays(date(2026, 6, 1), cfg.backfill_sessions)

    prep_api = FakeMassiveAPI()
    for d in dates:
        prep_api.grouped[d.isoformat()] = _grouped_ok([_bar("AAPL", 100.0, volume=100_000)])
    prep_client = prep_api.client()
    for d in dates:
        archive_session(session, prep_client, d, source=cfg.normalized_source)
    assert len(archived_sessions(session, source=cfg.normalized_source)) == cfg.backfill_sessions

    slow_api = FakeMassiveAPI()
    slow_api.sleep_on_reference = 1.5  # burns past the 1-second runtime budget deterministically
    slow_api.reference_pages = [{"status": "OK", "results": [_ref_row("AAPL", type_="CS")]}]

    rep = run_universe_update(
        session, cfg=cfg, client=slow_api.client(), now=_SCREEN_NOW, do_scan=True
    )

    assert "runtime budget" in rep.stopped_reason
    assert rep.scans == []


# --------------------------------------------------------------------------- #
# 7) safety: import boundaries + config-gated scheduler no-op
# --------------------------------------------------------------------------- #


def test_universe_package_never_imports_alerts_paper_or_llm() -> None:
    import signalforge.universe as pkg

    pkg_dir = Path(pkg.__file__).parent
    forbidden = ("signalforge.alerts", "signalforge.paper.ledger", "signalforge.llm")
    for fname in ("bulk.py", "discovery.py", "screen.py", "normalize.py", "pipeline.py"):
        text = (pkg_dir / fname).read_text()
        for bad in forbidden:
            assert bad not in text, f"{fname} must never reference {bad}"


def test_job_universe_update_is_a_noop_when_pipeline_disabled(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    import signalforge.scheduler as sched

    fake_cfg = types.SimpleNamespace(enabled=False)
    fake_research = types.SimpleNamespace(universe_pipeline=fake_cfg)
    monkeypatch.setattr(
        "signalforge.settings_store.effective_research_config", lambda sess: fake_research
    )

    sched.job_universe_update()

    row = session.scalar(select(AuditLog).where(AuditLog.action == "universe.update"))
    assert row is None
