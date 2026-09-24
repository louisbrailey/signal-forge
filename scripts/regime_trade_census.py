"""Read-only census: OOS trade COUNTS per trend regime for candidate evidence windows.

Runs ``research.backtest_runner.run_strategy_over_universe`` — the exact code
path whose persisted ``oos_by_regime`` rows the live scan's
``_oos_regime_coverage`` gate reads — over a SQLite connection opened with
``mode=ro``. Nothing is persisted; any accidental write would raise.

Only trade COUNTS per regime label are printed — never expectancy, P&L or any
other performance number — so this census cannot inform a later sealed test
beyond the structural question "how many OOS trades land in each regime".

Usage:
  python scripts/regime_trade_census.py --universe watchlist|snapshot:3|snapshot:11 \
      --end 2026-09-24 --years 2 4 5 [--strategies trend_continuation.short_swing ...]
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from signalforge.research.backtest_runner import run_strategy_over_universe
from signalforge.research.strategies import default_strategies

_DEFAULT_DB = Path.home() / "signal-forge" / "data" / "signalforge.sqlite"
_DEFAULT_STRATEGIES = (
    "trend_continuation.short_swing",
    "trend_continuation.medium_swing",
    "relative_strength.medium_swing",
)
# The configured 25-symbol research universe the existing scan evidence
# (backtest_run ids 38/39/41) was produced on — read from those rows' params.
_WATCHLIST_RUN_ID = 41


def _symbols(db: str, universe: str) -> list[str]:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    if universe == "watchlist":
        row = con.execute(
            "SELECT params_json FROM backtest_run WHERE id = ?", (_WATCHLIST_RUN_ID,)
        ).fetchone()
        return list(json.loads(row[0])["symbols"])
    kind, _, sid = universe.partition(":")
    if kind != "snapshot" or not sid.isdigit():
        raise SystemExit(f"bad --universe {universe!r}")
    row = con.execute("SELECT symbols_json FROM data_snapshot WHERE id = ?", (int(sid),)).fetchone()
    return list(json.loads(row[0]))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(_DEFAULT_DB))
    ap.add_argument("--universe", default="watchlist")
    ap.add_argument("--end", type=date.fromisoformat, default=date.today())
    ap.add_argument("--years", type=int, nargs="+", default=[2])
    ap.add_argument("--source", default="massive")
    ap.add_argument("--strategies", nargs="+", default=list(_DEFAULT_STRATEGIES))
    args = ap.parse_args()

    symbols = _symbols(args.db, args.universe)
    engine = create_engine(f"sqlite+pysqlite:///file:{args.db}?mode=ro&uri=true")
    strategies = {s.spec().name: s for s in default_strategies()}
    print(f"universe={args.universe} n={len(symbols)} end={args.end} source={args.source}")
    with Session(engine) as session:
        for years in args.years:
            start = args.end - timedelta(days=365 * years + 10)
            for name in args.strategies:
                res = run_strategy_over_universe(
                    session,
                    strategies[name],
                    symbols,
                    start,
                    args.end,
                    source=args.source,
                    allow_short=False,
                    min_bars=60,
                )
                by_trend: Counter[str] = Counter()
                for label, m in res.by_regime.items():
                    by_trend[label.split("/", 1)[0]] += m.n_trades
                print(
                    f"  years={years} start={start} {name}: OOS n={res.out_of_sample.n_trades} "
                    f"by_label={ {k: v.n_trades for k, v in res.by_regime.items()} } "
                    f"by_trend={dict(by_trend)}"
                )
        session.rollback()


if __name__ == "__main__":
    main()
