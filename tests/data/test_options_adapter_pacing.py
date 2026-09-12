"""Options adapter: pacing, retry/backoff, and the listing parameters (D1 §7.6).

The shipped adapter made a SINGLE unretried HTTP attempt and raised immediately
on 429, while the equities adapter self-paces and backs off — which is how a
multi-day options backfill turns into a multi-day stream of unretried rate
limits. These tests pin the ported behaviour, the terminal-vs-retryable status
split, and the pagination accounting the ladder selection depends on.

Offline: MockTransport stands in for api.massive.com and every sleep is patched,
so nothing here waits and nothing here reaches a network.
"""

from __future__ import annotations

from datetime import date

import httpx
import pytest

from signalforge.data.adapters import massive_options as mo
from signalforge.data.adapters.base import AdapterError
from signalforge.data.adapters.massive_options import MassiveOptionsAdapter


def _client(handler) -> httpx.Client:  # type: ignore[no-untyped-def]
    return httpx.Client(transport=httpx.MockTransport(handler))


# Captured before any patching, so the one test that must exercise the REAL
# chunked wait can still reach it.
_REAL_SLEEP = MassiveOptionsAdapter._sleep


@pytest.fixture(autouse=True)
def _no_real_sleeping(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch ``_sleep``, NOT ``time.sleep``.

    The backoff is a chunked wait driven by ``time.monotonic()``: neutering
    ``time.sleep`` alone leaves the loop spinning for exactly the same wall
    time, so a five-attempt give-up test still costs 22.5 s — it just burns a
    core doing it."""
    monkeypatch.setattr(mo.MassiveOptionsAdapter, "_sleep", lambda self, _s: None)


def test_retries_a_429_and_eventually_succeeds() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(429, json={"status": "ERROR"})
        return httpx.Response(200, json={"status": "OK", "results": []})

    adapter = MassiveOptionsAdapter("k", client=_client(handler))
    assert adapter._get("/v3/x") == {"status": "OK", "results": []}
    assert calls["n"] == 3  # two retries, then the success


def test_gives_up_after_max_attempts_and_reports_rate_limited() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(429, json={"status": "ERROR"})

    adapter = MassiveOptionsAdapter("k", client=_client(handler))
    with pytest.raises(AdapterError) as exc:
        adapter._get("/v3/x")
    assert exc.value.rate_limited is True
    assert calls["n"] == mo._MAX_ATTEMPTS


def test_a_403_is_terminal_and_is_never_retried() -> None:
    """Burning a multi-day budget against an entitlement wall is how a long run
    becomes a long no-op."""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(403, json={"status": "NOT_AUTHORIZED"})

    adapter = MassiveOptionsAdapter("k", client=_client(handler))
    with pytest.raises(AdapterError) as exc:
        adapter._get("/v3/x")
    assert calls["n"] == 1
    assert exc.value.rate_limited is False


def test_retry_after_header_is_honoured(monkeypatch: pytest.MonkeyPatch) -> None:
    slept: list[float] = []
    monkeypatch.setattr(MassiveOptionsAdapter, "_sleep", lambda self, s: slept.append(s))
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(503, headers={"retry-after": "7"}, json={})
        return httpx.Response(200, json={"results": []})

    MassiveOptionsAdapter("k", client=_client(handler))._get("/v3/x")
    assert slept == [7.0]


def test_a_backoff_sleep_is_chunked_so_the_kill_switch_stays_responsive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The honest bound on kill latency is NOT a chunk size — an in-flight
    request is not cancelled — but the WAIT must not swallow the switch."""
    checks = {"n": 0}
    monkeypatch.setattr(mo, "ensure_not_engaged", lambda: checks.__setitem__("n", checks["n"] + 1))
    ticks = iter([0.0, 0.0, 0.05, 0.1, 0.15, 0.2, 0.25, 0.3, 0.35, 0.4, 0.45, 0.5, 0.5])
    monkeypatch.setattr(mo.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(mo.time, "sleep", lambda _s: None)  # the clock above drives the loop
    adapter = MassiveOptionsAdapter("k", client=_client(lambda r: httpx.Response(200, json={})))
    _REAL_SLEEP(adapter, 0.5)  # the autouse fixture neutered the bound method
    # a 0.5 s backoff was broken into several chunks, each one consulting the
    # switch — not one uninterruptible half-second
    assert checks["n"] >= 4


def test_pacing_precedence_argument_then_setting_then_equities_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from signalforge.config.settings import get_settings

    handler = lambda r: httpx.Response(200, json={})  # noqa: E731
    assert MassiveOptionsAdapter("k", client=_client(handler)).min_request_spacing_s == 12.1

    monkeypatch.setenv("OPTIONS_MIN_REQUEST_SPACING_S", "3.5")
    get_settings.cache_clear()
    try:
        assert MassiveOptionsAdapter("k", client=_client(handler)).min_request_spacing_s == 3.5
        # an explicit argument still wins over the setting
        a = MassiveOptionsAdapter("k", client=_client(handler), min_request_spacing_s=0.25)
        assert a.min_request_spacing_s == 0.25
    finally:
        monkeypatch.delenv("OPTIONS_MIN_REQUEST_SPACING_S", raising=False)
        get_settings.cache_clear()


def test_pacing_waits_between_requests_when_no_client_is_injected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    waits = {"n": 0}
    clock = {"t": 1000.0}

    def _sleep(seconds: float) -> None:
        waits["n"] += 1
        clock["t"] += max(seconds, 0.05)

    monkeypatch.setattr(mo.time, "sleep", _sleep)
    monkeypatch.setattr(mo.time, "monotonic", lambda: clock["t"])
    monkeypatch.setattr(mo.httpx, "get", lambda *a, **kw: httpx.Response(200, json={"results": []}))

    adapter = MassiveOptionsAdapter("k", min_request_spacing_s=5.0)
    adapter._get("/v3/x")  # nothing to wait for yet
    assert waits["n"] == 0
    t_after_first = clock["t"]

    adapter._get("/v3/x")  # must not fire until the spacing has elapsed
    assert waits["n"] > 0
    assert clock["t"] - t_after_first >= 5.0


# --- listing parameters and pagination accounting -------------------------- #
def _contracts_handler(urls: list[str], *, pages: int = 1, bad_rows: int = 0):  # type: ignore[no-untyped-def]
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        urls.append(url)
        page = url.count("cursor=")
        rows = [
            {
                "ticker": f"O:SPY231117C{400 + i:05d}000",
                "contract_type": "call",
                "strike_price": 400.0 + i,
                "expiration_date": "2023-11-17",
                "exercise_style": "american",
                "shares_per_contract": 100,
            }
            for i in range(3)
        ]
        rows += [{"ticker": "broken"} for _ in range(bad_rows)]
        body: dict[str, object] = {"status": "OK", "results": rows}
        if page + 1 < pages:
            body["next_url"] = "https://api.massive.com/v3/reference/options/contracts?cursor=next"
        return httpx.Response(200, json=body)

    return handler


def test_expired_and_as_of_are_sent_only_when_asked_for() -> None:
    urls: list[str] = []
    a = MassiveOptionsAdapter("k", client=_client(_contracts_handler(urls)))
    a.fetch_contracts("SPY", expiration_gte=date(2023, 11, 17), expiration_lte=date(2023, 11, 17))
    assert "expired=" not in urls[-1] and "as_of=" not in urls[-1]

    a.fetch_contracts(
        "SPY",
        expiration_gte=date(2023, 11, 17),
        expiration_lte=date(2023, 11, 17),
        expired=True,
        as_of=date(2023, 9, 18),
    )
    assert "expired=true" in urls[-1]
    assert "as_of=2023-09-18" in urls[-1]


def test_a_complete_listing_reports_itself_complete() -> None:
    urls: list[str] = []
    page = MassiveOptionsAdapter(
        "k", client=_client(_contracts_handler(urls))
    ).fetch_contracts_page(
        "SPY", expiration_gte=date(2023, 11, 17), expiration_lte=date(2023, 11, 17)
    )
    assert page.is_complete
    assert page.pages_walked == 1
    assert page.next_url_exhausted and not page.page_cap_hit
    assert page.rows_unparseable == 0
    assert len(page.rows) == 3


def test_a_page_capped_listing_is_reported_incomplete() -> None:
    """A truncated ladder is otherwise indistinguishable from a complete one —
    and the bracket check is computed from exactly that set."""
    urls: list[str] = []
    handler = _contracts_handler(urls, pages=mo._MAX_PAGES + 5)
    page = MassiveOptionsAdapter("k", client=_client(handler)).fetch_contracts_page(
        "SPY", expiration_gte=date(2023, 11, 17), expiration_lte=date(2023, 11, 17)
    )
    assert page.pages_walked == mo._MAX_PAGES
    assert page.page_cap_hit and not page.next_url_exhausted
    assert not page.is_complete


def test_unparseable_rows_are_counted_not_silently_dropped() -> None:
    urls: list[str] = []
    page = MassiveOptionsAdapter(
        "k", client=_client(_contracts_handler(urls, bad_rows=2))
    ).fetch_contracts_page(
        "SPY", expiration_gte=date(2023, 11, 17), expiration_lte=date(2023, 11, 17)
    )
    assert page.rows_unparseable == 2
    assert not page.is_complete
    assert len(page.rows) == 3


def test_dividends_and_splits_parse_and_sort() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "/v3/reference/dividends" in url:
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "ex_dividend_date": "2024-03-15",
                            "cash_amount": 1.5,
                            "declaration_date": "2024-03-01",
                            "pay_date": "2024-03-28",
                            "frequency": 4,
                            "dividend_type": "CD",
                            "currency": "USD",
                        },
                        {"ex_dividend_date": "2023-12-15", "cash_amount": 1.4},
                        {"cash_amount": 9.9},  # no ex-date: unusable, dropped
                    ]
                },
            )
        return httpx.Response(
            200,
            json={
                "results": [
                    {"execution_date": "2024-06-10", "split_from": 1, "split_to": 10},
                    {"execution_date": "2020-08-31", "split_from": 1, "split_to": 4},
                ]
            },
        )

    a = MassiveOptionsAdapter("k", client=_client(handler))
    divs = a.fetch_dividends("SPY")
    assert [d.ex_dividend_date.isoformat() for d in divs] == ["2023-12-15", "2024-03-15"]
    assert divs[1].frequency == 4
    splits = a.fetch_splits("NVDA")
    assert [s.execution_date.isoformat() for s in splits] == ["2020-08-31", "2024-06-10"]
    assert splits[1].ratio == 10.0
