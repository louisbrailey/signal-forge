"""Offline lifecycle tests; parent evidence is synthetic and never scored."""

from datetime import UTC, date, datetime

import pytest
from freezegun import freeze_time
from scripts import study_refresh as refresh
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from signalforge.db.base import Base
from signalforge.db.models import Strategy, StrategyVersion
from signalforge.domain import Horizon, StrategyStatus
from signalforge.experiments import comparison
from signalforge.research import prospective_funded as forward
from signalforge.settings_store import set_setting


def file_bytes(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def study_root(args):
    name = "kronos-comparison-v2-short" if args["kind"] == "kronos" else "funded-validation-v2"
    return args["destination"] / name


@pytest.fixture(params=["kronos", "forward"])
def staged_input(request, tmp_path, monkeypatch):
    kind = request.param
    source = tmp_path / "source.sqlite"
    engine = create_engine("sqlite:///" + str(source))
    Base.metadata.create_all(engine)
    with Session(engine) as session, session.begin():
        strategy = Strategy(
            name="synthetic", horizon=Horizon.SHORT_SWING, status=StrategyStatus.PAPER_APPROVED
        )
        session.add(strategy)
        session.flush()
        session.add(
            StrategyVersion(
                strategy_id=strategy.id,
                version="1",
                git_sha="synthetic",
                spec_json={},
                status=StrategyStatus.PAPER_APPROVED,
            )
        )
    engine.dispose()
    roots = []
    for name in ("weights", "tokenizer", "model-code"):
        path = tmp_path / name
        path.write_text("synthetic " + name)
        roots.append(path)
    parent = tmp_path / "parent-v1"
    with freeze_time("2026-10-23 22:00:00"):
        if kind == "kronos":
            comparison.freeze(source, parent, roots)
        else:
            forward.freeze(
                parent,
                {"SPY": {"instrument_type": "etf", "sector": "broad"}},
                (),
                ["SPY"],
                date(2020, 1, 1),
            )
    (parent / "opaque-evidence").write_bytes(b"synthetic append-only prior evidence")
    # Keep the real pinned subprocess validator and native freeze APIs. Only
    # the new-release Git deployment constraint is synthetic in lifecycle tests.
    monkeypatch.setattr(
        refresh,
        "release",
        lambda checkout, commit: {
            "checkout": str(checkout),
            "commit": commit,
        },
    )
    monkeypatch.setattr(refresh, "git", lambda *args: "0" * 40)
    monkeypatch.setattr(comparison, "forecast", lambda *a, **kw: pytest.fail("inference"))
    import socket

    monkeypatch.setattr(socket, "create_connection", lambda *a, **kw: pytest.fail("network"))
    with freeze_time("2026-11-08 23:00:00"):
        yield {
            "kind": kind,
            "parent": parent,
            "parent_checkout": refresh.ROOT,
            "checkout": tmp_path / "new-release",
            "commit": "1" * 40,
            "destination": tmp_path / "study-v2",
            "observation": date(2026, 11, 9),
            "entry": date(2026, 11, 10) if kind == "forward" else None,
            "confirmed": True,
        }, source


def test_native_freeze_and_immutable_parent_preservation(staged_input):
    args, source = staged_input
    parent_before = file_bytes(args["parent"])
    source_before = source.read_bytes()
    request = refresh.stage(**args)
    root = args["destination"]
    study = study_root(args)
    assert not study.exists()
    assert (root / refresh.NAMES[args["kind"]]).read_bytes() == parent_before[
        refresh.NAMES[args["kind"]]
    ]
    assert refresh.prepare(root, True, publish=False)["status"] == "COMPATIBLE"
    assert not study.exists()
    assert refresh.prepare(root, True, publish=True)["status"] == "STARTED_NEW_PAPER_STUDY"
    _, lineage = refresh.read_metadata(study / "refresh-lineage.json")
    assert lineage["request_hash"] == request["hash"]
    assert lineage["parent"]["metadata_sha256"] == request["parent"]["metadata_sha256"]
    assert lineage["release"]["commit"] == args["commit"]
    assert len(lineage["config_sha256"]) == 64
    assert len(lineage["native_code_digest"]) == 64
    assert lineage["modelweights_sha256"] == request["parent"]["modelweights_sha256"]
    if args["kind"] == "kronos":
        engine, child = comparison.open_books(study)
        engine.dispose()
        assert child["study_days"][0] == "2026-11-09"
    else:
        child = forward.validate_plan(study)
        assert child["first_observation_session"] == "2026-11-09"
        assert child["first_entry_session"] == "2026-11-10"
    _, old = refresh.read_metadata(args["parent"] / refresh.NAMES[args["kind"]])
    assert refresh.inherited(old, args["kind"]) == refresh.inherited(child, args["kind"])
    assert file_bytes(args["parent"]) == parent_before
    assert source.read_bytes() == source_before
    assert not (study / "opaque-evidence").exists()
    assert not (study / "collections").exists()


def test_non_overwrite_and_no_retrospective_score_reset(staged_input):
    args, _ = staged_input
    refresh.stage(**args)
    with pytest.raises(ValueError, match="exists"):
        refresh.stage(**args)
    refresh.prepare(args["destination"], True, publish=True)
    before = file_bytes(args["destination"])
    with pytest.raises(ValueError, match="never refreeze"):
        refresh.prepare(args["destination"], True, publish=True)
    assert file_bytes(args["destination"]) == before


def test_explicit_future_dates_and_no_delayed_historical_start(staged_input):
    args, _ = staged_input
    with pytest.raises(ValueError, match="explicit future"):
        refresh.stage(**dict(args, observation=date(2026, 11, 6)))
    refresh.stage(**args)
    with freeze_time("2026-11-09 14:00:00"), pytest.raises(ValueError, match="explicit future"):
        refresh.prepare(args["destination"], True, publish=True)
    assert not study_root(args).exists()


def test_freeze_window_is_checked_without_changing_native_dates(staged_input):
    args, _ = staged_input
    args["observation"] = date(2026, 11, 10)
    args["entry"] = date(2026, 11, 11) if args["kind"] == "forward" else None
    refresh.stage(**args)
    assert refresh.prepare(args["destination"], True, publish=False)["status"] == (
        "WAITING_FOR_FREEZE_WINDOW"
    )
    with pytest.raises(ValueError, match="Native freeze dates differ"):
        refresh.prepare(args["destination"], True, publish=True)
    assert not study_root(args).exists()
    assert not list(args["destination"].glob(".refresh-build-*"))


def test_atomic_failed_build_can_retry(staged_input, monkeypatch):
    args, _ = staged_input
    refresh.stage(**args)
    original = refresh.native_freeze

    def fail(kind, parent, destination):
        original(kind, parent, destination)
        raise RuntimeError("simulated interruption")

    with monkeypatch.context() as patch:
        patch.setattr(refresh, "native_freeze", fail)
        with pytest.raises(RuntimeError, match="interruption"):
            refresh.prepare(args["destination"], True, publish=True)
    assert not study_root(args).exists()
    assert not list(args["destination"].glob(".refresh-build-*"))
    assert refresh.prepare(args["destination"], True, publish=True)["status"].startswith("STARTED")


def test_parent_archive_tampering_is_never_rebased(staged_input):
    args, _ = staged_input
    refresh.stage(**args)
    path = args["destination"] / refresh.NAMES[args["kind"]]
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="Parent/archive changed"):
        refresh.prepare(args["destination"], True, publish=True)


