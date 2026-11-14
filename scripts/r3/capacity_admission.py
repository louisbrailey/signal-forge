"""R3-C: admission order, trim-to-budget and the luck band in a funded account.

Pre-registration: docs/research/PREREGISTRATION_r3_capacity_admission_2026-11-10.md
Results file:     docs/research/RESULTS_r3_capacity_admission_2026-11-10.md

Read-only research on a private scratch copy of the database, development window
only (bars end 2025-09-05). No library code is edited: this script carries a local
copy of the ``run_funded_replay`` day loop (``signalforge/backtest/funded.py``) in
which

* the same-day admission order is pluggable (alphabetical, seeded random, K1-K3);
* the three outright rejections of ``risk.engine.size_position`` (gross, sector,
  open risk) can be replaced by trim-to-budget;
* an accepts-per-day cap can be applied.

Stages (``python capacity_admission.py <stage>``):

  prepare   load each book, build its signal table and ranking keys, and run the
            identity check against the library (alphabetical order, outright
            rejection). Stops the study if the check fails.
  grid      every pre-registered arm at base costs -> runs.csv
  analyze   luck band, paired trim test, key percentiles, verdicts -> summary.json
  stress    stress-cost runs for the final table only -> stress_runs.csv
  report    markdown tables from the saved outputs

Research signal only - no order was placed.
"""
# ruff: noqa: E501 - markdown table rows and their f-strings are kept on one line

from __future__ import annotations

import argparse
import csv
import json
import math
import multiprocessing as mp
import os
import pickle
import sqlite3
import subprocess
import sys
import time
from bisect import bisect_right
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from datetime import date
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from pathlib import Path
from typing import Any

import funded_replay_report as frr
import numpy as np

from signalforge.backtest.actions import Dividend
from signalforge.backtest.costs import CostModel
from signalforge.backtest.funded import (
    AttributedEntrySignal,
    EntryProposal,
    EntryVerdict,
    FundedReplay,
    Position,
    composite_signal_fn,
    money,
    run_funded_replay,
    sell_price,
)
from signalforge.config.research import RiskLimits
from signalforge.data.calendar import sessions
from signalforge.data.series import PriceSeries
from signalforge.domain import Direction
from signalforge.paper.ledger import (
    HARD_MAX_GROSS_PCT,
    HARD_MAX_OPEN_RISK_PCT,
    HARD_MAX_PER_TRADE_RISK_PCT,
    HARD_MAX_SECTOR_PCT,
    HARD_MAX_SYMBOL_PCT,
)
from signalforge.research.features.daily import rolling_return, volume_ratio
from signalforge.research.regime import regime_lookup
from signalforge.research.strategies import signal_fn_for
from signalforge.risk.engine import (
    OpenExposure,
    SizingRequest,
    SizingResult,
    _shares_within,
    size_position,
)

# ----------------------------------------------------------------------------- fixed scope
SCRATCH = Path(
    "/private/tmp/claude-501/-Users-louisbrailey-Projects-signal-forge/"
    "ec635db8-8e7c-46dd-bc95-83c88a678e74/scratchpad"
)


def default_db() -> Path:
    """The scratch copy: ``$SIGNALFORGE_DATA_DIR/signalforge.sqlite`` (set by the verified
    environment), else this round's scratch location."""
    data_dir = os.environ.get("SIGNALFORGE_DATA_DIR")
    return (Path(data_dir) if data_dir else SCRATCH / "r3/db") / "signalforge.sqlite"


def default_out() -> Path:
    """Raw outputs live beside the scratch database folder: ``<scratch>/r3/out/capacity``."""
    return default_db().parent.parent / "out" / "capacity"


FORBIDDEN = (
    "/Users/louisbrailey/Projects/signal-forge/data",
    "/Users/louisbrailey/Projects/signal-forge-releases",
)

FULL_START = date(2016, 10, 17)
IS_END = date(2022, 2, 10)
OOS_START = date(2022, 2, 11)
DEV_END = date(2025, 9, 5)  # last development session; no bar or ex-date after it is loaded
NEVER_ON_OR_AFTER = date(2025, 9, 7)
PERIODS = {"IS": (FULL_START, IS_END), "OOS": (OOS_START, DEV_END)}

# Priority order from the task; (strategy key, approved snapshot, strategy_version id).
BOOKS: tuple[tuple[str, int, int], ...] = (
    ("trend_continuation.medium_swing", 11, 3),
    ("high52_breakout.medium_swing", 11, 13),
    ("trend_continuation.short_swing", 3, 2),
    ("relative_strength.medium_swing", 3, 5),
)
INITIAL_CASH = Decimal("30000")
WARMUP = 50  # run_funded_replay default, as funded_replay_report uses it
MAX_VOLUME_PARTICIPATION = 0.01  # run_funded_replay default
SYMBOL_CAP_PCT = 10.0
SECTOR_CAP_PCT = 20.0
PER_TRADE_RISK_PCT = 0.5
MAXIMA_OPEN_RISK_PCT = 3.0
MAXIMA_GROSS_PCT = 100.0
SEED0 = 20261110
N_SEEDS = 40
KEYS = ("K1", "K2", "K3")
KEY_LABELS = {
    "K1": "relative strength (63-session return minus SPY)",
    "K2": "volume surge (signal-day volume / 20-session mean)",
    "K3": "stop distance ((close - stop) / close)",
}
SIGN_TEST_WINS = 26
DD_TOLERANCE_PTS = 2.0
KEY_PERCENTILE = 90.0
BASE = "base"
STRESS = "higher_cost_stress"
CENT = Decimal("0.01")


@dataclass(frozen=True)
class Caps:
    name: str
    open_risk_pct: float
    gross_pct: float
    daily_cap: int | None


def make_limits(caps: Caps) -> RiskLimits:
    """Exactly the limits ``funded_replay_report.replay`` builds, after the library's ceilings."""
    limits = RiskLimits(
        max_position_concentration_pct=SYMBOL_CAP_PCT,
        max_correlated_exposure_pct=SECTOR_CAP_PCT,
        max_daily_portfolio_risk_pct=caps.open_risk_pct,
        max_portfolio_exposure_pct=caps.gross_pct,
    )
    assert limits.per_trade_risk_pct == PER_TRADE_RISK_PCT == HARD_MAX_PER_TRADE_RISK_PCT
    assert SYMBOL_CAP_PCT <= HARD_MAX_SYMBOL_PCT and SECTOR_CAP_PCT <= HARD_MAX_SECTOR_PCT
    assert caps.open_risk_pct <= HARD_MAX_OPEN_RISK_PCT and caps.gross_pct <= HARD_MAX_GROSS_PCT
    return limits


# ----------------------------------------------------------------------------- data
@dataclass
class Book:
    strategy: str
    snapshot_id: int
    version_id: int
    dates: tuple[date, ...]
    data: dict[str, PriceSeries]  # complete symbols plus SPY, full development window
    selected: list[str]  # sorted tradable symbols
    sectors: dict[str, str]
    dividends: dict[str, list[Dividend]]
    skipped: dict[str, str]
    n_is: int
    day_signals: list[list[tuple[str, AttributedEntrySignal]]] = field(default_factory=list)
    keys: dict[tuple[int, str], tuple[float, float, float]] = field(default_factory=dict)
    # per-process caches (not pickled)
    _arrays: dict[str, Any] = field(default_factory=dict, repr=False)

    def __getstate__(self) -> dict[str, Any]:
        state = dict(self.__dict__)
        state["_arrays"] = {}
        return state


def _guard_paths(*paths: Path) -> None:
    for p in paths:
        text = str(p.resolve())
        if any(text.startswith(f) for f in FORBIDDEN):
            raise SystemExit(f"refusing to touch operating path {text}")


def load_book(db: Path, strategy: str, snapshot_id: int, version_id: int) -> Book:
    """Bars, sectors and dividends exactly as ``funded_replay_report.replay`` loads them
    (source 'massive' only, quality-gated, complete sessions or skipped)."""
    _guard_paths(db)
    dates = tuple(sessions(FULL_START, DEV_END))
    assert dates[0] == FULL_START and dates[-1] == DEV_END and dates[-1] < NEVER_ON_OR_AFTER
    data: dict[str, PriceSeries] = {}
    sectors: dict[str, str] = {}
    skipped: dict[str, str] = {}
    dividends: dict[str, list[Dividend]] = {}
    with sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True) as c:
        c.execute("PRAGMA query_only=ON")
        c.execute("BEGIN")
        if c.execute(
            "SELECT 1 FROM sqlite_master WHERE name LIKE 'comparison_%' LIMIT 1"
        ).fetchone():
            raise ValueError("Frozen comparison databases excluded")
        universe = frr.snapshot_symbols(c, snapshot_id)
        for symbol in sorted(set(universe) | {"SPY"}):
            try:
                rows = frr._load(c, symbol, FULL_START, DEV_END, dates)
            except frr.IncompleteSeries as exc:
                if symbol == "SPY":
                    raise
                skipped[symbol] = str(exc)
                continue
            data[symbol] = PriceSeries.from_bars(
                symbol, [(date.fromisoformat(r[0]), *r[1:6]) for r in rows]
            )
            row = c.execute("SELECT sector FROM instrument WHERE symbol=?", (symbol,)).fetchone()
            sectors[symbol] = row[0] or "unknown"
            # The library loader reads the symbol's split_event rows with no date bound and
            # divides each dividend by the ratio of every later split, because the stored
            # bars are on the current share basis. Split rows dated after DEV_END are
            # therefore read for the symbols that have them (5 symbols, 176 dividend rows).
            # No price is involved. See point 19 under "Deviations and clarifications" in the
            # results file and check 4 of capacity_admission_verify.py.
            dividends[symbol] = frr._dividends(c, symbol, data[symbol], FULL_START, DEV_END)
    for bars in data.values():
        assert bars.dates == dates and max(bars.dates) < NEVER_ON_OR_AFTER
    selected = [s for s in sorted(universe) if s not in skipped]
    return Book(
        strategy=strategy,
        snapshot_id=snapshot_id,
        version_id=version_id,
        dates=dates,
        data=data,
        selected=selected,
        sectors=sectors,
        dividends=dividends,
        skipped=skipped,
        n_is=bisect_right(dates, IS_END),
    )


def fresh_signal_fns(strategy: str, spy: PriceSeries, symbols: list[str]) -> dict[str, Any]:
    """Signal functions built exactly as ``funded_replay_report.replay`` builds them."""
    (strat,) = frr.resolve_strategies(strategy)
    regimes = regime_lookup(spy)
    return {
        s: composite_signal_fn([(strat.key, signal_fn_for(strat, regime_by_date=regimes))])
        for s in symbols
    }


def ranking_keys(
    bars: PriceSeries, spy: PriceSeries, t: int, stop_price: float
) -> tuple[float, float, float]:
    """K1, K2, K3 at signal day ``t`` from library feature functions.

    Callers pass ``head(t)`` prefixes, so nothing after the signal day exists in the
    arrays handed to this function."""
    k1 = rolling_return(bars, t, 63) - rolling_return(spy, t, 63)
    k2 = volume_ratio(bars, t, 20)
    close = float(bars.close[t])
    k3 = (close - stop_price) / close
    return (k1, k2, k3)


