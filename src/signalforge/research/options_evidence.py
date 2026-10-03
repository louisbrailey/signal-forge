"""Assemble :class:`OptionsEvidence` from real data (D4 §6; the I-O4/I-O5 gap).

Wave 2 shipped the options engine, the runner reductions, the gate predicates and
``evaluate_options_promotion`` — and **no caller that measures any of it**.  Every
evidence object was built by hand in a test.  This module is the missing caller:
it loops a snapshot's underlyings, loads each one's chain, runs the dual-spread
engine over it, and reduces the whole population to the single
:class:`~signalforge.research.options_promotion.OptionsEvidence` the ladder
consumes.

Four properties are structural here rather than conventional:

* **Nothing is written, and no write transaction is ever opened.**  Every database
  read runs on the session the caller hands in; ``validate_daily`` is called with
  ``persist=False``; no row is added, flushed or updated anywhere in this module.
  The chain load is bounded per underlying and released before the next one, so a
  long assembly never holds the SQLite write lock (``docs/SQLITE_CONCURRENCY.md``
  rule 4).  The *decision* to write belongs to ``evaluate_options_promotion``.
* **No per-contract row reaches any report.**  Contracts and their bars are read
  into memory because the engine needs them to price a fill; every field this
  module *emits* is a count, a fraction, a date, an identity or a pooled
  statistic.  The one price-shaped number that leaves here is a P&L-derived R
  statistic over the pooled population, which is what the ladder exists to gate.
  Coverage is read from :func:`signalforge.data.options_backfill.coverage_summary`,
  whose own ``assert_price_free`` makes the counts-only property mechanical.
* **The clustered bootstrap is implemented, seeded and recorded.**  D4 §6.3 item
  12 / OQ-8 pre-register the unit ``(underlying, expiry cycle)``; the equity side
  has never computed one, so there is no precedent to inherit and the seed is
  pinned in :data:`OPTIONS_CLUSTER_BOOTSTRAP_SEED` and reported in the evidence.
  D5 §6.3b's F11 declares a *different*, coarser unit — the cycle-month pooled
  across underlyings — and F11 is a NO-SHIP disposition rule, not gate 4.  The two
  disagree, so **both are computed** and both land in
  ``OptionsDataQuality.clustered_bootstrap_ci``: the D4 unit under ``low``/``high``
  (matching ``clustering_unit``, which gate 8 prints) and the F11 unit under the
  ``f11_*`` keys.  Neither is silently picked.
* **The sealed year is opt-in.**  ``include_sealed`` defaults to ``False``, so an
  assembly cannot produce a :class:`SealedOptionsOutcome` — and therefore cannot
  consume a sealed look — unless the caller asks for one explicitly.  That is what
  lets the CLI's ``--dry-run`` print a full ladder with gate 9 failing honestly.

**Interpretations recorded rather than defaulted.**  Three evidence fields have no
single mechanical definition in D4/D5, and the reading used here is stated so a
reviewer can disagree with it:

1. ``bar_continuity_min_observed`` is the **minimum over underlyings** of that
   underlying's evaluation-wide marked-session fraction (``1 - unmarked/held``),
   which is the quantity D5 §5.2 pre-registers at 0.80.  D5's 0.60 *per-structure*
   stratification is reported separately as
   ``OptionsDataQuality.thin_continuity_fraction`` — the share of structures below
   it — so the two thresholds are not conflated into one number.
2. ``surface_n_actual_min`` is measured from the chain, not from the pricer: the
   minimum, over the (session, expiry) pairs a trade actually touched, of the
   number of distinct printed strikes on that expiry.  That is the sample a
   same-session surface *would* be fitted from, and it is 0 — an honest gate-0.e
   failure — when there are no trades.
3. ``limits_in_options_config_hash`` is computed by asking
   ``OptionsEvaluationConfig`` whether it carries the limit fields at all.  Today
   it does not (they live on the paper-side ``execution_limits`` row, which S11b
   forbids this module from importing), so the answer is ``False`` and gate 0.i
   fails — which is the wave-2 finding, surfaced rather than papered over.

S11b: this module sits on the same side of the wall as ``options_gates`` and
imports nothing from ``llm``, ``alerts``, ``execution`` or any paper ledger.
"""

from __future__ import annotations

import hashlib
import math
import statistics
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Protocol

import numpy as np
from sqlalchemy import distinct, func, select
from sqlalchemy.orm import Session

from signalforge.backtest.options_costs import OptionCostModel
from signalforge.backtest.options_engine import (
    FILL_MODEL,
    OptionsBacktestOutcome,
    OptionsCounters,
    OptionsEntrySignal,
    OptionTrade,
    RBasis,
)
from signalforge.backtest.options_leakage import chain_leakage_self_check
from signalforge.backtest.options_pricing import IvSource
from signalforge.config.research import OptionsEvaluationConfig
from signalforge.data import calendar as equity_calendar
from signalforge.data import options_calendar
from signalforge.data.option_chain import ContractPrint, ContractRef, OptionChainSeries, Right
from signalforge.data.options_backfill import OptionsCoverageSummary, coverage_summary
from signalforge.data.options_corporate_actions import Q_SERIES_SOURCE, splits_between
from signalforge.data.series import PriceSeries
from signalforge.db.models import DataSnapshot, DividendYieldDaily, EntitlementCheck, IngestionRun
from signalforge.db.models.market import OptionAggregateDaily, OptionContract
from signalforge.domain import Horizon
from signalforge.observability import get_logger
from signalforge.research.options_backtest_runner import (
    DualSpreadReport,
    JointRegimeCensus,
    RegimePartitionDisclosure,
    _cells_for,  # the SAME four-way reduction the runner uses; see _pool_dual
    is_oos_boundary,
    joint_regime_census,
    options_portfolio_metrics,
    regime_partition_crosstab,
    run_dual_spread,
)
from signalforge.research.options_gates import (
    BenchmarkPair,
    OptionsDataAvailability,
    OptionsDataQuality,
    OptionsGate,
    OptionsGateThresholds,
    OptionsSensitivitySummary,
    OptionsWindow,
    SealedOptionsOutcome,
    StressedOos,
    StructureIdentity,
    UnderlyingCoverage,
    gate_0_5_structure,
    gate_0a_window,
    gate_0b_underlyings,
    gate_0c_bracketing,
    gate_0d_continuity,
    gate_0e_iv_provenance,
    gate_0f_fill_provenance,
    gate_0g_dividend_yield,
    gate_0h_deliverable,
    gate_0i_risk_limits,
    gate_1_walkforward,
    gate_2_oos_trades,
    gate_3_expectancy,
    gate_4_bootstrap,
    gate_4b_dual_spread,
    gate_5_sensitivity,
    gate_6_regime,
    gate_6b_joint,
    gate_7_benchmark,
    gate_7b_mechanical,
    gate_8_data_quality,
    gate_9_sealed,
    gate_10_probation,
)
from signalforge.research.options_promotion import OptionsEvidence

_log = get_logger("research.options_evidence")

# --------------------------------------------------------------------------- #
# pre-registered constants
# --------------------------------------------------------------------------- #

#: D4 §6.3 item 12 / OQ-8.  The cluster bootstrap has no equity precedent, so the
#: seed is pinned HERE and recorded in the evidence rather than inherited from
#: ``montecarlo.bootstrap_ci``'s own ``20240101`` — two different resamplers
#: sharing one seed would look like agreement where there is none (S4).
OPTIONS_CLUSTER_BOOTSTRAP_SEED = 20260912
OPTIONS_CLUSTER_RESAMPLES = 2_000
OPTIONS_CLUSTER_CI = 0.95

#: The D4 unit, and the value ``OptionsDataQuality.clustering_unit`` defaults to.
CLUSTER_UNIT_D4 = "(underlying, expiry cycle)"
#: D5 §6.3b F11's coarser unit — same cycle, pooled ACROSS underlyings.
CLUSTER_UNIT_F11 = "(expiry cycle) pooled across underlyings"

#: The pre-registration whose commit freezes the cost-model constants (D4 §2.6).
D5_PREREGISTRATION_PATH = "docs/research/options_designs/D5_first_strategy_preregistration.md"

#: Option bars and the underlying closes that index them must share one basis:
#: a listed strike is an unadjusted number, so the close it is compared against
#: is loaded unadjusted too.  Splits are handled by EXCLUSION (D1 §7), which is
#: why ``corporate_action_exclusions`` is gate-8 evidence rather than a silent
#: re-basing.
UNDERLYING_ADJUSTED = False


