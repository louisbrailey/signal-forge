from datetime import UTC, datetime

import pytest

from signalforge.config import get_settings
from signalforge.data import market_context as ctx
from signalforge.db.models import RawPayloadCache
from signalforge.db.session import session_scope


def bar(t=1000, close=2):
    return {"t": t, "o": 2, "h": 3, "l": 1, "c": close}


@pytest.mark.parametrize("rows", [[bar(), bar()], [bar(close=4)], [bar(close=float("nan"))]])
def test_invalid_bars_refused(rows):
    with pytest.raises(ValueError):
        ctx.normalize({"results": rows})


def test_empty_dashboard(session):
    assert all(r["status"] == "unavailable" for r in ctx.read_context(session))


def test_refresh_deduplicates_and_dashboard_uses_cache(db_url, monkeypatch):
    monkeypatch.setenv("MARKET_DATA_API_KEY", "test-context-key")
    get_settings.cache_clear()
    calls = []
    monkeypatch.setattr(ctx.time, "sleep", lambda _: None)

    def fetch(client, path, key):
        calls.append(path)
        t = int(datetime.now(UTC).timestamp() * 1000) - 86400000
        return 200, {"status": "OK", "results": [bar(t - 86400000), bar(t, 3)]}

    monkeypatch.setattr(ctx, "_get", fetch)
    assert ctx.refresh() == 6
    assert ctx.refresh() == 0
    assert len(calls) == 6
    with session_scope() as session:
        rows = ctx.read_context(session)
        assert all(r["close"] == 3 and r["change_pct"] == 50 for r in rows)
        assert all(r["latency"] == "END_OF_DAY" for r in rows)


def test_error_is_visible_and_secret_not_cached(db_url, monkeypatch):
    monkeypatch.setenv("MARKET_DATA_API_KEY", "test-context-key")
    get_settings.cache_clear()
    monkeypatch.setattr(ctx, "_get", lambda *args: (403, {"message": "test-context-key"}))
    monkeypatch.setattr(ctx.time, "sleep", lambda _: None)
    ctx.refresh()
    with session_scope() as session:
        from sqlalchemy import select

        assert all(
            "test-context-key" not in r.payload for r in session.scalars(select(RawPayloadCache))
        )
        assert all(r["status"] == "unavailable" for r in ctx.read_context(session))


def test_futures_timestamp_nanoseconds():
    rows = ctx.normalize(
        {
            "results": [
                {"window_start": 1792627200000000000, "open": 2, "high": 3, "low": 1, "close": 2}
            ]
        }
    )
    assert rows == [{"timestamp": "2026-10-22T00:00:00+00:00", "close": 2.0}]


def test_stale_context_is_not_healthy(db_url, monkeypatch):
    monkeypatch.setenv("MARKET_DATA_API_KEY", "test-context-key")
    get_settings.cache_clear()
    monkeypatch.setattr(ctx.time, "sleep", lambda _: None)
    monkeypatch.setattr(ctx, "_get", lambda *args: (200, {"results": [bar()]}))
    ctx.refresh()
    with session_scope() as session:
        assert all(r["status"] == "stale" for r in ctx.read_context(session))


def test_historical_context_cannot_see_later_retrieval(db_url, monkeypatch):
    monkeypatch.setenv("MARKET_DATA_API_KEY", "test-context-key")
    get_settings.cache_clear()
    monkeypatch.setattr(ctx.time, "sleep", lambda _: None)
    monkeypatch.setattr(ctx, "_get", lambda *args: (200, {"results": [bar()]}))
    ctx.refresh()
    with session_scope() as session:
        assert all(
            r["status"] == "unavailable"
            for r in ctx.read_context(session, as_of=datetime(2000, 1, 1, tzinfo=UTC))
        )