def build_signal_table(book: Book) -> dict[str, Any]:
    """Every (session, symbol) long signal over the development window, and its keys.

    A signal function is a pure function of the bars up to ``t`` and the SPY regime at
    ``t``; the library evaluates it only for symbols not held, so a table of all
    values reproduces any admission path. The identity check verifies this against
    fresh library runs."""
    n = len(book.dates)
    spy = book.data["SPY"]
    fns = fresh_signal_fns(book.strategy, spy, book.selected)
    day_signals: list[list[tuple[str, AttributedEntrySignal]]] = [[] for _ in range(n)]
    keys: dict[tuple[int, str], tuple[float, float, float]] = {}
    for symbol in book.selected:
        bars = book.data[symbol]
        fn = fns[symbol]
        for t in range(WARMUP, n - 1):
            visible = bars.head(t)
            sig = fn(visible, t)
            if sig is None:
                continue
            assert sig.direction is Direction.LONG and isinstance(sig, AttributedEntrySignal)
            spy_visible = spy.head(t)
            # No lookahead: both prefixes end on the signal day.
            assert visible.dates[-1] == book.dates[t] == spy_visible.dates[-1]
            assert len(visible) == t + 1 == len(spy_visible)
            day_signals[t].append((symbol, sig))
            keys[(t, symbol)] = ranking_keys(visible, spy_visible, t, sig.stop_price)
    for lst in day_signals:
        assert [s for s, _ in lst] == sorted(s for s, _ in lst)
    book.day_signals = day_signals
    book.keys = keys

    # Poison test: recompute a sample of keys on arrays whose bars after the signal day
    # are NaN. Identical values prove the key functions never read past the signal day.
    rng = np.random.default_rng(SEED0)
    items = sorted(keys)
    sample = [items[i] for i in rng.choice(len(items), size=min(400, len(items)), replace=False)]

    def poisoned(b: PriceSeries, t: int) -> PriceSeries:
        arrays = [a.copy() for a in (b.open, b.high, b.low, b.close, b.volume)]
        for a in arrays:
            a[t + 1 :] = np.nan
        return PriceSeries(b.symbol, b.dates, *arrays)

    for t, symbol in sample:
        sig = dict(day_signals[t])[symbol]
        again = ranking_keys(poisoned(book.data[symbol], t), poisoned(spy, t), t, sig.stop_price)
        stored = keys[(t, symbol)]
        assert all(
            (a == b) or (math.isnan(a) and math.isnan(b))
            for a, b in zip(again, stored, strict=True)
        ), (t, symbol, again, stored)
    missing = [sum(1 for v in keys.values() if not math.isfinite(v[k])) for k in range(3)]
    return {
        "signal_days_total": len(keys),
        "keys_missing": dict(zip(KEYS, missing, strict=True)),
        "lookahead_poison_sample": len(sample),
        "lookahead_poison_test": "passed",
    }


def period_inputs(book: Book, period: str) -> dict[str, Any]:
    """Series, dividends and the first session index of a period.

    IS loads only bars to 2022-02-10. OOS keeps the earlier bars as signal history and
    uses the library's ``entry_start`` so the account is all cash until 2022-02-11."""
    if period == "IS":
        last = book.n_is - 1
        return {
            "series": {s: book.data[s].head(last) for s in book.selected},
            "spy": book.data["SPY"].head(last),
            "dividends": tuple(
                d for s in book.selected for d in book.dividends[s] if d.ex_date <= IS_END
            ),
            "spy_dividends": [d for d in book.dividends["SPY"] if d.ex_date <= IS_END],
            "entry_start": None,
            "first": 0,
        }
    if period == "OOS":
        return {
            "series": {s: book.data[s] for s in book.selected},
            "spy": book.data["SPY"],
            "dividends": tuple(d for s in book.selected for d in book.dividends[s]),
            "spy_dividends": list(book.dividends["SPY"]),
            "entry_start": OOS_START,
            "first": book.n_is,
        }
    raise ValueError(period)


# ----------------------------------------------------------------------------- trim sizing
def _largest_fit(upper: int, used: float, unit: float, cap: float) -> int:
    """Largest whole ``n <= upper`` for which the library's own test
    ``used + n * unit > cap`` is false; 0 when not even one share fits."""
    room = cap - used
    if room <= 0 or unit <= 0:
        return 0
    n = min(upper, math.floor(room / unit))
    while n > 0 and used + n * unit > cap:
        n -= 1
    while n < upper and used + (n + 1) * unit <= cap:
        n += 1
    return max(n, 0)


def size_position_trim(
    request: SizingRequest, limits: RiskLimits, exposure: OpenExposure
) -> SizingResult:
    """``risk.engine.size_position`` with the gross, sector and open-risk rejections
    replaced by a trim to the largest whole-share size that fits (minimum one share).

    Per-trade risk sizing and the symbol (concentration) cap are the library's own
    lines, unchanged. A budget that cannot fit one share still rejects, with the
    library's reason text."""
    exp = exposure
    checks: dict[str, str] = {}
    equity = request.account_equity
    if equity <= 0:
        return SizingResult.reject("account_equity must be positive", checks)
    per_share_risk = abs(request.entry_price - request.stop_price)
    if per_share_risk <= 0:
        return SizingResult.reject("entry and stop are equal", checks)
    risk_budget = equity * (limits.per_trade_risk_pct / 100.0)
    shares = _shares_within(risk_budget, per_share_risk)
    if shares < 1:
        return SizingResult.reject("per-trade risk budget too small for one share", checks)
    notional = shares * request.entry_price
    conc_cap = equity * (limits.max_position_concentration_pct / 100.0)
    if notional > conc_cap:
        shares = _shares_within(conc_cap, request.entry_price)
        if shares < 1:
            return SizingResult.reject("position concentration cap below one share", checks)
        notional = shares * request.entry_price
        checks["concentration"] = f"trimmed to {limits.max_position_concentration_pct}% of equity"
    else:
        checks["concentration"] = "ok"
    trimmed: list[str] = []

    expo_cap = equity * (limits.max_portfolio_exposure_pct / 100.0)
    if exp.gross_dollars + notional > expo_cap:
        shares = _largest_fit(shares, exp.gross_dollars, request.entry_price, expo_cap)
        if shares < 1:
            return SizingResult.reject(
                f"max portfolio exposure {limits.max_portfolio_exposure_pct}% would be exceeded",
                checks,
            )
        notional = shares * request.entry_price
        trimmed.append("gross")
    checks["portfolio_exposure"] = "ok"

    corr_cap = equity * (limits.max_correlated_exposure_pct / 100.0)
    sector_now = exp.by_sector_dollars.get(request.sector, 0.0)
    if sector_now + notional > corr_cap:
        shares = _largest_fit(shares, sector_now, request.entry_price, corr_cap)
        if shares < 1:
            return SizingResult.reject(
                f"max correlated exposure {limits.max_correlated_exposure_pct}% for sector "
                f"{request.sector!r} would be exceeded",
                checks,
            )
        notional = shares * request.entry_price
        trimmed.append("sector")
    checks["correlated_exposure"] = "ok"

    daily_cap = equity * (limits.max_daily_portfolio_risk_pct / 100.0)
    risk_dollars = shares * per_share_risk
    if exp.open_risk_dollars + risk_dollars > daily_cap:
        shares = _largest_fit(shares, exp.open_risk_dollars, per_share_risk, daily_cap)
        if shares < 1:
            return SizingResult.reject(
                f"max daily portfolio risk {limits.max_daily_portfolio_risk_pct}% would be exceeded",
                checks,
            )
        notional = shares * request.entry_price
        risk_dollars = shares * per_share_risk
        trimmed.append("open_risk")
    checks["daily_risk"] = "ok"

    # The trimmed size passes every test the library applies.
    assert shares >= 1
    assert not exp.gross_dollars + notional > expo_cap
    assert not sector_now + notional > corr_cap
    assert not exp.open_risk_dollars + risk_dollars > daily_cap
    assert not notional > conc_cap and not risk_dollars > risk_budget
    if trimmed:
        checks["trimmed_to_budget"] = ",".join(trimmed)
    return SizingResult(
        shares=shares,
        notional=round(notional, 2),
        risk_dollars=round(risk_dollars, 2),
        risk_pct_of_account=round(risk_dollars / equity * 100.0, 4),
        checks=checks,
    )


# ----------------------------------------------------------------------------- admission order
def seed_for(i: int) -> int:
    return SEED0 + i


def make_order(book: Book, order: tuple[str, Any]) -> Any:
    """Return ``f(i, pending) -> [(symbol, signal), ...]`` for fill-day index ``i``.

    alpha   the library's order (by symbol).
    random  each (session, symbol) has one uniform priority drawn from
            ``numpy.random.default_rng(seed)`` on the full calendar x sorted symbols
            grid; lowest first. The grid does not depend on the trim mode, cap set or
            period, so reject and trim runs of one seed see the same order.
    key     K1/K2/K3 of the signal day (i - 1), highest first; ties and missing keys
            fall back to symbol order (missing last).
    """
    kind = order[0]
    if kind == "alpha":
        return lambda i, pending: sorted(pending.items(), key=lambda kv: kv[0])
    if kind == "random":
        prio = np.random.default_rng(int(order[1])).random((len(book.dates), len(book.selected)))
        index = {s: j for j, s in enumerate(book.selected)}

        def by_priority(i: int, pending: dict[str, Any]) -> list[tuple[str, Any]]:
            row = prio[i]
            return sorted(pending.items(), key=lambda kv: (row[index[kv[0]]], kv[0]))

        return by_priority
    if kind == "key":
        k = KEYS.index(order[1])
        keys = book.keys

        def by_key(i: int, pending: dict[str, Any]) -> list[tuple[str, Any]]:
            def sort_key(kv: tuple[str, Any]) -> tuple[int, float, str]:
                value = keys[(i - 1, kv[0])][k]  # signal day = i - 1, never later
                if math.isfinite(value):
                    return (0, -value, kv[0])
                return (1, 0.0, kv[0])

            return sorted(pending.items(), key=sort_key)

        return by_key
    raise ValueError(order)


# ----------------------------------------------------------------------------- local replay
def _arrays(book: Book, period: str) -> dict[str, Any]:
    cached = book._arrays.get(period)
    if cached is None:
        inputs = period_inputs(book, period)
        series = inputs["series"]
        div_by_day: dict[date, list[Dividend]] = defaultdict(list)
        for d in inputs["dividends"]:
            div_by_day[d.ex_date].append(d)
        cached = {
            **inputs,
            "dates": series[book.selected[0]].dates,
            "open": {s: b.open.tolist() for s, b in series.items()},
            "high": {s: b.high.tolist() for s, b in series.items()},
            "low": {s: b.low.tolist() for s, b in series.items()},
            "close": {s: b.close.tolist() for s, b in series.items()},
            "volume": {s: b.volume.tolist() for s, b in series.items()},
            "div_by_day": dict(div_by_day),
        }
        book._arrays[period] = cached
    return cached


