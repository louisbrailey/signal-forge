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


def _make_client(
    *,
    n_expiries: int,
    n_strikes: int,
    bars_past_expiry: int = 0,
    fail_tickers: frozenset[str] = frozenset(),
    fail_status: int = 503,
    overshoot: bool = False,
    future_bars: int = 0,
) -> httpx.Client:
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
            if tk in fail_tickers:
                return httpx.Response(fail_status, json={"status": "ERROR"})
            a = date.fromisoformat(m["a"])
            b = date.fromisoformat(m["b"])
            expiry = _expiry_of(tk)
            days = list(_sessions(a, min(b, _TODAY)))
            if overshoot:
                # a vendor quirk: extra bars on non-trading days *within the
                # requested, in-window range* — inflates the per-contract count
                # beyond what the XNYS-session estimate (expected_per_contract)
                # predicted, without tripping the future/past-expiry/window guard.
                d = a
                while d <= min(b, _TODAY):
                    if d.weekday() >= 5 and d not in days:  # Sat/Sun, not already a session
                        days.append(d)
                    d += timedelta(days=1)
            if bars_past_expiry:
                days += list(_sessions(expiry + timedelta(days=1), expiry + timedelta(days=15)))[
                    :bars_past_expiry
                ]
            if future_bars:
                days += [_TODAY + timedelta(days=i + 1) for i in range(future_bars)]
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


def test_backfill_never_stores_a_future_dated_bar(session: Session) -> None:
    backfill_option_aggregates(
        session,
        _adapter(n_expiries=1, n_strikes=4, future_bars=5),
        ["SPY"],
        start=_START,
        end=_TODAY,
        caps=BackfillCaps(
            lookback_days=120, expirations_per_underlying=1, contracts_per_underlying=3
        ),
    )
    assert all(r.session_date <= _TODAY for r in session.scalars(select(OptionAggregateDaily)))


# ---- regression tests for the adversarial-review findings -----------------
def test_underlying_with_every_contract_failing_is_not_marked_done_and_resume_retries_it(
    session: Session,
) -> None:
    """A transient per-contract failure must leave the underlying retryable on
    --resume, never silently marked complete (review finding: resume-idempotency #1)."""
    caps = BackfillCaps(lookback_days=120, expirations_per_underlying=1, contracts_per_underlying=2)

    # discover which contracts will be selected so we can fail exactly those
    probe_adapter = _adapter(n_expiries=1, n_strikes=2)
    real_tickers = frozenset(
        c.option_ticker
        for c in probe_adapter.fetch_contracts(
            "QQQ", expiration_gte=_START, expiration_lte=_TODAY + timedelta(days=150)
        )
    )
    failing_adapter = MassiveOptionsAdapter(
        "k", client=_make_client(n_expiries=1, n_strikes=2, fail_tickers=real_tickers)
    )
    run1 = backfill_option_aggregates(
        session, failing_adapter, ["QQQ"], start=_START, end=_TODAY, caps=caps
    )
    assert run1.symbols_ok == []  # NOT marked done — every contract failed
    assert run1.status in ("partial", "failed")
    assert any(k.startswith("QQQ:") for k in run1.symbols_failed)

    ok_adapter = _adapter(n_expiries=1, n_strikes=2)
    run2 = backfill_option_aggregates(
        session, ok_adapter, ["QQQ"], start=_START, end=_TODAY, caps=caps, resume_run_id=run1.id
    )
    assert run2.symbols_ok == ["QQQ"]  # retried and completed on resume
    assert run2.status == "ok"
    assert not run2.symbols_failed  # stale failure keys cleared


def test_total_bar_cap_is_a_hard_ceiling_even_if_a_contract_overshoots_the_estimate(
    session: Session,
) -> None:
    """The pre-fetch estimate is a heuristic; the runtime check must be authoritative
    (review finding: cap-enforcement #2/#3)."""
    caps = BackfillCaps(
        lookback_days=30,  # expected_per_contract is small...
        expirations_per_underlying=1,
        contracts_per_underlying=5,
        max_total_bars=50,  # ...but each contract actually returns ~a year of bars
    )
    run = backfill_option_aggregates(
        session,
        _adapter(n_expiries=1, n_strikes=5, overshoot=True),
        ["SPY"],
        start=_START,
        end=_TODAY,
        caps=caps,
    )
    assert _count(session) <= caps.max_total_bars
    assert "ceiling" in run.notes and "SPY" in run.notes


def test_selection_caps_record_what_they_dropped(session: Session) -> None:
    """expirations_per_underlying / contracts_per_underlying truncation must be
    recorded, not just the total-bar cap (review finding: cap-enforcement #4)."""
    caps = BackfillCaps(
        lookback_days=120,
        expirations_per_underlying=2,
        contracts_per_underlying=6,
        strike_pct_band=0.5,
        max_total_bars=1_000_000,
    )
    run = backfill_option_aggregates(
        session, _adapter(n_expiries=5, n_strikes=20), ["SPY"], start=_START, end=_TODAY, caps=caps
    )
    d = run.gaps_json["SPY"]
    assert d["dropped_expirations"] == 3  # 5 fetched, 2 kept
    assert d["dropped_by_cap"] > 0  # the ATM-ranked tail beyond 6 contracts