class OptionsEvidenceError(ValueError):
    """The assembly cannot proceed on the inputs it was handed."""


# --------------------------------------------------------------------------- #
# the strategy surface this module needs (structural, not nominal)
# --------------------------------------------------------------------------- #
class OptionsStrategy(Protocol):
    """What an options strategy must expose to be evaluable.

    A Protocol rather than an import of ``OptionsShortVertical`` so that a test
    can drive the assembler with a three-line synthetic strategy, and so that a
    second family cannot be added by editing this module.
    """

    key: str
    horizon: Horizon
    selection_cost_model: OptionCostModel

    def __call__(
        self, chain: OptionChainSeries, underlying: PriceSeries, t: int
    ) -> OptionsEntrySignal | None: ...

    def sensitivity_axes(self) -> Mapping[str, Sequence[float | int]]: ...

    def oat_parameters(self) -> Mapping[str, Sequence[float | int]]: ...

    def structure_identity(self) -> StructureIdentity: ...

    def mechanical_benchmark(self) -> OptionsStrategy: ...

    def mechanical_spec(self) -> dict[str, object]: ...


# --------------------------------------------------------------------------- #
# clustered bootstrap (D4 §6.3 item 12, OQ-8) — implemented, seeded, recorded
# --------------------------------------------------------------------------- #
ClusterKeyFn = Callable[[OptionTrade], tuple[str, ...]]


def expiry_cycle_of(trade: OptionTrade) -> date:
    """The monthly expiry cycle a closed structure belonged to.

    ``OptionTrade`` carries no expiration — it is a *reduction* of the structure,
    not the structure — so the cycle is recovered from the exit session.  Under
    the pre-registered monthly third-Friday cycle rule (D1 §3) a structure is
    always force-closed on or before its own expiry, so the next monthly expiry
    at or after the exit session **is** that structure's expiry.  A weekly or
    quarterly rule would break the identity, which is why it is a named function
    with its own test rather than an inline expression.
    """
    return options_calendar.cycle_of(trade.exit_date)


def cluster_key_underlying_cycle(trade: OptionTrade) -> tuple[str, ...]:
    """D4 §6.3 item 12 / OQ-8: ``(underlying, expiry cycle)``."""
    return (trade.underlying_symbol, expiry_cycle_of(trade).isoformat())


def cluster_key_cycle_only(trade: OptionTrade) -> tuple[str, ...]:
    """D5 §6.3b F11: the cycle-month, pooled across underlyings."""
    return (expiry_cycle_of(trade).isoformat(),)


@dataclass(frozen=True, slots=True)
class ClusteredBootstrap:
    """A cluster-resampled CI for expectancy, with its design effect.

    ``rho`` is the one-way ANOVA intra-cluster correlation and ``deff =
    1 + (mbar - 1) * rho`` is the planning quantity D5 §6.3b tabulates.  A
    negative estimated ``rho`` is reported as 0.0 — it means the observed
    between-cluster variance is below the within-cluster variance, which is not
    evidence of *negative* dependence at these sample sizes.
    """

    unit: str
    seed: int
    n_resamples: int
    ci: float
    n_trades: int
    n_clusters: int
    mean_cluster_size: float
    point: float
    low: float
    high: float
    rho: float
    deff: float

    def to_mapping(self, prefix: str = "") -> dict[str, float]:
        """Flat floats only — ``OptionsDataQuality.clustered_bootstrap_ci`` is a
        ``Mapping[str, float]`` and gate 8 copies it verbatim into ``gates_json``."""
        return {
            f"{prefix}low": round(self.low, 6),
            f"{prefix}point": round(self.point, 6),
            f"{prefix}high": round(self.high, 6),
            f"{prefix}rho": round(self.rho, 6),
            f"{prefix}deff": round(self.deff, 6),
            f"{prefix}n_clusters": float(self.n_clusters),
            f"{prefix}mean_cluster_size": round(self.mean_cluster_size, 6),
            f"{prefix}n_trades": float(self.n_trades),
            f"{prefix}seed": float(self.seed),
            f"{prefix}n_resamples": float(self.n_resamples),
        }


def _icc_one_way(groups: Sequence[Sequence[float]]) -> float:
    """One-way random-effects ICC over unequal group sizes; 0.0 when undefined."""
    k = len(groups)
    n_total = sum(len(g) for g in groups)
    if k < 2 or n_total <= k:
        return 0.0
    grand = sum(sum(g) for g in groups) / n_total
    ms_between = sum(len(g) * (sum(g) / len(g) - grand) ** 2 for g in groups) / (k - 1)
    ms_within = (
        sum(sum((x - sum(g) / len(g)) ** 2 for x in g) for g in groups) / (n_total - k)
        if n_total > k
        else 0.0
    )
    n0 = (n_total - sum(len(g) ** 2 for g in groups) / n_total) / (k - 1)
    denom = ms_between + (n0 - 1) * ms_within
    if denom <= 0:
        return 0.0
    return max(0.0, (ms_between - ms_within) / denom)


def clustered_bootstrap_ci(
    trades: Sequence[OptionTrade],
    *,
    key_fn: ClusterKeyFn = cluster_key_underlying_cycle,
    unit: str = CLUSTER_UNIT_D4,
    seed: int = OPTIONS_CLUSTER_BOOTSTRAP_SEED,
    n_resamples: int = OPTIONS_CLUSTER_RESAMPLES,
    ci: float = OPTIONS_CLUSTER_CI,
    value_of: Callable[[OptionTrade], float] = lambda t: t.pnl_r,
) -> ClusteredBootstrap:
    """Resample whole CLUSTERS with replacement, never individual trades.

    ``bootstrap_ci`` resamples a bare float sequence, which assumes the trades
    are independent.  Fourteen short-vol structures on one monthly expiry are
    not, and D4 §6.3's note is explicit that the equity omission must not be
    repeated.  The estimator here is the cluster (block) bootstrap: draw ``k``
    clusters with replacement from the ``k`` observed clusters, concatenate their
    per-trade R values, and take the mean of the concatenation.  Cluster sizes
    therefore vary between resamples exactly as they do in the population.

    Deterministic: ``numpy.random.default_rng(seed)`` and a cluster ordering
    sorted by key, so the same trade list always produces the same interval (S4).
    """
    ordered = sorted({key_fn(t) for t in trades})
    grouped: dict[tuple[str, ...], list[float]] = {k: [] for k in ordered}
    for tr in trades:
        grouped[key_fn(tr)].append(float(value_of(tr)))
    groups = [grouped[k] for k in ordered]
    n_trades = sum(len(g) for g in groups)
    k = len(groups)
    if k == 0 or n_trades == 0:
        return ClusteredBootstrap(
            unit=unit,
            seed=seed,
            n_resamples=n_resamples,
            ci=ci,
            n_trades=0,
            n_clusters=0,
            mean_cluster_size=0.0,
            point=0.0,
            low=0.0,
            high=0.0,
            rho=0.0,
            deff=1.0,
        )
    point = sum(sum(g) for g in groups) / n_trades
    rho = _icc_one_way(groups)
    mbar = n_trades / k
    deff = 1.0 + (mbar - 1.0) * rho

    rng = np.random.default_rng(seed)
    arrays = [np.asarray(g, dtype=np.float64) for g in groups]
    draws = rng.integers(0, k, size=(n_resamples, k))
    means = np.empty(n_resamples, dtype=np.float64)
    for i in range(n_resamples):
        pooled = np.concatenate([arrays[j] for j in draws[i]])
        means[i] = pooled.mean()
    lo_q = (1 - ci) / 2 * 100
    hi_q = (1 - (1 - ci) / 2) * 100
    return ClusteredBootstrap(
        unit=unit,
        seed=seed,
        n_resamples=n_resamples,
        ci=ci,
        n_trades=n_trades,
        n_clusters=k,
        mean_cluster_size=mbar,
        point=point,
        low=float(np.percentile(means, lo_q)),
        high=float(np.percentile(means, hi_q)),
        rho=rho,
        deff=deff,
    )


