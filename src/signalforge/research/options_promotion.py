"""``evaluate_options_promotion`` — the options gate ladder, wired (D4).

**A separate evaluate path, and that is the whole design.**  ``evaluate_promotion``
is not touched, not parameterised, and not branched on asset class.  The
guarantee is mechanical rather than promised: ``tests/research/
test_options_promotion.py::test_equity_gates_json_is_byte_identical`` runs the
equity ladder over the existing fixtures and compares the persisted
``gates_json`` byte for byte against the same run with this module imported.

What this module adds on top of ``options_gates``' pure predicates:

* **Fail-fast gate 0.**  Sub-gates 0.a-0.i run first and, on the first failure,
  the ladder returns through ``_finalize_options`` with nothing else evaluated —
  copying ``promotion.py``'s own INTRADAY precedent.  A fabricated pass on absent
  data is the failure mode gate 0 exists to prevent, so an options evaluation
  that cannot answer 0.c never reaches gate 3's expectancy at all.
* **Sealed-look accounting from k = 0.**  ``count_sealed_looks`` keys on
  ``Strategy.name``; an ``options_*`` family has no prior rows, so ``k_prior``
  is 0 by construction with no new code and the join makes conflation with the
  equity ledger impossible in either direction.  What IS new here is D4 §8.4's
  ``options_program_looks`` (the sum over the pre-registered family list, so a
  second structure's multiplicity cost is visible at the moment it is paid) and
  D5 §10's ``k_effective`` (sealed looks **plus** recorded pre-sealed
  abandonments, which ``count_sealed_looks`` cannot see).
* **The sealed path is pinned to baseline cost, structurally.**
  :class:`~signalforge.research.options_gates.SealedOptionsOutcome` raises in its
  own constructor at any ``spread_multiplier != 1.0``, and this module refuses to
  seal from a stressed outcome.  D4 §4.3a's hazard is that one line of plumbing
  would let a 2x run CREATE a ``StrategySealedTest`` and consume a look
  permanently; the assertion is therefore on the *intent*, not the aftermath.
* **An explicit snapshot key is mandatory.**  D4 §2.9b: the unkeyed symbol-match
  fallback is symbol-only, so two runs at different gate fractions would collide
  on it.  ``evaluate_options_promotion`` takes a resolved ``DataSnapshot`` and
  refuses one carrying no ``options_scope_json``.

Nothing here runs an evaluation on real data.  Every input is measured by the
caller and handed in; the tests use synthetic chains only (R1: pre-registration
precedes any outcome).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from signalforge import audit
from signalforge.config.research import ResearchConfig
from signalforge.db.models import (
    AuditLog,
    DataSnapshot,
    Strategy,
    StrategyPromotionEvaluation,
    StrategySealedTest,
    StrategyVersion,
)
from signalforge.db.types import utcnow
from signalforge.domain import StrategyStatus
from signalforge.observability import get_logger
from signalforge.research.options_backtest_runner import (
    DualSpreadReport,
    JointRegimeCensus,
    RegimePartitionDisclosure,
)
from signalforge.research.options_gates import (
    OPTIONS_LADDER_SHAPE,
    BenchmarkPair,
    OptionsDataAvailability,
    OptionsDataQuality,
    OptionsGate,
    OptionsGateThresholds,
    OptionsSensitivitySummary,
    OptionsWindow,
    SealedAtNonBaselineCost,
    SealedOptionsOutcome,
    StressedOos,
    StructureIdentity,
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
from signalforge.research.persistence import spec_json_hash, upsert_strategy_version
from signalforge.research.promotion import (
    VERDICT_APPROVED,
    VERDICT_NO_TRADE,
    count_sealed_looks,
    format_sealed_look_line,
    sealed_look_ledger,
)
from signalforge.research.registry import StrategySpec

_log = get_logger("research.options_promotion")

#: D4 §8.4 / D5 §10.  The COMPLETE enumerated list of ``Strategy.name`` values
#: the options program will ever use, pre-registered before the first sealed
#: look.  ``count_sealed_looks`` restarts at 0 for each name, so without this
#: list the program's *total* multiplicity would be invisible while every
#: individual number stayed technically correct.  **A family name that appears
#: later and is not on this list is, by definition, an undisclosed look.**
OPTIONS_FAMILY_NAMES: tuple[str, ...] = ("options_short_vertical.medium_swing",)

#: D5 §10's budget (1 variant, hard cap 2) is TIGHTER than D4 §8.4's 3 and is the
#: binding pre-registration.  Both are recorded so the discrepancy is visible.
OPTIONS_LOOK_BUDGET = 2
OPTIONS_LOOK_BUDGET_D4 = 3


class OptionsSnapshotNotScoped(ValueError):
    """An options evaluation was handed a snapshot with no options scope.

    D4 §2.9b: the unkeyed symbol-match fallback hashes the SYMBOL SET and
    nothing else, so an options run over the 24 approved equity symbols would
    otherwise bind to the live equity snapshot and collapse the options
    sealed-look ledger onto the equity one.
    """


@dataclass(frozen=True, slots=True)
class OptionsPromotionResult:
    strategy_key: str
    version: str
    strategy_version_id: int
    evaluation_id: int
    evaluated_at: str
    config_hash: str
    options_config_hash: str
    full_config_hash: str
    git_sha: str
    universe: list[str]
    window: OptionsWindow
    dataset_snapshot_id: int
    dataset_snapshot_key: str
    data_provenance: dict[str, Any]
    gates: list[OptionsGate]
    passed: bool
    verdict: str
    sealed_test_id: int | None
    sealed_look_prior: int = 0
    sealed_look_index: int = 0
    sealed_test_reused: bool = False
    options_program_looks: int = 0
    presealed_abandonments: int = 0

    @property
    def k_effective(self) -> int:
        """D5 §10: sealed looks **plus** recorded pre-sealed abandonments.

        ``count_sealed_looks`` cannot see a pre-sealed abandonment, and this
        program's stopping rules are full of them — a v0.1.0 stopped at F8 leaves
        the counter at 0 and a v0.2.0 would print ``k_prior = 0``, understating
        multiplicity by a full pre-sealed evaluation.
        """
        return self.sealed_look_prior + self.presealed_abandonments

    @property
    def ladder_shape(self) -> tuple[tuple[int, str], ...]:
        return tuple((g.number, g.label) for g in self.gates)

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy_key": self.strategy_key,
            "version": self.version,
            "strategy_version_id": self.strategy_version_id,
            "evaluation_id": self.evaluation_id,
            "evaluated_at": self.evaluated_at,
            "config_hash": self.config_hash,
            "options_config_hash": self.options_config_hash,
            "full_config_hash": self.full_config_hash,
            "git_sha": self.git_sha,
            "universe": list(self.universe),
            "window": self.window.to_dict(),
            "dataset_snapshot": {
                "id": self.dataset_snapshot_id,
                "key": self.dataset_snapshot_key,
            },
            "data_provenance": self.data_provenance,
            "gates": [g.to_dict() for g in self.gates],
            "passed": self.passed,
            "verdict": self.verdict,
            "sealed_test_id": self.sealed_test_id,
            "sealed_look_prior": self.sealed_look_prior,
            "sealed_look_index": self.sealed_look_index,
            "sealed_test_reused": self.sealed_test_reused,
            "options_program_looks": self.options_program_looks,
            "presealed_abandonments": self.presealed_abandonments,
            "k_effective": self.k_effective,
            "look_budget": OPTIONS_LOOK_BUDGET,
            "options_family_names": list(OPTIONS_FAMILY_NAMES),
        }


@dataclass(frozen=True, slots=True)
class OptionsEvidence:
    """Everything the ladder measures, gathered by the caller.

    Kept as one object rather than fifteen keyword arguments so that adding a
    gate is an additive field, never a signature change that silently defaults.
    """

    availability: OptionsDataAvailability
    identity: StructureIdentity
    dual: DualSpreadReport
    census: JointRegimeCensus
    partition: RegimePartitionDisclosure
    benchmark: BenchmarkPair
    data_quality: OptionsDataQuality
    folds: Sequence[Mapping[str, Any]] = ()
    sensitivity: OptionsSensitivitySummary | None = None
    sealed: SealedOptionsOutcome | None = None
    n_oos_trades: int = 0
    oos_expectancy_r: float = 0.0
    oos_ci_low_r: float = 0.0
    # The same OOS triple re-priced at 2x with SELECTION FROZEN (D5 §6.2c form
    # (a)). ``None`` means the stressed leg was not run, which gate 4b treats as
    # a failure rather than a skip.
    stressed_oos: StressedOos | None = None
    presealed_abandonments: int = 0
    equity_diagnostic_ref: str = ""
    extra_provenance: Mapping[str, Any] = field(default_factory=dict)


# --------------------------------------------------------------------------- #
# sealed test — read before compute, baseline cost only
# --------------------------------------------------------------------------- #
def _get_or_create_options_sealed_test(
    session: Session,
    version: StrategyVersion,
    sealed: SealedOptionsOutcome,
    *,
    symbols: list[str],
    dataset_snapshot_id: int,
    th: OptionsGateThresholds,
) -> tuple[StrategySealedTest, bool]:
    """``(row, reused)``.  ``reused=True`` means an existing LOCKED row came back.

    Keyed on ``(strategy_version_id, dataset_snapshot_id)`` exactly as the equity
    sealed test is, so the options family inherits the same read-before-recompute
    protection and the same unique constraint — and so ``count_sealed_looks`` and
    ``sealed_look_ledger`` work on it with no new code at all.

    The outcome is **computed by the caller over the sealed window at the
    baseline cost model** and handed in; this function never runs a backtest, so
    there is no path by which a stressed cost model could reach a sealed row.
    """
    if sealed.spread_multiplier != 1.0:  # pragma: no cover - the ctor already raised
        raise SealedAtNonBaselineCost("refusing to seal at a non-baseline cost model")
    existing = session.scalar(
        select(StrategySealedTest).where(
            StrategySealedTest.strategy_version_id == version.id,
            StrategySealedTest.dataset_snapshot_id == dataset_snapshot_id,
        )
    )
    if existing is not None:
        return existing, True  # locked — never recomputed, never overwritten

    passed = bool(
        sealed.n_trades >= th.sealed_min_trades
        and sealed.expectancy_r >= th.sealed_min_expectancy_r
    )
    row = StrategySealedTest(
        strategy_version_id=version.id,
        dataset_snapshot_id=dataset_snapshot_id,
        window_start=sealed.window_start,
        window_end=sealed.window_end,
        universe_json=list(symbols),
        data_provenance_json=dict(sealed.data_provenance),
        metrics_json={
            "n_trades": sealed.n_trades,
            "expectancy_r": round(sealed.expectancy_r, 4),
            "r_basis": sealed.r_basis.value,
            "series_basis": "unclamped",
            "spread_multiplier": sealed.spread_multiplier,
            **dict(sealed.metrics),
        },
        benchmark_metrics_json=dict(sealed.benchmark),
        passed=passed,
        detail=(
            f"{sealed.n_trades} structures, net expectancy {sealed.expectancy_r:+.4f}R on the "
            f"{sealed.r_basis.value} basis at BASELINE cost (need >= "
            f"{th.sealed_min_expectancy_r:+.4f}R on >= {th.sealed_min_trades})"
        ),
        evaluated_at=utcnow(),
    )
    try:
        with session.begin_nested():
            session.add(row)
            session.flush()
    except IntegrityError:
        winner = session.scalar(
            select(StrategySealedTest).where(
                StrategySealedTest.strategy_version_id == version.id,
                StrategySealedTest.dataset_snapshot_id == dataset_snapshot_id,
            )
        )
        if winner is not None:
            return winner, True
        raise
    _log.warning(
        "options_promotion.sealed_test_sealed",
        strategy=version.strategy_id,
        n_trades=sealed.n_trades,
        passed=passed,
    )
    return row, False


def options_program_looks(session: Session, names: Sequence[str] = OPTIONS_FAMILY_NAMES) -> int:
    """The arithmetic SUM of ``count_sealed_looks`` over the pre-registered list.

    Gate 0.5 makes each structure type its own version; if each also gets its own
    ``Strategy.name``, ``count_sealed_looks`` restarts at 0 for each and the
    program's total multiplicity becomes invisible while every individual number
    stays correct.  This is the arithmetic that closes that leak (D4 §8.4) — no
    new mechanism, just a sum nobody was taking.
    """
    return sum(count_sealed_looks(session, n) for n in names)


# --------------------------------------------------------------------------- #
# the ladder
# --------------------------------------------------------------------------- #
def evaluate_options_promotion(
    session: Session,
    spec: StrategySpec,
    *,
    symbols: list[str],
    window: OptionsWindow,
    dataset_snapshot: DataSnapshot,
    evidence: OptionsEvidence,
    thresholds: OptionsGateThresholds | None = None,
    config: ResearchConfig | None = None,
    options_config_hash: str = "",
    promote_on_pass: bool = False,
) -> OptionsPromotionResult:
    """Run the options ladder for one strategy version and record the result.

    ``evaluate_promotion`` is untouched by this call.  The only shared mutable
    surface is the database, and the only rows written are this evaluation and
    at most one sealed test for ``(version, snapshot)``.

    **``promote_on_pass`` defaults to FALSE, and that is a deliberate deviation
    from D4 §9 / D5 §9.1's "a gate-ladder pass writes PAPER_APPROVED".**  The
    reason is a live-path coupling neither document names: ``Strategy.status ==
    PAPER_APPROVED`` is what ``approved_scope_scan.approved_scan_groups`` selects
    on, filtered by **horizon alone** — there is no asset-class condition
    anywhere in it — so a PAPER_APPROVED ``options_*.medium_swing`` row becomes a
    candidate for an EQUITY scan group over the options snapshot's symbol set.
    Today it is saved only by an accident: this module writes no ``sources`` into
    ``data_provenance_json``, so ``approved_scopes`` yields an empty source set
    and the version is *skipped* with a reason.  An accident is not a control,
    and D5 §9.1 independently makes every options gate-10 input VOID until
    ``accept_candidate`` fails closed on instrument type — a guard D3/D6 own and
    that does not exist yet.

    So the status flip is available (``promote_on_pass=True``) and is not the
    default.  Flipping it is an operator decision that belongs with the D3/D6
    guards, not a side effect of wiring the ladder.
    """
    th = thresholds or OptionsGateThresholds()
    if config is None:
        from signalforge.settings_store import effective_research_config

        config = effective_research_config(session)
    if dataset_snapshot.options_scope_json is None:
        raise OptionsSnapshotNotScoped(
            f"dataset snapshot {dataset_snapshot.key!r} (id={dataset_snapshot.id}) carries no "
            "options_scope_json. An options evaluation MUST pass an explicit, options-scoped "
            "snapshot: the unkeyed fallback resolves by symbol set alone, so two runs at "
            "different gate fractions — or an options run and an equity run over the same "
            "universe — would collide on one snapshot and one sealed row (D4 §2.9b)."
        )

    version = upsert_strategy_version(session, spec)
    # Captured BEFORE gate 9 can seal anything, so "k prior looks" is unambiguous
    # even when this run locks a new sealed test (R2 disclosure).
    k_prior = count_sealed_looks(session, spec.name)
    program_looks = options_program_looks(session)
    av = evidence.availability

    data_provenance: dict[str, Any] = {
        "dataset_snapshot": {"id": dataset_snapshot.id, "key": dataset_snapshot.key},
        "options_scope_json": dataset_snapshot.options_scope_json,
        "options_config_hash": options_config_hash,
        "full_config_hash": config.full_config_hash,
        "config_hash": config.config_hash,
        "promotion_thresholds_verbatim": th.to_dict(),
        "fill_model": av.fill_model,
        "r_basis_of_gated_figures": "incl",
        "series_basis_of_gated_figures": "unclamped",
        "structure_type": evidence.identity.structure_type.value,
        "sealed_look_family": spec.name,
        "options_family_names": list(OPTIONS_FAMILY_NAMES),
        **dict(evidence.extra_provenance),
    }

    # ---- gate 0: FAIL-FAST.  0.a-0.i then 0.5, and the first failure returns.
    gate_zero: list[OptionsGate] = [
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
        return _finalize_options(
            session,
            spec,
            version,
            config,
            symbols=symbols,
            window=window,
            gates=gate_zero,
            sealed_test_id=None,
            data_provenance=data_provenance,
            dataset_snapshot=dataset_snapshot,
            options_config_hash=options_config_hash,
            sealed_look_prior=k_prior,
            options_program_looks_count=program_looks,
            presealed_abandonments=evidence.presealed_abandonments,
            promote_on_pass=promote_on_pass,
        )

    gates: list[OptionsGate] = list(gate_zero)

    # ---- gates 1-4 on the pre-sealed span, R_incl basis, UNCLAMPED series ----
    gates.append(gate_1_walkforward(evidence.folds, th))
    gates.append(gate_2_oos_trades(evidence.n_oos_trades, th))
    gates.append(gate_3_expectancy(evidence.oos_expectancy_r, "incl", th))
    gates.append(gate_4_bootstrap(evidence.oos_ci_low_r, "incl", th))

    # ---- gate 4b: the dual-spread pass, on the OPTIONS stream ---------------
    baseline_oos = StressedOos(
        n_trades=evidence.n_oos_trades,
        expectancy_r=evidence.oos_expectancy_r,
        ci_low_r=evidence.oos_ci_low_r,
    )
    stressed_oos = evidence.stressed_oos or StressedOos(0, 0.0, 0.0)
    gates.append(
        gate_4b_dual_spread(
            evidence.dual,
            evidence.benchmark,
            th,
            baseline_oos=baseline_oos,
            stressed_oos=stressed_oos,
            equity_diagnostic_ref=evidence.equity_diagnostic_ref,
        )
    )

    gates.append(gate_5_sensitivity(evidence.sensitivity, th))
    gates.append(gate_6_regime(evidence.census, th, evidence.partition))
    gates.append(gate_6b_joint(evidence.census, th))
    gates.append(gate_7_benchmark(evidence.benchmark, th))
    gates.append(gate_7b_mechanical(evidence.benchmark))
    gates.append(gate_8_data_quality(evidence.data_quality, evidence.dual, th))

    # ---- gate 9: sealed, baseline cost only, read-before-compute ------------
    sealed_row: StrategySealedTest | None = None
    sealed_reused = False
    if evidence.sealed is not None:
        sealed_row, sealed_reused = _get_or_create_options_sealed_test(
            session,
            version,
            evidence.sealed,
            symbols=symbols,
            dataset_snapshot_id=dataset_snapshot.id,
            th=th,
        )
    ledger = sealed_look_ledger(
        session,
        spec.name,
        k_prior=k_prior,
        this_run_sealed_test_id=sealed_row.id if sealed_row is not None else None,
        reused_this_run=sealed_reused,
    )
    seal_note = (
        f"LOCKED REPLAY of sealed test {sealed_row.id} — NOT created by this run"
        if sealed_reused and sealed_row is not None
        else "evaluated now, locked by this run"
    )
    gates.append(
        gate_9_sealed(
            evidence.sealed,
            ledger,
            th,
            sealed_test_id=sealed_row.id if sealed_row is not None else None,
            reused=sealed_reused,
            options_program_looks=options_program_looks(session),
            seal_note=seal_note,
        )
    )
    hm = config.health_monitor
    gates.append(
        gate_10_probation(
            enabled=hm.enabled,
            min_paper_trades=hm.min_paper_trades,
            downgrade_z=hm.downgrade_z,
            disable_z=hm.disable_z,
        )
    )

    data_provenance["sealed_look_line"] = format_sealed_look_line(ledger)
    return _finalize_options(
        session,
        spec,
        version,
        config,
        symbols=symbols,
        window=window,
        gates=gates,
        sealed_test_id=sealed_row.id if sealed_row is not None else None,
        data_provenance=data_provenance,
        dataset_snapshot=dataset_snapshot,
        options_config_hash=options_config_hash,
        sealed_look_prior=int(ledger["k_prior"]),
        sealed_look_index=int(ledger["this_look"]),
        sealed_test_reused=sealed_reused,
        options_program_looks_count=options_program_looks(session),
        presealed_abandonments=evidence.presealed_abandonments,
        promote_on_pass=promote_on_pass,
    )


def _finalize_options(
    session: Session,
    spec: StrategySpec,
    version: StrategyVersion,
    config: ResearchConfig,
    *,
    symbols: list[str],
    window: OptionsWindow,
    gates: list[OptionsGate],
    sealed_test_id: int | None,
    data_provenance: dict[str, Any],
    dataset_snapshot: DataSnapshot,
    options_config_hash: str,
    sealed_look_prior: int = 0,
    sealed_look_index: int = 0,
    sealed_test_reused: bool = False,
    options_program_looks_count: int = 0,
    presealed_abandonments: int = 0,
    promote_on_pass: bool = True,
) -> OptionsPromotionResult:
    """A sibling of ``promotion._finalize``, never a call into it.

    The verdict rule is identical — ``bool(gates) and all(g.passed ...)`` — and
    so is the "only this path may approve" property.  What is deliberately NOT
    shared is the function itself: ``_finalize`` takes a ``BaselineStrategy`` and
    a ``list[Gate]``, and widening either to accommodate options would put an
    options change on the equity ladder's own code path.
    """
    passed = bool(gates) and all(g.passed for g in gates)
    verdict = VERDICT_APPROVED if passed else VERDICT_NO_TRADE
    now = utcnow()

    row = StrategyPromotionEvaluation(
        strategy_version_id=version.id,
        dataset_snapshot_id=dataset_snapshot.id,
        evaluated_at=now,
        config_hash=config.config_hash,
        git_sha=spec.git_sha,
        spec_json_hash=spec_json_hash(spec),
        universe_json=list(symbols),
        window_start=window.start,
        window_end=window.end,
        data_provenance_json=data_provenance,
        gates_json=[g.to_dict() for g in gates],
        passed=passed,
        verdict=verdict,
        sealed_test_id=sealed_test_id,
    )
    session.add(row)
    session.flush()

    if passed and promote_on_pass:
        strat = session.get(Strategy, version.strategy_id)
        before = strat.status.value if strat else version.status.value
        if strat is not None:
            strat.status = StrategyStatus.PAPER_APPROVED
        version.status = StrategyStatus.PAPER_APPROVED
        session.flush()
        session.add(
            AuditLog(
                ts=now,
                actor="options_promotion_pipeline",
                action="strategy.promote",
                entity=f"{spec.name}@{spec.version}",
                before_json={"status": before},
                after_json={
                    "status": StrategyStatus.PAPER_APPROVED.value,
                    "evaluation_id": row.id,
                    "gates_passed": len(gates),
                    "asset_class": "options",
                    "authorises_no_order": True,
                },
            )
        )
        session.flush()
        audit.record(
            "strategy.promote",
            actor="options_promotion_pipeline",
            entity=f"{spec.name}@{spec.version}",
            before=before,
            after=StrategyStatus.PAPER_APPROVED.value,
            evaluation_id=row.id,
        )
        _log.warning(
            "options_promotion.approved",
            strategy=spec.name,
            version=spec.version,
            evaluation_id=row.id,
        )
    else:
        _log.info(
            "options_promotion.no_trade",
            strategy=spec.name,
            version=spec.version,
            evaluation_id=row.id,
            failed_gates=[g.gate_id for g in gates if not g.passed],
        )

    return OptionsPromotionResult(
        strategy_key=spec.name,
        version=spec.version,
        strategy_version_id=version.id,
        evaluation_id=row.id,
        evaluated_at=now.isoformat(),
        config_hash=config.config_hash,
        options_config_hash=options_config_hash,
        full_config_hash=config.full_config_hash,
        git_sha=spec.git_sha,
        universe=list(symbols),
        window=window,
        dataset_snapshot_id=dataset_snapshot.id,
        dataset_snapshot_key=dataset_snapshot.key,
        data_provenance=data_provenance,
        gates=gates,
        passed=passed,
        verdict=verdict,
        sealed_test_id=sealed_test_id,
        sealed_look_prior=sealed_look_prior,
        sealed_look_index=sealed_look_index,
        sealed_test_reused=sealed_test_reused,
        options_program_looks=options_program_looks_count,
        presealed_abandonments=presealed_abandonments,
    )


# --------------------------------------------------------------------------- #
# the disposition record (D4 §9)
# --------------------------------------------------------------------------- #
def options_disposition_record(
    result: OptionsPromotionResult,
    *,
    verdict: str,
    status: str,
    preregistration_ref: str,
    variant_grid: Sequence[Mapping[str, Any]] = (),
    falsification: Sequence[Mapping[str, Any]] = (),
    closes: str = "",
    does_not_close: str = "",
    operator_decisions: Sequence[str] = (),
) -> str:
    """Render D4 §9's disposition format for one options family.

    The append convention is kept from the existing records in
    ``docs/research/dispositions/``: a later powered or confirming run appends a
    ``## CONFIRMED`` section; **earlier sections are never rewritten.**  The
    sections D4 adds over the equity format are §0 (structure identity and the
    incomparability notice), §4 (data provenance), §5 (measured artefacts), §5a
    (risk-limit fit) and §6 (the complete pre-registered variant grid, cell by
    cell — because "abandoned variant" is definable only as "a pre-registered
    cell that was not reported").
    """
    ev = {g.gate_id: g for g in result.gates}

    def _row(gate_id: str) -> str:
        g = ev.get(gate_id)
        if g is None:
            return f"| {gate_id} | — | not reached | gate 0 is fail-fast |"
        mark = "PASS" if g.passed else "FAIL"
        detail = g.detail.replace("\n", " ").replace("|", "/")
        return f"| {g.number} | {g.label or '—'} | {mark} | {detail} |"

    identity = ev.get("0.5")
    ident_ev = identity.evidence if identity is not None else {}
    limits = ev.get("0.i")
    limit_ev = limits.evidence if limits is not None else {}
    quality = ev.get("8")
    q_ev = quality.evidence if quality is not None else {}
    fill = ev.get("0.f")
    fill_ev = fill.evidence if fill is not None else {}
    iv = ev.get("0.e")
    iv_ev = iv.evidence if iv is not None else {}
    q_by = ev.get("0.g")
    qby_ev = q_by.evidence if q_by is not None else {}

    lines: list[str] = []
    lines.append(
        f"# Disposition — `{result.strategy_key}` v{result.version} "
        f"(version {result.strategy_version_id})"
    )
    lines.append("")
    lines.append(
        f"**Verdict: {verdict}.** Status stays/becomes `{status}`. "
        "No `src/` or `tests/` file is touched."
    )
    took_a_look = bool(result.sealed_look_index) and not result.sealed_test_reused
    k_after = result.sealed_look_prior + int(took_a_look)
    lines.append(
        f"**Sealed looks consumed: {int(took_a_look)}. "
        f"count_sealed_looks({result.strategy_key}) = {k_after} "
        f"(was {result.sealed_look_prior}).**"
    )
    lines.append(
        f"**Options program looks (pre-registered family list): {result.options_program_looks}. "
        f"k_effective = {result.k_effective} "
        f"({result.sealed_look_prior} sealed + {result.presealed_abandonments} pre-sealed "
        f"abandonments). Budget {OPTIONS_LOOK_BUDGET}.**"
    )
    lines.append("")
    lines.append(
        f"Source: `{preregistration_ref}` (pre-registration, read in full); "
        "`docs/research/options_designs/D4_options_gate_spec.md` (this ladder)."
    )
    lines.append("")
    lines.append("## 0. Structure identity and R basis")
    lines.append(
        f"structure_type: {ident_ev.get('structure_type')}      "
        f"legs: {ident_ev.get('legs_per_structure')}      "
        f"sign pattern: {ident_ev.get('leg_sign_pattern')}"
    )
    lines.append(
        f"R basis: {ident_ev.get('r_basis_formula')}, M = {ident_ev.get('m_declared')}, "
        f"R scale = ${ident_ev.get('r_scale_usd', 0.0):,.2f}"
    )
    lines.append(
        "**Incomparability notice:** this R stream may not be pooled, averaged, bootstrapped "
        "together, or compared with any other structure's R stream, or with the equity R stream."
    )
    lines.append("")
    lines.append("## 1. The verdict, precisely")
    binding = ev.get("4")
    lines.append(
        f"gated on R_incl, UNCLAMPED series; CI low "
        f"{binding.evidence.get('ci_low_r') if binding else 'n/a'}; "
        f"clustering convention {q_ev.get('clustering_unit')}"
    )
    lines.append("")
    lines.append("## 2. The sealed ledger")
    lines.append("| Snap | Window | Sealed n | Expectancy | passed | k_prior | this_look |")
    lines.append("|---|---|---|---|---|---|---|")
    sealed_gate = ev.get("9")
    sl = (sealed_gate.evidence.get("sealed_look_ledger") if sealed_gate else {}) or {}
    for look in sl.get("looks", []):
        lines.append(
            f"| {look.get('dataset_snapshot_key')} | {look.get('window')} | "
            f"{look.get('n_trades')} | {look.get('expectancy_r')} | {look.get('passed')} | "
            f"{sl.get('k_prior')} | {sl.get('this_look')} |"
        )
    if not sl.get("looks"):
        lines.append("| — | — | — | — | — | 0 | 0 |  <!-- k = 0 by construction -->")
    lines.append("")
    lines.append("## 3. Gate-by-gate result")
    lines.append("| Gate | label | pass | detail |")
    lines.append("|---|---|---|---|")
    for gate_id in (
        "0.a",
        "0.b",
        "0.c",
        "0.d",
        "0.e",
        "0.f",
        "0.g",
        "0.h",
        "0.i",
        "0.5",
        "1",
        "2",
        "3",
        "4",
        "4b",
        "5",
        "6",
        "6b",
        "7",
        "7b",
        "8",
        "9",
        "10",
    ):
        lines.append(_row(gate_id))
    lines.append("")
    lines.append("## 4. Data-provenance and disclosure block")
    lines.append(f"iv_source mix: {iv_ev.get('iv_source_mix')}")
    lines.append(f"q by underlying: {qby_ev.get('q_by_underlying')}")
    lines.append(f"fill_model: {fill_ev.get('fill_model')}")
    lines.append(
        "NBBO unavailable for options AND equities (403, "
        f"{fill_ev.get('entitlement_batches_checked')}/"
        f"{fill_ev.get('entitlement_batches_checked')} entitlement batches)."
    )
    lines.append(
        "Assignment approximated away by the force-close rule — **bias is in the strategy's "
        "favour**. Early assignment on short calls is not modelled at all."
    )
    lines.append("Stop is a **close-basis** stop, checked only against the session close.")
    lines.append("")
    lines.append("## 5. The measured-artefact block")
    lines.append(
        f"r_clamped: {q_ev.get('r_clamped_count')} ({q_ev.get('r_clamped_fraction')})   "
        f"pnl_r min unclamped: {q_ev.get('pnl_r_min_unclamped')}"
    )
    lines.append(
        f"pinned: {q_ev.get('pinned_fraction')}   expectancy excluding pinned: "
        f"{q_ev.get('expectancy_excluding_pinned_r')}  (sign survives? "
        f"{q_ev.get('expectancy_sign_survives_pin_removal')})"
    )
    lines.append(
        f"stop non-binding: {q_ev.get('stop_non_binding_count')} of "
        f"{q_ev.get('n_losing_trades')} losing trades "
        f"({q_ev.get('stop_non_binding_fraction_of_losers')}) — the ceiling binds on the "
        "LOSING-trade fraction"
    )
    lines.append(
        f"non-entries: {q_ev.get('non_entry_count')}   exit deferrals: "
        f"{q_ev.get('exit_deferral_distribution')}"
    )
    lines.append(
        f"synthetic mark fraction (trade-weighted): "
        f"{q_ev.get('synthetic_mark_fraction_trade_weighted')}  (ceiling "
        f"{q_ev.get('synthetic_mark_fraction_max')})"
    )
    lines.append("")
    lines.append("## 5a. Risk-limit fit block")
    lines.append(
        f"declared width: {ident_ev.get('width_declared')}    R scale: "
        f"${ident_ev.get('r_scale_usd', 0.0):,.2f}    max R observed: "
        f"${limit_ev.get('r_max_observed_usd', 0.0):,.2f}"
    )
    lines.append(
        f"pre-registered per-structure max loss: "
        f"${limit_ev.get('options_per_structure_max_loss', 0.0):,.2f}   aggregate open max loss: "
        f"${limit_ev.get('options_total_open_max_loss', 0.0):,.2f}"
    )
    lines.append(
        f"max concurrent open R over the span: "
        f"${limit_ev.get('concurrent_open_r_max_usd', 0.0):,.2f}     structures breaching the "
        f"cap: {limit_ev.get('structures_breaching_per_structure_cap')}"
    )
    lines.append(
        f"limits are inside options_config_hash: "
        f"{limit_ev.get('limits_in_options_config_hash')}"
    )
    lines.append("")
    lines.append("## 6. Variant ledger (R5)")
    lines.append("| # | cell | reported? | pre-sealed result (SE) | status |")
    lines.append("|---|---|---|---|---|")
    reported = 0
    for i, cell in enumerate(variant_grid, start=1):
        was = bool(cell.get("reported"))
        reported += int(was)
        lines.append(
            f"| {i} | {cell.get('cell')} | {'yes' if was else 'NO'} | "
            f"{cell.get('result', '—')} | {cell.get('status', 'abandoned' if not was else '')} |"
        )
    lines.append(
        f"Total pre-registered cells: {len(variant_grid)}. Reported: {reported}. "
        "**Unreported = abandoned, and listed here.**"
    )
    lines.append("")
    lines.append("## 7. Falsification record (R10)")
    for f in falsification:
        lines.append(f"- **{f.get('id')}** — {f.get('condition')} → observed: {f.get('observed')}")
    if not falsification:
        lines.append("- (none recorded)")
    lines.append("")
    lines.append("## 8. What this closes, and what it does not")
    lines.append(closes or "(not stated)")
    lines.append(does_not_close or "")
    lines.append("")
    lines.append("## 9. Operator decisions outstanding")
    for d in operator_decisions:
        lines.append(f"- {d}")
    if not operator_decisions:
        lines.append("- (none recorded)")
    lines.append("")
    lines.append("---")
    lines.append(
        "*Read-only disposition. No strategy code, configuration, database row, or gate "
        "threshold was changed in producing this record.*"
    )
    return "\n".join(lines) + "\n"


__all__ = [
    "OPTIONS_FAMILY_NAMES",
    "OPTIONS_LADDER_SHAPE",
    "OPTIONS_LOOK_BUDGET",
    "OPTIONS_LOOK_BUDGET_D4",
    "OptionsEvidence",
    "OptionsPromotionResult",
    "OptionsSnapshotNotScoped",
    "evaluate_options_promotion",
    "options_disposition_record",
    "options_program_looks",
]
