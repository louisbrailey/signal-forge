"""The options branches of the two R-computing readers (D3 §7.3), and the proof
that neither of them moved the equity numbers.

D3 §7.3's argument, restated so this file explains itself: options structures
never write a ``paper_position`` row, so ``health_monitor`` and
``paper_probation`` are structurally blind to them by default — and blind means
an options strategy that underperforms is **never downgraded**, a fail-open in
the one place this system must fail closed. The branch therefore has to be
written, behind a positive predicate, using the options definition of R
(max-loss-normalised), with the clamp reported rather than absorbed.

The first test is the one that matters most on this box: on a database with no
options rows, both readers produce exactly what they produced before the branch
existed, and the options reader is not even called.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

import signalforge.research.health_monitor as hm
import signalforge.research.paper_probation as pp
from signalforge.db.models import (
    BacktestMetric,
    BacktestRun,
    Instrument,
    JobRun,
    OptionsPosition,
    OptionsReconcileReport,
    PaperAccount,
    PaperPosition,
    Strategy,
    StrategyVersion,
)
from signalforge.domain import Horizon, PositionSide, StrategyStatus

EQUITY_ACCOUNT = "default"
OPTIONS_ACCOUNT = "options"


def _version(
    session: Session, *, name: str, status: StrategyStatus = StrategyStatus.PAPER_APPROVED
) -> StrategyVersion:
    strat = Strategy(name=name, horizon=Horizon.SHORT_SWING, status=status)
    session.add(strat)
    session.flush()
    ver = StrategyVersion(
        strategy_id=strat.id, version="0.1.0", status=status, spec_json={}, git_sha="fixture"
    )
    session.add(ver)
    session.flush()
    return ver


def _oos(session: Session, ver: StrategyVersion, expectancy_r: float) -> None:
    run = BacktestRun(
        strategy_version_id=ver.id,
        params_json={},
        date_start=date(2023, 1, 1),
        date_end=date(2024, 1, 1),
        config_hash="test",
    )
    session.add(run)
    session.flush()
    session.add(
        BacktestMetric(
            run_id=run.id,
            segment="all",
            phase="out_of_sample",
            metrics_json={"expectancy_r": expectancy_r, "n_trades": 200},
        )
    )
    session.flush()


def _equity_trades(session: Session, ver: StrategyVersion, r_values: list[float]) -> None:
    """entry 100, stop 98 -> $2/share risk x 10 shares -> $20 of R per trade."""
    acct = session.scalar(select(PaperAccount).where(PaperAccount.name == EQUITY_ACCOUNT))
    if acct is None:
        acct = PaperAccount(name=EQUITY_ACCOUNT, initial_cash=Decimal("10000"), cash=Decimal("1"))
        session.add(acct)
        session.flush()
    inst = Instrument(symbol=f"E{ver.id}", instrument_type="stock")
    session.add(inst)
    session.flush()
    opened = datetime(2024, 1, 2, tzinfo=UTC)
    for i, r in enumerate(r_values):
        session.add(
            PaperPosition(
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
        )
    session.flush()


def _options_structures(
    session: Session,
    ver: StrategyVersion,
    r_values: list[float],
    *,
    r_dollars: float = 200.0,
    closed: bool = True,
) -> PaperAccount:
    acct = session.scalar(select(PaperAccount).where(PaperAccount.name == OPTIONS_ACCOUNT))
    if acct is None:
        acct = PaperAccount(
            name=OPTIONS_ACCOUNT, initial_cash=Decimal("25000"), cash=Decimal("25000")
        )
        session.add(acct)
        session.flush()
    inst = Instrument(symbol="SPY", instrument_type="etf")
    session.add(inst)
    session.flush()
    opened = datetime(2026, 1, 5, tzinfo=UTC)
    for i, r in enumerate(r_values):
        session.add(
            OptionsPosition(
                account_id=acct.id,
                strategy_version_id=ver.id,
                underlying_instrument_id=inst.id,
                underlying_symbol="SPY",
                structure_type="vertical_credit",
                contracts=1,
                entry_net_premium=Decimal("50"),
                r_dollars=Decimal(str(r_dollars)),
                collateral_reserved=Decimal(str(r_dollars)),
                expiration_date=date(2026, 3, 20),
                opened_at=opened + timedelta(days=i),
                closed_at=(opened + timedelta(days=i, hours=6)) if closed else None,
                realized_pnl=Decimal(str(round(r * r_dollars, 6))),
                pnl_r=r,
                r_clamped=r < -1.0,
            )
        )
    session.flush()
    return acct


# --------------------------------------------------------------------------- #
# The equity path, proved unchanged
# --------------------------------------------------------------------------- #
def test_the_equity_path_is_unchanged_on_a_database_with_no_options_rows(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Both readers, on a DB whose options tables are empty.

    The options reader is replaced by a landmine in BOTH modules first: if either
    path enters the branch for an equity family, the test fails with that message
    instead of quietly returning the same answer for the wrong reason.
    """

    def _landmine(*_a: object, **_k: object) -> object:
        raise AssertionError("the options branch must not run for an equity family")

    ver = _version(session, name="trend_continuation")
    _oos(session, ver, 0.30)
    _equity_trades(session, ver, [0.5, -1.0, 1.5, -1.0, 2.0] * 5)  # 25 trades, mean +0.4R
    session.flush()

    monkeypatch.setattr(hm, "closed_options_r_multiples", _landmine)
    monkeypatch.setattr(pp, "closed_options_r_multiples", _landmine)

    assert hm.is_options_strategy_version(session, ver.id) is False

    out = hm.evaluate_strategy_health(session)
    assessed = next(a for a in out if a.strategy == "trend_continuation")
    assert assessed.n_paper_trades == 25
    assert assessed.paper_expectancy_r == 0.4
    assert assessed.window_label == "last_25_paper_trades"
    assert assessed.action == "none"  # positive expectancy is never downgraded

    ctx = pp.paper_probation_context(session)
    row = next(s for s in ctx["strategies"] if s["strategy_key"] == "trend_continuation")
    assert row["options"] is None
    assert row["paper"]["n_trades"] == 25
    assert row["paper"]["realized_expectancy_r"] == 0.4
    assert row["expected_oos_expectancy_r"] == 0.30
    assert row["paper"]["shortfall_vs_expected_r"] == 0.1

    # the StrategyHealth note is the equity sentence and nothing else
    note = pp.latest_health_by_strategy(session)["trend_continuation"].note
    assert note == "paper +0.400R vs backtest +0.300R over 25 trades (z=+0.40)"


