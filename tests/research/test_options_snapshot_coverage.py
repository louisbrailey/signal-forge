"""Per-snapshot coverage pre-flight and ``signalforge options snapshot``.

The pre-flight asks gate 0.c's and 0.d's floors of the pool of the SNAPSHOT'S
underlyings, each read from the cycle-backfill run that fetched it — not of
whichever run is newest.  Nothing here contacts a provider: every run row is
synthetic (``tests/research/options_evidence_support.py``), and the numbers are
counts and fractions only.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

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
    CoveragePreflight,
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
    stage_a, _ = _seed_stage_a_then_failing_stage_b(session)
    seed_snapshot(session, INDEX, key="index_only_snapshot", ingestion_run_ids=[stage_a])
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
    assert "ingestion_run_ids" not in res.output and "OR-0c" not in res.output, res.output


def test_evaluate_promotion_refuses_a_snapshot_holding_a_failing_stock(session: Session) -> None:
    stage_a, stage_b = _seed_stage_a_then_failing_stage_b(session)
    seed_snapshot(
        session,
        [*INDEX, "AAPL"],
        key="index_plus_stock_snapshot",
        ingestion_run_ids=[stage_a, stage_b],
    )
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


# --------------------------------------------------------------------------- #
# BLOCK 1 — a member a run merely requested is never pooled silently
# --------------------------------------------------------------------------- #
def _pooled(session: Session, symbols: list[str]) -> CoveragePreflight:
    return coverage_preflight(
        snapshot_options_coverage(
            session, symbols, window_start=WINDOW_START, window_end=WINDOW_END
        )
    )


def test_a_pool_with_a_member_that_has_no_cycle_records_is_refused(session: Session) -> None:
    """The fail-open probe: SPY 10/10 + QQQ requested but with no records used to
    PASS 1.0/1.0 for {SPY, QQQ}, because QQQ added nothing to either count."""
    run = seed_coverage_run(session, ["SPY", "QQQ"])
    gaps = dict(run.gaps_json)
    gaps.pop("QQQ")
    run.gaps_json = gaps
    session.commit()
    pre = _pooled(session, ["SPY", "QQQ"])
    # the pooled fractions still look perfect — which is exactly why it must refuse
    assert pre.bracket_fraction == pytest.approx(1.0)
    assert pre.bar_continuity_fraction == pytest.approx(1.0)
    assert not pre.passed
    assert any(r.startswith("QQQ was requested") and "recorded no" in r for r in pre.reasons)
    assert not any(r.startswith("SPY") for r in pre.reasons)
    assert "QQQ" in [row[0] for row in pre.members_below_floor]


def test_a_pool_with_an_empty_cycles_map_is_refused(session: Session) -> None:
    run = seed_coverage_run(session, ["SPY", "QQQ"])
    run.gaps_json = {**run.gaps_json, "QQQ": {"cycles": {}}}
    session.commit()
    pre = _pooled(session, ["SPY", "QQQ"])
    assert not pre.passed
    assert any(r.startswith("QQQ was requested") and "recorded no" in r for r in pre.reasons)
    # and asked for alone, the same member is refused by name too
    alone = _pooled(session, ["QQQ"])
    assert not alone.passed
    assert any(r.startswith("QQQ was requested") for r in alone.reasons)


def test_a_pool_with_a_member_the_run_lists_as_failed_is_refused(session: Session) -> None:
    """QQQ has partial cycle records AND is in symbols_failed.  20/20 + 9/9 pools
    to 1.0 — only the failure list says its records are incomplete."""
    run = seed_coverage_run(session, ["SPY", "QQQ"])
    gaps = dict(run.gaps_json)
    qqq_cycles = dict(gaps["QQQ"]["cycles"])
    qqq_cycles.pop(sorted(qqq_cycles)[-1])  # a cycle the failed pass never reached
    gaps["QQQ"] = {"cycles": qqq_cycles}
    run.gaps_json = gaps
    run.symbols_ok = ["SPY"]
    run.symbols_failed = {"QQQ": "pass ended: network"}
    run.status = "partial"
    session.commit()
    pre = _pooled(session, ["SPY", "QQQ"])
    assert pre.bracket_fraction == pytest.approx(1.0)
    assert not pre.passed
    assert any("QQQ is listed as FAILED" in r and "pass ended: network" in r for r in pre.reasons)
    # the healthy member alone, from the same run, is not tainted by it
    assert _pooled(session, ["SPY"]).passed


def test_a_member_with_cycles_but_no_expected_sessions_is_refused(session: Session) -> None:
    run = seed_coverage_run(session, ["SPY", "QQQ"])
    gaps = dict(run.gaps_json)
    gaps["QQQ"] = {
        "cycles": {
            k: {**v, "sessions_expected": 0, "bars_written": 0}
            for k, v in gaps["QQQ"]["cycles"].items()
        }
    }
    run.gaps_json = gaps
    session.commit()
    pre = _pooled(session, ["SPY", "QQQ"])
    assert not pre.passed
    assert any(r.startswith("QQQ has") and "zero expected sessions" in r for r in pre.reasons)


def test_a_bare_summary_listing_a_failed_underlying_is_refused(session: Session) -> None:
    run = seed_coverage_run(session, ["SPY", "QQQ"])
    run.symbols_failed = {"QQQ": "HTTP 500"}
    session.commit()
    pre = coverage_preflight(coverage_summary(run))
    assert not pre.passed
    assert any("lists QQQ as FAILED" in r for r in pre.reasons)


# --------------------------------------------------------------------------- #
# the evaluation reads ONLY the runs the snapshot recorded
# --------------------------------------------------------------------------- #
def test_a_snapshot_recording_no_ingestion_runs_is_refused_not_fallen_back(
    session: Session,
) -> None:
    _seed_stage_a_then_failing_stage_b(session)
    snap = seed_snapshot(session, INDEX, key="unpinned_index_snapshot")
    session.commit()
    cov = dataset_snapshot_coverage(session, snap, window_start=WINDOW_START, window_end=WINDOW_END)
    assert cov.summary is None and cov.run_ids == ()
    pre = coverage_preflight(cov)
    assert not pre.passed
    assert any("records no ingestion_run_ids" in r for r in pre.reasons)

    res = runner.invoke(
        app,
        [
            "options",
            "evaluate-promotion",
            "--strategy",
            "options_short_vertical.medium_swing",
            "--snapshot-key",
            "unpinned_index_snapshot",
            *_window(),
            "--sealed-days",
            "30",
        ],
    )
    assert res.exit_code == 2
    assert "records no ingestion_run_ids" in res.output


def test_ingestion_run_ids_are_outside_the_scope_hash_so_the_command_compares_them(
    session: Session, no_worker: None
) -> None:
    """``ingestion_run_ids`` is provenance, not identity (options_scope._UNHASHED_KEYS),
    so the scope comparison cannot see a changed coverage basis.  The command
    therefore compares the recorded ids itself rather than report 'nothing to
    write' over a snapshot pinned to other runs."""
    stage_a, _ = _seed_stage_a_then_failing_stage_b(session)
    args = ["options", "snapshot", "--symbols", "SPY,QQQ,IWM", *_window(), "--confirm"]
    assert runner.invoke(app, args).exit_code == 0
    before = _snapshot_count(session)
    newer = seed_coverage_run(session, INDEX, bars_written=900, sessions_expected=1000)
    session.commit()
    assert newer.id != stage_a

    res = runner.invoke(app, args)
    assert res.exit_code == 2, res.output
    assert "is pinned to ingestion run(s)" in res.output
    assert _snapshot_count(session) == before

    pinned = runner.invoke(app, [*args, "--run", str(stage_a)])
    assert pinned.exit_code == 0, pinned.output
    assert "nothing to write" in pinned.output