# --------------------------------------------------------------------------- #
# data loading — plain reads, bounded per underlying, nothing written
# --------------------------------------------------------------------------- #
def load_option_chain_series(
    session: Session,
    underlying: str,
    *,
    start: date,
    end: date,
    source: str,
    underlying_series: PriceSeries | None = None,
) -> OptionChainSeries | None:
    """Build one underlying's :class:`OptionChainSeries` from stored rows.

    ``None`` when the underlying has no daily bars in the window — a chain must be
    indexed by the *underlying's* session list (D2 §3.5), so without those bars
    there is no index and therefore no chain.  Sessions on which an option printed
    but the underlying did not are dropped by ``from_rows`` and counted by the
    caller; they are a data defect, never interpolated.

    A read-only query on the session it is handed.  Per-contract rows stop here:
    what leaves this function is an in-memory series the engine prices against,
    and nothing downstream emits a contract row into a report.
    """
    series = underlying_series or PriceSeries.load(
        session, underlying, start, end, source=source, adjusted=UNDERLYING_ADJUSTED
    )
    if not len(series):
        return None
    closes = dict(zip(series.dates, series.close, strict=True))

    meta_rows = session.scalars(
        select(OptionContract).where(
            OptionContract.underlying_symbol == underlying.upper(),
            OptionContract.source == source,
        )
    ).all()
    if not meta_rows:
        return None
    meta = {r.option_ticker: r for r in meta_rows}

    bar_rows = session.execute(
        select(
            OptionAggregateDaily.option_ticker,
            OptionAggregateDaily.session_date,
            OptionAggregateDaily.open,
            OptionAggregateDaily.high,
            OptionAggregateDaily.low,
            OptionAggregateDaily.close,
            OptionAggregateDaily.volume,
            OptionAggregateDaily.vwap,
            OptionAggregateDaily.transactions,
        )
        .where(
            OptionAggregateDaily.underlying_symbol == underlying.upper(),
            OptionAggregateDaily.source == source,
            OptionAggregateDaily.session_date >= start,
            OptionAggregateDaily.session_date <= end,
        )
        .order_by(OptionAggregateDaily.session_date, OptionAggregateDaily.option_ticker)
    ).all()
    if not bar_rows:
        return None

    prints: dict[date, dict[str, ContractPrint]] = {}
    first_seen: dict[str, date] = {}
    for ticker, sdate, o, h, low, c, vol, vwap, txns in bar_rows:
        if ticker not in meta:
            continue
        prints.setdefault(sdate, {})[ticker] = ContractPrint(
            open=float(o),
            high=float(h),
            low=float(low),
            close=float(c),
            volume=float(vol or 0.0),
            vwap=float(vwap) if vwap is not None else None,
            transactions=int(txns) if txns is not None else None,
        )
        if ticker not in first_seen or sdate < first_seen[ticker]:
            first_seen[ticker] = sdate

    contracts = [
        ContractRef(
            option_ticker=t,
            underlying_symbol=meta[t].underlying_symbol,
            right=Right(meta[t].contract_type),
            strike=float(meta[t].strike_price),
            expiration=meta[t].expiration_date,
            shares_per_contract=int(meta[t].shares_per_contract),
            exercise_style=str(meta[t].exercise_style),
            first_print_session=d,
        )
        for t, d in sorted(first_seen.items())
    ]
    if not contracts:
        return None
    return OptionChainSeries.from_rows(
        underlying, contracts=contracts, underlying_closes=closes, prints=prints
    )


def latest_options_coverage_summary(
    session: Session, *, window_start: date | None = None, window_end: date | None = None
) -> OptionsCoverageSummary | None:
    """The newest cycle-backfill run's coverage summary, or ``None``.

    Counts and completeness only: ``coverage_summary`` reads ``IngestionRun`` and
    never ``option_aggregate_daily``, and ``OptionsCoverageSummary`` cannot hold a
    price by construction.  This is the single entry point through which coverage
    reaches an evaluation.
    """
    stmt = select(IngestionRun).where(IngestionRun.kind == "options_cycle_backfill")
    if window_start is not None:
        stmt = stmt.where(IngestionRun.requested_end >= window_start)
    if window_end is not None:
        stmt = stmt.where(IngestionRun.requested_start <= window_end)
    run = session.scalars(stmt.order_by(IngestionRun.started_at.desc()).limit(1)).first()
    if run is None:
        return None
    OptionsCoverageSummary.assert_price_free()
    return coverage_summary(run)


def preregistration_digest(root: Path | None = None) -> str:
    """``D5@<sha256[:12]>`` of the pre-registration file, or ``""`` if absent.

    Gate 0.f needs a ``cost_model_frozen_at`` that is a *fact* rather than a
    promise.  Tying the freeze to the digest of the document that declares the
    constants means editing D5 changes the recorded freeze, which is exactly the
    disclosure R3 asks for.
    """
    base = root or Path(__file__).resolve().parents[3]
    path = base / D5_PREREGISTRATION_PATH
    if not path.is_file():
        return ""
    return "D5@" + hashlib.sha256(path.read_bytes()).hexdigest()[:12]


def preregistration_path(root: Path | None = None) -> Path:
    return (root or Path(__file__).resolve().parents[3]) / D5_PREREGISTRATION_PATH


@dataclass(frozen=True, slots=True)
class CoveragePreflight:
    """Gate 0's coverage floors, asked of the BACKFILL before a look is spent.

    Gate 0.c and 0.d are computed from the evaluated population; this asks the
    same two questions of the coverage summary, which is available *before* any
    chain is loaded.  It exists so a run that is going to fail gate 0 on coverage
    fails at the command line in a second, rather than after loading fourteen
    underlyings — and, on a ``--confirm`` run, before anything can be written.

    Counts only: the summary it reads cannot hold a price (``assert_price_free``).
    """

    passed: bool
    reasons: tuple[str, ...]
    bracket_fraction: float
    bar_continuity_fraction: float
    coverage_run_id: int | None
    underlyings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "reasons": list(self.reasons),
            "cycles_bracket_fraction": round(self.bracket_fraction, 6),
            "bar_continuity_fraction": round(self.bar_continuity_fraction, 6),
            "coverage_run_id": self.coverage_run_id,
            "underlyings": list(self.underlyings),
        }


def coverage_preflight(
    summary: OptionsCoverageSummary | None,
    *,
    evaluation: OptionsEvaluationConfig | None = None,
) -> CoveragePreflight:
    """Is the stored options coverage above gate 0.c's and 0.d's pre-registered floors?"""
    ev = evaluation or OptionsEvaluationConfig()
    if summary is None:
        return CoveragePreflight(
            passed=False,
            reasons=(
                "no options cycle-backfill run is recorded in this database, so gate 0.c and "
                "0.d have no coverage to read; run 'signalforge options cycle-backfill' first "
                "(docs/research/options_designs/IO2_RUNBOOK.md)",
            ),
            bracket_fraction=0.0,
            bar_continuity_fraction=0.0,
            coverage_run_id=None,
        )
    reasons: list[str] = []
    if not summary.underlyings:
        reasons.append("the coverage run requested no underlyings")
    if summary.cycles_bracket_fraction < ev.gate_0c_cycles_bracket:
        reasons.append(
            f"cycle bracketing {summary.cycles_bracket_fraction:.3f} is below gate 0.c's "
            f"pre-registered floor {ev.gate_0c_cycles_bracket:.2f} "
            f"({summary.cycles_covered}/{summary.cycles_total} cycles)"
        )
    if summary.bar_continuity_fraction < ev.gate_0d_session_bars:
        reasons.append(
            f"bar continuity {summary.bar_continuity_fraction:.3f} is below gate 0.d's "
            f"pre-registered floor {ev.gate_0d_session_bars:.2f} "
            f"({summary.bars_written:,}/{summary.sessions_expected:,} expected bars)"
        )
    if summary.status not in ("ok", "partial"):
        reasons.append(f"the coverage run's status is {summary.status!r}, not 'ok' or 'partial'")
    return CoveragePreflight(
        passed=not reasons,
        reasons=tuple(reasons),
        bracket_fraction=summary.cycles_bracket_fraction,
        bar_continuity_fraction=summary.bar_continuity_fraction,
        coverage_run_id=summary.run_id,
        underlyings=tuple(summary.underlyings),
    )


# --------------------------------------------------------------------------- #
# pooling the per-underlying runs into one population
# --------------------------------------------------------------------------- #
_COUNTER_INT_FIELDS = (
    "non_entry_missing_leg_bar",
    "non_entry_no_signal_window",
    "force_close_unpriceable_exclusions",
    "force_close_beyond_data",
    "shares_per_contract_refusals",
    "exercise_style_refusals",
    "structure_refusals",
    "zero_spread_refusals",
    "non_positive_r_refusals",
    "spread_ge_print_leg_sides",
    "sale_proceeds_floored_at_zero",
    "leg_sides_priced",
    "held_sessions",
    "unmarked_sessions",
    "r_clamped",
    "pin_risk_flag",
    "assignment_risk",
    "stop_non_binding",
    "n_losing_trades",
)