def local_replay(
    book: Book,
    period: str,
    caps: Caps,
    cost_model: CostModel,
    spread_bps: float,
    *,
    order: tuple[str, Any],
    trim: bool,
) -> tuple[FundedReplay, dict[str, int]]:
    """Script-local copy of the ``run_funded_replay`` day loop.

    Same arithmetic, in the same order, for everything the report path uses (no
    splits, ticker changes, eligibility filter, staggered start or drawdown halt:
    ``funded_replay_report.replay`` passes none of them). Differences are only the
    three plug points: ``order``, ``trim`` and ``caps.daily_cap``."""
    arr = _arrays(book, period)
    dates: tuple[date, ...] = arr["dates"]
    opens, highs, lows, closes, vols = (
        arr["open"],
        arr["high"],
        arr["low"],
        arr["close"],
        arr["volume"],
    )
    div_by_day: dict[date, list[Dividend]] = arr["div_by_day"]
    entry_start: date | None = arr["entry_start"]
    sectors = book.sectors
    day_signals = book.day_signals
    cm = cost_model
    limits = make_limits(caps)
    daily_cap = caps.daily_cap
    order_fn = make_order(book, order)
    n = len(dates)
    day_str = [str(d) for d in dates]

    cash = money(INITIAL_CASH)
    receivables: list[tuple[date, Decimal, str]] = []
    positions: dict[str, Position] = {}
    aux: dict[str, tuple[float, float, float]] = {}  # entry, stop fill, entry fee as floats
    pending: dict[str, AttributedEntrySignal] = {}
    result = FundedReplay()
    fills = result.fills
    decisions = result.decisions
    events = result.corporate_events
    marks_out = result.marks
    penalty = (cm.slippage_bps + (spread_bps / 2 if cm.half_spread_fill_penalty else 0)) / 10000
    stats: Counter[str] = Counter()
    min_rr = limits.min_reward_to_risk
    per_trade_pct = limits.per_trade_risk_pct
    open_risk_pct = limits.max_daily_portfolio_risk_pct

    def sell(symbol: str, i: int, raw: float, reason: str) -> None:
        nonlocal cash
        p = positions.pop(symbol)
        del aux[symbol]
        fill = Decimal(str(raw * (1 - penalty))).quantize(CENT, rounding=ROUND_FLOOR)
        fee = money(cm.commission(p.shares))
        cash += fill * p.shares - fee
        cost = money(abs(raw - float(fill)) * p.shares) + fee
        result.costs += cost
        fills.append(
            {
                "day": day_str[i],
                "symbol": symbol,
                "ticker": symbol,
                "side": "sell",
                "shares": p.shares,
                "price": str(fill),
                "commission": str(fee),
                "modeled_cost_usd": str(cost),
                "reason": reason,
                "realized_pnl_usd": str(fill * p.shares - p.cost_basis - fee - p.entry_fee),
                "strategy": p.signal.strategy,
            }
        )

    for i, day in enumerate(dates):
        # Entitlement belongs to holders entering the ex-date, even if sold at its open.
        for dividend in div_by_day.get(day, ()):
            if dividend.symbol in positions:
                amount = money(dividend.amount * positions[dividend.symbol].shares)
                receivables.append((dividend.pay_date, amount, dividend.symbol))
                events.append(
                    {
                        "day": day_str[i],
                        "symbol": dividend.symbol,
                        "kind": "dividend_entitlement",
                        "amount_usd": str(amount),
                        "pay_date": str(dividend.pay_date),
                        "source": dividend.source,
                    }
                )
        if receivables:
            for pay_date, amount, symbol in receivables:
                if pay_date <= day:
                    cash += amount
                    events.append(
                        {
                            "day": day_str[i],
                            "symbol": symbol,
                            "kind": "dividend_payment",
                            "amount_usd": str(amount),
                            "pay_date": str(pay_date),
                        }
                    )
            receivables = [r for r in receivables if r[0] > day]
        due = sum((r[1] for r in receivables), Decimal(0))
        # Only known opening gaps may free cash before other opening entries.
        for symbol in list(positions):
            o = opens[symbol][i]
            if o <= positions[symbol].signal.stop_price:
                sell(symbol, i, o, "gap_stop")
        if pending:
            accepted_today = 0
            for symbol, sig in order_fn(i, pending):
                if symbol in positions:
                    continue
                if entry_start is not None and day < entry_start:
                    continue
                stats["offered"] += 1
                raw = opens[symbol][i]
                fill = Decimal(str(raw * (1 + penalty))).quantize(CENT, rounding=ROUND_CEILING)
                fill_f = float(fill)
                reason: str | None = None
                if (
                    not math.isfinite(sig.stop_price)
                    or sig.stop_price <= 0
                    or sig.stop_price >= fill_f
                ):
                    reason = "invalid_or_crossed_stop"
                elif sig.target_price is not None and (
                    not math.isfinite(sig.target_price)
                    or (sig.target_price - fill_f) / (fill_f - sig.stop_price) < min_rr
                ):
                    reason = "reward_risk"
                if reason:
                    decisions.append(
                        {
                            "day": day_str[i],
                            "symbol": symbol,
                            "status": "rejected",
                            "reason": reason,
                            "shares": 0,
                            "strategy": sig.strategy,
                        }
                    )
                    continue
                marks = {s: opens[s][i] for s in positions}
                gross = sum(positions[s].shares * marks[s] for s in positions)
                equity = float(cash + due) + gross
                sector_totals: dict[str, float] = {}
                risk = 0.0
                for s, p in positions.items():
                    entry_f, stop_fill_f, entry_fee_f = aux[s]
                    sector_totals[sectors[s]] = (
                        sector_totals.get(sectors[s], 0) + p.shares * marks[s]
                    )
                    risk += (
                        p.shares * max(0.0, max(entry_f, marks[s]) - stop_fill_f)
                        + entry_fee_f
                        + cm.commission(p.shares)
                    )
                request = SizingRequest(symbol, sectors[symbol], fill_f, sig.stop_price, equity)
                exposure = OpenExposure(gross, risk, sector_totals, len(positions))
                if trim:
                    sized = size_position_trim(request, limits, exposure)
                    reference = size_position(request, limits, exposure)
                    if not reference.rejected:
                        # Nothing binds: trim mode must size exactly as the library does.
                        assert not sized.rejected and sized.shares == reference.shares
                        assert "trimmed_to_budget" not in sized.checks
                else:
                    sized = size_position(request, limits, exposure)
                shares = min(
                    sized.shares,
                    math.floor(vols[symbol][i - 1] * 1.0 * MAX_VOLUME_PARTICIPATION),
                )
                if sized.rejected:
                    reason = reason or sized.rejected_reason
                # Includes commissions in both affordability and total open risk.
                stop_fill_new = float(sell_price(sig.stop_price, penalty))
                bound = min(
                    equity * per_trade_pct / 100,
                    equity * open_risk_pct / 100 - risk,
                )
                while shares > 0 and (
                    fill * shares + money(cm.commission(shares)) > cash
                    or (fill_f - stop_fill_new) * shares + 2 * cm.commission(shares) > bound
                ):
                    shares -= 1
                if shares < 1:
                    reason = reason or "cash_or_open_risk"
                if reason is None and daily_cap is not None and accepted_today >= daily_cap:
                    reason = "daily_cap"
                decisions.append(
                    {
                        "day": day_str[i],
                        "symbol": symbol,
                        "status": "rejected" if reason else "accepted",
                        "reason": reason,
                        "shares": 0 if reason else shares,
                        "signal_day": day_str[i - 1],
                        "entry_admission": {},
                        "strategy": sig.strategy,
                    }
                )
                if reason:
                    continue
                accepted_today += 1
                if "trimmed_to_budget" in sized.checks:
                    stats["trim_admitted"] += 1
                fee = money(cm.commission(shares))
                cash -= fill * shares + fee
                cost = money(abs(fill_f - raw) * shares) + fee
                result.costs += cost
                positions[symbol] = Position(shares, fill, sig, i, fee, fill * shares)
                aux[symbol] = (fill_f, stop_fill_new, float(fee))
                fills.append(
                    {
                        "day": day_str[i],
                        "symbol": symbol,
                        "ticker": symbol,
                        "signal_day": day_str[i - 1],
                        "side": "buy",
                        "shares": shares,
                        "price": str(fill),
                        "commission": str(fee),
                        "modeled_cost_usd": str(cost),
                        "strategy": sig.strategy,
                        "signal_reason": sig.reason,
                    }
                )
        pending = {}
        # Stop before target; end-of-window liquidation includes costs.
        for symbol in list(positions):
            p = positions[symbol]
            sig = p.signal
            raw_exit: float | None = None
            why = ""
            if lows[symbol][i] <= sig.stop_price:
                raw_exit, why = sig.stop_price, "stop"
            elif sig.target_price is not None and highs[symbol][i] >= sig.target_price:
                raw_exit, why = sig.target_price, "target"
            elif i - p.entry_index >= sig.time_stop_bars:
                raw_exit, why = closes[symbol][i], "time_stop"
            elif i == n - 1:
                raw_exit, why = closes[symbol][i], "end_of_data"
            if raw_exit is not None:
                sell(symbol, i, raw_exit, why)
        liquidation = cash + due
        gross_close = Decimal(0)
        for symbol, p in positions.items():
            raw = closes[symbol][i]
            gross_close += money(raw) * p.shares
            liquidation += sell_price(raw, penalty) * p.shares - money(cm.commission(p.shares))
        marks_out.append(
            {
                "day": day_str[i],
                "cash_usd": str(cash),
                "gross_exposure_usd": str(gross_close),
                "net_liquidation_usd": str(liquidation),
                "open_positions": len(positions),
                "dividend_receivable_usd": str(due),
                "drawdown_halted": False,
            }
        )
        if WARMUP <= i < n - 1:
            pending = {s: sig for s, sig in day_signals[i] if s not in positions}
    assert not positions and not pending
    return result, dict(stats)


# ----------------------------------------------------------------------------- library reference
class DailyCap:
    """Accepts-per-day cap expressed through the library's ``entry_admission`` hook."""

    def __init__(self, cap: int) -> None:
        self.cap = cap
        self.day: date | None = None
        self.count = 0

    def __call__(self, proposal: EntryProposal) -> EntryVerdict:
        if proposal.day != self.day:
            self.day, self.count = proposal.day, 0
        if self.count >= self.cap:
            return EntryVerdict(False, "daily_cap", {})
        self.count += 1
        return EntryVerdict(True, "", {})