# --------------------------------------------------------------------------- #
# BLOCK 2 — OR-0c: pooled is computed, per-symbol is disclosed, --confirm waits
# --------------------------------------------------------------------------- #
def _seed_pool_passes_but_qqq_is_below_the_bracket_floor(session: Session) -> int:
    """SPY 20/20, QQQ 17/20 (0.85 < 0.90): pooled 37/40 = 0.925 passes."""
    run = seed_coverage_run(
        session,
        ["SPY", "QQQ"],
        cycles_total=20,
        cycles_covered=20,
        sessions_expected=2000,
        bars_written=2000,
    )
    gaps = dict(run.gaps_json)
    qqq = {k: dict(v) for k, v in gaps["QQQ"]["cycles"].items()}
    for k in sorted(qqq)[-3:]:
        qqq[k]["excluded"] = "ladder_incomplete"
    gaps["QQQ"] = {"cycles": qqq}
    run.gaps_json = gaps
    session.commit()
    return int(run.id)


_OR0C_WARNING = "OR-0c is open: pooled reading passes, per-symbol reading fails for: QQQ"


def test_members_below_floor_is_reported_without_changing_the_pooled_result(
    session: Session,
) -> None:
    _seed_pool_passes_but_qqq_is_below_the_bracket_floor(session)
    pre = _pooled(session, ["SPY", "QQQ"])
    assert pre.passed, pre.reasons  # the pooled computation is unchanged
    assert pre.bracket_fraction == pytest.approx(37 / 40)
    assert pre.floors == (0.90, 0.80)
    assert [row[0] for row in pre.members_below_floor] == ["QQQ"]
    _, bracket, continuity, _ = pre.members_below_floor[0]
    assert bracket == pytest.approx(0.85) and continuity == pytest.approx(1.0)
    assert pre.or0c_warning().startswith(_OR0C_WARNING)
    assert pre.to_dict()["members_below_floor"][0]["underlying"] == "QQQ"
    # a set whose every member clears both floors carries no warning
    assert _pooled(session, ["SPY"]).members_below_floor == ()
    assert _pooled(session, ["SPY"]).or0c_warning() == ""


