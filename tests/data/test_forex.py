"""Forex daily-bar ingest — offline only (mocked transport, no provider call)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from signalforge.data import forex as fx
from signalforge.db.models import DataFeedStatus, FxBarDaily, OHLCVDaily
from signalforge.domain import FeedType, LatencyCategory

KEY = "sf-test-forex-key"  # pragma: allowlist secret
# Wed 2026-10-21 12:00 UTC -> last completed UTC weekday is Tue 2026-10-20.
NOW = datetime(2026, 10, 21, 12, 0, tzinfo=UTC)


def _ms(d: date) -> int:
    return int(datetime(d.year, d.month, d.day, tzinfo=UTC).timestamp() * 1000)


def _bar(d: date, c: float = 1.10) -> dict[str, Any]:
    return {"t": _ms(d), "o": c, "h": c + 0.01, "l": c - 0.01, "c": c, "v": 1234, "n": 99}


class FakeAPI:
    def __init__(self) -> None:
        self.bars: dict[str, list[dict[str, Any]]] = {}
        self.status: dict[str, int] = {}
        self.calls: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.calls.append(url)
        assert request.headers["authorization"] == f"Bearer {KEY}"
        assert KEY not in url
        pair = url.split("/ticker/C:", 1)[1].split("/", 1)[0]
        frm, to = url.split("/range/1/day/", 1)[1].split("?", 1)[0].split("/")
        if pair in self.status:
            return httpx.Response(self.status[pair], json={"status": "ERROR"})
        rows = [
            b
            for b in self.bars.get(pair, [])
            if _ms(date.fromisoformat(frm)) <= b["t"] <= _ms(date.fromisoformat(to))
        ]
        return httpx.Response(
            200, json={"status": "OK", "resultsCount": len(rows), "results": rows}
        )

    def client(self) -> fx.ForexClient:
        return fx.ForexClient(
            api_key=KEY,
            client=httpx.Client(transport=httpx.MockTransport(self.handler)),
            spacing_s=0.0,
            sleep=lambda _s: None,
        )


def test_parse_pairs_normalises_and_rejects_garbage() -> None:
    assert fx.parse_pairs("eurusd, C:USDJPY,EUR/USD,") == ["EURUSD", "USDJPY"]
    with pytest.raises(ValueError):
        fx.parse_pairs("EURUSD,SPY")


def test_last_completed_day_skips_the_weekend() -> None:
    assert fx.last_completed_fx_day(NOW) == date(2026, 10, 20)
    # Monday 2026-10-26 -> Sunday is not a session -> Friday 2026-10-23
    assert fx.last_completed_fx_day(datetime(2026, 10, 26, 3, tzinfo=UTC)) == date(2026, 10, 23)


def test_ingest_writes_weekday_bars_drops_weekends_and_records_feed(session: Session) -> None:
    api = FakeAPI()
    days = [date(2026, 10, d) for d in (15, 16, 17, 18, 19, 20)]  # Thu..Tue incl. Sat/Sun
    api.bars["EURUSD"] = [_bar(d) for d in days]

    rep = fx.ingest_forex(session, ["EURUSD"], lookback_days=5, client=api.client(), now=NOW)

    pr = rep.pairs[0]
    assert pr.status == "ok"
    assert pr.written == 4
    assert pr.weekend_dropped == 2
    assert pr.gaps == []
    stored = session.scalars(select(FxBarDaily).order_by(FxBarDaily.session_date)).all()
    assert [b.session_date.day for b in stored] == [15, 16, 19, 20]
    assert all(b.latency_category is LatencyCategory.END_OF_DAY for b in stored)
    assert all(b.source == "massive_fx" for b in stored)
    feed = session.scalar(select(DataFeedStatus).where(DataFeedStatus.provider == "massive_fx"))
    assert feed is not None and feed.feed_type is FeedType.BAR_DAILY
    assert feed.last_success_at is not None
    # FX never lands in the equity bar table
    assert session.scalars(select(OHLCVDaily)).all() == []


def test_rerun_tops_up_from_the_newest_stored_bar(session: Session) -> None:
    api = FakeAPI()
    api.bars["USDJPY"] = [_bar(date(2026, 10, d), 150.0) for d in (19, 20)]
    fx.ingest_forex(session, ["USDJPY"], lookback_days=3, client=api.client(), now=NOW)

    api.bars["USDJPY"].append(_bar(date(2026, 10, 21), 151.0))
    later = datetime(2026, 10, 22, 12, tzinfo=UTC)
    api.calls.clear()
    rep = fx.ingest_forex(session, ["USDJPY"], lookback_days=3, client=api.client(), now=later)

    assert rep.pairs[0].written == 1
    assert "/2026-10-21/2026-10-21" in api.calls[0]
    # third run: nothing new to request
    api.calls.clear()
    rep = fx.ingest_forex(session, ["USDJPY"], lookback_days=3, client=api.client(), now=later)
    assert rep.pairs[0].status == "up_to_date"
    assert api.calls == []


def test_missing_weekday_is_reported_as_a_gap_not_filled(session: Session) -> None:
    api = FakeAPI()
    api.bars["GBPUSD"] = [_bar(date(2026, 10, 19), 1.3)]  # 10-20 missing
    rep = fx.ingest_forex(session, ["GBPUSD"], lookback_days=1, client=api.client(), now=NOW)
    assert rep.pairs[0].gaps == ["2026-10-20"]
    assert len(session.scalars(select(FxBarDaily)).all()) == 1


def test_malformed_bar_rejects_the_whole_pair_and_marks_the_feed(session: Session) -> None:
    api = FakeAPI()
    bad = _bar(date(2026, 10, 20))
    bad["h"] = 0.5  # high below close
    api.bars["AUDUSD"] = [_bar(date(2026, 10, 19)), bad]
    api.bars["EURUSD"] = [_bar(date(2026, 10, 20))]

    rep = fx.ingest_forex(
        session, ["AUDUSD", "EURUSD"], lookback_days=2, client=api.client(), now=NOW
    )

    assert rep.failed == ["AUDUSD"]
    assert rep.pairs[1].written == 1  # one pair failing never blocks the others
    pairs = {b.pair for b in session.scalars(select(FxBarDaily))}
    assert pairs == {"EURUSD"}


def test_not_entitled_fails_cleanly_without_retrying(session: Session) -> None:
    api = FakeAPI()
    api.status["USDCHF"] = 403
    rep = fx.ingest_forex(session, ["USDCHF"], lookback_days=2, client=api.client(), now=NOW)
    assert rep.failed == ["USDCHF"]
    assert "not entitled" in rep.pairs[0].error
    assert len(api.calls) == 1
    feed = session.scalar(select(DataFeedStatus).where(DataFeedStatus.provider == "massive_fx"))
    assert feed is not None and feed.consecutive_failures == 1


def test_rate_limit_backs_off_a_full_minute(session: Session) -> None:
    slept: list[float] = []
    responses = iter([429, 200])

    def handler(request: httpx.Request) -> httpx.Response:
        code = next(responses)
        if code == 429:
            return httpx.Response(429, json={"status": "ERROR"})
        return httpx.Response(200, json={"status": "OK", "results": [_bar(date(2026, 10, 20))]})

    client = fx.ForexClient(
        api_key=KEY,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        spacing_s=0.0,
        sleep=slept.append,
    )
    rep = fx.ingest_forex(session, ["NZDUSD"], lookback_days=1, client=client, now=NOW)
    assert rep.pairs[0].written == 1
    assert slept == [61.0]


def test_missing_key_never_calls_the_provider(session: Session) -> None:
    api = FakeAPI()
    client = fx.ForexClient(
        api_key="",
        client=httpx.Client(transport=httpx.MockTransport(api.handler)),
        spacing_s=0.0,
    )
    rep = fx.ingest_forex(session, ["EURUSD"], lookback_days=1, client=client, now=NOW)
    assert rep.failed == ["EURUSD"]
    assert api.calls == []


def test_scheduled_job_is_off_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    from signalforge import scheduler

    called: list[bool] = []
    monkeypatch.setattr(fx, "ingest_forex", lambda *a, **k: called.append(True))
    scheduler.job_forex_ingest()
    assert called == []


# --- crypto (same Currencies plan, seven-day market) ----------------------- #
def _crypto_client(api: FakeAPI) -> fx.ForexClient:
    return fx.ForexClient(
        api_key=KEY,
        client=httpx.Client(transport=httpx.MockTransport(api.crypto_handler)),
        spacing_s=0.0,
        sleep=lambda _s: None,
        prefix="X",
    )


def _crypto_handler(self: FakeAPI, request: httpx.Request) -> httpx.Response:
    url = str(request.url)
    assert "/ticker/X:" in url and "/ticker/C:" not in url
    return self.handler(
        httpx.Request("GET", url.replace("/ticker/X:", "/ticker/C:"), headers=request.headers)
    )


FakeAPI.crypto_handler = _crypto_handler  # type: ignore[attr-defined]


def test_crypto_pairs_parse_with_their_own_rules() -> None:
    assert fx.parse_pairs("btcusd, X:ETHUSD, BTC-USD", fx.CRYPTO) == ["BTCUSD", "ETHUSD"]
    with pytest.raises(ValueError):
        fx.parse_pairs("EURJPY", fx.CRYPTO)  # crypto quotes in USD only


def test_crypto_keeps_weekend_bars_in_its_own_table(session: Session) -> None:
    from signalforge.db.models import CryptoBarDaily

    api = FakeAPI()
    days = [date(2026, 10, d) for d in range(16, 21)]  # Fri..Tue incl. Sat/Sun
    api.bars["BTCUSD"] = [_bar(d, 82000.0) for d in days]
    # Sunday 2026-10-25 -> last completed crypto day is Saturday 10-24, not Friday
    assert fx.last_completed_fx_day(
        datetime(2026, 10, 25, 3, tzinfo=UTC), trades_weekends=True
    ) == date(2026, 10, 24)

    rep = fx.ingest_crypto(
        session, ["BTCUSD"], lookback_days=4, client=_crypto_client(api), now=NOW
    )

    pr = rep.pairs[0]
    assert (pr.status, pr.written, pr.weekend_dropped, pr.gaps) == ("ok", 5, 0, [])
    rows = session.scalars(select(CryptoBarDaily).order_by(CryptoBarDaily.session_date)).all()
    assert [r.session_date.day for r in rows] == [16, 17, 18, 19, 20]
    assert rows[0].volume == 1234 and rows[0].source == "massive_crypto"
    assert session.scalars(select(FxBarDaily)).all() == []
    assert session.scalars(select(OHLCVDaily)).all() == []
    feed = session.scalar(select(DataFeedStatus).where(DataFeedStatus.provider == "massive_crypto"))
    assert feed is not None and feed.last_success_at is not None


def test_crypto_job_is_off_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    from signalforge import scheduler

    called: list[bool] = []
    monkeypatch.setattr(fx, "ingest_crypto", lambda *a, **k: called.append(True))
    scheduler.job_crypto_ingest()
    assert called == []
