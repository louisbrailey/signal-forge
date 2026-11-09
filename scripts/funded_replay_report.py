"""Read-only descriptive replay of frozen daily baseline rules, never promotion.

No study databases, provider requests, account writes or new sealed looks.
Any registered daily strategy runs long-only; a comma-separated ``--strategy``
list is a priority-ordered per-symbol composite with per-strategy attribution.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sqlite3
import sys
import time
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import asdict
from datetime import date
from decimal import ROUND_CEILING, Decimal, InvalidOperation
from itertools import pairwise
from pathlib import Path
from typing import Any

from signalforge.backtest.actions import Dividend
from signalforge.backtest.costs import CostModel
from signalforge.backtest.funded import (
    FundedReplay,
    composite_signal_fn,
    money,
    run_funded_replay,
    sell_price,
)
from signalforge.config.research import RiskLimits
from signalforge.data.calendar import sessions
from signalforge.data.series import PriceSeries
from signalforge.domain import Horizon
from signalforge.paper.ledger import (
    HARD_MAX_GROSS_PCT,
    HARD_MAX_OPEN_RISK_PCT,
    HARD_MAX_SECTOR_PCT,
    HARD_MAX_SYMBOL_PCT,
)
from signalforge.research.funded_diagnostics import diagnose, passive_comparator
from signalforge.research.regime import regime_lookup
from signalforge.research.strategies import BaselineStrategy, default_strategies, signal_fn_for

# The sealed final-test year is never read: development windows end before it.
SEALED_START = date(2025, 9, 8)
SEALED_END = date(2026, 9, 8)
DEFAULT_UNTIL = date(2025, 9, 7)
DEFAULT_STRATEGY = "trend_continuation.short_swing"
DEFAULT_MAX_OPEN_RISK_PCT = 1.5
DEFAULT_MAX_GROSS_PCT = 60.0
TRADING_SESSIONS_PER_YEAR = 252
SHARPE_POLICY = (
    "Annualised Sharpe: mean / sample stdev of session-to-session simple returns of the "
    f"modeled liquidation value (first from initial cash), x sqrt({TRADING_SESSIONS_PER_YEAR}); "
    "risk-free rate 0."
)
BENCHMARK_POLICY = (
    "SPY buy-and-hold, total return: all initial cash in whole SPY shares at the first "
    "session open with the same fill penalty and commissions. SPY cash dividends "
    "(dividend_event, converted to the split-adjusted bars' share basis) accrue to shares "
    "held entering each ex-date and are credited on the pay date; that cash, with any "
    "residual cash, is reinvested in whole shares at the pay date's open under the same "
    "cost model. Marked at each close net of exit costs plus declared-but-unpaid "
    "dividends; liquidated at the last close."
)
EXPOSURE_MATCHED_POLICY = (
    "Exposure-matched SPY: frictionless reference holding SPY total return (close-to-close "
    "plus ex-date dividends; first session from its open) at a constant fraction of value "
    "equal to this cost case's mean session exposure, rebalanced daily, the rest in cash "
    "at 0%. No costs and not tradable; it shows how much of a run's smaller drawdown "
    "lower exposure alone explains."
)
ACTIVE_WINDOW_POLICY = (
    "Active window: from the first session on which any entry decision occurred, so the "
    "signal warm-up (no history before --since is loaded; 252-session rules sit in cash "
    "for about a year) is not charged against the strategy. The strategy is all cash "
    "until then; SPY total-return buy-and-hold starts at that session's open."
)
DIVIDEND_POLICY = (
    "Cash dividends come from dividend_event for every replayed symbol that has rows "
    "(amounts divided by every later split_event ratio, since bars are split-adjusted to "
    "the current share basis); a symbol without rows is credited no dividends, which "
    "understates its holdings. Dividends accrue to shares held entering the ex-date and "
    "are paid as cash on the pay date; they are not attributed to strategies."
)
OPEN_RISK_NOTE = (
    "Open risk is measured per held position from max(entry, mark) down to the stop fill, "
    "so unrealised gains in winners consume the open-risk budget; a candidate whose risk "
    "would exceed the remaining budget is rejected outright (risk.engine.size_position), "
    "not trimmed. Rejection counts are candidate-days: a signal re-proposed on each "
    "session while the book is full is counted every session; episodes count runs of "
    "consecutive sessions for the same symbol and reason."
)

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


def _dividends(
    conn: sqlite3.Connection, symbol: str, series: PriceSeries, start: date, end: date
) -> list[Dividend]:
    """Cash dividends with ex-dates in the window, on the bars' split-adjusted basis.

    Raises rather than dropping an event whose ex-date is not a replay session or
    whose pay date is missing, and when a split inside the window is not already
    reflected in the bars (the conversion assumes split-adjusted bars)."""
    splits = conn.execute(
        "SELECT execution_date, split_from, split_to FROM split_event WHERE symbol=?",
        (symbol,),
    ).fetchall()
    index = {d: i for i, d in enumerate(series.dates)}
    for day, split_from, split_to in splits:
        i = index.get(date.fromisoformat(day))
        if i:
            jump = math.log(float(series.close[i]) / float(series.close[i - 1]))
            if abs(jump + math.log(split_to / split_from)) < abs(jump):
                raise ValueError(f"{symbol}: bars are not adjusted for the {day} split")
    rows = conn.execute(
        """SELECT ex_dividend_date, pay_date, cash_amount, currency, source
        FROM dividend_event WHERE symbol=? AND ex_dividend_date BETWEEN ? AND ?
        ORDER BY ex_dividend_date""",
        (symbol, str(start), str(end)),
    ).fetchall()
    out = []
    for ex, pay, amount, currency, source in rows:
        ex_date = date.fromisoformat(ex)
        if ex_date not in index or not pay:
            raise ValueError(f"{symbol}: dividend {ex} is not a replay session or lacks a pay date")
        ratio = Decimal(1)
        for day, split_from, split_to in splits:
            if date.fromisoformat(day) > ex_date:
                ratio *= Decimal(str(split_to)) / Decimal(str(split_from))
        out.append(
            Dividend(
                symbol,
                ex_date,
                date.fromisoformat(pay),
                Decimal(str(amount)) / ratio,
                source,
                currency,
            )
        )
    return out


def max_drawdown_pct(result: FundedReplay) -> float:
    peak = Decimal(0)
    worst = Decimal(0)
    for mark in result.marks:
        value = Decimal(mark["net_liquidation_usd"])
        peak = max(peak, value)
        if peak > 0:
            worst = max(worst, (peak - value) / peak)
    return float(worst * 100)


def check_risk_caps(max_open_risk_pct: float, max_gross_pct: float) -> None:
    """Open-risk and gross caps may only narrow the paper ledger's hard maxima."""
    if not 0 < max_open_risk_pct <= HARD_MAX_OPEN_RISK_PCT:
        raise ValueError(
            f"--max-open-risk-pct must be in (0, {HARD_MAX_OPEN_RISK_PCT}] (paper ledger maximum)"
        )
    if not 0 < max_gross_pct <= HARD_MAX_GROSS_PCT:
        raise ValueError(
            f"--max-gross-pct must be in (0, {HARD_MAX_GROSS_PCT}] (paper ledger maximum)"
        )