def test_an_equity_version_is_not_an_options_family_even_beside_an_options_one(
    session: Session,
) -> None:
    equity = _version(session, name="trend_continuation")
    options = _version(session, name="options_short_vertical.position")
    _options_structures(session, options, [0.5])
    session.flush()
    assert hm.is_options_strategy_version(session, equity.id) is False
    assert hm.is_options_strategy_version(session, options.id) is True
    assert hm.closed_options_r_multiples(session, equity.id).r_multiples == []


# --------------------------------------------------------------------------- #
# The options branch itself
# --------------------------------------------------------------------------- #
def test_r_is_max_loss_normalised_and_clamped_at_minus_one(session: Session) -> None:
    ver = _version(session, name="options_short_vertical.position")
    # -1.28R is reachable: the intrinsic floor on a forced close, plus exit costs
    # on a structure closed at max loss (D3 §5.4).
    _options_structures(session, ver, [0.5, -1.28, 0.5], r_dollars=200.0)
    session.flush()

    series = hm.closed_options_r_multiples(session, ver.id)
    assert series.r_multiples == pytest.approx([0.5, -1.0, 0.5])
    assert series.clamped == 1
    assert series.unclamped_min == pytest.approx(-1.28)
    assert "1 clamped at -1R, unclamped min -1.280" in series.note()


def test_an_open_structure_is_not_in_the_series(session: Session) -> None:
    ver = _version(session, name="options_short_vertical.position")
    _options_structures(session, ver, [0.5], closed=False)
    session.flush()
    assert hm.closed_options_r_multiples(session, ver.id).r_multiples == []
    assert hm.is_options_strategy_version(session, ver.id) is True  # still the family


def test_the_health_monitor_downgrades_an_options_family_on_its_own_evidence(
    session: Session,
) -> None:
    """The fail-open D3 §7.3 names: without the branch this version has ZERO
    paper trades, is recorded ``insufficient_data`` forever, and is never
    downgraded no matter how badly the structures do."""
    ver = _version(session, name="options_short_vertical.position")
    _oos(session, ver, 0.30)
    _options_structures(session, ver, [-0.4, -0.6] * 12 + [-0.5])  # 25 structures, mean -0.5R
    session.flush()

    out = hm.evaluate_strategy_health(session)
    assessed = next(a for a in out if a.strategy == "options_short_vertical.position")
    assert assessed.n_paper_trades == 25
    assert assessed.paper_expectancy_r == pytest.approx(-0.5, abs=1e-3)
    assert assessed.action == "downgrade"
    assert assessed.to_status == "experimental"

    health = pp.latest_health_by_strategy(session)["options_short_vertical.position"]
    assert "25 closed options structure(s) included" in health.note
    assert "0 clamped at -1R" in health.note


