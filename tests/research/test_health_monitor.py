"""Strategy-health monitor: configurable, auditable downgrade/disable rules."""

from __future__ import annotations

import math
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from signalforge.config.research import HealthMonitorConfig
from signalforge.db.models import (
    AuditLog,
    BacktestMetric,
    BacktestRun,
    Instrument,
    PaperAccount,
    PaperPosition,
    PaperTrade,
    Strategy,
    StrategyHealth,
    StrategyVersion,
)
from signalforge.domain import Horizon, PaperDecision, PositionSide, StrategyStatus
from signalforge.research import health_monitor as hm
from signalforge.research.health_monitor import closed_paper_r_multiples, evaluate_strategy_health
from signalforge.research.persistence import upsert_strategy_version
from signalforge.research.strategies import default_strategies

STRAT = next(s for s in default_strategies() if s.spec().name.startswith("trend"))


def _seed(
    session: Session,
    *,
    status: StrategyStatus,
    oos_expectancy_r: float,
    paper_returns_r: list[float],
    manual_returns_r: tuple[float, ...] = (),
    unattributed_returns_r: tuple[float, ...] = (),
) -> Strategy:
    """``paper_returns_r`` are MECHANICALLY accepted (actor ``auto_simulate``);
    ``manual_returns_r`` were accepted by the operator (``local-user``);
    ``unattributed_returns_r`` have no ACCEPTED ``paper_trade`` at all."""
    acct = PaperAccount(name="default", initial_cash=Decimal("10000"), cash=Decimal("10000"))
    inst = Instrument(symbol="AAA", instrument_type="stock")
    session.add_all([acct, inst])
    session.flush()

    ver = upsert_strategy_version(session, STRAT.spec())
    strat = session.get(Strategy, ver.strategy_id)
    assert strat is not None
    strat.status = status
    ver.status = status
    session.flush()

    run = BacktestRun(
        strategy_version_id=ver.id,
        params_json={},
        date_start=datetime(2023, 1, 1, tzinfo=UTC).date(),
        date_end=datetime(2024, 1, 1, tzinfo=UTC).date(),
        config_hash="test",
    )
    session.add(run)
    session.flush()
    session.add(
        BacktestMetric(
            run_id=run.id,
            segment="all",
            phase="out_of_sample",
            metrics_json={"expectancy_r": oos_expectancy_r, "n_trades": 200},
        )
    )
    session.flush()

    # Each closed position: entry 100, stop 98 -> $2/share risk, 10 shares -> $20 risk.
    opened = datetime(2024, 1, 2, tzinfo=UTC)
    seeded: list[tuple[float, str | None]] = [
        *((r, hm.MECHANICAL_EQUITY_ACTOR) for r in paper_returns_r),
        *((r, "local-user") for r in manual_returns_r),
        *((r, None) for r in unattributed_returns_r),
    ]
    for i, (r, actor) in enumerate(seeded):
        position = PaperPosition(
            account_id=acct.id,
            instrument_id=inst.id,
            strategy_version_id=ver.id,
            horizon=Horizon.SHORT_SWING,
            side=PositionSide.LONG,
            qty=10,
            avg_price=Decimal("100"),
            stop_level=98.0,
            opened_at=opened + timedelta(days=i),
            closed_at=opened + timedelta(days=i, hours=6),
            realized_pnl=Decimal(str(round(r * 20.0, 2))),
        )
        session.add(position)
        session.flush()
        if actor is not None:
            session.add(
                PaperTrade(
                    account_id=acct.id,
                    position_id=position.id,
                    decision=PaperDecision.ACCEPTED,
                    signal_snapshot_json={"decision": {"actor": actor}},
                    plan_json={},
                    actor=actor,
                    created_at=opened + timedelta(days=i),
                )
            )
    session.flush()
    return strat