def test_a_member_below_the_continuity_floor_alone_is_also_reported(session: Session) -> None:
    now = utcnow()
    seed_coverage_run(session, ["SPY"], started_at=now - timedelta(days=1))
    seed_coverage_run(session, ["QQQ"], bars_written=790, sessions_expected=1000, started_at=now)
    session.commit()
    pre = _pooled(session, ["SPY", "QQQ"])
    assert pre.passed  # pooled continuity 1790/2000 = 0.895
    assert [row[0] for row in pre.members_below_floor] == ["QQQ"]


def test_the_repository_records_the_operators_or0c_decision() -> None:
    """The operator decided OR-0c pooled on 2026-10-26; the committed file carries
    exactly that line, dated and attributed (OR-0c memo, "How the operator records")."""
    from signalforge.research import options_evidence as oe

    assert oe.OR0C_DECISIONS_FILE.is_file()
    assert oe.or0c_pooled_decision_recorded()
    text = oe.OR0C_DECISIONS_FILE.read_text(encoding="utf-8")
    line = next(ln for ln in text.splitlines() if ln.startswith("OR-0c: DECIDED pooled"))
    assert "2026-10-26" in line and "operator" in line


def test_the_or0c_decision_line_is_parsed_strictly(tmp_path: Path) -> None:
    from signalforge.research.options_evidence import or0c_pooled_decision_recorded

    f = tmp_path / "decisions.md"
    assert not or0c_pooled_decision_recorded(f)  # missing file: not decided
    for not_decided in (
        "| OR-0c | Gate 0.c read pooled over the set or per symbol | **Open** |",
        "OR-0c: DECIDED per-symbol",
        "OR-0c: Open",
        "we might say OR-0c: DECIDED pooled later",
        "OR-0c: DECIDED pooledish",
        "or-0c: decided pooled",
    ):
        f.write_text(f"# decisions\n\n{not_decided}\n", encoding="utf-8")
        assert not or0c_pooled_decision_recorded(f), not_decided
    for decided in (
        "OR-0c: DECIDED pooled",
        "- **OR-0c: DECIDED pooled** — operator, 2026-10-05",
        "> OR-0c: DECIDED pooled (operator)",
    ):
        f.write_text(f"# decisions\n\n{decided}\n", encoding="utf-8")
        assert or0c_pooled_decision_recorded(f), decided