def test_config_or_review_threshold_changes_block_publication(staged_input):
    args, source = staged_input
    if args["kind"] == "forward":
        path = args["parent"] / "plan.json"
        _, parent = refresh.read_metadata(path)
        parent["minimum_sessions_before_review"] = 999
        path.write_bytes(refresh.encode(parent))
    refresh.stage(**args)
    if args["kind"] == "kronos":
        engine = create_engine("sqlite:///" + str(source))
        with Session(engine) as session, session.begin():
            set_setting(session, "research_overrides", {"slippage_bps": 8}, actor="test")
        engine.dispose()
    parent_before = file_bytes(args["parent"])
    with pytest.raises(ValueError, match="Inherited metadata changed"):
        refresh.prepare(args["destination"], True, publish=True)
    assert not study_root(args).exists()
    assert file_bytes(args["parent"]) == parent_before


def test_parent_checksum_mutation_refused_even_when_parsed_metadata_is_unchanged(staged_input):
    args, _ = staged_input
    refresh.stage(**args)
    path = args["parent"] / refresh.NAMES[args["kind"]]
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="Parent/archive changed"):
        refresh.prepare(args["destination"], True, publish=True)
    assert not study_root(args).exists()


def test_parent_manifest_validator_and_artifact_integrity(staged_input):
    args, _ = staged_input
    if args["kind"] == "kronos":
        (args["parent"].parent / "weights").write_text("revised weights")
        with pytest.raises(ValueError, match="weights/tokenizer/implementation changed"):
            refresh.stage(**args)
    else:
        path = args["parent"] / "plan.json"
        _, parent = refresh.read_metadata(path)
        parent["code_digest"] = "wrong"
        path.write_bytes(refresh.encode(parent))
        with pytest.raises(ValueError, match="Pinned parent validator failed"):
            refresh.stage(**args)
    assert not args["destination"].exists()