def test_out_of_range_stored_bar_cannot_permanently_freeze_a_contract(session: Session) -> None:
    """A single out-of-range row (e.g. a legacy row from before this guard existed)
    must never poison the 'already covered' check for the rest of the window
    (review finding: labelling-and-leakage #5)."""
    caps = BackfillCaps(lookback_days=120, expirations_per_underlying=1, contracts_per_underlying=1)
    probe_adapter = _adapter(n_expiries=1, n_strikes=1)
    contract = probe_adapter.fetch_contracts(
        "SPY", expiration_gte=_START, expiration_lte=_TODAY + timedelta(days=150)
    )[0]
    # a poison row far past the contract's expiry — unbounded max(have) would
    # otherwise make the "already covered to hard_end" check trivially true.
    session.add(
        OptionAggregateDaily(
            option_ticker=contract.option_ticker,
            underlying_symbol="SPY",
            session_date=contract.expiration_date + timedelta(days=400),
            open=1.0,
            high=1.0,
            low=1.0,
            close=1.0,
            volume=0.0,
            source="massive_options",
            latency_category=LatencyCategory.HISTORICAL,
            ingested_at=datetime.now(UTC),
            quality_flags=["backfilled_test_poison_row"],
        )
    )
    session.flush()

    backfill_option_aggregates(
        session, _adapter(n_expiries=1, n_strikes=1), ["SPY"], start=_START, end=_TODAY, caps=caps
    )
    have = {
        d
        for (d,) in session.execute(
            select(OptionAggregateDaily.session_date).where(
                OptionAggregateDaily.option_ticker == contract.option_ticker
            )
        )
    }
    expected = set(_sessions(_START, _TODAY))
    assert expected <= have  # the poison row did not stop the real window from filling in


def test_contract_bar_clamp_is_recorded_on_the_run(session: Session) -> None:
    """review finding: cap-enforcement #8 — the per-contract defensive clamp must
    show up in gaps_json and notes, not just a log line."""
    import signalforge.data.options_backfill as _mod

    old = _mod._MAX_BARS_PER_CONTRACT
    _mod._MAX_BARS_PER_CONTRACT = 10  # force the clamp to trip on ordinary data
    try:
        run = backfill_option_aggregates(
            session,
            _adapter(n_expiries=1, n_strikes=1, overshoot=True),
            ["SPY"],
            start=_START,
            end=_TODAY,
            caps=BackfillCaps(
                lookback_days=400,
                expirations_per_underlying=1,
                contracts_per_underlying=1,
                max_total_bars=1_000_000,
            ),
        )
    finally:
        _mod._MAX_BARS_PER_CONTRACT = old
    assert run.gaps_json["SPY"]["bars_clamped"] > 0
    assert "clamp" in run.notes


def test_budget_trimmed_underlying_is_retried_after_a_higher_cap_resume(session: Session) -> None:
    """A whole underlying dropped by the GLOBAL total-bar budget (not the fixed
    per-underlying selection caps) must stay retryable — otherwise raising
    --max-total-bars and resuming can never recover it (dismissed-but-verified-
    independently review finding: 'cap-exhausted symbol marked ok, skipped
    forever on a higher-cap resume')."""
    tight = BackfillCaps(
        lookback_days=120,
        expirations_per_underlying=1,
        contracts_per_underlying=10,
        strike_pct_band=0.5,
        max_total_bars=90,  # enough for SPY alone, nothing left for QQQ
    )
    run1 = backfill_option_aggregates(
        session,
        _adapter(n_expiries=2, n_strikes=10),
        ["SPY", "QQQ"],
        start=_START,
        end=_TODAY,
        caps=tight,
    )
    assert "QQQ" not in run1.symbols_ok  # budget-starved, not permanently "done"
    assert run1.gaps_json["QQQ"]["contracts"] == 0
    qqq_bars_after_1 = session.scalar(
        select(func.count())
        .select_from(OptionAggregateDaily)
        .where(OptionAggregateDaily.underlying_symbol == "QQQ")
    )
    assert qqq_bars_after_1 == 0

    generous = BackfillCaps(
        lookback_days=120,
        expirations_per_underlying=1,
        contracts_per_underlying=10,
        strike_pct_band=0.5,
        max_total_bars=100_000,
    )
    run2 = backfill_option_aggregates(
        session,
        _adapter(n_expiries=2, n_strikes=10),
        ["SPY", "QQQ"],
        start=_START,
        end=_TODAY,
        caps=generous,
        resume_run_id=run1.id,
    )
    assert "QQQ" in run2.symbols_ok  # recovered once the budget allowed it
    qqq_bars_after_2 = session.scalar(
        select(func.count())
        .select_from(OptionAggregateDaily)
        .where(OptionAggregateDaily.underlying_symbol == "QQQ")
    )
    assert qqq_bars_after_2 > 0