def test_snapshot_warns_about_or0c_and_still_proceeds(session: Session, no_worker: None) -> None:
    _seed_pool_passes_but_qqq_is_below_the_bracket_floor(session)
    args = ["options", "snapshot", "--symbols", "SPY,QQQ", *_window()]
    before = _snapshot_count(session)
    dry = runner.invoke(app, args)
    assert dry.exit_code == 0, dry.output
    assert "WARNING: " + _OR0C_WARNING in dry.output
    assert "DRY RUN" in dry.output
    assert _snapshot_count(session) == before

    res = runner.invoke(app, [*args, "--confirm"])
    assert res.exit_code == 0, res.output
    assert "WARNING: " + _OR0C_WARNING in res.output
    assert _snapshot_count(session) == before + 1

    # no below-floor member: no warning
    clean = runner.invoke(app, ["options", "snapshot", "--symbols", "SPY", *_window()])
    assert "OR-0c" not in clean.output


def _evaluable_snapshot_with_a_weak_member(session: Session) -> str:
    from tests.research.options_evidence_support import seed_everything

    snap, run = seed_everything(session, ["SPY", "QQQ"])
    gaps = dict(run.gaps_json)
    qqq = {k: dict(v) for k, v in gaps["QQQ"]["cycles"].items()}
    # default seed: 10/10 per symbol.  QQQ -> 8/10 = 0.80; pooled 18/20 = 0.90.
    # Give SPY more cycles so the pool is clear of the floor's edge.
    for k in sorted(qqq)[-2:]:
        qqq[k]["excluded"] = "ladder_incomplete"
    spy = {k: dict(v) for k, v in gaps["SPY"]["cycles"].items()}
    for i in range(10):
        spy[f"2025-{i + 1:02d}-15"] = dict(next(iter(spy.values())))
    gaps["QQQ"] = {"cycles": qqq}
    gaps["SPY"] = {"cycles": spy}
    run.gaps_json = gaps
    session.commit()
    pre = coverage_preflight(
        dataset_snapshot_coverage(session, snap, window_start=WINDOW_START, window_end=WINDOW_END)
    )
    assert pre.passed and [r[0] for r in pre.members_below_floor] == ["QQQ"], pre
    return str(snap.key)


def _evaluate_args(key: str, *extra: str) -> list[str]:
    return [
        "options",
        "evaluate-promotion",
        "--strategy",
        "options_short_vertical.medium_swing",
        "--snapshot-key",
        key,
        *_window(),
        "--sealed-days",
        "30",
        *extra,
    ]


def _nothing_was_written(session: Session) -> bool:
    from signalforge.db.models import StrategyPromotionEvaluation

    session.rollback()
    return (
        int(session.scalar(select(func.count()).select_from(StrategySealedTest)) or 0) == 0
        and int(session.scalar(select(func.count()).select_from(StrategyPromotionEvaluation)) or 0)
        == 0
    )


def test_evaluate_dry_run_prints_the_or0c_warning_and_keeps_its_exit_semantics(
    session: Session,
) -> None:
    key = _evaluable_snapshot_with_a_weak_member(session)
    res = runner.invoke(app, _evaluate_args(key))
    assert "WARNING: " + _OR0C_WARNING in res.output
    # a dry run is not refused by OR-0c: no refusal block, the ladder is shown, exit 0
    assert "REFUSED" not in res.output, res.output
    assert "DRY RUN — no evaluation row, no sealed test, no look" in res.output
    assert res.exit_code == 0, res.output
    assert _nothing_was_written(session)


def test_evaluate_confirm_refuses_a_below_floor_member_without_the_flag(
    session: Session, no_worker: None
) -> None:
    key = _evaluable_snapshot_with_a_weak_member(session)
    res = runner.invoke(app, _evaluate_args(key, "--confirm", "--grid"))
    assert res.exit_code == 2, res.output
    assert "WARNING: " + _OR0C_WARNING in res.output
    assert "OR-0c is open and QQQ is below a coverage floor" in res.output
    assert "no evidence was assembled, no row was written and no sealed look was spent" in (
        res.output
    )
    assert _nothing_was_written(session)