def test_downgrades_paper_approved_on_a_sustained_shortfall(session: Session) -> None:
    strat = _seed(
        session,
        status=StrategyStatus.PAPER_APPROVED,
        oos_expectancy_r=0.30,
        paper_returns_r=[-0.4, -0.6] * 12 + [-0.5],  # 25 trades, mean -0.5R
    )
    out = evaluate_strategy_health(session)

    assessed = next(a for a in out if a.strategy == strat.name)
    assert assessed.action == "downgrade"
    assert assessed.from_status == "paper_approved"
    assert assessed.to_status == "experimental"
    assert strat.status is StrategyStatus.EXPERIMENTAL

    # A strategy_health row and an audit_log row are written.
    assert session.scalar(select(func.count()).select_from(StrategyHealth)) == 1
    log = session.scalar(select(AuditLog).where(AuditLog.action == "strategy.downgrade"))
    assert log is not None
    assert log.before_json == {"status": "paper_approved"}
    assert log.after_json["status"] == "experimental"
    assert log.after_json["n_paper_trades"] == 25


def test_disables_an_experimental_strategy_on_a_severe_shortfall(session: Session) -> None:
    strat = _seed(
        session,
        status=StrategyStatus.EXPERIMENTAL,
        oos_expectancy_r=0.30,
        paper_returns_r=[-0.45, -0.55] * 12 + [-0.5],
    )
    out = evaluate_strategy_health(session)
    assessed = next(a for a in out if a.strategy == strat.name)
    assert assessed.action == "disable"
    assert strat.status is StrategyStatus.DISABLED
    assert session.scalar(select(AuditLog).where(AuditLog.action == "strategy.disable")) is not None


def test_insufficient_closed_paper_trades_changes_nothing_but_is_recorded(
    session: Session,
) -> None:
    strat = _seed(
        session,
        status=StrategyStatus.PAPER_APPROVED,
        oos_expectancy_r=0.30,
        paper_returns_r=[-0.9] * 5,
    )
    out = evaluate_strategy_health(session)
    assessed = next(a for a in out if a.strategy == strat.name)
    assert assessed.action == hm.INSUFFICIENT_ACTION
    assert strat.status is StrategyStatus.PAPER_APPROVED
    # A strategy_health row proves the monitor ran; no transition, no audit row.
    row = session.scalars(select(StrategyHealth)).one()
    assert row.action == hm.INSUFFICIENT_ACTION
    assert row.window_label == "last_5_paper_trades"
    assert (row.paper_expectancy, row.backtest_expectancy, row.z_score) == (0.0, 0.0, 0.0)
    assert "5 closed mechanically accepted paper trade(s) < 20 required" in row.note
    assert session.scalar(select(func.count()).select_from(AuditLog)) == 0
    # With no real assessment anywhere, the placeholder is what the pages show.
    assert hm.latest_health_by_strategy(session)[strat.name] is row
    assert hm.latest_health_by_version(session)[row.strategy_version_id] is row


def test_min_paper_trades_threshold_is_configurable(session: Session) -> None:
    strat = _seed(
        session,
        status=StrategyStatus.PAPER_APPROVED,
        oos_expectancy_r=0.30,
        paper_returns_r=[-0.4, -0.6] * 12 + [-0.5],  # 25 trades
    )
    out = evaluate_strategy_health(session, config=HealthMonitorConfig(min_paper_trades=100))
    assert next(a for a in out if a.strategy == strat.name).action == hm.INSUFFICIENT_ACTION
    assert strat.status is StrategyStatus.PAPER_APPROVED


def test_monitor_can_be_switched_off(session: Session) -> None:
    strat = _seed(
        session,
        status=StrategyStatus.PAPER_APPROVED,
        oos_expectancy_r=0.30,
        paper_returns_r=[-0.5] * 30,
    )
    out = evaluate_strategy_health(session, config=HealthMonitorConfig(enabled=False))
    assert out == []
    assert strat.status is StrategyStatus.PAPER_APPROVED


