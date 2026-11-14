"""R4-O: do the approved rules add anything on top of holding the index?

Pre-registration: docs/research/PREREGISTRATION_r4_core_overlay_2026-11-10.md (commit 1b8cc3a)
Results file:     docs/research/RESULTS_r4_core_overlay_2026-11-10.md

Read-only research on a private scratch copy of the database, development window only
(bars end 2025-09-05). No library code and no R3 script is edited: this script imports
the R3-C module (``scripts/r3/capacity_admission.py``) for the books, their cached signal
tables, the script-local funded replay, the 40 seeded same-day orders and the metrics.

The account is a book plus an index sleeve that holds the book's idle cash in SPY. The
overlay never changes a book's trades: every entry, exit, size and cost is that of the
standalone replay, sized on the book's own equity.

Stages (``python core_overlay.py <stage>``):

  run     identity check A (the 640 R3-C random-order, outright-rejection, base-cost
          replays are re-run and each must reproduce its row in R3-C's runs.csv), the
          SPY total-return legs, identity check B (accounting unit tests), the overlay
          accounts, increments and verdicts, and stress costs for qualifying cells only
          -> replays.csv, replays_by_year.csv, marks_base.npz, summary.json
  report  markdown tables from summary.json (and the results file when the
          hand-written head and tail exist beside them)

Research signal only - no order was placed.
"""
# ruff: noqa: E501 - markdown table rows and their f-strings are kept on one line

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import pickle
import sqlite3
import subprocess
import sys
import time
from dataclasses import asdict
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

_SCRIPTS = Path(__file__).resolve().parents[1]
for _p in (_SCRIPTS, _SCRIPTS / "r3"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import capacity_admission as ca  # noqa: E402 - the R3-C study module; imported, never modified
import funded_replay_report as frr  # noqa: E402
import numpy as np  # noqa: E402

from signalforge.backtest.actions import Dividend  # noqa: E402
from signalforge.backtest.funded import money, sell_price  # noqa: E402
from signalforge.data.series import PriceSeries  # noqa: E402

# ----------------------------------------------------------------------------- fixed scope
PREREGISTRATION = "docs/research/PREREGISTRATION_r4_core_overlay_2026-11-10.md"
RESULTS_FILE = (
    Path(__file__).resolve().parents[2] / "docs/research/RESULTS_r4_core_overlay_2026-11-10.md"
)
K0 = 30000.0
assert Decimal(str(K0)) == ca.INITIAL_CASH
SLEEVE_COST = {ca.BASE: 5.5e-4, ca.STRESS: 11.0e-4}  # c: cost per dollar of sleeve flow
CAP_SETS = ("operating", "maxima")
PERIOD_NAMES = ("IS", "OOS")
MIN_POSITIVE_ORDERS = 36  # of 40
DD_TOLERANCE_PTS = 2.0
SHORTFALL_LIMIT_PCT = 1.0
CENT_TOL = 0.005  # "to the cent"
R3C_SPY_NET = {"IS": 130.13, "OOS": 50.60}  # as printed in the R3-C results file

EXIT_KINDS = ("gap_stop", "stop", "target", "time_stop", "end_of_data", "dividend")
REQUIRED_FIELDS = ("final_equity_usd", "entries", "net_return_pct")
FLOAT_FIELDS = (
    "net_return_pct",
    "cagr_pct",
    "max_drawdown_pct",
    "sharpe",
    "mean_exposure_pct",
    "entries_per_signal",
)
INT_FIELDS = ("entries", "signals_total", "signals_offered", "trim_admitted")
TEXT_FIELDS = ("final_equity_usd", "costs_usd", "dividend_income_usd", "rejections")
ALL_FIELDS = FLOAT_FIELDS + INT_FIELDS + TEXT_FIELDS


def default_out() -> Path:
    """Raw outputs live beside the scratch database folder: ``<scratch>/r3/out/r4-overlay``."""
    return ca.default_db().parent.parent / "out" / "r4-overlay"


# ----------------------------------------------------------------------------- data
_CACHE_GLOBALS = {
    ("datetime", "date"),
    ("decimal", "Decimal"),
    ("numpy", "dtype"),
    ("numpy", "ndarray"),
    ("numpy._core.numeric", "_frombuffer"),
    ("numpy._core.multiarray", "_reconstruct"),
    ("numpy._core.multiarray", "scalar"),
    ("signalforge.data.series", "PriceSeries"),
    ("signalforge.backtest.actions", "Dividend"),
    ("signalforge.backtest.funded", "AttributedEntrySignal"),
    ("signalforge.domain", "Direction"),
}


class _CacheUnpickler(pickle.Unpickler):
    """Reads R3-C's own book cache and nothing else.

    R3-C wrote the cache from pool workers, where the study script is the module
    ``__mp_main__``; that name is mapped to the imported module's ``Book``. Every other
    global must be one of the plain data types the cache is known to contain."""

    def find_class(self, module: str, name: str) -> Any:
        if name == "Book" and module in ("__mp_main__", "__main__", "capacity_admission"):
            return ca.Book
        if (module, name) not in _CACHE_GLOBALS:
            raise pickle.UnpicklingError(f"unexpected global in book cache: {module}.{name}")
        return super().find_class(module, name)


def load_books(cache: Path) -> dict[str, ca.Book]:
    """The four books exactly as R3-C prepared them (bars, sectors, dividends, signals)."""
    books: dict[str, ca.Book] = {}
    for strategy, snapshot_id, version_id in ca.BOOKS:
        # Trusted input: written by R3-C's own prepare stage into the private scratch folder.
        with (cache / f"{strategy}.pkl").open("rb") as fh:
            book = _CacheUnpickler(fh).load()
        assert isinstance(book, ca.Book)
        assert (book.strategy, book.snapshot_id, book.version_id) == (
            strategy,
            snapshot_id,
            version_id,
        )
        assert book.dates[0] == ca.FULL_START and book.dates[-1] == ca.DEV_END
        assert max(book.dates) < ca.NEVER_ON_OR_AFTER
        for bars in book.data.values():
            assert bars.dates == book.dates
        assert book.day_signals and len(book.day_signals) == len(book.dates)
        books[strategy] = book
    return books


def check_spy_against_db(db: Path, books: dict[str, ca.Book]) -> dict[str, Any]:
    """SPY bars and dividends in every cached book equal a fresh, window-bounded read of
    the scratch copy; and the stored bars carry no dividend adjustment.

    Nothing dated after 2025-09-05 is selected. The library dividend loader reads the
    symbol's split rows without a date bound (R3-C point 19); SPY has none."""
    ca._guard_paths(db)
    dates = next(iter(books.values())).dates
    with sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True) as c:
        c.execute("PRAGMA query_only=ON")
        rows = frr._load(c, "SPY", ca.FULL_START, ca.DEV_END, dates)
        spy = PriceSeries.from_bars("SPY", [(date.fromisoformat(r[0]), *r[1:6]) for r in rows])
        divs = frr._dividends(c, "SPY", spy, ca.FULL_START, ca.DEV_END)
        n, adj_eq_close, div_cash_nonzero, split_not_one = c.execute(
            """SELECT count(*), sum(b.adj_close = b.close), sum(b.div_cash != 0),
            sum(b.split_factor != 1)
            FROM ohlcv_daily b JOIN instrument i ON i.id=b.instrument_id
            WHERE i.symbol='SPY' AND b.source='massive' AND b.session_date BETWEEN ? AND ?""",
            (str(ca.FULL_START), str(ca.DEV_END)),
        ).fetchone()
        spy_split_rows = c.execute(
            "SELECT count(*) FROM split_event WHERE symbol='SPY'"
        ).fetchone()[0]
    assert spy.dates == dates and max(spy.dates) < ca.NEVER_ON_OR_AFTER
    for book in books.values():
        cached = book.data["SPY"]
        for name in ("open", "high", "low", "close", "volume"):
            assert np.array_equal(getattr(cached, name), getattr(spy, name)), (book.strategy, name)
        assert book.dividends["SPY"] == divs, book.strategy
    assert n == len(dates) == adj_eq_close and not div_cash_nonzero and not split_not_one
    ex_dates = [d.ex_date for d in divs]
    assert len(set(ex_dates)) == len(ex_dates) and all(d.symbol == "SPY" for d in divs)
    return {
        "spy_bars": n,
        "first_bar": str(dates[0]),
        "last_bar": str(dates[-1]),
        "adj_close_equals_close_rows": adj_eq_close,
        "div_cash_nonzero_rows": div_cash_nonzero or 0,
        "split_factor_not_one_rows": split_not_one or 0,
        "spy_dividend_rows": len(divs),
        "spy_dividend_first_ex_date": str(min(ex_dates)),
        "spy_dividend_last_ex_date": str(max(ex_dates)),
        "spy_split_rows": spy_split_rows,
        "cached_books_identical_to_database": True,
    }


def load_r3c_rows(path: Path, cost_label: str) -> dict[tuple[str, str, str, str], dict[str, str]]:
    """R3-C rows for the random-order, outright-rejection arm, keyed by cell and seed."""
    out: dict[tuple[str, str, str, str], dict[str, str]] = {}
    if not path.exists():
        return out
    with path.open() as fh:
        for r in csv.DictReader(fh):
            if r["cost_case"] == cost_label and r["arm"] == "random" and r["trim"] == "0":
                key = (r["book"], r["cap_set"], r["period"], r["order"])
                assert key not in out, key
                out[key] = r
    return out


