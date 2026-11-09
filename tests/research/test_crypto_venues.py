"""Per-venue crypto costs and the long-only variants — synthetic data only."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, date, datetime, timedelta

import numpy as np
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from signalforge.data.series import PriceSeries
from signalforge.db.models import CurrencySealedTest
from signalforge.domain import Direction
from signalforge.research.fx import harness as h
from signalforge.research.fx import sealed as sl
from signalforge.research.fx.hourly import (
    CRYPTO_H4_STRATEGIES,
    CRYPTO_H5_PAIRS,
    CRYPTO_H5_STRATEGIES,
    CRYPTO_H5_VERSION,
    HOURLY_STRATEGIES,
)
from signalforge.research.fx.strategies import (
    CRYPTO2_STRATEGIES,
    CRYPTO5_PAIRS,
    CRYPTO5_STRATEGIES,
    CRYPTO_STRATEGIES,
    _donchian,
)
from signalforge.research.fx.venues import (
    COINBASE_CFM_INTRO,
    COINBASE_SPOT_INTRO,
    HARNESS_DEFAULT,
    VENUES,
    get_venue,
)

LONG_KEYS = ("crypto_donchian_55_long", "crypto_donchian_55_u10_long")
HOURLY_LONG = "crypto_h_donchian168_trail72_volx_long"


def _crypto_series(pair: str, seed: int, n: int = 1500) -> PriceSeries:
    rng = np.random.default_rng(seed)
    drift = np.where((np.arange(n) // 150) % 2 == 0, 0.003, -0.003)
    closes = 20000 * np.exp(np.cumsum(drift + rng.normal(0, 0.03, n)))
    rows, prev = [], float(closes[0])
    for i, c in enumerate(closes):
        c = float(c)
        d = date(2020, 1, 1) + timedelta(days=i)
        rows.append((d, prev, max(prev, c) * 1.01, min(prev, c) * 0.99, c))
        prev = c
    return PriceSeries.from_bars(pair, [(*r, 0.0) for r in rows])


# --- venue spec -------------------------------------------------------------- #


def test_harness_default_is_exactly_todays_crypto_spreads() -> None:
    for pair in [*h.CRYPTO_SPREAD_BPS, "XRPUSD", "BNBUSD", "ANYUSD"]:
        assert HARNESS_DEFAULT.engine_spread_bps(pair) == h.CRYPTO_MARKET.spread(pair)
    assert HARNESS_DEFAULT.funding_bps_per_year == 0.0
    assert HARNESS_DEFAULT.contract_fee_bps("BTCUSD") == 0.0
    assert get_venue("harness_default") is HARNESS_DEFAULT


def test_named_venues_carry_the_account_fee_tiers() -> None:
    assert set(VENUES) == {"harness_default", "coinbase_spot_intro", "coinbase_cfm_intro"}
    spot, cfm = COINBASE_SPOT_INTRO, COINBASE_CFM_INTRO
    assert (spot.maker_bps, spot.taker_bps, spot.can_short) == (50.0, 90.0, False)
    assert (cfm.maker_bps, cfm.taker_bps, cfm.contract_fee_usd) == (9.5, 10.0, 0.15)
    assert cfm.funding_bps_per_year == 0.0
    assert cfm.contract_size == {
        "BTCUSD": 0.01,
        "ETHUSD": 0.1,
        "SOLUSD": 5.0,
        "XRPUSD": 500.0,
        "DOGEUSD": 5000.0,
        "ADAUSD": 1000.0,
        "LINKUSD": 50.0,
        "AVAXUSD": 10.0,
        "LTCUSD": 5.0,
        "BNBUSD": 1.0,
    }
    # $0.15 on one 0.01 BTC contract at $75,690 = 1.98 bps; at a given price it scales
    assert cfm.contract_fee_bps("BTCUSD") == pytest.approx(0.15 / 756.9 * 1e4)
    assert cfm.contract_fee_bps("BTCUSD", price=50000.0) == pytest.approx(3.0)
    # spot: same half-spread, 80 bps more taker per side than the harness
    assert spot.engine_spread_bps("BTCUSD") == pytest.approx(24.0 + 160.0)
    assert cfm.with_funding(500).funding_bps_per_year == 500.0
    assert get_venue("coinbase_cfm_intro", funding_bps_per_year=100).funding_bps_per_year == 100
    with pytest.raises(ValueError, match="unknown venue"):
        get_venue("binance")
    with pytest.raises(ValueError, match="no contract size"):
        cfm.contract_fee_bps("FOOUSD")


# --- harness venue parameter ------------------------------------------------- #


def _eval(strat_key: str, venue=None):  # type: ignore[no-untyped-def]
    strat = next(s for s in CRYPTO_STRATEGIES if s.key == strat_key)
    series = {"BTCUSD": _crypto_series("BTCUSD", 3), "ETHUSD": _crypto_series("ETHUSD", 4)}
    seal_from = h.sealed_start(series, 365)
    return h.evaluate_strategy(
        strat, series, seal_from=seal_from, gates=h.FxGates(), market=h.CRYPTO_MARKET, venue=venue
    )


def test_harness_default_venue_leaves_the_evaluation_byte_for_byte_unchanged() -> None:
    plain = _eval("crypto_donchian_55")
    via = _eval("crypto_donchian_55", HARNESS_DEFAULT)
    assert plain.pooled["n_trades"] > 0
    assert json.dumps(asdict(plain), sort_keys=True, default=str) == json.dumps(
        asdict(via), sort_keys=True, default=str
    )


def test_a_dearer_venue_costs_the_same_trades_more() -> None:
    base = _eval("crypto_donchian_55")
    spot = _eval("crypto_donchian_55", COINBASE_SPOT_INTRO)
    cfm = _eval("crypto_donchian_55", COINBASE_CFM_INTRO)
    funded = _eval("crypto_donchian_55", COINBASE_CFM_INTRO.with_funding(1000))
    assert base.pooled["n_trades"] == spot.pooled["n_trades"] == cfm.pooled["n_trades"]
    assert spot.pooled["expectancy_r"] < cfm.pooled["expectancy_r"] < base.pooled["expectancy_r"]
    assert funded.pooled["expectancy_r"] < cfm.pooled["expectancy_r"]
    assert funded.pooled["n_trades"] == cfm.pooled["n_trades"]


def test_run_research_reports_the_venue_only_when_one_is_given(session: Session) -> None:
    from signalforge.db.models import CryptoBarDaily
    from signalforge.domain import LatencyCategory

    s = _crypto_series("BTCUSD", 5, n=900)
    now = datetime(2026, 1, 1, tzinfo=UTC)
    for d, o, hi, lo, c in zip(s.dates, s.open, s.high, s.low, s.close, strict=True):
        session.add(
            CryptoBarDaily(
                pair="BTCUSD",
                session_date=d,
                open=float(o),
                high=float(hi),
                low=float(lo),
                close=float(c),
                source="massive_crypto",
                latency_category=LatencyCategory.END_OF_DAY,
                ingested_at=now,
                quality_flags=[],
            )
        )
    session.commit()
    plain = h.run_crypto_research(session, ["BTCUSD"])
    assert "venue" not in plain and plain["spread_bps"] == {"BTCUSD": 24.0}
    via_default = h.run_research(
        session,
        ["BTCUSD"],
        market=h.CRYPTO_MARKET,
        strategies=h.CRYPTO_STRATEGIES,
        venue=HARNESS_DEFAULT,
    )
    via_default.pop("venue")
    assert json.dumps(via_default, default=str) == json.dumps(plain, default=str)
    rep = h.run_research(
        session,
        ["BTCUSD"],
        market=h.CRYPTO_MARKET,
        strategies=h.CRYPTO_STRATEGIES,
        venue=COINBASE_SPOT_INTRO,
    )
    assert rep["venue"]["name"] == "coinbase_spot_intro"
    assert rep["spread_bps"] == {"BTCUSD": pytest.approx(184.0)}


# --- long-only variants ------------------------------------------------------ #


def test_parents_are_unchanged_and_long_variants_only_go_long() -> None:
    d55 = next(s for s in CRYPTO_STRATEGIES if s.key == "crypto_donchian_55")
    assert d55.signal is _donchian and "long_only" not in d55.params
    u10 = next(s for s in CRYPTO2_STRATEGIES if s.key == "crypto_donchian_55_u10")
    volx = CRYPTO_H4_STRATEGIES[2]
    parents = {LONG_KEYS[0]: d55, LONG_KEYS[1]: u10}
    for s in CRYPTO5_STRATEGIES:
        p = parents[s.key]
        assert s.params == {**p.params, "long_only": 1}
        assert (s.warmup, s.trail_channel) == (p.warmup, p.trail_channel)
    (hl,) = CRYPTO_H5_STRATEGIES
    assert hl.key == HOURLY_LONG and hl.params == {**volx.params, "long_only": 1}
    assert (hl.warmup, hl.trail_channel) == (volx.warmup, volx.trail_channel) == (170, 72)
    assert HOURLY_STRATEGIES[CRYPTO_H5_VERSION] is CRYPTO_H5_STRATEGIES

    series = _crypto_series("BTCUSD", 7)
    longs = shorts = 0
    for t in range(d55.warmup, len(series) - 1):
        parent = d55.signal(series.head(t), t)
        child = CRYPTO5_STRATEGIES[0].signal(series.head(t), t)
        if parent is not None and parent.direction is Direction.SHORT:
            shorts += 1
            assert child is None
        else:
            longs += parent is not None
            assert child == parent
    assert longs and shorts, "fixture must produce both directions"


def test_long_variants_use_their_parents_pairs() -> None:
    assert CRYPTO5_PAIRS["crypto_donchian_55_long"] == ("BTCUSD", "ETHUSD", "SOLUSD")
    u10 = CRYPTO5_PAIRS["crypto_donchian_55_u10_long"]
    assert len(u10) == 9 and "BNBUSD" not in u10
    assert CRYPTO_H5_PAIRS == {HOURLY_LONG: ("BTCUSD", "ETHUSD")}


def test_long_variants_are_registered_as_their_own_unsealed_versions(session: Session) -> None:
    for key in LONG_KEYS:
        mk, strat, gates = sl._lookup("crypto", key)
        assert (mk.name, mk.version) == ("Crypto", "CRYPTO-5")
        assert strat.params["long_only"] == 1 and gates == h.FxGates()
    mk, strat, _ = sl._lookup("crypto_hourly", HOURLY_LONG)
    assert (mk.name, mk.version) == ("Crypto (hourly)", "CRYPTO-H5")
    # Parents keep their versions.
    assert sl._lookup("crypto", "crypto_donchian_55")[0].version == "CRYPTO-1"
    assert sl._lookup("crypto", "crypto_donchian_55_u10")[0].version == "CRYPTO-2"
    assert (
        sl._lookup("crypto_hourly", "crypto_h_donchian168_trail72_volx")[0].version == "CRYPTO-H4"
    )


def _parent_rows(session: Session) -> None:
    for market, version, key, pairs in (
        ("Crypto", "CRYPTO-1", "crypto_donchian_55", ["BTCUSD", "ETHUSD", "SOLUSD"]),
        ("Crypto", "CRYPTO-2", "crypto_donchian_55_u10", ["BTCUSD"]),
        ("Crypto (hourly)", "CRYPTO-H4", "crypto_h_donchian168_trail72_volx", ["BTCUSD"]),
    ):
        session.add(
            CurrencySealedTest(
                market=market,
                version=version,
                strategy_key=key,
                sealed_from=date(2025, 11, 3),
                sealed_to=date(2026, 11, 2),
                pairs=pairs,
                result={"metrics": {"expectancy_r": 0.9}},
                verdict="SEALED_PASS",
            )
        )
    session.commit()


def test_no_sealed_result_or_paper_book_by_inheritance(session: Session) -> None:
    from signalforge.paper import crypto_hourly_ledger as hl
    from signalforge.paper import crypto_ledger as cl

    _parent_rows(session)
    now = datetime(2026, 11, 8, tzinfo=UTC)
    for key in LONG_KEYS:
        assert sl.existing(session, "crypto", key) is None
        with pytest.raises(cl.PaperBookRefused, match="CRYPTO-5 has no sealed test"):
            cl.start_book(session, key, now=now)
        assert cl.get_book(session, key) is None
    assert sl.existing(session, "crypto_hourly", HOURLY_LONG) is None
    with pytest.raises(hl.PaperBookRefused, match="CRYPTO-H5 has no sealed test"):
        hl.start_book(session, HOURLY_LONG, now=now)
    # A parent's book still starts: the parents are unaffected.
    assert cl.start_book(session, "crypto_donchian_55", now=now).version == "CRYPTO-1"


def _hourly_bars(session: Session, start: datetime, hours: int) -> None:
    from signalforge.db.models import CryptoBarIntraday
    from signalforge.domain import LatencyCategory

    rng = np.random.default_rng(11)
    closes = 30000 * np.exp(np.cumsum(rng.normal(0.00005, 0.004, hours)))
    prev = float(closes[0])
    for i, c in enumerate(closes):
        c = float(c)
        session.add(
            CryptoBarIntraday(
                pair="BTCUSD",
                bar_size="1h",
                bar_start=start + timedelta(hours=i),
                open=prev,
                high=max(prev, c) * 1.002,
                low=min(prev, c) * 0.998,
                close=c,
                source="massive_crypto",
                latency_category=LatencyCategory.END_OF_DAY,
                ingested_at=start,
            )
        )
        prev = c
    session.commit()


def test_a_sealed_look_is_refused_until_its_window_is_fresh(session: Session) -> None:
    """Data ending 2026-11-08: the sealed window would start 2025-11-09, inside
    bars already seen. Refused BEFORE any evaluation, and no row is written."""
    _hourly_bars(session, datetime(2024, 11, 1, tzinfo=UTC), 24 * 738)
    with pytest.raises(
        sl.SealedTestRefused, match=r"EXPERIMENTAL.*may not start before 2026-11-09"
    ):
        sl.run_sealed_test(session, "crypto_hourly", HOURLY_LONG, ["BTCUSD"])
    assert session.scalars(select(CurrencySealedTest)).all() == []
    assert sl.SEALED_NOT_BEFORE[("Crypto", "CRYPTO-5")] == date(2026, 11, 9)


def test_a_fresh_window_passes_the_freshness_guard(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Data through 2027-12: the sealed window starts after 2026-11-09, so the
    guard lets the request through to the development gate (stubbed to fail
    here, so the synthetic look is never actually taken)."""
    _hourly_bars(session, datetime(2026, 1, 1, tzinfo=UTC), 24 * 720)
    calls: list[str] = []

    def dev_fail(strat, *a, **k):  # type: ignore[no-untyped-def]
        calls.append(strat.key)
        return h.StrategyResult(key=strat.key, description="", params={}, reasons=["stub"])

    monkeypatch.setattr(sl, "evaluate_strategy", dev_fail)
    with pytest.raises(sl.SealedTestRefused, match="DEV_FAIL"):
        sl.run_sealed_test(session, "crypto_hourly", HOURLY_LONG, ["BTCUSD"])
    assert calls == [HOURLY_LONG]
    assert session.scalars(select(CurrencySealedTest)).all() == []


