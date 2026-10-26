"""Development-window evaluation of the pre-registered FX strategies.

Discipline (mirrors docs/METHODOLOGY.md, adapted for FX):

* **Sealed tail.** The final ``sealed_days`` of history are cut off before any
  strategy runs. This harness never evaluates them; a sealed evaluation is a
  separate, one-time step that does not exist yet.
* **No tuning.** Parameters are fixed in ``strategies.py`` (version FX-1). The
  report counts every (strategy, pair) test so the multiple-testing burden is
  visible next to any result.
* **Walk-forward.** Each pair's development window is split 60% in-sample /
  40% out-of-sample in four folds (``run_walkforward``). Gates read the
  out-of-sample trades only, pooled across pairs.
* **Costs.** Per-pair spread (pre-registered, conservative retail daily-close
  figures) plus slippage on entry and exit, and a 2x-spread stress run that
  must also be non-negative. Overnight swap/carry is NOT modelled, which is why
  holding periods are capped by each rule's time stop.

Verdicts are ``DEV_PASS`` or ``DEV_FAIL``. A ``DEV_PASS`` is permission to run
the sealed test, never permission to trade: nothing here can reach paper,
alerts or execution.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from signalforge.backtest.costs import CostModel
from signalforge.backtest.engine import SimTrade, run_backtest
from signalforge.backtest.metrics import compute_metrics
from signalforge.backtest.montecarlo import bootstrap_ci
from signalforge.backtest.walkforward import run_walkforward
from signalforge.data.series import PriceSeries
from signalforge.db.models import CryptoBarDaily, FxBarDaily
from signalforge.research.fx.strategies import (
    CRYPTO_STRATEGIES,
    CRYPTO_STRATEGY_VERSION,
    FX_STRATEGIES,
    FX_STRATEGY_VERSION,
    FxStrategy,
)

FX_SOURCE = "massive_fx"

# Round-trip-relevant quoted spread in basis points of price, per pair.
# Conservative retail figures around the daily close (wider than peak-hours).
FX_SPREAD_BPS: dict[str, float] = {
    "EURUSD": 1.0,
    "USDJPY": 1.2,
    "GBPUSD": 1.5,
    "AUDUSD": 1.6,
    "USDCAD": 1.8,
    "USDCHF": 1.8,
    "NZDUSD": 2.5,
    "XAUUSD": 3.0,
}
DEFAULT_SPREAD_BPS = 3.0  # any pair not listed above

CRYPTO_SOURCE = "massive_crypto"
# Crypto has no single quoted spread: a retail taker also pays an exchange fee
# on every fill. The engine charges ``spread_bps / 2`` (plus slippage) on EACH
# side, so each figure below is 2 x (half-spread + taker fee) per side.
CRYPTO_SPREAD_BPS: dict[str, float] = {
    "BTCUSD": 24.0,  # ~2 bps half-spread + ~10 bps taker fee, per side
    "ETHUSD": 26.0,
    "SOLUSD": 40.0,
}
CRYPTO_DEFAULT_SPREAD_BPS = 50.0


@dataclass(frozen=True, slots=True)
class ResearchMarket:
    name: str
    version: str
    model: type[FxBarDaily] | type[CryptoBarDaily]
    source: str
    spreads: dict[str, float]
    default_spread_bps: float
    ingest_hint: str
    caveat: str

    def spread(self, pair: str) -> float:
        return self.spreads.get(pair, self.default_spread_bps)


FX_MARKET = ResearchMarket(
    name="FX",
    version=FX_STRATEGY_VERSION,
    model=FxBarDaily,
    source=FX_SOURCE,
    spreads=FX_SPREAD_BPS,
    default_spread_bps=DEFAULT_SPREAD_BPS,
    ingest_hint="run forex-ingest",
    caveat="Swap/carry not modelled.",
)
CRYPTO_MARKET = ResearchMarket(
    name="Crypto",
    version=CRYPTO_STRATEGY_VERSION,
    model=CryptoBarDaily,
    source=CRYPTO_SOURCE,
    spreads=CRYPTO_SPREAD_BPS,
    default_spread_bps=CRYPTO_DEFAULT_SPREAD_BPS,
    ingest_hint="run crypto-ingest",
    caveat="Perpetual funding and exchange counterparty risk not modelled; spot-style costs only.",
)


@dataclass(frozen=True, slots=True)
class FxGates:
    """Pre-registered development gates (version FX-1)."""

    sealed_days: int = 365
    n_folds: int = 4
    train_frac: float = 0.6
    min_oos_trades: int = 30
    min_oos_expectancy_r: float = 0.0
    min_ci_low_r: float = 0.02
    min_positive_folds: int = 3
    stress_spread_multiplier: float = 2.0
    min_stress_expectancy_r: float = 0.0
    min_positive_pair_frac: float = 0.5
    slippage_bps: float = 1.0


@dataclass(slots=True)
class PairResult:
    pair: str
    dev_start: str
    dev_end: str
    oos_start: str
    oos_trades: int
    oos_expectancy_r: float
    stress_oos_expectancy_r: float


@dataclass(slots=True)
class StrategyResult:
    key: str
    description: str
    params: dict[str, float]
    pairs: list[PairResult] = field(default_factory=list)
    pooled: dict[str, Any] = field(default_factory=dict)
    ci_expectancy_r: dict[str, float] = field(default_factory=dict)
    fold_expectancy_r: list[float] = field(default_factory=list)
    stress_expectancy_r: float = 0.0
    verdict: str = "DEV_FAIL"
    reasons: list[str] = field(default_factory=list)


def load_series(session: Session, pair: str, market: ResearchMarket | None = None) -> PriceSeries:
    mk = market or FX_MARKET
    m = mk.model
    rows = session.execute(
        select(m.session_date, m.open, m.high, m.low, m.close)
        .where(m.pair == pair, m.source == mk.source)
        .order_by(m.session_date)
    ).all()
    return PriceSeries.from_bars(pair, [(d, o, h, lo, c, 0.0) for d, o, h, lo, c in rows])


def _cut(series: PriceSeries, before: date) -> PriceSeries:
    n = sum(1 for d in series.dates if d < before)
    return series.head(n - 1) if n else series.head(-1)


def sealed_start(series_by_pair: dict[str, PriceSeries], sealed_days: int) -> date:
    last = max(s.dates[-1] for s in series_by_pair.values() if len(s))
    return last - timedelta(days=sealed_days - 1)


def evaluate_strategy(
    strat: FxStrategy,
    series_by_pair: dict[str, PriceSeries],
    *,
    seal_from: date,
    gates: FxGates,
    market: ResearchMarket | None = None,
) -> StrategyResult:
    mk = market or FX_MARKET
    res = StrategyResult(key=strat.key, description=strat.description, params=dict(strat.params))
    oos: list[SimTrade] = []
    stress_oos: list[SimTrade] = []
    fold_trades: list[list[SimTrade]] = [[] for _ in range(gates.n_folds)]
    cm = CostModel(slippage_bps=gates.slippage_bps)
    for pair, full in sorted(series_by_pair.items()):
        dev = _cut(full, seal_from)
        if len(dev) < strat.warmup + 50:
            continue
        spread = mk.spread(pair)
        base = run_backtest(
            dev, strat.signal, cost_model=cm, spread_bps=spread, warmup=strat.warmup
        )
        wf = run_walkforward(
            dev, strat.signal, n_folds=gates.n_folds, train_frac=gates.train_frac, outcome=base
        )
        stress = run_backtest(
            dev,
            strat.signal,
            cost_model=cm,
            spread_bps=spread * gates.stress_spread_multiplier,
            warmup=strat.warmup,
        )
        pair_oos = [t for t in base.trades if wf.oos_start <= t.entry_date <= wf.oos_end]
        pair_stress = [t for t in stress.trades if wf.oos_start <= t.entry_date <= wf.oos_end]
        oos += pair_oos
        stress_oos += pair_stress
        for i, f in enumerate(wf.folds[: gates.n_folds]):
            fold_trades[i] += [t for t in pair_oos if f.fold.start <= t.entry_date <= f.fold.end]
        res.pairs.append(
            PairResult(
                pair=pair,
                dev_start=dev.dates[0].isoformat(),
                dev_end=dev.dates[-1].isoformat(),
                oos_start=wf.oos_start.isoformat(),
                oos_trades=len(pair_oos),
                oos_expectancy_r=compute_metrics(pair_oos).expectancy_r,
                stress_oos_expectancy_r=compute_metrics(pair_stress).expectancy_r,
            )
        )

    pooled = compute_metrics(oos)
    res.pooled = pooled.to_dict()
    res.ci_expectancy_r = bootstrap_ci([t.pnl_r for t in oos])["expectancy_r"]
    res.fold_expectancy_r = [compute_metrics(ft).expectancy_r for ft in fold_trades]
    res.stress_expectancy_r = compute_metrics(stress_oos).expectancy_r

    reasons = []
    if pooled.n_trades < gates.min_oos_trades:
        reasons.append(f"OOS trades {pooled.n_trades} < {gates.min_oos_trades}")
    if pooled.expectancy_r < gates.min_oos_expectancy_r:
        reasons.append(f"OOS expectancy {pooled.expectancy_r:.3f}R < {gates.min_oos_expectancy_r}R")
    if res.ci_expectancy_r["low"] < gates.min_ci_low_r:
        reasons.append(
            f"bootstrap CI low {res.ci_expectancy_r['low']:.3f}R < {gates.min_ci_low_r}R"
        )
    pos_folds = sum(
        1 for (e, ft) in zip(res.fold_expectancy_r, fold_trades, strict=True) if ft and e > 0
    )
    if pos_folds < gates.min_positive_folds:
        reasons.append(f"positive OOS folds {pos_folds} < {gates.min_positive_folds}")
    if res.stress_expectancy_r < gates.min_stress_expectancy_r:
        reasons.append(
            f"{gates.stress_spread_multiplier:g}x-spread expectancy "
            f"{res.stress_expectancy_r:.3f}R < {gates.min_stress_expectancy_r}R"
        )
    traded = [p for p in res.pairs if p.oos_trades]
    pos_frac = (sum(1 for p in traded if p.oos_expectancy_r > 0) / len(traded)) if traded else 0.0
    if pos_frac < gates.min_positive_pair_frac:
        reasons.append(
            f"pairs with positive OOS expectancy {pos_frac:.0%} < "
            f"{gates.min_positive_pair_frac:.0%}"
        )
    res.reasons = reasons
    res.verdict = "DEV_PASS" if not reasons else "DEV_FAIL"
    return res


def run_fx_research(
    session: Session,
    pairs: Sequence[str],
    *,
    gates: FxGates | None = None,
    strategies: Sequence[FxStrategy] = FX_STRATEGIES,
) -> dict[str, Any]:
    return run_research(session, pairs, market=FX_MARKET, gates=gates, strategies=strategies)


def run_crypto_research(
    session: Session,
    pairs: Sequence[str],
    *,
    gates: FxGates | None = None,
    strategies: Sequence[FxStrategy] = CRYPTO_STRATEGIES,
) -> dict[str, Any]:
    return run_research(session, pairs, market=CRYPTO_MARKET, gates=gates, strategies=strategies)


def run_research(
    session: Session,
    pairs: Sequence[str],
    *,
    market: ResearchMarket,
    gates: FxGates | None = None,
    strategies: Sequence[FxStrategy],
) -> dict[str, Any]:
    gates = gates or FxGates()
    series_by_pair = {p: load_series(session, p, market) for p in pairs}
    series_by_pair = {p: s for p, s in series_by_pair.items() if len(s)}
    if not series_by_pair:
        raise ValueError(f"no {market.name} history for the requested pairs; {market.ingest_hint}")
    seal_from = sealed_start(series_by_pair, gates.sealed_days)
    results = [
        evaluate_strategy(s, series_by_pair, seal_from=seal_from, gates=gates, market=market)
        for s in strategies
    ]
    return {
        "market": market.name,
        "version": market.version,
        "gates": asdict(gates),
        "spread_bps": {p: market.spread(p) for p in series_by_pair},
        "history": {
            p: {"first": s.dates[0].isoformat(), "last": s.dates[-1].isoformat(), "bars": len(s)}
            for p, s in sorted(series_by_pair.items())
        },
        "sealed_from": seal_from.isoformat(),
        "tests_run": len(strategies) * len(series_by_pair),
        "strategies": [asdict(r) for r in results],
        "notice": (
            "Development-window research only. Sealed final year not evaluated. "
            f"{market.caveat} No order was placed."
        ),
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        f"# {report.get('market', 'FX')} research report — strategies {report['version']}",
        "",
        f"Sealed from {report['sealed_from']} (not evaluated). "
        f"Tests run: {report['tests_run']} (strategy x pair).",
        "",
        "| Strategy | Verdict | OOS trades | Expectancy (R) | CI low (R) "
        "| 2x-spread (R) | Folds (R) |",
        "|---|---|---|---|---|---|---|",
    ]
    for s in report["strategies"]:
        folds = ", ".join(f"{e:+.2f}" for e in s["fold_expectancy_r"])
        lines.append(
            f"| {s['key']} | {s['verdict']} | {s['pooled']['n_trades']} | "
            f"{s['pooled']['expectancy_r']:+.3f} | {s['ci_expectancy_r']['low']:+.3f} | "
            f"{s['stress_expectancy_r']:+.3f} | {folds} |"
        )
    for s in report["strategies"]:
        lines += ["", f"## {s['key']}", "", s["description"], ""]
        if s["reasons"]:
            lines += [f"- {r}" for r in s["reasons"]]
        else:
            lines.append("- All development gates passed. Next step is the one-time sealed test.")
        lines += [
            "",
            "| Pair | OOS from | OOS trades | Expectancy (R) | 2x-spread (R) |",
            "|---|---|---|---|---|",
        ]
        lines += [
            f"| {p['pair']} | {p['oos_start']} | {p['oos_trades']} | "
            f"{p['oos_expectancy_r']:+.3f} | {p['stress_oos_expectancy_r']:+.3f} |"
            for p in s["pairs"]
        ]
    lines += ["", report["notice"], ""]
    return "\n".join(lines)