def pool_counters(counters: Sequence[OptionsCounters]) -> OptionsCounters:
    """Sum the per-underlying counters; ``*_max_run`` takes the max, not the sum."""
    out = OptionsCounters()
    for c in counters:
        for name in _COUNTER_INT_FIELDS:
            setattr(out, name, getattr(out, name) + getattr(c, name))
        out.long_leg_intrinsic_gap_dollars += c.long_leg_intrinsic_gap_dollars
        out.unmarked_sessions_max_run = max(
            out.unmarked_sessions_max_run, c.unmarked_sessions_max_run
        )
        out.exit_deferred_sessions.extend(c.exit_deferred_sessions)
    return out


def _pool_outcome(
    outcomes: Sequence[OptionsBacktestOutcome], *, label: str
) -> OptionsBacktestOutcome:
    trades: list[OptionTrade] = []
    excluded = []
    firsts = [o.first_date for o in outcomes if o.first_date is not None]
    lasts = [o.last_date for o in outcomes if o.last_date is not None]
    for o in outcomes:
        trades.extend(o.trades)
        excluded.extend(o.excluded)
    trades.sort(key=lambda t: (t.entry_date, t.underlying_symbol))
    return OptionsBacktestOutcome(
        underlying_symbol=label,
        r_basis=outcomes[0].r_basis if outcomes else RBasis.INCL,
        spread_multiplier=outcomes[0].spread_multiplier if outcomes else 1.0,
        trades=trades,
        excluded=excluded,
        counters=pool_counters([o.counters for o in outcomes]),
        sessions=sum(o.sessions for o in outcomes),
        first_date=min(firsts) if firsts else None,
        last_date=max(lasts) if lasts else None,
    )


def pool_dual(reports: Sequence[DualSpreadReport], *, label: str = "") -> DualSpreadReport:
    """One :class:`DualSpreadReport` over every underlying's population.

    The four cells are recomputed by ``options_backtest_runner._cells_for`` — the
    *same* private reduction ``run_dual_spread`` uses, imported for the same reason
    ``options_backtest_runner`` itself imports ``backtest_runner._is_boundary``: a
    second implementation of "which cell binds" is a second answer waiting to
    disagree with the first.
    """
    if not reports:
        raise OptionsEvidenceError("no underlying produced a dual-spread report")
    name = label or f"POOLED({len(reports)})"
    base = _pool_outcome([r.baseline for r in reports], label=name)
    stress = _pool_outcome([r.stressed for r in reports], label=name)
    return DualSpreadReport(
        cells=_cells_for(base) | _cells_for(stress), baseline=base, stressed=stress
    )


# --------------------------------------------------------------------------- #
# per-underlying run
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class UnderlyingRun:
    """One underlying's contribution, kept for disclosure — never a contract row."""

    symbol: str
    coverage: UnderlyingCoverage
    sessions: int
    chain_sessions: int
    dropped_sessions: int
    dual: DualSpreadReport | None
    mechanical: DualSpreadReport | None
    chain_leakage_error: str | None
    marked_fraction: float
    surface_n_min: int
    bracket_matrix: dict[str, dict[str, float]]
    cycles_eligible: int
    cycles_bracketed: int
    skipped_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "sessions": self.sessions,
            "chain_sessions": self.chain_sessions,
            "dropped_sessions": self.dropped_sessions,
            "n_trades": len(self.dual.baseline.trades) if self.dual else 0,
            "marked_fraction": round(self.marked_fraction, 6),
            "surface_n_min": self.surface_n_min,
            "cycles_eligible": self.cycles_eligible,
            "cycles_bracketed": self.cycles_bracketed,
            "chain_leakage_error": self.chain_leakage_error,
            "skipped_reason": self.skipped_reason,
        }


@dataclass(frozen=True, slots=True)
class AssembledEvidence:
    """The evidence plus everything that explains how it was measured."""

    evidence: OptionsEvidence
    per_underlying: tuple[UnderlyingRun, ...]
    coverage: OptionsCoverageSummary | None
    clustered_d4: ClusteredBootstrap
    clustered_f11: ClusteredBootstrap
    boundary: date | None
    notes: tuple[str, ...] = ()

    @property
    def universe(self) -> list[str]:
        return [u.symbol for u in self.per_underlying]

    def provenance(self) -> dict[str, Any]:
        return {
            "assembler": "signalforge.research.options_evidence:assemble_options_evidence",
            "underlyings": [u.to_dict() for u in self.per_underlying],
            "is_oos_boundary": self.boundary.isoformat() if self.boundary else None,
            "clustered_bootstrap": {
                "d4_unit": self.clustered_d4.unit,
                "f11_unit": self.clustered_f11.unit,
                "seed": self.clustered_d4.seed,
                "n_resamples": self.clustered_d4.n_resamples,
            },
            "coverage_run_id": self.coverage.run_id if self.coverage else None,
            "notes": list(self.notes),
        }


def _marked_fraction(counters: OptionsCounters) -> float:
    if not counters.held_sessions:
        return 0.0
    return 1.0 - counters.unmarked_sessions / counters.held_sessions


def _bracket_matrix(
    chain: OptionChainSeries,
    *,
    dte_targets: Sequence[int],
    window: OptionsWindow,
) -> tuple[dict[str, dict[str, float]], int, int]:
    """Does the listed ladder straddle the underlying close at each declared cell?

    D4 §2.3's denominator is strategy-independent: a cycle is eligible iff its
    expiry falls inside the evaluation window and the underlying is covered over
    it.  Nothing about the regime filter, the delta target or the width enters
    here — which is what keeps the denominator identical in every grid cell.
    """
    matrix: dict[str, dict[str, float]] = {}
    eligible_cycles: set[date] = set()
    bracketed_cycles: set[date] = set()
    dates = chain.session_dates()
    if not dates:
        return {}, 0, 0
    expiries = sorted({c.expiration for c in chain.contracts.values()})
    expiries = [e for e in expiries if window.start <= e <= window.end]
    for dte in sorted({int(d) for d in dte_targets}):
        cell: dict[str, float] = {}
        for side in ("put", "call"):
            seen = brack = 0
            for exp in expiries:
                target = exp - timedelta(days=dte)
                idx = next((i for i, d in enumerate(dates) if d >= target), None)
                if idx is None:
                    continue
                seen += 1
                eligible_cycles.add(exp)
                close = chain.underlying_close(idx)
                strikes = [
                    c.strike
                    for c in chain.visible_contracts(idx).values()
                    if c.expiration == exp and c.right.value == side
                ]
                if close is not None and strikes and min(strikes) < close < max(strikes):
                    brack += 1
                    bracketed_cycles.add(exp)
            cell[side] = (brack / seen) if seen else 0.0
        matrix[str(dte)] = cell
    return matrix, len(eligible_cycles), len(bracketed_cycles)


def _surface_n_min(chain: OptionChainSeries, trades: Sequence[OptionTrade]) -> int:
    """Distinct printed strikes on the expiries a trade actually touched."""
    dates = chain.session_dates()
    index = {d: i for i, d in enumerate(dates)}
    best: int | None = None
    for tr in trades:
        exp = expiry_cycle_of(tr)
        for d in (tr.entry_date, tr.exit_date):
            i = index.get(d)
            if i is None:
                continue
            strikes = {
                chain.contracts[t].strike
                for t in chain.printed_tickers(i)
                if t in chain.contracts and chain.contracts[t].expiration == exp
            }
            best = len(strikes) if best is None else min(best, len(strikes))
    return best or 0


