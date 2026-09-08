"""Formal strategy-promotion pipeline (ARCHITECTURE.md §6.5).

The **only** code path allowed to set ``StrategyStatus.PAPER_APPROVED``. A
strategy *version* is promoted only when every one of the ten gates below
passes, on genuine licensed data:

 1. Multiple rolling walk-forward out-of-sample windows over the pre-sealed
    span, with no parameter selection based on the sealed final test (enforced
    by construction: the sealed slice is never even loaded until gate 9, after
    every other gate has already run against the strategy's frozen params).
 2. Adequate out-of-sample trade count — the bar is fixed in
    ``PromotionThresholds`` (version-controlled, hashed into ``config_hash``)
    *before* any evaluation runs, not chosen after seeing a result.
 3. Positive net expectancy after the project's conservative cost model
    (commission + slippage + half-spread).
 4. A bootstrap confidence interval whose lower bound is *materially* above
    zero, not merely non-negative.
 5. Robustness across a parameter-sensitivity grid (delegates to
    ``research.sensitivity``) — a lucky, narrow parameter setting fails this.
 6. Evidence in bull, bear, *and* range-bound regimes, each with a minimum
    trade count.
 7. A risk-adjusted benchmark comparison (Sharpe vs SPY buy-and-hold over the
    same span) — cumulative return alone never decides this.
 8. No unresolved data-quality or leakage finding: a fresh ``validate_daily``
    pass, plus a live look-ahead self-check on the shared feature functions.
 9. A sealed final out-of-sample window, evaluated **once** and locked
    immutably to the strategy version (``StrategySealedTest``, unique on
    ``strategy_version_id``) — a later call reuses the first result, it never
    recomputes or overwrites it.
10. A defined live-paper probation: the existing ``health_monitor`` downgrade/
    disable rules (``HealthMonitorConfig``), confirmed active — they apply
    automatically to every trade the strategy books once promoted.

Every evaluation — pass or fail — is recorded as an append-only
``StrategyPromotionEvaluation`` row, so the Strategy Promotion dashboard shows
the full history, not just the latest attempt. When no strategy version has
ever passed, the correct, honest operational result is
``"NO TRADE — insufficient evidence or poor risk/reward"`` — that is not a
failure of this module, it is the module doing its job.

Manual actions (the dashboard, the CLI) may downgrade or disable a strategy
directly; only ``evaluate_promotion`` may approve one.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from dataclasses import replace as _replace
from datetime import date, timedelta
from typing import Any

import numpy as np
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from signalforge import audit
from signalforge.backtest.costs import CostModel
from signalforge.backtest.leakage import LookaheadDetected, assert_no_lookahead
from signalforge.backtest.regime import TREND_LOOKBACK, label_regimes
from signalforge.config.research import PromotionThresholds, ResearchConfig
from signalforge.data.repository import SourceFilter
from signalforge.data.series import PriceSeries
from signalforge.data.validate import validate_daily
from signalforge.db.models import (
    AuditLog,
    DataSnapshot,
    Strategy,
    StrategyPromotionEvaluation,
    StrategySealedTest,
    StrategyVersion,
)
from signalforge.db.types import utcnow
from signalforge.domain import Horizon, StrategyStatus
from signalforge.observability import get_logger
from signalforge.research.backtest_runner import run_strategy_over_universe
from signalforge.research.features.daily import atr, realized_vol, rolling_return, sma
from signalforge.research.persistence import upsert_strategy_version
from signalforge.research.portfolio_metrics import compute_portfolio_metrics
from signalforge.research.sensitivity import run_parameter_sensitivity
from signalforge.research.strategies.base import BaselineStrategy

_log = get_logger("research.promotion")

VERDICT_APPROVED = "PAPER_APPROVED"
VERDICT_NO_TRADE = "NO TRADE — insufficient evidence or poor risk/reward"

# The pre-sealed span must clear regime.py's TREND_LOOKBACK warmup (every
# session before it is labelled 'warmup' and excluded from gate 6's bull/bear/
# range buckets) with enough real trading sessions left over to actually
# measure regime coverage — not just the bare minimum to exit warmup.
MIN_PRESEALED_DAYS = math.ceil(TREND_LOOKBACK * 365.25 / 252) + 60

# matches signalforge.research.sensitivity.StrategyFactory
StrategyFactory = Callable[[Mapping[str, Any]], BaselineStrategy]


@dataclass(frozen=True, slots=True)
class Gate:
    number: int
    name: str
    passed: bool
    detail: str
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "number": self.number,
            "name": self.name,
            "passed": self.passed,
            "detail": self.detail,
            "evidence": self.evidence,
        }


@dataclass(frozen=True, slots=True)
class PromotionResult:
    strategy_key: str
    version: str
    strategy_version_id: int
    evaluation_id: int
    evaluated_at: str
    config_hash: str
    git_sha: str
    universe: list[str]
    window_start: date
    window_end: date
    data_provenance: dict[str, Any]
    gates: list[Gate]
    passed: bool
    verdict: str
    sealed_test_id: int | None
    dataset_snapshot_id: int | None = None
    already_approved_via_pipeline: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy_key": self.strategy_key,
            "version": self.version,
            "strategy_version_id": self.strategy_version_id,
            "evaluation_id": self.evaluation_id,
            "evaluated_at": self.evaluated_at,
            "config_hash": self.config_hash,
            "git_sha": self.git_sha,
            "universe": self.universe,
            "window": {"start": self.window_start.isoformat(), "end": self.window_end.isoformat()},
            "data_provenance": self.data_provenance,
            "gates": [g.to_dict() for g in self.gates],
            "passed": self.passed,
            "verdict": self.verdict,
            "sealed_test_id": self.sealed_test_id,
            "dataset_snapshot_id": self.dataset_snapshot_id,
        }


# --------------------------------------------------------------------------- #
# per-strategy parameter-sensitivity plans (gate 5)
# --------------------------------------------------------------------------- #
def _sensitivity_plan(
    strategy: BaselineStrategy,
) -> tuple[StrategyFactory, dict[str, list[float | int]]] | None:
    """(factory, grid) for the sensitivity gate, or ``None`` if this strategy has
    no defined grid yet — that is an honest gate-5 failure, not a skip."""
    key = strategy.key
    if key.startswith("relative_strength"):
        from signalforge.research.strategies.relative_strength import RelativeStrength

        base = strategy.params  # type: ignore[attr-defined]
        horizon = strategy.horizon  # type: ignore[attr-defined]

        def factory(p: Mapping[str, Any]) -> BaselineStrategy:
            return RelativeStrength(horizon, _replace(base, **p))

        return factory, {"excess_return_min": [0.03, 0.05, 0.07], "lookback": [42, 63, 84]}

    if key.startswith("trend_continuation"):
        from signalforge.research.strategies.trend_continuation import TrendContinuation

        base = strategy.params  # type: ignore[attr-defined]
        horizon = strategy.horizon  # type: ignore[attr-defined]

        def factory(p: Mapping[str, Any]) -> BaselineStrategy:
            return TrendContinuation(horizon, _replace(base, **p))

        return factory, {"sma_fast": [15, 20, 25], "stop_atr": [1.2, 1.5, 1.8]}

    if key.startswith("mean_reversion"):
        from signalforge.research.strategies.mean_reversion import MeanReversion

        base = strategy.params  # type: ignore[attr-defined]

        def factory(p: Mapping[str, Any]) -> BaselineStrategy:
            return MeanReversion(_replace(base, **p))

        return factory, {"z_entry": [-2.5, -2.0, -1.5], "stop_atr": [1.5, 2.0, 2.5]}

    if key.startswith("volatility_breakout"):
        from signalforge.research.strategies.breakout import VolatilityBreakout

        base = strategy.params  # type: ignore[attr-defined]
        horizon = strategy.horizon  # type: ignore[attr-defined]

        def factory(p: Mapping[str, Any]) -> BaselineStrategy:
            return VolatilityBreakout(horizon, _replace(base, **p))

        return factory, {"contraction_max": [0.65, 0.75, 0.85], "stop_atr": [1.5, 1.75, 2.0]}

    return None


# --------------------------------------------------------------------------- #
# small numeric helpers
# --------------------------------------------------------------------------- #
def _benchmark_metrics(proxy: PriceSeries, lo: date, hi: date) -> dict[str, float]:
    """Buy-and-hold Sharpe/CAGR/vol/maxDD for the proxy over ``[lo, hi]``."""
    idx = [i for i, d in enumerate(proxy.dates) if lo <= d <= hi]
    if len(idx) < 3:
        return {
            "n_sessions": len(idx),
            "total_return_pct": 0.0,
            "cagr_pct": 0.0,
            "ann_vol_pct": 0.0,
            "sharpe": 0.0,
            "max_drawdown_pct": 0.0,
        }
    closes = np.asarray(proxy.close[idx[0] : idx[-1] + 1], dtype=np.float64)
    rets = np.diff(closes) / closes[:-1]
    total_return = float(closes[-1] / closes[0] - 1.0)
    days = (proxy.dates[idx[-1]] - proxy.dates[idx[0]]).days or 1
    years = days / 365.25
    cagr = (1 + total_return) ** (1 / years) - 1 if years > 0 and 1 + total_return > 0 else 0.0
    ann_vol = float(np.std(rets, ddof=1) * math.sqrt(252)) if rets.size > 1 else 0.0
    sharpe = (cagr / ann_vol) if ann_vol > 0 else 0.0
    eq = np.cumprod(1 + rets)
    peak = np.maximum.accumulate(eq)
    max_dd = float((eq / peak - 1.0).min()) if eq.size else 0.0
    return {
        "n_sessions": len(idx),
        "total_return_pct": round(total_return * 100, 2),
        "cagr_pct": round(cagr * 100, 2),
        "ann_vol_pct": round(ann_vol * 100, 2),
        "sharpe": round(sharpe, 3),
        "max_drawdown_pct": round(abs(max_dd) * 100, 2),
    }


def _leakage_self_check(
    session: Session, symbol: str, start: date, end: date, source: SourceFilter
) -> str | None:
    """Re-verify the shared daily feature functions are look-ahead-free against
    real data for this window. Returns an error string, or ``None`` if clean."""
    series = PriceSeries.load(session, symbol, start, end, source=source)
    if len(series) < 60:
        return None  # too little data to check meaningfully; not a leakage finding
    checks: list[tuple[str, Any]] = [
        ("sma(50)", lambda s, t: sma(s, t, 50)),
        ("rolling_return(20)", lambda s, t: rolling_return(s, t, 20)),
        ("atr(14)", lambda s, t: atr(s, t, 14)),
        ("realized_vol(20)", lambda s, t: realized_vol(s, t, 20)),
    ]
    for name, fn in checks:
        try:
            assert_no_lookahead(fn, series)
        except LookaheadDetected as exc:
            return f"{name}: {exc}"
    return None


# --------------------------------------------------------------------------- #
# dataset snapshots — a changed universe is new data, not an edit
# --------------------------------------------------------------------------- #
def _symbols_fingerprint(symbols: list[str]) -> str:
    import hashlib

    return hashlib.sha256(",".join(sorted(s.upper() for s in symbols)).encode()).hexdigest()[:10]


def get_or_create_dataset_snapshot(
    session: Session,
    *,
    key: str | None = None,
    symbols: list[str],
    description: str = "",
    source_note: str = "",
    continuity_mapping_id: int | None = None,
) -> DataSnapshot:
    """Resolve the dataset snapshot a promotion evaluation is about to use.

    Looked up by exact ``key`` when given (the CLI/report layer names its
    three FB/META comparison variants explicitly this way); otherwise by an
    exact match on the symbol set among snapshots marked
    ``reusable_by_new_evaluations`` — so a caller that doesn't care about
    dataset versioning (existing tests, the plain CLI default) transparently
    reuses whatever snapshot already covers that exact universe, while never
    silently re-attaching to an audit-history row like
    ``universe_25_baseline_legacy`` (a migration backfill, marked
    non-reusable) whose own description promises it will never be reused.

    A ``key`` hit whose stored ``symbols_json`` (or ``continuity_mapping_id``,
    when given) no longer matches what was just requested raises
    ``ValueError`` rather than silently reusing stale data — a
    ``DataSnapshot`` is immutable once created (per its own contract), so a
    genuinely changed universe or superseding continuity mapping needs a new,
    distinct key, not a quiet reinterpretation of an existing one.

    Creates a new, immutable snapshot only when neither lookup finds one.
    """
    if key is not None:
        existing = session.scalar(select(DataSnapshot).where(DataSnapshot.key == key))
        if existing is not None:
            wanted = sorted(s.upper() for s in symbols)
            have = sorted(x.upper() for x in existing.symbols_json)
            mapping_mismatch = (
                continuity_mapping_id is not None
                and existing.continuity_mapping_id is not None
                and existing.continuity_mapping_id != continuity_mapping_id
            )
            if wanted != have or mapping_mismatch:
                raise ValueError(
                    f"dataset snapshot key {key!r} already exists (id={existing.id}) with "
                    f"different data than just requested — existing symbols={have}, requested="
                    f"{wanted}; existing continuity_mapping_id={existing.continuity_mapping_id}, "
                    f"requested={continuity_mapping_id}. A DataSnapshot's contents are immutable "
                    "once created — reusing this key for genuinely different data would "
                    "silently misrepresent every future evaluation's provenance. Use a new, "
                    "distinct key for the changed data."
                )
            return existing
    else:
        wanted = sorted(s.upper() for s in symbols)
        for row in session.scalars(
            select(DataSnapshot).where(DataSnapshot.reusable_by_new_evaluations.is_(True))
        ):
            if sorted(x.upper() for x in row.symbols_json) == wanted:
                return row
    snap = DataSnapshot(
        key=key or f"universe_auto_{len(symbols)}sym_{_symbols_fingerprint(symbols)}",
        symbols_json=list(symbols),
        description=description,
        source_note=source_note,
        continuity_mapping_id=continuity_mapping_id,
    )
    session.add(snap)
    session.flush()
    _log.info("promotion.dataset_snapshot_created", key=snap.key, n_symbols=len(symbols))
    return snap


# --------------------------------------------------------------------------- #
# gate 9 — sealed test, computed once, reused forever
# --------------------------------------------------------------------------- #
def _get_or_create_sealed_test(
    session: Session,
    strategy: BaselineStrategy,
    version: StrategyVersion,
    *,
    symbols: list[str],
    sealed_start: date,
    end: date,
    proxy_symbol: str,
    source: SourceFilter,
    cost_model: CostModel,
    th: PromotionThresholds,
    dataset_snapshot_id: int,
) -> tuple[StrategySealedTest, bool]:
    """Returns ``(row, reused)`` — ``reused=True`` means an existing locked row
    was returned as-is; nothing was recomputed.

    Keyed on ``(strategy_version_id, dataset_snapshot_id)``, not on the
    strategy version alone: evaluating the identical version against a
    DIFFERENT dataset snapshot (a corrected symbol series, a narrowed
    universe) is guaranteed a fresh sealed test rather than silently reusing
    — or being blocked by — a prior snapshot's locked result.
    """
    existing = session.scalar(
        select(StrategySealedTest).where(
            StrategySealedTest.strategy_version_id == version.id,
            StrategySealedTest.dataset_snapshot_id == dataset_snapshot_id,
        )
    )
    if existing is not None:
        return existing, True  # locked — never recomputed, never overwritten

    result = run_strategy_over_universe(
        session,
        strategy,
        symbols,
        sealed_start,
        end,
        proxy_symbol=proxy_symbol,
        source=source,
        cost_model=cost_model,
    )
    trades = result.trades  # every trade in the sealed window, evaluated once
    n = len(trades)
    exp = sum(t.pnl_r for t in trades) / n if n else 0.0
    pm = compute_portfolio_metrics(trades, span_start=sealed_start, span_end=end)
    proxy = PriceSeries.load(session, proxy_symbol, sealed_start, end, source=source)
    bench = _benchmark_metrics(proxy, sealed_start, end)
    passed = bool(n >= th.sealed_min_trades and exp >= th.sealed_min_expectancy_r)
    detail = (
        f"{n} trades, net expectancy {exp:+.4f}R (need >= {th.sealed_min_expectancy_r:+.4f}R "
        f"on >= {th.sealed_min_trades} trades)"
    )
    row = StrategySealedTest(
        strategy_version_id=version.id,
        dataset_snapshot_id=dataset_snapshot_id,
        window_start=sealed_start,
        window_end=end,
        universe_json=list(symbols),
        data_provenance_json={
            "sources": list(result.data.sources),
            "simulated": result.data.simulated,
            "bars": result.data.bars,
        },
        metrics_json={"n_trades": n, "expectancy_r": round(exp, 4), **pm.to_dict()},
        benchmark_metrics_json=bench,
        passed=passed,
        detail=detail,
        evaluated_at=utcnow(),
    )
    try:
        with session.begin_nested():  # SAVEPOINT: a failure here rolls back only this insert
            session.add(row)
            session.flush()
    except IntegrityError:
        # a concurrent evaluate_promotion() for the same (version, dataset)
        # won the race and committed its own sealed test first — discard this
        # compute and reuse the winner, rather than raising or (worse) ending
        # up with two sealed tests for one (version, dataset) pair.
        winner = session.scalar(
            select(StrategySealedTest).where(
                StrategySealedTest.strategy_version_id == version.id,
                StrategySealedTest.dataset_snapshot_id == dataset_snapshot_id,
            )
        )
        if winner is not None:
            return winner, True
        raise
    _log.info(
        "promotion.sealed_test_sealed",
        strategy=strategy.key,
        version=version.version,
        n_trades=n,
        passed=passed,
    )
    return row, False


# --------------------------------------------------------------------------- #
# main entry point
# --------------------------------------------------------------------------- #
def evaluate_promotion(
    session: Session,
    strategy: BaselineStrategy,
    *,
    symbols: list[str],
    start: date,
    end: date,
    proxy_symbol: str = "SPY",
    source: SourceFilter = None,
    config: ResearchConfig | None = None,
    dataset_snapshot: DataSnapshot | None = None,
) -> PromotionResult:
    """Run every gate for one strategy version and record the result.

    Flips ``Strategy``/``StrategyVersion`` status to ``PAPER_APPROVED`` only
    when every gate passes. Never downgrades — that stays the health monitor's
    and a human's job. Every call persists a new, immutable evaluation row.

    ``source`` filters which ``OHLCVDaily`` rows count as this run's data — a
    plain string (the usual case) for a single provider, or a sequence of
    strings when a dataset legitimately mixes sources for different symbols
    (e.g. one symbol's bars come from a verified symbol-continuity bridge
    tagged distinctly from the rest of the universe's raw provider tag).
    Gate 8's ``validate_daily`` check always evaluates against only the
    FIRST entry (the real provider) regardless — a bridge tag is deliberately
    never treated as equivalent to raw single-provider data for that specific
    check, even though gates 1-7/9 do see and trade its bars.

    ``dataset_snapshot`` identifies exactly which data this call used (see
    ``DataSnapshot``). Omit it for the common case (an existing, unversioned
    universe) — it is resolved automatically from ``symbols``, transparently
    reusing whatever snapshot already covers that exact symbol set. Pass one
    explicitly to run a deliberate, separately-identified comparison (e.g. a
    24-symbol universe excluding a symbol with an unresolved data-quality
    finding, or a corrected continuous series after a verified symbol-
    continuity mapping) — gate 9's sealed test is then keyed to THIS snapshot
    and can never reuse, or be blocked by, a different snapshot's result.
    """
    if config is None:
        from signalforge.settings_store import effective_research_config

        config = effective_research_config(session)
    th = config.promotion
    cost_model = CostModel(
        commission_per_share=config.commission_per_share,
        commission_min_per_order=config.commission_min_per_order,
        slippage_bps=config.slippage_bps,
        half_spread_fill_penalty=config.half_spread_fill_penalty,
    )
    if dataset_snapshot is None:
        dataset_snapshot = get_or_create_dataset_snapshot(session, symbols=symbols)

    spec = strategy.spec()
    version = upsert_strategy_version(session, spec)
    gates: list[Gate] = []
    sealed_row: StrategySealedTest | None = None

    if spec.horizon is Horizon.INTRADAY:
        gates.append(
            Gate(
                0,
                "data_availability",
                False,
                "no intraday bar history is ingested for this horizon — evaluation not attempted "
                "(not a fabricated pass on absent data)",
            )
        )
        return _finalize(
            session,
            strategy,
            version,
            config,
            symbols,
            start,
            end,
            gates,
            None,
            {},
            dataset_snapshot.id,
        )

    # Pin the sealed window to any already-locked sealed test for this exact
    # strategy version. Without this, re-evaluating the same version after
    # more data has been ingested (a later "today") would recompute
    # sealed_start fresh from the new `end`, sliding it forward — and the
    # gates-1-8 pre-sealed span would then silently grow to overlap calendar
    # days that are already part of the FIRST, locked sealed test. Pinning
    # keeps the two windows permanently disjoint after the first evaluation.
    existing_sealed = session.scalar(
        select(StrategySealedTest).where(
            StrategySealedTest.strategy_version_id == version.id,
            StrategySealedTest.dataset_snapshot_id == dataset_snapshot.id,
        )
    )
    sealed_start = (
        existing_sealed.window_start
        if existing_sealed is not None
        else end - timedelta(days=th.sealed_window_days)
    )
    sealed_end = existing_sealed.window_end if existing_sealed is not None else end
    # Gates 1-8 use the pre-sealed span [start, pre_sealed_end] — strictly
    # BEFORE sealed_start, never touching the sealed window's own first day.
    pre_sealed_end = sealed_start - timedelta(days=1)

    if sealed_start <= start or (pre_sealed_end - start).days < MIN_PRESEALED_DAYS:
        gates.append(
            Gate(
                0,
                "data_availability",
                False,
                f"window [{start}..{end}] is too short: the pre-sealed span needs >= "
                f"{MIN_PRESEALED_DAYS} calendar days (enough to clear regime.py's "
                f"{TREND_LOOKBACK}-session warmup with real sessions left to measure) before "
                f"the {th.sealed_window_days}-day sealed test begins",
            )
        )
        return _finalize(
            session,
            strategy,
            version,
            config,
            symbols,
            start,
            end,
            gates,
            None,
            {},
            dataset_snapshot.id,
        )

    # ---- shared evidence over the PRE-SEALED span (gates 1-8) -------------
    full = run_strategy_over_universe(
        session,
        strategy,
        symbols,
        start,
        pre_sealed_end,
        proxy_symbol=proxy_symbol,
        source=source,
        cost_model=cost_model,
        config_hash=config.config_hash,
    )
    data_provenance = {
        "sources": list(full.data.sources),
        "simulated": full.data.simulated,
        "bars": full.data.bars,
        "coverage": f"{full.data.first}..{full.data.last}",
        "costs": full.costs_label,
        "dataset_snapshot": {"id": dataset_snapshot.id, "key": dataset_snapshot.key},
    }

    # Gate 1: rolling walk-forward folds over the pre-sealed span. A fold only
    # counts as evidence of an edge if it clears its own trade-count floor
    # AND has positive expectancy — a fold with one lucky trade, or a
    # net-losing fold, must not count toward "the edge holds up over time".
    span_days = (pre_sealed_end - start).days
    n_folds = th.min_walkforward_folds
    fold_rows: list[dict[str, Any]] = []
    for k in range(n_folds):
        lo = start + timedelta(days=span_days * k // n_folds)
        hi = start + timedelta(days=span_days * (k + 1) // n_folds)
        ft = [t for t in full.trades if lo <= t.entry_date < hi]
        pm = compute_portfolio_metrics(ft, span_start=lo, span_end=hi)
        fold_rows.append(
            {
                "fold": k + 1,
                "start": lo.isoformat(),
                "end": hi.isoformat(),
                "n_trades": pm.n_trades,
                "expectancy_r": pm.avg_trade_r,
                "sharpe": pm.sharpe,
            }
        )
    folds_with_trades = sum(1 for f in fold_rows if f["n_trades"] > 0)
    folds_with_edge = sum(
        1
        for f in fold_rows
        if f["n_trades"] >= th.sensitivity_min_grid_trades
        and f["expectancy_r"] > th.min_net_expectancy_r
    )
    gate1_pass = bool(len(fold_rows) >= n_folds and folds_with_edge >= max(1, n_folds // 2))
    gates.append(
        Gate(
            1,
            "rolling_walkforward",
            gate1_pass,
            f"{len(fold_rows)} rolling folds over the pre-sealed span, {folds_with_trades} with "
            f"any trades, {folds_with_edge} clearing both a per-fold trade floor "
            f"(>={th.sensitivity_min_grid_trades}) and positive expectancy (need >="
            f"{max(1, n_folds // 2)} of {n_folds}); strategy params are its frozen spec "
            f"defaults — the sealed slice below is not loaded until gate 9, so nothing here "
            f"can be selected against it",
            {"folds": fold_rows},
        )
    )

    # Gate 2: adequate OOS trade count (threshold fixed in config before this ran).
    oos = full.out_of_sample
    gate2_pass = bool(oos.n_trades >= th.min_oos_trades)
    gates.append(
        Gate(
            2,
            "min_oos_trades",
            gate2_pass,
            f"{oos.n_trades} out-of-sample trades (threshold {th.min_oos_trades}, fixed in "
            f"PromotionThresholds prior to this evaluation)",
            {"n_oos_trades": oos.n_trades, "threshold": th.min_oos_trades},
        )
    )

    # Gate 3: positive net expectancy after conservative costs.
    gate3_pass = bool(oos.expectancy_r > th.min_net_expectancy_r)
    gates.append(
        Gate(
            3,
            "net_expectancy",
            gate3_pass,
            f"OOS expectancy {oos.expectancy_r:+.4f}R net of costs ({full.costs_label}); "
            f"need > {th.min_net_expectancy_r:+.4f}R",
            {"expectancy_r": oos.expectancy_r, "threshold": th.min_net_expectancy_r},
        )
    )

    # Gate 4: bootstrap CI materially above zero.
    ci_low = float(full.oos_ci.get("expectancy_r", {}).get("low", 0.0))
    gate4_pass = bool(ci_low > th.min_bootstrap_ci_low_r)
    gates.append(
        Gate(
            4,
            "bootstrap_ci",
            gate4_pass,
            f"95% bootstrap CI lower bound {ci_low:+.4f}R; need "
            f"> {th.min_bootstrap_ci_low_r:+.4f}R (materially above zero, not merely non-negative)",
            {"ci": full.oos_ci.get("expectancy_r", {}), "threshold": th.min_bootstrap_ci_low_r},
        )
    )

    # Gate 5: parameter-sensitivity robustness.
    plan = _sensitivity_plan(strategy)
    if plan is None:
        gates.append(
            Gate(
                5,
                "parameter_sensitivity",
                False,
                "no parameter-sensitivity grid is defined for this strategy — robustness cannot "
                "be verified, so it cannot pass",
            )
        )
    else:
        factory, grid = plan
        from dataclasses import asdict as _asdict

        sens = run_parameter_sensitivity(
            session,
            strategy_key=spec.name,
            version=spec.version,
            factory=factory,
            baseline_params=_asdict(strategy.params),  # type: ignore[attr-defined]
            grid=grid,
            symbols=symbols,
            start=start,
            end=pre_sealed_end,
            source=source,
            cost_model=cost_model,
            min_trades=th.sensitivity_min_grid_trades,
            positive_fraction_min=th.sensitivity_positive_fraction_min,
            neighbour_fraction_min=th.sensitivity_neighbour_fraction_min,
        )
        gates.append(
            Gate(
                5,
                "parameter_sensitivity",
                not sens.fragile,
                (
                    f"{sens.n_evaluable}/{sens.n_points} grid points evaluable, "
                    f"{sens.positive_fraction:.0%} positive, "
                    f"{sens.neighbour_positive_fraction:.0%} of one-step neighbours positive"
                    + (f"; {'; '.join(sens.reasons)}" if sens.reasons else "")
                ),
                sens.to_dict(),
            )
        )

    # Gate 6: bull / bear / range-bound coverage.
    proxy_full = PriceSeries.load(session, proxy_symbol, start, pre_sealed_end, source=source)
    regimes = label_regimes(proxy_full) if len(proxy_full) else {}
    bucket_counts = {"bull": 0, "bear": 0, "range": 0}
    for t in full.trades:
        lbl = regimes.get(t.entry_date, "warmup")
        if lbl == "range_bound":
            bucket_counts["range"] += 1
        elif lbl.startswith("bull"):
            bucket_counts["bull"] += 1
        elif lbl.startswith("bear"):
            bucket_counts["bear"] += 1
    covered = sum(1 for c in bucket_counts.values() if c >= th.min_trades_per_regime)
    gate6_pass = bool(covered >= th.min_regimes_covered)
    gates.append(
        Gate(
            6,
            "regime_coverage",
            gate6_pass,
            f"trades per regime — bull {bucket_counts['bull']}, bear {bucket_counts['bear']}, "
            f"range {bucket_counts['range']} (need >= {th.min_trades_per_regime} each in "
            f"{th.min_regimes_covered} of 3 regimes; {covered}/3 met)",
            {"trades_per_regime": bucket_counts, "min_trades_per_regime": th.min_trades_per_regime},
        )
    )

    # Gate 7: risk-adjusted benchmark comparison. Annualise both sides over the
    # SAME actually-available span: if the proxy's real ingested history starts
    # later than `start` (a shorter data-provider entitlement than requested),
    # compute_portfolio_metrics would silently annualise the strategy's trades
    # over the full nominal window while _benchmark_metrics self-corrects to
    # its real date range — biasing the comparison. Use the proxy's actual
    # matched dates for both.
    proxy_span_dates = [d for d in proxy_full.dates if start <= d <= pre_sealed_end]
    eff_start = proxy_span_dates[0] if proxy_span_dates else start
    eff_end = proxy_span_dates[-1] if proxy_span_dates else pre_sealed_end
    pm_strategy = compute_portfolio_metrics(full.trades, span_start=eff_start, span_end=eff_end)
    bench = _benchmark_metrics(proxy_full, eff_start, eff_end)
    gate7_pass = bool(
        (not th.require_beat_benchmark_sharpe) or pm_strategy.sharpe > bench["sharpe"]
    )
    gates.append(
        Gate(
            7,
            "benchmark_comparison",
            gate7_pass,
            f"strategy Sharpe {pm_strategy.sharpe:+.2f} (CAGR {pm_strategy.cagr_pct:+.1f}%, "
            f"vol {pm_strategy.ann_vol_pct:.1f}%, maxDD {pm_strategy.max_drawdown_pct:.1f}%, "
            f"turnover {pm_strategy.turnover_per_year:.1f}/yr, exposure "
            f"{pm_strategy.exposure:.2f}) "
            f"vs {proxy_symbol} buy-and-hold Sharpe {bench['sharpe']:+.2f} (CAGR "
            f"{bench['cagr_pct']:+.1f}%, vol {bench['ann_vol_pct']:.1f}%, maxDD "
            f"{bench['max_drawdown_pct']:.1f}%) over the same span — risk-adjusted, not "
            f"cumulative return alone",
            {"strategy": pm_strategy.to_dict(), "benchmark": bench},
        )
    )

    # Gate 8: data-quality + leakage. Deliberately checks ONLY the real
    # provider tag (the first entry when `source` is a sequence) — a
    # symbol-continuity bridge tag is never treated as equivalent to raw
    # single-provider data for this specific check, even though gates 1-7/9
    # do load and trade its bars via the full `source` filter above.
    if isinstance(source, str):
        provider = source
    elif source:
        provider = source[0]
    else:
        provider = "unknown"
    validation = validate_daily(session, symbols, source=provider, persist=True)
    leak_err = _leakage_self_check(session, proxy_symbol, start, pre_sealed_end, source)
    gate8_pass = bool(
        (validation.passed or not th.require_data_validation_pass)
        and (leak_err is None or not th.require_leakage_check_pass)
    )
    findings = [c.detail for c in validation.checks if not c.passed]
    gates.append(
        Gate(
            8,
            "data_quality_and_leakage",
            gate8_pass,
            (
                f"validate_daily: {'PASS' if validation.passed else 'FAIL'}"
                + (f" ({'; '.join(findings)})" if findings else "")
                + f"; leakage self-check: {'clean' if leak_err is None else leak_err}"
            ),
            {
                "data_validation_passed": validation.passed,
                "data_validation_findings": findings,
                "leakage_error": leak_err,
                "known_caveats": [
                    "the equities universe is a fixed hand-picked large-cap list — it embeds "
                    "survivorship bias (no delisted names, no point-in-time membership)",
                ],
            },
        )
    )

    # Gate 9: sealed test — computed once, immutable, reused on every later call.
    sealed_row, sealed_reused = _get_or_create_sealed_test(
        session,
        strategy,
        version,
        symbols=symbols,
        sealed_start=sealed_start,
        end=sealed_end,
        proxy_symbol=proxy_symbol,
        source=source,
        cost_model=cost_model,
        th=th,
        dataset_snapshot_id=dataset_snapshot.id,
    )
    seal_note = "reused, locked on a prior evaluation" if sealed_reused else "evaluated now, locked"
    gates.append(
        Gate(
            9,
            "sealed_final_test",
            sealed_row.passed,
            f"sealed window {sealed_row.window_start}..{sealed_row.window_end} ({seal_note}; "
            f"never recomputed once locked): {sealed_row.detail}",
            {
                "sealed_test_id": sealed_row.id,
                "window": f"{sealed_row.window_start}..{sealed_row.window_end}",
                "metrics": sealed_row.metrics_json,
                "benchmark": sealed_row.benchmark_metrics_json,
                "dataset_snapshot": {"id": dataset_snapshot.id, "key": dataset_snapshot.key},
            },
        )
    )

    # Gate 10: the live-paper probation mechanism is defined and active.
    hm = config.health_monitor
    gates.append(
        Gate(
            10,
            "live_paper_probation",
            hm.enabled,
            (
                f"health-monitor probation "
                f"{'active' if hm.enabled else 'DISABLED — cannot promote'}: downgrade to "
                f"experimental at z<={hm.downgrade_z} once >={hm.min_paper_trades} paper trades "
                f"exist and paper expectancy is negative; disable at z<={hm.disable_z}. Applies "
                f"automatically the moment this version books paper trades — no separate action "
                f"needed"
            ),
            {
                "enabled": hm.enabled,
                "min_paper_trades": hm.min_paper_trades,
                "downgrade_z": hm.downgrade_z,
                "disable_z": hm.disable_z,
            },
        )
    )

    return _finalize(
        session,
        strategy,
        version,
        config,
        symbols,
        start,
        end,
        gates,
        sealed_row.id,
        data_provenance,
        dataset_snapshot.id,
    )


def _finalize(
    session: Session,
    strategy: BaselineStrategy,
    version: StrategyVersion,
    config: ResearchConfig,
    symbols: list[str],
    window_start: date,
    window_end: date,
    gates: list[Gate],
    sealed_test_id: int | None,
    data_provenance: dict[str, Any],
    dataset_snapshot_id: int | None = None,
) -> PromotionResult:
    spec = strategy.spec()
    passed = bool(gates) and all(g.passed for g in gates)
    verdict = VERDICT_APPROVED if passed else VERDICT_NO_TRADE
    now = utcnow()

    row = StrategyPromotionEvaluation(
        strategy_version_id=version.id,
        dataset_snapshot_id=dataset_snapshot_id,
        evaluated_at=now,
        config_hash=config.config_hash,
        git_sha=spec.git_sha,
        universe_json=list(symbols),
        window_start=window_start,
        window_end=window_end,
        data_provenance_json=data_provenance,
        gates_json=[g.to_dict() for g in gates],
        passed=passed,
        verdict=verdict,
        sealed_test_id=sealed_test_id,
    )
    session.add(row)
    session.flush()

    if passed:
        strat = session.get(Strategy, version.strategy_id)
        before = strat.status.value if strat else version.status.value
        if strat is not None:
            strat.status = StrategyStatus.PAPER_APPROVED
        version.status = StrategyStatus.PAPER_APPROVED
        session.flush()
        session.add(
            AuditLog(
                ts=now,
                actor="promotion_pipeline",
                action="strategy.promote",
                entity=f"{spec.name}@{spec.version}",
                before_json={"status": before},
                after_json={
                    "status": StrategyStatus.PAPER_APPROVED.value,
                    "evaluation_id": row.id,
                    "gates_passed": len(gates),
                },
            )
        )
        session.flush()
        audit.record(
            "strategy.promote",
            actor="promotion_pipeline",
            entity=f"{spec.name}@{spec.version}",
            before=before,
            after=StrategyStatus.PAPER_APPROVED.value,
            evaluation_id=row.id,
        )
        _log.warning(
            "promotion.approved", strategy=spec.name, version=spec.version, evaluation_id=row.id
        )
    else:
        _log.info(
            "promotion.no_trade",
            strategy=spec.name,
            version=spec.version,
            evaluation_id=row.id,
            failed_gates=[g.name for g in gates if not g.passed],
        )

    return PromotionResult(
        strategy_key=spec.name,
        version=spec.version,
        strategy_version_id=version.id,
        evaluation_id=row.id,
        evaluated_at=now.isoformat(),
        config_hash=config.config_hash,
        git_sha=spec.git_sha,
        universe=list(symbols),
        window_start=window_start,
        window_end=window_end,
        data_provenance=data_provenance,
        gates=gates,
        passed=passed,
        verdict=verdict,
        sealed_test_id=sealed_test_id,
        dataset_snapshot_id=dataset_snapshot_id,
    )


def evaluate_all_default_strategies(
    session: Session,
    *,
    symbols: list[str] | None = None,
    start: date | None = None,
    end: date | None = None,
    source: SourceFilter = None,
    config: ResearchConfig | None = None,
    dataset_snapshot: DataSnapshot | None = None,
) -> list[PromotionResult]:
    """Evaluate every default strategy. Convenience wrapper for the CLI and the
    Strategy Promotion dashboard page's "run now" action.

    ``dataset_snapshot``, when given, is used for every strategy — the
    mechanism the FB/META dataset-comparison report uses to run the full
    default set once per named universe variant."""
    from datetime import date as _date

    from signalforge.research.strategies import default_strategies
    from signalforge.settings_store import effective_research_config

    cfg = config or effective_research_config(session)
    syms = symbols or list(cfg.universe)
    end = end or _date.today()
    start = start or (end - timedelta(days=365 * 10))

    results: list[PromotionResult] = []
    for strat in default_strategies():
        results.append(
            evaluate_promotion(
                session,
                strat,
                symbols=syms,
                start=start,
                end=end,
                source=source,
                config=cfg,
                dataset_snapshot=dataset_snapshot,
            )
        )
    return results


def latest_evaluations(session: Session) -> dict[int, StrategyPromotionEvaluation]:
    """Most recent evaluation row per strategy_version_id."""
    rows = session.execute(
        select(StrategyPromotionEvaluation).order_by(
            StrategyPromotionEvaluation.strategy_version_id,
            StrategyPromotionEvaluation.evaluated_at.desc(),
            StrategyPromotionEvaluation.id.desc(),
        )
    ).scalars()
    out: dict[int, StrategyPromotionEvaluation] = {}
    for row in rows:
        out.setdefault(row.strategy_version_id, row)
    return out
