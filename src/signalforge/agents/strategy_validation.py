"""Deterministic strategy-validation agent (read-only).

Reports what the deterministic promotion pipeline and the scheduled
health-monitor job have already recorded for each strategy version: the
latest promotion evaluation (pass/fail, failed gate names), the sealed
out-of-sample test, the exact approved scope of every PASSING evaluation,
the latest health-monitor assessment, and a simple, honest read of live-paper
trades. This agent never runs a backtest, a walk-forward evaluation, a sealed
test, or the health monitor itself — it only reads versioned rows those jobs
already wrote.

Import-boundary note (S14, ``pyproject.toml``): ``signalforge.research.promotion``
is explicitly forbidden, so ``latest_evaluations`` is reproduced here as a
direct query. Less obviously, ``signalforge.research.approval_scope`` and
``signalforge.research.paper_probation`` are ALSO unsafe to import even though
their read-only helpers (``approved_scopes``, ``paper_probation_context``) do
nothing but query the ORM: ``approval_scope.py`` has a deferred import (inside
``current_spec_json_hash``, a function this agent never calls) that reaches
``signalforge.research.persistence`` -> ``signalforge.research.backtest_runner``
-> ``signalforge.data.repository`` -> ``signalforge.data.adapters.base``, and
``paper_probation.py`` imports ``approval_scope`` at module level — so both
modules carry that edge in ``lint-imports``' whole-module import graph
regardless of which function is actually used. The small amount of logic this
agent needs from both (an approved scope's dataset/hashes/sources; a simple
count and average R-multiple over closed paper positions) is reproduced
directly against ``signalforge.db.models`` instead, which has no such
entanglement. Only ``signalforge.research.health_monitor.latest_health_by_strategy``
was verified import-safe and is used as-is.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from signalforge.agents.base import ResearchAgent
from signalforge.db.models import (
    DataSnapshot,
    PaperPosition,
    Strategy,
    StrategyPromotionEvaluation,
    StrategySealedTest,
    StrategyVersion,
)
from signalforge.domain import StrategyStatus
from signalforge.research.health_monitor import latest_health_by_strategy


class StrategyValidationAgent(ResearchAgent):
    """Reads versioned promotion / sealed-test / health-monitor results and
    reports them as-is. Never approves, disables, or re-evaluates a strategy."""

    name = "strategy_validation"
    role = "Deterministic strategy-validation agent"
    allowed_inputs = (
        "signalforge.db.models.Strategy",
        "signalforge.db.models.StrategyVersion",
        "signalforge.db.models.StrategyPromotionEvaluation",
        "signalforge.db.models.StrategySealedTest",
        "signalforge.db.models.DataSnapshot",
        "signalforge.db.models.PaperPosition",
        "signalforge.research.health_monitor.latest_health_by_strategy",
    )
    outputs = (
        "promotion_status",
        "approved_scope_report",
        "sealed_test_summary",
        "health_summary",
        "paper_trade_summary",
    )
    prohibited = (
        "run_backtest",
        "run_walkforward",
        "run_sealed_test",
        "run_health_monitor",
        "approve_strategy",
        "change_strategy_status",
        "write_setting",
    )
    llm_narrative = False

    def collect(self, session: Session) -> dict[str, Any]:
        now = datetime.now(UTC)
        missing: list[str] = []

        strategies = list(session.scalars(select(Strategy).order_by(Strategy.name)))
        if not strategies:
            missing.append("no strategies recorded yet")

        health_by_name = latest_health_by_strategy(session)

        strategy_versions: list[dict[str, Any]] = []
        paper_approved: list[dict[str, Any]] = []

        for strat in strategies:
            versions = list(
                session.scalars(
                    select(StrategyVersion)
                    .where(StrategyVersion.strategy_id == strat.id)
                    .order_by(StrategyVersion.version)
                )
            )
            if not versions:
                missing.append(f"{strat.name}: no strategy versions recorded")
                continue

            health_row = health_by_name.get(strat.name)
            health: dict[str, Any] | None = None
            if health_row is None:
                missing.append(f"{strat.name}: no health-monitor assessment recorded yet")
            else:
                health = {
                    "window_label": health_row.window_label,
                    "z_score": health_row.z_score,
                    "action": health_row.action,
                    "note": health_row.note,
                    "evaluated_at": health_row.evaluated_at.isoformat(),
                    "source": "signalforge.db.models.StrategyHealth",
                    "as_of": health_row.evaluated_at.isoformat(),
                }

            for ver in versions:
                latest_eval_row = session.scalar(
                    select(StrategyPromotionEvaluation)
                    .where(StrategyPromotionEvaluation.strategy_version_id == ver.id)
                    .order_by(
                        StrategyPromotionEvaluation.evaluated_at.desc(),
                        StrategyPromotionEvaluation.id.desc(),
                    )
                    .limit(1)
                )
                evaluation: dict[str, Any] | None = None
                if latest_eval_row is None:
                    missing.append(
                        f"{strat.name} v{ver.version}: no promotion evaluation recorded yet"
                    )
                else:
                    gates = list(latest_eval_row.gates_json or [])
                    failed_gates = [
                        str(g.get("name", "?")) for g in gates if not g.get("passed", False)
                    ]
                    evaluation = {
                        "evaluated_at": latest_eval_row.evaluated_at.isoformat(),
                        "passed": latest_eval_row.passed,
                        "verdict": latest_eval_row.verdict,
                        "gates_total": len(gates),
                        "gates_failed": failed_gates,
                        "source": "signalforge.db.models.StrategyPromotionEvaluation",
                        "as_of": latest_eval_row.evaluated_at.isoformat(),
                    }

                # "approved scope" = every PASSING evaluation's exact scope
                # (reproduces signalforge.research.approval_scope.approved_scopes
                # without importing that module — see the module docstring).
                passing_rows = list(
                    session.scalars(
                        select(StrategyPromotionEvaluation).where(
                            StrategyPromotionEvaluation.strategy_version_id == ver.id,
                            StrategyPromotionEvaluation.passed.is_(True),
                        )
                    )
                )
                scopes: list[dict[str, Any]] = []
                for row in passing_rows:
                    snap = (
                        session.get(DataSnapshot, row.dataset_snapshot_id)
                        if row.dataset_snapshot_id is not None
                        else None
                    )
                    scopes.append(
                        {
                            "evaluation_id": row.id,
                            "dataset_snapshot_id": row.dataset_snapshot_id,
                            "dataset_key": snap.key if snap is not None else None,
                            "universe_size": len(row.universe_json or []),
                            "sources": sorted(
                                (row.data_provenance_json or {}).get("sources") or []
                            ),
                            "config_hash": row.config_hash,
                            "spec_json_hash": row.spec_json_hash,
                            "source": "signalforge.db.models.StrategyPromotionEvaluation",
                            "as_of": row.evaluated_at.isoformat(),
                        }
                    )

                sealed_row = None
                if scopes:
                    sealed_row = session.scalar(
                        select(StrategySealedTest).where(
                            StrategySealedTest.strategy_version_id == ver.id,
                            StrategySealedTest.dataset_snapshot_id
                            == scopes[0]["dataset_snapshot_id"],
                        )
                    )
                if sealed_row is None:
                    sealed_row = session.scalar(
                        select(StrategySealedTest)
                        .where(StrategySealedTest.strategy_version_id == ver.id)
                        .order_by(StrategySealedTest.evaluated_at.desc())
                        .limit(1)
                    )
                sealed: dict[str, Any] | None = None
                if sealed_row is None:
                    missing.append(f"{strat.name} v{ver.version}: no sealed test recorded")
                else:
                    metrics = sealed_row.metrics_json or {}
                    sealed = {
                        "window_start": sealed_row.window_start.isoformat(),
                        "window_end": sealed_row.window_end.isoformat(),
                        "n_trades": metrics.get("n_trades"),
                        "expectancy_r": metrics.get("expectancy_r"),
                        "passed": sealed_row.passed,
                        "detail": sealed_row.detail,
                        "source": "signalforge.db.models.StrategySealedTest",
                        "as_of": sealed_row.evaluated_at.isoformat(),
                    }

                # Live-paper trades: a simple, direct, independently-computed
                # read from paper_position rows (count + mean R-multiple) —
                # NOT the Paper Probation dashboard's equity-curve/drawdown
                # figures, which live in research.paper_probation and cannot
                # be imported here under contract S14 (see module docstring).
                positions = list(
                    session.scalars(
                        select(PaperPosition).where(
                            PaperPosition.strategy_version_id == ver.id,
                            PaperPosition.closed_at.is_not(None),
                        )
                    )
                )
                r_values: list[float] = []
                last_closed: datetime | None = None
                for pos in positions:
                    if pos.stop_level is not None:
                        per_share_risk = abs(float(pos.avg_price) - pos.stop_level)
                        if per_share_risk > 0:
                            r_values.append(float(pos.realized_pnl) / (per_share_risk * pos.qty))
                    if pos.closed_at is not None and (
                        last_closed is None or pos.closed_at > last_closed
                    ):
                        last_closed = pos.closed_at
                paper = {
                    "n_closed_trades": len(positions),
                    "n_r_valid_trades": len(r_values),
                    "realized_expectancy_r": (
                        round(sum(r_values) / len(r_values), 4) if r_values else None
                    ),
                    "last_closed_at": last_closed.isoformat() if last_closed else None,
                    "note": (
                        "simplified independent recomputation from paper_position rows — "
                        "not the Paper Probation dashboard's equity-curve figures"
                    ),
                    "source": "signalforge.db.models.PaperPosition",
                    "as_of": now.isoformat(),
                }
                if ver.status == StrategyStatus.PAPER_APPROVED and not positions:
                    missing.append(
                        f"{strat.name} v{ver.version}: paper_approved but no closed paper "
                        "positions recorded yet"
                    )

                entry = {
                    "strategy_name": strat.name,
                    "strategy_id": strat.id,
                    "horizon": strat.horizon.value,
                    "strategy_status": strat.status.value,
                    "version_id": ver.id,
                    "version": ver.version,
                    "version_status": ver.status.value,
                    "git_sha": ver.git_sha,
                    "latest_evaluation": evaluation,
                    "approved_scopes": scopes,
                    "sealed_test": sealed,
                    "health": health,
                    "paper": paper,
                }
                strategy_versions.append(entry)

                is_approved = (
                    strat.status == StrategyStatus.PAPER_APPROVED
                    and ver.status == StrategyStatus.PAPER_APPROVED
                )
                if is_approved:
                    paper_approved.append(
                        {
                            "strategy_name": strat.name,
                            "version": ver.version,
                            "scopes": scopes,
                        }
                    )
                    if not scopes:
                        missing.append(
                            f"{strat.name} v{ver.version}: status is paper_approved but no "
                            "passing evaluation scope was found"
                        )

        if not paper_approved:
            missing.append("no PAPER_APPROVED strategy versions found")

        return {
            "as_of": now.isoformat(),
            "strategy_versions": strategy_versions,
            "paper_approved": paper_approved,
            "note": (
                "This agent only reads versioned results already produced by the "
                "deterministic promotion pipeline and the scheduled health-monitor job "
                "(StrategyPromotionEvaluation, StrategySealedTest, StrategyHealth); it never "
                "runs a backtest, a walk-forward evaluation, a sealed test, or a health check."
            ),
            "missing_data": missing,
        }

    def summarize(self, evidence: dict[str, Any]) -> str:
        lines: list[str] = [
            "Strategy-validation report (read-only): this agent only reads versioned "
            "results already produced by the deterministic promotion pipeline and the "
            "scheduled health-monitor job — it never runs a backtest, walk-forward "
            "evaluation, sealed test, or health check itself."
        ]

        approved = evidence["paper_approved"]
        if approved:
            lines.append(f"PAPER_APPROVED strategy versions ({len(approved)}):")
            for a in approved:
                if not a["scopes"]:
                    lines.append(
                        f"  - {a['strategy_name']} v{a['version']}: no passing evaluation "
                        "scope on record."
                    )
                    continue
                for sc in a["scopes"]:
                    lines.append(
                        f"  - {a['strategy_name']} v{a['version']}: dataset_snapshot_id="
                        f"{sc['dataset_snapshot_id']} (key={sc['dataset_key']}), "
                        f"universe_size={sc['universe_size']}, sources={sc['sources']}, "
                        f"config_hash={sc['config_hash'][:12]}, "
                        f"spec_hash={sc['spec_json_hash'][:12]}."
                    )
        else:
            lines.append("No strategy version is currently PAPER_APPROVED.")

        for entry in evidence["strategy_versions"]:
            ev = entry["latest_evaluation"]
            if ev is not None and not ev["passed"] and ev["gates_failed"]:
                lines.append(
                    f"{entry['strategy_name']} v{entry['version']} latest evaluation FAILED "
                    "gates: " + ", ".join(ev["gates_failed"]) + "."
                )

        if evidence["missing_data"]:
            lines.append(
                f"Missing data ({len(evidence['missing_data'])}): "
                + "; ".join(evidence["missing_data"])
                + "."
            )

        return "\n".join(lines)