def test_the_audit_row_carries_the_options_counters_only_when_they_apply(
    session: Session,
) -> None:
    from signalforge.db.models import AuditLog

    ver = _version(session, name="options_short_vertical.position")
    _oos(session, ver, 0.30)
    _options_structures(session, ver, [-0.4, -0.6] * 12 + [-0.5])
    session.flush()
    hm.evaluate_strategy_health(session)

    log = session.scalar(select(AuditLog).where(AuditLog.action == "strategy.downgrade"))
    assert log is not None
    assert log.after_json["n_options_structures"] == 25
    assert log.after_json["options_clamped_at_minus_1r"] == 0
    assert log.after_json["options_unclamped_min_r"] == pytest.approx(-0.6)


# --------------------------------------------------------------------------- #
# The probation options section
# --------------------------------------------------------------------------- #
def test_options_paper_status_on_a_deployment_that_never_opted_in(session: Session) -> None:
    s = pp.options_paper_status(session)
    assert s["exists"] is False
    assert s["account"] == "options"
    assert s["n_open"] == 0
    assert s["reconciliation"] is None
    assert s["eod_chain"]["enabled"] is False
    assert s["eod_chain"]["job"] == "options_paper_eod"
    assert s["eod_chain"]["last_run_at"] is None
    assert s["auto_simulate"] == {
        "setting_key": "auto_simulate_options_enabled",
        "enabled": False,
        "max_per_day": 0,
    }


def test_options_paper_status_reports_the_four_facts(session: Session) -> None:
    ver = _version(session, name="options_short_vertical.position")
    acct = _options_structures(session, ver, [0.5], closed=False)
    session.add(
        OptionsReconcileReport(
            account_id=acct.id,
            as_of=date(2026, 9, 10),
            clean=True,
            findings_json=[],
            collateral_reserved_observed=Decimal("200"),
            collateral_reserved_expected=Decimal("200"),
            open_structures=1,
        )
    )
    session.add(
        JobRun(
            name="options_paper_eod",
            started_at=datetime(2026, 9, 10, 22, 30, tzinfo=UTC),
            finished_at=datetime(2026, 9, 10, 22, 31, tzinfo=UTC),
            status="ok",
            detail="",
        )
    )
    session.flush()

    s = pp.options_paper_status(session, as_of=date(2026, 9, 12))
    assert s["exists"] is True and s["account"] == "options"
    assert s["n_open"] == 1
    assert s["open_structures"][0]["underlying"] == "SPY"
    assert s["reconciliation"]["as_of"] == "2026-09-10"
    assert s["reconciliation"]["clean"] is True
    assert s["reconciliation"]["age_days"] == 2  # stale, and visibly so
    assert s["eod_chain"]["last_run_status"] == "ok"
    assert s["eod_chain"]["hours_since_last_run"] is not None
    assert "SIMULATED" in s["notice"]


def test_the_probation_context_carries_the_options_block_for_an_options_family(
    session: Session,
) -> None:
    ver = _version(session, name="options_short_vertical.position")
    _oos(session, ver, 0.30)
    _options_structures(session, ver, [0.5, -1.28])
    session.flush()

    ctx = pp.paper_probation_context(session)
    row = next(s for s in ctx["strategies"] if s["strategy_key"].startswith("options_"))
    assert row["options"] == {
        "n_closed_structures": 2,
        "n_open_structures": 0,
        "realized_expectancy_r": -0.25,  # (0.5 + -1.0) / 2, on the CLAMPED series
        "clamped_at_minus_1r": 1,
        "unclamped_min_r": pytest.approx(-1.28),
    }
    # the equity block is still there, and still empty
    assert row["paper"]["n_trades"] == 0
    assert ctx["options_paper"]["exists"] is True


def test_the_probation_status_cli_prints_an_options_section(db_url: str) -> None:
    from typer.testing import CliRunner

    from signalforge.cli import app

    result = CliRunner().invoke(app, ["paper-probation-status"])
    assert result.exit_code == 0
    assert "options paper book (SIMULATED, separate account)" in result.stdout
    assert "DOES NOT EXIST" in result.stdout
    assert "reconciliation: NONE" in result.stdout
    assert "options_paper_eod: never run" in result.stdout
    assert "research.options.paper_eod_enabled: OFF" in result.stdout


def test_the_activation_preconditions_report_options_and_never_gate_on_it(db_url: str) -> None:
    from signalforge.cli import _activation_preconditions

    def _options_activation_rows_of(rows):
        return [r for r in rows if "options" in r[0]]

    checks = _activation_preconditions()
    labels = [label for label, _ok, _note in checks]
    assert any("options paper account" in label for label in labels)
    assert any("options collateral reconciliation" in label for label in labels)
    assert any("options_paper_eod" in label for label in labels)
    assert any("options open structures" in label for label in labels)
    # every options row is informational: it can never refuse the equity trial
    assert all(ok for _label, ok, _note in _options_activation_rows_of(checks))
    for label, ok, _note in checks:
        if "options" in label:
            assert ok is True, f"{label} must report, never gate"