def test_evaluate_confirm_refuses_the_flag_while_the_decisions_file_says_open(
    session: Session, no_worker: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The flag alone is not a decision: a decisions file that says Open refuses it."""
    from signalforge.research import options_evidence as oe

    still_open = tmp_path / "decisions.md"
    still_open.write_text(
        "| OR-0c | Gate 0.c read pooled or per symbol | **Open** |\n", encoding="utf-8"
    )
    monkeypatch.setattr(oe, "OR0C_DECISIONS_FILE", still_open)
    key = _evaluable_snapshot_with_a_weak_member(session)
    res = runner.invoke(
        app, _evaluate_args(key, "--confirm", "--grid", "--accept-pooled-coverage", "OR-0c")
    )
    assert res.exit_code == 2, res.output
    assert "has no line 'OR-0c: DECIDED pooled'" in res.output
    assert "the flag is not honoured" in res.output
    assert _nothing_was_written(session)


def test_evaluate_confirm_refuses_a_recorded_decision_without_the_flag(
    session: Session, no_worker: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from signalforge.research import options_evidence as oe

    decided = tmp_path / "decisions.md"
    decided.write_text("OR-0c: DECIDED pooled\n", encoding="utf-8")
    monkeypatch.setattr(oe, "OR0C_DECISIONS_FILE", decided)
    key = _evaluable_snapshot_with_a_weak_member(session)
    res = runner.invoke(app, _evaluate_args(key, "--confirm", "--grid"))
    assert res.exit_code == 2, res.output
    assert "OR-0c is open and QQQ is below a coverage floor" in res.output
    wrong = runner.invoke(
        app, _evaluate_args(key, "--confirm", "--grid", "--accept-pooled-coverage", "yes")
    )
    assert wrong.exit_code == 2
    assert "--accept-pooled-coverage takes exactly 'OR-0c'" in wrong.output
    assert _nothing_was_written(session)


def test_evaluate_confirm_is_allowed_with_the_flag_and_a_recorded_pooled_decision(
    session: Session, no_worker: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Flag + a decisions file carrying the line: the OR-0c guard lets the run
    through.  The run is stopped at evidence assembly — this test is about the
    guard, not the ladder — so nothing is evaluated and no look is spent."""
    import signalforge.research.options_evidence as oe
    import signalforge.research.options_sensitivity as sens

    decided = tmp_path / "decisions.md"
    decided.write_text("# decisions\n\n- **OR-0c: DECIDED pooled** — operator\n", encoding="utf-8")
    monkeypatch.setattr(oe, "OR0C_DECISIONS_FILE", decided)

    class _PastTheGuard(RuntimeError):
        pass

    class _FakeReport:
        evaluated_points = 0
        declared_points = 0
        dropped_points: tuple[object, ...] = ()
        cache_hit = False

        def summary(self, th: object) -> None:
            return None

    def _stop(*a: object, **kw: object) -> object:
        raise _PastTheGuard

    monkeypatch.setattr(sens, "run_options_sensitivity", lambda *a, **kw: _FakeReport())
    monkeypatch.setattr(oe, "assemble_options_evidence", _stop)

    key = _evaluable_snapshot_with_a_weak_member(session)
    res = runner.invoke(
        app, _evaluate_args(key, "--confirm", "--grid", "--accept-pooled-coverage", "OR-0c")
    )
    assert isinstance(res.exception, _PastTheGuard), res.output
    assert "REFUSED" not in res.output, res.output
    assert "WARNING: " + _OR0C_WARNING in res.output  # still disclosed
    assert "OR-0c: DECIDED pooled is recorded in decisions.md" in res.output
    assert _nothing_was_written(session)


def test_the_or0c_flag_never_overrides_a_pooled_floor_failure(
    session: Session, no_worker: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from signalforge.research import options_evidence as oe

    decided = tmp_path / "decisions.md"
    decided.write_text("OR-0c: DECIDED pooled\n", encoding="utf-8")
    monkeypatch.setattr(oe, "OR0C_DECISIONS_FILE", decided)
    stage_a, stage_b = _seed_stage_a_then_failing_stage_b(session)
    seed_snapshot(
        session, [*INDEX, "AAPL"], key="pool_fails_snapshot", ingestion_run_ids=[stage_a, stage_b]
    )
    session.commit()
    res = runner.invoke(
        app,
        _evaluate_args(
            "pool_fails_snapshot", "--confirm", "--grid", "--accept-pooled-coverage", "OR-0c"
        ),
    )
    assert res.exit_code == 2
    assert "below gate 0.c's pre-registered floor" in res.output
    assert "pooled reading fails" in res.output
    assert _nothing_was_written(session)
