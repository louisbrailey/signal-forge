#!/usr/bin/env python3
"""Stage versioned paper studies without reading outcomes or rewriting a parent."""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import hashlib
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from signalforge.backtest.actions import TickerChange
from signalforge.config import get_settings
from signalforge.data.calendar import sessions
from signalforge.domain import Horizon
from signalforge.experiments import comparison
from signalforge.research import prospective_funded as forward
from signalforge.settings_store import effective_research_config

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "study-refresh-v2"
NAMES = {"kronos": "manifest.json", "forward": "plan.json"}
MAX_METADATA_BYTES = 2 * 1024**2
MAX_ARTIFACT_BYTES = 4 * 1024**3


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_metadata(path: Path) -> tuple[bytes, dict[str, Any]]:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_METADATA_BYTES:
        raise ValueError("Missing, linked or oversized metadata")
    with path.open("rb") as stream:
        content = stream.read(MAX_METADATA_BYTES + 1)
    if len(content) > MAX_METADATA_BYTES:
        raise ValueError("Oversized metadata")
    value = json.loads(content)
    if not isinstance(value, dict):
        raise ValueError("Metadata must be an object")
    return content, value


def git(checkout: Path, *args: str) -> str:
    result = subprocess.run(  # noqa: S603 - fixed git executable; no shell
        ["git", "--no-optional-locks", "-C", str(checkout), *args],  # noqa: S607
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    return result.stdout.strip()


def release(checkout: Path, commit: str) -> dict[str, str]:
    checkout = checkout.resolve()
    if checkout != ROOT.resolve() or comparison.ROOT.resolve() != checkout:
        raise ValueError("Run the refresh script and imports from the new release checkout")
    if git(checkout, "rev-parse", "HEAD") != commit or len(commit) != 40:
        raise ValueError("Release must be the exact full checkout commit")
    if git(checkout, "status", "--porcelain", "--untracked-files=normal"):
        raise ValueError("Release checkout must be clean")
    if git(checkout, "rev-parse", "--abbrev-ref", "HEAD") != "HEAD":
        raise ValueError("Use a separate detached immutable release checkout")
    return {"checkout": str(checkout), "commit": commit}


def paper_only(confirmed: bool) -> None:
    cfg = get_settings().research.execution
    if not confirmed or cfg.enabled is not False or cfg.adapter_name != "paper_reference":
        raise ValueError("Require --paper-only and disabled execution with paper_reference")


# Run only the pinned metadata validators. -B prevents writes to old __pycache__.
# Never call status(), review_readiness(), collectors, forecasts or providers.
PARENT_VALIDATOR = """
import json, sys
from pathlib import Path
kind, directory, checkout = sys.argv[1:]
if kind == 'kronos':
    from signalforge.experiments import comparison as c
    if c.ROOT.resolve() != Path(checkout).resolve():
        raise ValueError('Pinned import mismatch')
    engine, manifest = c.open_books(Path(directory))
    engine.dispose()
else:
    from signalforge.research import prospective_funded as c
    if Path(c.__file__).resolve().parents[3] != Path(checkout).resolve():
        raise ValueError('Pinned import mismatch')
    manifest = c.validate_plan(Path(directory))
print(json.dumps(manifest))
"""


def pinned_metadata(kind: str, parent: Path, checkout: Path) -> dict[str, Any]:
    env = dict(os.environ, PYTHONPATH=str(checkout / "src"), PYTHONDONTWRITEBYTECODE="1")
    result = subprocess.run(  # noqa: S603 - local interpreter, fixed metadata-only code
        [sys.executable, "-B", "-c", PARENT_VALIDATOR, kind, str(parent), str(checkout)],
        env=env,
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    if result.returncode:
        raise ValueError("Pinned parent validator failed; check its frozen code/imports/manifest")
    return json.loads(result.stdout)


def parent_snapshot(kind: str, parent: Path, checkout: Path) -> tuple[bytes, dict[str, Any]]:
    parent, checkout = parent.resolve(), checkout.resolve()
    content, manifest = read_metadata(parent / NAMES[kind])
    expected = "kronos-comparison-v1" if kind == "kronos" else "funded-forward-v1"
    if manifest.get("protocol" if kind == "kronos" else "schema") != expected:
        raise ValueError("Unsupported parent schema")
    if pinned_metadata(kind, parent, checkout) != manifest:
        raise ValueError("Parent file differs from its pinned validator/embedded manifest")
    if kind == "kronos":
        cfg = manifest["config"]["execution"]
        if cfg.get("enabled") is not False or cfg.get("adapter_name") != "paper_reference":
            raise ValueError("Parent must have disabled paper execution")
        artifacts = manifest["artifacts"]
        if not artifacts or len(artifacts) > 20000:
            raise ValueError("Invalid parent artifact inventory")
        roots = [Path(p) for p in manifest["artifact_roots"]]
        if not 3 <= len(roots) <= 256:
            raise ValueError("Invalid parent artifact roots")
        count, size = 0, 0
        for root in roots:
            for path in root.rglob("*") if root.is_dir() else [root]:
                if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
                    count, size = count + 1, size + path.stat().st_size
                    if count > 20000 or size > MAX_ARTIFACT_BYTES:
                        raise ValueError("Parent artifacts exceed refresh inventory/byte bound")
        if comparison.artifacts(roots) != artifacts:
            raise ValueError("Parent pinned weights/tokenizer/implementation changed")
    # Recheck the sidecar after the SQLite metadata snapshot/artifact validation.
    # No raw DB bytes are copied/hashed: active WAL writers can keep appending.
    if read_metadata(parent / NAMES[kind])[0] != content:
        raise ValueError("Parent metadata changed during snapshot")
    return content, manifest


def future_dates(kind: str, observation: date, entry: date | None, now: datetime) -> None:
    today = now.astimezone(ZoneInfo("America/New_York")).date()
    if not today < observation <= today + timedelta(days=90):
        raise ValueError("First observation must be an explicit future date within 90 days")
    days = sessions(observation, observation + timedelta(days=10))
    if not days or days[0] != observation:
        raise ValueError("First observation must be a trading session")
    if kind == "forward" and entry != days[1]:
        raise ValueError(
            "Forward first entry must explicitly be the next session after observation"
        )
    if kind == "kronos" and entry is not None:
        raise ValueError("Kronos uses study_days; no separate first entry")


def disjoint(destination: Path, protected: Path) -> None:
    if (
        destination == protected
        or destination.is_relative_to(protected)
        or protected.is_relative_to(destination)
    ):
        raise ValueError("Destination must be disjoint from parent study and pinned checkout")


@contextlib.contextmanager
def publication_lock(destination: Path):
    # A stable sibling lock serializes stage/start publishers; never locks a parent.
    with (destination.parent / f".{destination.name}.refresh.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def write_new(path: Path, content: bytes) -> None:
    with path.open("xb") as output:
        path.chmod(0o600)
        output.write(content)
        output.flush()
        os.fsync(output.fileno())


def encode(value: dict[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, indent=2).encode()


def study_name(kind: str, manifest: dict[str, Any]) -> str:
    if kind == "forward":
        return "funded-validation-v2"
    names = {"SHORT_SWING": "short", "MEDIUM_SWING": "medium"}
    return "kronos-comparison-v2-" + names[manifest["horizon"]]


def metadata_hashes(kind: str, manifest: dict[str, Any]) -> dict[str, Any]:
    return {
        "config_sha256": comparison.digest(
            manifest["config"] if kind == "kronos" else inherited(manifest, kind)
        ),
        "config_hash_scope": "native config" if kind == "kronos" else "native plan policies/specs",
        "modelweights_sha256": (
            comparison.digest(manifest["artifacts"]) if kind == "kronos" else None
        ),
    }


def stage(
    *,
    kind: str,
    parent: Path,
    parent_checkout: Path,
    checkout: Path,
    commit: str,
    destination: Path,
    observation: date,
    entry: date | None,
    confirmed: bool,
) -> dict[str, Any]:
    paper_only(confirmed)
    now = datetime.now(UTC)
    future_dates(kind, observation, entry, now)
    pinned_release = release(checkout, commit)
    parent, parent_checkout = parent.resolve(), parent_checkout.resolve()
    destination = destination.absolute()
    for protected in (parent, parent_checkout):
        disjoint(destination.resolve(), protected)
        disjoint(checkout.resolve(), protected)
    content, manifest = parent_snapshot(kind, parent, parent_checkout)
    if git(parent_checkout, "rev-parse", "HEAD") == commit:
        raise ValueError("Refresh needs updated code in a separate release")
    first = manifest["study_days"][0] if kind == "kronos" else manifest["first_observation_session"]
    if observation <= date.fromisoformat(first):
        raise ValueError("Refresh cannot reset retrospective scores")
    request = {
        "schema": SCHEMA,
        "version": 2,
        "kind": kind,
        "study_name": study_name(kind, manifest),
        "created_at": now.isoformat(),
        "paper_only": True,
        "execution_enabled": False,
        "release": pinned_release,
        "parent": {
            "directory": str(parent),
            "checkout": str(parent_checkout),
            "commit": git(parent_checkout, "rev-parse", "HEAD"),
            "metadata_sha256": sha(content),
            "code_digest": manifest["code_hash" if kind == "kronos" else "code_digest"],
            "archive_scope": "manifest_metadata_only; evidence remains append-only in parent",
            **metadata_hashes(kind, manifest),
        },
        "first_observation_session": str(observation),
        "first_entry_session": str(entry) if entry else None,
        "evidence_policy": "Independent future evidence; never combine/reset/relabel parent scores",
    }
    request["hash"] = comparison.digest(request)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with publication_lock(destination):
        if os.path.lexists(destination):
            raise ValueError("Destination exists; never overwrite or restage")
        temporary = Path(tempfile.mkdtemp(prefix=".refresh-stage-", dir=destination.parent))
        try:
            write_new(temporary / NAMES[kind], content)
            write_new(temporary / "refresh.json", encode(request))
            temporary.rename(destination)
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)
    return request


def load_request(directory: Path, confirmed: bool) -> tuple[dict[str, Any], dict[str, Any]]:
    paper_only(confirmed)
    if directory.is_symlink():
        raise ValueError("Linked refresh directory")
    _, request = read_metadata(directory / "refresh.json")
    expected = request.pop("hash")
    if request.get("schema") != SCHEMA or comparison.digest(request) != expected:
        raise ValueError("Refresh request checksum mismatch")
    request["hash"] = expected
    if request["paper_only"] is not True or request["execution_enabled"] is not False:
        raise ValueError("Refresh must remain paper-only with disabled execution")
    release(Path(request["release"]["checkout"]), request["release"]["commit"])
    parent = request["parent"]
    content, manifest = parent_snapshot(
        request["kind"], Path(parent["directory"]), Path(parent["checkout"])
    )
    archived, _ = read_metadata(directory / NAMES[request["kind"]])
    if sha(content) != parent["metadata_sha256"] or content != archived:
        raise ValueError("Parent/archive changed; never replace lineage")
    if git(Path(parent["checkout"]), "rev-parse", "HEAD") != parent["commit"]:
        raise ValueError("Pinned parent checkout moved")
    if request["study_name"] != study_name(request["kind"], manifest):
        raise ValueError("Invalid native study directory name")
    return request, manifest


def differences(parent: Any, child: Any, path: str = "") -> list[str]:
    if isinstance(parent, dict) and isinstance(child, dict):
        return [
            key_path
            for key in sorted(parent.keys() | child.keys())
            for key_path in (
                differences(parent[key], child[key], f"{path}.{key}".strip("."))
                if key in parent and key in child
                else [f"{path}.{key}".strip(".")]
            )
        ]
    return [] if parent == child else [path]


def inherited(manifest: dict[str, Any], kind: str) -> dict[str, Any]:
    result = json.loads(json.dumps(manifest))
    variable = (
        ("hash", "code_hash", "frozen_at", "study_days")
        if kind == "kronos"
        else ("code_digest", "created_at", "first_observation_session", "first_entry_session")
    )
    for key in variable:
        result.pop(key, None)
    # A new code revision is provenance, never permission to change strategy rules.
    if kind == "forward":
        for spec in result["strategies"]:
            spec.pop("git_sha", None)
    return result


def native_freeze(kind: str, parent: dict[str, Any], destination: Path) -> dict[str, Any]:
    if kind == "kronos":
        source = comparison.source_engine(Path(parent["source"]))
        try:
            with Session(source) as session:
                execution = effective_research_config(session).execution
                if execution.enabled is not False or execution.adapter_name != "paper_reference":
                    raise ValueError("Source execution must remain disabled and paper_reference")
        finally:
            source.dispose()
        return comparison.freeze(
            Path(parent["source"]),
            destination,
            [Path(p) for p in parent["artifact_roots"]],
            horizon=Horizon(parent["horizon"]),
        )
    changes = tuple(
        TickerChange(
            c["old"], c["new"], date.fromisoformat(c["effective"]), c["source"], c["evidence"]
        )
        for c in parent["ticker_changes"]
    )
    return forward.freeze(
        destination,
        parent["metadata"],
        changes,
        parent["symbols"],
        date.fromisoformat(parent["history_start"]),
    )


def prepare(directory: Path, confirmed: bool, *, publish: bool) -> dict[str, Any]:
    directory = directory.absolute()
    # Validate before creating a lock: passing a v1 directory must cause no writes.
    if directory.is_symlink():
        raise ValueError("Linked refresh directory")
    read_metadata(directory / "refresh.json")
    with publication_lock(directory):
        request, parent = load_request(directory, confirmed)
        kind = request["kind"]
        study = directory / request["study_name"]
        if os.path.lexists(study):
            raise ValueError("Study exists; never refreeze or reset evidence")
        observation = date.fromisoformat(request["first_observation_session"])
        entry = date.fromisoformat(request["first_entry_session"]) if kind == "forward" else None
        future_dates(kind, observation, entry, datetime.now(UTC))
        temporary = Path(tempfile.mkdtemp(prefix=".refresh-build-", dir=directory))
        try:
            child = native_freeze(kind, parent, temporary / "study")
            if kind == "kronos":
                engine, checked = comparison.open_books(temporary / "study")
                engine.dispose()
            else:
                checked = forward.validate_plan(temporary / "study")
            _, saved = read_metadata(temporary / "study" / NAMES[kind])
            if checked != child or saved != child:
                raise ValueError("Native frozen metadata mismatch")
            changed = differences(inherited(parent, kind), inherited(child, kind))
            if changed:
                raise ValueError("Inherited metadata changed: " + ", ".join(changed[:30]))
            first = (
                child["study_days"][0] if kind == "kronos" else child["first_observation_session"]
            )
            dates_match = first == str(observation) and (
                kind == "kronos" or child["first_entry_session"] == str(entry)
            )
            result = {
                "status": "COMPATIBLE" if dates_match else "WAITING_FOR_FREEZE_WINDOW",
                "first_observation_session": str(observation),
                "native_first_observation_today": first,
                "automatic_promotion": False,
            }
            if publish:
                if not dates_match:
                    raise ValueError(
                        "Native freeze dates differ; run start in the documented window"
                    )
                # Recheck parent, release and execution immediately before publishing.
                load_request(directory, confirmed)
                future_dates(kind, observation, entry, datetime.now(UTC))
                write_new(
                    temporary / "study" / "refresh-lineage.json",
                    encode(
                        {
                            "request_hash": request["hash"],
                            "parent": request["parent"],
                            "release": request["release"],
                            "native_code_digest": child[
                                "code_hash" if kind == "kronos" else "code_digest"
                            ],
                            "native_metadata_sha256": comparison.file_hash(
                                temporary / "study" / NAMES[kind]
                            ),
                            **metadata_hashes(kind, child),
                        }
                    ),
                )
                (temporary / "study").rename(study)
                result["status"] = "STARTED_NEW_PAPER_STUDY"
            return result
        finally:
            shutil.rmtree(temporary)


def operator_commands(directory: Path, request: dict[str, Any]) -> list[str]:
    root = Path(request["release"]["checkout"])
    python = str(root / ".venv/bin/python")
    script = str(root / "scripts/study_refresh.py")
    study = str(directory / request["study_name"])
    commands = [
        shlex.join(
            [python, script, action, str(directory), "--paper-only", "--env-file", "LOCAL_ENV_FILE"]
        )
        for action in ("check", "start")
    ]
    if request["kind"] == "kronos":
        args = [
            python,
            str(root / "scripts/kronos_comparison_collect.py"),
            "--checkout",
            str(root),
            "--experiment",
            study,
            "--state-dir",
            str(directory / "collector-state"),
            "--env-file",
            "LOCAL_ENV_FILE",
        ]
    else:
        args = [
            python,
            str(root / "scripts/funded_forward.py"),
            "collect",
            study,
            "--env-file",
            "LOCAL_ENV_FILE",
        ]
    commands.append(shlex.join(args))
    return commands


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    for action in ("validate-parent", "stage", "check", "start"):
        p = sub.add_parser(action)
        p.add_argument("--paper-only", action="store_true", required=True)
        p.add_argument("--env-file", type=Path, help="Local settings, never copied or printed")
        if action in ("check", "start"):
            p.add_argument("directory", type=Path)
        else:
            p.add_argument("--kind", choices=NAMES, required=True)
            p.add_argument("--parent", type=Path, required=True)
            p.add_argument("--parent-checkout", type=Path, required=True)
        if action == "stage":
            p.add_argument("--checkout", type=Path, required=True)
            p.add_argument("--release", required=True)
            p.add_argument("--destination", type=Path, required=True)
            p.add_argument("--first-observation", type=date.fromisoformat, required=True)
            p.add_argument("--first-entry", type=date.fromisoformat)
    args = parser.parse_args()
    try:
        if args.env_file:
            from dotenv import load_dotenv

            if not args.env_file.is_file():
                raise ValueError("Local settings file missing")
            load_dotenv(args.env_file, override=False)
            get_settings.cache_clear()
        paper_only(args.paper_only)
        if args.action == "validate-parent":
            content, _ = parent_snapshot(args.kind, args.parent, args.parent_checkout)
            result = {"status": "PARENT_METADATA_VALID", "metadata_sha256": sha(content)}
        elif args.action == "stage":
            request = stage(
                kind=args.kind,
                parent=args.parent,
                parent_checkout=args.parent_checkout,
                checkout=args.checkout,
                commit=args.release,
                destination=args.destination,
                observation=args.first_observation,
                entry=args.first_entry,
                confirmed=args.paper_only,
            )
            result = {
                "status": "STAGED_NOT_STARTED",
                "commands": operator_commands(args.destination, request),
            }
        else:
            result = prepare(args.directory, args.paper_only, publish=args.action == "start")
        print(json.dumps(result, indent=2))
        return 0
    except ValueError as exc:
        print(json.dumps({"status": "BLOCKED", "reason": str(exc)}))
        return 1
    except (OSError, subprocess.SubprocessError, KeyError) as exc:
        print(json.dumps({"status": "BLOCKED", "error_category": type(exc).__name__}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
