"""Bounded generation registry shared by study collectors and operational UI.

No book/outcome queries, providers, credentials, execution or experiment imports.
Registry replacement and heartbeat publication share a lock to fence cutovers.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

SCHEMA = "study-active-v1"
MAX_BYTES = 60 * 1024
NAME = re.compile(r"[a-z0-9][a-z0-9._-]{0,79}\Z")


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def read_json(path: Path, *, limit: int = MAX_BYTES) -> dict[str, Any]:
    if path.is_symlink():
        raise ValueError("Linked operational metadata")
    with path.open("rb") as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError("Oversized operational metadata")
    result = json.loads(raw)
    if not isinstance(result, dict):
        raise ValueError("Operational metadata must be an object")
    return result


def timestamp(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("Missing timestamp")
    stamp = datetime.fromisoformat(value)
    if stamp.tzinfo is None:
        raise ValueError("Timestamp must have timezone")
    return stamp.astimezone(UTC)


def absolute_path(value: Any) -> Path:
    if not isinstance(value, str) or len(value) > 4096 or not Path(value).is_absolute():
        raise ValueError("Registry paths must be absolute")
    return Path(value)


def hash_value(value: Any, length: int = 64) -> None:
    if not isinstance(value, str) or not re.fullmatch("[0-9a-f]{" + str(length) + "}", value):
        raise ValueError("Invalid registry checksum")


def validate_registry(data: dict[str, Any]) -> dict[str, Any]:
    body = {k: v for k, v in data.items() if k != "hash"}
    if data.get("schema") != SCHEMA or digest(body) != data.get("hash"):
        raise ValueError("Registry checksum/schema mismatch")
    if type(data.get("generation")) is not int or data["generation"] < 2:
        raise ValueError("Invalid active generation")
    timestamp(data["activated_at"])
    hash_value(data["release_sha"], 40)
    entries = data["active"]
    if not isinstance(entries, list) or len(entries) != 3:
        raise ValueError("Require two Kronos studies and one forward study")
    names, directories = set(), set()
    kinds = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("Malformed registry entry")
        name = entry["name"]
        if not isinstance(name, str) or not NAME.fullmatch(name) or name in names:
            raise ValueError("Invalid or duplicate study identity")
        directory = absolute_path(entry["directory"]).resolve()
        if directory.name != name or directory in directories:
            raise ValueError("Study path/identity mismatch")
        names.add(name)
        directories.add(directory)
        kinds.append(entry["kind"])
        for field in ("request_hash", "metadata_sha256", "code_digest", "config_sha256"):
            hash_value(entry[field])
        if entry["kind"] == "kronos":
            hash_value(entry["modelweights_sha256"])
        elif entry.get("modelweights_sha256") is not None:
            raise ValueError("Forward study cannot have model weights")
        date.fromisoformat(entry["first_observation_session"])
    if sorted(kinds) != ["forward", "kronos", "kronos"]:
        raise ValueError("Registry study kinds mismatch")
    status = absolute_path(data["status_path"]).resolve()
    forward = absolute_path(data["forward_status_path"]).resolve()
    if status == forward:
        raise ValueError("Independent collectors need separate status paths")
    forward_entry = next(e for e in entries if e["kind"] == "forward")
    if forward != Path(forward_entry["directory"]).resolve() / "status.json":
        raise ValueError("Forward heartbeat must belong to active study")
    archives = data["archive"]
    if not isinstance(archives, list) or len(archives) > 16:
        raise ValueError("Unbounded registry archive")
    generations = set()
    for archived in archives:
        generation = archived["generation"]
        if type(generation) is not int or not 1 <= generation < data["generation"]:
            raise ValueError("Invalid archived generation")
        if generation in generations:
            raise ValueError("Duplicate archived generation")
        generations.add(generation)
        path = absolute_path(archived["status_path"]).resolve()
        if path in (status, forward):
            raise ValueError("Active heartbeat must not reuse archive state")
        old_names = archived["names"]
        if not isinstance(old_names, list) or not 1 <= len(old_names) <= 16:
            raise ValueError("Unbounded archived identities")
        if len(set(old_names)) != len(old_names) or any(
            not isinstance(n, str) or not NAME.fullmatch(n) or n in names for n in old_names
        ):
            raise ValueError("Archive and active identities must be distinct")
    return data


def load_registry(path: Path) -> dict[str, Any]:
    return validate_registry(read_json(path))


@contextmanager
def registry_lock(path: Path) -> Iterator[None]:
    with (path.parent / f".{path.name}.lock").open("a") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def atomic_json(path: Path, data: dict[str, Any]) -> None:
    content = json.dumps(data, sort_keys=True, indent=2).encode()
    if len(content) > MAX_BYTES:
        raise ValueError("Registry publication exceeds metadata bound")
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def assert_current(path: Path, snapshot: dict[str, Any]) -> None:
    if load_registry(path)["hash"] != snapshot["hash"]:
        raise ValueError("Active study generation changed during poll")


def publish_current(path: Path, snapshot: dict[str, Any], publish: Callable[[], None]) -> None:
    with registry_lock(path):
        assert_current(path, snapshot)
        publish()


def validate_study_metadata(entry: dict[str, Any]) -> None:
    root = absolute_path(entry["directory"])
    name = "manifest.json" if entry["kind"] == "kronos" else "plan.json"
    with (root / name).open("rb") as stream:
        raw = stream.read(2 * 1024**2 + 1)
    if len(raw) > 2 * 1024**2 or hashlib.sha256(raw).hexdigest() != entry["metadata_sha256"]:
        raise ValueError("Active study manifest checksum mismatch")
    lineage = read_json(root / "refresh-lineage.json")
    for source, target in (
        ("request_hash", "request_hash"),
        ("native_metadata_sha256", "metadata_sha256"),
        ("native_code_digest", "code_digest"),
        ("config_sha256", "config_sha256"),
        ("modelweights_sha256", "modelweights_sha256"),
    ):
        if lineage[source] != entry[target]:
            raise ValueError("Active study lineage mismatch")


def pin_collector(
    path: Path, generation: int, kind: str, directories: list[Path]
) -> dict[str, Any]:
    snapshot = load_registry(path)
    if generation != snapshot["generation"]:
        raise ValueError("Collector expected generation mismatch")
    entries = [e for e in snapshot["active"] if e["kind"] == kind]
    if len(directories) != len(entries) or len({d.resolve() for d in directories}) != len(
        directories
    ):
        raise ValueError("Collector studies must be unique and complete")
    if {Path(e["directory"]).resolve() for e in entries} != {d.resolve() for d in directories}:
        raise ValueError("Collector active study set mismatch")
    for entry in entries:
        validate_study_metadata(entry)
    return snapshot
