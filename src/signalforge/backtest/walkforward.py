"""Walk-forward / out-of-sample evaluation.

The timeline is split into an in-sample head and an out-of-sample tail; the tail
is divided into ``n_folds`` contiguous blocks. The engine runs once over the full
series and each trade is assigned to a block by its **entry date**. Reports show
in-sample vs per-fold vs combined out-of-sample side by side; the combined OOS
figure is the one used downstream.

(Phase 1 strategies fit no parameters, so re-running per window would give the
same trades; per-fold re-fitting is a Phase 2 addition. This is documented, not
hidden.)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from signalforge.backtest.engine import BacktestOutcome, SignalFn, SimTrade, run_backtest
from signalforge.backtest.metrics import Metrics, compute_metrics
from signalforge.backtest.series import PriceSeries


@dataclass(frozen=True, slots=True)
class Fold:
    index: int
    start: date
    end: date


@dataclass(slots=True)
class FoldResult:
    fold: Fold
    n_trades: int
    metrics: Metrics


@dataclass(slots=True)
class WalkforwardReport:
    symbol: str
    in_sample_start: date
    in_sample_end: date
    oos_start: date
    oos_end: date
    in_sample: Metrics
    oos_combined: Metrics
    folds: list[FoldResult] = field(default_factory=list)
    n_trades_total: int = 0

    def to_dict(self) -> dict[str, object]:
        return {
            "symbol": self.symbol,
            "in_sample": {
                "start": self.in_sample_start.isoformat(),
                "end": self.in_sample_end.isoformat(),
                "metrics": self.in_sample.to_dict(),
            },
            "out_of_sample": {
                "start": self.oos_start.isoformat(),
                "end": self.oos_end.isoformat(),
                "metrics": self.oos_combined.to_dict(),
            },
            "folds": [
                {
                    "index": f.fold.index,
                    "start": f.fold.start.isoformat(),
                    "end": f.fold.end.isoformat(),
                    "n_trades": f.n_trades,
                    "metrics": f.metrics.to_dict(),
                }
                for f in self.folds
            ],
            "n_trades_total": self.n_trades_total,
        }


def _split_dates(dates: tuple[date, ...], train_frac: float) -> tuple[date, date, date, date]:
    if len(dates) < 10:
        raise ValueError("need at least 10 sessions for a walk-forward split")
    cut = int(len(dates) * train_frac)
    cut = min(max(cut, 1), len(dates) - 2)
    return dates[0], dates[cut - 1], dates[cut], dates[-1]


def _make_folds(oos_start: date, oos_end: date, n_folds: int) -> list[Fold]:
    total_days = (oos_end - oos_start).days + 1
    step = max(1, total_days // n_folds)
    folds: list[Fold] = []
    from datetime import timedelta

    cursor = oos_start
    for i in range(n_folds):
        end = min(oos_end, cursor + timedelta(days=step - 1)) if i < n_folds - 1 else oos_end
        folds.append(Fold(index=i, start=cursor, end=end))
        cursor = end + timedelta(days=1)
        if cursor > oos_end:
            break
    return folds


def run_walkforward(
    series: PriceSeries,
    signal_fn: SignalFn,
    *,
    n_folds: int = 4,
    train_frac: float = 0.6,
    outcome: BacktestOutcome | None = None,
) -> WalkforwardReport:
    is_start, is_end, oos_start, oos_end = _split_dates(series.dates, train_frac)
    result = outcome or run_backtest(series, signal_fn)

    def _in(trs: list[SimTrade], lo: date, hi: date) -> list[SimTrade]:
        return [t for t in trs if lo <= t.entry_date <= hi]

    is_trades = _in(result.trades, is_start, is_end)
    oos_trades = _in(result.trades, oos_start, oos_end)

    folds: list[FoldResult] = []
    for fold in _make_folds(oos_start, oos_end, n_folds):
        ft = _in(result.trades, fold.start, fold.end)
        folds.append(FoldResult(fold=fold, n_trades=len(ft), metrics=compute_metrics(ft)))

    return WalkforwardReport(
        symbol=series.symbol,
        in_sample_start=is_start,
        in_sample_end=is_end,
        oos_start=oos_start,
        oos_end=oos_end,
        in_sample=compute_metrics(is_trades),
        oos_combined=compute_metrics(oos_trades),
        folds=folds,
        n_trades_total=len(result.trades),
    )
