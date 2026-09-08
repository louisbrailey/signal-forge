"""Bounded historical options-aggregates backfill — offline contract tests.

MockTransport stands in for api.massive.com. Asserts the storage caps
(expirations / contracts / total bars) are enforced *before* fetching, that
whatever a cap drops is recorded on the run, that the backfill is idempotent and
resumable, that every stored bar is labelled HISTORICAL, and that no bar past a
contract's expiration is ever stored.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from signalforge.data.adapters.massive_options import MassiveOptionsAdapter
from signalforge.data.calendar import sessions as _sessions
from signalforge.data.options_backfill import BackfillCaps, backfill_option_aggregates
from signalforge.db.models import OptionAggregateDaily
from signalforge.domain import LatencyCategory

_TODAY = date.today()
_START = _TODAY - timedelta(days=120)


def _occ(underlying: str, expiry: date, strike: float, cp: str = "C") -> str:
    return f"O:{underlying}{expiry.strftime('%y%m%d')}{cp}{round(strike * 1000):08d}"


def _contract_payload(underlyings: list[str], *, n_expiries: int, n_strikes: int) -> dict:
    results = []
    for u in underlyings:
        ref = 100.0
        for e in range(n_expiries):
            expiry = _TODAY + timedelta(days=20 + e * 7)
            for k in range(n_strikes):
                strike = ref * (0.95 + 0.01 * k)
                results.append(
                    {
                        "ticker": _occ(u, expiry, strike),
                        "underlying_ticker": u,
                        "contract_type": "call",
                        "strike_price": round(strike, 2),
                        "expiration_date": expiry.isoformat(),
                        "exercise_style": "american",
                        "shares_per_contract": 100,
                    }
                )
    return {"status": "OK", "results": results}


_AGG_RE = re.compile(r"/v2/aggs/ticker/(?P<tk>[^/]+)/range/1/day/(?P<a>[\d-]+)/(?P<b>[\d-]+)")
_EXP_RE = re.compile(r"O:[A-Z]+(?P<yy>\d\d)(?P<mm>\d\d)(?P<dd>\d\d)[CP]")


def _expiry_of(option_ticker: str) -> date:
    m = _EXP_RE.search(option_ticker)
    assert m
    return date(2000 + int(m["yy"]), int(m["mm"]), int(m["dd"]))


def _make_client(*, n_expiries: int, n_strikes: int, bars_past_expiry: int = 0) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"].startswith("Bearer ")
        url = str(request.url)
        if "/v3/reference/options/contracts" in url:
            us = re.search(r"underlying_ticker=([A-Z]+)", url)
            return httpx.Response(
                200,
                json=_contract_payload(
                    [us.group(1)] if us else ["SPY"],
                    n_expiries=n_expiries,
                    n_strikes=n_strikes,
                ),
            )
        m = _AGG_RE.search(url)
        if m:
            tk = m["tk"]
            a = date.fromisoformat(m["a"])
            b = date.fromisoformat(m["b"])
            expiry = _expiry_of(tk)
            days = list(_sessions(a, min(b, _TODAY)))
            if bars_past_expiry:
                days += list(_sessions(expiry + timedelta(days=1), expiry + timedelta(days=15)))[
                    :bars_past_expiry
                ]
            out = []
            for d in days:
                ts = int(datetime(d.year, d.month, d.day, tzinfo=UTC).timestamp() * 1000)
                out.append(
                    {"t": ts, "o": 1.0, "h": 1.5, "l": 0.8, "c": 1.2, "v": 100, "vw": 1.1, "n": 5}
                )
            return httpx.Response(200, json={"status": "OK", "results": out})
        return httpx.Response(404, json={"status": "NOT_FOUND"})

    return httpx.Client(transport=httpx.MockTransport(handler))


def _adapter(**kw: object) -> MassiveOptionsAdapter:
    return MassiveOptionsAdapter("k", client=_make_client(**kw))  # type: ignore[arg-type]


def _count(session: Session) -> int:
    return session.scalar(select(func.count()).select_from(OptionAggregateDaily)) or 0


# ---------------------------------------------------------------------------
def test_backfill_respects_expiration_and_contract_caps(session: Session) -> None:
    caps = BackfillCaps(
        lookback_days=120,
        expirations_per_underlying=2,
        contracts_per_underlying=6,
        strike_pct_band=0.5,
        max_total_bars=1_000_000,
    )
    run = backfill_option_aggregates(
        session,
        _adapter(n_expiries=5, n_strikes=20),
        ["SPY"],
        start=_START,
        end=_TODAY,
        caps=caps,
    )
    tickers = {t for (t,) in session.execute(select(OptionAggregateDaily.option_ticker).distinct())}
    assert len(tickers) <= 6
    expiries = {_expiry_of(t) for t in tickers}
    assert len(expiries) <= 2
    assert run.status == "ok"
    assert run.gaps_json["SPY"]["contracts"] <= 6
    assert len(run.gaps_json["SPY"]["expirations"]) == 2


def test_backfill_total_bar_cap_trims_and_records_the_drop(session: Session) -> None:
    # ~82 sessions in 120 days -> one contract ~82 bars. Ceiling 120 => room for 1
    # contract on the first underlying, 0 on the second.
    caps = BackfillCaps(
        lookback_days=120,
        expirations_per_underlying=1,
        contracts_per_underlying=10,
        strike_pct_band=0.5,
        max_total_bars=120,
    )
    run = backfill_option_aggregates(
        session,
        _adapter(n_expiries=2, n_strikes=10),
        ["SPY", "QQQ"],
        start=_START,
        end=_TODAY,
        caps=caps,
    )
    assert _count(session) <= 120
    dropped = sum(int(v["dropped_by_cap"]) for v in run.gaps_json.values())
    assert dropped > 0
    assert "ceiling" in run.notes


def test_backfill_is_idempotent(session: Session) -> None:
    caps = BackfillCaps(lookback_days=120, expirations_per_underlying=1, contracts_per_underlying=3)
    a = _adapter(n_expiries=2, n_strikes=6)
    run1 = backfill_option_aggregates(session, a, ["SPY"], start=_START, end=_TODAY, caps=caps)
    n_after_first = _count(session)
    assert run1.bars_written == n_after_first > 0
    run2 = backfill_option_aggregates(
        session, _adapter(n_expiries=2, n_strikes=6), ["SPY"], start=_START, end=_TODAY, caps=caps
    )
    assert run2.bars_written == 0
    assert _count(session) == n_after_first


def test_backfill_resumes_and_skips_completed_underlyings(session: Session) -> None:
    caps = BackfillCaps(lookback_days=120, expirations_per_underlying=1, contracts_per_underlying=2)
    run1 = backfill_option_aggregates(
        session, _adapter(n_expiries=1, n_strikes=4), ["SPY"], start=_START, end=_TODAY, caps=caps
    )
    assert run1.symbols_ok == ["SPY"]
    spy_bars = _count(session)
    run2 = backfill_option_aggregates(
        session,
        _adapter(n_expiries=1, n_strikes=4),
        ["SPY", "QQQ"],
        start=_START,
        end=_TODAY,
        caps=caps,
        resume_run_id=run1.id,
    )
    assert run2.id == run1.id
    assert run2.symbols_ok == ["SPY", "QQQ"]
    assert run2.gaps_json["QQQ"]["bars"] > 0
    # SPY was not re-fetched: its bar count is unchanged
    spy_now = session.scalar(
        select(func.count())
        .select_from(OptionAggregateDaily)
        .where(OptionAggregateDaily.underlying_symbol == "SPY")
    )
    assert spy_now == spy_bars


def test_every_stored_bar_is_labelled_historical(session: Session) -> None:
    backfill_option_aggregates(
        session,
        _adapter(n_expiries=1, n_strikes=4),
        ["SPY"],
        start=_START,
        end=_TODAY,
        caps=BackfillCaps(
            lookback_days=120, expirations_per_underlying=1, contracts_per_underlying=3
        ),
    )
    rows = list(session.scalars(select(OptionAggregateDaily)))
    assert rows
    assert all(r.latency_category is LatencyCategory.HISTORICAL for r in rows)
    assert all(r.source == "massive_options" for r in rows)


def test_backfill_never_stores_a_bar_past_expiry(session: Session) -> None:
    backfill_option_aggregates(
        session,
        _adapter(n_expiries=1, n_strikes=4, bars_past_expiry=5),
        ["SPY"],
        start=_START,
        end=_TODAY,
        caps=BackfillCaps(
            lookback_days=120, expirations_per_underlying=1, contracts_per_underlying=3
        ),
    )
    bad = [
        (r.option_ticker, r.session_date)
        for r in session.scalars(select(OptionAggregateDaily))
        if r.session_date > _expiry_of(r.option_ticker)
    ]
    assert bad == []
