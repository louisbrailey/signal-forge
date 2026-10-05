"""Per-snapshot coverage pre-flight and ``signalforge options snapshot``.

The pre-flight asks gate 0.c's and 0.d's floors of the pool of the SNAPSHOT'S
underlyings, each read from the cycle-backfill run that fetched it — not of
whichever run is newest.  Nothing here contacts a provider: every run row is
synthetic (``tests/research/options_evidence_support.py``), and the numbers are
counts and fractions only.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from typer.testing import CliRunner

from signalforge.cli import app
from signalforge.config.research import OptionsEvaluationConfig
from signalforge.data.options_backfill import coverage_summary
from signalforge.db.models import DataSnapshot, StrategySealedTest
from signalforge.db.types import utcnow
from signalforge.research.options_evidence import (
    coverage_preflight,
    dataset_snapshot_coverage,
    snapshot_options_coverage,
)
from signalforge.research.options_gates import OptionsGateThresholds
from signalforge.research.options_scope import (
    build_options_scope,
    canonical_options_snapshot_key,
    options_scope_hash,
)
from tests.research.options_evidence_support import (
    WINDOW_END,
    WINDOW_START,
    seed_coverage_run,
    seed_snapshot,
)

runner = CliRunner()

INDEX = ["SPY", "QQQ", "IWM"]
STOCKS = ["AAPL", "XLE"]


def _seed_stage_a_then_failing_stage_b(session: Session) -> tuple[int, int]:
    """An older run whose index ETFs pass both floors, then a NEWER run of
    stocks that fail both — the shape of the real Stage A / Stage B backfill."""
    now = utcnow()
    stage_a = seed_coverage_run(
        session,
        INDEX,
        cycles_total=10,
        cycles_covered=10,
        bars_written=900,
        sessions_expected=1000,
        started_at=now - timedelta(days=3),
    )
    stage_b = seed_coverage_run(
        session,
        STOCKS,
        cycles_total=10,
        cycles_covered=4,
        bars_written=600,
        sessions_expected=1000,
        started_at=now,
    )
    session.commit()
    return stage_a.id, stage_b.id


def _window() -> list[str]:
    return ["--since", WINDOW_START.isoformat(), "--until", WINDOW_END.isoformat()]


@pytest.fixture
def no_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    import signalforge.scheduler as sched
    import signalforge.worker_lock as wl

    monkeypatch.setattr(wl, "worker_lock_holder", lambda path=None: None)
    monkeypatch.setattr(sched, "other_live_worker", lambda: None)


# --------------------------------------------------------------------------- #
# the floors are the pre-registered ones — this change moved neither
# --------------------------------------------------------------------------- #
def test_the_coverage_floors_are_unchanged(session: Session) -> None:
    ev = OptionsEvaluationConfig()
    assert ev.gate_0c_cycles_bracket == 0.90
    assert ev.gate_0d_session_bars == 0.80
    assert OptionsGateThresholds().bar_continuity_min == 0.80
    scope = build_options_scope(coverage_summary(seed_coverage_run(session, ["SPY"])))
    assert scope["coverage_thresholds"] == {
        "gate_0c_cycles_bracket": 0.90,
        "gate_0d_session_bars": 0.80,
    }


# --------------------------------------------------------------------------- #
# the pre-flight judges the snapshot's underlyings
# --------------------------------------------------------------------------- #
def test_an_index_only_snapshot_passes_although_a_newer_run_of_stocks_fails(
    session: Session,
) -> None:
    stage_a, _ = _seed_stage_a_then_failing_stage_b(session)
    cov = snapshot_options_coverage(
        session, INDEX, window_start=WINDOW_START, window_end=WINDOW_END
    )
    pre = coverage_preflight(cov)
    assert pre.passed, pre.reasons
    assert pre.coverage_run_ids == (stage_a,)
    assert sorted(pre.underlyings) == sorted(INDEX)
    assert pre.bracket_fraction == pytest.approx(1.0)
    assert pre.bar_continuity_fraction == pytest.approx(0.9)
    assert [row[0] for row in pre.per_underlying] == sorted(INDEX)


def test_a_snapshot_including_a_failing_stock_is_refused(session: Session) -> None:
    stage_a, stage_b = _seed_stage_a_then_failing_stage_b(session)
    cov = snapshot_options_coverage(
        session, [*INDEX, "AAPL"], window_start=WINDOW_START, window_end=WINDOW_END
    )
    pre = coverage_preflight(cov)
    assert not pre.passed
    # 3 x 10/10 + 1 x 4/10 = 34/40 = 0.85 < 0.90; the stock spans a second run.
    assert pre.bracket_fraction == pytest.approx(34 / 40)
    assert any("below gate 0.c's pre-registered floor 0.90" in r for r in pre.reasons)
    assert pre.coverage_run_ids == (stage_a, stage_b)
    assert pre.coverage_run_id is None  # more than one run: no single id to claim


def test_the_failing_stocks_alone_fail_both_floors(session: Session) -> None:
    _seed_stage_a_then_failing_stage_b(session)
    pre = coverage_preflight(
        snapshot_options_coverage(session, STOCKS, window_start=WINDOW_START, window_end=WINDOW_END)
    )
    assert not pre.passed
    assert any("gate 0.c" in r for r in pre.reasons)
    assert any("gate 0.d" in r for r in pre.reasons)


def test_the_newest_run_for_an_underlying_is_read_not_a_better_older_one(
    session: Session,
) -> None:
    """A worse, newer run of the same underlying must not be hidden by an older
    passing one: per underlying the read is 'newest', never 'best'."""
    now = utcnow()
    seed_coverage_run(session, ["SPY"], started_at=now - timedelta(days=2))
    seed_coverage_run(
        session,
        ["SPY"],
        cycles_total=10,
        cycles_covered=3,
        bars_written=100,
        sessions_expected=1000,
        started_at=now,
    )
    session.commit()
    pre = coverage_preflight(
        snapshot_options_coverage(
            session, ["SPY"], window_start=WINDOW_START, window_end=WINDOW_END
        )
    )
    assert not pre.passed
    assert pre.bracket_fraction == pytest.approx(0.3)


def test_an_underlying_with_no_recorded_coverage_is_refused(session: Session) -> None:
    _seed_stage_a_then_failing_stage_b(session)
    pre = coverage_preflight(
        snapshot_options_coverage(
            session, [*INDEX, "XOM"], window_start=WINDOW_START, window_end=WINDOW_END
        )
    )
    assert not pre.passed
    assert any("records coverage for XOM" in r for r in pre.reasons)


def test_an_underlying_requested_by_a_run_that_recorded_no_cycles_fails(
    session: Session,
) -> None:
    run = seed_coverage_run(session, ["SPY", "QQQ"])
    gaps = dict(run.gaps_json)
    gaps.pop("QQQ")
    run.gaps_json = gaps
    session.commit()
    pre = coverage_preflight(
        snapshot_options_coverage(
            session, ["QQQ"], window_start=WINDOW_START, window_end=WINDOW_END
        )
    )
    assert not pre.passed
    assert pre.bracket_fraction == 0.0


def test_runs_on_different_listing_bases_cannot_pool_into_one_dataset(session: Session) -> None:
    now = utcnow()
    seed_coverage_run(session, ["SPY"], started_at=now - timedelta(days=1))
    other = seed_coverage_run(session, ["QQQ"], started_at=now)
    gaps = dict(other.gaps_json)
    gaps["__run__"] = {**gaps["__run__"], "strike_listing_basis": "first_bar_proxy"}
    other.gaps_json = gaps
    session.commit()
    pre = coverage_preflight(
        snapshot_options_coverage(
            session, ["SPY", "QQQ"], window_start=WINDOW_START, window_end=WINDOW_END
        )
    )
    assert not pre.passed
    assert any("disagree on strike_listing_basis" in r for r in pre.reasons)


def test_restricted_continuity_uses_per_cycle_bars_and_never_the_run_total(
    session: Session,
) -> None:
    """The run-level counter cannot be apportioned to an underlying; inflating it
    must not move a restricted summary."""
    run = seed_coverage_run(session, INDEX, bars_written=700, sessions_expected=1000)
    run.bars_written = 10_000_000
    session.commit()
    part = coverage_summary(run, underlyings=["SPY"])
    assert part.underlyings == ("SPY",)
    assert (part.bars_written, part.sessions_expected) == (700, 1000)
    assert part.bar_continuity_fraction == pytest.approx(0.7)
    assert not coverage_preflight(
        snapshot_options_coverage(session, INDEX, window_start=WINDOW_START, window_end=WINDOW_END)
    ).passed


def test_a_snapshot_is_judged_on_the_runs_its_scope_recorded(session: Session) -> None:
    stage_a, _ = _seed_stage_a_then_failing_stage_b(session)
    snap = seed_snapshot(session, INDEX, key="pinned_index_snapshot")
    snap.options_scope_json = {**snap.options_scope_json, "ingestion_run_ids": [stage_a]}
    session.commit()
    cov = dataset_snapshot_coverage(session, snap, window_start=WINDOW_START, window_end=WINDOW_END)
    assert cov.run_ids == (stage_a,)
    assert coverage_preflight(cov).passed

    snap.options_scope_json = {**snap.options_scope_json, "ingestion_run_ids": [987654]}
    session.commit()
    gone = coverage_preflight(
        dataset_snapshot_coverage(session, snap, window_start=WINDOW_START, window_end=WINDOW_END)
    )
    assert not gone.passed  # the recorded run is absent: fail closed, never fall back


# --------------------------------------------------------------------------- #
# evaluate-promotion uses the per-snapshot pre-flight
# --------------------------------------------------------------------------- #
def _coverage_refusals(output: str) -> bool:
    return "pre-registered floor" in output or "records coverage for" in output


def test_evaluate_promotion_does_not_refuse_an_index_snapshot_on_the_stocks_run(
    session: Session,
) -> None:
    _seed_stage_a_then_failing_stage_b(session)
    seed_snapshot(session, INDEX, key="index_only_snapshot")
    session.commit()
    res = runner.invoke(
        app,
        [
            "options",
            "evaluate-promotion",
            "--strategy",
            "options_short_vertical.medium_swing",
            "--snapshot-key",
            "index_only_snapshot",
            *_window(),
            "--sealed-days",
            "30",
        ],
    )
    assert not _coverage_refusals(res.output), res.output


def test_evaluate_promotion_refuses_a_snapshot_holding_a_failing_stock(session: Session) -> None:
    _seed_stage_a_then_failing_stage_b(session)
    seed_snapshot(session, [*INDEX, "AAPL"], key="index_plus_stock_snapshot")
    session.commit()
    res = runner.invoke(
        app,
        [
            "options",
            "evaluate-promotion",
            "--strategy",
            "options_short_vertical.medium_swing",
            "--snapshot-key",
            "index_plus_stock_snapshot",
            *_window(),
            "--sealed-days",
            "30",
        ],
    )
    assert res.exit_code == 2
    assert "below gate 0.c's pre-registered floor" in res.output


# --------------------------------------------------------------------------- #
# `signalforge options snapshot`
# --------------------------------------------------------------------------- #
def _snapshot_count(session: Session) -> int:
    session.rollback()  # end the read transaction so another connection's commit is visible
    return int(session.scalar(select(func.count()).select_from(DataSnapshot)) or 0)


def _canonical_key(session: Session, symbols: list[str]) -> str:
    from signalforge.research.options_scope import (
        DEFAULT_FILL_TIMING_BASIS,
        DEFAULT_SPREAD_MODEL_ID,
    )

    cov = snapshot_options_coverage(
        session, symbols, window_start=WINDOW_START, window_end=WINDOW_END
    )
    assert cov.summary is not None
    scope = build_options_scope(
        cov.summary,
        spread_model_id=DEFAULT_SPREAD_MODEL_ID,
        spread_multiplier=1.0,
        fill_timing_basis=DEFAULT_FILL_TIMING_BASIS,
        ingestion_run_ids=cov.run_ids,
    )
    key = canonical_options_snapshot_key(scope)
    assert key.endswith(options_scope_hash(scope)[:10])
    return key


def test_snapshot_dry_run_is_the_default_and_writes_nothing(
    session: Session, no_worker: None
) -> None:
    _seed_stage_a_then_failing_stage_b(session)
    key = _canonical_key(session, INDEX)
    assert key.startswith(f"options_idx3_massive_{WINDOW_START}_{WINDOW_END}_")
    before = _snapshot_count(session)
    res = runner.invoke(app, ["options", "snapshot", "--symbols", "SPY,QQQ,IWM", *_window()])
    assert res.exit_code == 0, res.output
    assert "DRY RUN" in res.output
    assert key in res.output
    assert "options_scope_hash" in res.output and "options_config_hash" in res.output
    assert _snapshot_count(session) == before


def test_snapshot_confirm_writes_one_scoped_row_and_is_idempotent(
    session: Session, no_worker: None
) -> None:
    stage_a, _ = _seed_stage_a_then_failing_stage_b(session)
    key = _canonical_key(session, INDEX)
    before = _snapshot_count(session)
    args = ["options", "snapshot", "--symbols", "SPY,QQQ,IWM", *_window(), "--confirm"]
    res = runner.invoke(app, args)
    assert res.exit_code == 0, res.output
    assert _snapshot_count(session) == before + 1
    snap = session.scalar(select(DataSnapshot).where(DataSnapshot.key == key))
    assert snap is not None
    assert sorted(snap.symbols_json) == sorted(INDEX)
    scope = snap.options_scope_json
    assert scope["underlyings"] == sorted(INDEX)
    assert scope["ingestion_run_ids"] == [stage_a]
    assert scope["cycles"] == 30
    assert scope["coverage_thresholds"] == {
        "gate_0c_cycles_bracket": 0.90,
        "gate_0d_session_bars": 0.80,
    }
    assert scope["options_config_hash"] == OptionsEvaluationConfig().options_config_hash
    # creating a snapshot spends no look
    assert int(session.scalar(select(func.count()).select_from(StrategySealedTest)) or 0) == 0

    again = runner.invoke(app, args)
    assert again.exit_code == 0, again.output
    assert "already exists" in again.output and "nothing to write" in again.output
    assert _snapshot_count(session) == before + 1


def test_snapshot_refuses_a_set_that_includes_a_failing_stock(
    session: Session, no_worker: None
) -> None:
    _seed_stage_a_then_failing_stage_b(session)
    before = _snapshot_count(session)
    res = runner.invoke(
        app, ["options", "snapshot", "--symbols", "SPY,QQQ,IWM,AAPL", *_window(), "--confirm"]
    )
    assert res.exit_code == 2
    assert "below gate 0.c's pre-registered floor" in res.output
    assert "no DataSnapshot row was written" in res.output
    assert _snapshot_count(session) == before


def test_snapshot_refuses_an_existing_key_with_different_symbols_or_scope(
    session: Session, no_worker: None
) -> None:
    _seed_stage_a_then_failing_stage_b(session)
    key = _canonical_key(session, INDEX)
    # the same key, already taken by a different symbol set
    seed_snapshot(session, ["SPY"], key=key)
    session.commit()
    res = runner.invoke(
        app, ["options", "snapshot", "--symbols", "SPY,QQQ,IWM", *_window(), "--confirm"]
    )
    assert res.exit_code == 2
    assert "already exists" in res.output and "different symbols" in res.output

    # the same key and symbols, a different scope
    existing = session.scalar(select(DataSnapshot).where(DataSnapshot.key == key))
    assert existing is not None
    existing.symbols_json = sorted(INDEX)
    session.commit()
    res = runner.invoke(
        app, ["options", "snapshot", "--symbols", "SPY,QQQ,IWM", *_window(), "--confirm"]
    )
    assert res.exit_code == 2
    assert "different options scope" in res.output


def test_snapshot_refuses_a_key_that_does_not_carry_the_scope_hash(
    session: Session, no_worker: None
) -> None:
    _seed_stage_a_then_failing_stage_b(session)
    before = _snapshot_count(session)
    res = runner.invoke(
        app,
        ["options", "snapshot", "--symbols", "SPY,QQQ,IWM", *_window(), "--key", "my_options"],
    )
    assert res.exit_code == 2
    assert "does not carry this scope's hash" in res.output
    assert _snapshot_count(session) == before


def test_snapshot_refuses_a_window_the_runs_were_not_fetched_for(
    session: Session, no_worker: None
) -> None:
    _seed_stage_a_then_failing_stage_b(session)
    res = runner.invoke(
        app,
        [
            "options",
            "snapshot",
            "--symbols",
            "SPY,QQQ,IWM",
            "--since",
            (WINDOW_START + timedelta(days=30)).isoformat(),
            "--until",
            WINDOW_END.isoformat(),
        ],
    )
    assert res.exit_code == 2
    assert "not the requested" in res.output


def test_snapshot_confirm_refuses_while_a_worker_is_live(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    import signalforge.scheduler as sched
    import signalforge.worker_lock as wl

    _seed_stage_a_then_failing_stage_b(session)
    before = _snapshot_count(session)
    monkeypatch.setattr(wl, "worker_lock_holder", lambda path=None: "12345")
    monkeypatch.setattr(sched, "other_live_worker", lambda: None)
    args = ["options", "snapshot", "--symbols", "SPY,QQQ,IWM", *_window()]
    res = runner.invoke(app, [*args, "--confirm"])
    assert res.exit_code == 2
    assert "stop the worker first" in res.output
    assert _snapshot_count(session) == before
    # a dry run reads only, so a live worker does not block it
    assert runner.invoke(app, args).exit_code == 0

    monkeypatch.setattr(wl, "worker_lock_holder", lambda path=None: None)
    monkeypatch.setattr(sched, "other_live_worker", lambda: "a live scheduler heartbeat exists")
    res = runner.invoke(app, [*args, "--confirm"])
    assert res.exit_code == 2
    assert "live scheduler heartbeat" in res.output
    assert _snapshot_count(session) == before


def test_snapshot_refuses_an_unknown_run_id(session: Session, no_worker: None) -> None:
    _seed_stage_a_then_failing_stage_b(session)
    res = runner.invoke(
        app, ["options", "snapshot", "--symbols", "SPY,QQQ,IWM", *_window(), "--run", "987654"]
    )
    assert res.exit_code == 2
    assert "records coverage for" in res.output
