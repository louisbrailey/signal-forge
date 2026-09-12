"""Deterministic simulator for the mechanical grid strategy.

The rules, stated exactly (all of them operate on DAILY bars):

* Each symbol carries an **anchor price**. The anchor starts at the close of the
  first session on which the symbol is tracked; that first session never trades.
* On every later session's close, exactly **one** evaluation happens per symbol:

  - ``close <= anchor * (1 - drop_pct)`` -> BUY ``buy_usd`` of stock;
  - ``close >= anchor * (1 + rise_pct)`` -> SELL ``sell_usd`` of stock, capped at
    the position's market value;
  - otherwise nothing happens and the anchor does not move.

* A triggered order fills at the **next session's open** for that symbol (the
  project's existing next-open convention), with slippage + half-spread applied
  against the trade. The anchor moves to the **decision close** only when an
  order actually fills: an order skipped for cash, the per-symbol cap, or the
  minimum notional leaves the level armed.
* Constraints: a symbol's cost basis may never exceed ``per_symbol_cap``; cash
  may never go negative; a sell may never exceed the shares held; an order below
  ``min_order_usd`` is skipped. A sell that would leave a remainder worth less
  than ``min_order_usd`` sells the WHOLE position instead — otherwise the stub
  could never be sold again and the symbol would freeze.

Determinism: pure arithmetic over the input arrays; no RNG, no wall-clock, no
database. Ordering inside one session is fixed — sells fill before buys (so the
day's proceeds can fund the day's purchases), and within each group symbols are
processed in **universe order**, which is what decides who gets scarce cash.

On :mod:`signalforge.research.portfolio_metrics`: that module builds a
*sequential* equity curve from R-multiple trades, where R is the entry-to-stop
distance. The grid has no stop, so R is undefined and those metrics are not
applicable. The metrics below are therefore computed from the **daily
mark-to-market equity curve**, which is strictly more informative for a
continuously-invested rule, using the same annualisation conventions.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

from signalforge.grid.config import GridParams

__all__ = [
    "GridSeries",
    "GridState",
    "GridDecision",
    "GridTrade",
    "GridPositionSnapshot",
    "GridMetrics",
    "BenchmarkResult",
    "GridBacktestResult",
    "decide",
    "execute_fill",
    "fill_price",
    "initial_anchor",
    "run_grid_backtest",
]

# Fractional-share quantities are stored as Numeric(20, 6); the simulator uses
# exactly the same resolution so a backtest and the live job cannot drift.
QTY_DP = 6
_EPS = 1e-9

BUY = "buy"
SELL = "sell"
NONE = "none"


def _q(x: float) -> float:
    """Position quantities, rounded to the stored precision."""
    return round(x, QTY_DP)


def _order_qty(usd: float, price: float) -> float:
    """Shares for a NOTIONAL order, rounded DOWN to the stored precision.

    Rounding to nearest would let ``qty * price`` land a fraction of a cent above
    the dollar amount asked for, which then trips the per-symbol cap and the cash
    check at fill time. With ``per_symbol_cap == buy_usd`` that rejected roughly
    half of every buy in the 1000-symbol / $5-cap run — a pure rounding artifact,
    not an economic constraint. A real fractional-share broker fills at most the
    notional requested, so floor is also the honest model.
    """
    scale = 10**QTY_DP
    return math.floor(max(usd, 0.0) / price * scale) / scale


@dataclass(frozen=True, slots=True)
class GridSeries:
    """The only market data the grid needs: daily opens and closes."""

    symbol: str
    dates: tuple[date, ...]
    open: tuple[float, ...]
    close: tuple[float, ...]

    def __post_init__(self) -> None:
        if not (len(self.dates) == len(self.open) == len(self.close)):
            raise ValueError("GridSeries arrays must all match len(dates)")

    def __len__(self) -> int:
        return len(self.dates)

    @classmethod
    def from_price_series(cls, ps: Any) -> GridSeries:
        """Adapt a :class:`signalforge.data.series.PriceSeries`."""
        return cls(
            symbol=ps.symbol,
            dates=tuple(ps.dates),
            open=tuple(float(x) for x in ps.open),
            close=tuple(float(x) for x in ps.close),
        )


@dataclass(frozen=True, slots=True)
class GridDecision:
    """The outcome of one evaluation of the rule at one close.

    ``action`` is ``buy`` / ``sell`` / ``none``; ``reason`` always explains it,
    including why a triggered order was skipped.
    """

    action: str
    reason: str
    anchor_before: float
    close: float
    usd: float = 0.0
    buy_level: float = 0.0
    sell_level: float = 0.0
    # "No order, but adopt ``close`` as the new anchor anyway" — only ever set
    # for a rise past the sell level with nothing to sell, and only when
    # ``GridParams.reanchor_on_untradeable_rise`` is on.
    reanchor: bool = False

    @property
    def triggered(self) -> bool:
        """Whether a level was breached, regardless of whether an order was sent."""
        return self.reason not in ("no_trigger",)

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "reason": self.reason,
            "anchor_before": round(self.anchor_before, 6),
            "close": round(self.close, 6),
            "usd": round(self.usd, 6),
            "buy_level": round(self.buy_level, 6),
            "sell_level": round(self.sell_level, 6),
            "reanchor": self.reanchor,
        }


@dataclass(frozen=True, slots=True)
class GridTrade:
    """One filled order. Immutable; the live table mirrors these fields."""

    symbol: str
    side: str  # "buy" | "sell"
    decision_date: date  # the close the rule fired on
    session_date: date  # the session whose OPEN filled it
    qty: float
    price: float  # fill price, costs already applied against the trade
    usd: float  # signed cash impact is -usd for a buy, +usd for a sell
    commission: float
    anchor_before: float
    anchor_after: float
    realized_pnl: float  # sells only; 0.0 for a buy
    raw_open: float  # the untouched session open, for auditability

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "side": self.side,
            "decision_date": self.decision_date.isoformat(),
            "session_date": self.session_date.isoformat(),
            "qty": round(self.qty, QTY_DP),
            "price": round(self.price, 6),
            "usd": round(self.usd, 6),
            "commission": round(self.commission, 6),
            "anchor_before": round(self.anchor_before, 6),
            "anchor_after": round(self.anchor_after, 6),
            "realized_pnl": round(self.realized_pnl, 6),
            "raw_open": round(self.raw_open, 6),
        }


@dataclass(frozen=True, slots=True)
class GridPositionSnapshot:
    symbol: str
    qty: float
    cost_basis: float
    anchor_price: float
    last_close: float

    @property
    def market_value(self) -> float:
        return self.qty * self.last_close

    @property
    def unrealized_pnl(self) -> float:
        return self.market_value - self.cost_basis

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "qty": round(self.qty, QTY_DP),
            "cost_basis": round(self.cost_basis, 6),
            "anchor_price": round(self.anchor_price, 6),
            "last_close": round(self.last_close, 6),
            "market_value": round(self.market_value, 6),
            "unrealized_pnl": round(self.unrealized_pnl, 6),
        }


# --------------------------------------------------------------------------- #
# The rule — shared verbatim by the backtest and the live daily job
# --------------------------------------------------------------------------- #
def decide(
    *,
    close: float,
    anchor: float,
    qty: float,
    cost_basis: float,
    cash: float,
    params: GridParams,
) -> GridDecision:
    """Evaluate the grid rule for ONE symbol at ONE close.

    Pure: no I/O, no state mutation. Both the simulator and ``grid.live`` call
    this, so the live job can never drift from the backtested rule.
    """
    buy_level = anchor * (1.0 - params.drop_pct)
    sell_level = anchor * (1.0 + params.rise_pct)

    if close <= buy_level + _EPS:
        if cost_basis + params.buy_usd > params.per_symbol_cap + _EPS:
            return GridDecision(
                NONE, "skip_per_symbol_cap", anchor, close, 0.0, buy_level, sell_level
            )
        if cash + _EPS < params.buy_usd + params.commission_min_per_order:
            return GridDecision(
                NONE, "skip_insufficient_cash", anchor, close, 0.0, buy_level, sell_level
            )
        if params.buy_usd + _EPS < params.min_order_usd:
            return GridDecision(
                NONE, "skip_min_notional", anchor, close, 0.0, buy_level, sell_level
            )
        return GridDecision(
            BUY, "buy_trigger", anchor, close, params.buy_usd, buy_level, sell_level
        )

    if close >= sell_level - _EPS:
        if qty <= 0:
            # Nothing to sell. Whether the anchor ratchets up to this close is
            # the one genuine ambiguity in the operator's rule — see
            # GridParams.reanchor_on_untradeable_rise.
            return GridDecision(
                NONE,
                "skip_no_position",
                anchor,
                close,
                0.0,
                buy_level,
                sell_level,
                reanchor=params.reanchor_on_untradeable_rise,
            )
        usd = min(params.sell_usd, qty * close)
        if usd + _EPS < params.min_order_usd:
            return GridDecision(
                NONE, "skip_min_notional", anchor, close, 0.0, buy_level, sell_level
            )
        return GridDecision(SELL, "sell_trigger", anchor, close, usd, buy_level, sell_level)

    return GridDecision(NONE, "no_trigger", anchor, close, 0.0, buy_level, sell_level)


def fill_price(raw_open: float, side: str, params: GridParams) -> float:
    """Next-session open with slippage + half-spread applied AGAINST the trade."""
    slip = params.slippage_frac
    return raw_open * (1.0 + slip) if side == BUY else raw_open * (1.0 - slip)


def _commission(params: GridParams, qty: float) -> float:
    raw = abs(qty) * params.commission_per_share
    return max(raw, params.commission_min_per_order) if qty else 0.0


# --------------------------------------------------------------------------- #
# Simulator state
# --------------------------------------------------------------------------- #
@dataclass(slots=True)
class GridState:
    """Mutable per-symbol grid state.

    The live job rehydrates one of these from a ``grid_position`` row and hands
    it to :func:`execute_fill`, so a simulated fill and a live fill run the
    exact same arithmetic.
    """

    symbol: str
    qty: float = 0.0
    cost_basis: float = 0.0
    anchor: float = 0.0
    tracking: bool = False
    last_close: float = 0.0
    realized_pnl: float = 0.0
    buys: int = 0
    sells: int = 0
    max_cost_basis: float = 0.0
    traded_notional: float = 0.0


@dataclass(slots=True)
class _Pending:
    decision: GridDecision
    decision_date: date


# --------------------------------------------------------------------------- #
# Metrics
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class GridMetrics:
    start_equity: float
    end_equity: float
    total_return_pct: float
    cagr_pct: float
    max_drawdown_pct: float
    ann_vol_pct: float
    sharpe: float
    sortino: float
    exposure: float  # mean invested fraction of equity across the daily curve
    turnover_per_year: float  # traded notional per year / mean equity
    trades_per_year: float
    n_trades: int
    n_buys: int
    n_sells: int
    span_days: int
    sessions: int

    def to_dict(self) -> dict[str, float | int]:
        return {
            "start_equity": self.start_equity,
            "end_equity": self.end_equity,
            "total_return_pct": self.total_return_pct,
            "cagr_pct": self.cagr_pct,
            "max_drawdown_pct": self.max_drawdown_pct,
            "ann_vol_pct": self.ann_vol_pct,
            "sharpe": self.sharpe,
            "sortino": self.sortino,
            "exposure": self.exposure,
            "turnover_per_year": self.turnover_per_year,
            "trades_per_year": self.trades_per_year,
            "n_trades": self.n_trades,
            "n_buys": self.n_buys,
            "n_sells": self.n_sells,
            "span_days": self.span_days,
            "sessions": self.sessions,
        }


@dataclass(frozen=True, slots=True)
class BenchmarkResult:
    """SPY buy-and-hold over exactly the same span, same cost model."""

    symbol: str
    available: bool
    detail: str = ""
    start_date: date | None = None
    end_date: date | None = None
    entry_price: float = 0.0
    exit_price: float = 0.0
    qty: float = 0.0
    start_equity: float = 0.0
    end_equity: float = 0.0
    total_return_pct: float = 0.0
    cagr_pct: float = 0.0
    max_drawdown_pct: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "available": self.available,
            "detail": self.detail,
            "start_date": self.start_date.isoformat() if self.start_date else None,
            "end_date": self.end_date.isoformat() if self.end_date else None,
            "entry_price": round(self.entry_price, 6),
            "exit_price": round(self.exit_price, 6),
            "qty": round(self.qty, QTY_DP),
            "start_equity": round(self.start_equity, 2),
            "end_equity": round(self.end_equity, 2),
            "total_return_pct": self.total_return_pct,
            "cagr_pct": self.cagr_pct,
            "max_drawdown_pct": self.max_drawdown_pct,
        }


@dataclass(frozen=True, slots=True)
class GridBacktestResult:
    params: GridParams
    symbols: tuple[str, ...]
    skipped_symbols: tuple[str, ...]  # requested but no bars in the window
    start: date | None
    end: date | None
    trades: tuple[GridTrade, ...]
    positions: tuple[GridPositionSnapshot, ...]
    equity_curve: tuple[tuple[date, float, float, float], ...]  # (date, equity, cash, invested)
    final_cash: float
    metrics: GridMetrics
    benchmark: BenchmarkResult
    per_symbol_pnl: Mapping[str, float]
    pnl_distribution: Mapping[str, float]
    cash_utilisation: Mapping[str, float]
    symbols_at_cap: int
    symbols_traded: int
    skip_counts: Mapping[str, int]

    @property
    def realized_pnl(self) -> float:
        return sum(t.realized_pnl for t in self.trades)

    def to_dict(self) -> dict[str, Any]:
        return {
            "params": self.params.to_dict(),
            "universe_requested": len(self.symbols) + len(self.skipped_symbols),
            "symbols": list(self.symbols),
            "skipped_symbols": list(self.skipped_symbols),
            "start": self.start.isoformat() if self.start else None,
            "end": self.end.isoformat() if self.end else None,
            "metrics": self.metrics.to_dict(),
            "benchmark": self.benchmark.to_dict(),
            "final_cash": round(self.final_cash, 2),
            "realized_pnl": round(self.realized_pnl, 2),
            "symbols_at_cap": self.symbols_at_cap,
            "symbols_traded": self.symbols_traded,
            "skip_counts": dict(self.skip_counts),
            "cash_utilisation": dict(self.cash_utilisation),
            "pnl_distribution": dict(self.pnl_distribution),
            "per_symbol_pnl": {k: round(v, 4) for k, v in self.per_symbol_pnl.items()},
            "positions": [p.to_dict() for p in self.positions],
            "equity_curve": [
                [d.isoformat(), round(e, 4), round(c, 4), round(i, 4)]
                for d, e, c, i in self.equity_curve
            ],
            "trades": [t.to_dict() for t in self.trades],
        }


# --------------------------------------------------------------------------- #
# The simulator
# --------------------------------------------------------------------------- #
def run_grid_backtest(
    series_by_symbol: Mapping[str, GridSeries],
    params: GridParams,
    *,
    symbols: Sequence[str] | None = None,
    requested: Sequence[str] | None = None,
    benchmark: GridSeries | None = None,
    benchmark_symbol: str = "SPY",
) -> GridBacktestResult:
    """Run the grid over ``series_by_symbol``.

    ``symbols`` fixes the processing order (universe rank order), which is what
    decides who gets scarce cash; it defaults to the mapping's key order.
    ``requested`` is the full list asked for, so symbols with no bars in the
    window can be reported rather than silently dropped.
    """
    order = [s for s in (symbols if symbols is not None else list(series_by_symbol)) if s]
    order = [s for s in order if s in series_by_symbol and len(series_by_symbol[s]) > 0]
    asked = list(requested) if requested is not None else list(order)
    skipped = tuple(s for s in asked if s not in order)

    state = {s: GridState(symbol=s) for s in order}
    # Per-symbol index into its own bar arrays, keyed by date for O(1) access.
    index_by_symbol: dict[str, dict[date, int]] = {
        s: {d: i for i, d in enumerate(series_by_symbol[s].dates)} for s in order
    }
    all_dates = sorted({d for s in order for d in series_by_symbol[s].dates})

    cash = params.starting_cash
    pending: dict[str, _Pending] = {}
    trades: list[GridTrade] = []
    equity_curve: list[tuple[date, float, float, float]] = []
    skip_counts: dict[str, int] = {}

    for day in all_dates:
        todays = [s for s in order if day in index_by_symbol[s]]

        # --- 1. fills at TODAY's open for orders decided on the previous close.
        #        Sells first so the day's proceeds can fund the day's buys.
        for want in (SELL, BUY):
            for sym in todays:
                pend = pending.get(sym)
                if pend is None or pend.decision.action != want:
                    continue
                del pending[sym]
                st = state[sym]
                ser = series_by_symbol[sym]
                idx = index_by_symbol[sym][day]
                trade, cash = execute_fill(
                    st, pend.decision, pend.decision_date, day, ser.open[idx], cash, params
                )
                if trade is None:
                    skip_counts["skip_at_fill"] = skip_counts.get("skip_at_fill", 0) + 1
                else:
                    trades.append(trade)

        # --- 2. one evaluation per symbol at TODAY's close.
        for sym in todays:
            st = state[sym]
            ser = series_by_symbol[sym]
            close = ser.close[index_by_symbol[sym][day]]
            st.last_close = close
            if not st.tracking:
                # The first session a symbol is seen only establishes the anchor;
                # close == anchor can never breach either level.
                st.anchor = close
                st.tracking = True
                continue
            dec = decide(
                close=close,
                anchor=st.anchor,
                qty=st.qty,
                cost_basis=st.cost_basis,
                cash=cash,
                params=params,
            )
            if dec.action == NONE:
                if dec.reason != "no_trigger":
                    skip_counts[dec.reason] = skip_counts.get(dec.reason, 0) + 1
                if dec.reanchor:
                    st.anchor = close  # the grid ratchets up with price
                continue
            pending[sym] = _Pending(decision=dec, decision_date=day)

        # --- 3. mark to market at today's close (forward-filled for stale symbols).
        invested = sum(st.qty * st.last_close for st in state.values() if st.qty > 0)
        equity_curve.append((day, cash + invested, cash, invested))

    positions = tuple(
        GridPositionSnapshot(
            symbol=st.symbol,
            qty=_q(st.qty),
            cost_basis=st.cost_basis,
            anchor_price=st.anchor,
            last_close=st.last_close,
        )
        for st in (state[s] for s in order)
        if st.qty > 0
    )
    per_symbol_pnl = {
        st.symbol: st.realized_pnl + (st.qty * st.last_close - st.cost_basis)
        for st in (state[s] for s in order)
        if st.buys or st.sells
    }
    metrics = _metrics(equity_curve, trades, params, state)
    bench = _benchmark(
        benchmark,
        benchmark_symbol,
        params.starting_cash,
        equity_curve[0][0] if equity_curve else None,
        equity_curve[-1][0] if equity_curve else None,
        params,
    )
    # "At cap" means the cap actually bit: the symbol bought at least once and
    # reached a cost basis where one more buy would have breached the cap.
    at_cap = sum(
        1
        for st in state.values()
        if st.buys and st.max_cost_basis + params.buy_usd > params.per_symbol_cap + _EPS
    )
    return GridBacktestResult(
        params=params,
        symbols=tuple(order),
        skipped_symbols=skipped,
        start=all_dates[0] if all_dates else None,
        end=all_dates[-1] if all_dates else None,
        trades=tuple(trades),
        positions=positions,
        equity_curve=tuple(equity_curve),
        final_cash=cash,
        metrics=metrics,
        benchmark=bench,
        per_symbol_pnl=per_symbol_pnl,
        pnl_distribution=_distribution(list(per_symbol_pnl.values())),
        cash_utilisation=_cash_stats(equity_curve, params),
        symbols_at_cap=at_cap,
        symbols_traded=sum(1 for st in state.values() if st.buys or st.sells),
        skip_counts=skip_counts,
    )


def execute_fill(
    st: GridState,
    dec: GridDecision,
    decision_date: date,
    session_date: date,
    raw_open: float,
    cash: float,
    params: GridParams,
) -> tuple[GridTrade | None, float]:
    """Fill ``dec`` at ``raw_open``, mutating ``st``. Returns (trade|None, new cash).

    Every constraint is re-checked against the ACTUAL fill price, so the
    invariants (cost basis <= cap, cash >= 0, sell <= holdings, notional >=
    minimum) hold exactly regardless of how the price moved overnight.
    """
    if raw_open <= 0:
        return None, cash
    px = fill_price(raw_open, dec.action, params)
    if px <= 0:
        return None, cash

    if dec.action == BUY:
        qty = _order_qty(params.buy_usd, px)
        if qty <= 0:
            return None, cash
        notional = qty * px
        comm = _commission(params, qty)
        outflow = notional + comm
        if notional + _EPS < params.min_order_usd:
            return None, cash
        if outflow > cash + _EPS:
            return None, cash
        if st.cost_basis + outflow > params.per_symbol_cap + _EPS:
            return None, cash
        cash -= outflow
        st.qty = _q(st.qty + qty)
        st.cost_basis += outflow
        st.max_cost_basis = max(st.max_cost_basis, st.cost_basis)
        st.buys += 1
        st.traded_notional += notional
        anchor_before, st.anchor = st.anchor, dec.close
        return (
            GridTrade(
                symbol=st.symbol,
                side=BUY,
                decision_date=decision_date,
                session_date=session_date,
                qty=qty,
                price=px,
                usd=outflow,
                commission=comm,
                anchor_before=anchor_before,
                anchor_after=st.anchor,
                realized_pnl=0.0,
                raw_open=raw_open,
            ),
            cash,
        )

    # --- SELL: never more than the shares held, never more than sell_usd.
    if st.qty <= 0:
        return None, cash
    qty = min(st.qty, _order_qty(params.sell_usd, px))
    qty = _q(qty)
    # Never leave an unsellable stub. A $10 sell out of a $10.50 position would
    # leave $0.50, which can never clear the per-order minimum again: the sell is
    # skipped forever, so the anchor never moves and the symbol freezes — on the
    # 10-year 100-symbol run that stranded 69 of 92 open positions. If the
    # remainder would fall below ``min_order_usd``, sell the whole position.
    residual = _q(st.qty - qty)
    if 0 < residual * px < params.min_order_usd:
        qty = st.qty
    if qty <= 0:
        return None, cash
    gross = qty * px
    comm = _commission(params, qty)
    proceeds = gross - comm
    if proceeds + _EPS < params.min_order_usd:
        return None, cash
    cost_removed = st.cost_basis * (qty / st.qty) if st.qty > 0 else 0.0
    realized = proceeds - cost_removed
    cash += proceeds
    st.qty = _q(st.qty - qty)
    st.cost_basis = 0.0 if st.qty <= 0 else st.cost_basis - cost_removed
    st.realized_pnl += realized
    st.sells += 1
    st.traded_notional += gross
    anchor_before, st.anchor = st.anchor, dec.close
    return (
        GridTrade(
            symbol=st.symbol,
            side=SELL,
            decision_date=decision_date,
            session_date=session_date,
            qty=qty,
            price=px,
            usd=proceeds,
            commission=comm,
            anchor_before=anchor_before,
            anchor_after=st.anchor,
            realized_pnl=realized,
            raw_open=raw_open,
        ),
        cash,
    )


# --------------------------------------------------------------------------- #
# Metric helpers
# --------------------------------------------------------------------------- #
def _drawdown_pct(values: Sequence[float]) -> float:
    peak = float("-inf")
    worst = 0.0
    for v in values:
        peak = max(peak, v)
        if peak > 0:
            worst = max(worst, (peak - v) / peak)
    return worst * 100.0


def _metrics(
    curve: Sequence[tuple[date, float, float, float]],
    trades: Sequence[GridTrade],
    params: GridParams,
    state: Mapping[str, GridState],
) -> GridMetrics:
    if not curve:
        return GridMetrics(
            params.starting_cash,
            params.starting_cash,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0,
            0,
            0,
            0,
            0,
        )
    equities = [e for _, e, _, _ in curve]
    start_eq = params.starting_cash
    end_eq = equities[-1]
    span_days = max((curve[-1][0] - curve[0][0]).days, 1)
    years = span_days / 365.25

    rets = [
        (equities[i] / equities[i - 1] - 1.0)
        for i in range(1, len(equities))
        if equities[i - 1] > 0
    ]
    n = len(rets)
    mean = sum(rets) / n if n else 0.0
    var = sum((r - mean) ** 2 for r in rets) / n if n else 0.0
    std = math.sqrt(var)
    downside = [r for r in rets if r < 0]
    dstd = math.sqrt(sum(r * r for r in downside) / n) if downside and n else 0.0
    ann = math.sqrt(252.0)
    sharpe = (mean / std) * ann if std > 0 else 0.0
    sortino = (mean / dstd) * ann if dstd > 0 else 0.0

    total_return = end_eq / start_eq - 1.0
    cagr = (end_eq / start_eq) ** (1.0 / years) - 1.0 if years > 0 and end_eq > 0 else 0.0
    exposure = sum(inv / eq for _, eq, _, inv in curve if eq > 0) / len(curve)
    mean_equity = sum(equities) / len(equities)
    traded = sum(st.traded_notional for st in state.values())
    turnover = (traded / mean_equity / years) if mean_equity > 0 and years > 0 else 0.0
    n_buys = sum(1 for t in trades if t.side == BUY)
    n_sells = len(trades) - n_buys

    return GridMetrics(
        start_equity=round(start_eq, 2),
        end_equity=round(end_eq, 2),
        total_return_pct=round(total_return * 100.0, 3),
        cagr_pct=round(cagr * 100.0, 3),
        max_drawdown_pct=round(_drawdown_pct(equities), 3),
        ann_vol_pct=round(std * ann * 100.0, 3),
        sharpe=round(sharpe, 3),
        sortino=round(sortino, 3),
        exposure=round(exposure, 4),
        turnover_per_year=round(turnover, 3),
        trades_per_year=round(len(trades) / years, 2) if years > 0 else 0.0,
        n_trades=len(trades),
        n_buys=n_buys,
        n_sells=n_sells,
        span_days=span_days,
        sessions=len(curve),
    )


def _percentile(sorted_vals: Sequence[float], p: float) -> float:
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    k = (len(sorted_vals) - 1) * p
    lo = math.floor(k)
    hi = math.ceil(k)
    if lo == hi:
        return sorted_vals[int(k)]
    return sorted_vals[lo] * (hi - k) + sorted_vals[hi] * (k - lo)


def _distribution(values: Sequence[float]) -> dict[str, float]:
    if not values:
        return {"n": 0}
    vals = sorted(values)
    return {
        "n": len(vals),
        "n_positive": float(sum(1 for v in vals if v > 0)),
        "n_negative": float(sum(1 for v in vals if v < 0)),
        "total": round(sum(vals), 4),
        "mean": round(sum(vals) / len(vals), 4),
        "p10": round(_percentile(vals, 0.10), 4),
        "p25": round(_percentile(vals, 0.25), 4),
        "median": round(_percentile(vals, 0.50), 4),
        "p75": round(_percentile(vals, 0.75), 4),
        "p90": round(_percentile(vals, 0.90), 4),
        "min": round(vals[0], 4),
        "max": round(vals[-1], 4),
    }


def _cash_stats(
    curve: Sequence[tuple[date, float, float, float]], params: GridParams
) -> dict[str, float]:
    if not curve:
        return {}
    cash_vals = [c for _, _, c, _ in curve]
    deployed = [inv / eq for _, eq, _, inv in curve if eq > 0]
    invested = [inv for _, _, _, inv in curve]
    return {
        "min_cash": round(min(cash_vals), 2),
        "max_cash": round(max(cash_vals), 2),
        "mean_cash": round(sum(cash_vals) / len(cash_vals), 2),
        "final_cash": round(cash_vals[-1], 2),
        "peak_invested": round(max(invested), 2),
        "mean_deployed_fraction": round(sum(deployed) / len(deployed), 4) if deployed else 0.0,
        "max_deployed_fraction": round(max(deployed), 4) if deployed else 0.0,
        "starting_cash": round(params.starting_cash, 2),
        "budget_if_every_symbol_capped": round(params.max_committed_usd, 2),
    }


def _benchmark(
    series: GridSeries | None,
    symbol: str,
    starting_cash: float,
    start: date | None,
    end: date | None,
    params: GridParams,
) -> BenchmarkResult:
    """Buy-and-hold ``symbol`` with the same cash, over exactly the grid's span."""
    if series is None or len(series) == 0:
        return BenchmarkResult(symbol, False, detail=f"no {symbol} bars for the window")
    if start is None or end is None:
        return BenchmarkResult(symbol, False, detail="the grid produced no sessions")
    idx = [i for i, d in enumerate(series.dates) if start <= d <= end]
    if not idx:
        return BenchmarkResult(symbol, False, detail=f"no {symbol} bars inside {start}..{end}")
    first, last = idx[0], idx[-1]
    entry = fill_price(series.open[first], BUY, params)
    if entry <= 0:
        return BenchmarkResult(symbol, False, detail=f"{symbol} open at {series.dates[first]} <= 0")
    qty = starting_cash / entry
    equities = [qty * series.close[i] for i in idx]
    end_eq = equities[-1]
    span_days = max((series.dates[last] - series.dates[first]).days, 1)
    years = span_days / 365.25
    cagr = (end_eq / starting_cash) ** (1.0 / years) - 1.0 if years > 0 and end_eq > 0 else 0.0
    return BenchmarkResult(
        symbol=symbol,
        available=True,
        detail="buy-and-hold at the first session's open, same slippage + half-spread",
        start_date=series.dates[first],
        end_date=series.dates[last],
        entry_price=entry,
        exit_price=series.close[last],
        qty=qty,
        start_equity=starting_cash,
        end_equity=end_eq,
        total_return_pct=round((end_eq / starting_cash - 1.0) * 100.0, 3),
        cagr_pct=round(cagr * 100.0, 3),
        max_drawdown_pct=round(_drawdown_pct(equities), 3),
    )


# Exposed for the live job and the dashboard so the tracking-day rule is shared.
def initial_anchor(close: float) -> float:
    """The anchor for a symbol's first tracked session is that session's close."""
    return close
