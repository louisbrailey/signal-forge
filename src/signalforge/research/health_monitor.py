"""Strategy-health monitor (ARCHITECTURE.md §5.3, Phase 2).

Compares each strategy version's rolling *live-paper* expectancy against its
out-of-sample backtest expectancy. A material, statistically meaningful shortfall
auto-downgrades ``paper_approved`` -> ``experimental``; a severe shortfall on an
already-experimental strategy -> ``disabled``.

The rules live in ``HealthMonitorConfig`` (version-controlled, folded into
``config_hash``, shown in Strategy Lab). Every transition writes a
``strategy_health`` row, an ``audit_log`` row, and a JSONL audit line.

Two asset classes, one monitor (D3 §7.3). Options structures never write a
``paper_position`` row, so the equity reader here is structurally blind to them —
and blind means never downgraded, a fail-open in the one place this system must
fail closed. The options branch is therefore EXPLICIT
(:func:`is_options_strategy_version` -> :func:`closed_options_r_multiples`), is
entered only for an options family, and uses the options definition of R:
``realized_pnl / r_dollars``, max-loss-normalised and clamped at -1R, with the
clamp count and the unclamped minimum reported beside it rather than absorbed.
An equity version's series, expectancy, z-score, note and ``strategy_health`` row
are unchanged, to the digit.

Deterministic: no RNG, no LLM, no network.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from signalforge import audit
from signalforge.config.research import HealthMonitorConfig
from signalforge.db.models import (
    AuditLog,
    BacktestMetric,
    BacktestRun,
    Candidate,
    OptionsPosition,
    OptionsTrade,
    PaperPosition,
    PaperTrade,
    Strategy,
    StrategyHealth,
    StrategyVersion,
)
from signalforge.db.paper_voids import voided_position_ids
from signalforge.db.types import utcnow
from signalforge.domain import PaperDecision, StrategyStatus
from signalforge.observability import get_logger

_log = get_logger("health_monitor")

_NO_ACTION = "none"

#: Persisted (and reported) when a version has too few closed mechanically
#: accepted paper trades to compare. Deliberately <= 12 characters:
#: ``strategy_health.action`` is ``String(12)`` and Postgres (docker-compose)
#: enforces the length — a longer value would abort the whole monitor cycle.
INSUFFICIENT_ACTION = "insufficient"

#: The automatic acceptance actors. Literals rather than imports of
#: ``paper.auto_simulate.AUTO_SIM_ACTOR`` / ``paper.options_auto_simulate.
#: OPTIONS_AUTO_SIM_ACTOR`` because those modules pull in the whole paper write
#: stack, and read-only readers (agents/, the dashboard) import this module — a
#: pinning test asserts the literals stay equal to those constants.
MECHANICAL_EQUITY_ACTOR = "auto_simulate"
MECHANICAL_OPTIONS_ACTOR = "options_auto_simulate"

#: A sample standard error needs at least two observations (n - 1 > 0). Whatever
#: ``HealthMonitorConfig.min_paper_trades`` says, fewer than this is never compared.
_MIN_TRADES_FOR_SAMPLE_VARIANCE = 2


@dataclass(frozen=True, slots=True)
class HealthAssessment:
    strategy: str
    version: str
    window_label: str
    n_paper_trades: int
    paper_expectancy_r: float
    backtest_expectancy_r: float
    z_score: float
    action: str  # none | downgrade | disable | insufficient | no_backtest | disabled
    from_status: str
    to_status: str


def closed_paper_r_multiples(
    session: Session,
    strategy_version_id: int,
    *,
    closed_since: datetime | None = None,
) -> list[float]:
    """R-multiples of every closed paper position for this strategy version.

    R = realized P&L / initial dollar risk (entry-to-stop distance * shares).
    ``realized_pnl`` is already signed for the position's side, so a winning
    long and a winning short both yield a positive R.

    Public because the D6 arming ceremony's decision-10 evidence precondition
    ("at least 20 closed paper trades with non-negative expectancy **under the
    health monitor**") must be measured with THIS definition of a closed trade
    and THIS definition of R — not a second, separately-drifting copy inside
    the execution layer. D6 open question Q10 asked which health-monitor field
    the arming CLI reads; this function is the answer.

    ``closed_since`` narrows the window to positions closed at or after a given
    instant. D6 §7b rule 3 uses it: superseding an ``execution_limits`` row
    resets the live-evidence counter, because evidence accumulated under a
    different set of execution parameters is evidence about a different system.

    MECHANICAL ACCEPTANCES ONLY. A position counts only when the ACCEPTED
    ``paper_trade`` that opened it carries ``actor == "auto_simulate"`` (the
    indexed column D6 §5.3 P6 already trusts for order authorisation). An
    operator's manual ``accept_candidate`` (actor ``local-user``) is the
    operator's selection, not the strategy's — counting it would let hand-picked
    trades both shield a strategy from a downgrade and manufacture decision-10
    arming evidence. A position with no ACCEPTED trade at all is not provably
    mechanical either, so it is excluded too (fail closed: the inclusion test is
    positive, never "not known to be manual").
    """
    mechanically_accepted = exists().where(
        PaperTrade.position_id == PaperPosition.id,
        PaperTrade.decision == PaperDecision.ACCEPTED,
        PaperTrade.actor == MECHANICAL_EQUITY_ACTOR,
    )
    stmt = select(PaperPosition).where(
        PaperPosition.strategy_version_id == strategy_version_id,
        PaperPosition.closed_at.is_not(None),
        mechanically_accepted,
    )
    if closed_since is not None:
        stmt = stmt.where(PaperPosition.closed_at >= closed_since)
    positions = session.scalars(stmt)
    out: list[float] = []
    # A voided trade (append-only ``legacy_void`` correction) never happened:
    # it is not a closed trade and contributes no R.
    voided = voided_position_ids(session)
    for p in positions:
        if p.id in voided:
            continue
        if p.stop_level is None:
            continue
        per_share_risk = abs(float(p.avg_price) - p.stop_level)
        risk_dollars = per_share_risk * p.qty
        if risk_dollars <= 0:
            continue
        out.append(float(p.realized_pnl) / risk_dollars)
    return out


#: The monitor's own internal name, kept so this module reads as it did.
_paper_returns_r = closed_paper_r_multiples


#: D3 §7.3 / D3 §2.6: an options structure's R is its MAX LOSS at entry after
#: entry costs, and the live series is CLAMPED at -1 so R means what it means in
#: the backtest. Two mechanisms can push the raw ratio below -1 (the intrinsic
#: floor on a forced close, and exit costs on a structure closed at max loss), so
#: the clamp is real and its rate is a finding, not a footnote.
OPTIONS_R_FLOOR = -1.0


@dataclass(frozen=True, slots=True)
class OptionsRSeries:
    """The options half of a version's live R series, with its own honesty
    counters kept ALONGSIDE the numbers rather than summarised away."""

    r_multiples: list[float]  # clamped at OPTIONS_R_FLOOR
    clamped: int
    unclamped_min: float | None

    @property
    def n(self) -> int:
        return len(self.r_multiples)

    def note(self) -> str:
        if not self.r_multiples:
            return ""
        worst = "n/a" if self.unclamped_min is None else f"{self.unclamped_min:+.3f}"
        return (
            f"; {self.n} closed options structure(s) included "
            f"({self.clamped} clamped at {OPTIONS_R_FLOOR:+.0f}R, unclamped min {worst})"
        )


def is_options_strategy_version(session: Session, strategy_version_id: int) -> bool:
    """Is this version an OPTIONS family? Asked EXPLICITLY, never inferred from
    an empty result.

    D3 §7.3 is blunt about why: options structures never write a
    ``paper_position`` row, so both R-computing readers are structurally blind to
    them by default — and blind means never downgraded, which is a fail-open in
    the one place this system must fail closed. The options branch therefore has
    to be *written*, and it has to be written behind a positive predicate so that
    "no options rows" and "not an options strategy" stay distinguishable.

    Two positive signals, either of which settles it: the version already holds
    (or held) an options structure, or it has ever produced a candidate carrying
    a ``structure_kind`` — the same discriminator ``paper.ledger`` refuses on.
    """
    has_structure = session.scalar(
        select(OptionsPosition.id)
        .where(OptionsPosition.strategy_version_id == strategy_version_id)
        .limit(1)
    )
    if has_structure is not None:
        return True
    return (
        session.scalar(
            select(Candidate.id)
            .where(
                Candidate.strategy_version_id == strategy_version_id,
                Candidate.structure_kind.is_not(None),
            )
            .limit(1)
        )
        is not None
    )


def closed_options_r_multiples(
    session: Session,
    strategy_version_id: int,
    *,
    closed_since: datetime | None = None,
) -> OptionsRSeries:
    """R-multiples of every closed options STRUCTURE for this strategy version.

    R is max-loss-normalised: ``realized_pnl / r_dollars``, where ``r_dollars``
    is the structure's maximum loss at entry **after entry costs** — the same
    denominator every capital limit in D3 §5 is stated against, and the same one
    ``options_marks`` stores as ``pnl_r``. It is NOT the equity definition
    (entry-to-stop distance x shares): a structure has no stop level and no
    per-share price, which is exactly why D3 §13 gave it its own table.

    The returned series is CLAMPED at ``OPTIONS_R_FLOOR``; the clamp count and
    the unclamped minimum come back with it so a high clamp rate is visible
    rather than absorbed (D3 open question 16).

    ``closed_since`` mirrors :func:`closed_paper_r_multiples` so the arming
    ceremony's evidence window means the same thing on both asset classes, and
    so does the mechanical-only rule: a structure counts only when its ACCEPTED
    ``options_trade`` carries ``actor == "options_auto_simulate"``.
    """
    mechanically_accepted = exists().where(
        OptionsTrade.options_position_id == OptionsPosition.id,
        OptionsTrade.decision == PaperDecision.ACCEPTED,
        OptionsTrade.actor == MECHANICAL_OPTIONS_ACTOR,
    )
    stmt = select(OptionsPosition).where(
        OptionsPosition.strategy_version_id == strategy_version_id,
        OptionsPosition.closed_at.is_not(None),
        mechanically_accepted,
    )
    if closed_since is not None:
        stmt = stmt.where(OptionsPosition.closed_at >= closed_since)
    clamped = 0
    raw: list[float] = []
    out: list[float] = []
    for p in session.scalars(stmt):
        r_dollars = float(p.r_dollars)
        if r_dollars <= 0:
            continue
        value = float(p.realized_pnl) / r_dollars
        raw.append(value)
        if value < OPTIONS_R_FLOOR:
            clamped += 1
            value = OPTIONS_R_FLOOR
        out.append(value)
    return OptionsRSeries(r_multiples=out, clamped=clamped, unclamped_min=min(raw) if raw else None)


#: The "this version is not an options family" answer, so the equity path never
#: constructs an options object at all.
_NO_OPTIONS = OptionsRSeries(r_multiples=[], clamped=0, unclamped_min=None)


def _latest_oos_expectancy(session: Session, strategy_version_id: int) -> float | None:
    metric = session.scalar(
        select(BacktestMetric)
        .join(BacktestRun, BacktestMetric.run_id == BacktestRun.id)
        .where(
            BacktestRun.strategy_version_id == strategy_version_id,
            BacktestMetric.phase == "out_of_sample",
            BacktestMetric.segment == "all",
        )
        .order_by(BacktestRun.created_at.desc(), BacktestMetric.id.desc())
        .limit(1)
    )
    if metric is None:
        return None
    value = metric.metrics_json.get("expectancy_r")
    return float(value) if value is not None else None


def _decide(
    status: StrategyStatus, z: float, paper_exp: float, cfg: HealthMonitorConfig
) -> tuple[StrategyStatus, str]:
    """Return the (possibly unchanged) status and the action label.

    Both transitions also require paper expectancy to be outright negative, so a
    still-profitable strategy that merely trails a rich backtest is left alone.
    """
    if paper_exp >= 0 or z > cfg.downgrade_z:
        return status, _NO_ACTION
    if status is StrategyStatus.PAPER_APPROVED:
        return StrategyStatus.EXPERIMENTAL, "downgrade"
    if status is StrategyStatus.EXPERIMENTAL and z <= cfg.disable_z:
        return StrategyStatus.DISABLED, "disable"
    return status, _NO_ACTION


def _resolve_config(session: Session, config: HealthMonitorConfig | None) -> HealthMonitorConfig:
    if config is not None:
        return config
    from signalforge.settings_store import effective_research_config

    return effective_research_config(session).health_monitor


def evaluate_strategy_health(
    session: Session, *, config: HealthMonitorConfig | None = None
) -> list[HealthAssessment]:
    """Assess every strategy version; apply and record any status transitions."""
    cfg = _resolve_config(session, config)
    assessments: list[HealthAssessment] = []
    if not cfg.enabled:
        return assessments

    rows = session.execute(
        select(StrategyVersion, Strategy)
        .join(Strategy, StrategyVersion.strategy_id == Strategy.id)
        .order_by(StrategyVersion.id)
    ).all()

    for ver, strat in rows:
        from_status = strat.status.value
        if strat.status is StrategyStatus.DISABLED:
            assessments.append(
                HealthAssessment(
                    strat.name,
                    ver.version,
                    "n/a",
                    0,
                    0.0,
                    0.0,
                    0.0,
                    "disabled",
                    from_status,
                    from_status,
                )
            )
            continue

        returns = _paper_returns_r(session, ver.id)
        # D3 §7.3's explicit options branch. Asked per version and only for an
        # options family, so an equity version's series — and therefore its
        # expectancy, its z-score, its note and its StrategyHealth row — is the
        # identical list this function has always built.
        options = _NO_OPTIONS
        if is_options_strategy_version(session, ver.id):
            options = closed_options_r_multiples(session, ver.id)
            returns = [*returns, *options.r_multiples]
        n = len(returns)
        window = f"last_{n}_paper_trades"

        min_trades = max(cfg.min_paper_trades, _MIN_TRADES_FOR_SAMPLE_VARIANCE)
        if n < min_trades:
            # Recorded, not just returned: a strategy_health row per cycle is
            # how the dashboard/status can tell "monitor ran, nothing to
            # compare yet" from "monitor never ran". Placeholder 0.0 numbers
            # (the columns are NOT NULL); the action and note say they are not
            # measurements. No status change, no audit_log row.
            session.add(
                StrategyHealth(
                    strategy_version_id=ver.id,
                    window_label=window,
                    paper_expectancy=0.0,
                    backtest_expectancy=0.0,
                    z_score=0.0,
                    action=INSUFFICIENT_ACTION,
                    note=(
                        f"{n} closed mechanically accepted paper trade(s) < {min_trades} "
                        "required; not compared (manual acceptances excluded)"
                    ),
                    evaluated_at=utcnow(),
                )
            )
            session.flush()
            assessments.append(
                HealthAssessment(
                    strat.name,
                    ver.version,
                    window,
                    n,
                    0.0,
                    0.0,
                    0.0,
                    INSUFFICIENT_ACTION,
                    from_status,
                    from_status,
                )
            )
            continue

        bt_exp = _latest_oos_expectancy(session, ver.id)
        paper_exp = sum(returns) / n
        if bt_exp is None:
            assessments.append(
                HealthAssessment(
                    strat.name,
                    ver.version,
                    window,
                    n,
                    round(paper_exp, 4),
                    0.0,
                    0.0,
                    "no_backtest",
                    from_status,
                    from_status,
                )
            )
            continue

        # SAMPLE variance (Bessel, n - 1): the paper mean is itself estimated
        # from these n trades, so dividing by n understates the spread, shrinks
        # the standard error and inflates |z| — biased toward a downgrade on
        # small samples. n >= 2 is guaranteed by the min_trades gate above.
        variance = sum((r - paper_exp) ** 2 for r in returns) / (n - 1)
        std_err = math.sqrt(variance / n) or 1e-9
        z = (paper_exp - bt_exp) / std_err

        new_status, action = _decide(strat.status, z, paper_exp, cfg)
        note = (
            f"paper {paper_exp:+.3f}R vs backtest {bt_exp:+.3f}R over {n} trades (z={z:+.2f})"
            + options.note()
        )

        if action != _NO_ACTION:
            strat.status = new_status
            ver.status = new_status
            session.flush()
            after_json: dict[str, object] = {
                "status": new_status.value,
                "z_score": round(z, 3),
                "paper_expectancy_r": round(paper_exp, 4),
                "backtest_expectancy_r": round(bt_exp, 4),
                "n_paper_trades": n,
                "rule": f"z<={cfg.downgrade_z} (downgrade) / z<={cfg.disable_z} (disable)",
            }
            # Added ONLY when the options branch actually contributed, so an
            # equity transition's audit payload is the identical dict it was.
            if options.n:
                after_json["n_options_structures"] = options.n
                after_json["options_clamped_at_minus_1r"] = options.clamped
                after_json["options_unclamped_min_r"] = options.unclamped_min
            session.add(
                AuditLog(
                    ts=utcnow(),
                    actor="health_monitor",
                    action=f"strategy.{action}",
                    entity=f"{strat.name}@{ver.version}",
                    before_json={"status": from_status},
                    after_json=after_json,
                )
            )
            audit.record(
                f"strategy.{action}",
                actor="health_monitor",
                entity=f"{strat.name}@{ver.version}",
                before=from_status,
                after=new_status.value,
                z_score=round(z, 3),
                n_paper_trades=n,
            )
            _log.warning(
                "health.transition",
                strategy=strat.name,
                version=ver.version,
                action=action,
                z=round(z, 2),
                paper_exp=round(paper_exp, 3),
                bt_exp=round(bt_exp, 3),
            )

        session.add(
            StrategyHealth(
                strategy_version_id=ver.id,
                window_label=window,
                paper_expectancy=paper_exp,
                backtest_expectancy=bt_exp,
                z_score=z,
                action=action,
                note=note,
                evaluated_at=utcnow(),
            )
        )
        session.flush()
        assessments.append(
            HealthAssessment(
                strategy=strat.name,
                version=ver.version,
                window_label=window,
                n_paper_trades=n,
                paper_expectancy_r=round(paper_exp, 4),
                backtest_expectancy_r=round(bt_exp, 4),
                z_score=round(z, 3),
                action=action,
                from_status=from_status,
                to_status=strat.status.value,
            )
        )
    return assessments


def run_health_monitor(
    session: Session, *, config: HealthMonitorConfig | None = None
) -> list[HealthAssessment]:
    """Scheduler entry point: assess health and log a one-line cycle summary."""
    result = evaluate_strategy_health(session, config=config)
    _log.info(
        "health.cycle",
        assessed=len(result),
        transitions=sum(1 for a in result if a.action in ("downgrade", "disable")),
    )
    return result


def _newest_preferring_assessments[K](
    rows: list[tuple[K, StrategyHealth]],
) -> dict[K, StrategyHealth]:
    """First row per key from newest-first ``rows``, where an ``insufficient``
    row is used only when the key has no real assessment at all.

    Every short-of-trades version writes an ``insufficient`` row each cycle, so
    "newest wins" would let a sibling version's (or a later cycle's)
    placeholder hide a real downgrade/disable from the operator. A real
    assessment always outranks a placeholder; its ``evaluated_at`` shows its age.
    """
    real: dict[K, StrategyHealth] = {}
    placeholder: dict[K, StrategyHealth] = {}
    for key, health in rows:
        bucket = placeholder if health.action == INSUFFICIENT_ACTION else real
        bucket.setdefault(key, health)
    for key, health in placeholder.items():
        real.setdefault(key, health)
    return real


def latest_health_by_strategy(session: Session) -> dict[str, StrategyHealth]:
    """Most recent real StrategyHealth row per strategy name (for Strategy Lab),
    falling back to the newest ``insufficient`` row only when the strategy has
    no real assessment for any version."""
    rows = session.execute(
        select(Strategy.name, StrategyHealth)
        .join(StrategyVersion, StrategyHealth.strategy_version_id == StrategyVersion.id)
        .join(Strategy, StrategyVersion.strategy_id == Strategy.id)
        .order_by(StrategyHealth.evaluated_at.desc(), StrategyHealth.id.desc())
    ).all()
    return _newest_preferring_assessments([(name, health) for name, health in rows])


def latest_health_by_version(session: Session) -> dict[int, StrategyHealth]:
    """Most recent real StrategyHealth row per strategy_version_id, with the
    same ``insufficient`` fallback (for pages that render one row per version)."""
    rows = session.scalars(
        select(StrategyHealth).order_by(
            StrategyHealth.evaluated_at.desc(), StrategyHealth.id.desc()
        )
    ).all()
    return _newest_preferring_assessments([(h.strategy_version_id, h) for h in rows])