def equity_metrics(
    values: Sequence[Decimal], *, initial_cash: Decimal, start: date, end: date
) -> dict[str, Any]:
    """Net return, CAGR, max drawdown, return/drawdown ratios and annualised Sharpe.

    ``values`` are one modeled liquidation value per session, in order. CAGR uses
    calendar days ``start..end`` inclusive over 365.25, as ``diagnose()`` does. The
    drawdown peak starts at ``initial_cash``. See :data:`SHARPE_POLICY`."""
    if not values or initial_cash <= 0:
        raise ValueError("Session values and positive initial cash required")
    series = [float(initial_cash), *(float(v) for v in values)]
    peak = worst = 0.0
    for value in series:
        peak = max(peak, value)
        worst = max(worst, (peak - value) / peak)
    growth = series[-1] / series[0]
    years = ((end - start).days + 1) / 365.25
    cagr = (growth ** (1 / years) - 1) * 100 if growth > 0 else -100.0
    net = (growth - 1) * 100
    dd = worst * 100
    returns = [b / a - 1 for a, b in pairwise(series) if a > 0]
    sharpe = None
    if len(returns) > 1:
        mean = sum(returns) / len(returns)
        sd = math.sqrt(sum((r - mean) ** 2 for r in returns) / (len(returns) - 1))
        sharpe = mean / sd * math.sqrt(TRADING_SESSIONS_PER_YEAR) if sd > 0 else None
    return {
        "net_return_pct": net,
        "cagr_pct": cagr,
        "max_drawdown_pct": dd,
        "return_to_max_drawdown": net / dd if dd > 0 else None,
        "cagr_to_max_drawdown": cagr / dd if dd > 0 else None,
        "sharpe_annualised": sharpe,
    }


