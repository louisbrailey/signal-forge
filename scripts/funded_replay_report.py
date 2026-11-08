"""Read-only descriptive replay of frozen daily baseline rules, never promotion.

No study databases, provider requests, account writes or new sealed looks.
Any registered daily strategy runs long-only; a comma-separated ``--strategy``
list is a priority-ordered per-symbol composite with per-strategy attribution.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import asdict
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from signalforge.backtest.costs import CostModel
from signalforge.backtest.funded import (
    FundedReplay,
    composite_signal_fn,
    money,
    run_funded_replay,
)
from signalforge.config.research import RiskLimits
from signalforge.data.calendar import sessions
from signalforge.data.series import PriceSeries
from signalforge.domain import Horizon
from signalforge.paper.ledger import HARD_MAX_SECTOR_PCT, HARD_MAX_SYMBOL_PCT
from signalforge.research.funded_diagnostics import diagnose, passive_comparator
from signalforge.research.regime import regime_lookup
from signalforge.research.strategies import BaselineStrategy, default_strategies, signal_fn_for

# The sealed final-test year is never read: development windows end before it.
SEALED_START = date(2025, 9, 8)
SEALED_END = date(2026, 9, 8)
DEFAULT_UNTIL = date(2025, 9, 7)
DEFAULT_STRATEGY = "trend_continuation.short_swing"

# Fixed sensitivity cases, never a search for the most profitable settings.
COST_CASES: dict[str, tuple[CostModel, float]] = {
    "base": (CostModel(), 5.0),
    "zero_fees_spread_slippage": (CostModel(slippage_bps=0), 0.0),
    "higher_cost_stress": (
        CostModel(commission_per_share=0.005, commission_min_per_order=1, slippage_bps=10),
        10.0,
    ),
}


class IncompleteSeries(ValueError):
    """A symbol's bars do not cover every session of the window."""


def check_window(start: date, end: date) -> None:
    if start > end:
        raise ValueError("--since must not be after --until")
    if start <= SEALED_END and end >= SEALED_START:
        raise ValueError(
            f"Window {start}..{end} overlaps the sealed year {SEALED_START}..{SEALED_END}; "
            f"development runs end by {DEFAULT_UNTIL}"
        )


def daily_strategies() -> dict[str, BaselineStrategy]:
    """Registered daily strategies by key; every one is replayed long-only."""
    return {s.key: s for s in default_strategies() if s.spec().horizon is not Horizon.INTRADAY}


def resolve_strategies(spec: str | Sequence[str]) -> list[BaselineStrategy]:
    keys = [k.strip() for k in spec.split(",")] if isinstance(spec, str) else list(spec)
    if not keys or any(not k for k in keys) or len(set(keys)) != len(keys):
        raise ValueError("Strategy list must be nonempty, comma-separated and unique")
    known = daily_strategies()
    unknown = [k for k in keys if k not in known]
    if unknown:
        raise ValueError(f"Unknown or non-daily strategy {unknown}; choose from {sorted(known)}")
    return [known[k] for k in keys]


