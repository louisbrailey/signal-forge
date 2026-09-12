"""``signalforge options evaluate-promotion`` — the dry run, the refusals, the look.

Nothing here contacts a provider: the dataset is the synthetic one in
``tests/research/options_evidence_support.py``.
"""

from __future__ import annotations

import inspect

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from typer.testing import CliRunner

from signalforge.cli import app
from signalforge.db.models import (
    DataSnapshot,
    StrategyPromotionEvaluation,
    StrategySealedTest,
)
from tests.research.options_evidence_support import (
    WINDOW_END,
    WINDOW_START,
    seed_coverage_run,
    seed_everything,
    seed_snapshot,
)

runner = CliRunner()

_ARGS = (
    "options",
    "evaluate-promotion",
    "--strategy",
    "options_short_vertical.medium_swing",
)


def _window_args() -> list[str]:
    return [
        "--since",
        WINDOW_START.isoformat(),
        "--until",
        WINDOW_END.isoformat(),
        "--sealed-days",
        "30",
    ]


def test_unknown_strategy_is_refused(session: Session) -> None:
    seed_everything(session)
    res = runner.invoke(
        app,
        [
            "options",
            "evaluate-promotion",
            "--strategy",
            "nope",
            "--snapshot-key",
            "options_w3b_test",
        ],
    )
    assert res.exit_code == 2
    assert "unknown options strategy" in res.output


def test_missing_snapshot_is_refused(session: Session) -> None:
    seed_everything(session)
    res = runner.invoke(app, [*_ARGS, "--snapshot-key", "does-not-exist", *_window_args()])
    assert res.exit_code == 2
    assert "no DataSnapshot with key" in res.output


def test_an_unscoped_snapshot_is_refused(session: Session) -> None:
    seed_everything(session)
    snap = DataSnapshot(
        key="equity_only",
        symbols_json=["SPY"],
        description="no options scope",
        source_note="SIMULATED",
    )
    session.add(snap)
    session.commit()
    res = runner.invoke(app, [*_ARGS, "--snapshot-key", "equity_only", *_window_args()])
    assert res.exit_code == 2
    assert "carries no options_scope_json" in res.output


def test_coverage_below_the_floor_refuses_and_exits_non_zero(session: Session) -> None:
    """No cycle-backfill run at all: gate 0.c/0.d have no coverage to read."""
    snap = seed_snapshot(session, ["SPY"], key="no_coverage_snapshot")
    session.commit()
    res = runner.invoke(app, [*_ARGS, "--snapshot-key", "no_coverage_snapshot", *_window_args()])
    assert res.exit_code == 2
    assert "REFUSED" in res.output
    assert "no options cycle-backfill run" in res.output
    assert snap.key in res.output or "DRY RUN" in res.output


def test_a_thin_backfill_is_refused_by_the_preflight(session: Session) -> None:
    seed_snapshot(session, ["SPY"], key="thin_coverage_snapshot")
    seed_coverage_run(
        session, ["SPY"], cycles_total=10, cycles_covered=4, bars_written=10, sessions_expected=100
    )
    session.commit()
    res = runner.invoke(app, [*_ARGS, "--snapshot-key", "thin_coverage_snapshot", *_window_args()])
    assert res.exit_code == 2
    assert "below gate 0.c's pre-registered floor" in res.output
    assert "below gate 0.d's pre-registered floor" in res.output


def test_confirm_refuses_while_the_worker_holds_the_write_lock(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed_everything(session)
    import signalforge.worker_lock as wl

    monkeypatch.setattr(wl, "worker_lock_holder", lambda path=None: "12345")
    res = runner.invoke(
        app, [*_ARGS, "--snapshot-key", "options_w3b_test", "--confirm", *_window_args()]
    )
    assert res.exit_code == 2
    assert "holds the write lock" in res.output
    assert (
        "no evidence was assembled, no row was written and no sealed look was spent" in res.output
    )
    session.expire_all()
    assert session.scalar(select(func.count()).select_from(StrategySealedTest)) == 0
    assert session.scalar(select(func.count()).select_from(StrategyPromotionEvaluation)) == 0


def test_confirm_without_the_grid_is_refused_before_anything_is_assembled(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ruling R-2: a sealed look may not be spent on an automatic gate-5 failure."""
    seed_everything(session)
    import signalforge.worker_lock as wl

    monkeypatch.setattr(wl, "worker_lock_holder", lambda path=None: None)
    res = runner.invoke(
        app, [*_ARGS, "--snapshot-key", "options_w3b_test", "--confirm", *_window_args()]
    )
    assert res.exit_code == 2
    assert "--confirm without --grid" in res.output
    session.expire_all()
    assert session.scalar(select(func.count()).select_from(StrategySealedTest)) == 0
    assert session.scalar(select(func.count()).select_from(StrategyPromotionEvaluation)) == 0


def test_dry_run_prints_the_ladder_and_writes_nothing(session: Session) -> None:
    seed_everything(session, ["SPY"])
    res = runner.invoke(app, [*_ARGS, "--snapshot-key", "options_w3b_test", *_window_args()])
    assert "DRY RUN — no evaluation row, no sealed test, no look" in res.output
    assert "0.a. data_availability_window" in res.output
    assert "clustered CI (underlying, expiry cycle)" in res.output
    assert "sealed looks: none" in res.output
    assert "SIMULATION ONLY" in res.output
    session.expire_all()
    assert session.scalar(select(func.count()).select_from(StrategySealedTest)) == 0
    assert session.scalar(select(func.count()).select_from(StrategyPromotionEvaluation)) == 0


def test_the_equity_evaluate_promotion_command_is_untouched() -> None:
    """W3b adds a SIBLING command; the equity one keeps its exact parameter set.

    ``cli.py`` is a shared module, so the additive rule is asserted rather than
    asserted-in-prose: a new option on the equity command would change what a
    stored disposition's reproduction line means.
    """
    from signalforge.cli import evaluate_promotion_cmd

    assert list(inspect.signature(evaluate_promotion_cmd).parameters) == [
        "strategy",
        "symbols",
        "since",
        "until",
        "dataset",
        "snapshot_key",
    ]


def test_the_options_command_is_registered_under_the_options_group() -> None:
    from signalforge.cli import options_app

    names = {c.name or c.callback.__name__ for c in options_app.registered_commands}
    assert "evaluate-promotion" in names
    # and NOT on the top-level app, where it would shadow the equity command
    top = {c.name for c in app.registered_commands if c.name}
    assert "evaluate-promotion" in top  # the equity one
    assert len([c for c in app.registered_commands if c.name == "evaluate-promotion"]) == 1