def library_replay(
    book: Book,
    period: str,
    caps: Caps,
    cost_model: CostModel,
    spread_bps: float,
    *,
    table_backed: bool,
) -> FundedReplay:
    """``run_funded_replay`` called as ``funded_replay_report.replay`` calls it.

    ``table_backed=False`` builds fresh signal functions from the period's own SPY
    bars (independent of this script's signal table)."""
    inputs = period_inputs(book, period)
    series = inputs["series"]
    limits = make_limits(caps)
    if table_backed:
        table = {(s, t): sig for t, lst in enumerate(book.day_signals) for s, sig in lst}
        signals = {s: (lambda _series, t, s=s: table.get((s, t))) for s in series}
    else:
        signals = fresh_signal_fns(book.strategy, inputs["spy"], list(series))
    return run_funded_replay(
        series,
        signals,
        book.sectors,
        limits=limits,
        cost_model=cost_model,
        spread_bps=spread_bps,
        initial_cash=INITIAL_CASH,
        dividends=inputs["dividends"],
        max_position_ceiling_pct=SYMBOL_CAP_PCT,
        max_sector_ceiling_pct=SECTOR_CAP_PCT,
        max_gross_ceiling_pct=caps.gross_pct,
        max_open_risk_ceiling_pct=caps.open_risk_pct,
        entry_start=inputs["entry_start"],
        entry_admission=DailyCap(caps.daily_cap) if caps.daily_cap is not None else None,
    )


# ----------------------------------------------------------------------------- metrics
def run_metrics(book: Book, period: str, result: FundedReplay, stats: dict[str, int]) -> dict:
    start, end = PERIODS[period]
    first = 0 if period == "IS" else book.n_is
    marks = result.marks
    assert len(marks) == (book.n_is if period == "IS" else len(book.dates))
    assert marks[first]["day"] == str(start) and marks[-1]["day"] == str(end)
    if first:
        # Fresh cash: nothing may have happened before the period starts.
        assert all(
            Decimal(m["net_liquidation_usd"]) == INITIAL_CASH and m["open_positions"] == 0
            for m in marks[:first]
        )
    assert all(f["day"] >= str(start) for f in result.fills)
    values = [Decimal(m["net_liquidation_usd"]) for m in marks[first:]]
    em = frr.equity_metrics(values, initial_cash=INITIAL_CASH, start=start, end=end)
    exposures = [
        float(Decimal(m["gross_exposure_usd"]) / Decimal(m["net_liquidation_usd"]))
        for m in marks[first:]
        if Decimal(m["net_liquidation_usd"]) > 0
    ]
    entries = sum(1 for f in result.fills if f["side"] == "buy")
    last_signal_day = (book.n_is if period == "IS" else len(book.dates)) - 2
    first_signal_day = WARMUP if period == "IS" else book.n_is - 1
    signals_total = sum(
        len(book.day_signals[t]) for t in range(first_signal_day, last_signal_day + 1)
    )
    rejections = Counter(d["reason"] for d in result.decisions if d["status"] == "rejected")
    dividend_income = sum(
        (
            Decimal(e["amount_usd"])
            for e in result.corporate_events
            if e["kind"] == "dividend_entitlement"
        ),
        Decimal(0),
    )
    return {
        "net_return_pct": em["net_return_pct"],
        "cagr_pct": em["cagr_pct"],
        "max_drawdown_pct": em["max_drawdown_pct"],
        "sharpe": em["sharpe_annualised"],
        "mean_exposure_pct": sum(exposures) / len(exposures) * 100,
        "entries": entries,
        "signals_total": signals_total,
        "signals_offered": stats.get("offered", 0),
        "entries_per_signal": entries / signals_total if signals_total else None,
        "trim_admitted": stats.get("trim_admitted", 0),
        "final_equity_usd": str(values[-1]),
        "costs_usd": str(result.costs),
        "dividend_income_usd": str(dividend_income),
        "rejections": json.dumps(dict(sorted(rejections.items())), sort_keys=True),
    }


def spy_reference(book: Book, period: str, cost_label: str) -> dict[str, Any]:
    start, end = PERIODS[period]
    inputs = period_inputs(book, period)
    cm, spread = frr.COST_CASES[cost_label]
    bench = frr.spy_benchmark(
        inputs["spy"],
        dividends=inputs["spy_dividends"],
        initial_cash=INITIAL_CASH,
        cost_model=cm,
        spread_bps=spread,
        start=start,
        end=end,
        from_index=inputs["first"],
    )
    assert bench["start"] == str(start)
    return {
        "net_return_pct": bench["net_return_pct"],
        "cagr_pct": bench["cagr_pct"],
        "max_drawdown_pct": bench["max_drawdown_pct"],
        "sharpe": bench["sharpe_annualised"],
    }


# ----------------------------------------------------------------------------- workers
_STATE: dict[str, Any] = {}


def _init(out: str, caps_json: str) -> None:
    for var in (
        "OMP_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "MKL_NUM_THREADS",
        "VECLIB_MAXIMUM_THREADS",
    ):
        os.environ[var] = "1"
    _STATE["out"] = Path(out)
    _STATE["caps"] = {c["name"]: Caps(**c) for c in json.loads(caps_json)}
    _STATE["books"] = {}


def _book(strategy: str) -> Book:
    books = _STATE["books"]
    if strategy not in books:
        # Trusted input: this cache is written by ``prepare_book`` of this same script
        # into the private scratch output directory, never fetched from elsewhere.
        with (_STATE["out"] / "cache" / f"{strategy}.pkl").open("rb") as fh:
            books[strategy] = pickle.load(fh)  # noqa: S301 - this script's own cache
    return books[strategy]


def read_operating_caps(db: Path) -> list[Caps]:
    """Operating open-risk and gross limits and the daily cap, read from the scratch copy."""
    from signalforge.db.session import session_scope
    from signalforge.paper.auto_simulate import max_per_day
    from signalforge.settings_store import effective_research_config

    url = os.environ.get("DATABASE_URL", "")
    if "mode=ro" not in url or str(db) not in url:
        raise SystemExit("DATABASE_URL must point read-only at the scratch copy")
    with session_scope() as s:
        risk = effective_research_config(s).risk
        cap = max_per_day(s)
    operating = Caps(
        "operating",
        min(HARD_MAX_OPEN_RISK_PCT, risk.max_daily_portfolio_risk_pct),
        min(HARD_MAX_GROSS_PCT, risk.max_portfolio_exposure_pct),
        cap,
    )
    maxima = Caps("maxima", MAXIMA_OPEN_RISK_PCT, MAXIMA_GROSS_PCT, None)
    return [operating, maxima]


def _compare(ref: FundedReplay, loc: FundedReplay) -> dict[str, Any]:
    final_ref = Decimal(ref.marks[-1]["net_liquidation_usd"])
    final_loc = Decimal(loc.marks[-1]["net_liquidation_usd"])
    out = {
        "library_fills": len(ref.fills),
        "local_fills": len(loc.fills),
        "library_final_equity_usd": str(final_ref),
        "local_final_equity_usd": str(final_loc),
        "fills_identical": ref.fills == loc.fills,
        "final_equity_identical": final_ref == final_loc,
        "marks_identical": ref.marks == loc.marks,
        "decisions_identical": ref.decisions == loc.decisions,
        "costs_identical": ref.costs == loc.costs,
        "dividend_events_identical": ref.corporate_events == loc.corporate_events,
    }
    out["passed"] = all(v for k, v in out.items() if k.endswith("_identical"))
    return out


def prepare_book(args: tuple[str, int, int, str]) -> dict[str, Any]:
    """Build one book's cache and run its identity checks."""
    strategy, snapshot_id, version_id, db = args
    started = time.perf_counter()
    out: Path = _STATE["out"]
    caps: dict[str, Caps] = _STATE["caps"]
    book = load_book(Path(db), strategy, snapshot_id, version_id)
    table_info = build_signal_table(book)
    cache = out / "cache"
    cache.mkdir(parents=True, exist_ok=True)
    with (cache / f"{strategy}.pkl").open("wb") as fh:
        pickle.dump(book, fh, protocol=pickle.HIGHEST_PROTOCOL)
    report: dict[str, Any] = {
        "strategy": strategy,
        "snapshot_id": snapshot_id,
        "strategy_version_id": version_id,
        "symbols_replayed": len(book.selected),
        "skipped_symbols": sorted(book.skipped),
        "sessions": {"full": len(book.dates), "IS": book.n_is, "OOS": len(book.dates) - book.n_is},
        "symbols_with_dividend_rows": sum(bool(book.dividends[s]) for s in book.selected),
        "table": table_info,
        "table_seconds": round(time.perf_counter() - started, 1),
        "cells": [],
        "stress_cells": [],
    }
    base_cm, base_spread = frr.COST_CASES[BASE]
    stress_cm, stress_spread = frr.COST_CASES[STRESS]
    for cap_name in ("operating", "maxima"):
        for period in ("IS", "OOS"):
            t0 = time.perf_counter()
            ref = library_replay(
                book, period, caps[cap_name], base_cm, base_spread, table_backed=False
            )
            t1 = time.perf_counter()
            loc, _stats = local_replay(
                book, period, caps[cap_name], base_cm, base_spread, order=("alpha",), trim=False
            )
            t2 = time.perf_counter()
            cell = {"cap_set": cap_name, "period": period, "cost_case": BASE, **_compare(ref, loc)}
            cell["library_seconds"] = round(t1 - t0, 2)
            cell["local_seconds"] = round(t2 - t1, 2)
            report["cells"].append(cell)
            # Additional check (not pre-registered): commission arithmetic under stress costs.
            ref_s = library_replay(
                book, period, caps[cap_name], stress_cm, stress_spread, table_backed=True
            )
            loc_s, _ = local_replay(
                book,
                period,
                caps[cap_name],
                stress_cm,
                stress_spread,
                order=("alpha",),
                trim=False,
            )
            report["stress_cells"].append(
                {
                    "cap_set": cap_name,
                    "period": period,
                    "cost_case": STRESS,
                    **_compare(ref_s, loc_s),
                }
            )
    # Cross-check of the harness inputs and metrics against the canonical report script
    # (possible only where it needs no entry_start or daily cap: IS, maxima, base costs).
    t0 = time.perf_counter()
    canonical = frr.replay(
        Path(db),
        None,
        FULL_START,
        IS_END,
        strategy=strategy,
        snapshot_id=snapshot_id,
        initial_cash=INITIAL_CASH,
        max_position_pct=SYMBOL_CAP_PCT,
        max_sector_pct=SECTOR_CAP_PCT,
        max_open_risk_pct=MAXIMA_OPEN_RISK_PCT,
        max_gross_pct=MAXIMA_GROSS_PCT,
    )
    loc, stats = local_replay(
        book, "IS", caps["maxima"], base_cm, base_spread, order=("alpha",), trim=False
    )
    mine = run_metrics(book, "IS", loc, stats)
    theirs = canonical["scenario_diagnostics"][BASE]
    spy_mine = spy_reference(book, "IS", BASE)
    report["canonical_report_crosscheck"] = {
        "cell": "IS / maxima / base",
        "fills_identical": canonical["result"]["fills"] == loc.fills,
        "marks_identical": canonical["result"]["marks"] == loc.marks,
        "skipped_identical": sorted(canonical["run_config"]["skipped_symbols"])
        == sorted(book.skipped),
        "metrics_identical": all(
            mine[a] == theirs["risk_adjusted"][b]
            for a, b in (
                ("net_return_pct", "net_return_pct"),
                ("cagr_pct", "cagr_pct"),
                ("max_drawdown_pct", "max_drawdown_pct"),
                ("sharpe", "sharpe_annualised"),
            )
        )
        and mine["mean_exposure_pct"] == theirs["diagnostics"]["average_session_exposure_pct"],
        "spy_identical": spy_mine["net_return_pct"] == theirs["benchmark"]["net_return_pct"]
        and spy_mine["sharpe"] == theirs["benchmark"]["sharpe_annualised"],
        "seconds": round(time.perf_counter() - t0, 1),
    }
    report["canonical_report_crosscheck"]["passed"] = all(
        v for k, v in report["canonical_report_crosscheck"].items() if k.endswith("_identical")
    )
    report["spy"] = {
        cost: {period: spy_reference(book, period, cost) for period in PERIODS}
        for cost in (BASE, STRESS)
    }
    report["passed"] = all(c["passed"] for c in report["cells"])
    report["stress_passed"] = all(c["passed"] for c in report["stress_cells"])
    report["seconds"] = round(time.perf_counter() - started, 1)
    return report


