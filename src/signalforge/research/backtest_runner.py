"""Run a baseline strategy across a set of instruments and summarise the result.

Aggregates trades from every symbol, computes combined metrics + bootstrap CIs,
splits in-sample vs out-of-sample, and segments the out-of-sample trades by the
market regime on their entry date.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime

from sqlalchemy.orm import Session

from signalforge.backtest.costs import CostModel
from signalforge.backtest.engine import BacktestOutcome, SimTrade, run_backtest
from signalforge.backtest.metrics import Metrics, compute_metrics
from signalforge.backtest.montecarlo import bootstrap_ci
from signalforge.data.series import PriceSeries
from signalforge.research.regime import RegimeState, regime_lookup
from signalforge.research.registry import StrategySpec
from signalforge.research.strategies.base import BaselineStrategy, signal_fn_for

DEFAULT_PROXY = "SPY"
_TRAIN_FRAC = 0.6


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
    )