def test_parent_namespace_and_execution_are_protected(staged_input, monkeypatch):
    args, _ = staged_input
    with pytest.raises(ValueError, match="disjoint"):
        refresh.stage(**dict(args, destination=args["parent"] / "new"))
    with pytest.raises(ValueError, match="paper-only"):
        refresh.stage(**dict(args, confirmed=False))
    from signalforge.config import ResearchConfig

    class EnabledSettings:
        research = ResearchConfig.model_validate({"execution": {"enabled": True}})

    monkeypatch.setattr(refresh, "get_settings", lambda: EnabledSettings())
    with pytest.raises(ValueError, match="disabled execution"):
        refresh.stage(**args)


def test_calendar_requires_explicit_entry_and_trading_session():
    now = datetime(2026, 11, 8, 23, tzinfo=UTC)
    with pytest.raises(ValueError, match="explicitly"):
        refresh.future_dates("forward", date(2026, 11, 9), None, now)
    with pytest.raises(ValueError, match="trading session"):
        refresh.future_dates("kronos", date(2026, 11, 14), None, now)


def test_new_york_midnight_boundary_is_strict():
    # UTC Monday is still New York Sunday: Monday's session is strictly future.
    refresh.future_dates("kronos", date(2026, 11, 9), None, datetime(2026, 11, 9, 2, tzinfo=UTC))
    # At New York midnight reject today's session, including before the opening bar.
    with pytest.raises(ValueError, match="explicit future"):
        refresh.future_dates(
            "kronos", date(2026, 11, 9), None, datetime(2026, 11, 9, 5, tzinfo=UTC)
        )


def test_exchange_holiday_cannot_be_an_observation_session():
    with pytest.raises(ValueError, match="trading session"):
        refresh.future_dates(
            "kronos", date(2026, 11, 26), None, datetime(2026, 11, 25, 23, tzinfo=UTC)
        )


def test_weekend_freeze_and_session_open_boundaries(staged_input):
    args, _ = staged_input
    args["observation"] = date(2026, 11, 16)
    args["entry"] = date(2026, 11, 17) if args["kind"] == "forward" else None
    with freeze_time("2026-11-13 19:00:00"):
        refresh.stage(**args)
        status = refresh.prepare(args["destination"], True, publish=False)["status"]
        assert status == ("WAITING_FOR_FREEZE_WINDOW" if args["kind"] == "kronos" else "COMPATIBLE")
    with freeze_time("2026-11-13 22:00:00"):
        assert refresh.prepare(args["destination"], True, publish=True)["status"].startswith(
            "STARTED"
        )
    _, child = refresh.read_metadata(study_root(args) / refresh.NAMES[args["kind"]])
    first = (
        child["study_days"][0] if args["kind"] == "kronos" else child["first_observation_session"]
    )
    from signalforge.data.calendar import rth_bounds_utc

    creation = datetime.fromisoformat(
        child["frozen_at" if args["kind"] == "kronos" else "created_at"]
    )
    assert rth_bounds_utc(date.fromisoformat(first))[0] > creation


def test_v1_cannot_be_passed_as_v2_even_to_check(staged_input):
    args, _ = staged_input
    before = file_bytes(args["parent"].parent)
    with pytest.raises(ValueError, match="metadata"):
        refresh.prepare(args["parent"], True, publish=False)
    assert file_bytes(args["parent"].parent) == before


def test_atomic_stage_failure_and_retry(staged_input, monkeypatch):
    args, _ = staged_input
    original = refresh.write_new

    def fail(path, content):
        original(path, content)
        raise OSError("simulated metadata failure")

    with monkeypatch.context() as patch:
        patch.setattr(refresh, "write_new", fail)
        with pytest.raises(OSError, match="simulated"):
            refresh.stage(**args)
    assert not args["destination"].exists()
    assert not list(args["destination"].parent.glob(".refresh-stage-*"))
    refresh.stage(**args)


def test_unique_kronos_identities_for_operational_status():
    assert refresh.study_name("kronos", {"horizon": "SHORT_SWING"}) == "kronos-comparison-v2-short"
    assert (
        refresh.study_name("kronos", {"horizon": "MEDIUM_SWING"}) == "kronos-comparison-v2-medium"
    )


