"""Publication-layout unit regressions; no provider, model or evidence access."""

from pathlib import Path

import pytest
from scripts import study_refresh as refresh

from signalforge import study_registry as registry


def tree(root):
    result = {}
    for path in root.rglob("*"):
        key = str(path.relative_to(root))
        if path.is_symlink():
            result[key] = ("link", str(path.readlink()))
        elif path.is_dir():
            result[key] = ("directory",)
        else:
            result[key] = ("file", path.read_bytes())
    return result


@pytest.fixture
def layout(tmp_path, monkeypatch):
    # Stub only prior native-study validation to isolate filesystem preflight.
    # A separate regression exercises the same rejection with real freeze APIs.
    snapshots = {}
    controls = []
    natives = []
    for kind, name in (
        ("kronos", "kronos-comparison-v2-short"),
        ("kronos", "kronos-comparison-v2-medium"),
        ("forward", "funded-validation-v2"),
    ):
        control = tmp_path / "controls" / name
        native = control / name
        native.mkdir(parents=True)
        (control / "refresh.json").write_text("immutable request marker")
        (native / ("plan.json" if kind == "forward" else "manifest.json")).write_text(
            "immutable native marker"
        )
        controls.append(control)
        natives.append(native)
        snapshots[control] = (
            {
                "kind": kind,
                "name": name,
                "directory": str(native),
                "request_hash": "1" * 64,
                "metadata_sha256": "2" * 64,
                "code_digest": "3" * 64,
                "config_sha256": "4" * 64,
                "modelweights_sha256": "5" * 64 if kind == "kronos" else None,
                "first_observation_session": "2026-11-09",
            },
            {
                "kind": kind,
                "release": {"commit": "a" * 40},
                "parent": {
                    "directory": str(tmp_path / "parents" / name.replace("-v2", "-v1")),
                    "checkout": str(tmp_path / "pinned"),
                },
            },
        )
    monkeypatch.setattr(refresh, "started_entry", lambda directory: snapshots[directory])
    legacy = tmp_path / "legacy" / "status.json"
    legacy.parent.mkdir()
    legacy.write_text("untouched archive marker")
    return controls, natives, legacy


@pytest.mark.parametrize("occupied", [False, True])
@pytest.mark.parametrize(
    "collision",
    [
        "registry_forward_status",
        "registry_kronos_status",
        "registry_forward_status_lock",
        "registry_kronos_status_lock",
        "registry_forward_hidden_status_lock",
        "registry_kronos_hidden_status_lock",
        "registry_forward_collector_lock",
        "registry_kronos_collector_lock",
        "registry_native_manifest",
        "registry_control_request",
        "state_inside_forward",
        "state_inside_kronos",
        "state_inside_control",
        "state_ancestor_controls",
        "registry_inside_state",
        "state_inside_registry",
        "archive_equals_registry",
        "archive_equals_registry_lock",
        "registry_equals_archive_collector_lock",
        "registry_lock_aliases_forward_status",
        "registry_lock_aliases_kronos_status",
        "registry_lock_aliases_forward_lock",
        "registry_aliases_forward_status",
    ],
)
def test_collision_refusal_creates_or_overwrites_nothing(layout, tmp_path, collision, occupied):
    controls, natives, legacy = layout
    pointer = tmp_path / "never-created" / "registry" / "active.json"
    state = tmp_path / "never-created" / "state"
    forward = natives[2]
    if collision == "registry_forward_status":
        pointer = forward / "status.json"
    elif collision == "registry_kronos_status":
        pointer = state / "status.json"
    elif collision == "registry_forward_status_lock":
        pointer = forward / "status.lock"
    elif collision == "registry_kronos_status_lock":
        pointer = state / "status.lock"
    elif collision == "registry_forward_hidden_status_lock":
        pointer = forward / ".status.json.lock"
    elif collision == "registry_kronos_hidden_status_lock":
        pointer = state / ".status.json.lock"
    elif collision == "registry_forward_collector_lock":
        pointer = forward / "collector.lock"
    elif collision == "registry_kronos_collector_lock":
        pointer = state / "collector.lock"
    elif collision == "registry_native_manifest":
        pointer = natives[0] / "manifest.json"
    elif collision == "registry_control_request":
        pointer = controls[0] / "refresh.json"
    elif collision == "state_inside_forward":
        state = forward / "state"
    elif collision == "state_inside_kronos":
        state = natives[0] / "state"
    elif collision == "state_inside_control":
        state = controls[0] / "state"
    elif collision == "state_ancestor_controls":
        state = controls[0].parent
    elif collision == "registry_inside_state":
        pointer = state / "nested" / "active.json"
    elif collision == "state_inside_registry":
        state = pointer / "state"
    elif collision == "archive_equals_registry":
        legacy = pointer
    elif collision == "archive_equals_registry_lock":
        legacy = registry.lock_path(pointer)
    elif collision == "registry_equals_archive_collector_lock":
        pointer = legacy.parent / "collector.lock"
    elif collision.startswith("registry_lock_aliases"):
        target = (
            forward / "collector.lock"
            if collision.endswith("forward_lock")
            else (
                state / "status.json"
                if collision.endswith("kronos_status")
                else forward / "status.json"
            )
        )
        if occupied:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("existing heartbeat/lock alias target must survive")
        registry.lock_path(pointer).parent.mkdir(parents=True)
        registry.lock_path(pointer).symlink_to(target)
    elif collision == "registry_aliases_forward_status":
        if occupied:
            (forward / "status.json").write_text("existing alias target must survive")
        pointer.parent.mkdir(parents=True)
        pointer.symlink_to(forward / "status.json")
    if occupied and not pointer.exists() and not pointer.is_symlink():
        pointer.parent.mkdir(parents=True, exist_ok=True)
        pointer.write_text("existing registry/status/lock must survive")
    before = tree(tmp_path)
    with pytest.raises(ValueError):
        refresh.activate(pointer, controls, 2, 0, state, legacy)
    assert tree(tmp_path) == before


