"""Run a baseline strategy across a set of instruments and summarise the result.

Aggregates trades from every symbol, computes combined metrics + bootstrap CIs,
splits in-sample vs out-of-sample, and segments the out-of-sample trades by the
market regime on their entry date.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import Integer, func, select
from sqlalchemy.orm import Session

from signalforge.backtest.costs import CostModel
from signalforge.backtest.engine import BacktestOutcome, SimTrade, run_backtest
from signalforge.backtest.metrics import Metrics, compute_metrics
from signalforge.backtest.montecarlo import bootstrap_ci
from signalforge.data.series import PriceSeries
from signalforge.db.models import Instrument, OHLCVDaily, OHLCVIntraday
from signalforge.research.regime import RegimeState, regime_lookup
from signalforge.research.registry import StrategySpec
from signalforge.research.strategies.base import BaselineStrategy, signal_fn_for

DEFAULT_PROXY = "SPY"
_TRAIN_FRAC = 0.6


@dataclass(frozen=True, slots=True)
class DataProvenance:
    """What data actually backed this run — so a report can never imply real
    results from simulated bars (or vice versa)."""

    sources: tuple[str, ...]
    simulated: bool
    bars: int
    first: date | None
    last: date | None

    @property
    def label(self) -> str:
        src = "+".join(self.sources) if self.sources else "none"
        kind = "SIMULATED" if self.simulated else "real"
        span = f"{self.first}..{self.last}" if self.first else "no bars"
        return f"{src} · {kind} · {self.bars} bars · {span}"


def _data_provenance(
    session: Session, symbols: list[str], start: date, end: date, *, intraday: bool
) -> DataProvenance:
    tbl: Any = OHLCVIntraday if intraday else OHLCVDaily
    date_col = tbl.bar_start if intraday else tbl.session_date
    lo: object = datetime(start.year, start.month, start.day, tzinfo=UTC) if intraday else start
    hi: object = datetime(end.year, end.month, end.day, tzinfo=UTC) if intraday else end
    id_col, sim_col, src_col, inst_col = tbl.id, tbl.is_simulated, tbl.source, tbl.instrument_id

    bars, first, last, sim = session.execute(
        select(
            func.count(id_col),
            func.min(date_col),
            func.max(date_col),
            func.max(func.cast(sim_col, Integer)),
        )
        .join(Instrument, inst_col == Instrument.id)
        .where(Instrument.symbol.in_(symbols), date_col >= lo, date_col <= hi)
    ).one()
    sources = tuple(
        sorted(
            row[0]
            for row in session.execute(
                select(src_col)
                .join(Instrument, inst_col == Instrument.id)
                .where(Instrument.symbol.in_(symbols))
                .distinct()
            )
        )
    )
    first_d = first.date() if hasattr(first, "date") else first
    last_d = last.date() if hasattr(last, "date") else last
    return DataProvenance(sources, bool(sim), int(bars or 0), first_d, last_d)


@dataclass(slots=True)
class StrategyBacktestResult:
    spec: StrategySpec
    symbols: list[str]
    start: date
    end: date
    n_trades: int
    in_sample: Metrics
    out_of_sample: Metrics
    oos_ci: dict[str, dict[str, float]]
    by_regime: dict[str, Metrics] = field(default_factory=dict)
    per_symbol_trades: dict[str, int] = field(default_factory=dict)
    trades: list[SimTrade] = field(default_factory=list)
    config_hash: str = ""
    data: DataProvenance = field(default_factory=lambda: DataProvenance((), False, 0, None, None))
    costs: dict[str, float | bool] = field(default_factory=dict)

    @property
    def costs_label(self) -> str:
        c = self.costs
        if not c:
            return "default: 0 commission · 3.0 bps slippage · half-spread on"
        return (
            f"{c.get('commission_per_share', 0.0)}/sh commission "
            f"(min {c.get('commission_min_per_order', 0.0)}/order) · "
            f"{c.get('slippage_bps', 0.0)} bps slippage · "
            f"half-spread {'on' if c.get('half_spread_fill_penalty') else 'off'}"
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "strategy": self.spec.key,
            "version": self.spec.version,
            "git_sha": self.spec.git_sha,
            "symbols": self.symbols,
            "window": {"start": self.start.isoformat(), "end": self.end.isoformat()},
            "n_trades": self.n_trades,
            "in_sample": self.in_sample.to_dict(),
            "out_of_sample": self.out_of_sample.to_dict(),
            "out_of_sample_ci": self.oos_ci,
            "by_regime": {k: v.to_dict() for k, v in self.by_regime.items()},
            "per_symbol_trades": self.per_symbol_trades,
            "config_hash": self.config_hash,
            "costs": self.costs,
            "data": {
                "sources": list(self.data.sources),
                "simulated": self.data.simulated,
                "bars": self.data.bars,
                "first": self.data.first.isoformat() if self.data.first else None,
                "last": self.data.last.isoformat() if self.data.last else None,
            },
        }


def _is_boundary(series: PriceSeries) -> date:
    cut = max(1, min(int(len(series) * _TRAIN_FRAC), len(series) - 2))
    return series.dates[cut - 1]


def _as_date(x: object) -> date:
    return x.date() if isinstance(x, datetime) else x  # type: ignore[return-value]


def run_strategy_over_universe(
    session: Session,
    strategy: BaselineStrategy,
    symbols: list[str],
    start: date,
    end: date,
    *,
    proxy_symbol: str = DEFAULT_PROXY,
    source: str | None = None,
    allow_short: bool = False,
    cost_model: CostModel | None = None,
    config_hash: str = "",
    intraday: bool = False,
    bar_size: str = "15m",
    min_bars: int = 60,
) -> StrategyBacktestResult:
    proxy = PriceSeries.load(session, proxy_symbol, start, end, source=source)
    regimes = regime_lookup(proxy) if len(proxy) else {}
    fn = signal_fn_for(strategy, regime_by_date=regimes, allow_short=allow_short)

    all_trades: list[SimTrade] = []
    is_trades: list[SimTrade] = []
    oos_trades: list[SimTrade] = []
    per_symbol: dict[str, int] = {}

    win_start = datetime.combine(start, datetime.min.time(), tzinfo=UTC)
    win_end = datetime.combine(end, datetime.min.time(), tzinfo=UTC)

    for sym in symbols:
        series = (
            PriceSeries.load_intraday(
                session, sym, win_start, win_end, bar_size=bar_size, source=source
            )
            if intraday
            else PriceSeries.load(session, sym, start, end, source=source)
        )
        if len(series) < min_bars:
            continue
        outcome: BacktestOutcome = run_backtest(
            series, fn, cost_model=cost_model, warmup=min_bars // 2
        )
        boundary = _as_date(_is_boundary(series))
        per_symbol[sym] = len(outcome.trades)
        for tr in outcome.trades:
            all_trades.append(tr)
            (is_trades if _as_date(tr.entry_date) <= boundary else oos_trades).append(tr)

    by_regime: dict[str, list[SimTrade]] = {}
    for tr in oos_trades:
        r: RegimeState | None = regimes.get(_as_date(tr.entry_date))
        label = f"{r.trend.value}/{r.vol.value}" if r else "unknown"
        by_regime.setdefault(label, []).append(tr)

    return StrategyBacktestResult(
        spec=strategy.spec(),
        symbols=list(symbols),
        start=start,
        end=end,
        n_trades=len(all_trades),
        in_sample=compute_metrics(is_trades),
        out_of_sample=compute_metrics(oos_trades),
        oos_ci=bootstrap_ci([t.pnl_r for t in oos_trades]),
        by_regime={k: compute_metrics(v) for k, v in sorted(by_regime.items())},
        per_symbol_trades=per_symbol,
        trades=all_trades,
        config_hash=config_hash,
        data=_data_provenance(session, list(symbols), start, end, intraday=intraday),
        costs={
            "commission_per_share": (cost_model or CostModel()).commission_per_share,
            "commission_min_per_order": (cost_model or CostModel()).commission_min_per_order,
            "slippage_bps": (cost_model or CostModel()).slippage_bps,
            "half_spread_fill_penalty": (cost_model or CostModel()).half_spread_fill_penalty,
        },
    )