def snapshot_symbols(conn: sqlite3.Connection, snapshot_id: int) -> list[str]:
    row = conn.execute(
        "SELECT symbols_json, continuity_mapping_id, options_scope_json "
        "FROM data_snapshot WHERE id=?",
        (snapshot_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"data_snapshot {snapshot_id} not found")
    if row[1] is not None or row[2] is not None:
        raise ValueError("Continuity-mapped or options snapshots are not supported")
    symbols = json.loads(row[0])
    if not symbols or len(set(symbols)) != len(symbols):
        raise ValueError("Snapshot requires unique symbols")
    return list(symbols)


def _load(
    conn: sqlite3.Connection, symbol: str, start: date, end: date, dates: tuple[date, ...]
) -> list[tuple]:
    rows = conn.execute(
        """SELECT b.session_date,b.open,b.high,b.low,b.close,b.volume,
        b.is_adjusted,b.is_simulated,b.quality_flags,b.source,b.latency_category
        FROM ohlcv_daily b JOIN instrument i ON i.id=b.instrument_id
        WHERE i.symbol=? AND b.source='massive' AND b.session_date BETWEEN ? AND ?
        ORDER BY b.session_date""",
        (symbol, str(start), str(end)),
    ).fetchall()
    if tuple(date.fromisoformat(r[0]) for r in rows) != dates:
        raise IncompleteSeries(
            f"{symbol}: missing or duplicate sessions ({len(rows)}/{len(dates)}); "
            "no silent truncation"
        )
    if any(not r[6] or r[7] or r[8] is None or json.loads(r[8]) for r in rows):
        raise ValueError(f"{symbol}: adjustment, simulation or quality gate failed")
    return rows


def max_drawdown_pct(result: FundedReplay) -> float:
    peak = Decimal(0)
    worst = Decimal(0)
    for mark in result.marks:
        value = Decimal(mark["net_liquidation_usd"])
        peak = max(peak, value)
        if peak > 0:
            worst = max(worst, (peak - value) / peak)
    return float(worst * 100)


def strategy_attribution(
    result: FundedReplay, keys: Sequence[str], *, round_trip_pnl: Decimal | None = None
) -> dict[str, Any]:
    """Per-strategy entries, round trips and realized P&L from attributed fills.

    Dividends are not attributed. Raises unless every exit carries its entry's
    strategy, attributed costs sum to the engine's own ``result.costs``, and (when
    given) attributed P&L equals ``round_trip_pnl``, the diagnose() round-trip
    total that is itself reconciled to terminal cash."""
    rows: dict[str, dict[str, Any]] = {
        k: {
            "entries": 0,
            "closed_trades": 0,
            "wins": 0,
            "net_pnl_usd": Decimal(0),
            "gross_gain_usd": Decimal(0),
            "gross_loss_usd": Decimal(0),
            "modeled_costs_usd": Decimal(0),
            "rejected_entries": 0,
        }
        for k in keys
    }
    total = Decimal(0)
    open_by_symbol: dict[str, str] = {}
    for fill in result.fills:
        key = fill.get("strategy")
        if key not in rows:
            raise ValueError(f"Unattributed or unknown strategy on fill: {key!r}")
        row = rows[key]
        row["modeled_costs_usd"] += Decimal(fill["modeled_cost_usd"])
        if fill["side"] == "buy":
            open_by_symbol[fill["symbol"]] = key
            row["entries"] += 1
            continue
        if open_by_symbol.pop(fill["symbol"], None) != key:
            raise ValueError(f"Exit strategy differs from entry strategy: {fill['symbol']}")
        pnl = Decimal(fill["realized_pnl_usd"])
        total += pnl
        row["closed_trades"] += 1
        row["wins"] += pnl > 0
        row["net_pnl_usd"] += pnl
        row["gross_gain_usd" if pnl > 0 else "gross_loss_usd"] += max(pnl, -pnl)
    for decision in result.decisions:
        if decision["status"] == "rejected" and decision.get("strategy") in rows:
            rows[decision["strategy"]]["rejected_entries"] += 1
    if sum((r["modeled_costs_usd"] for r in rows.values()), Decimal(0)) != result.costs:
        raise ValueError("Attributed costs do not reconcile to replay costs")
    if round_trip_pnl is not None and total != round_trip_pnl:
        raise ValueError("Attributed P&L does not reconcile to round trips")
    out = {}
    for key, row in rows.items():
        n, loss = row["closed_trades"], row["gross_loss_usd"]
        out[key] = {
            "entries": row["entries"],
            "closed_trades": n,
            "hit_rate": row["wins"] / n if n else None,
            "net_pnl_usd": str(money(row["net_pnl_usd"])),
            "profit_factor": float(row["gross_gain_usd"] / loss) if loss else None,
            "modeled_costs_usd": str(money(row["modeled_costs_usd"])),
            "rejected_entries": row["rejected_entries"],
        }
    return out


def replay(
    database: Path,
    symbols: list[str] | None,
    start: date,
    end: date,
    *,
    cost_scenarios: bool = False,
    strategy: str | Sequence[str] = DEFAULT_STRATEGY,
    snapshot_id: int | None = None,
    initial_cash: Decimal = Decimal("10000"),
    max_position_pct: float = 5.0,
    max_sector_pct: float = 20.0,
    cost_case: str = "base",
    log: Callable[[str], None] | None = None,
) -> dict:
    check_window(start, end)
    strategies = resolve_strategies(strategy)
    keys = [s.key for s in strategies]
    if not initial_cash.is_finite() or initial_cash <= 0:
        raise ValueError("Initial cash must be positive")
    if not 0 < max_position_pct <= HARD_MAX_SYMBOL_PCT:
        raise ValueError(f"--max-position-pct must be in (0, {HARD_MAX_SYMBOL_PCT}]")
    if not 0 < max_sector_pct <= HARD_MAX_SECTOR_PCT:
        raise ValueError(f"--max-sector-pct must be in (0, {HARD_MAX_SECTOR_PCT}]")
    if cost_case not in COST_CASES:
        raise ValueError(f"Unknown cost case {cost_case!r}")
    if (snapshot_id is None) == (not symbols):
        raise ValueError("Exactly one of explicit symbols or a snapshot id is required")
    if not database.is_file() or (symbols and len(set(symbols)) != len(symbols)):
        raise ValueError("Existing database and unique symbols required")
    dates = tuple(sessions(start, end))
    if not dates:
        raise ValueError("No sessions")
    data = {}
    sectors = {}
    hashes = {}
    skipped: dict[str, str] = {}
    with sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True) as c:
        c.execute("PRAGMA query_only=ON")
        c.execute("BEGIN")
        if c.execute(
            "SELECT 1 FROM sqlite_master WHERE name LIKE 'comparison_%' LIMIT 1"
        ).fetchone():
            raise ValueError("Frozen comparison databases excluded")
        universe = snapshot_symbols(c, snapshot_id) if snapshot_id is not None else symbols
        assert universe is not None
        for symbol in sorted(set(universe) | {"SPY"}):
            try:
                rows = _load(c, symbol, start, end, dates)
            except IncompleteSeries as exc:
                # Only snapshot members are skippable; SPY and explicit symbols halt.
                if snapshot_id is None or symbol == "SPY":
                    raise
                skipped[symbol] = str(exc)
                if log:
                    log(f"skipped {exc}")
                continue
            hashes[symbol] = hashlib.sha256(
                json.dumps(rows, separators=(",", ":")).encode()
            ).hexdigest()
            data[symbol] = PriceSeries.from_bars(
                symbol, [(date.fromisoformat(r[0]), *r[1:6]) for r in rows]
            )
            row = c.execute("SELECT sector FROM instrument WHERE symbol=?", (symbol,)).fetchone()
            sectors[symbol] = row[0] or "unknown"
    regimes = regime_lookup(data["SPY"])
    limits = RiskLimits(
        max_position_concentration_pct=max_position_pct,
        max_correlated_exposure_pct=max_sector_pct,
    )
    selected = {s: data[s] for s in sorted(universe) if s not in skipped}
    if not selected:
        raise ValueError("No symbol has complete bars over the window")

    def signals() -> dict:
        return {
            s: composite_signal_fn(
                [(st.key, signal_fn_for(st, regime_by_date=regimes)) for st in strategies]
            )
            for s in selected
        }

    def run(costs: CostModel, spread: float) -> FundedReplay:
        return run_funded_replay(
            selected,
            signals(),
            sectors,
            limits=limits,
            cost_model=costs,
            spread_bps=spread,
            initial_cash=initial_cash,
            max_position_ceiling_pct=max_position_pct,
            max_sector_ceiling_pct=max_sector_pct,
        )

    costs, spread_bps = COST_CASES[cost_case]
    result = run(costs, spread_bps)
    source_reference = hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()
    scenarios = {cost_case: (result, costs, spread_bps)}
    if cost_scenarios:
        for label, (scenario_costs, spread) in COST_CASES.items():
            if label not in scenarios:
                scenarios[label] = (run(scenario_costs, spread), scenario_costs, spread)
    version = (
        strategies[0].spec().version
        if len(strategies) == 1
        else ",".join(f"{s.key}@{s.spec().version}" for s in strategies)
    )
    diagnostics = {}
    for label, (outcome, scenario_costs, spread) in scenarios.items():
        diag = diagnose(
            outcome,
            start=start,
            end=end,
            initial_cash=initial_cash,
            source_reference=source_reference,
            strategy_version=version,
            cost_model_reference=json.dumps(asdict(scenario_costs), sort_keys=True)
            + f";spread_bps={spread}",
        )
        round_trip_pnl = sum(
            (Decimal(v) for v in diag["net_pnl_by_symbol_usd"].values()), Decimal(0)
        )
        diagnostics[label] = {
            "cost_model": asdict(scenario_costs),
            "spread_bps": spread,
            "diagnostics": diag,
            "passive_comparator": passive_comparator(
                selected,
                sectors,
                initial_cash=initial_cash,
                cost_model=scenario_costs,
                spread_bps=spread,
            ),
            "strategy_attribution": strategy_attribution(
                outcome, keys, round_trip_pnl=round_trip_pnl
            ),
            "max_drawdown_pct": max_drawdown_pct(outcome),
        }
    return {
        "status": "DESCRIPTIVE_UNVALIDATED",
        "strategy": ",".join(keys),
        "strategy_spec": asdict(strategies[0].spec()) if len(strategies) == 1 else None,
        "initial_cash_usd": str(money(initial_cash)),
        "window": [str(start), str(end)],
        "dataset_sha256_by_symbol": hashes,
        "sector_snapshot": {s: sectors[s] for s in sorted(selected)},
        "cost_model": asdict(costs),
        "spread_bps": int(spread_bps) if spread_bps == int(spread_bps) else spread_bps,
        "risk_limits": limits.model_dump(mode="json"),
        "result": asdict(result),
        "scenario_diagnostics": diagnostics,
        "scenario_policy": (
            "Fixed zero/base/stress cost cases; cent rounding retained; "
            "no strategy/risk optimization."
        ),
        "limitations": [
            "Already-observed history; not a fresh sealed test.",
            "Fixed surviving universe and current sector metadata; selection/PIT limitations.",
            "Split-adjusted prices; no dividend ledger or point-in-time earnings exclusion.",
            "Rule replay only; scanner price/ADV/event/promotion gates absent.",
            "Fixed modeled spread/slippage, no observed NBBO or queue/market impact.",
            "Same-bar stop-first; alphabetical admission, no portfolio optimization.",
            "Not calibrated or promoted; no forecast of reliable income.",
        ]
        + (
            []
            if (max_position_pct, max_sector_pct) == (5, 20)
            else [
                "Passive comparator keeps fixed 5% name/20% sector/60% total sizing; "
                "it does not use this run's position/sector caps."
            ]
        ),
        "strategies": keys,
        "strategy_specs": {s.key: asdict(s.spec()) for s in strategies},
        "composite_policy": (
            "Per symbol, strategies are evaluated in the listed priority order and the first "
            "long entry signal wins that session; the open position belongs to that strategy "
            "until its own stop/target/time stop exits it."
            if len(strategies) > 1
            else "Single strategy."
        ),
        "run_config": {
            "snapshot_id": snapshot_id,
            "symbols_requested": sorted(universe),
            "symbols_replayed": len(selected),
            "skipped_symbols": skipped,
            "max_position_pct": max_position_pct,
            "max_sector_pct": max_sector_pct,
            "passive_comparator_caps_pct": {"position": 5, "sector": 20, "gross": 60},
            "primary_cost_case": cost_case,
        },
        "strategy_attribution": diagnostics[cost_case]["strategy_attribution"],
    }