# --- review fixes (2026-11-08) ----------------------------------------------- #


def _daily_bars(session: Session, pair: str, end: date, n: int = 900, seed: int = 5) -> None:
    from signalforge.db.models import CryptoBarDaily
    from signalforge.domain import LatencyCategory

    s = _crypto_series(pair, seed, n=n)
    shift = end - s.dates[-1]
    now = datetime(2026, 1, 1, tzinfo=UTC)
    for d, o, hi, lo, c in zip(s.dates, s.open, s.high, s.low, s.close, strict=True):
        session.add(
            CryptoBarDaily(
                pair=pair,
                session_date=d + shift,
                open=float(o),
                high=float(hi),
                low=float(lo),
                close=float(c),
                source="massive_crypto",
                latency_category=LatencyCategory.END_OF_DAY,
                ingested_at=now,
                quality_flags=[],
            )
        )
    session.commit()


@pytest.mark.parametrize("key", LONG_KEYS)
def test_a_daily_sealed_look_is_refused_until_its_window_is_fresh(
    session: Session, key: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    _daily_bars(session, "BTCUSD", date(2026, 11, 8))

    def never(*a, **k):  # type: ignore[no-untyped-def]
        raise AssertionError("the development window must not be evaluated")

    monkeypatch.setattr(sl, "evaluate_strategy", never)
    with pytest.raises(
        sl.SealedTestRefused, match=r"Crypto CRYPTO-5 .*EXPERIMENTAL.*2026-11-09.*operator decision"
    ):
        sl.run_sealed_test(session, "crypto", key, ["BTCUSD"])
    assert session.scalars(select(CurrencySealedTest)).all() == []


@pytest.mark.parametrize(
    ("market", "key"),
    [("crypto", LONG_KEYS[0]), ("crypto", LONG_KEYS[1]), ("crypto_hourly", HOURLY_LONG)],
)
def test_an_experimental_sealed_look_refuses_caller_gates(
    session: Session, market: str, key: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A shrunken window (sealed_days=90) could start after the guard date and
    pass it; for these versions only the registered gates are accepted, and the
    check runs before any bar is loaded."""

    def never(*a, **k):  # type: ignore[no-untyped-def]
        raise AssertionError("nothing may be loaded or evaluated")

    monkeypatch.setattr(sl, "_series_loader", never)
    with pytest.raises(sl.SealedTestRefused, match="caller-supplied gates"):
        sl.run_sealed_test(session, market, key, ["BTCUSD"], gates=h.FxGates(sealed_days=90))
    assert session.scalars(select(CurrencySealedTest)).all() == []


def test_registered_gates_passed_explicitly_still_reach_the_date_guard(session: Session) -> None:
    _daily_bars(session, "BTCUSD", date(2026, 11, 8))
    with pytest.raises(sl.SealedTestRefused, match="may not start before 2026-11-09"):
        sl.run_sealed_test(session, "crypto", LONG_KEYS[0], ["BTCUSD"], gates=h.FxGates())


def test_a_parent_keeps_accepting_caller_gates(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _daily_bars(session, "BTCUSD", date(2026, 11, 8))

    def dev_fail(strat, *a, **k):  # type: ignore[no-untyped-def]
        return h.StrategyResult(key=strat.key, description="", params={}, reasons=["stub"])

    monkeypatch.setattr(sl, "evaluate_strategy", dev_fail)
    with pytest.raises(sl.SealedTestRefused, match="DEV_FAIL"):
        sl.run_sealed_test(
            session, "crypto", "crypto_donchian_55", ["BTCUSD"], gates=h.FxGates(sealed_days=90)
        )


def test_a_fresh_experimental_sealed_row_carries_the_holdout_caveat(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Synthetic bars through 2027-12-31 (window from 2027-01-01) in the test
    database: the row records that the window is not an unseen holdout. A
    parent row on the same bars carries no such key."""
    _daily_bars(session, "BTCUSD", date(2027, 12, 31), n=1500)

    def dev_pass(strat, *a, **k):  # type: ignore[no-untyped-def]
        return h.StrategyResult(key=strat.key, description="", params={}, verdict="DEV_PASS")

    monkeypatch.setattr(sl, "evaluate_strategy", dev_pass)
    row = sl.run_sealed_test(session, "crypto", LONG_KEYS[0], ["BTCUSD"])
    assert row.sealed_from == date(2027, 1, 1)
    assert row.dev_summary["holdout_caveat"] == sl.HOLDOUT_CAVEAT
    assert "not an unseen holdout" in sl.HOLDOUT_CAVEAT
    parent = sl.run_sealed_test(session, "crypto", "crypto_donchian_55", ["BTCUSD"])
    assert "holdout_caveat" not in parent.dev_summary


def test_crypto5_research_cuts_before_the_parents_sealed_years(session: Session) -> None:
    _daily_bars(session, "BTCUSD", date(2026, 11, 8))
    rep = h.run_crypto5_research(session, ["BTCUSD"])
    assert rep["version"] == "CRYPTO-5" and rep["sealed_from"] == "2025-10-26"
    assert all(
        date.fromisoformat(p["dev_end"]) < date(2025, 10, 26)
        for s in rep["strategies"]
        for p in s["pairs"]
    )
    # The parents' runners keep their own cut (the final 365 days).
    assert h.run_crypto2_research(session, ["BTCUSD"])["sealed_from"] == "2025-11-09"


def test_crypto_h5_research_cuts_before_h4s_sealed_year(session: Session) -> None:
    from signalforge.research.fx.hourly import run_crypto_hourly_research

    _hourly_bars(session, datetime(2024, 11, 1, tzinfo=UTC), 24 * 738)
    rep = run_crypto_hourly_research(session, ["BTCUSD"], version=CRYPTO_H5_VERSION)
    assert rep["sealed_from"] == "2025-11-03T00:00:00+00:00"
    h4 = run_crypto_hourly_research(session, ["BTCUSD"], version="CRYPTO-H4")
    assert h4["sealed_from"] > "2025-11-08"


def test_a_venue_that_cannot_short_fails_a_two_sided_rule() -> None:
    spot = _eval("crypto_donchian_55", COINBASE_SPOT_INTRO)
    assert spot.verdict == "DEV_FAIL"
    assert any("coinbase_spot_intro cannot short" in r for r in spot.reasons)
    for venue in (None, HARNESS_DEFAULT, COINBASE_CFM_INTRO):
        assert not any("cannot short" in r for r in _eval("crypto_donchian_55", venue).reasons)
    long_only = CRYPTO5_STRATEGIES[0]
    series = {"BTCUSD": _crypto_series("BTCUSD", 3), "ETHUSD": _crypto_series("ETHUSD", 4)}
    res = h.evaluate_strategy(
        long_only,
        series,
        seal_from=h.sealed_start(series, 365),
        gates=h.FxGates(),
        market=h.CRYPTO5_MARKET,
        venue=COINBASE_SPOT_INTRO,
    )
    assert res.pooled["n_trades"] > 0
    assert not any("cannot short" in r for r in res.reasons)


def test_funding_keeps_each_trade_internally_consistent() -> None:
    from signalforge.backtest.costs import CostModel

    strat = next(s for s in CRYPTO_STRATEGIES if s.key == "crypto_donchian_55")
    out = h.backtest(
        strat,
        _crypto_series("BTCUSD", 3),
        cost_model=CostModel(slippage_bps=1.0),
        spread_bps=COINBASE_CFM_INTRO.engine_spread_bps("BTCUSD"),
    )
    funded = h._charge_funding(out.trades, COINBASE_CFM_INTRO.with_funding(1000), 1.0)
    assert len(funded) == len(out.trades) > 0
    for before, after in zip(out.trades, funded, strict=True):
        assert after.pnl_r < before.pnl_r
        assert after.pnl_dollars == pytest.approx(after.pnl_r * 1_000.0)
        if before.pnl_r and after.pnl_r:
            assert after.pnl_pct / after.pnl_r == pytest.approx(before.pnl_pct / before.pnl_r)
    # holding_cost_r reads the same risk fraction before and after funding
    gates_cost = 5.0
    for before, after in zip(out.trades, funded, strict=True):
        if before.pnl_r and after.pnl_r:
            assert h.holding_cost_r(after, gates_cost, 0.0) == pytest.approx(
                h.holding_cost_r(before, gates_cost, 0.0)
            )