# ----------------------------------------------------------------------------- SPY legs
def spy_legs(spy: PriceSeries, dividends: list[Dividend], first: int, last: int) -> dict[str, Any]:
    """SPY's daily total return in two legs for sessions ``first..last`` of ``spy``.

    r_on[t] = (open_t + dividend with ex-date t) / close_{t-1} - 1   (overnight)
    r_id[t] = close_t / open_t - 1                                  (intraday)

    The stored bars are split-adjusted but not dividend-adjusted, so the dividend is
    credited on its ex-date; (1 + r_on)(1 + r_id) is the total return of a holder who
    puts the dividend back into SPY at the ex-date open. The first session has no
    overnight leg: the account starts in cash and buys at that open."""
    assert 0 <= first < last < len(spy)
    dates = spy.dates[first : last + 1]
    assert max(dates) < ca.NEVER_ON_OR_AFTER
    open_ = np.asarray(spy.open[first : last + 1], dtype=float)
    close = np.asarray(spy.close[first : last + 1], dtype=float)
    per_share = {d.ex_date: float(d.amount) for d in dividends}
    assert len(per_share) == len(dividends)
    assert dates[0] not in per_share  # bought at the first open: no entitlement that day
    n = len(dates)
    div = np.array([per_share.get(d, 0.0) if k else 0.0 for k, d in enumerate(dates)])
    r_on = np.zeros(n)
    r_on[1:] = (open_[1:] + div[1:]) / close[:-1] - 1.0
    r_id = close / open_ - 1.0
    assert np.all(np.isfinite(r_on)) and np.all(np.isfinite(r_id))
    assert np.all(open_ > 0) and np.all(close > 0)
    # Growth of one dollar of SPY to the last close of the period: from the close of
    # session t (g_close) and from the open of session t (g_open).
    total = (1.0 + r_on) * (1.0 + r_id)
    g_close = np.concatenate((np.cumprod(total[::-1])[::-1][1:], [1.0]))
    g_open = (1.0 + r_id) * g_close
    return {
        "dates": dates,
        "open": open_,
        "close": close,
        "div": div,
        "r_on": r_on,
        "r_id": r_id,
        "g_open": g_open,
        "g_close": g_close,
        "ex_dates_in_period": int(np.count_nonzero(div)),
        "dividends_per_share_sum": float(div.sum()),
    }


def period_legs(book: ca.Book, period: str) -> dict[str, Any]:
    inputs = ca.period_inputs(book, period)
    spy: PriceSeries = inputs["spy"]  # IS: bars to 2022-02-10 only; OOS: the whole window
    first = inputs["first"]
    legs = spy_legs(spy, inputs["spy_dividends"], first, len(spy) - 1)
    start, end = ca.PERIODS[period]
    assert legs["dates"][0] == start and legs["dates"][-1] == end
    return legs


# ----------------------------------------------------------------------------- accounting
def reference_path(legs: dict[str, Any], c: float) -> np.ndarray:
    """Pre-registered reference: the whole $30,000 into SPY at the first open, one cost
    of ``c`` on that purchase, held with total return."""
    growth = np.cumprod((1.0 + legs["r_on"]) * (1.0 + legs["r_id"]))
    return K0 * (1.0 - c) * growth


def reference_account(legs: dict[str, Any], c: float) -> np.ndarray:
    """The reference as the overlay account of a book that never trades. Increments are
    taken against this path, so a stretch without trades differs by exactly zero."""
    idle = np.full(len(legs["r_on"]), K0)
    return overlay(idle, idle, legs, c)["V"]


def reference_share_count(legs: dict[str, Any], c: float) -> np.ndarray:
    """The same reference as a share count (an independent route to the same path):
    buy (30,000 - c x 30,000) / open on the first session, add n x d / open shares on
    each ex-date, value the shares at each close."""
    n = (K0 - c * K0) / legs["open"][0]
    out = np.empty(len(legs["open"]))
    for t in range(len(out)):
        if t:
            n += n * legs["div"][t] / legs["open"][t]
        out[t] = n * legs["close"][t]
    return out


def overlay(
    E: np.ndarray, C: np.ndarray, legs: dict[str, Any], c: float, *, zero_returns: bool = False
) -> dict[str, Any]:
    """The pre-registered overlay accounting.

    F_t = C_t - C_{t-1}                (flow at the open of session t; C_0 = 30,000)
    K_t = (K_{t-1}(1 + r_on,t) + F_t - cost_t)(1 + r_id,t),   K_0 = 30,000
    cost_t = c |F_t|, plus on the first session the reference's own one-time cost
             c x 30,000 for putting the starting cash into SPY (clarification 2)
    V_t = (E_t - C_t) + K_t
    """
    n = len(E)
    assert len(C) == n == len(legs["r_on"])
    r_on = np.zeros(n) if zero_returns else legs["r_on"]
    r_id = np.zeros(n) if zero_returns else legs["r_id"]
    floor_binds = int(np.count_nonzero(C < 0))
    Cf = np.maximum(C, 0.0)
    K = np.empty(n)
    F = np.empty(n)
    cost = np.empty(n)
    k_prev, c_prev = K0, K0
    for t in range(n):
        f = Cf[t] - c_prev
        ct = c * abs(f) + (c * K0 if t == 0 else 0.0)
        k_prev = (k_prev * (1.0 + r_on[t]) + f - ct) * (1.0 + r_id[t])
        K[t], F[t], cost[t] = k_prev, f, ct
        c_prev = Cf[t]
    V = (E - Cf) + K
    return {"K": K, "V": V, "F": F, "cost": cost, "floor_binds": floor_binds}


def overlay_share_ledger(
    E: np.ndarray, C: np.ndarray, legs: dict[str, Any], c: float
) -> np.ndarray:
    """Independent implementation of the same account as a SPY share ledger: every
    sleeve trade is done in shares at the session's open, dividends on the shares held
    into an ex-date buy more shares at that open. Returns V_t."""
    n_sh = 0.0
    c_prev = K0
    V = np.empty(len(E))
    for t in range(len(E)):
        o = legs["open"][t]
        if t == 0:
            n_sh = (K0 - c * K0) / o
        else:
            n_sh += n_sh * legs["div"][t] / o
        f = max(C[t], 0.0) - c_prev
        n_sh += (f - c * abs(f)) / o
        c_prev = max(C[t], 0.0)
        V[t] = (E[t] - c_prev) + n_sh * legs["close"][t]
    return V


def split_increment(
    E: np.ndarray, C: np.ndarray, flows: np.ndarray, legs: dict[str, Any], c: float
) -> tuple[float, float, float]:
    """Exact split of the final difference from the reference (descriptive only).

    V_T - R_T = remainder + exit_day + cost, with pay-ins D_t = max(F_t, 0), withdrawals
    W_t = max(-F_t, 0) and SPY's growth to the last close from the open (g_open) or the
    close (g_close) of session t:

      remainder = (E_T - C_T) + sum D_t g_close,t - sum W_t g_open,t
      exit_day  = sum D_t r_id,t g_close,t   SPY's open-to-close return on money the book
                  paid in that day; booked because every flow is taken at the open
      cost      = -c sum |F_t| g_open,t      (the opening purchase is in both paths)
    """
    dep, wd = np.maximum(flows, 0.0), np.maximum(-flows, 0.0)
    remainder = float((E[-1] - C[-1]) + np.sum(dep * legs["g_close"]) - np.sum(wd * legs["g_open"]))
    exit_day = float(np.sum(dep * legs["r_id"] * legs["g_close"]))
    cost = float(-c * np.sum(np.abs(flows) * legs["g_open"]))
    return remainder, exit_day, cost


def self_test_accounting() -> dict[str, Any]:
    """A three-session example worked by hand; it fixes the sign and timing of every term.

    SPY: day 1 open 100, close 110; day 2 ex-dividend 1.00, open 120, close 120; day 3
    open 120, close 132. So r_id = 10%, 0%, 10% and r_on = -, 10%, 0%.
    Book: idle on day 1; buys $10,000 of stock at the open of day 2 (flat that day);
    sells it for $10,500 on day 3. Sleeve cost 10 bps.

      K_1 = (30,000 - 30) x 1.10                          = 32,967.00
      K_2 = (32,967.00 x 1.10 - 10,000 - 10) x 1.00       = 26,253.70   V_2 = 36,253.70
      K_3 = (26,253.70 x 1.00 + 10,500 - 10.50) x 1.10    = 40,417.52   V_3 = 40,417.52
      reference R_3 = 29,970 x 1.331                      = 39,890.07
      V_3 - R_3 = 527.45 = -500.00 (remainder) + 1,050.00 (exit day) - 22.55 (cost)
    """
    dates = (date(2020, 1, 2), date(2020, 1, 3), date(2020, 1, 6))
    toy = PriceSeries(
        "TOY",
        dates,
        np.array([100.0, 120.0, 120.0]),
        np.array([110.0, 120.0, 132.0]),
        np.array([100.0, 120.0, 120.0]),
        np.array([110.0, 120.0, 132.0]),
        np.array([1.0, 1.0, 1.0]),
    )
    legs = spy_legs(
        toy, [Dividend("TOY", dates[1], dates[1], Decimal("1"), "worked example")], 0, 2
    )
    assert np.allclose(legs["r_on"], [0.0, 0.10, 0.0]) and np.allclose(
        legs["r_id"], [0.10, 0.0, 0.10]
    )
    E = np.array([30000.0, 30000.0, 30500.0])
    C = np.array([30000.0, 20000.0, 30500.0])
    c = 0.001
    acct = overlay(E, C, legs, c)
    assert np.allclose(acct["F"], [0.0, -10000.0, 10500.0], atol=1e-9)
    assert np.allclose(acct["K"], [32967.00, 26253.70, 40417.52], atol=1e-6)
    assert np.allclose(acct["V"], [32967.00, 36253.70, 40417.52], atol=1e-6)
    assert np.allclose(acct["cost"], [30.0, 10.0, 10.5], atol=1e-9)
    ref = reference_account(legs, c)
    assert np.allclose(ref, [32967.00, 36263.70, 39890.07], atol=1e-6)
    assert np.allclose(reference_path(legs, c), ref, atol=1e-6)
    assert np.allclose(reference_share_count(legs, c), ref, atol=1e-6)
    assert np.allclose(overlay_share_ledger(E, C, legs, c), acct["V"], atol=1e-6)
    parts = split_increment(E, C, acct["F"], legs, c)
    assert np.allclose(parts, [-500.0, 1050.0, -22.55], atol=1e-6)
    assert abs(sum(parts) - (acct["V"][-1] - ref[-1])) < 1e-6
    flat = overlay(E, C, legs, 0.0, zero_returns=True)
    assert np.allclose(flat["V"], E, atol=1e-9)
    return {
        "sessions": 3,
        "final_account_usd": 40417.52,
        "final_reference_usd": 39890.07,
        "passed": True,
    }


def path_metrics(values: np.ndarray, period: str) -> dict[str, float]:
    """R3-C's own metric function on a daily value path that starts from $30,000."""
    start, end = ca.PERIODS[period]
    em = frr.equity_metrics(
        [float(v) for v in values], initial_cash=ca.INITIAL_CASH, start=start, end=end
    )
    return {
        "net_return_pct": em["net_return_pct"],
        "cagr_pct": em["cagr_pct"],
        "max_drawdown_pct": em["max_drawdown_pct"],
        "sharpe": em["sharpe_annualised"],
    }


def daily_returns(values: np.ndarray) -> np.ndarray:
    return values / np.concatenate(([K0], values[:-1])) - 1.0