def run_underlying(
    session: Session,
    strategy: OptionsStrategy,
    symbol: str,
    *,
    window: OptionsWindow,
    source: str,
    dte_targets: Sequence[int],
    include_mechanical: bool = True,
    warmup: int = 50,
) -> UnderlyingRun:
    """Load one underlying, run the dual-spread pass, and reduce it.

    A plain read followed by pure compute.  Nothing here writes, and the chain is
    dropped when the function returns so peak memory is one underlying, not the
    universe.
    """
    series = PriceSeries.load(
        session, symbol, window.start, window.end, source=source, adjusted=UNDERLYING_ADJUSTED
    )
    sessions_expected = len(equity_calendar.sessions(window.start, window.end))
    coverage = UnderlyingCoverage(
        symbol=symbol,
        source=source,
        first_bar=series.dates[0] if len(series) else None,
        last_bar=series.dates[-1] if len(series) else None,
        gap_sessions=max(0, sessions_expected - len(series)) if len(series) else 0,
    )
    empty = UnderlyingRun(
        symbol=symbol,
        coverage=coverage,
        sessions=len(series),
        chain_sessions=0,
        dropped_sessions=0,
        dual=None,
        mechanical=None,
        chain_leakage_error=None,
        marked_fraction=0.0,
        surface_n_min=0,
        bracket_matrix={},
        cycles_eligible=0,
        cycles_bracketed=0,
    )
    if not len(series):
        return replace(empty, skipped_reason="no underlying bars in the window")

    chain = load_option_chain_series(
        session, symbol, start=window.start, end=window.end, source=source, underlying_series=series
    )
    if chain is None:
        return replace(empty, skipped_reason="no option chain rows in the window")

    baseline = strategy.selection_cost_model
    stressed = replace(baseline, spread_multiplier=2.0)
    dual = run_dual_spread(
        chain, series, strategy, baseline=baseline, stressed=stressed, warmup=warmup
    )
    mech = None
    if include_mechanical:
        mech = run_dual_spread(
            chain,
            series,
            strategy.mechanical_benchmark(),
            baseline=baseline,
            stressed=stressed,
            warmup=warmup,
        )
    matrix, eligible, bracketed = _bracket_matrix(chain, dte_targets=dte_targets, window=window)
    return UnderlyingRun(
        symbol=symbol,
        coverage=coverage,
        sessions=len(series),
        chain_sessions=len(chain),
        dropped_sessions=max(0, len(series) - len(chain)),
        dual=dual,
        mechanical=mech,
        chain_leakage_error=chain_leakage_self_check(chain, series),
        marked_fraction=_marked_fraction(dual.baseline.counters),
        surface_n_min=_surface_n_min(chain, dual.baseline.trades),
        bracket_matrix=matrix,
        cycles_eligible=eligible,
        cycles_bracketed=bracketed,
    )


# --------------------------------------------------------------------------- #
# the assembler
# --------------------------------------------------------------------------- #
def _split_presealed(trades: Sequence[OptionTrade], window: OptionsWindow) -> list[OptionTrade]:
    return [t for t in trades if window.start <= t.entry_date <= window.pre_sealed_end]


def _split_sealed(trades: Sequence[OptionTrade], window: OptionsWindow) -> list[OptionTrade]:
    return [t for t in trades if window.sealed_start <= t.entry_date <= window.end]


def _concurrent_open_r_max(trades: Sequence[OptionTrade]) -> float:
    """Max simultaneously-open R in dollars — a sweep, not an assumption."""
    events: list[tuple[date, int, float]] = []
    for t in trades:
        events.append((t.entry_date, 1, t.r_incl))
        events.append((t.exit_date, -1, t.r_incl))
    events.sort(key=lambda e: (e[0], e[1]))
    cur = peak = 0.0
    for _d, sign, r in events:
        cur += sign * r
        peak = max(peak, cur)
    return peak


def _iv_source_mix(trades: Sequence[OptionTrade]) -> tuple[dict[str, float], int]:
    named = {s.value for s in IvSource}
    counts: dict[str, int] = {}
    unnamed = 0
    for t in trades:
        value = getattr(t.iv_source, "value", str(t.iv_source))
        if value not in named:
            unnamed += 1
            continue
        counts[value] = counts.get(value, 0) + 1
    total = sum(counts.values())
    mix = {k: v / total for k, v in sorted(counts.items())} if total else {}
    return mix, unnamed


def _q_by_underlying(
    session: Session,
    symbols: Sequence[str],
    *,
    window: OptionsWindow,
    trades: Sequence[OptionTrade],
    source: str = Q_SERIES_SOURCE,
) -> tuple[dict[str, dict[str, Any]], int]:
    """Summarise the derived ``q`` series per underlying over the PRE-SEALED span.

    Gate 0.g distinguishes a recorded, sourced ``q`` from one that fell through
    the pricer's 0.0 default, so the record is a ``(value, source, as_of)``
    triple plus coverage, never a bare float.  Everything here is read at or
    before ``window.pre_sealed_end``: the previous single ``as_of`` at
    ``window.end`` read a SEALED-window date, which an assembler that runs
    before the sealed test may not do.

    An underlying counts as DEFAULTED when the series has no row on the
    pre-sealed span, or when any pre-sealed entry it took has no row on its
    signal session — the only two ways a priced structure can have rested on an
    unsourced ``q``.  ``derive_dividend_yield_series`` writes no row where there
    is no dividend history, so an absent row stays absent here too.
    """
    out: dict[str, dict[str, Any]] = {}
    defaulted = 0
    lo, hi = window.start, window.pre_sealed_end
    traded: dict[str, set[date]] = {}
    for t in trades:
        if lo <= t.entry_date <= hi:
            traded.setdefault(t.underlying_symbol, set()).add(t.entry_date)
    for sym in symbols:
        rows = list(
            session.execute(
                select(DividendYieldDaily.session_date, DividendYieldDaily.q)
                .where(
                    DividendYieldDaily.symbol == sym.upper(),
                    DividendYieldDaily.source == source,
                    DividendYieldDaily.session_date >= lo,
                    DividendYieldDaily.session_date <= hi,
                )
                .order_by(DividendYieldDaily.session_date)
            )
        )
        sessions_traded = traded.get(sym, set())
        if not rows:
            defaulted += 1
            continue
        covered = {d for d, _ in rows}
        uncovered = sorted(sessions_traded - covered)
        if uncovered:
            defaulted += 1
        last_date, last_q = rows[-1]
        out[sym] = {
            "value": float(last_q),
            "source": source,
            "as_of": last_date.isoformat(),
            "first_session": rows[0][0].isoformat(),
            "last_session": last_date.isoformat(),
            "sessions_covered": len(rows),
            "sessions_traded": len(sessions_traded),
            "sessions_traded_uncovered": [d.isoformat() for d in uncovered],
            "span_end": hi.isoformat(),
        }
    return out, defaulted