RUN_FIELDS = [
    "book",
    "snapshot_id",
    "cap_set",
    "period",
    "cost_case",
    "arm",
    "order",
    "trim",
    "net_return_pct",
    "cagr_pct",
    "max_drawdown_pct",
    "sharpe",
    "mean_exposure_pct",
    "entries",
    "signals_total",
    "signals_offered",
    "entries_per_signal",
    "trim_admitted",
    "final_equity_usd",
    "costs_usd",
    "dividend_income_usd",
    "rejections",
    "seconds",
]


def run_task(task: tuple[str, str, str, str, str, Any, bool]) -> dict[str, Any]:
    strategy, cap_name, period, cost_label, kind, ident, trim = task
    book = _book(strategy)
    caps = _STATE["caps"][cap_name]
    cm, spread = frr.COST_CASES[cost_label]
    order = ("random", seed_for(ident)) if kind == "random" else (kind, ident)
    t0 = time.perf_counter()
    result, stats = local_replay(book, period, caps, cm, spread, order=order, trim=trim)
    row = run_metrics(book, period, result, stats)
    row.update(
        book=strategy,
        snapshot_id=book.snapshot_id,
        cap_set=cap_name,
        period=period,
        cost_case=cost_label,
        arm=kind,
        order=(f"seed{seed_for(ident)}" if kind == "random" else str(ident)),
        trim=int(trim),
        seconds=round(time.perf_counter() - t0, 2),
    )
    return row


def grid_tasks(cost_label: str, books: list[str], *, keys: bool) -> list[tuple]:
    tasks = []
    for strategy in books:
        for cap_name in ("operating", "maxima"):
            for period in ("IS", "OOS"):
                for i in range(N_SEEDS):
                    for trim in (False, True):
                        tasks.append((strategy, cap_name, period, cost_label, "random", i, trim))
                if keys:
                    for key in KEYS:
                        for trim in (False, True):
                            tasks.append((strategy, cap_name, period, cost_label, "key", key, trim))
    return tasks


def run_pool(tasks: list[tuple], out: Path, caps: list[Caps], csv_path: Path, workers: int) -> int:
    """Run tasks on ``workers`` processes, appending each finished row to ``csv_path``."""
    done: set[tuple] = set()
    if csv_path.exists():
        with csv_path.open() as fh:
            for r in csv.DictReader(fh):
                done.add(
                    (
                        r["book"],
                        r["cap_set"],
                        r["period"],
                        r["cost_case"],
                        r["arm"],
                        r["order"],
                        r["trim"],
                    )
                )

    def ident(task: tuple) -> tuple:
        strategy, cap_name, period, cost_label, kind, i, trim = task
        order = f"seed{seed_for(i)}" if kind == "random" else str(i)
        return (strategy, cap_name, period, cost_label, kind, order, str(int(trim)))

    todo = [t for t in tasks if ident(t) not in done]
    print(f"{len(tasks)} tasks, {len(done)} already saved, {len(todo)} to run", flush=True)
    if not todo:
        return 0
    new_file = not csv_path.exists()
    started = time.perf_counter()
    ctx = mp.get_context("spawn")
    with csv_path.open("a", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=RUN_FIELDS)
        if new_file:
            writer.writeheader()
        with ctx.Pool(
            workers, initializer=_init, initargs=(str(out), json.dumps([asdict(c) for c in caps]))
        ) as pool:
            for k, row in enumerate(pool.imap(run_task, todo, chunksize=4), 1):
                writer.writerow(row)
                if k % 50 == 0 or k == len(todo):
                    fh.flush()
                    print(
                        f"  {k}/{len(todo)} runs, {time.perf_counter() - started:.0f}s, "
                        f"last {row['book']} {row['cap_set']} {row['period']}",
                        flush=True,
                    )
    return len(todo)


# ----------------------------------------------------------------------------- analysis
def _f(x: Any) -> float:
    return float("nan") if x in (None, "", "None") else float(x)