def markdown(report: dict) -> str:
    cfg = report["run_config"]
    lines = [
        f"# Funded replay: {report['strategy']}",
        "",
        f"Status: **{report['status']}** — descriptive, already-observed history; "
        "not a sealed test, promotion or income forecast.",
        "",
        f"- Window: {report['window'][0]} .. {report['window'][1]}",
        f"- Initial cash: ${report['initial_cash_usd']}",
        f"- Caps: {cfg['max_position_pct']}% per symbol, {cfg['max_sector_pct']}% per sector, "
        f"{report['risk_limits']['max_portfolio_exposure_pct']}% gross",
        f"- Symbols replayed: {cfg['symbols_replayed']}"
        + (f" (snapshot {cfg['snapshot_id']})" if cfg["snapshot_id"] is not None else ""),
        f"- Skipped (incomplete bars): {', '.join(sorted(cfg['skipped_symbols'])) or 'none'}",
        "",
        "## Scenarios",
        "",
        "| Cost case | Net P&L $ | Return % | Max DD % | Trades | Hit rate | PF | Costs $ |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for label, scenario in report["scenario_diagnostics"].items():
        d = scenario["diagnostics"]
        lines.append(
            f"| {label} | {d['income_targets']['full_period_net_pnl_usd']} "
            f"| {d['net_return_pct']:.2f} | {scenario['max_drawdown_pct']:.2f} "
            f"| {d['closed_trades']} | {_fmt(d['hit_rate'])} | {_fmt(d['profit_factor'])} "
            f"| {d['modeled_costs_usd']} |"
        )
    for label, scenario in report["scenario_diagnostics"].items():
        lines += [
            "",
            f"## Strategy attribution ({label})",
            "",
            "| Strategy | Entries | Trades | Hit rate | Net P&L $ | PF | Costs $ | Rejected |",
            "|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
        for key, a in scenario["strategy_attribution"].items():
            lines.append(
                f"| {key} | {a['entries']} | {a['closed_trades']} | {_fmt(a['hit_rate'])} "
                f"| {a['net_pnl_usd']} | {_fmt(a['profit_factor'])} | {a['modeled_costs_usd']} "
                f"| {a['rejected_entries']} |"
            )
    lines += ["", "## Limitations", ""] + [f"- {x}" for x in report["limitations"]]
    lines += ["", "Research signal only — no order was placed.", ""]
    return "\n".join(lines)


def _fmt(value: float | None) -> str:
    return "—" if value is None else f"{value:.2f}"


def _decimal(text: str) -> Decimal:
    try:
        value = Decimal(text)
    except InvalidOperation as exc:
        raise argparse.ArgumentTypeError(f"invalid amount {text!r}") from exc
    if not value.is_finite() or value <= 0:
        raise argparse.ArgumentTypeError("must be a positive amount")
    return value


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("database", type=Path)
    universe = p.add_mutually_exclusive_group(required=True)
    universe.add_argument("--symbols", nargs="+")
    universe.add_argument(
        "--snapshot-id",
        type=int,
        help="take symbols from data_snapshot; symbols with incomplete bars are skipped",
    )
    p.add_argument("--since", type=date.fromisoformat, required=True)
    p.add_argument(
        "--until",
        type=date.fromisoformat,
        default=DEFAULT_UNTIL,
        help=f"default {DEFAULT_UNTIL}; windows overlapping the sealed year are refused",
    )
    p.add_argument(
        "--strategy",
        default=DEFAULT_STRATEGY,
        help="daily strategy key, or a comma-separated priority list for a composite",
    )
    p.add_argument("--initial-cash", type=_decimal, default=Decimal("10000"))
    p.add_argument("--max-position-pct", type=float, default=5.0)
    p.add_argument("--max-sector-pct", type=float, default=20.0)
    p.add_argument("--cost-case", choices=sorted(COST_CASES), default="base")
    p.add_argument("--cost-scenarios", action="store_true")
    p.add_argument("--out", type=Path, help="write JSON here and a markdown summary beside it")
    a = p.parse_args(argv)
    try:
        check_window(a.since, a.until)
        resolve_strategies(a.strategy)
    except ValueError as exc:
        p.error(str(exc))
    if not 0 < a.max_position_pct <= HARD_MAX_SYMBOL_PCT:
        p.error(f"--max-position-pct must be in (0, {HARD_MAX_SYMBOL_PCT}] (paper ledger maximum)")
    if not 0 < a.max_sector_pct <= HARD_MAX_SECTOR_PCT:
        p.error(f"--max-sector-pct must be in (0, {HARD_MAX_SECTOR_PCT}] (paper ledger maximum)")
    if a.out is not None and a.out.suffix != ".json":
        p.error("--out must name a .json file")
    return a


def main(argv: Sequence[str] | None = None) -> int:
    a = parse_args(argv)
    started = time.monotonic()
    report = replay(
        a.database,
        a.symbols,
        a.since,
        a.until,
        cost_scenarios=a.cost_scenarios,
        strategy=a.strategy,
        snapshot_id=a.snapshot_id,
        initial_cash=a.initial_cash,
        max_position_pct=a.max_position_pct,
        max_sector_pct=a.max_sector_pct,
        cost_case=a.cost_case,
        log=lambda line: print(line, file=sys.stderr),
    )
    text = json.dumps(report, default=str, indent=2)
    if a.out is None:
        print(text)
    else:
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(text + "\n")
        a.out.with_suffix(".md").write_text(markdown(report))
        print(f"wrote {a.out} and {a.out.with_suffix('.md')}", file=sys.stderr)
    print(f"elapsed {time.monotonic() - started:.1f}s", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