def test_a_still_profitable_strategy_below_its_backtest_is_left_alone(session: Session) -> None:
    strat = _seed(
        session,
        status=StrategyStatus.PAPER_APPROVED,
        oos_expectancy_r=0.50,
        paper_returns_r=[0.05, 0.15] * 12 + [0.1],  # mean +0.1R: below backtest but positive
    )
    out = evaluate_strategy_health(session)
    assessed = next(a for a in out if a.strategy == strat.name)
    assert assessed.action == "none"
    assert strat.status is StrategyStatus.PAPER_APPROVED
    # still recorded for the trend view
    assert session.scalar(select(func.count()).select_from(StrategyHealth)) == 1


def test_z_score_uses_the_sample_variance(session: Session) -> None:
    """z = (paper mean - OOS) / (s / sqrt(n)) with s the n-1 sample deviation."""
    returns = [0.5, -1.0, 1.5, -1.0, 2.0] * 4  # 20 trades
    _seed(
        session,
        status=StrategyStatus.PAPER_APPROVED,
        oos_expectancy_r=0.30,
        paper_returns_r=returns,
    )
    n = len(returns)
    mean = sum(returns) / n
    sample_var = sum((r - mean) ** 2 for r in returns) / (n - 1)
    expected_z = (mean - 0.30) / math.sqrt(sample_var / n)
    population_z = (mean - 0.30) / math.sqrt(sample_var * (n - 1) / n / n)

    evaluate_strategy_health(session)
    row = session.scalars(select(StrategyHealth)).one()
    assert row.z_score == pytest.approx(expected_z, abs=1e-12)
    assert row.z_score != pytest.approx(population_z, abs=1e-6)
    # Sample variance widens the standard error, so |z| is SMALLER than the
    # population-variance figure: the correction can only make a downgrade harder.
    assert abs(row.z_score) < abs(population_z)


def test_fewer_than_two_trades_is_never_compared_even_if_configured(session: Session) -> None:
    strat = _seed(
        session,
        status=StrategyStatus.PAPER_APPROVED,
        oos_expectancy_r=0.30,
        paper_returns_r=[-5.0],
    )
    out = evaluate_strategy_health(session, config=HealthMonitorConfig(min_paper_trades=1))
    assessed = next(a for a in out if a.strategy == strat.name)
    assert assessed.action == hm.INSUFFICIENT_ACTION
    assert strat.status is StrategyStatus.PAPER_APPROVED
    row = session.scalars(select(StrategyHealth)).one()
    assert "< 2 required" in row.note


def test_manual_acceptances_are_not_health_evidence(session: Session) -> None:
    """19 mechanical trades + 10 manual ones is still < 20: insufficient."""
    strat = _seed(
        session,
        status=StrategyStatus.PAPER_APPROVED,
        oos_expectancy_r=0.30,
        paper_returns_r=[-0.5] * 19,
        manual_returns_r=(-0.5,) * 10,
    )
    out = evaluate_strategy_health(session)
    assessed = next(a for a in out if a.strategy == strat.name)
    assert assessed.action == hm.INSUFFICIENT_ACTION
    assert assessed.n_paper_trades == 19
    assert strat.status is StrategyStatus.PAPER_APPROVED


def test_manual_winners_cannot_shield_a_failing_strategy(session: Session) -> None:
    """Hand-picked winners would lift the mean above zero; excluded, the
    strategy's own 25 trades still trigger the downgrade."""
    strat = _seed(
        session,
        status=StrategyStatus.PAPER_APPROVED,
        oos_expectancy_r=0.30,
        paper_returns_r=[-0.4, -0.6] * 12 + [-0.5],
        manual_returns_r=(5.0,) * 5,
    )
    out = evaluate_strategy_health(session)
    assessed = next(a for a in out if a.strategy == strat.name)
    assert assessed.n_paper_trades == 25
    assert assessed.action == "downgrade"
    assert strat.status is StrategyStatus.EXPERIMENTAL


def test_closed_r_series_counts_only_mechanical_acceptances(session: Session) -> None:
    _seed(
        session,
        status=StrategyStatus.PAPER_APPROVED,
        oos_expectancy_r=0.30,
        paper_returns_r=[1.0, -1.0],
        manual_returns_r=(3.0,),
        unattributed_returns_r=(4.0,),
    )
    ver_id = session.scalars(select(PaperPosition.strategy_version_id)).first()
    assert ver_id is not None
    assert sorted(closed_paper_r_multiples(session, ver_id)) == [-1.0, 1.0]


