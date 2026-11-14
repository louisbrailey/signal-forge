"""R3-C verification of the ordering plumbing and ranking keys (no new study arm).

Run after ``capacity_admission.py prepare`` with the same environment. It checks, on
the 150-symbol trend_continuation.medium book:

1. the alphabetical, random and K1-K3 order functions on the 200 busiest signal days;
2. K1, K2 and K3 against an independent pandas recomputation from the database;
3. one trim run (seed 20261110, operating caps, IS; a duplicate of a grid run): sizes,
   rejection reasons and the two-accepts-per-day cap;
4. the share basis of the booked dividends (added after review): which booked amounts
   depend on a split row dated after the development window, and whether prices fall by
   about the booked dividend on ex-dates. In-window rows and the study cache only: the
   split query here is bounded at the last development session, so no row dated after it
   is selected, and only counts and group averages are printed.

Research signal only - no order was placed.
"""

from __future__ import annotations

import math
import pickle
import sqlite3
from collections import Counter
from datetime import date
from decimal import Decimal

import capacity_admission as ca
import numpy as np
import pandas as pd

import __main__

# The cache was pickled by the study script running as ``__main__``.
__main__.Book = ca.Book  # type: ignore[attr-defined]

BOOK = "trend_continuation.medium_swing"


def main() -> int:
    # Trusted input: written by this study's own prepare stage into the scratch folder.
    with (ca.default_out() / "cache" / f"{BOOK}.pkl").open("rb") as fh:
        book = pickle.load(fh)  # noqa: S301 - this study's own cache

    # 1. order functions on the busiest signal days
    busy = sorted(range(len(book.day_signals)), key=lambda t: -len(book.day_signals[t]))[:200]
    alpha = ca.make_order(book, ("alpha",))
    for seed in (ca.SEED0, ca.SEED0 + ca.N_SEEDS - 1):
        rnd = ca.make_order(book, ("random", seed))
        prio = np.random.default_rng(seed).random((len(book.dates), len(book.selected)))
        idx = {s: j for j, s in enumerate(book.selected)}
        for t in busy:
            pending = dict(book.day_signals[t])
            i = t + 1
            assert [s for s, _ in rnd(i, pending)] == sorted(pending, key=lambda s: prio[i, idx[s]])
            assert [s for s, _ in alpha(i, pending)] == sorted(pending)
    for k, name in enumerate(ca.KEYS):
        order = ca.make_order(book, ("key", name))
        for t in busy:
            pending = dict(book.day_signals[t])
            values = [book.keys[(t, s)][k] for s, _ in order(t + 1, pending)]
            finite = [v for v in values if math.isfinite(v)]
            assert finite == sorted(finite, reverse=True), (name, t)
            assert all(math.isfinite(v) for v in values[: len(finite)])  # missing keys last
    print(
        f"order functions verified on {len(busy)} busiest days; "
        f"max same-day signals {len(book.day_signals[busy[0]])}"
    )

    # 2. independent recomputation of the keys from the database
    con = sqlite3.connect(f"file:{ca.default_db()}?mode=ro", uri=True)

    def bars(symbol: str) -> pd.DataFrame:
        return pd.read_sql_query(
            "SELECT b.session_date d,b.open,b.high,b.low,b.close,b.volume FROM ohlcv_daily b "
            "JOIN instrument i ON i.id=b.instrument_id WHERE i.symbol=? AND b.source='massive' "
            "AND b.session_date BETWEEN ? AND ? ORDER BY 1",
            con,
            params=(symbol, str(ca.FULL_START), str(ca.DEV_END)),
        ).set_index("d")

    spy = bars("SPY")["close"].to_numpy()
    rng = np.random.default_rng(7)
    items = sorted(book.keys)
    worst = [0.0, 0.0, 0.0]
    for j in rng.choice(len(items), 300, replace=False):
        t, symbol = items[j]
        df = bars(symbol)
        assert df.index[t] == str(book.dates[t])
        close, volume = df["close"].to_numpy(), df["volume"].to_numpy()
        high, low = df["high"].to_numpy(), df["low"].to_numpy()
        k1 = (
            (close[t] / close[t - 63] - 1) - (spy[t] / spy[t - 63] - 1) if t >= 63 else float("nan")
        )
        k2 = volume[t] / volume[t - 19 : t].mean()
        true_range = np.maximum.reduce(
            [high[1:] - low[1:], abs(high[1:] - close[:-1]), abs(low[1:] - close[:-1])]
        )
        k3 = 1.5 * true_range[t - 14 : t].mean() / close[t]  # stop = close - 1.5 x ATR(14)
        pairs = zip((k1, k2, k3), book.keys[(t, symbol)], strict=True)
        for n, (a, b) in enumerate(pairs):
            if not (math.isnan(a) and math.isnan(b)):
                worst[n] = max(worst[n], abs(a - b))
    print("independent key recomputation, max abs difference K1/K2/K3:", worst)
    assert max(worst) < 1e-12
    assert max(book.dates) == ca.DEV_END

    # 3. one trim run against its reject twin
    caps = ca.Caps("operating", 1.5, 60.0, 2)
    cm, spread = ca.frr.COST_CASES[ca.BASE]
    order = ("random", ca.SEED0)
    reject, _ = ca.local_replay(book, "IS", caps, cm, spread, order=order, trim=False)
    trim, stats = ca.local_replay(book, "IS", caps, cm, spread, order=order, trim=True)
    buys_r = [f for f in reject.fills if f["side"] == "buy"]
    buys_t = [f for f in trim.fills if f["side"] == "buy"]
    assert min(f["shares"] for f in buys_t) >= 1
    assert max(Counter(f["day"] for f in buys_t).values()) <= caps.daily_cap
    assert max(Counter(f["day"] for f in buys_r).values()) <= caps.daily_cap
    print(
        f"seed {ca.SEED0}, operating, IS: reject entries {len(buys_r)}, "
        f"trim entries {len(buys_t)}, admitted by a trim {stats.get('trim_admitted')}, "
        f"smallest trim entry "
        f"{min(f['shares'] for f in buys_t)} share(s)"
    )
    for label, result in (("reject", reject), ("trim", trim)):
        reasons = Counter(d["reason"] for d in result.decisions if d["status"] == "rejected")
        print(f"  {label} rejections:", reasons.most_common(6))

    # 4. share basis of the booked dividends. The library loader the study calls
    # (funded_replay_report._dividends) reads split_event with no date bound. Recomputing
    # each amount with the split query bounded at the last development session shows which
    # booked amounts depend on a later split row, without selecting that row here.
    end = str(ca.DEV_END)
    index = {d: i for i, d in enumerate(book.dates)}
    spy_series = book.data["SPY"]
    spy_dividend = {d.ex_date: float(d.amount) for d in book.dividends["SPY"]}
    falls: dict[bool, list[tuple[float, float]]] = {True: [], False: []}
    symbols = {True: 0, False: 0}
    rows_total = rows_dependent = symbols_with_rows = 0
    for symbol in sorted(book.dividends):
        booked = book.dividends[symbol]
        splits = con.execute(
            "SELECT execution_date, split_from, split_to FROM split_event "
            "WHERE symbol=? AND execution_date<=?",
            (symbol, end),
        ).fetchall()
        rows = con.execute(
            "SELECT ex_dividend_date, cash_amount FROM dividend_event "
            "WHERE symbol=? AND ex_dividend_date BETWEEN ? AND ? ORDER BY ex_dividend_date",
            (symbol, str(ca.FULL_START), end),
        ).fetchall()
        assert len(rows) == len(booked) and all(day <= end for day, _, _ in splits)
        rows_total += len(rows)
        symbols_with_rows += bool(rows)
        series = book.data[symbol]
        dependent = 0
        pairs = []
        for (ex, amount), d in zip(rows, booked, strict=True):
            assert date.fromisoformat(ex) == d.ex_date <= ca.DEV_END
            ratio = Decimal(1)
            for day, split_from, split_to in splits:
                if date.fromisoformat(day) > d.ex_date:
                    ratio *= Decimal(str(split_to)) / Decimal(str(split_from))
            dependent += Decimal(str(amount)) / ratio != d.amount
            i = index[d.ex_date]
            if i == 0:
                continue
            # Overnight move into the ex-date, net of SPY's (SPY's own dividend is added
            # back when SPY is ex-dividend the same day), and the booked dividend, both as
            # fractions of the prior close on the bars' share basis.
            market = float(spy_series.open[i]) / float(spy_series.close[i - 1]) - 1
            market += spy_dividend.get(d.ex_date, 0.0) / float(spy_series.close[i - 1])
            move = float(series.open[i]) / float(series.close[i - 1]) - 1
            pairs.append((market - move, float(d.amount) / float(series.close[i - 1])))
        rows_dependent += dependent
        assert dependent in (0, len(rows))  # a later split rescales every in-window row
        if symbol == "SPY":  # the market reference of the fall check
            assert dependent == 0
        elif rows:
            falls[dependent > 0].extend(pairs)
            symbols[dependent > 0] += 1
    print(
        f"dividend basis: {rows_total} in-window dividend rows for {symbols_with_rows} "
        f"symbols; the booked amounts of {symbols[True]} symbols ({rows_dependent} rows) "
        f"depend on a split row dated after {end}"
    )
    multiples = {}
    for depends, label in ((True, "those symbols"), (False, "the other symbols, SPY excluded")):
        fall, booked_yield = (np.array(v) for v in zip(*falls[depends], strict=True))
        multiples[depends] = float(fall.mean() / booked_yield.mean())
        se = float(fall.std(ddof=1) / math.sqrt(len(fall)) / booked_yield.mean())
        print(
            f"  ex-date overnight fall net of the market, as a multiple of the booked dividend, "
            f"{label}: {multiples[depends]:.2f} (standard error {se:.2f}; {len(fall)} ex-dates, "
            f"{symbols[depends]} symbols)"
        )
    # On the wrong share basis the multiple would be the split ratio, not about one.
    assert 0.5 < multiples[True] < 1.5 and 0.5 < multiples[False] < 1.5
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