def year_segments(dates: tuple[date, ...]) -> list[tuple[str, int, int]]:
    """(label, first index, last index) of each calendar year inside the period."""
    segs: list[tuple[str, int, int]] = []
    start = 0
    for i in range(1, len(dates) + 1):
        if i == len(dates) or dates[i].year != dates[start].year:
            a, b = dates[start], dates[i - 1]
            label = str(a.year)
            if start == 0 and (a.month, a.day) > (1, 4):
                label += f" (from {a:%m-%d})"
            if i == len(dates) and (b.month, b.day) < (12, 28):
                label += f" (to {b:%m-%d})"
            segs.append((label, start, i - 1))
            start = i
    return segs


def segment_returns(values: np.ndarray, segs: list[tuple[str, int, int]]) -> list[float]:
    out = []
    for _, a, b in segs:
        prior = K0 if a == 0 else values[a - 1]
        out.append(float(values[b] / prior - 1.0) * 100.0)
    return out


# ----------------------------------------------------------------------------- SPY reconciliation
def spy_reconciliation(
    book: ca.Book, period: str, legs: dict[str, Any], c: float
) -> dict[str, Any]:
    """The pre-registered reference next to the R3-C figure, one convention at a time."""
    start, end = ca.PERIODS[period]
    inputs = ca.period_inputs(book, period)
    cm, spread = frr.COST_CASES[ca.BASE]
    bench = frr.spy_benchmark(
        inputs["spy"],
        dividends=inputs["spy_dividends"],
        initial_cash=ca.INITIAL_CASH,
        cost_model=cm,
        spread_bps=spread,
        start=start,
        end=end,
        from_index=inputs["first"],
    )
    penalty = (cm.slippage_bps + (spread / 2 if cm.half_spread_fill_penalty else 0)) / 10000
    assert abs(penalty - c) < 1e-15, "the sleeve's base cost is the library's base fill penalty"
    shares = bench["shares"]
    raw_close = float(inputs["spy"].close[-1])
    exit_cost = float(
        (Decimal(str(raw_close)) - sell_price(raw_close, penalty)) * shares
        + money(cm.commission(shares))
    )
    a_final = float(bench["final_value_usd"])
    a_no_exit = a_final + exit_cost

    # Fractional shares, one cost at the first open, no exit cost, dividends still credited
    # on the pay date (reinvested at that open, unpaid ones counted as receivable).
    dates = legs["dates"]
    n_sh = (K0 - c * K0) / legs["open"][0]
    receivable: list[tuple[date, float]] = []
    for t, day in enumerate(dates):
        if t and legs["div"][t]:
            pay = next(d.pay_date for d in inputs["spy_dividends"] if d.ex_date == day)
            receivable.append((pay, n_sh * legs["div"][t]))
        paid = sum(a for p, a in receivable if p <= day)
        receivable = [r for r in receivable if r[0] > day]
        if paid:
            n_sh += paid / legs["open"][t]
    frac_pay_final = n_sh * legs["close"][-1] + sum(a for _, a in receivable)
    ref_final = float(reference_account(legs, c)[-1])

    def net(v: float) -> float:
        return (v / K0 - 1.0) * 100.0

    return {
        "r3c_benchmark": {
            "final_usd": a_final,
            "net_return_pct": bench["net_return_pct"],
            "cagr_pct": bench["cagr_pct"],
            "max_drawdown_pct": bench["max_drawdown_pct"],
            "sharpe": bench["sharpe_annualised"],
            "shares": shares,
            "entry_price_usd": bench["entry_price_usd"],
            "residual_cash_usd": bench["residual_cash_usd"],
            "dividends_received_usd": bench["dividends_received_usd"],
            "dividend_reinvestment_buys": bench["dividend_reinvestment_buys"],
            "modeled_costs_usd": bench["modeled_costs_usd"],
        },
        "bridge": [
            {
                "step": "R3-C figure: whole shares, 5.5 bps on every buy, dividends paid and reinvested on the pay date, valued net of a 5.5 bps exit cost",
                "final_usd": a_final,
                "net_return_pct": net(a_final),
            },
            {
                "step": "the same without the exit cost",
                "final_usd": a_no_exit,
                "net_return_pct": net(a_no_exit),
            },
            {
                "step": "fractional shares with no idle cash, one 5.5 bps cost on the first purchase only, dividends still on the pay date",
                "final_usd": frac_pay_final,
                "net_return_pct": net(frac_pay_final),
            },
            {
                "step": "pre-registered reference: dividends credited on the ex-date and reinvested at that open",
                "final_usd": ref_final,
                "net_return_pct": net(ref_final),
            },
        ],
        "exit_cost_usd": exit_cost,
    }