@pytest.mark.parametrize("target", ["registry", "registry_lock", "forward_lock"])
def test_loading_registry_rejects_heartbeat_lock_aliases_without_writes(layout, tmp_path, target):
    controls, _, legacy = layout
    pointer = tmp_path / "active.json"
    state = tmp_path / "new-state"
    refresh.activate(pointer, controls, 2, 0, state, legacy)
    data = registry.load_registry(pointer)
    aliases = {
        "registry": pointer,
        "registry_lock": registry.lock_path(pointer),
        "forward_lock": Path(data["forward_status_path"]).parent / "collector.lock",
    }
    data["status_path"] = str(aliases[target])
    data["hash"] = registry.digest({k: v for k, v in data.items() if k != "hash"})
    registry.atomic_json(pointer, data)
    before = tree(tmp_path)
    with pytest.raises(ValueError):
        registry.load_registry(pointer)
    assert tree(tmp_path) == before


def test_publisher_checks_current_layout_before_creating_its_lock(layout, tmp_path):
    controls, _, legacy = layout
    pointer = tmp_path / "active.json"
    refresh.activate(pointer, controls, 2, 0, tmp_path / "new-state", legacy)
    expected = registry.load_registry(pointer)
    malformed = dict(expected, status_path=str(registry.lock_path(pointer)))
    malformed["hash"] = registry.digest({k: v for k, v in malformed.items() if k != "hash"})
    registry.atomic_json(pointer, malformed)
    registry.lock_path(pointer).unlink()
    before = tree(tmp_path)
    with pytest.raises(ValueError):
        registry.publish_current(pointer, expected, lambda: pytest.fail("must not publish"))
    assert tree(tmp_path) == before


def test_failed_registry_write_preserves_state_and_can_retry(layout, tmp_path, monkeypatch):
    controls, _, legacy = layout
    pointer, state = tmp_path / "pointer" / "active.json", tmp_path / "new-state"

    def fail(*args):
        raise OSError("simulated atomic publication failure")

    with monkeypatch.context() as patch:
        patch.setattr(registry, "atomic_json", fail)
        with pytest.raises(OSError, match="simulated"):
            refresh.activate(pointer, controls, 2, 0, state, legacy)
    assert not pointer.exists() and not state.exists()
    refresh.activate(pointer, controls, 2, 0, state, legacy)
    assert registry.load_registry(pointer)["generation"] == 2
