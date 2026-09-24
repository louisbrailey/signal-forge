"""Read-only census of the regime classifier's labels over the ingested proxy history.

Opens the SQLite database in ``mode=ro`` (no ORM session, no writes, no
migrations) and runs BOTH classifiers the pipeline uses over the full SPY
``massive`` history:

* ``research.regime.regime_from_proxy`` — the bull/bear/neutral trend label the
  live scan's ``_oos_regime_coverage`` gate buckets OOS trades by;
* ``backtest.regime.label_regimes`` — the bull/bear/range label promotion
  gate 6 uses.

Sessions before the 200-session SMA warmup are reported as ``warmup`` —
``regime_from_proxy`` returns NEUTRAL there only because SMA-200 is NaN, which
is not a genuine range-bound market and must not be counted as neutral evidence.

Usage: python scripts/regime_span_census.py [--db PATH] [--proxy SPY] [--source massive]
"""

from __future__ import annotations

import argparse
import itertools
import sqlite3
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

from signalforge.backtest.regime import TREND_LOOKBACK, label_regimes
from signalforge.data.series import PriceSeries
from signalforge.research.regime import regime_from_proxy

_DEFAULT_DB = Path.home() / "signal-forge" / "data" / "signalforge.sqlite"


def load_proxy(con: sqlite3.Connection, symbol: str, source: str) -> PriceSeries:
    rows = con.execute(
        "SELECT o.session_date, o.open, o.high, o.low, o.close, o.adj_close, o.volume "
        "FROM ohlcv_daily o JOIN instrument i ON i.id = o.instrument_id "
        "WHERE i.symbol = ? AND o.source = ? AND o.is_simulated = 0 ORDER BY o.session_date",
        (symbol, source),
    ).fetchall()
    bars: list[tuple[date, float, float, float, float, float]] = []
    for d, o, h, lo, cl, adj, v in rows:
        close = adj if adj is not None else cl
        scale = close / cl if cl else 1.0
        bars.append((date.fromisoformat(d), o * scale, h * scale, lo * scale, close, v))
    return PriceSeries.from_bars(symbol, bars)


def spans(labels: list[tuple[date, str]]) -> list[tuple[str, date, date, int]]:
    out = []
    for key, grp in itertools.groupby(labels, key=lambda x: x[1]):
        g = list(grp)
        out.append((key, g[0][0], g[-1][0], len(g)))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(_DEFAULT_DB))
    ap.add_argument("--proxy", default="SPY")
    ap.add_argument("--source", default="massive")
    ap.add_argument("--min-span", type=int, default=5)
    args = ap.parse_args()

    con = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    proxy = load_proxy(con, args.proxy, args.source)
    first, last = proxy.dates[0], proxy.dates[-1]
    print(f"{args.proxy}/{args.source}: {len(proxy)} sessions {first} -> {last}")

    trend: list[tuple[date, str]] = []
    for t in range(len(proxy)):
        label = "warmup" if t < TREND_LOOKBACK - 1 else regime_from_proxy(proxy, t).trend.value
        trend.append((proxy.dates[t], label))

    print(f"\n== research.regime trend spans (>= {args.min_span} sessions)")
    for key, a, b, n in spans(trend):
        if n >= args.min_span:
            print(f"  {key:8} {a} -> {b}  {n:4d} sessions")
    print("  totals:", dict(Counter(lab for _, lab in trend)))
    print("\n  per calendar year:")
    for y in range(proxy.dates[0].year, proxy.dates[-1].year + 1):
        print(f"    {y}: {dict(Counter(lab for d, lab in trend if d.year == y))}")
    print("\n  trailing windows ending at the last session:")
    for days in (365, 548, 730, 1095, 1460, 1825, 2190):
        lo = proxy.dates[-1] - timedelta(days=days)
        print(f"    {days:4d}d: {dict(Counter(lab for d, lab in trend if d > lo))}")

    g6 = label_regimes(proxy)
    coarse = [(d, g6[d].split("_")[0]) for d in proxy.dates]
    print(f"\n== backtest.regime (gate 6) coarse spans (>= {args.min_span * 2} sessions)")
    for key, a, b, n in spans(coarse):
        if n >= args.min_span * 2:
            print(f"  {key:8} {a} -> {b}  {n:4d} sessions")
    print("  totals:", dict(Counter(lab for _, lab in coarse)))


if __name__ == "__main__":
    main()
