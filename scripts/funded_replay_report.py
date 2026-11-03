"""Read-only descriptive replay of frozen daily baseline rules, never promotion.

No study databases, provider requests, account writes or new sealed looks.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from dataclasses import asdict
from datetime import date
from pathlib import Path

from signalforge.backtest.costs import CostModel
from signalforge.backtest.funded import run_funded_replay
from signalforge.config.research import RiskLimits
from signalforge.data.calendar import sessions
from signalforge.data.series import PriceSeries
from signalforge.domain import Horizon
from signalforge.research.regime import regime_lookup
from signalforge.research.strategies import TrendContinuation, signal_fn_for


def replay(database: Path, symbols: list[str], start: date, end: date) -> dict:
    if not database.is_file() or not symbols or len(set(symbols)) != len(symbols):
        raise ValueError("Existing database and unique symbols required")
    dates = tuple(sessions(start, end))
    if not dates:
        raise ValueError("No sessions")
    data = {}
    sectors = {}
    hashes = {}
    with sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True) as c:
        c.execute("PRAGMA query_only=ON")
        c.execute("BEGIN")
        if c.execute(
            "SELECT 1 FROM sqlite_master WHERE name LIKE 'comparison_%' LIMIT 1"
        ).fetchone():
            raise ValueError("Frozen comparison databases excluded")
        for symbol in sorted(set(symbols) | {"SPY"}):
            rows = c.execute(
                """SELECT b.session_date,b.open,b.high,b.low,b.close,b.volume,
                b.is_adjusted,b.is_simulated,b.quality_flags,b.source,b.latency_category
                FROM ohlcv_daily b JOIN instrument i ON i.id=b.instrument_id
                WHERE i.symbol=? AND b.source='massive' AND b.session_date BETWEEN ? AND ?
                ORDER BY b.session_date""",
                (symbol, str(start), str(end)),
            ).fetchall()
            if tuple(date.fromisoformat(r[0]) for r in rows) != dates:
                raise ValueError(f"{symbol}: missing or duplicate sessions; no silent truncation")
            if any(not r[6] or r[7] or r[8] is None or json.loads(r[8]) for r in rows):
                raise ValueError(f"{symbol}: adjustment, simulation or quality gate failed")
            hashes[symbol] = hashlib.sha256(
                json.dumps(rows, separators=(",", ":")).encode()
            ).hexdigest()
            data[symbol] = PriceSeries.from_bars(
                symbol, [(date.fromisoformat(r[0]), *r[1:6]) for r in rows]
            )
            row = c.execute("SELECT sector FROM instrument WHERE symbol=?", (symbol,)).fetchone()
            sectors[symbol] = row[0] or "unknown"
    regimes = regime_lookup(data["SPY"])
    strategy = TrendContinuation(Horizon.SHORT_SWING)
    limits = RiskLimits(max_position_concentration_pct=5, max_correlated_exposure_pct=20)
    costs = CostModel()
    selected = {s: data[s] for s in sorted(symbols)}
    result = run_funded_replay(
        selected,
        {s: signal_fn_for(strategy, regime_by_date=regimes) for s in selected},
        sectors,
        limits=limits,
        cost_model=costs,
    )
    return {
        "status": "DESCRIPTIVE_UNVALIDATED",
        "strategy": "trend_continuation.short_swing",
        "strategy_spec": asdict(strategy.spec()),
        "initial_cash_usd": "10000.00",
        "window": [str(start), str(end)],
        "dataset_sha256_by_symbol": hashes,
        "cost_model": asdict(costs),
        "spread_bps": 5,
        "risk_limits": limits.model_dump(mode="json"),
        "result": asdict(result),
        "limitations": [
            "Already-observed history; not a fresh sealed test.",
            "Fixed surviving universe and current sector metadata; selection/PIT limitations.",
            "Split-adjusted prices; no dividend ledger or point-in-time earnings exclusion.",
            "Fixed modeled spread/slippage, no observed NBBO or queue/market impact.",
            "Same-bar stop-first; alphabetical admission, no portfolio optimization.",
            "Not calibrated or promoted; no forecast of reliable income.",
        ],
    }


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("database", type=Path)
    p.add_argument("--symbols", nargs="+", required=True)
    p.add_argument("--since", type=date.fromisoformat, required=True)
    p.add_argument("--until", type=date.fromisoformat, required=True)
    a = p.parse_args()
    print(json.dumps(replay(a.database, a.symbols, a.since, a.until), default=str, indent=2))