def load_rows(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open() as fh:
        for r in csv.DictReader(fh):
            for k in (
                "net_return_pct",
                "cagr_pct",
                "max_drawdown_pct",
                "sharpe",
                "mean_exposure_pct",
                "entries_per_signal",
            ):
                r[k] = _f(r[k])
            for k in ("entries", "signals_total", "signals_offered", "trim_admitted", "trim"):
                r[k] = int(r[k])
            rows.append(r)
    return rows


def _pct(values: list[float], q: float) -> float:
    return float(np.percentile(np.array(values, dtype=float), q))


def _band(values: list[float]) -> dict[str, float]:
    return {"p5": _pct(values, 5), "p50": _pct(values, 50), "p95": _pct(values, 95)}


def _sign_p(wins: int, n: int) -> float:
    return sum(math.comb(n, k) for k in range(wins, n + 1)) / 2**n


def analyze(
    rows: list[dict[str, Any]], books: list[str], identity: dict[str, Any] | None = None
) -> dict[str, Any]:
    cells: dict[tuple, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        cells[(r["book"], r["cap_set"], r["period"], r["arm"], r["trim"])].append(r)
    # The library's alphabetical order, from the identity runs (net return only).
    alpha: dict[tuple, float] = {}
    for rep in (identity or {}).get("books", []):
        for c in rep["cells"]:
            alpha[(rep["strategy"], c["cap_set"], c["period"])] = float(
                (Decimal(c["library_final_equity_usd"]) / INITIAL_CASH - 1) * 100
            )
    out: dict[str, Any] = {
        "luck_band": [],
        "trim": [],
        "trim_verdicts": [],
        "keys": [],
        "key_verdicts": [],
    }
    for book in books:
        for cap in ("operating", "maxima"):
            trim_period_pass = {}
            for period in ("IS", "OOS"):
                by_mode = {}
                for trim in (0, 1):
                    rs = sorted(
                        cells[(book, cap, period, "random", trim)], key=lambda r: r["order"]
                    )
                    if len(rs) != N_SEEDS:
                        raise SystemExit(
                            f"{book} {cap} {period} trim={trim}: {len(rs)} random runs, need {N_SEEDS}"
                        )
                    by_mode[trim] = rs
                    out["luck_band"].append(
                        {
                            "book": book,
                            "cap_set": cap,
                            "period": period,
                            "trim": trim,
                            "n": len(rs),
                            "net_return_pct": _band([r["net_return_pct"] for r in rs]),
                            "sharpe": _band([r["sharpe"] for r in rs]),
                            "net_return_min_max": [
                                min(r["net_return_pct"] for r in rs),
                                max(r["net_return_pct"] for r in rs),
                            ],
                            "net_return_p95_minus_p5_pts": _pct(
                                [r["net_return_pct"] for r in rs], 95
                            )
                            - _pct([r["net_return_pct"] for r in rs], 5),
                            "alphabetical_net_return_pct": alpha.get((book, cap, period))
                            if trim == 0
                            else None,
                            "alphabetical_percentile_in_random": (
                                100.0
                                * sum(r["net_return_pct"] < alpha[(book, cap, period)] for r in rs)
                                / len(rs)
                                if trim == 0 and (book, cap, period) in alpha
                                else None
                            ),
                            "net_return_p90": _pct(
                                [r["net_return_pct"] for r in rs], KEY_PERCENTILE
                            ),
                            "sharpe_p90": _pct([r["sharpe"] for r in rs], KEY_PERCENTILE),
                            "median_cagr_pct": _pct([r["cagr_pct"] for r in rs], 50),
                            "median_max_drawdown_pct": _pct(
                                [r["max_drawdown_pct"] for r in rs], 50
                            ),
                            "median_mean_exposure_pct": _pct(
                                [r["mean_exposure_pct"] for r in rs], 50
                            ),
                            "median_entries": _pct([r["entries"] for r in rs], 50),
                            "signals_total": rs[0]["signals_total"],
                            "median_entries_per_signal": _pct(
                                [r["entries_per_signal"] for r in rs], 50
                            ),
                            "median_trim_admitted": _pct([r["trim_admitted"] for r in rs], 50),
                        }
                    )
                rej, tr = by_mode[0], by_mode[1]
                assert [r["order"] for r in rej] == [r["order"] for r in tr]
                diffs = [
                    t["net_return_pct"] - r["net_return_pct"] for r, t in zip(rej, tr, strict=True)
                ]
                wins = sum(d > 0 for d in diffs)
                losses = sum(d < 0 for d in diffs)
                dd_rej = _pct([r["max_drawdown_pct"] for r in rej], 50)
                dd_trim = _pct([r["max_drawdown_pct"] for r in tr], 50)
                sign_ok = wins >= SIGN_TEST_WINS
                dd_ok = (dd_trim - dd_rej) <= DD_TOLERANCE_PTS
                trim_period_pass[period] = sign_ok and dd_ok
                out["trim"].append(
                    {
                        "book": book,
                        "cap_set": cap,
                        "period": period,
                        "wins": wins,
                        "losses": losses,
                        "ties": N_SEEDS - wins - losses,
                        "sign_test_p_one_sided": _sign_p(wins, N_SEEDS),
                        "median_diff_net_return_pts": _pct(diffs, 50),
                        "mean_diff_net_return_pts": float(np.mean(diffs)),
                        "median_diff_sharpe": _pct(
                            [t["sharpe"] - r["sharpe"] for r, t in zip(rej, tr, strict=True)], 50
                        ),
                        "median_max_dd_reject_pct": dd_rej,
                        "median_max_dd_trim_pct": dd_trim,
                        "median_max_dd_diff_pts": dd_trim - dd_rej,
                        "sign_test_pass": sign_ok,
                        "drawdown_pass": dd_ok,
                        "period_pass": sign_ok and dd_ok,
                    }
                )
            out["trim_verdicts"].append(
                {
                    "book": book,
                    "cap_set": cap,
                    "IS_pass": trim_period_pass["IS"],
                    "OOS_pass": trim_period_pass["OOS"],
                    "admission_candidate": trim_period_pass["IS"] and trim_period_pass["OOS"],
                }
            )
            for trim in (0, 1):
                for key in KEYS:
                    passes = {}
                    for period in ("IS", "OOS"):
                        rs = cells[(book, cap, period, "random", trim)]
                        ks = [
                            r for r in cells[(book, cap, period, "key", trim)] if r["order"] == key
                        ]
                        if len(ks) != 1:
                            raise SystemExit(
                                f"{book} {cap} {period} {key} trim={trim}: {len(ks)} runs"
                            )
                        kr = ks[0]
                        nets = [r["net_return_pct"] for r in rs]
                        sharpes = [r["sharpe"] for r in rs]
                        p90_net, p90_sh = _pct(nets, KEY_PERCENTILE), _pct(sharpes, KEY_PERCENTILE)
                        net_ok = kr["net_return_pct"] > p90_net
                        sh_ok = kr["sharpe"] > p90_sh
                        passes[period] = bool(net_ok and sh_ok)
                        out["keys"].append(
                            {
                                "book": book,
                                "cap_set": cap,
                                "trim": trim,
                                "key": key,
                                "period": period,
                                "net_return_pct": kr["net_return_pct"],
                                "random_p90_net_return_pct": p90_net,
                                "random_p50_net_return_pct": _pct(nets, 50),
                                "net_percentile_in_random": 100.0
                                * sum(v < kr["net_return_pct"] for v in nets)
                                / len(nets),
                                "sharpe": kr["sharpe"],
                                "random_p90_sharpe": p90_sh,
                                "random_p50_sharpe": _pct(sharpes, 50),
                                "sharpe_percentile_in_random": 100.0
                                * sum(v < kr["sharpe"] for v in sharpes)
                                / len(sharpes),
                                "cagr_pct": kr["cagr_pct"],
                                "max_drawdown_pct": kr["max_drawdown_pct"],
                                "mean_exposure_pct": kr["mean_exposure_pct"],
                                "entries": kr["entries"],
                                "signals_total": kr["signals_total"],
                                "entries_per_signal": kr["entries_per_signal"],
                                "net_above_p90": bool(net_ok),
                                "sharpe_above_p90": bool(sh_ok),
                                "period_pass": passes[period],
                            }
                        )
                    out["key_verdicts"].append(
                        {
                            "book": book,
                            "cap_set": cap,
                            "trim": trim,
                            "key": key,
                            "IS_pass": passes["IS"],
                            "OOS_pass": passes["OOS"],
                            "admission_candidate": passes["IS"] and passes["OOS"],
                        }
                    )
    return out


def stress_summary(rows: list[dict[str, Any]], books: list[str]) -> list[dict[str, Any]]:
    cells: dict[tuple, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        cells[
            (
                r["book"],
                r["cap_set"],
                r["period"],
                r["arm"],
                r["order"] if r["arm"] == "key" else "",
                r["trim"],
            )
        ].append(r)
    out = []
    for book in books:
        for cap in ("operating", "maxima"):
            for period in ("IS", "OOS"):
                rej = sorted(
                    cells.get((book, cap, period, "random", "", 0), []), key=lambda r: r["order"]
                )
                tr = sorted(
                    cells.get((book, cap, period, "random", "", 1), []), key=lambda r: r["order"]
                )
                if len(rej) != N_SEEDS or len(tr) != N_SEEDS:
                    continue
                diffs = [
                    t["net_return_pct"] - r["net_return_pct"] for r, t in zip(rej, tr, strict=True)
                ]
                out.append(
                    {
                        "book": book,
                        "cap_set": cap,
                        "period": period,
                        "reject_median_net_return_pct": _pct(
                            [r["net_return_pct"] for r in rej], 50
                        ),
                        "trim_median_net_return_pct": _pct([r["net_return_pct"] for r in tr], 50),
                        "reject_median_sharpe": _pct([r["sharpe"] for r in rej], 50),
                        "trim_median_sharpe": _pct([r["sharpe"] for r in tr], 50),
                        "reject_median_max_dd_pct": _pct([r["max_drawdown_pct"] for r in rej], 50),
                        "trim_median_max_dd_pct": _pct([r["max_drawdown_pct"] for r in tr], 50),
                        "reject_band_net_return_pct": _band([r["net_return_pct"] for r in rej]),
                        "trim_band_net_return_pct": _band([r["net_return_pct"] for r in tr]),
                        "trim_wins": sum(d > 0 for d in diffs),
                        "median_diff_net_return_pts": _pct(diffs, 50),
                    }
                )
    return out


def stress_key_summary(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Each stress-cost key run against the stress-cost random orders of the same book,
    cap set, period and trim mode (informational: the decision rule is a base-cost rule)."""
    out = []
    for kr in sorted(
        (r for r in rows if r["arm"] == "key"),
        key=lambda r: (r["book"], r["cap_set"], r["trim"], r["order"], r["period"]),
    ):
        rs = [
            r
            for r in rows
            if r["arm"] == "random"
            and (r["book"], r["cap_set"], r["period"], r["trim"])
            == (kr["book"], kr["cap_set"], kr["period"], kr["trim"])
        ]
        if len(rs) != N_SEEDS:
            raise SystemExit("stress key arm without its 40 random orders")
        nets = [r["net_return_pct"] for r in rs]
        sharpes = [r["sharpe"] for r in rs]
        out.append(
            {
                "book": kr["book"],
                "cap_set": kr["cap_set"],
                "trim": kr["trim"],
                "key": kr["order"],
                "period": kr["period"],
                "net_return_pct": kr["net_return_pct"],
                "sharpe": kr["sharpe"],
                "max_drawdown_pct": kr["max_drawdown_pct"],
                "random_p50_net_return_pct": _pct(nets, 50),
                "random_p90_net_return_pct": _pct(nets, KEY_PERCENTILE),
                "random_p50_sharpe": _pct(sharpes, 50),
                "random_p90_sharpe": _pct(sharpes, KEY_PERCENTILE),
                "net_percentile_in_random": 100.0
                * sum(v < kr["net_return_pct"] for v in nets)
                / len(nets),
                "sharpe_percentile_in_random": 100.0
                * sum(v < kr["sharpe"] for v in sharpes)
                / len(sharpes),
                "above_p90_both": bool(
                    kr["net_return_pct"] > _pct(nets, KEY_PERCENTILE)
                    and kr["sharpe"] > _pct(sharpes, KEY_PERCENTILE)
                ),
            }
        )
    return out


# ----------------------------------------------------------------------------- report tables
SHORT = {
    "trend_continuation.medium_swing": "TC medium (11)",
    "high52_breakout.medium_swing": "high52 (11)",
    "trend_continuation.short_swing": "TC short (3)",
    "relative_strength.medium_swing": "RS medium (3)",
}


def _n(x: float | None, digits: int = 2, signed: bool = False) -> str:
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "n/a"
    return f"{x:+.{digits}f}" if signed else f"{x:.{digits}f}"


def render_tables(summary: dict[str, Any]) -> str:
    L: list[str] = []
    ident = summary["identity"]
    spy = summary["spy"]
    caps = {c["name"]: c for c in summary["cap_sets"]}
    books = summary["books_run"]

    L += ["## Identity check (alphabetical order, outright rejection, base costs)", ""]
    L += [
        "| Book | Cap set | Period | Fills (library / local) | Final equity library $ | Final equity local $ | Fills identical | Marks identical | Decisions identical | Passed |",
        "|---|---|---|---:|---:|---:|---|---|---|---|",
    ]
    for rep in ident["books"]:
        for c in rep["cells"]:
            L.append(
                f"| {SHORT[rep['strategy']]} | {c['cap_set']} | {c['period']} | {c['library_fills']} / {c['local_fills']} "
                f"| {c['library_final_equity_usd']} | {c['local_final_equity_usd']} | {'yes' if c['fills_identical'] else 'NO'} "
                f"| {'yes' if c['marks_identical'] else 'NO'} | {'yes' if c['decisions_identical'] else 'NO'} | {'yes' if c['passed'] else 'NO'} |"
            )
    L += [""]

    L += ["## Luck band: 40 random same-day orders, outright rejection, base costs", ""]
    L += [
        "| Book | Cap set | Period | Net % p5 | Net % p50 | Net % p95 | p95 - p5 (pts) | Sharpe p5 | Sharpe p50 | Sharpe p95 | Median CAGR % | Median max DD % | Median exposure % | Median entries / signals | Alphabetical order net % (percentile in the 40) | SPY total return % |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for b in summary["analysis"]["luck_band"]:
        if b["trim"] != 0:
            continue
        L.append(
            f"| {SHORT[b['book']]} | {b['cap_set']} | {b['period']} | {_n(b['net_return_pct']['p5'], signed=True)} | {_n(b['net_return_pct']['p50'], signed=True)} "
            f"| {_n(b['net_return_pct']['p95'], signed=True)} | {_n(b['net_return_p95_minus_p5_pts'])} | {_n(b['sharpe']['p5'])} | {_n(b['sharpe']['p50'])} | {_n(b['sharpe']['p95'])} "
            f"| {_n(b['median_cagr_pct'], signed=True)} | {_n(b['median_max_drawdown_pct'])} | {_n(b['median_mean_exposure_pct'], 1)} "
            f"| {_n(b['median_entries'], 0)} / {b['signals_total']} ({_n(100 * b['median_entries_per_signal'], 1)}%) "
            f"| {_n(b['alphabetical_net_return_pct'], signed=True)} ({_n(b['alphabetical_percentile_in_random'], 1)}) "
            f"| {_n(spy[BASE][b['period']]['net_return_pct'], signed=True)} |"
        )
    L += [""]

    L += ["## Trim-to-budget vs outright rejection: the same 40 orders, paired, base costs", ""]
    L += [
        "| Book | Cap set | Period | Trim wins / 40 | Losses | Ties | Median diff (pts) | Net % p50 reject | Net % p50 trim | Median max DD reject % | Median max DD trim % | DD diff (pts) | Median entries trim | Median entries admitted by a trim | Sign test >= 26 | DD <= +2 | Period pass |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|---|",
    ]
    band = {
        (b["book"], b["cap_set"], b["period"], b["trim"]): b
        for b in summary["analysis"]["luck_band"]
    }
    for t in summary["analysis"]["trim"]:
        r0 = band[(t["book"], t["cap_set"], t["period"], 0)]
        r1 = band[(t["book"], t["cap_set"], t["period"], 1)]
        L.append(
            f"| {SHORT[t['book']]} | {t['cap_set']} | {t['period']} | {t['wins']} | {t['losses']} | {t['ties']} "
            f"| {_n(t['median_diff_net_return_pts'], signed=True)} | {_n(r0['net_return_pct']['p50'], signed=True)} | {_n(r1['net_return_pct']['p50'], signed=True)} "
            f"| {_n(t['median_max_dd_reject_pct'])} | {_n(t['median_max_dd_trim_pct'])} | {_n(t['median_max_dd_diff_pts'], signed=True)} "
            f"| {_n(r1['median_entries'], 0)} | {_n(r1['median_trim_admitted'], 0)} "
            f"| {'yes' if t['sign_test_pass'] else 'no'} | {'yes' if t['drawdown_pass'] else 'no'} | {'PASS' if t['period_pass'] else 'fail'} |"
        )
    L += [
        "",
        "| Book | Cap set | IS | OOS | Trim-to-budget admission candidate |",
        "|---|---|---|---|---|",
    ]
    for v in summary["analysis"]["trim_verdicts"]:
        L.append(
            f"| {SHORT[v['book']]} | {v['cap_set']} | {'pass' if v['IS_pass'] else 'fail'} | {'pass' if v['OOS_pass'] else 'fail'} "
            f"| {'YES' if v['admission_candidate'] else 'no'} |"
        )
    L += [""]

    L += ["## Luck band with trim-to-budget (the same 40 orders), base costs", ""]
    L += [
        "| Book | Cap set | Period | Net % p5 | Net % p50 | Net % p95 | Sharpe p5 | Sharpe p50 | Sharpe p95 | Median CAGR % | Median max DD % | Median exposure % | Median entries / signals |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for b in summary["analysis"]["luck_band"]:
        if b["trim"] != 1:
            continue
        L.append(
            f"| {SHORT[b['book']]} | {b['cap_set']} | {b['period']} | {_n(b['net_return_pct']['p5'], signed=True)} | {_n(b['net_return_pct']['p50'], signed=True)} "
            f"| {_n(b['net_return_pct']['p95'], signed=True)} | {_n(b['sharpe']['p5'])} | {_n(b['sharpe']['p50'])} | {_n(b['sharpe']['p95'])} "
            f"| {_n(b['median_cagr_pct'], signed=True)} | {_n(b['median_max_drawdown_pct'])} | {_n(b['median_mean_exposure_pct'], 1)} "
            f"| {_n(b['median_entries'], 0)} / {b['signals_total']} ({_n(100 * b['median_entries_per_signal'], 1)}%) |"
        )
    L += [""]

    L += ["## Ranking keys against the random-order distribution, base costs", ""]
    L += [
        "Percentile = share of the 40 random orders (same book, cap set, period and trim mode) "
        "strictly below the key's value. A cell passes only if net return and Sharpe are both "
        "above the random 90th percentile.",
        "",
        "| Book | Cap set | Mode | Key | Period | Net % | Random p90 net % | Net percentile | Sharpe | Random p90 Sharpe | Sharpe percentile | CAGR % | Max DD % | Exposure % | Entries / signals | Period pass |",
        "|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for k in summary["analysis"]["keys"]:
        L.append(
            f"| {SHORT[k['book']]} | {k['cap_set']} | {'trim' if k['trim'] else 'reject'} | {k['key']} | {k['period']} "
            f"| {_n(k['net_return_pct'], signed=True)} | {_n(k['random_p90_net_return_pct'], signed=True)} | {_n(k['net_percentile_in_random'], 1)} "
            f"| {_n(k['sharpe'])} | {_n(k['random_p90_sharpe'])} | {_n(k['sharpe_percentile_in_random'], 1)} "
            f"| {_n(k['cagr_pct'], signed=True)} | {_n(k['max_drawdown_pct'])} | {_n(k['mean_exposure_pct'], 1)} "
            f"| {k['entries']} / {k['signals_total']} ({_n(100 * k['entries_per_signal'], 1)}%) | {'PASS' if k['period_pass'] else 'fail'} |"
        )
    L += [
        "",
        "| Book | Cap set | Mode | Key | IS | OOS | Ranking-key admission candidate |",
        "|---|---|---|---|---|---|---|",
    ]
    for v in summary["analysis"]["key_verdicts"]:
        L.append(
            f"| {SHORT[v['book']]} | {v['cap_set']} | {'trim' if v['trim'] else 'reject'} | {v['key']} "
            f"| {'pass' if v['IS_pass'] else 'fail'} | {'pass' if v['OOS_pass'] else 'fail'} | {'YES' if v['admission_candidate'] else 'no'} |"
        )
    L += [""]

    if summary.get("stress"):
        st = summary["stress"]
        trims = {(t["book"], t["cap_set"], t["period"]): t for t in summary["analysis"]["trim"]}
        keys_base = {
            (k["book"], k["cap_set"], k["trim"], k["key"], k["period"]): k
            for k in summary["analysis"]["keys"]
        }
        L += [f"## Final table: qualifying arms at base and stress costs ({st['selection']})", ""]
        L += [
            "The decision rules are base-cost rules; the stress columns are reported for the "
            "reader and carry no verdict. Stress = $0.005 per share with a $1 minimum, 10 bps "
            "slippage, 10 bps spread.",
            "",
        ]
        if st.get("trim_candidates"):
            L += [
                "Trim-to-budget candidates (40 paired random orders):",
                "",
                "| Book | Cap set | Period | Base: trim wins / 40 | Base: median diff (pts) | Stress: trim wins / 40 | Stress: median diff (pts) | Stress net % p50 reject | Stress net % p50 trim | Stress Sharpe p50 reject | Stress Sharpe p50 trim | Stress max DD % p50 reject | Stress max DD % p50 trim |",
                "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
            ]
            wanted = {tuple(x) for x in st["trim_candidates"]}
            for srow in st["random_median"]:
                if (srow["book"], srow["cap_set"]) not in wanted:
                    continue
                t = trims[(srow["book"], srow["cap_set"], srow["period"])]
                L.append(
                    f"| {SHORT[srow['book']]} | {srow['cap_set']} | {srow['period']} | {t['wins']} | {_n(t['median_diff_net_return_pts'], signed=True)} "
                    f"| {srow['trim_wins']} | {_n(srow['median_diff_net_return_pts'], signed=True)} "
                    f"| {_n(srow['reject_median_net_return_pct'], signed=True)} | {_n(srow['trim_median_net_return_pct'], signed=True)} "
                    f"| {_n(srow['reject_median_sharpe'])} | {_n(srow['trim_median_sharpe'])} "
                    f"| {_n(srow['reject_median_max_dd_pct'])} | {_n(srow['trim_median_max_dd_pct'])} |"
                )
            L += [""]
        if st.get("keys"):
            L += [
                "Ranking-key candidates (percentile within the 40 random orders of the same trim mode and cost case):",
                "",
                "| Book | Cap set | Mode | Key | Period | Base net % | Base random p50 / p90 net % | Base percentile net / Sharpe | Stress net % | Stress random p50 / p90 net % | Stress Sharpe | Stress random p50 / p90 Sharpe | Stress percentile net / Sharpe | Stress max DD % | Above stress p90 on both |",
                "|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
            ]
            for k in st["keys"]:
                b = keys_base[(k["book"], k["cap_set"], k["trim"], k["key"], k["period"])]
                L.append(
                    f"| {SHORT[k['book']]} | {k['cap_set']} | {'trim' if k['trim'] else 'reject'} | {k['key']} | {k['period']} "
                    f"| {_n(b['net_return_pct'], signed=True)} | {_n(b['random_p50_net_return_pct'], signed=True)} / {_n(b['random_p90_net_return_pct'], signed=True)} "
                    f"| {_n(b['net_percentile_in_random'], 1)} / {_n(b['sharpe_percentile_in_random'], 1)} "
                    f"| {_n(k['net_return_pct'], signed=True)} | {_n(k['random_p50_net_return_pct'], signed=True)} / {_n(k['random_p90_net_return_pct'], signed=True)} "
                    f"| {_n(k['sharpe'])} | {_n(k['random_p50_sharpe'])} / {_n(k['random_p90_sharpe'])} "
                    f"| {_n(k['net_percentile_in_random'], 1)} / {_n(k['sharpe_percentile_in_random'], 1)} | {_n(k['max_drawdown_pct'])} "
                    f"| {'yes' if k['above_p90_both'] else 'no'} |"
                )
            L += [""]
        L += [
            "Random-order medians at stress costs for every book and cap set that was run at stress (reject vs trim):",
            "",
            "| Book | Cap set | Period | Reject net % p5 / p50 / p95 | Trim net % p5 / p50 / p95 | Reject Sharpe p50 | Trim Sharpe p50 | Trim wins / 40 | Median diff (pts) | SPY total return % (stress costs) |",
            "|---|---|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
        for srow in st["random_median"]:
            rb, tb = srow["reject_band_net_return_pct"], srow["trim_band_net_return_pct"]
            L.append(
                f"| {SHORT[srow['book']]} | {srow['cap_set']} | {srow['period']} "
                f"| {_n(rb['p5'], signed=True)} / {_n(rb['p50'], signed=True)} / {_n(rb['p95'], signed=True)} "
                f"| {_n(tb['p5'], signed=True)} / {_n(tb['p50'], signed=True)} / {_n(tb['p95'], signed=True)} "
                f"| {_n(srow['reject_median_sharpe'])} | {_n(srow['trim_median_sharpe'])} | {srow['trim_wins']} | {_n(srow['median_diff_net_return_pts'], signed=True)} "
                f"| {_n(spy[STRESS][srow['period']]['net_return_pct'], signed=True)} |"
            )
        L += [""]

    L += ["## SPY total return for the same periods (reference)", ""]
    L += [
        "| Period | Cost case | Net % | CAGR % | Max DD % | Sharpe |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for cost in (BASE, STRESS):
        for period in ("IS", "OOS"):
            s = spy[cost][period]
            L.append(
                f"| {period} | {cost} | {_n(s['net_return_pct'], signed=True)} | {_n(s['cagr_pct'], signed=True)} | {_n(s['max_drawdown_pct'])} | {_n(s['sharpe'])} |"
            )
    L += [""]
    L += ["## Scope actually run", ""]
    for rep in ident["books"]:
        L.append(
            f"- {rep['strategy']} (strategy version {rep['strategy_version_id']}, snapshot {rep['snapshot_id']}): "
            f"{rep['symbols_replayed']} symbols replayed, skipped for incomplete bars: {', '.join(rep['skipped_symbols']) or 'none'}; "
            f"{rep['table']['signal_days_total']} signal-days in the table; dividend rows for {rep['symbols_with_dividend_rows']} symbols."
        )
    L.append(
        f"- Cap sets: operating = open risk {caps['operating']['open_risk_pct']}%, gross {caps['operating']['gross_pct']}%, "
        f"{caps['operating']['daily_cap']} accepts per day (read from the scratch copy); maxima = open risk {caps['maxima']['open_risk_pct']}%, "
        f"gross {caps['maxima']['gross_pct']}%, no daily cap. Both: per-trade risk {PER_TRADE_RISK_PCT}%, symbol {SYMBOL_CAP_PCT}%, sector {SECTOR_CAP_PCT}%, ${INITIAL_CASH} cash."
    )
    L.append(
        f"- Books run: {', '.join(books)}. Runs saved: {summary['runs']['base']} base, {summary['runs'].get('stress', 0)} stress."
    )
    L += [""]
    return "\n".join(L)


# ----------------------------------------------------------------------------- stages
def _git_head() -> str:
    try:
        return subprocess.run(  # noqa: S603 - fixed argv, read-only metadata
            ["git", "-C", str(Path(__file__).resolve().parents[2]), "rev-parse", "HEAD"],  # noqa: S607
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except Exception:
        return "unknown"


def self_test_trim() -> None:
    """``_largest_fit`` returns the largest size the library's own test accepts, and
    ``size_position_trim`` equals ``size_position`` whenever the library accepts."""
    rng = np.random.default_rng(SEED0)
    limits = make_limits(Caps("t", 1.5, 60.0, None))
    for _ in range(20000):
        upper = int(rng.integers(1, 400))
        used, unit, cap = (
            float(rng.uniform(0, 2e4)),
            float(rng.uniform(0.05, 900)),
            float(rng.uniform(0, 2.2e4)),
        )
        n = _largest_fit(upper, used, unit, cap)
        assert 0 <= n <= upper
        assert n == 0 or not used + n * unit > cap
        assert n == upper or used + (n + 1) * unit > cap
        equity = float(rng.uniform(2.5e4, 4e4))
        price = float(rng.uniform(5, 900))
        request = SizingRequest("X", "S", price, price * float(rng.uniform(0.9, 0.995)), equity)
        exposure = OpenExposure(
            float(rng.uniform(0, 0.62 * equity)),
            float(rng.uniform(0, 0.016 * equity)),
            {"S": float(rng.uniform(0, 0.21 * equity))},
            3,
        )
        a, b = (
            size_position(request, limits, exposure),
            size_position_trim(request, limits, exposure),
        )
        if not a.rejected:
            assert not b.rejected and a.shares == b.shares and a.notional == b.notional
        else:
            assert b.rejected or b.shares >= 1


def stage_prepare(out: Path, db: Path, workers: int) -> int:
    self_test_trim()
    caps = read_operating_caps(db)
    print("cap sets:", [asdict(c) for c in caps], flush=True)
    ctx = mp.get_context("spawn")
    started = time.perf_counter()
    with ctx.Pool(
        workers, initializer=_init, initargs=(str(out), json.dumps([asdict(c) for c in caps]))
    ) as pool:
        reports = pool.map(
            prepare_book, [(s, snap, vid, str(db)) for s, snap, vid in BOOKS], chunksize=1
        )
    identity = {
        "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "git_head": _git_head(),
        "database": str(db),
        "cap_sets": [asdict(c) for c in caps],
        "books": reports,
        "passed": all(r["passed"] for r in reports),
        "stress_passed": all(r["stress_passed"] for r in reports),
        "canonical_crosscheck_passed": all(
            r["canonical_report_crosscheck"]["passed"] for r in reports
        ),
        "seconds": round(time.perf_counter() - started, 1),
    }
    (out / "identity.json").write_text(json.dumps(identity, indent=2) + "\n")
    for r in reports:
        print(
            r["strategy"],
            "identity",
            "PASS" if r["passed"] else "FAIL",
            "| stress identity",
            "PASS" if r["stress_passed"] else "FAIL",
            "| canonical cross-check",
            "PASS" if r["canonical_report_crosscheck"]["passed"] else "FAIL",
            f"| {r['seconds']}s",
            flush=True,
        )
        for c in r["cells"]:
            print(
                f"   {c['cap_set']:9s} {c['period']:3s} fills {c['library_fills']}/{c['local_fills']} "
                f"final {c['library_final_equity_usd']} / {c['local_final_equity_usd']} "
                f"lib {c['library_seconds']}s local {c['local_seconds']}s {'ok' if c['passed'] else 'MISMATCH'}",
                flush=True,
            )
    if not identity["passed"]:
        print("IDENTITY CHECK FAILED - study stops here", flush=True)
        return 2
    return 0


def _identity(out: Path) -> dict[str, Any]:
    identity = json.loads((out / "identity.json").read_text())
    if not identity["passed"]:
        raise SystemExit("identity check has not passed; nothing may be run or reported")
    return identity


def stage_grid(out: Path, workers: int, books: list[str]) -> int:
    identity = _identity(out)
    caps = [Caps(**c) for c in identity["cap_sets"]]
    run_pool(grid_tasks(BASE, books, keys=True), out, caps, out / "runs.csv", workers)
    return 0


def stage_analyze(out: Path, books: list[str]) -> int:
    identity = _identity(out)
    rows = [r for r in load_rows(out / "runs.csv") if r["cost_case"] == BASE and r["book"] in books]
    analysis = analyze(rows, books, identity)
    summary = {
        "study": "R3-C capacity admission",
        "preregistration": "docs/research/PREREGISTRATION_r3_capacity_admission_2026-11-10.md",
        "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "git_head": identity["git_head"],
        "database": identity["database"],
        "periods": {k: [str(a), str(b)] for k, (a, b) in PERIODS.items()},
        "initial_cash_usd": str(INITIAL_CASH),
        "cap_sets": identity["cap_sets"],
        "seeds": [seed_for(i) for i in range(N_SEEDS)],
        "books_run": books,
        "books_not_run": [b for b, _, _ in BOOKS if b not in books],
        "identity": identity,
        "spy": identity["books"][0]["spy"],
        "analysis": analysis,
        "decision_rules": {
            "trim": f"both periods: trim beats reject on net return in >= {SIGN_TEST_WINS} of {N_SEEDS} paired orders and median max drawdown not more than {DD_TOLERANCE_PTS} points higher",
            "key": f"both periods: net return and Sharpe above the {KEY_PERCENTILE:.0f}th percentile (numpy linear interpolation) of the 40 random orders on the same cap set and trim mode",
        },
        "verdicts": {
            "trim_candidates": [
                f"{v['book']} / {v['cap_set']}"
                for v in analysis["trim_verdicts"]
                if v["admission_candidate"]
            ],
            "key_candidates": [
                f"{v['book']} / {v['cap_set']} / {'trim' if v['trim'] else 'reject'} / {v['key']}"
                for v in analysis["key_verdicts"]
                if v["admission_candidate"]
            ],
        },
        "runs": {"base": len(rows)},
    }
    spy_all = [rep["spy"] for rep in identity["books"]]
    assert all(s == spy_all[0] for s in spy_all), "SPY reference differs between books"
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary["verdicts"], indent=2))
    return 0


def stage_stress(out: Path, workers: int, books: list[str]) -> int:
    identity = _identity(out)
    summary = json.loads((out / "summary.json").read_text())
    if not identity["stress_passed"]:
        print("stress-cost identity did not pass; stress table is not produced", flush=True)
        summary["stress"] = None
        (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        return 0
    caps = [Caps(**c) for c in identity["cap_sets"]]
    trim_c = [v for v in summary["analysis"]["trim_verdicts"] if v["admission_candidate"]]
    key_c = [v for v in summary["analysis"]["key_verdicts"] if v["admission_candidate"]]
    tasks: list[tuple] = []
    if not trim_c and not key_c:
        selection = "no arm qualified: random-order median, reject vs trim, every book"
        tasks = grid_tasks(STRESS, books, keys=False)
    else:
        selection = "qualifying arms only, with their paired random orders"
        seen: set[tuple] = set()
        for v in trim_c:
            for period in ("IS", "OOS"):
                for i in range(N_SEEDS):
                    for trim in (False, True):
                        seen.add((v["book"], v["cap_set"], period, STRESS, "random", i, trim))
        for v in key_c:
            for period in ("IS", "OOS"):
                seen.add(
                    (v["book"], v["cap_set"], period, STRESS, "key", v["key"], bool(v["trim"]))
                )
                for i in range(N_SEEDS):
                    for trim in (False, True):
                        seen.add((v["book"], v["cap_set"], period, STRESS, "random", i, trim))
        order = {b: k for k, (b, _, _) in enumerate(BOOKS)}
        tasks = sorted(seen, key=lambda t: (order[t[0]], t[1], t[2], t[4], str(t[5]), t[6]))
    run_pool(tasks, out, caps, out / "stress_runs.csv", workers)
    rows = [r for r in load_rows(out / "stress_runs.csv") if r["cost_case"] == STRESS]
    summary["stress"] = {
        "selection": selection,
        "cost_case": STRESS,
        "random_median": stress_summary(rows, books),
        "keys": stress_key_summary(rows),
        "trim_candidates": [[v["book"], v["cap_set"]] for v in trim_c],
        "key_candidates": [[v["book"], v["cap_set"], v["trim"], v["key"]] for v in key_c],
    }
    summary["runs"]["stress"] = len(rows)
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    return 0


RESULTS_FILE = (
    Path(__file__).resolve().parents[2]
    / "docs/research/RESULTS_r3_capacity_admission_2026-11-10.md"
)


def stage_report(out: Path) -> int:
    """Write the generated tables; when the hand-written head and tail exist beside
    them, assemble the pre-registered results file (text by hand, numbers by script)."""
    summary = json.loads((out / "summary.json").read_text())
    tables = render_tables(summary)
    (out / "tables.md").write_text(tables)
    print(f"wrote {out / 'tables.md'}")
    head, tail = out / "results_head.md", out / "results_tail.md"
    if head.exists() and tail.exists():
        text = (
            head.read_text().rstrip()
            + "\n\n"
            + tables.rstrip()
            + "\n\n"
            + tail.read_text().rstrip()
            + "\n"
        )
        RESULTS_FILE.write_text(text)
        print(f"wrote {RESULTS_FILE}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("stage", choices=["prepare", "grid", "analyze", "stress", "report", "all"])
    p.add_argument("--db", type=Path, default=None, help="scratch database (read-only)")
    p.add_argument("--out", type=Path, default=None, help="raw output folder")
    p.add_argument("--workers", type=int, default=3)
    p.add_argument("--books", default=",".join(b for b, _, _ in BOOKS))
    a = p.parse_args(argv)
    if not 1 <= a.workers <= 3:
        p.error("CPU budget for this study is at most 3 worker processes")
    a.db = a.db or default_db()
    a.out = a.out or default_out()
    _guard_paths(a.db, a.out)
    a.out.mkdir(parents=True, exist_ok=True)
    books = [b.strip() for b in a.books.split(",") if b.strip()]
    known = [b for b, _, _ in BOOKS]
    if any(b not in known for b in books):
        p.error(f"unknown book; choose from {known}")
    books = [b for b in known if b in books]
    stages = ["prepare", "grid", "analyze", "stress", "report"] if a.stage == "all" else [a.stage]
    for stage in stages:
        print(f"== {stage} ({time.strftime('%H:%M:%S', time.gmtime())} UTC)", flush=True)
        if stage == "prepare":
            code = stage_prepare(a.out, a.db, a.workers)
        elif stage == "grid":
            code = stage_grid(a.out, a.workers, books)
        elif stage == "analyze":
            code = stage_analyze(a.out, books)
        elif stage == "stress":
            code = stage_stress(a.out, a.workers, books)
        else:
            code = stage_report(a.out)
        if code:
            return code
    return 0


if __name__ == "__main__":
    sys.exit(main())
