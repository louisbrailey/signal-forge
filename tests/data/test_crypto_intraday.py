"""Hourly crypto ingest — mocked transport, no provider call."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from signalforge.data import crypto_intraday as ci
from signalforge.data.forex import ForexClient
from signalforge.db.models import CryptoBarIntraday, DataFeedStatus

KEY = "sf-test-hourly-key"  # pragma: allowlist secret
NOW = datetime(2024, 3, 2, 5, 30, tzinfo=UTC)  # last complete hour 04:00


def _bar(t: datetime, c: float = 100.0) -> dict[str, Any]:
    return {"t": int(t.timestamp() * 1000), "o": c, "h": c + 1, "l": c - 1, "c": c, "v": 3.5}


class Fake:
    def __init__(self, hours: list[datetime]) -> None:
        self.hours = hours
        self.calls: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        assert "/ticker/X:BTCUSD/range/1/hour/" in url
        self.calls.append(url)
        frm, to = url.split("/range/1/hour/", 1)[1].split("?", 1)[0].split("/")
        lo = datetime.fromisoformat(frm).replace(tzinfo=UTC)
        hi = datetime.fromisoformat(to).replace(tzinfo=UTC) + timedelta(days=1, hours=5)
        rows = [_bar(h) for h in self.hours if lo <= h < hi]  # includes spill past the day
        return httpx.Response(200, json={"status": "OK", "results": rows})

    def client(self) -> ForexClient:
        return ForexClient(
            api_key=KEY,
            client=httpx.Client(transport=httpx.MockTransport(self.handler)),
            spacing_s=0.0,
            sleep=lambda _s: None,
            prefix="X",
        )


def _hours(start: datetime, end: datetime) -> list[datetime]:
    out, h = [], start
    while h <= end:
        out.append(h)
        h += timedelta(hours=1)
    return out


def test_month_chunks_fit_under_the_base_minute_cap() -> None:
    chunks = ci.month_chunks(date(2024, 1, 15), date(2024, 3, 2))
    assert chunks == [
        (date(2024, 1, 15), date(2024, 1, 31)),
        (date(2024, 2, 1), date(2024, 2, 29)),
        (date(2024, 3, 1), date(2024, 3, 2)),
    ]


def test_ingests_completed_hours_only_drops_spill_and_never_touches_feed_status(
    session: Session,
) -> None:
    fake = Fake(_hours(datetime(2024, 2, 1, tzinfo=UTC), datetime(2024, 3, 2, 23, tzinfo=UTC)))
    rep = ci.ingest_crypto_hourly(
        session, ["BTCUSD"], start=date(2024, 2, 1), client=fake.client(), now=NOW
    )
    (pr,) = rep.pairs
    assert pr.failed_months == []
    assert pr.outside_window > 0  # provider spill past the window was dropped, not fatal
    rows = session.scalars(select(CryptoBarIntraday).order_by(CryptoBarIntraday.bar_start)).all()
    first, last = rows[0].bar_start, rows[-1].bar_start
    assert first.replace(tzinfo=UTC) == datetime(2024, 2, 1, tzinfo=UTC)
    assert last.replace(tzinfo=UTC) == datetime(2024, 3, 2, 4, tzinfo=UTC)  # last complete hour
    assert len(rows) == 29 * 24 + 24 + 5
    assert pr.missing_hours == 0
    assert session.scalars(select(DataFeedStatus)).all() == []

    # a rerun skips complete months without a request and adds the newly completed hours
    fake.calls.clear()
    later = NOW + timedelta(hours=3)
    rep2 = ci.ingest_crypto_hourly(
        session, ["BTCUSD"], start=date(2024, 2, 1), client=fake.client(), now=later
    )
    assert len(fake.calls) == 1 and "/2024-03-01/2024-03-02" in fake.calls[0]
    assert rep2.pairs[0].written == 3


def test_a_malformed_hour_rejects_only_that_month(session: Session) -> None:
    hours = _hours(datetime(2024, 1, 1, tzinfo=UTC), datetime(2024, 2, 29, 23, tzinfo=UTC))
    fake = Fake(hours)
    orig = fake.handler

    def bad(request: httpx.Request) -> httpx.Response:
        r = orig(request)
        if "/2024-01-01/" in str(request.url):
            body = r.json()
            body["results"][5]["h"] = 1.0  # high below close
            return httpx.Response(200, json=body)
        return r

    fake.handler = bad  # type: ignore[method-assign]
    rep = ci.ingest_crypto_hourly(
        session,
        ["BTCUSD"],
        start=date(2024, 1, 1),
        end=date(2024, 2, 29),
        client=fake.client(),
        now=datetime(2024, 3, 5, tzinfo=UTC),
    )
    assert [f[:7] for f in rep.pairs[0].failed_months] == ["2024-01"]
    assert rep.pairs[0].written == 29 * 24


def test_non_hourly_timestamps_are_refused() -> None:
    with pytest.raises(ValueError, match="on the hour"):
        ci.parse_hours(
            {"results": [_bar(datetime(2024, 1, 1, 0, 30, tzinfo=UTC))]},
            start=date(2024, 1, 1),
            end=date(2024, 1, 1),
        )
