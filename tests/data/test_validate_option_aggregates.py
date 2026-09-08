"""Data-validation checks for the historical options-aggregates store.

Each violation (post-expiry bar, non-trading-day bar, OHLC breach, non-HISTORICAL
latency label, per-underlying cap breach) must fail its matching check; clean
data must pass every check.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from sqlalchemy.orm import Session

from signalforge.data.calendar import sessions as _sessions
from signalforge.data.validate import validate_option_aggregates
from signalforge.db.models import OptionAggregateDaily, OptionContract
from signalforge.domain import LatencyCategory

_TODAY = date.today()
_EXPIRY = _TODAY + timedelta(days=30)
_SRC = "massive_options"


def _contract(session: Session, ticker: str, expiry: date = _EXPIRY) -> None:
    session.add(
        OptionContract(
            option_ticker=ticker,
            underlying_symbol="SPY",
            contract_type="call",
            strike_price=100.0,
            expiration_date=expiry,
            exercise_style="american",
            shares_per_contract=100,
            source=_SRC,
            ingested_at=datetime.now(UTC),
        )
    )
    session.flush()


def _bar(
    session: Session,
    ticker: str,
    d: date,
    *,
    o: float = 1.0,
    h: float = 1.5,
    low: float = 0.8,
    c: float = 1.2,
    volume: float = 10.0,
    latency: LatencyCategory = LatencyCategory.HISTORICAL,
) -> None:
    session.add(
        OptionAggregateDaily(
            option_ticker=ticker,
            underlying_symbol="SPY",
            session_date=d,
            open=o,
            high=h,
            low=low,
            close=c,
            volume=volume,
            vwap=1.1,
            transactions=3,
            source=_SRC,
            latency_category=latency,
            ingested_at=datetime.now(UTC),
            quality_flags=[],
        )
    )
    session.flush()


def _clean(session: Session, ticker: str = "O:SPY_C1", n: int = 10) -> None:
    _contract(session, ticker)
    days = list(_sessions(_TODAY - timedelta(days=30), _TODAY))[:n]
    for d in days:
        _bar(session, ticker, d)


# ---------------------------------------------------------------------------
def test_clean_backfill_passes_every_check(session: Session) -> None:
    _clean(session)
    res = validate_option_aggregates(session, ["SPY"], persist=True)
    assert res.passed, [f"{c.name}: {c.detail}" for c in res.checks if not c.passed]
    assert res.provider == "massive_options_agg"


def test_flags_post_expiry_bar(session: Session) -> None:
    _clean(session)
    _bar(session, "O:SPY_C1", _EXPIRY + timedelta(days=3))  # 3 days after expiry
    res = validate_option_aggregates(session, ["SPY"], persist=False)
    failed = {c.name for c in res.checks if not c.passed}
    assert "no_post_expiry_bars" in failed


def test_flags_non_trading_day_bar(session: Session) -> None:
    _clean(session)
    # find a Saturday near today
    d = _TODAY
    while d.weekday() != 5:
        d -= timedelta(days=1)
    _bar(session, "O:SPY_C1", d)
    res = validate_option_aggregates(session, ["SPY"], persist=False)
    assert "sessions_are_trading_days" in {c.name for c in res.checks if not c.passed}


def test_flags_ohlc_breach(session: Session) -> None:
    _clean(session)
    trading = next(iter(_sessions(_TODAY - timedelta(days=5), _TODAY)))
    _bar(session, "O:SPY_C2", trading, o=1.0, h=0.5, low=0.9, c=1.2)  # high < low, high < open
    _contract(session, "O:SPY_C2")
    res = validate_option_aggregates(session, ["SPY"], persist=False)
    assert "ohlcv_sanity" in {c.name for c in res.checks if not c.passed}


def test_flags_non_historical_latency(session: Session) -> None:
    _contract(session, "O:SPY_C3")
    trading = next(iter(_sessions(_TODAY - timedelta(days=5), _TODAY)))
    _bar(session, "O:SPY_C3", trading, latency=LatencyCategory.DELAYED)
    res = validate_option_aggregates(session, ["SPY"], persist=False)
    assert "latency_labelled_historical" in {c.name for c in res.checks if not c.passed}


def test_flags_per_underlying_cap_breach(session: Session) -> None:
    days = list(_sessions(_TODAY - timedelta(days=20), _TODAY))
    for i in range(5):
        tk = f"O:SPY_C{i}"
        _contract(session, tk)
        _bar(session, tk, days[i])

    class _Caps:
        contracts_per_underlying = 3
        max_total_bars = 1_000_000

    res = validate_option_aggregates(session, ["SPY"], caps=_Caps(), persist=False)
    assert "caps_respected" in {c.name for c in res.checks if not c.passed}