# ----------------------------------------------------------------------------- replays
def run_replays(
    books: dict[str, ca.Book],
    caps: dict[str, ca.Caps],
    cost_label: str,
    cells: list[tuple[str, str]],
    r3c_rows: dict[tuple[str, str, str, str], dict[str, str]],
    *,
    require_r3c: bool,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Re-run the 40 random-order, outright-rejection replays of each (book, cap set)
    in both periods, compare every run with its R3-C row and keep its daily marks."""
    cm, spread = frr.COST_CASES[cost_label]
    runs: list[dict[str, Any]] = []
    cell_report: list[dict[str, Any]] = []
    started = time.perf_counter()
    for strategy, cap_name in cells:
        book = books[strategy]
        for period in PERIOD_NAMES:
            first = 0 if period == "IS" else book.n_is
            matched_required = matched_all = compared = 0
            mismatches: list[dict[str, Any]] = []
            for i in range(ca.N_SEEDS):
                seed = ca.seed_for(i)
                result, stats = ca.local_replay(
                    book, period, caps[cap_name], cm, spread, order=("random", seed), trim=False
                )
                row = ca.run_metrics(book, period, result, stats)
                marks = result.marks[first:]
                if first:
                    before = result.marks[first - 1]
                    assert Decimal(before["cash_usd"]) == ca.INITIAL_CASH
                    assert Decimal(before["net_liquidation_usd"]) == ca.INITIAL_CASH
                assert marks[0]["day"] == str(ca.PERIODS[period][0])
                assert marks[-1]["day"] == str(ca.PERIODS[period][1])
                E = np.array([float(m["net_liquidation_usd"]) for m in marks])
                C = np.array([float(m["cash_usd"]) for m in marks])
                # Where the book's pay-ins come from (context for the exit-day part).
                paid_in = dict.fromkeys(EXIT_KINDS, 0.0)
                for f in result.fills:
                    if f["side"] == "sell":
                        paid_in[f["reason"]] += float(
                            Decimal(f["price"]) * f["shares"] - Decimal(f["commission"])
                        )
                paid_in["dividend"] = float(
                    sum(
                        Decimal(e["amount_usd"])
                        for e in result.corporate_events
                        if e["kind"] == "dividend_payment"
                    )
                )
                bought = float(
                    sum(
                        Decimal(f["price"]) * f["shares"] + Decimal(f["commission"])
                        for f in result.fills
                        if f["side"] == "buy"
                    )
                )
                # The book's cash is exactly its fills and dividend payments.
                assert abs(K0 + sum(paid_in.values()) - bought - C[-1]) < CENT_TOL
                assert str(Decimal(marks[-1]["net_liquidation_usd"])) == row["final_equity_usd"]
                theirs = r3c_rows.get((strategy, cap_name, period, f"seed{seed}"))
                if theirs is None:
                    if require_r3c:
                        raise SystemExit(
                            f"no R3-C row for {strategy} {cap_name} {period} seed{seed}"
                        )
                else:
                    compared += 1
                    same = {}
                    for k in ALL_FIELDS:
                        if k in FLOAT_FIELDS:
                            same[k] = (
                                theirs[k] in ("", "None")
                                if row[k] is None
                                else float(theirs[k]) == row[k]
                            )
                        elif k in INT_FIELDS:
                            same[k] = int(theirs[k]) == row[k]
                        else:
                            same[k] = theirs[k] == str(row[k])
                    ok_required = all(same[k] for k in REQUIRED_FIELDS)
                    matched_required += ok_required
                    matched_all += all(same.values())
                    if not all(same.values()):
                        mismatches.append(
                            {
                                "seed": seed,
                                "fields": [k for k, v in same.items() if not v],
                                "mine": {k: row[k] for k in REQUIRED_FIELDS},
                                "r3c": {k: theirs[k] for k in REQUIRED_FIELDS},
                            }
                        )
                runs.append(
                    {
                        "book": strategy,
                        "cap_set": cap_name,
                        "period": period,
                        "cost_case": cost_label,
                        "seed": seed,
                        "row": row,
                        "E": E,
                        "C": C,
                        "paid_in": paid_in,
                        "bought": bought,
                    }
                )
            cell_report.append(
                {
                    "book": strategy,
                    "cap_set": cap_name,
                    "period": period,
                    "cost_case": cost_label,
                    "replays": ca.N_SEEDS,
                    "compared_with_r3c": compared,
                    "matched_final_equity_entries_net_return": matched_required,
                    "matched_all_fields": matched_all,
                    "mismatches": mismatches,
                }
            )
            print(
                f"  {strategy:34s} {cap_name:9s} {period:3s} {cost_label}: "
                f"{matched_required}/{compared} reproduce R3-C "
                f"({time.perf_counter() - started:.0f}s)",
                flush=True,
            )
    compared = sum(c["compared_with_r3c"] for c in cell_report)
    report = {
        "cost_case": cost_label,
        "replays": len(runs),
        "compared_with_r3c": compared,
        "matched_final_equity_entries_net_return": sum(
            c["matched_final_equity_entries_net_return"] for c in cell_report
        ),
        "matched_all_fields": sum(c["matched_all_fields"] for c in cell_report),
        "fields_required": list(REQUIRED_FIELDS),
        "fields_all": list(ALL_FIELDS),
        "cells": cell_report,
        "seconds": round(time.perf_counter() - started, 1),
    }
    report["passed"] = (
        report["matched_final_equity_entries_net_return"] == compared
        and report["matched_all_fields"] == compared
        and (compared == len(runs) or not require_r3c)
    )
    return runs, report


# ----------------------------------------------------------------------------- analysis
def _pct(values: list[float], q: float) -> float:
    return ca._pct(values, q)  # numpy linear interpolation, as R3-C


def _band(values: list[float]) -> dict[str, float]:
    return {
        "p5": _pct(values, 5),
        "p50": _pct(values, 50),
        "p95": _pct(values, 95),
        "min": float(min(values)),
        "max": float(max(values)),
    }


def account_rows(
    runs: list[dict[str, Any]], legs_by_period: dict[str, dict[str, Any]], c: float
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """Overlay account, increments and per-replay unit tests for every run."""
    refs: dict[str, dict[str, Any]] = {}
    for period, legs in legs_by_period.items():
        path = reference_account(legs, c)
        assert float(np.max(np.abs(path - reference_path(legs, c)))) < CENT_TOL
        segs = year_segments(legs["dates"])
        refs[period] = {
            "path": path,
            "metrics": path_metrics(path, period),
            "segments": segs,
            "segment_returns": segment_returns(path, segs),
            "daily": daily_returns(path),
        }
    rows: list[dict[str, Any]] = []
    years: list[dict[str, Any]] = []
    unit_i_max = ledger_max = 0.0
    floor_binds = 0
    for run in runs:
        period = run["period"]
        legs = legs_by_period[period]
        ref = refs[period]
        E, C = run["E"], run["C"]
        acct = overlay(E, C, legs, c)
        K, V = acct["K"], acct["V"]
        floor_binds += acct["floor_binds"]
        # Unit test (i): zero SPY returns and zero sleeve cost give back the book itself.
        flat = overlay(E, C, legs, 0.0, zero_returns=True)
        dev_i = float(np.max(np.abs(flat["V"] - E)))
        assert dev_i < CENT_TOL, (run["book"], run["cap_set"], period, run["seed"], dev_i)
        unit_i_max = max(unit_i_max, dev_i)
        # Independent share-ledger implementation of the same account.
        dev_l = float(np.max(np.abs(overlay_share_ledger(E, C, legs, c) - V)))
        assert dev_l < CENT_TOL, (run["book"], run["cap_set"], period, run["seed"], dev_l)
        ledger_max = max(ledger_max, dev_l)
        assert abs(float(np.sum(acct["F"])) - (C[-1] - K0)) < 1e-6
        assert np.all(V > 0)
        dep, wd = np.maximum(acct["F"], 0.0), np.maximum(-acct["F"], 0.0)
        part_a, part_b, part_c = split_increment(E, C, acct["F"], legs, c)
        gap = float(V[-1] - ref["path"][-1])
        assert abs(part_a + part_b + part_c - gap) < 1e-6, (part_a, part_b, part_c, gap)

        m = path_metrics(V, period)
        rm = ref["metrics"]
        short = K < 0
        shortfall_usd = float(np.max(-K[short])) if short.any() else 0.0
        shortfall_pct = float(np.max(-K[short] / V[short]) * 100.0) if short.any() else 0.0
        worst = int(np.argmax(np.where(short, -K / V, -np.inf))) if short.any() else None
        active = daily_returns(V) - ref["daily"]
        sa = run["row"]
        rows.append(
            {
                "book": run["book"],
                "cap_set": run["cap_set"],
                "period": period,
                "cost_case": run["cost_case"],
                "order": f"seed{run['seed']}",
                "sleeve_cost_bps": c * 1e4,
                "standalone_final_usd": sa["final_equity_usd"],
                "standalone_net_return_pct": sa["net_return_pct"],
                "standalone_cagr_pct": sa["cagr_pct"],
                "standalone_max_drawdown_pct": sa["max_drawdown_pct"],
                "standalone_sharpe": sa["sharpe"],
                "standalone_mean_exposure_pct": sa["mean_exposure_pct"],
                "standalone_dividend_income_usd": sa["dividend_income_usd"],
                "entries": sa["entries"],
                "account_final_usd": float(V[-1]),
                "account_net_return_pct": m["net_return_pct"],
                "account_cagr_pct": m["cagr_pct"],
                "account_max_drawdown_pct": m["max_drawdown_pct"],
                "account_sharpe": m["sharpe"],
                "spy_net_return_pct": rm["net_return_pct"],
                "spy_cagr_pct": rm["cagr_pct"],
                "spy_max_drawdown_pct": rm["max_drawdown_pct"],
                "spy_sharpe": rm["sharpe"],
                "inc_net_return_pts": m["net_return_pct"] - rm["net_return_pct"],
                "inc_cagr_pts": m["cagr_pct"] - rm["cagr_pct"],
                "inc_sharpe": m["sharpe"] - rm["sharpe"],
                "inc_max_drawdown_pts": m["max_drawdown_pct"] - rm["max_drawdown_pct"],
                "mean_sleeve_share_pct": float(np.mean(K / V) * 100.0),
                "min_sleeve_usd": float(np.min(K)),
                "shortfall_sessions": int(np.count_nonzero(short)),
                "max_shortfall_usd": shortfall_usd,
                "max_shortfall_pct_of_account": shortfall_pct,
                "max_shortfall_day": str(legs["dates"][worst]) if worst is not None else "",
                "first_session_flow_usd": float(acct["F"][0]),
                "sleeve_turnover_usd": float(np.sum(np.abs(acct["F"]))),
                "sleeve_costs_usd": float(np.sum(acct["cost"])),
                "part_a_pts": part_a / K0 * 100.0,
                "part_b_pts": part_b / K0 * 100.0,
                "part_cost_pts": part_c / K0 * 100.0,
                "net_deposits_usd": float(dep.sum()),
                "net_withdrawals_usd": float(wd.sum()),
                "gross_bought_usd": run["bought"],
                **{f"paid_in_{k}_usd": run["paid_in"][k] for k in EXIT_KINDS},
                "deposits_x_spy_intraday_usd": float(np.sum(dep * legs["r_id"])),
                "withdrawals_x_spy_intraday_usd": float(np.sum(wd * legs["r_id"])),
                "mean_active_bps": float(np.mean(active) * 1e4),
                "se_active_bps": float(np.std(active, ddof=1) / math.sqrt(len(active)) * 1e4),
                "unit_i_max_abs_usd": dev_i,
                "share_ledger_max_abs_usd": dev_l,
            }
        )
        seg_acct = segment_returns(V, ref["segments"])
        for (label, _, _), a, r in zip(
            ref["segments"], seg_acct, ref["segment_returns"], strict=True
        ):
            years.append(
                {
                    "book": run["book"],
                    "cap_set": run["cap_set"],
                    "period": period,
                    "cost_case": run["cost_case"],
                    "order": f"seed{run['seed']}",
                    "year": label,
                    "account_return_pct": a,
                    "spy_return_pct": r,
                    "inc_pts": a - r,
                }
            )
        run["V"], run["active"] = V, active
    checks = {
        "unit_i_zero_returns_zero_cost_max_abs_usd": unit_i_max,
        "share_ledger_vs_recursion_max_abs_usd": ledger_max,
        "replays_checked": len(runs),
        "sessions_with_negative_book_cash": floor_binds,
    }
    return rows, years, {"refs": refs, "checks": checks}


def summarise_cells(
    rows: list[dict[str, Any]], runs: list[dict[str, Any]], years: list[dict[str, Any]]
) -> dict[str, Any]:
    """Cell tables, the pre-registered decision rule and the descriptive splits."""
    by_cell: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for r in rows:
        by_cell.setdefault((r["book"], r["cap_set"], r["period"]), []).append(r)
    active_by_cell: dict[tuple[str, str, str], list[np.ndarray]] = {}
    for run in runs:
        active_by_cell.setdefault((run["book"], run["cap_set"], run["period"]), []).append(
            run["active"]
        )
    year_by_cell: dict[tuple[str, str, str], dict[str, list[dict[str, Any]]]] = {}
    for y in years:
        year_by_cell.setdefault((y["book"], y["cap_set"], y["period"]), {}).setdefault(
            y["year"], []
        ).append(y)

    cells: list[dict[str, Any]] = []
    verdicts: list[dict[str, Any]] = []
    order = [(b, cap) for b, _, _ in ca.BOOKS for cap in CAP_SETS]
    for book, cap in order:
        if (book, cap, "IS") not in by_cell:
            continue
        passes = {}
        for period in PERIOD_NAMES:
            rs = sorted(by_cell[(book, cap, period)], key=lambda r: r["order"])
            assert len(rs) == ca.N_SEEDS and len({r["order"] for r in rs}) == ca.N_SEEDS
            spy = {
                k: rs[0][f"spy_{k}"]
                for k in ("net_return_pct", "cagr_pct", "max_drawdown_pct", "sharpe")
            }
            assert all(r["spy_net_return_pct"] == spy["net_return_pct"] for r in rs)
            inc_net = [r["inc_net_return_pts"] for r in rs]
            inc_sharpe = [r["inc_sharpe"] for r in rs]
            median_dd = _pct([r["account_max_drawdown_pct"] for r in rs], 50)
            positive = sum(v > 0 for v in inc_net)
            max_short_pct = max(r["max_shortfall_pct_of_account"] for r in rs)
            worst = max(rs, key=lambda r: r["max_shortfall_pct_of_account"])
            cond = {
                "median_net_increment_positive": _pct(inc_net, 50) > 0,
                "median_sharpe_increment_positive": _pct(inc_sharpe, 50) > 0,
                "at_least_36_orders_positive": positive >= MIN_POSITIVE_ORDERS,
                "median_max_dd_within_2_pts_of_spy": median_dd - spy["max_drawdown_pct"]
                <= DD_TOLERANCE_PTS,
                "implementable_as_stated": max_short_pct <= SHORTFALL_LIMIT_PCT,
            }
            passes[period] = all(cond.values())
            series = np.mean(np.vstack(active_by_cell[(book, cap, period)]), axis=0)
            se = float(np.std(series, ddof=1) / math.sqrt(len(series)))
            per_order_mean = [r["mean_active_bps"] for r in rs]
            year_rows = []
            for label, ys in year_by_cell[(book, cap, period)].items():
                assert len(ys) == ca.N_SEEDS
                year_rows.append(
                    {
                        "year": label,
                        "spy_return_pct": ys[0]["spy_return_pct"],
                        "median_account_return_pct": _pct(
                            [y["account_return_pct"] for y in ys], 50
                        ),
                        "median_inc_pts": _pct([y["inc_pts"] for y in ys], 50),
                        "orders_positive": sum(y["inc_pts"] > 0 for y in ys),
                    }
                )
            cells.append(
                {
                    "book": book,
                    "cap_set": cap,
                    "period": period,
                    "cost_case": rs[0]["cost_case"],
                    "n": len(rs),
                    "spy": spy,
                    "standalone_net_return_pct": _band(
                        [r["standalone_net_return_pct"] for r in rs]
                    ),
                    "standalone_sharpe_p50": _pct([r["standalone_sharpe"] for r in rs], 50),
                    "standalone_cagr_pct_p50": _pct([r["standalone_cagr_pct"] for r in rs], 50),
                    "standalone_max_drawdown_pct_p50": _pct(
                        [r["standalone_max_drawdown_pct"] for r in rs], 50
                    ),
                    "standalone_mean_exposure_pct_p50": _pct(
                        [r["standalone_mean_exposure_pct"] for r in rs], 50
                    ),
                    "standalone_dividend_income_usd_p50": _pct(
                        [float(r["standalone_dividend_income_usd"]) for r in rs], 50
                    ),
                    "entries_p50": _pct([r["entries"] for r in rs], 50),
                    "account_net_return_pct": _band([r["account_net_return_pct"] for r in rs]),
                    "account_cagr_pct_p50": _pct([r["account_cagr_pct"] for r in rs], 50),
                    "account_sharpe": _band([r["account_sharpe"] for r in rs]),
                    "account_max_drawdown_pct_p50": median_dd,
                    "inc_net_return_pts": _band(inc_net),
                    "inc_cagr_pts_p50": _pct([r["inc_cagr_pts"] for r in rs], 50),
                    "inc_sharpe": _band(inc_sharpe),
                    "inc_max_drawdown_pts_p50": median_dd - spy["max_drawdown_pct"],
                    "orders_positive_net_increment": positive,
                    "orders_positive_sharpe_increment": sum(v > 0 for v in inc_sharpe),
                    "mean_sleeve_share_pct": float(
                        np.mean([r["mean_sleeve_share_pct"] for r in rs])
                    ),
                    "min_sleeve_usd": min(r["min_sleeve_usd"] for r in rs),
                    "shortfall_sessions": sum(r["shortfall_sessions"] for r in rs),
                    "orders_with_shortfall": sum(r["shortfall_sessions"] > 0 for r in rs),
                    "max_shortfall_usd": max(r["max_shortfall_usd"] for r in rs),
                    "max_shortfall_pct_of_account": max_short_pct,
                    "max_shortfall_day": worst["max_shortfall_day"],
                    "max_shortfall_order": worst["order"] if max_short_pct > 0 else "",
                    "max_abs_first_session_flow_usd": max(
                        abs(r["first_session_flow_usd"]) for r in rs
                    ),
                    "median_sleeve_costs_usd": _pct([r["sleeve_costs_usd"] for r in rs], 50),
                    "median_sleeve_turnover_usd": _pct([r["sleeve_turnover_usd"] for r in rs], 50),
                    "parts": {
                        "mean_inc_net_return_pts": float(np.mean(inc_net)),
                        "mean_a_pts": float(np.mean([r["part_a_pts"] for r in rs])),
                        "mean_b_pts": float(np.mean([r["part_b_pts"] for r in rs])),
                        "mean_cost_pts": float(np.mean([r["part_cost_pts"] for r in rs])),
                        "a_pts": _band([r["part_a_pts"] for r in rs]),
                        "b_pts": _band([r["part_b_pts"] for r in rs]),
                        "cost_pts": _band([r["part_cost_pts"] for r in rs]),
                        "orders_positive_a": sum(r["part_a_pts"] > 0 for r in rs),
                        "paid_in_share_pct": {
                            k: sum(r[f"paid_in_{k}_usd"] for r in rs)
                            / sum(r[f"paid_in_{j}_usd"] for r in rs for j in EXIT_KINDS)
                            * 100.0
                            for k in EXIT_KINDS
                        },
                        "spy_intraday_bps_on_net_deposit_days": sum(
                            r["deposits_x_spy_intraday_usd"] for r in rs
                        )
                        / sum(r["net_deposits_usd"] for r in rs)
                        * 1e4,
                        "spy_intraday_bps_on_net_withdrawal_days": sum(
                            r["withdrawals_x_spy_intraday_usd"] for r in rs
                        )
                        / sum(r["net_withdrawals_usd"] for r in rs)
                        * 1e4,
                    },
                    "conditions": cond,
                    "period_pass": passes[period],
                    "active": {
                        "sessions": len(series),
                        "mean_bps": float(np.mean(series) * 1e4),
                        "se_bps": se * 1e4,
                        "t": float(np.mean(series) / se) if se > 0 else None,
                        "annualised_pct": float(np.mean(series) * 252 * 100.0),
                        "per_order_mean_bps": _band(per_order_mean),
                        "per_order_se_bps_p50": _pct([r["se_active_bps"] for r in rs], 50),
                        "orders_positive_mean": sum(v > 0 for v in per_order_mean),
                    },
                    "by_year": year_rows,
                }
            )
        mine = [c for c in cells if (c["book"], c["cap_set"]) == (book, cap)]
        verdicts.append(
            {
                "book": book,
                "cap_set": cap,
                "IS": passes["IS"],
                "OOS": passes["OOS"],
                "implementable_as_stated": all(
                    c["conditions"]["implementable_as_stated"] for c in mine
                ),
                "account_level_candidate": passes["IS"] and passes["OOS"],
            }
        )
    return {"cells": cells, "verdicts": verdicts}


# ----------------------------------------------------------------------------- outputs
ROW_FIELDS = [
    "book",
    "cap_set",
    "period",
    "cost_case",
    "order",
    "sleeve_cost_bps",
    "standalone_final_usd",
    "standalone_net_return_pct",
    "standalone_cagr_pct",
    "standalone_max_drawdown_pct",
    "standalone_sharpe",
    "standalone_mean_exposure_pct",
    "standalone_dividend_income_usd",
    "entries",
    "account_final_usd",
    "account_net_return_pct",
    "account_cagr_pct",
    "account_max_drawdown_pct",
    "account_sharpe",
    "spy_net_return_pct",
    "spy_cagr_pct",
    "spy_max_drawdown_pct",
    "spy_sharpe",
    "inc_net_return_pts",
    "inc_cagr_pts",
    "inc_sharpe",
    "inc_max_drawdown_pts",
    "mean_sleeve_share_pct",
    "min_sleeve_usd",
    "shortfall_sessions",
    "max_shortfall_usd",
    "max_shortfall_pct_of_account",
    "max_shortfall_day",
    "first_session_flow_usd",
    "sleeve_turnover_usd",
    "sleeve_costs_usd",
    "part_a_pts",
    "part_b_pts",
    "part_cost_pts",
    "net_deposits_usd",
    "net_withdrawals_usd",
    "gross_bought_usd",
    *(f"paid_in_{k}_usd" for k in EXIT_KINDS),
    "deposits_x_spy_intraday_usd",
    "withdrawals_x_spy_intraday_usd",
    "mean_active_bps",
    "se_active_bps",
    "unit_i_max_abs_usd",
    "share_ledger_max_abs_usd",
]
YEAR_FIELDS = [
    "book",
    "cap_set",
    "period",
    "cost_case",
    "order",
    "year",
    "account_return_pct",
    "spy_return_pct",
    "inc_pts",
]


def write_csv(path: Path, fields: list[str], rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for r in rows:
            writer.writerow({k: r[k] for k in fields})


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git(*args: str) -> str:
    try:
        return subprocess.run(  # noqa: S603 - fixed argv, read-only metadata
            ["git", "-C", str(Path(__file__).resolve().parents[2]), *args],  # noqa: S607
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except Exception:
        return "unknown"


def provenance() -> dict[str, Any]:
    """Hashes of this script and of the imported R3 scripts, and whether each imported
    file is byte-identical to the blob committed at HEAD (pure reads; no git state change)."""
    root = Path(__file__).resolve().parents[2]
    out: dict[str, Any] = {"git_head": _git("rev-parse", "HEAD"), "files": {}}
    for rel in (
        "scripts/r4/core_overlay.py",
        "scripts/r3/capacity_admission.py",
        "scripts/funded_replay_report.py",
    ):
        path = root / rel
        entry: dict[str, Any] = {"sha256": _sha256(path)}
        if rel != "scripts/r4/core_overlay.py":
            committed = _git("rev-parse", f"HEAD:{rel}")
            working = _git("hash-object", str(path))
            entry["identical_to_head_blob"] = committed == working != "unknown"
        out["files"][rel] = entry
    return out


# ----------------------------------------------------------------------------- stage: run
def stage_run(out: Path, db: Path) -> int:
    started = time.perf_counter()
    worked_example = self_test_accounting()
    print("worked three-session example of the accounting: passed", flush=True)
    r3c_out = ca.default_out()
    identity_r3c = json.loads((r3c_out / "identity.json").read_text())
    if not identity_r3c["passed"]:
        raise SystemExit("R3-C identity check has not passed; nothing may be run")
    caps_list = [ca.Caps(**c) for c in identity_r3c["cap_sets"]]
    assert caps_list == ca.read_operating_caps(db), "cap sets differ from the scratch copy"
    caps = {c.name: c for c in caps_list}
    assert tuple(caps) == CAP_SETS

    books = load_books(r3c_out / "cache")
    data_check = check_spy_against_db(db, books)
    print("SPY in the cached books equals the scratch copy:", json.dumps(data_check), flush=True)
    all_cells = [(b, cap) for b, _, _ in ca.BOOKS for cap in CAP_SETS]

    # ---- identity check A
    print("== identity check A: 640 base-cost replays against R3-C runs.csv", flush=True)
    r3c_rows = load_r3c_rows(r3c_out / "runs.csv", ca.BASE)
    assert len(r3c_rows) == len(all_cells) * len(PERIOD_NAMES) * ca.N_SEEDS == 640
    runs, identity_a = run_replays(books, caps, ca.BASE, all_cells, r3c_rows, require_r3c=True)
    identity_a["r3c_runs_csv"] = str(r3c_out / "runs.csv")
    identity_a["r3c_runs_csv_sha256"] = _sha256(r3c_out / "runs.csv")
    if not identity_a["passed"] or identity_a["replays"] != 640:
        (out / "identity_a_FAILED.json").write_text(json.dumps(identity_a, indent=2) + "\n")
        print("IDENTITY CHECK A FAILED - study stops here", flush=True)
        return 2
    print(
        f"identity check A passed: {identity_a['matched_all_fields']}/640 replays reproduce "
        f"every compared field ({identity_a['seconds']}s)",
        flush=True,
    )
    np.savez_compressed(
        out / "marks_base.npz",
        **{
            f"{r['book']}|{r['cap_set']}|{r['period']}|seed{r['seed']}|{k}": r[k]
            for r in runs
            for k in ("E", "C")
        },
    )

    # ---- SPY legs (identical across books: asserted)
    first_book = books[ca.BOOKS[0][0]]
    legs = {p: period_legs(first_book, p) for p in PERIOD_NAMES}
    for book in books.values():
        for p in PERIOD_NAMES:
            other = period_legs(book, p)
            assert other["dates"] == legs[p]["dates"]
            assert np.array_equal(other["r_on"], legs[p]["r_on"])
            assert np.array_equal(other["r_id"], legs[p]["r_id"])
    assert max(legs["OOS"]["dates"]) == ca.DEV_END < ca.NEVER_ON_OR_AFTER
    assert legs["IS"]["dates"][-1] == ca.IS_END and legs["OOS"]["dates"][0] == ca.OOS_START

    with (out / "spy_legs.csv").open("w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["period", "session", "open", "close", "dividend_ex_date", "r_on", "r_id"])
        for p in PERIOD_NAMES:
            lg = legs[p]
            for k, day in enumerate(lg["dates"]):
                writer.writerow(
                    [
                        p,
                        day,
                        lg["open"][k],
                        lg["close"][k],
                        lg["div"][k],
                        lg["r_on"][k],
                        lg["r_id"][k],
                    ]
                )

    # ---- identity check B
    print("== identity check B: accounting unit tests", flush=True)
    c_base = SLEEVE_COST[ca.BASE]
    unit_ii: dict[str, Any] = {}
    reconciliation: dict[str, Any] = {}
    for p in PERIOD_NAMES:
        n = len(legs[p]["dates"])
        idle = np.full(n, K0)
        no_trades = overlay(idle, idle, legs[p], c_base)
        ref_recursion = reference_account(legs[p], c_base)
        assert np.array_equal(no_trades["V"], ref_recursion)
        ref_shares = reference_share_count(legs[p], c_base)
        dev_ref = float(np.max(np.abs(no_trades["V"] - ref_shares)))
        dev_paths = float(np.max(np.abs(reference_path(legs[p], c_base) - ref_shares)))
        assert dev_ref < CENT_TOL and dev_paths < CENT_TOL, (p, dev_ref, dev_paths)
        assert not np.any(no_trades["F"]) and abs(no_trades["cost"].sum() - c_base * K0) < 1e-12
        unit_ii[p] = {
            "sessions": n,
            "no_trade_book_vs_share_count_reference_max_abs_usd": dev_ref,
            "compounded_reference_vs_share_count_max_abs_usd": dev_paths,
            "reference_final_usd": float(ref_recursion[-1]),
            "passed": True,
        }
        reconciliation[p] = spy_reconciliation(first_book, p, legs[p], c_base)
        r3c_spy = identity_r3c["books"][0]["spy"][ca.BASE][p]
        mine = ca.spy_reference(first_book, p, ca.BASE)
        assert mine == r3c_spy, (p, mine, r3c_spy)
        assert reconciliation[p]["r3c_benchmark"]["net_return_pct"] == r3c_spy["net_return_pct"]
        assert round(r3c_spy["net_return_pct"], 2) == R3C_SPY_NET[p]
        reconciliation[p]["r3c_figure_reproduced"] = True
        reconciliation[p]["reference"] = {
            **path_metrics(ref_recursion, p),
            "final_usd": float(ref_recursion[-1]),
        }
        reconciliation[p]["difference_pts"] = (
            reconciliation[p]["reference"]["net_return_pct"] - r3c_spy["net_return_pct"]
        )

    rows, years, extra = account_rows(runs, legs, c_base)
    checks = extra["checks"]
    assert checks["sessions_with_negative_book_cash"] == 0
    print(
        f"unit test (i): max |V - E| with zero returns and zero cost = "
        f"{checks['unit_i_zero_returns_zero_cost_max_abs_usd']:.3e} USD over 640 replays; "
        f"share ledger vs recursion max = {checks['share_ledger_vs_recursion_max_abs_usd']:.3e} USD",
        flush=True,
    )
    for p in PERIOD_NAMES:
        print(
            f"unit test (ii) {p}: no-trade book vs share-count reference max "
            f"{unit_ii[p]['no_trade_book_vs_share_count_reference_max_abs_usd']:.3e} USD; "
            f"(iii) reference {reconciliation[p]['reference']['net_return_pct']:+.2f}% vs "
            f"R3-C {identity_r3c['books'][0]['spy'][ca.BASE][p]['net_return_pct']:+.2f}%",
            flush=True,
        )

    # ---- metrics, increments, decision rule
    analysis = summarise_cells(rows, runs, years)
    candidates = [v for v in analysis["verdicts"] if v["account_level_candidate"]]
    print("verdicts:", flush=True)
    for v in analysis["verdicts"]:
        print(
            f"  {ca.SHORT[v['book']]:15s} {v['cap_set']:9s} IS {'pass' if v['IS'] else 'fail'} "
            f"OOS {'pass' if v['OOS'] else 'fail'} -> "
            f"{'CANDIDATE' if v['account_level_candidate'] else 'no'}",
            flush=True,
        )

    # ---- stress costs: qualifying cells only
    stress: dict[str, Any] | None = None
    stress_rows: list[dict[str, Any]] = []
    stress_years: list[dict[str, Any]] = []
    if candidates:
        print(f"== stress costs for {len(candidates)} qualifying cell(s)", flush=True)
        if not identity_r3c["stress_passed"]:
            raise SystemExit("R3-C stress-cost identity did not pass; stress table not produced")
        cells = [(v["book"], v["cap_set"]) for v in candidates]
        r3c_stress = load_r3c_rows(r3c_out / "stress_runs.csv", ca.STRESS)
        s_runs, s_identity = run_replays(
            books, caps, ca.STRESS, cells, r3c_stress, require_r3c=False
        )
        if not s_identity["passed"]:
            (out / "identity_a_stress_FAILED.json").write_text(
                json.dumps(s_identity, indent=2) + "\n"
            )
            print("STRESS IDENTITY CHECK FAILED - study stops here", flush=True)
            return 2
        stress_rows, stress_years, s_extra = account_rows(s_runs, legs, SLEEVE_COST[ca.STRESS])
        s_analysis = summarise_cells(stress_rows, s_runs, stress_years)
        stress = {
            "cost_case": ca.STRESS,
            "sleeve_cost_bps": SLEEVE_COST[ca.STRESS] * 1e4,
            "reference_cost_bps": SLEEVE_COST[ca.STRESS] * 1e4,
            "identity": s_identity,
            "checks": s_extra["checks"],
            "reference": {
                p: {
                    **s_extra["refs"][p]["metrics"],
                    "final_usd": float(s_extra["refs"][p]["path"][-1]),
                }
                for p in PERIOD_NAMES
            },
            "cells": s_analysis["cells"],
            "verdicts": [
                {
                    **v,
                    "standing": "holds at stress costs"
                    if v["account_level_candidate"]
                    else "base costs only",
                }
                for v in s_analysis["verdicts"]
            ],
        }

    write_csv(out / "replays.csv", ROW_FIELDS, rows + stress_rows)
    write_csv(out / "replays_by_year.csv", YEAR_FIELDS, years + stress_years)

    summary = {
        "study": "R4-O index-core overlay increment",
        "preregistration": PREREGISTRATION,
        "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "provenance": provenance(),
        "database": str(db),
        "periods": {k: [str(a), str(b)] for k, (a, b) in ca.PERIODS.items()},
        "sessions": {p: len(legs[p]["dates"]) for p in PERIOD_NAMES},
        "initial_cash_usd": str(ca.INITIAL_CASH),
        "cap_sets": [asdict(c) for c in caps_list],
        "seeds": [ca.seed_for(i) for i in range(ca.N_SEEDS)],
        "books": [
            {
                "strategy": b.strategy,
                "snapshot_id": b.snapshot_id,
                "strategy_version_id": b.version_id,
                "symbols_replayed": len(b.selected),
                "symbols_with_dividend_rows": sum(bool(b.dividends[x]) for x in b.selected),
                "skipped_symbols": sorted(b.skipped),
            }
            for b in books.values()
        ],
        "sleeve_cost_bps": {k: v * 1e4 for k, v in SLEEVE_COST.items()},
        "data_check": data_check,
        "spy_legs": {
            p: {
                "sessions": len(legs[p]["dates"]),
                "first": str(legs[p]["dates"][0]),
                "last": str(legs[p]["dates"][-1]),
                "ex_dates": legs[p]["ex_dates_in_period"],
                "dividends_per_share_usd": legs[p]["dividends_per_share_sum"],
                "price_only_return_pct": float(
                    (legs[p]["close"][-1] / legs[p]["open"][0] - 1.0) * 100.0
                ),
                "total_return_before_cost_pct": float(
                    (np.prod((1.0 + legs[p]["r_on"]) * (1.0 + legs[p]["r_id"])) - 1.0) * 100.0
                ),
                "mean_intraday_bps": float(np.mean(legs[p]["r_id"]) * 1e4),
                "mean_overnight_bps": float(np.mean(legs[p]["r_on"][1:]) * 1e4),
            }
            for p in PERIOD_NAMES
        },
        "identity_a": identity_a,
        "identity_b": {
            "unit_i": {
                "max_abs_usd": checks["unit_i_zero_returns_zero_cost_max_abs_usd"],
                "replays": checks["replays_checked"],
                "passed": True,
            },
            "unit_ii": unit_ii,
            "unit_iii": reconciliation,
            "share_ledger": {
                "max_abs_usd": checks["share_ledger_vs_recursion_max_abs_usd"],
                "replays": checks["replays_checked"],
                "passed": True,
            },
            "sessions_with_negative_book_cash": checks["sessions_with_negative_book_cash"],
            "worked_example": worked_example,
        },
        "reference": {
            p: {**extra["refs"][p]["metrics"], "final_usd": float(extra["refs"][p]["path"][-1])}
            for p in PERIOD_NAMES
        },
        "reference_by_year": {
            p: [
                {"year": label, "spy_return_pct": r}
                for (label, _, _), r in zip(
                    extra["refs"][p]["segments"], extra["refs"][p]["segment_returns"], strict=True
                )
            ]
            for p in PERIOD_NAMES
        },
        "decision_rule": (
            "both periods: median net-return increment > 0, median Sharpe increment > 0, "
            f"at least {MIN_POSITIVE_ORDERS} of {ca.N_SEEDS} orders with a positive net-return "
            f"increment, median max drawdown not more than {DD_TOLERANCE_PTS} points above SPY's, "
            f"and no session with a sleeve shortfall above {SHORTFALL_LIMIT_PCT}% of account value"
        ),
        "analysis": analysis,
        "candidates": [f"{v['book']} / {v['cap_set']}" for v in candidates],
        "stress": stress,
        "runs": {"base": len(rows), "stress": len(stress_rows)},
        "seconds": round(time.perf_counter() - started, 1),
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(
        f"wrote {out / 'replays.csv'} ({len(rows) + len(stress_rows)} rows), "
        f"{out / 'replays_by_year.csv'}, {out / 'marks_base.npz'}, {out / 'summary.json'} "
        f"in {summary['seconds']}s",
        flush=True,
    )
    return 0


# ----------------------------------------------------------------------------- stage: report
def _n(x: float | None, digits: int = 2, signed: bool = False) -> str:
    return ca._n(x, digits, signed)


def _yn(flag: bool) -> str:
    return "yes" if flag else "no"


def render_tables(s: dict[str, Any]) -> str:
    L: list[str] = []
    cells = s["analysis"]["cells"]
    ref = s["reference"]
    ib = s["identity_b"]

    L += ["## Verdicts (decision rule applied mechanically, base costs)", ""]
    L += [
        "| Book | Cap set | IS | OOS | Implementable as stated | Account-level candidate |",
        "|---|---|---|---|---|---|",
    ]
    for v in s["analysis"]["verdicts"]:
        L.append(
            f"| {ca.SHORT[v['book']]} | {v['cap_set']} | {'pass' if v['IS'] else 'fail'} "
            f"| {'pass' if v['OOS'] else 'fail'} | {'yes' if v['implementable_as_stated'] else 'NO (sleeve shortfall above 1%)'} "
            f"| {'YES' if v['account_level_candidate'] else 'no'} |"
        )
    L += [""]

    L += [
        "## Increment over the SPY reference and the decision rule, by period (40 orders, base costs)",
        "",
    ]
    L += [
        "Increment = overlay account minus the SPY reference of the same period. A period passes only if every condition holds.",
        "",
        "| Book | Cap set | Period | Median net-return increment (pts) | p5 / p95 (pts) | Orders with a positive increment / 40 | Median CAGR increment (pts) | Median Sharpe increment | Median max DD: account % / SPY % (diff pts) | Net > 0 | Sharpe > 0 | >= 36 orders | DD <= +2 | Implementable | Period |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---|---|---|---|---|---|",
    ]
    for c in cells:
        k = c["conditions"]
        L.append(
            f"| {ca.SHORT[c['book']]} | {c['cap_set']} | {c['period']} | {_n(c['inc_net_return_pts']['p50'], signed=True)} "
            f"| {_n(c['inc_net_return_pts']['p5'], signed=True)} / {_n(c['inc_net_return_pts']['p95'], signed=True)} "
            f"| {c['orders_positive_net_increment']} | {_n(c['inc_cagr_pts_p50'], signed=True)} | {_n(c['inc_sharpe']['p50'], signed=True)} "
            f"| {_n(c['account_max_drawdown_pct_p50'])} / {_n(c['spy']['max_drawdown_pct'])} ({_n(c['inc_max_drawdown_pts_p50'], signed=True)}) "
            f"| {_yn(k['median_net_increment_positive'])} | {_yn(k['median_sharpe_increment_positive'])} | {_yn(k['at_least_36_orders_positive'])} "
            f"| {_yn(k['median_max_dd_within_2_pts_of_spy'])} | {_yn(k['implementable_as_stated'])} | {'PASS' if c['period_pass'] else 'fail'} |"
        )
    L += [""]

    L += ["## Overlay account, SPY reference and the standalone book (40 orders, base costs)", ""]
    L += [
        "The standalone book and the sleeve share are context only and carry no verdict.",
        "",
        "| Book | Cap set | Period | SPY reference net % | Standalone book net % p50 | Account net % p5 | Account net % p50 | Account net % p95 | Account CAGR % p50 | Account Sharpe p50 (SPY) | Account max DD % p50 (SPY) | Standalone Sharpe p50 | Standalone max DD % p50 | Standalone exposure % p50 | Mean share of account in the sleeve % |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for c in cells:
        L.append(
            f"| {ca.SHORT[c['book']]} | {c['cap_set']} | {c['period']} | {_n(c['spy']['net_return_pct'], signed=True)} "
            f"| {_n(c['standalone_net_return_pct']['p50'], signed=True)} | {_n(c['account_net_return_pct']['p5'], signed=True)} "
            f"| {_n(c['account_net_return_pct']['p50'], signed=True)} | {_n(c['account_net_return_pct']['p95'], signed=True)} "
            f"| {_n(c['account_cagr_pct_p50'], signed=True)} | {_n(c['account_sharpe']['p50'])} ({_n(c['spy']['sharpe'])}) "
            f"| {_n(c['account_max_drawdown_pct_p50'])} ({_n(c['spy']['max_drawdown_pct'])}) | {_n(c['standalone_sharpe_p50'])} "
            f"| {_n(c['standalone_max_drawdown_pct_p50'])} | {_n(c['standalone_mean_exposure_pct_p50'], 1)} | {_n(c['mean_sleeve_share_pct'], 1)} |"
        )
    L += [""]

    L += [
        "## Sleeve shortfalls (sessions on which the book asked for more than the sleeve held)",
        "",
    ]
    L += [
        "| Book | Cap set | Period | Sessions with K < 0 (all 40 orders) | Orders affected / 40 | Largest shortfall $ | Largest shortfall, % of account value | On | Smallest sleeve value $ | Above the 1% limit |",
        "|---|---|---|---:|---:|---:|---:|---|---:|---|",
    ]
    for c in cells:
        L.append(
            f"| {ca.SHORT[c['book']]} | {c['cap_set']} | {c['period']} | {c['shortfall_sessions']} | {c['orders_with_shortfall']} "
            f"| {_n(c['max_shortfall_usd'])} | {_n(c['max_shortfall_pct_of_account'])} | {c['max_shortfall_day'] or '-'} "
            f"| {_n(c['min_sleeve_usd'])} | {'YES' if not c['conditions']['implementable_as_stated'] else 'no'} |"
        )
    L += [""]

    L += ["## Stress costs (qualifying cells only)", ""]
    if s["stress"] is None:
        L += [
            "No cell qualified at base costs, so no stress-cost replay was run (the pre-registration repeats qualifying cells only).",
            "",
        ]
    else:
        st = s["stress"]
        L += [
            f"Rule costs: the R3-C stress case ($0.005 per share with a $1 minimum, 10 bps slippage, 10 bps spread). Sleeve and reference cost: {_n(st['sleeve_cost_bps'], 1)} bps.",
            "",
            "| Book | Cap set | Period | SPY reference net % | Account net % p5 / p50 / p95 | Median net-return increment (pts) | Orders positive / 40 | Median Sharpe increment | Median max DD: account % / SPY % | Largest shortfall, % of account | Period |",
            "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|",
        ]
        for c in st["cells"]:
            L.append(
                f"| {ca.SHORT[c['book']]} | {c['cap_set']} | {c['period']} | {_n(c['spy']['net_return_pct'], signed=True)} "
                f"| {_n(c['account_net_return_pct']['p5'], signed=True)} / {_n(c['account_net_return_pct']['p50'], signed=True)} / {_n(c['account_net_return_pct']['p95'], signed=True)} "
                f"| {_n(c['inc_net_return_pts']['p50'], signed=True)} | {c['orders_positive_net_increment']} | {_n(c['inc_sharpe']['p50'], signed=True)} "
                f"| {_n(c['account_max_drawdown_pct_p50'])} / {_n(c['spy']['max_drawdown_pct'])} | {_n(c['max_shortfall_pct_of_account'])} | {'PASS' if c['period_pass'] else 'fail'} |"
            )
        L += ["", "| Book | Cap set | IS | OOS | Standing |", "|---|---|---|---|---|"]
        for v in st["verdicts"]:
            L.append(
                f"| {ca.SHORT[v['book']]} | {v['cap_set']} | {'pass' if v['IS'] else 'fail'} | {'pass' if v['OOS'] else 'fail'} | {v['standing']} |"
            )
        L += [""]

    L += [
        "## Descriptive only: what the increment is made of (exact split of the pre-registered number; no verdict)",
        "",
    ]
    L += [
        "For each replay the final difference from the reference splits exactly into three parts; the table gives the mean over the 40 orders, in points of net return, so the three parts add up to the mean increment. "
        "Exit-day part: SPY's open-to-close return on the money a book paid in that day, carried to the end of the period; it is in the account only because the pre-registered accounting takes every flow at the open. "
        "Sleeve cost: 5.5 bps of every flow, carried to the end. Remainder: everything else, which is what the same account would show with pay-ins credited at the close of their day and a free sleeve.",
        "",
        "| Book | Cap set | Period | Mean increment (pts) | Remainder (pts) | Exit-day part (pts) | Sleeve cost (pts) | Remainder: p5 / p50 / p95 (pts) | Orders with a positive remainder / 40 | Sleeve turnover $ p50 | SPY open-to-close on pay-in days (bps, flow-weighted) | on withdrawal days (bps) | on all days (bps) |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for c in cells:
        q = c["parts"]
        L.append(
            f"| {ca.SHORT[c['book']]} | {c['cap_set']} | {c['period']} | {_n(q['mean_inc_net_return_pts'], signed=True)} | {_n(q['mean_a_pts'], signed=True)} "
            f"| {_n(q['mean_b_pts'], signed=True)} | {_n(q['mean_cost_pts'], signed=True)} "
            f"| {_n(q['a_pts']['p5'], signed=True)} / {_n(q['a_pts']['p50'], signed=True)} / {_n(q['a_pts']['p95'], signed=True)} "
            f"| {q['orders_positive_a']} | {_n(c['median_sleeve_turnover_usd'], 0)} | {_n(q['spy_intraday_bps_on_net_deposit_days'], 1, signed=True)} "
            f"| {_n(q['spy_intraday_bps_on_net_withdrawal_days'], 1, signed=True)} | {_n(s['spy_legs'][c['period']]['mean_intraday_bps'], 1, signed=True)} |"
        )
    L += [""]

    L += [
        "Where the books' pay-ins come from (share of dollars, all 40 orders pooled). Only exits on an opening gap and dividends are in hand at the open of their day; the rest arrive during the session or at its close.",
        "",
        "| Book | Cap set | Period | Opening-gap stops % | Intraday stops % | Intraday targets % | Time stops at the close % | End-of-period liquidation % | Dividends % |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for c in cells:
        q = c["parts"]["paid_in_share_pct"]
        L.append(
            f"| {ca.SHORT[c['book']]} | {c['cap_set']} | {c['period']} | {_n(q['gap_stop'], 1)} | {_n(q['stop'], 1)} | {_n(q['target'], 1)} "
            f"| {_n(q['time_stop'], 1)} | {_n(q['end_of_data'], 1)} | {_n(q['dividend'], 2)} |"
        )
    L += [""]

    L += [
        "## Descriptive only: the increment by calendar year (median of 40 orders, points; no verdict)",
        "",
    ]
    L += [
        "Each entry is the account's return in that calendar year minus SPY's, in points; in brackets the number of the 40 orders with a positive difference. Yearly differences do not add up to the whole-period increment, because both sides compound.",
        "",
    ]
    for period in PERIOD_NAMES:
        labels = [y["year"] for y in s["reference_by_year"][period]]
        L += [
            f"{period}:",
            "",
            "| Book | Cap set | " + " | ".join(labels) + " |",
            "|---|---|" + "---:|" * len(labels),
            "| SPY reference return % | | "
            + " | ".join(
                _n(y["spy_return_pct"], signed=True) for y in s["reference_by_year"][period]
            )
            + " |",
        ]
        for c in cells:
            if c["period"] != period:
                continue
            assert [y["year"] for y in c["by_year"]] == labels
            L.append(
                f"| {ca.SHORT[c['book']]} | {c['cap_set']} | "
                + " | ".join(
                    f"{_n(y['median_inc_pts'], signed=True)} ({y['orders_positive']})"
                    for y in c["by_year"]
                )
                + " |"
            )
        L += [""]

    L += [
        "## Descriptive only: mean daily active return of the account against SPY (no verdict)",
        "",
    ]
    L += [
        "Active return = the account's daily return minus the SPY reference's. The first three columns use the average of the 40 orders' daily active returns; the standard error is the sample standard deviation over sessions divided by the square root of the number of sessions (no allowance for autocorrelation).",
        "",
        "| Book | Cap set | Period | Sessions | Mean daily active return (bps) | Standard error (bps) | Mean / SE | Annualised (% a year) | Single orders: mean bps p5 / p50 / p95 | Single orders: median SE (bps) | Orders with a positive mean / 40 |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for c in cells:
        a = c["active"]
        L.append(
            f"| {ca.SHORT[c['book']]} | {c['cap_set']} | {c['period']} | {a['sessions']} | {_n(a['mean_bps'], 3, signed=True)} | {_n(a['se_bps'], 3)} "
            f"| {_n(a['t'], 2, signed=True)} | {_n(a['annualised_pct'], 2, signed=True)} "
            f"| {_n(a['per_order_mean_bps']['p5'], 3, signed=True)} / {_n(a['per_order_mean_bps']['p50'], 3, signed=True)} / {_n(a['per_order_mean_bps']['p95'], 3, signed=True)} "
            f"| {_n(a['per_order_se_bps_p50'], 3)} | {a['orders_positive_mean']} |"
        )
    L += [""]

    ia = s["identity_a"]
    L += ["## Identity check A: the 640 R3-C replays re-run", ""]
    L += [
        f"Every replay must reproduce its row in R3-C's `runs.csv` (random order, outright rejection, base costs). Compared: final equity to the cent, entries and net return (required), and {len(ia['fields_all']) - len(ia['fields_required'])} further columns.",
        "",
        "| Book | Cap set | Period | Replays | Final equity, entries and net return identical | All compared columns identical |",
        "|---|---|---|---:|---:|---:|",
    ]
    for c in ia["cells"]:
        L.append(
            f"| {ca.SHORT[c['book']]} | {c['cap_set']} | {c['period']} | {c['replays']} | {c['matched_final_equity_entries_net_return']} | {c['matched_all_fields']} |"
        )
    L.append(
        f"| **All** | | | **{ia['replays']}** | **{ia['matched_final_equity_entries_net_return']}** | **{ia['matched_all_fields']}** |"
    )
    L += [""]

    L += ["## Identity check B: accounting unit tests", ""]
    L += [
        "| Test | Result |",
        "|---|---|",
        f"| (i) SPY returns set to zero and sleeve cost zero: V equals the book's own equity E on every session | passed for {ib['unit_i']['replays']} of {ib['unit_i']['replays']} replays; largest difference ${ib['unit_i']['max_abs_usd']:.1e} |",
    ]
    for p in PERIOD_NAMES:
        u = ib["unit_ii"][p]
        L.append(
            f"| (ii) a book with no trades, {p}: V equals the SPY reference path (reference built separately as a share count) | passed on {u['sessions']} sessions; largest difference ${u['no_trade_book_vs_share_count_reference_max_abs_usd']:.1e} |"
        )
    L.append(
        f"| (extra) every account rebuilt as a SPY share ledger, traded in shares at each open | equal to the recursion for {ib['share_ledger']['replays']} of {ib['share_ledger']['replays']} replays; largest difference ${ib['share_ledger']['max_abs_usd']:.1e} |"
    )
    L.append(
        f"| Sessions on which a book's cash was below zero (the floor at 0) | {ib['sessions_with_negative_book_cash']} |"
    )
    L.append(
        f"| (extra) a three-session example worked by hand in the script (every K, V, cost and the three-part split) | {'passed' if ib['worked_example']['passed'] else 'FAILED'} |"
    )
    L += [""]

    L += ["### (iii) The pre-registered SPY reference next to the R3-C figure", ""]
    L += [
        "| Period | Reference | Net % | CAGR % | Max DD % | Sharpe | Final value $ |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for p in PERIOD_NAMES:
        u = ib["unit_iii"][p]
        b, r = u["r3c_benchmark"], u["reference"]
        L.append(
            f"| {p} | R3-C (`funded_replay_report.spy_benchmark`, reproduced here) | {_n(b['net_return_pct'], signed=True)} | {_n(b['cagr_pct'], signed=True)} | {_n(b['max_drawdown_pct'])} | {_n(b['sharpe'])} | {_n(b['final_usd'])} |"
        )
        L.append(
            f"| {p} | R4-O pre-registered reference | {_n(r['net_return_pct'], signed=True)} | {_n(r['cagr_pct'], signed=True)} | {_n(r['max_drawdown_pct'])} | {_n(r['sharpe'])} | {_n(r['final_usd'])} |"
        )
    L += [""]
    L += [
        "Where the difference comes from, one convention at a time:",
        "",
        "| Step | IS final $ | IS net % | OOS final $ | OOS net % |",
        "|---|---:|---:|---:|---:|",
    ]
    for k, step in enumerate(ib["unit_iii"]["IS"]["bridge"]):
        o = ib["unit_iii"]["OOS"]["bridge"][k]
        L.append(
            f"| {step['step']} | {_n(step['final_usd'])} | {_n(step['net_return_pct'], signed=True)} | {_n(o['final_usd'])} | {_n(o['net_return_pct'], signed=True)} |"
        )
    L += [""]

    L += ["## Scope actually run", ""]
    for b in s["books"]:
        L.append(
            f"- {b['strategy']} (strategy version {b['strategy_version_id']}, snapshot {b['snapshot_id']}): {b['symbols_replayed']} symbols replayed ({b['symbols_with_dividend_rows']} with dividend rows), skipped for incomplete bars: {', '.join(b['skipped_symbols']) or 'none'}."
        )
    caps = {c["name"]: c for c in s["cap_sets"]}
    L.append(
        f"- Cap sets: operating = open risk {caps['operating']['open_risk_pct']}%, gross {caps['operating']['gross_pct']}%, {caps['operating']['daily_cap']} accepts per day; maxima = open risk {caps['maxima']['open_risk_pct']}%, gross {caps['maxima']['gross_pct']}%, no daily cap. Both: per-trade risk {ca.PER_TRADE_RISK_PCT}%, symbol {ca.SYMBOL_CAP_PCT}%, sector {ca.SECTOR_CAP_PCT}%, ${ca.INITIAL_CASH} cash."
    )
    L.append(
        f"- Replays: {s['runs']['base']} at base costs (4 books x 2 cap sets x 2 periods x 40 orders, seeds {s['seeds'][0]}..{s['seeds'][-1]}), {s['runs']['stress']} at stress costs. Sessions: IS {s['sessions']['IS']}, OOS {s['sessions']['OOS']}."
    )
    lg = s["spy_legs"]
    L.append(
        f"- SPY legs: {lg['IS']['ex_dates']} ex-dates in IS (${_n(lg['IS']['dividends_per_share_usd'])} a share) and {lg['OOS']['ex_dates']} in OOS (${_n(lg['OOS']['dividends_per_share_usd'])}); price-only return {_n(lg['IS']['price_only_return_pct'], signed=True)}% and {_n(lg['OOS']['price_only_return_pct'], signed=True)}%, total return before cost {_n(lg['IS']['total_return_before_cost_pct'], signed=True)}% and {_n(lg['OOS']['total_return_before_cost_pct'], signed=True)}%."
    )
    L.append(
        f"- Sleeve cost: {_n(s['sleeve_cost_bps']['base'], 1)} bps of every flow at base costs. Reference: ${_n(ref['IS']['final_usd'])} at the end of IS and ${_n(ref['OOS']['final_usd'])} at the end of OOS from $30,000."
    )
    L += [""]
    return "\n".join(L)


def stage_report(out: Path) -> int:
    """Write the generated tables; when the hand-written head and tail exist beside
    them, assemble the pre-registered results file (text by hand, numbers by script)."""
    summary = json.loads((out / "summary.json").read_text())
    if not summary["identity_a"]["passed"]:
        raise SystemExit("identity check A has not passed; nothing may be reported")
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
    p.add_argument("stage", choices=["run", "report", "all"])
    p.add_argument("--db", type=Path, default=None, help="scratch database (read-only)")
    p.add_argument("--out", type=Path, default=None, help="raw output folder")
    a = p.parse_args(argv)
    a.db = a.db or ca.default_db()
    a.out = a.out or default_out()
    ca._guard_paths(a.db, a.out, RESULTS_FILE)
    a.out.mkdir(parents=True, exist_ok=True)
    for stage in ["run", "report"] if a.stage == "all" else [a.stage]:
        print(f"== {stage} ({time.strftime('%H:%M:%S', time.gmtime())} UTC)", flush=True)
        code = stage_run(a.out, a.db) if stage == "run" else stage_report(a.out)
        if code:
            return code
    return 0


if __name__ == "__main__":
    sys.exit(main())
