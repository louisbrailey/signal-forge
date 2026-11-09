"""End-to-end offline rollover and fenced collector publication."""

import json
from pathlib import Path

import pytest
from freezegun import freeze_time
from scripts import funded_forward as funded
from scripts import kronos_comparison_collect as collector
from scripts import study_refresh as refresh
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from tests.experiments.test_study_refresh import staged_input as staged_input

from signalforge import study_registry as registry
from signalforge.db.models import Strategy, StrategyVersion
from signalforge.domain import Horizon, StrategyStatus
from signalforge.experiments import comparison
from signalforge.kronos.collection_status import collection_status

pytestmark = pytest.mark.parametrize("staged_input", ["kronos"], indirect=True)


@pytest.fixture
def rollover(staged_input, tmp_path):
    args, source = staged_input
    engine = create_engine("sqlite:///" + str(source))
    with Session(engine) as session, session.begin():
        for name, horizon in (
            ("medium", Horizon.MEDIUM_SWING),
            ("new-high52", Horizon.SHORT_SWING),
        ):
            strategy = Strategy(name=name, horizon=horizon, status=StrategyStatus.PAPER_APPROVED)
            session.add(strategy)
            session.flush()
            session.add(
                StrategyVersion(
                    strategy_id=strategy.id,
                    version="1",
                    git_sha="synthetic",
                    spec_json={"name": name},
                    status=StrategyStatus.PAPER_APPROVED,
                )
            )
    engine.dispose()
    _, short_parent = refresh.read_metadata(args["parent"] / "manifest.json")
    medium_parent = tmp_path / "medium-parent-v1"
    forward_parent = tmp_path / "forward-parent-v1"
    real_forward = registry.read_json(
        Path(__file__).parents[1] / "fixtures/studies/funded_forward_v1_metadata.json"
    )
    with freeze_time("2026-10-23 22:00:00"):
        comparison.freeze(
            source,
            medium_parent,
            [Path(p) for p in short_parent["artifact_roots"]],
            horizon=Horizon.MEDIUM_SWING,
        )
        refresh.native_freeze("forward", real_forward, forward_parent)
    controls = []
    for label, kind, parent in (
        ("short", "kronos", args["parent"]),
        ("medium", "kronos", medium_parent),
        ("forward", "forward", forward_parent),
    ):
        control = tmp_path / "v2" / label
        values = dict(
            args,
            kind=kind,
            parent=parent,
            destination=control,
            entry=args["observation"].replace(day=10) if kind == "forward" else None,
        )
        if label == "short":
            values.update(
                accept_scope_change=True,
                scope_change_reason="Include current approved high52 scope",
            )
        refresh.stage(**values)
        refresh.prepare(control, True, publish=True)
        controls.append(control)
    legacy = tmp_path / "legacy-heartbeat.json"
    legacy.write_text(
        json.dumps(
            {
                "checked_at": "2026-11-08T23:00:00+00:00",
                "results": [
                    {"experiment": p.name, "status": "complete"}
                    for p in (args["parent"], medium_parent)
                ],
                "pnl": "DO_NOT_RENDER",
            }
        )
    )
    path = tmp_path / "v2" / "active.json"
    state = tmp_path / "v2" / "collector-state-g2"
    refresh.activate(path, controls, 2, 0, state, legacy)
    snapshot = registry.load_registry(path)
    return path, snapshot, controls, state


def test_real_freeze_rollover_scope_lineage_and_collector_checks(rollover, tmp_path):
    path, snapshot, controls, state = rollover
    _, request = refresh.read_metadata(controls[0] / "refresh.json")
    assert len(request["scope_change"]["old"]["versions"]) == 1
    assert len(request["scope_change"]["new"]["versions"]) == 2
    entries = snapshot["active"]
    short = next(e for e in entries if e["name"].endswith("-short"))
    _, manifest = refresh.read_metadata(Path(short["directory"]) / "manifest.json")
    assert manifest["versions"] == request["scope_change"]["new"]["versions"]
    forward = next(e for e in entries if e["kind"] == "forward")
    _, plan = refresh.read_metadata(Path(forward["directory"]) / "plan.json")
    assert len(plan["strategies"]) == 5
    kronos = [Path(e["directory"]) for e in entries if e["kind"] == "kronos"]
    results = collector.run_poll(kronos, state, collect=False, registry_path=path, generation=2)
    assert all(r["status"] == "waiting_for_postclose_window" for r in results)
    # Unit fixture has no env file; check-only proves it never reads credentials.
    result = funded.run_collection(
        Path(forward["directory"]),
        tmp_path / "no-env",
        registry_path=path,
        generation=2,
        check_only=True,
    )
    assert result["status"] == "WAITING_FOR_FIRST_FUTURE_SESSION"
    projection = collection_status(registry_path=path)
    assert projection["generation"] == 2 and projection["health"] == "Healthy"
    assert projection["archive"][0]["generation"] == 1
    assert "DO_NOT_RENDER" not in json.dumps(projection)