def test_release_requires_clean_detached_exact_code(tmp_path, monkeypatch):
    import subprocess

    def run(*args):
        return subprocess.run(["git", "-C", str(tmp_path), *args], check=True, capture_output=True)

    run("init")
    path = tmp_path / "tracked"
    path.write_text("release")
    run("add", "tracked")
    run(
        "-c",
        "user.name=Offline Test",
        "-c",
        "user.email=test@example.invalid",
        "commit",
        "-m",
        "test",
    )
    commit = refresh.git(tmp_path, "rev-parse", "HEAD")
    monkeypatch.setattr(refresh, "ROOT", tmp_path)
    monkeypatch.setattr(comparison, "ROOT", tmp_path)
    with pytest.raises(ValueError, match="detached"):
        refresh.release(tmp_path, commit)
    run("checkout", "--detach", commit)
    assert refresh.release(tmp_path, commit)["commit"] == commit
    with pytest.raises(ValueError, match="exact"):
        refresh.release(tmp_path, "f" * 40)
    path.write_text("dirty")
    with pytest.raises(ValueError, match="clean"):
        refresh.release(tmp_path, commit)


def test_publish_lock_prevents_concurrent_cutover_or_duplicate_creation(staged_input):
    args, _ = staged_input
    root = args["destination"]
    refresh.stage(**args)
    with refresh.publication_lock(root), pytest.raises(BlockingIOError):
        refresh.prepare(root, True, publish=True)
    assert not study_root(args).exists()
    refresh.prepare(root, True, publish=True)
    before = file_bytes(root)
    with pytest.raises(ValueError, match="never refreeze"):
        refresh.prepare(root, True, publish=True)
    assert file_bytes(root) == before


@pytest.mark.parametrize("staged_input", ["kronos"], indirect=True)
def test_wal_lineage_reads_only_immutable_metadata_during_writer(staged_input):
    args, _ = staged_input
    import sqlite3

    # Synthetic WAL writer: unrelated appends must not be part of lineage.
    path = args["parent"] / "books.sqlite"
    with sqlite3.connect(path) as writer:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("CREATE TABLE opaque_future_append (id INTEGER)")
        writer.commit()
        writer.execute("BEGIN IMMEDIATE")
        writer.execute("INSERT INTO opaque_future_append VALUES (1)")
        snapshot = refresh.stage(**args)
        assert snapshot["parent"]["metadata_sha256"] == refresh.comparison.file_hash(
            args["parent"] / "manifest.json"
        )
        writer.commit()
    # Later appends do not invalidate frozen metadata or reset evidence.
    refresh.prepare(args["destination"], True, publish=True)


@pytest.mark.parametrize("staged_input", ["forward"], indirect=True)
def test_native_forward_api_cannot_silently_expand_parent_strategy_scope(staged_input):
    args, _ = staged_input
    path = args["parent"] / "plan.json"
    _, parent = refresh.read_metadata(path)
    assert len(parent["strategies"]) > 5
    parent["strategies"] = parent["strategies"][:5]
    path.write_bytes(refresh.encode(parent))
    before = file_bytes(args["parent"])
    refresh.stage(**args)
    with pytest.raises(ValueError, match="Inherited metadata changed: strategies"):
        refresh.prepare(args["destination"], True, publish=True)
    assert not study_root(args).exists()
    assert file_bytes(args["parent"]) == before


def test_credentials_are_neither_stored_nor_hashed(staged_input, monkeypatch):
    args, _ = staged_input
    first = refresh.stage(**args)
    secret = "synthetic-secret-never-store"  # pragma: allowlist secret
    monkeypatch.setenv("MARKET_DATA_API_KEY", secret)
    refresh.get_settings.cache_clear()
    second = refresh.stage(**dict(args, destination=args["destination"].with_name("other-v2")))
    assert first == second
    assert secret.encode() not in refresh.encode(second)
    assert refresh.sha(secret.encode()) not in refresh.encode(second).decode()


@pytest.mark.parametrize("staged_input", ["kronos"], indirect=True)
def test_source_execution_enablement_blocks_native_freeze(staged_input):
    args, source = staged_input
    refresh.stage(**args)
    engine = create_engine("sqlite:///" + str(source))
    with Session(engine) as session, session.begin():
        set_setting(session, "research_overrides", {"execution": {"enabled": True}}, actor="test")
    engine.dispose()
    with pytest.raises(ValueError, match="Source execution must remain disabled"):
        refresh.prepare(args["destination"], True, publish=True)
    assert not study_root(args).exists()