def _folds(
    trades: Sequence[OptionTrade],
    window: OptionsWindow,
    *,
    n_folds: int,
    start_equity: float,
    r_dollars: float,
) -> list[dict[str, Any]]:
    """Rolling folds over the PRE-SEALED span, built exactly as the equity ladder
    builds them (``promotion.py``'s gate 1) so the two are the same claim."""
    span_days = (window.pre_sealed_end - window.start).days
    rows: list[dict[str, Any]] = []
    for k in range(n_folds):
        lo = window.start + timedelta(days=span_days * k // n_folds)
        hi = window.start + timedelta(days=span_days * (k + 1) // n_folds)
        ft = [t for t in trades if lo <= t.entry_date < hi]
        pm = (
            options_portfolio_metrics(
                ft,
                start_equity=start_equity,
                r_dollars=r_dollars,
                span_start=lo,
                span_end=hi,
            )
            if ft
            else None
        )
        rows.append(
            {
                "fold": k + 1,
                "start": lo.isoformat(),
                "end": hi.isoformat(),
                "n_trades": pm.n_trades if pm else 0,
                "expectancy_r": pm.avg_trade_r if pm else 0.0,
                "sharpe": pm.sharpe if pm else 0.0,
            }
        )
    return rows


def _market_sharpe(proxy: PriceSeries, lo: date, hi: date) -> float:
    """Buy-and-hold Sharpe of the proxy over ``[lo, hi]`` — the gate-7 benchmark."""
    idx = [i for i, d in enumerate(proxy.dates) if lo <= d <= hi]
    if len(idx) < 3:
        return 0.0
    closes = np.asarray(proxy.close[idx[0] : idx[-1] + 1], dtype=np.float64)
    rets = np.diff(closes) / closes[:-1]
    if rets.size < 2:
        return 0.0
    total = float(closes[-1] / closes[0] - 1.0)
    days = (proxy.dates[idx[-1]] - proxy.dates[idx[0]]).days or 1
    years = days / 365.25
    cagr = (1 + total) ** (1 / years) - 1 if years > 0 and 1 + total > 0 else 0.0
    vol = float(np.std(rets, ddof=1) * math.sqrt(252))
    return round(cagr / vol, 3) if vol > 0 else 0.0


def _sharpe(
    trades: Sequence[OptionTrade], *, start_equity: float, r_dollars: float, lo: date, hi: date
) -> float:
    if not trades:
        return 0.0
    return options_portfolio_metrics(
        trades, start_equity=start_equity, r_dollars=r_dollars, span_start=lo, span_end=hi
    ).sharpe


def _limits_are_hashed(evaluation: OptionsEvaluationConfig) -> bool:
    """Is the arming limit set inside ``options_config_hash``?  Asked, not assumed.

    Today the limits live on the paper-side ``execution_limits`` row, which S11b
    forbids this module from importing, and ``OptionsEvaluationConfig`` carries no
    equivalent field — so the answer is ``False`` and gate 0.i fails.  Written as a
    field probe so it flips the day the fields are added, rather than as a constant
    somebody has to remember to change.
    """
    fields = set(type(evaluation).model_fields)
    return {"options_per_structure_max_loss", "options_total_open_max_loss"} <= fields


def assemble_options_evidence(
    session: Session,
    strategy: OptionsStrategy,
    *,
    dataset_snapshot: DataSnapshot,
    window: OptionsWindow,
    thresholds: OptionsGateThresholds | None = None,
    evaluation: OptionsEvaluationConfig | None = None,
    source: str = "massive",
    proxy_symbol: str = "SPY",
    sensitivity: OptionsSensitivitySummary | None = None,
    include_sealed: bool = False,
    include_mechanical: bool = True,
    cluster_seed: int = OPTIONS_CLUSTER_BOOTSTRAP_SEED,
    presealed_abandonments: int = 0,
    equity_diagnostic_ref: str = "",
    warmup: int = 50,
    limits_source: str = "D5 §9.2 / decisions #4 and #13 (paper-side execution_limits)",
) -> AssembledEvidence:
    """Measure everything the options ladder gates on, over one keyed snapshot.

    ``include_sealed`` is the switch that separates a rehearsal from a look: with
    it ``False`` the sealed outcome is ``None``, gate 9 fails honestly, and
    ``evaluate_options_promotion`` has nothing to seal.  A caller that wants to
    spend a look must say so.

    Read-only.  The session may be a plain reader; nothing here needs — or takes —
    write intent.
    """
    th = thresholds or OptionsGateThresholds()
    ev = evaluation or OptionsEvaluationConfig()
    symbols = [str(s).upper() for s in (dataset_snapshot.symbols_json or [])]
    notes: list[str] = []

    axes = strategy.sensitivity_axes()
    dte_targets = [int(v) for v in axes.get("dte_target", [35])]

    runs: list[UnderlyingRun] = []
    for sym in symbols:
        runs.append(
            run_underlying(
                session,
                strategy,
                sym,
                window=window,
                source=source,
                dte_targets=dte_targets,
                include_mechanical=include_mechanical,
                warmup=warmup,
            )
        )
    evaluable = [r for r in runs if r.dual is not None]
    for r in runs:
        if r.skipped_reason:
            notes.append(f"{r.symbol}: {r.skipped_reason}")

    proxy = PriceSeries.load(
        session, proxy_symbol, window.start, window.end, source=source, adjusted=True
    )

    if evaluable:
        dual = pool_dual([r.dual for r in evaluable if r.dual is not None])
        mech_reports = [r.mechanical for r in evaluable if r.mechanical is not None]
        mechanical = pool_dual(mech_reports) if mech_reports else None
    else:
        dual = _empty_dual(strategy.selection_cost_model)
        mechanical = None
        notes.append("no underlying produced an evaluable chain; every population statistic is 0")

    trades = list(dual.baseline.trades)
    stressed_trades = list(dual.stressed.trades)
    presealed = _split_presealed(trades, window)
    sealed_trades = _split_sealed(trades, window)

    boundary = is_oos_boundary(proxy) if len(proxy) >= 3 else None
    oos = [t for t in presealed if boundary is not None and t.entry_date > boundary]
    oos_keys = {(t.underlying_symbol, t.entry_date) for t in oos}
    # D5 §6.2c form (a): the SAME structures re-priced, matched by identity rather
    # than re-selected — a stressed population of a different size is form (b)
    # leaking into the gating path, and gate 4b checks the count for exactly that.
    oos_stressed = [t for t in stressed_trades if (t.underlying_symbol, t.entry_date) in oos_keys]

    # D5a §3: the width is a constant of the version, so the declared half of gate 0.5
    # takes no argument; the observed half is recovered from the trades by the gate.
    identity = strategy.structure_identity()
    r_scale = identity.r_scale_usd or 1.0

    availability = _availability(
        session,
        strategy,
        runs=runs,
        evaluable=evaluable,
        dual=dual,
        window=window,
        th=th,
        ev=ev,
        source=source,
        symbols=symbols,
        dte_targets=dte_targets,
        identity=identity,
        limits_source=limits_source,
        axes=axes,
    )

    clustered_d4 = clustered_bootstrap_ci(
        oos, key_fn=cluster_key_underlying_cycle, unit=CLUSTER_UNIT_D4, seed=cluster_seed
    )
    clustered_f11 = clustered_bootstrap_ci(
        oos, key_fn=cluster_key_cycle_only, unit=CLUSTER_UNIT_F11, seed=cluster_seed
    )

    data_quality = _data_quality(
        session,
        runs=runs,
        dual=dual,
        window=window,
        source=source,
        symbols=symbols,
        clustered_d4=clustered_d4,
        clustered_f11=clustered_f11,
        proxy_symbol=proxy_symbol,
    )

    census = joint_regime_census(presealed, proxy) if len(proxy) else _empty_census(len(presealed))
    partition = (
        regime_partition_crosstab(proxy)
        if len(proxy)
        else RegimePartitionDisclosure(
            signal_label_source="signalforge.research.regime:regime_from_proxy",
            census_label_source="signalforge.backtest.regime:label_regimes",
            crosstab={},
            bear_sessions_signal=0,
            bear_sessions_called_range=0,
            sessions=0,
        )
    )

    benchmark = BenchmarkPair(
        strategy_sharpe_baseline=_sharpe(
            presealed,
            start_equity=th.account_equity_basis,
            r_dollars=r_scale,
            lo=window.start,
            hi=window.pre_sealed_end,
        ),
        strategy_sharpe_stressed=_sharpe(
            _split_presealed(stressed_trades, window),
            start_equity=th.account_equity_basis,
            r_dollars=r_scale,
            lo=window.start,
            hi=window.pre_sealed_end,
        ),
        market_sharpe=_market_sharpe(proxy, window.start, window.pre_sealed_end),
        mechanical_sharpe_baseline=(
            _sharpe(
                _split_presealed(mechanical.baseline.trades, window),
                start_equity=th.account_equity_basis,
                r_dollars=r_scale,
                lo=window.start,
                hi=window.pre_sealed_end,
            )
            if mechanical is not None
            else None
        ),
        mechanical_sharpe_stressed=(
            _sharpe(
                _split_presealed(mechanical.stressed.trades, window),
                start_equity=th.account_equity_basis,
                r_dollars=r_scale,
                lo=window.start,
                hi=window.pre_sealed_end,
            )
            if mechanical is not None
            else None
        ),
        mechanical_n_trades=(
            len(_split_presealed(mechanical.baseline.trades, window))
            if mechanical is not None
            else 0
        ),
        mechanical_spec=strategy.mechanical_spec(),
        eff_start=window.start,
        eff_end=window.pre_sealed_end,
        proxy_symbol=proxy_symbol,
    )

    oos_metrics = (
        options_portfolio_metrics(
            oos,
            start_equity=th.account_equity_basis,
            r_dollars=r_scale,
            span_start=window.start,
            span_end=window.pre_sealed_end,
        )
        if oos
        else None
    )
    oos_ci = _iid_ci([t.pnl_r for t in oos])
    stressed_ci = _iid_ci([t.pnl_r for t in oos_stressed])

    sealed = None
    if include_sealed and sealed_trades:
        sealed = SealedOptionsOutcome(
            window_start=window.sealed_start,
            window_end=window.end,
            n_trades=len(sealed_trades),
            expectancy_r=statistics.fmean(t.pnl_r for t in sealed_trades),
            spread_multiplier=1.0,
            r_basis=RBasis.INCL,
            metrics={
                "sharpe": _sharpe(
                    sealed_trades,
                    start_equity=th.account_equity_basis,
                    r_dollars=r_scale,
                    lo=window.sealed_start,
                    hi=window.end,
                ),
                "n_clusters": clustered_bootstrap_ci(sealed_trades, seed=cluster_seed).n_clusters,
            },
            benchmark={"market_sharpe": _market_sharpe(proxy, window.sealed_start, window.end)},
            data_provenance={
                "sources": [source],
                "simulated": False,
                "dataset_snapshot": dataset_snapshot.key,
            },
        )
    elif include_sealed:
        notes.append("sealed window requested but no structure entered inside it")

    evidence = OptionsEvidence(
        availability=availability,
        identity=identity,
        dual=dual,
        census=census,
        partition=partition,
        benchmark=benchmark,
        data_quality=data_quality,
        folds=_folds(
            presealed,
            window,
            n_folds=th.min_walkforward_folds,
            start_equity=th.account_equity_basis,
            r_dollars=r_scale,
        ),
        sensitivity=sensitivity,
        sealed=sealed,
        n_oos_trades=len(oos),
        oos_expectancy_r=oos_metrics.avg_trade_r if oos_metrics else 0.0,
        oos_ci_low_r=oos_ci,
        stressed_oos=StressedOos(
            n_trades=len(oos_stressed),
            expectancy_r=(statistics.fmean(t.pnl_r for t in oos_stressed) if oos_stressed else 0.0),
            ci_low_r=stressed_ci,
        ),
        presealed_abandonments=presealed_abandonments,
        equity_diagnostic_ref=equity_diagnostic_ref,
        extra_provenance={
            "assembled_from": "signalforge.research.options_evidence",
            "underlying_close_basis": "unadjusted" if not UNDERLYING_ADJUSTED else "adjusted",
            "clustering_unit_d4": CLUSTER_UNIT_D4,
            "clustering_unit_f11": CLUSTER_UNIT_F11,
            "clustered_bootstrap_seed": cluster_seed,
            "f11_clustered_ci_low": round(clustered_f11.low, 6),
            "f11_noship_if_ci_low_below": th.min_bootstrap_ci_low_r,
            "f11_breached": clustered_f11.low <= th.min_bootstrap_ci_low_r,
            "sealed_window_evaluated": include_sealed,
        },
    )
    return AssembledEvidence(
        evidence=evidence,
        per_underlying=tuple(runs),
        coverage=latest_options_coverage_summary(
            session, window_start=window.start, window_end=window.end
        ),
        clustered_d4=clustered_d4,
        clustered_f11=clustered_f11,
        boundary=boundary,
        notes=tuple(notes),
    )


def _iid_ci(values: Sequence[float]) -> float:
    from signalforge.backtest.montecarlo import bootstrap_ci

    if not values:
        return 0.0
    return float(bootstrap_ci(list(values))["expectancy_r"]["low"])


def _empty_census(n: int) -> JointRegimeCensus:
    return JointRegimeCensus(
        regime_label_source="signalforge.backtest.regime:label_regimes",
        trend_buckets={"bull": 0, "bear": 0, "range": 0},
        joint_cells={"bull_highvol": 0, "bull_lowvol": 0, "bear_highvol": 0, "bear_lowvol": 0},
        vol_marginals={"highvol": 0, "lowvol": 0},
        range_bound_count=0,
        range_bound_vol_labelled=False,
        warmup=0,
        no_proxy_bar=n,
        unlabelled=0,
        n_trades=n,
    )


def _empty_dual(cost_model: OptionCostModel) -> DualSpreadReport:
    """A zero population, shaped so every gate reads it as a failure, not a skip."""
    base = OptionsBacktestOutcome(
        underlying_symbol="POOLED(0)", r_basis=RBasis.INCL, spread_multiplier=1.0
    )
    stress = OptionsBacktestOutcome(
        underlying_symbol="POOLED(0)", r_basis=RBasis.INCL, spread_multiplier=2.0
    )
    _ = cost_model
    return DualSpreadReport(
        cells=_cells_for(base) | _cells_for(stress), baseline=base, stressed=stress
    )


def _availability(
    session: Session,
    strategy: OptionsStrategy,
    *,
    runs: Sequence[UnderlyingRun],
    evaluable: Sequence[UnderlyingRun],
    dual: DualSpreadReport,
    window: OptionsWindow,
    th: OptionsGateThresholds,
    ev: OptionsEvaluationConfig,
    source: str,
    symbols: Sequence[str],
    dte_targets: Sequence[int],
    identity: StructureIdentity,
    limits_source: str,
    axes: Mapping[str, Sequence[float | int]],
) -> OptionsDataAvailability:
    trades = list(dual.baseline.trades)
    counters = dual.baseline.counters
    mix, unnamed = _iv_source_mix(trades)

    matrix: dict[str, dict[str, list[float]]] = {}
    for r in evaluable:
        for dte, cell in r.bracket_matrix.items():
            for side, frac in cell.items():
                matrix.setdefault(dte, {}).setdefault(side, []).append(frac)
    bracket_matrix = {
        dte: {side: statistics.fmean(vals) for side, vals in sorted(sides.items())}
        for dte, sides in sorted(matrix.items())
    }
    cycles_eligible = sum(r.cycles_eligible for r in evaluable)
    cycles_bracketed = sum(r.cycles_bracketed for r in evaluable)

    per_underlying_marked = [r.marked_fraction for r in evaluable if r.marked_fraction > 0]
    per_structure_marked = [
        1.0 - (t.unmarked_sessions / t.bars_held) for t in trades if t.bars_held > 0
    ]

    q_map, q_defaulted = _q_by_underlying(session, symbols, window=window, trades=trades)

    cost_by_multiplier: dict[str, float] = {}
    for outcome in (dual.baseline, dual.stressed):
        if outcome.trades:
            cost_by_multiplier[f"{outcome.spread_multiplier:g}"] = round(
                statistics.fmean(t.entry_costs + t.exit_costs for t in outcome.trades), 4
            )

    batches = int(session.scalar(select(func.count(distinct(EntitlementCheck.batch_id)))) or 0)

    r_values = [t.r_incl for t in trades]
    return OptionsDataAvailability(
        horizon=strategy.horizon,
        min_dte_at_entry_declared=min((t.dte_at_entry for t in trades), default=min(dte_targets)),
        underlyings=tuple(r.coverage for r in evaluable),
        required_source=source,
        cycles_eligible=cycles_eligible,
        cycles_bracketed=cycles_bracketed,
        bracket_fraction_matrix=bracket_matrix,
        bracket_gated_cells=tuple(
            (int(d), side)
            for d in sorted({int(x) for x in dte_targets})
            for side in ("put", "call")
        ),
        eligible_cycle_definition=(
            "(i) the underlying passes 0.b over that cycle, and (ii) the cycle's expiry falls "
            "inside the evaluation window. Nothing else — no regime filter, no DTE window, no "
            "delta target and no width (D4 §2.3)."
        ),
        bracket_failures_by_underlying={
            r.symbol: max(0, r.cycles_eligible - r.cycles_bracketed) for r in evaluable
        },
        bracket_failures_by_side=_bracket_failures_by_side(evaluable),
        bar_continuity_min_observed=min(per_underlying_marked, default=0.0),
        bar_continuity_median=(
            statistics.median(per_structure_marked) if per_structure_marked else 0.0
        ),
        non_entry_count=(counters.non_entry_missing_leg_bar + counters.non_entry_no_signal_window),
        non_entry_reasons={
            "missing_leg_bar": counters.non_entry_missing_leg_bar,
            "no_signal_window": counters.non_entry_no_signal_window,
            "structure_refusals": counters.structure_refusals,
            "zero_spread": counters.zero_spread_refusals,
            "non_positive_r": counters.non_positive_r_refusals,
        },
        exit_deferral_histogram=_histogram(counters.exit_deferred_sessions),
        gap_sessions=sum(r.coverage.gap_sessions for r in runs),
        iv_source_mix=mix,
        iv_source_unnamed_count=unnamed,
        surface_n_actual_min=min(
            (r.surface_n_min for r in evaluable if r.surface_n_min), default=0
        ),
        fill_model=FILL_MODEL,
        cost_model=strategy.selection_cost_model,
        cost_model_frozen_at=preregistration_digest(),
        cost_per_structure_roundtrip_usd=cost_by_multiplier,
        entitlement_batches_checked=batches,
        q_by_underlying=q_map,
        q_defaulted_count=q_defaulted
        + sum(1 for t in trades if not t.q_source or t.q_source == "unsourced"),
        deliverable_refusal_count=counters.shares_per_contract_refusals,
        deliverable_refusals=(
            ({"count": counters.shares_per_contract_refusals, "scope": "pooled"},)
            if counters.shares_per_contract_refusals
            else ()
        ),
        r_max_observed_usd=max(r_values, default=0.0),
        r_max_by_width={f"{identity.width_declared:g}": max(r_values, default=0.0)},
        concurrent_open_r_max_usd=_concurrent_open_r_max(trades),
        structures_breaching_per_structure_cap=sum(
            1 for r in r_values if r > th.options_per_structure_max_loss
        ),
        # D5a §3: widths are declared in DOLLARS of strike distance per contract; the
        # grid no longer carries a width axis, so the OAT table (or the identity's
        # single width) is what gate 0.i discloses.
        width_grid_declared=tuple(
            float(v)
            for v in (
                axes.get("width_usd")
                or strategy.oat_parameters().get("width_usd")
                or (identity.width_declared,)
            )
        ),
        limits_source=limits_source,
        limits_in_options_config_hash=_limits_are_hashed(ev),
    )


def _bracket_failures_by_side(runs: Sequence[UnderlyingRun]) -> dict[str, int]:
    out = {"put": 0, "call": 0}
    for r in runs:
        for cell in r.bracket_matrix.values():
            for side, frac in cell.items():
                if frac < 1.0:
                    out[side] = out.get(side, 0) + 1
    return out


def _histogram(values: Sequence[int]) -> dict[str, int]:
    out: dict[str, int] = {}
    for v in values:
        out[str(v)] = out.get(str(v), 0) + 1
    return dict(sorted(out.items(), key=lambda kv: int(kv[0])))


def _data_quality(
    session: Session,
    *,
    runs: Sequence[UnderlyingRun],
    dual: DualSpreadReport,
    window: OptionsWindow,
    source: str,
    symbols: Sequence[str],
    clustered_d4: ClusteredBootstrap,
    clustered_f11: ClusteredBootstrap,
    proxy_symbol: str,
) -> OptionsDataQuality:
    from signalforge.data.validate import validate_daily
    from signalforge.research.promotion import _leakage_self_check

    trades = list(dual.baseline.trades)
    counters = dual.baseline.counters

    # persist=False: an evidence assembly is a measurement, not an ingestion run,
    # and a read session must not grow a DataValidationReport row.
    validation = validate_daily(session, list(symbols), source=source, persist=False)
    leak = _leakage_self_check(session, proxy_symbol, window.start, window.end, source)
    chain_leak = next((r.chain_leakage_error for r in runs if r.chain_leakage_error), None)

    exclusions: dict[str, int] = {}
    for sym in symbols:
        n = len(splits_between(session, sym, window.start, window.end))
        if n:
            exclusions[sym] = n

    pinned = [t for t in trades if t.pin_risk_flag]
    unpinned = [t for t in trades if not t.pin_risk_flag]
    pinned_r = sorted(t.pnl_r for t in pinned)
    thin = [
        t for t in trades if t.bars_held > 0 and (1.0 - t.unmarked_sessions / t.bars_held) < 0.60
    ]
    return OptionsDataQuality(
        data_validation_passed=validation.passed,
        data_validation_findings=tuple(validation.findings),
        leakage_error=leak,
        chain_leakage_error=chain_leak,
        corporate_action_exclusions=exclusions,
        synthetic_mark_fraction_trade_weighted=(
            statistics.fmean(t.unmarked_sessions / t.bars_held for t in trades if t.bars_held > 0)
            if any(t.bars_held > 0 for t in trades)
            else 0.0
        ),
        pinned_fraction=(len(pinned) / len(trades)) if trades else 0.0,
        expectancy_excluding_pinned_r=(
            statistics.fmean(t.pnl_r for t in unpinned) if unpinned else 0.0
        ),
        pinned_r_distribution={
            "min": pinned_r[0] if pinned_r else 0.0,
            "median": statistics.median(pinned_r) if pinned_r else 0.0,
            "max": pinned_r[-1] if pinned_r else 0.0,
            "n": float(len(pinned_r)),
        },
        clustered_bootstrap_ci={
            **clustered_d4.to_mapping(),
            **clustered_f11.to_mapping(prefix="f11_"),
        },
        clustering_unit=CLUSTER_UNIT_D4,
        assignment_approximation_disclosed=True,
        assignment_risk_count=counters.assignment_risk,
        forced_intrinsic_mark_fraction=(
            counters.force_close_unpriceable_exclusions / len(trades) if trades else 0.0
        ),
        thin_continuity_fraction=(len(thin) / len(trades)) if trades else 0.0,
    )


# --------------------------------------------------------------------------- #
# the read-only ladder — what --dry-run prints
# --------------------------------------------------------------------------- #
def options_ladder_preview(
    evidence: OptionsEvidence,
    *,
    window: OptionsWindow,
    thresholds: OptionsGateThresholds | None = None,
    health_monitor_enabled: bool = False,
    min_paper_trades: int = 20,
    downgrade_z: float = -1.0,
    disable_z: float = -2.0,
) -> list[OptionsGate]:
    """Run the ladder's PREDICATES with no database, no row and no sealed look.

    Same gates, same order, same fail-fast gate 0 as
    ``evaluate_options_promotion`` — but nothing is persisted and gate 9 is
    evaluated against an empty ledger, so a preview can never create a
    ``StrategySealedTest``.  That is what makes ``--dry-run`` honest: it shows the
    ladder a ``--confirm`` run would see *except* for the look accounting, which
    only the real evaluation may touch.
    """
    th = thresholds or OptionsGateThresholds()
    av = evidence.availability
    gate_zero = [
        gate_0a_window(window, av, th),
        gate_0b_underlyings(av),
        gate_0c_bracketing(av, th),
        gate_0d_continuity(av, th),
        gate_0e_iv_provenance(av, th),
        gate_0f_fill_provenance(av),
        gate_0g_dividend_yield(av),
        gate_0h_deliverable(av),
        gate_0i_risk_limits(av, th),
        gate_0_5_structure(evidence.identity, evidence.dual.baseline.trades),
    ]
    if not all(g.passed for g in gate_zero):
        return gate_zero

    gates = list(gate_zero)
    gates.append(gate_1_walkforward(evidence.folds, th))
    gates.append(gate_2_oos_trades(evidence.n_oos_trades, th))
    gates.append(gate_3_expectancy(evidence.oos_expectancy_r, "incl", th))
    gates.append(gate_4_bootstrap(evidence.oos_ci_low_r, "incl", th))
    gates.append(
        gate_4b_dual_spread(
            evidence.dual,
            evidence.benchmark,
            th,
            baseline_oos=StressedOos(
                n_trades=evidence.n_oos_trades,
                expectancy_r=evidence.oos_expectancy_r,
                ci_low_r=evidence.oos_ci_low_r,
            ),
            stressed_oos=evidence.stressed_oos or StressedOos(0, 0.0, 0.0),
            equity_diagnostic_ref=evidence.equity_diagnostic_ref,
        )
    )
    gates.append(gate_5_sensitivity(evidence.sensitivity, th))
    gates.append(gate_6_regime(evidence.census, th, evidence.partition))
    gates.append(gate_6b_joint(evidence.census, th))
    gates.append(gate_7_benchmark(evidence.benchmark, th))
    gates.append(gate_7b_mechanical(evidence.benchmark))
    gates.append(gate_8_data_quality(evidence.data_quality, evidence.dual, th))
    gates.append(
        gate_9_sealed(
            evidence.sealed,
            {"k_prior": 0, "this_look": 0, "rows": [], "preview": True},
            th,
            sealed_test_id=None,
            reused=False,
            options_program_looks=0,
            seal_note="DRY RUN — no sealed test was read, created or consumed",
        )
    )
    gates.append(
        gate_10_probation(
            enabled=health_monitor_enabled,
            min_paper_trades=min_paper_trades,
            downgrade_z=downgrade_z,
            disable_z=disable_z,
        )
    )
    return gates


__all__ = [
    "CLUSTER_UNIT_D4",
    "CLUSTER_UNIT_F11",
    "D5_PREREGISTRATION_PATH",
    "OPTIONS_CLUSTER_BOOTSTRAP_SEED",
    "AssembledEvidence",
    "ClusteredBootstrap",
    "CoveragePreflight",
    "OptionsEvidenceError",
    "OptionsStrategy",
    "UnderlyingRun",
    "assemble_options_evidence",
    "coverage_preflight",
    "cluster_key_cycle_only",
    "cluster_key_underlying_cycle",
    "clustered_bootstrap_ci",
    "expiry_cycle_of",
    "latest_options_coverage_summary",
    "load_option_chain_series",
    "options_ladder_preview",
    "pool_counters",
    "pool_dual",
    "preregistration_digest",
    "preregistration_path",
    "run_underlying",
]