def spy_benchmark(
    spy: PriceSeries,
    *,
    dividends: Sequence[Dividend] = (),
    initial_cash: Decimal,
    cost_model: CostModel,
    spread_bps: float,
    start: date,
    end: date,
    from_index: int = 0,
) -> dict[str, Any]:
    """Fully invested, whole-share SPY total-return buy-and-hold; see BENCHMARK_POLICY.

    ``from_index`` starts the holding at that session's open (the active window)."""
    penalty = (
        cost_model.slippage_bps + (spread_bps / 2 if cost_model.half_spread_fill_penalty else 0)
    ) / 10000
    cash = initial_cash
    shares = 0
    costs = Decimal(0)
    received = Decimal(0)
    reinvest_buys = 0
    receivables: list[tuple[date, Decimal]] = []
    values = []

    def buy(raw_open: float) -> tuple[Decimal, int]:
        nonlocal cash, shares, costs
        price = Decimal(str(raw_open * (1 + penalty))).quantize(
            Decimal("0.01"), rounding=ROUND_CEILING
        )
        n = int(cash / price)
        while n and price * n + money(cost_model.commission(n)) > cash:
            n -= 1
        if n:
            fee = money(cost_model.commission(n))
            cash -= price * n + fee
            shares += n
            costs += money((float(price) - raw_open) * n) + fee
        return price, n

    for i in range(from_index, len(spy)):
        day = spy.dates[i]
        for d in dividends:
            if d.ex_date == day and shares:
                amount = money(d.amount * shares)
                receivables.append((d.pay_date, amount))
                received += amount
        paid = sum((a for p, a in receivables if p <= day), Decimal(0))
        receivables = [r for r in receivables if r[0] > day]
        cash += paid
        if i == from_index:
            entry_price, _ = buy(float(spy.open[i]))
        elif paid:
            reinvest_buys += bool(buy(float(spy.open[i]))[1])
        due = sum((a for _, a in receivables), Decimal(0))
        values.append(
            cash
            + due
            + sell_price(float(spy.close[i]), penalty) * shares
            - money(cost_model.commission(shares))
        )
    raw_close = float(spy.close[-1])
    costs += money((raw_close - float(sell_price(raw_close, penalty))) * shares) + money(
        cost_model.commission(shares)
    )
    return {
        "symbol": "SPY",
        "policy": BENCHMARK_POLICY,
        "price_only": False,
        "start": str(spy.dates[from_index]),
        "shares": shares,
        "entry_price_usd": str(entry_price),
        "dividend_reinvestment_buys": reinvest_buys,
        "dividends_received_usd": str(received),
        "residual_cash_usd": str(money(cash)),
        "final_value_usd": str(money(values[-1])),
        "net_pnl_usd": str(money(values[-1] - initial_cash)),
        "modeled_costs_usd": str(money(costs)),
        **equity_metrics(values, initial_cash=initial_cash, start=start, end=end),
    }


def exposure_matched_spy(
    spy: PriceSeries,
    *,
    dividends: Sequence[Dividend] = (),
    exposure_pct: float,
    initial_cash: Decimal,
    start: date,
    end: date,
) -> dict[str, Any]:
    """Frictionless constant-exposure SPY total return; see EXPOSURE_MATCHED_POLICY."""
    if not math.isfinite(exposure_pct) or not 0 <= exposure_pct <= 100:
        raise ValueError("Exposure must be a percentage in [0, 100]")
    weight = exposure_pct / 100
    cash_per_share = {d.ex_date: float(d.amount) for d in dividends}
    value = float(initial_cash)
    values = []
    for i, day in enumerate(spy.dates):
        prior = float(spy.open[0]) if i == 0 else float(spy.close[i - 1])
        paid = cash_per_share.get(day, 0.0) if i else 0.0
        value *= 1 + weight * ((float(spy.close[i]) + paid) / prior - 1)
        values.append(Decimal(str(value)))
    return {
        "symbol": "SPY",
        "policy": EXPOSURE_MATCHED_POLICY,
        "exposure_pct": exposure_pct,
        **equity_metrics(values, initial_cash=initial_cash, start=start, end=end),
    }