def test_compare_and_swap_activation_and_new_state_are_enforced(rollover):
    path, _, controls, state = rollover
    before = path.read_bytes()
    with pytest.raises(ValueError, match="compare-and-swap"):
        refresh.activate(path, controls, 3, 0, state.with_name("g3"))
    assert path.read_bytes() == before
    with pytest.raises(ValueError, match="new state"):
        refresh.activate(path, controls, 3, 2, state)
    assert path.read_bytes() == before


def test_kronos_cutover_during_poll_cannot_publish_old_generation(rollover, monkeypatch):
    path, snapshot, _, state = rollover
    directories = [Path(e["directory"]) for e in snapshot["active"] if e["kind"] == "kronos"]

    def cutover(*args, **kwargs):
        newer = dict(snapshot, generation=3)
        newer["hash"] = registry.digest({k: v for k, v in newer.items() if k != "hash"})
        with registry.registry_lock(path):
            registry.atomic_json(path, newer)
        return [{"experiment": d.name, "status": "complete"} for d in directories]

    monkeypatch.setattr(collector, "poll", cutover)
    with pytest.raises(ValueError, match="changed during poll"):
        collector.run_poll(directories, state, registry_path=path, generation=2)
    assert not (state / "status.json").exists()


def test_forward_cutover_during_poll_cannot_publish_old_generation(rollover, monkeypatch, tmp_path):
    path, snapshot, _, _ = rollover
    root = Path(next(e["directory"] for e in snapshot["active"] if e["kind"] == "forward"))

    def cutover(*args, **kwargs):
        newer = dict(snapshot, generation=3)
        newer["hash"] = registry.digest({k: v for k, v in newer.items() if k != "hash"})
        with registry.registry_lock(path):
            registry.atomic_json(path, newer)
        return {"status": "COLLECTING_UNVALIDATED"}

    monkeypatch.setattr(funded, "_collect", cutover)
    with pytest.raises(ValueError, match="changed during poll"):
        funded.run_collection(root, tmp_path / "no-env", registry_path=path, generation=2)
    assert not (root / "status.json").exists()


def test_repeated_metadata_poll_does_not_collect_or_mix_legacy_state(rollover):
    path, snapshot, _, state = rollover
    directories = [Path(e["directory"]) for e in snapshot["active"] if e["kind"] == "kronos"]
    first = collector.run_poll(directories, state, collect=False, registry_path=path, generation=2)
    second = collector.run_poll(directories, state, collect=False, registry_path=path, generation=2)
    assert first == second
    saved = registry.read_json(state / "status.json")
    assert saved["generation"] == 2 and saved["last_success"] == {}
    assert len(saved["transitions"]) == 1
    saved["generation"] = 1
    registry.atomic_json(state / "status.json", saved)
    with pytest.raises(ValueError, match="another generation"):
        collector.run_poll(directories, state, collect=False, registry_path=path, generation=2)


def test_duplicate_or_missing_collector_paths_and_mutated_child_are_refused(rollover):
    path, snapshot, _, state = rollover
    directories = [Path(e["directory"]) for e in snapshot["active"] if e["kind"] == "kronos"]
    for wrong in ([directories[0]], [*directories, directories[0]]):
        with pytest.raises(ValueError, match="unique and complete"):
            collector.run_poll(wrong, state, collect=False, registry_path=path, generation=2)
    manifest = directories[0] / "manifest.json"
    manifest.write_bytes(manifest.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="manifest checksum"):
        collector.run_poll(directories, state, collect=False, registry_path=path, generation=2)
    assert not (state / "status.json").exists()