def test_mechanical_actor_literals_match_the_acceptance_paths() -> None:
    from signalforge.paper.auto_simulate import AUTO_SIM_ACTOR
    from signalforge.paper.options_auto_simulate import OPTIONS_AUTO_SIM_ACTOR

    assert hm.MECHANICAL_EQUITY_ACTOR == AUTO_SIM_ACTOR
    assert hm.MECHANICAL_OPTIONS_ACTOR == OPTIONS_AUTO_SIM_ACTOR


def test_every_persisted_action_fits_the_strategy_health_column() -> None:
    """``strategy_health.action`` is String(12); Postgres enforces it, and one
    over-long value would abort the whole monitor cycle (one write session)."""
    width = StrategyHealth.__table__.c.action.type.length
    for action in ("none", "downgrade", "disable", hm.INSUFFICIENT_ACTION):
        assert len(action) <= width, action


def _sibling_version(session: Session, version: str = "9.9.9") -> StrategyVersion:
    """A newer version of the seeded strategy with no paper trades at all."""
    ver = upsert_strategy_version(session, replace(STRAT.spec(), version=version))
    session.flush()
    return ver


def test_a_sibling_versions_insufficient_row_never_masks_a_real_downgrade(
    session: Session,
) -> None:
    """Version A downgrades; its 0-trade sibling (evaluated later in the same
    cycle — versions are walked in id order) writes an ``insufficient`` row.
    The per-name lookup must still show A's downgrade, and the per-version
    lookup must give each version its own row."""
    strat = _seed(
        session,
        status=StrategyStatus.PAPER_APPROVED,
        oos_expectancy_r=0.30,
        paper_returns_r=[-0.4, -0.6] * 12 + [-0.5],
    )
    sibling = _sibling_version(session)
    out = evaluate_strategy_health(session)

    assert [a.action for a in out] == ["downgrade", hm.INSUFFICIENT_ACTION]
    rows = session.scalars(select(StrategyHealth).order_by(StrategyHealth.id)).all()
    assert [r.action for r in rows] == ["downgrade", hm.INSUFFICIENT_ACTION]
    assert rows[1].strategy_version_id == sibling.id

    assert hm.latest_health_by_strategy(session)[strat.name].action == "downgrade"
    by_version = hm.latest_health_by_version(session)
    assert by_version[rows[0].strategy_version_id].action == "downgrade"
    assert by_version[sibling.id].action == hm.INSUFFICIENT_ACTION


def test_a_later_cycles_insufficient_row_never_masks_an_earlier_real_assessment(
    session: Session,
) -> None:
    """Placeholders keep arriving every cycle; the newest REAL assessment stays
    the one shown (with its own evaluated_at), never a newer placeholder."""
    strat = _seed(
        session,
        status=StrategyStatus.PAPER_APPROVED,
        oos_expectancy_r=0.30,
        paper_returns_r=[-0.4, -0.6] * 12 + [-0.5],
    )
    assert [a.action for a in evaluate_strategy_health(session)] == ["downgrade"]
    _sibling_version(session)
    # Now experimental; a disable bar it cannot reach -> A records "none".
    lenient = HealthMonitorConfig(disable_z=-1000.0)
    for _ in range(2):
        out = evaluate_strategy_health(session, config=lenient)
        assert [a.action for a in out] == ["none", hm.INSUFFICIENT_ACTION]

    newest = session.scalars(select(StrategyHealth).order_by(StrategyHealth.id.desc())).first()
    assert newest is not None and newest.action == hm.INSUFFICIENT_ACTION
    latest = hm.latest_health_by_strategy(session)[strat.name]
    assert latest.action == "none"
    assert latest.id == max(
        r.id for r in session.scalars(select(StrategyHealth)) if r.action == "none"
    )