def rejection_episodes(result: FundedReplay) -> dict[str, dict[str, int]]:
    """Per rejection reason: candidate-days, distinct symbols and episodes, where an
    episode is a run of consecutive sessions rejecting the same symbol for that reason."""
    index = {m["day"]: i for i, m in enumerate(result.marks)}
    by_reason: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
    for d in result.decisions:
        if d["status"] == "rejected":
            by_reason[d["reason"]][d["symbol"]].append(index[d["day"]])
    out = {}
    for reason, symbols in sorted(by_reason.items()):
        days = [sorted(v) for v in symbols.values()]
        out[reason] = {
            "candidate_days": sum(len(v) for v in days),
            "symbols": len(days),
            "episodes": sum(1 + sum(b != a + 1 for a, b in pairwise(v)) for v in days if v),
        }
    return out


def active_window(
    result: FundedReplay,
    values: Sequence[Decimal],
    spy: PriceSeries,
    *,
    dividends: Sequence[Dividend],
    initial_cash: Decimal,
    cost_model: CostModel,
    spread_bps: float,
    end: date,
) -> dict[str, Any] | None:
    """Strategy and SPY metrics from the first entry decision; see ACTIVE_WINDOW_POLICY."""
    days = [m["day"] for m in result.marks]
    if not result.decisions:
        return None
    k = min(days.index(d["day"]) for d in result.decisions)
    if any(v != initial_cash for v in values[:k]):
        raise ValueError("Strategy value moved before its first entry decision")
    first = date.fromisoformat(days[k])
    return {
        "start": str(first),
        "policy": ACTIVE_WINDOW_POLICY,
        "strategy": equity_metrics(values[k:], initial_cash=initial_cash, start=first, end=end),
        "benchmark": spy_benchmark(
            spy,
            dividends=dividends,
            initial_cash=initial_cash,
            cost_model=cost_model,
            spread_bps=spread_bps,
            start=first,
            end=end,
            from_index=k,
        ),
    }


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
    max_open_risk_pct: float = DEFAULT_MAX_OPEN_RISK_PCT,
    max_gross_pct: float = DEFAULT_MAX_GROSS_PCT,
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
    check_risk_caps(max_open_risk_pct, max_gross_pct)
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
    dividends: dict[str, list[Dividend]] = {}
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
            dividends[symbol] = _dividends(c, symbol, data[symbol], start, end)
    regimes = regime_lookup(data["SPY"])
    limits = RiskLimits(
        max_position_concentration_pct=max_position_pct,
        max_correlated_exposure_pct=max_sector_pct,
        max_daily_portfolio_risk_pct=max_open_risk_pct,
        max_portfolio_exposure_pct=max_gross_pct,
    )
    selected = {s: data[s] for s in sorted(universe) if s not in skipped}
    if not selected:
        raise ValueError("No symbol has complete bars over the window")
    replay_dividends = tuple(d for s in selected for d in dividends[s])
    dividend_reference = hashlib.sha256(
        json.dumps(
            [[d.symbol, str(d.ex_date), str(d.pay_date), str(d.amount)] for d in replay_dividends]
            + [[d.symbol, str(d.ex_date), str(d.amount)] for d in dividends["SPY"]],
            separators=(",", ":"),
        ).encode()
    ).hexdigest()

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
            dividends=replay_dividends,
            max_position_ceiling_pct=max_position_pct,
            max_sector_ceiling_pct=max_sector_pct,
            max_gross_ceiling_pct=max_gross_pct,
            max_open_risk_ceiling_pct=max_open_risk_pct,
        )

    costs, spread_bps = COST_CASES[cost_case]
    result = run(costs, spread_bps)
    source_reference = hashlib.sha256(
        json.dumps({**hashes, "dividend_events": dividend_reference}, sort_keys=True).encode()
    ).hexdigest()
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
        values = [Decimal(m["net_liquidation_usd"]) for m in outcome.marks]
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
            "risk_adjusted": {
                **equity_metrics(values, initial_cash=initial_cash, start=start, end=end),
                "sharpe_policy": SHARPE_POLICY,
            },
            "benchmark": spy_benchmark(
                data["SPY"],
                dividends=dividends["SPY"],
                initial_cash=initial_cash,
                cost_model=scenario_costs,
                spread_bps=spread,
                start=start,
                end=end,
            ),
            "exposure_matched_benchmark": exposure_matched_spy(
                data["SPY"],
                dividends=dividends["SPY"],
                exposure_pct=diag["average_session_exposure_pct"] or 0.0,
                initial_cash=initial_cash,
                start=start,
                end=end,
            ),
            "active_window": active_window(
                outcome,
                values,
                data["SPY"],
                dividends=dividends["SPY"],
                initial_cash=initial_cash,
                cost_model=scenario_costs,
                spread_bps=spread,
                end=end,
            ),
            "rejection_episodes": rejection_episodes(outcome),
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
            "Split-adjusted prices; no point-in-time earnings exclusion.",
            DIVIDEND_POLICY
            + f" Symbols with dividend rows: {sum(bool(dividends[s]) for s in selected)} "
            f"of {len(selected)}.",
            "The passive_comparator reference credits no dividends.",
            OPEN_RISK_NOTE,
            "Rule replay only; scanner price/ADV/event/promotion gates absent.",
            "Fixed modeled spread/slippage, no observed NBBO or queue/market impact.",
            "Same-bar stop-first; alphabetical admission, no portfolio optimization.",
            "Not calibrated or promoted; no forecast of reliable income.",
            BENCHMARK_POLICY,
            EXPOSURE_MATCHED_POLICY,
            ACTIVE_WINDOW_POLICY,
        ]
        + (
            []
            if (max_position_pct, max_sector_pct, max_gross_pct) == (5, 20, 60)
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
            "max_open_risk_pct": max_open_risk_pct,
            "max_gross_pct": max_gross_pct,
            "dividend_events_by_symbol": {
                s: len(dividends[s]) for s in sorted(dividends) if dividends[s]
            },
            "dividend_events_sha256": dividend_reference,
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
        f"{report['risk_limits']['max_portfolio_exposure_pct']}% gross, "
        f"{report['risk_limits']['max_daily_portfolio_risk_pct']}% open risk",
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
    lines += [
        "",
        "## Risk-adjusted vs SPY total-return buy-and-hold",
        "",
        "| Cost case | Series | Return % | CAGR % | Max DD % | Return/DD | Sharpe |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for label, scenario in report["scenario_diagnostics"].items():
        matched = scenario["exposure_matched_benchmark"]
        series = [
            ("strategy", scenario["risk_adjusted"]),
            ("SPY", scenario["benchmark"]),
            (f"SPY at {matched['exposure_pct']:.1f}% exposure", matched),
        ]
        active = scenario["active_window"]
        if active is not None:
            series += [
                (f"strategy from {active['start']}", active["strategy"]),
                (f"SPY from {active['start']}", active["benchmark"]),
            ]
        for name, m in series:
            lines.append(
                f"| {label} | {name} | {m['net_return_pct']:.2f} | {m['cagr_pct']:.2f} "
                f"| {m['max_drawdown_pct']:.2f} | {_fmt(m['return_to_max_drawdown'])} "
                f"| {_fmt(m['sharpe_annualised'])} |"
            )
    lines += [
        "",
        SHARPE_POLICY,
        "",
        BENCHMARK_POLICY,
        "",
        EXPOSURE_MATCHED_POLICY,
        "",
        ACTIVE_WINDOW_POLICY,
    ]
    for label, scenario in report["scenario_diagnostics"].items():
        lines += [
            "",
            f"## Rejections ({label})",
            "",
            "| Reason | Candidate-days | Symbols | Episodes |",
            "|---|---:|---:|---:|",
        ]
        for reason, r in scenario["rejection_episodes"].items():
            lines.append(f"| {reason} | {r['candidate_days']} | {r['symbols']} | {r['episodes']} |")
    lines += ["", OPEN_RISK_NOTE]
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
    p.add_argument(
        "--max-open-risk-pct",
        type=float,
        default=DEFAULT_MAX_OPEN_RISK_PCT,
        help=f"aggregate open risk cap, at most {HARD_MAX_OPEN_RISK_PCT} (paper ledger maximum)",
    )
    p.add_argument(
        "--max-gross-pct",
        type=float,
        default=DEFAULT_MAX_GROSS_PCT,
        help=f"gross exposure cap, at most {HARD_MAX_GROSS_PCT} (paper ledger maximum)",
    )
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
    try:
        check_risk_caps(a.max_open_risk_pct, a.max_gross_pct)
    except ValueError as exc:
        p.error(str(exc))
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
        max_open_risk_pct=a.max_open_risk_pct,
        max_gross_pct=a.max_gross_pct,
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
