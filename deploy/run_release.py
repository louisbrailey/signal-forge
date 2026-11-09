"""Pinned, paper-only API/worker launcher. Invoke with release Python -I -S.

No site startup hooks, application imports, database writes or service management
occur during preflight. See docs/RELEASE_DEPLOYMENT.md for the launchd contract.
"""

from __future__ import annotations

import argparse
import ast
import contextlib
import importlib
import importlib.util
import io
import json
import os
import re
import runpy
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any, Never

sys.dont_write_bytecode = True


class Refused(Exception):
    """Contains a fixed category only, never exception details or settings."""


class Parser(argparse.ArgumentParser):
    def error(self, message: str) -> Never:
        raise Refused("arguments")


def _git(root: Path, *args: str) -> str:
    # No inherited Git directory/config, fsmonitor, hooks, shell or credential helper.
    result = subprocess.run(  # noqa: S603
        [
            "/usr/bin/git",
            "--no-optional-locks",
            "-c",
            "core.fsmonitor=false",
            "-C",
            str(root),
            *args,
        ],
        env={
            "PATH": "/usr/bin:/bin",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_SYSTEM": os.devnull,
            "LC_ALL": "C",
        },
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    return result.stdout.strip()


def _runtime(root: Path) -> Path:
    """Mount only this release and its dependencies; never execute .pth files."""
    venv = root / ".venv"
    python = venv / "bin/python"
    if (
        not sys.flags.isolated
        or not sys.flags.no_site
        or not sys.flags.safe_path
        or Path(sys.executable).absolute() != python
        or venv.resolve() != venv
        or not python.is_file()
        or "include-system-site-packages = false" not in (venv / "pyvenv.cfg").read_text()
    ):
        raise Refused("python_isolation")
    site = venv / f"lib/python{sys.version_info.major}.{sys.version_info.minor}/site-packages"
    if not site.is_dir() or site.resolve() != site:
        raise Refused("python_environment")
    base = Path(sys.base_prefix).resolve()
    stdlib = [p for p in sys.path if p and Path(p).resolve().is_relative_to(base)]
    sys.path[:] = [str(root / "src"), *stdlib, str(site)]
    # Python 3.12 -S leaves these pointing at the base interpreter.
    sys.prefix = sys.exec_prefix = str(venv)
    return python


def _origin(root: Path) -> Path:
    expected = root / "src/signalforge/__init__.py"
    if any(path.is_symlink() for path in (root / "src").rglob("*")):
        raise Refused("import_origin")
    spec = importlib.util.find_spec("signalforge")
    if spec is None or spec.origin is None or Path(spec.origin).resolve() != expected:
        raise Refused("import_origin")
    package = importlib.import_module("signalforge")
    source = package.__file__
    if source is None or Path(source).resolve() != expected:
        raise Refused("import_origin")
    return expected


def _env(name: str) -> str | None:
    values = [v for k, v in os.environ.items() if k.upper() == name]
    if len(set(values)) > 1:
        raise Refused("environment")
    return values[0] if values else None


def _setenv(name: str, value: str) -> None:
    for key in list(os.environ):
        if key.upper() == name:
            del os.environ[key]
    os.environ[name] = value


def _load_env(path: Path) -> None:
    from dotenv import load_dotenv

    explicit = {k.upper() for k in os.environ}
    before = set(os.environ)
    # Capture parser diagnostics too: malformed lines can contain secrets.
    load_dotenv(path, override=False, encoding="utf-8")
    # Settings is case insensitive; a lower-case launchd variable must also win.
    for key in set(os.environ) - before:
        if key.upper() in explicit:
            del os.environ[key]


def _paper_only(settings: Any, get_settings: Any) -> Any:
    # This source has no env_nested_delimiter. RESEARCH is the supported JSON
    # environment field. Preserve every effective research knob except execution.
    research = settings.research.model_dump(mode="json")
    research["execution"]["enabled"] = False
    _setenv("RESEARCH", json.dumps(research))
    get_settings.cache_clear()
    guarded = get_settings()
    if guarded.research.execution.enabled is not False:
        raise Refused("paper_boundary")
    if guarded.research.model_dump(mode="json") != research:
        raise Refused("paper_boundary")
    return guarded


def _sqlite_url(value: str, canonical: Path) -> tuple[str, Path]:
    from sqlalchemy.engine import make_url

    url = make_url(value)
    if url.get_backend_name() != "sqlite":
        raise Refused("database_backend")
    # SQLite URI filenames have a second query/escaping syntax. Refuse rather
    # than accidentally redirect a URI, memory DB, network or credentialed URL.
    if (
        not url.database
        or url.database == ":memory:"
        or url.database.startswith("file:")
        or "uri" in url.query
        or url.username is not None
        or url.password is not None
        or url.host is not None
        or url.port is not None
    ):
        raise Refused("database_location")
    path = Path(url.database)
    # SQLite itself does not expand '~' in database filenames.
    path = (path if path.is_absolute() else canonical / path).resolve()
    if not path.is_file():
        raise Refused("database_missing")
    return url.set(database=str(path)).render_as_string(hide_password=False), path


def _schema_at_head(root: Path, database: Path) -> dict[str, Any]:
    """Compare Alembic heads without importing migrations or running upgrade()."""
    revisions: set[str] = set()
    parents: set[str] = set()
    versions = root / "src/signalforge/db/migrations/versions"
    for source in versions.glob("*.py"):
        if source.name == "__init__.py":
            continue
        metadata: dict[str, Any] = {}
        for node in ast.parse(source.read_text(encoding="utf-8")).body:
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                name, value = node.target.id, node.value
            elif isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
                name, value = node.targets[0].id, node.value
            else:
                continue
            if name in {"revision", "down_revision", "depends_on"} and value is not None:
                metadata[name] = ast.literal_eval(value)
        revision = metadata["revision"]
        if not isinstance(revision, str) or revision in revisions or metadata.get("depends_on"):
            raise Refused("migration_graph")
        revisions.add(revision)
        down = metadata["down_revision"]
        if down is not None:
            parents.update([down] if isinstance(down, str) else down)
    heads = revisions - parents
    if not heads or not parents.issubset(revisions):
        raise Refused("migration_graph")
    # mode=ro honours the WAL; immutable=1 would miss uncheckpointed commits.
    with contextlib.closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as db:
        db.execute("PRAGMA query_only=ON")
        current = {row[0] for row in db.execute("SELECT version_num FROM alembic_version")}
        rows = db.execute(
            "SELECT value_json FROM app_setting WHERE key = ?", ("research_overrides",)
        ).fetchall()
    if current != heads:
        raise Refused("migration_required")
    if len(rows) > 1:
        raise Refused("paper_boundary")
    overrides = (json.loads(rows[0][0]) if rows else {}) or {}
    if not isinstance(overrides, dict):
        raise Refused("paper_boundary")
    return overrides


def _effective_paper(settings: Any, overrides: dict[str, Any]) -> None:
    # Mirror settings_store's documented deep overlay, without importing models.
    def merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
        result = dict(base)
        for key, value in overlay.items():
            result[key] = (
                merge(result[key], value)
                if isinstance(value, dict) and isinstance(result.get(key), dict)
                else value
            )
        return result

    effective = type(settings.research).model_validate(
        merge(settings.research.model_dump(mode="json"), overrides)
    )
    if effective.execution.enabled is not False:
        raise Refused("paper_boundary")


def _prepare(args: argparse.Namespace) -> tuple[dict[str, Any], Any]:
    root = args.release_root.resolve(strict=True)
    canonical = args.canonical_root.resolve(strict=True)
    if (
        not args.release_root.is_absolute()
        or not args.canonical_root.is_absolute()
        or root == canonical
        or root.is_relative_to(canonical)
        or Path(__file__).resolve() != root / "deploy/run_release.py"
    ):
        raise Refused("release_location")
    if not re.fullmatch(r"[0-9a-f]{40}", args.expected_sha):
        raise Refused("release_sha")
    if _git(root, "rev-parse", "--show-toplevel") != str(root):
        raise Refused("release_location")
    sha = _git(root, "rev-parse", "HEAD")
    if sha != args.expected_sha:
        raise Refused("release_sha")
    if _git(root, "status", "--porcelain=v1", "--untracked-files=all"):
        raise Refused("release_dirty")
    if (root / ".env").exists() or (root / ".env").is_symlink():
        raise Refused("release_environment")
    python = _runtime(root)
    origin = _origin(root)
    env_file = canonical / ".env"
    if not env_file.is_file():
        raise Refused("canonical_environment")
    _load_env(env_file)
    # No inherited or dotenv-supplied Python path can reintroduce dirty source.
    for key in list(os.environ):
        if key.startswith("PYTHON") or key == "__PYVENV_LAUNCHER__":
            del os.environ[key]
    _setenv("PYTHONPATH", str(root / "src"))
    _setenv("PYTHONSAFEPATH", "1")
    _setenv("PYTHONDONTWRITEBYTECODE", "1")
    _setenv("PYTHONUNBUFFERED", "1")
    _setenv("APP_RUN_SCHEDULER", "false")
    os.environ["VIRTUAL_ENV"] = str(root / ".venv")
    os.environ["PATH"] = f"{root / '.venv/bin'}:/usr/bin:/bin:/usr/sbin:/sbin"
    # Resolve against the operating checkout BEFORE moving to release cwd.
    os.chdir(canonical)
    raw_data = _env("SIGNALFORGE_DATA_DIR")
    data = Path(raw_data).expanduser() if raw_data else canonical / "data"
    data = data.resolve()
    if not data.is_dir():
        raise Refused("data_missing")
    _setenv("SIGNALFORGE_DATA_DIR", str(data))
    from signalforge.config.settings import get_settings

    settings = _paper_only(get_settings(), get_settings)
    database_url, database = _sqlite_url(settings.database_url, canonical)
    _setenv("DATABASE_URL", database_url)
    overrides = _schema_at_head(root, database)
    os.chdir(root)
    get_settings.cache_clear()
    settings = get_settings()
    if settings.database_url != database_url or settings.research.execution.enabled is not False:
        raise Refused("effective_settings")
    _effective_paper(settings, overrides)
    # Check every configuration import, not just the package's top-level file.
    for name, module in tuple(sys.modules.items()):
        if name.startswith("signalforge."):
            source = getattr(module, "__file__", None)
            if source is None or not Path(source).resolve().is_relative_to(
                root / "src/signalforge"
            ):
                raise Refused("import_origin")
    return {
        "release_root": str(root),
        "canonical_root": str(canonical),
        "env_file": str(env_file),
        "python": str(python),
        "package_origin": str(origin),
        "data_dir": str(data),
        "sqlite_path": str(database),
        "code_sha": sha,
        "git_clean": True,
        "python_isolated": True,
        "execution_disabled": True,
        "api_scheduler_disabled": _env("APP_RUN_SCHEDULER") == "false",
        "schema_at_head": True,
    }, settings


# Re-enter under the release interpreter, still without site hooks, and repeat
# preflight immediately before the fixed service entrypoint. No shell is involved.
_SERVICE_BOOTSTRAP = (
    "import runpy, sys; scope = runpy.run_path(sys.argv.pop(1)); "
    "raise SystemExit(scope['main'](service=True))"
)


def main(*, service: bool = False) -> int:
    category = "preflight"
    try:
        parser = Parser(description=__doc__)
        parser.add_argument("command", choices=("api", "worker"))
        parser.add_argument("--release-root", type=Path, required=True)
        parser.add_argument("--canonical-root", type=Path, required=True)
        parser.add_argument("--expected-sha", required=True)
        parser.add_argument("--check-only", action="store_true")
        args = parser.parse_args()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            status, settings = _prepare(args)
        if args.check_only:
            print(json.dumps(status, sort_keys=True))
            return 0
        if not service:
            category = "exec"
            python = status["python"]
            os.execve(  # noqa: S606 - pinned interpreter and fixed bootstrap; no shell
                python,
                [
                    python,
                    "-I",
                    "-S",
                    "-u",
                    "-c",
                    _SERVICE_BOOTSTRAP,
                    str(Path(__file__).resolve()),
                    *sys.argv[1:],
                ],
                dict(os.environ),
            )
        category = "service_start"
        if args.command == "api":
            sys.argv = [
                "uvicorn",
                "signalforge.app.main:app",
                "--host",
                settings.app_host,
                "--port",
                str(settings.app_port),
            ]
            runpy.run_module("uvicorn", run_name="__main__")
        else:
            sys.argv = ["signalforge", "run-scheduler"]
            runpy.run_module("signalforge.cli", run_name="__main__")
        return 0
    except Refused as exc:
        category = str(exc)
    except Exception:  # noqa: S110 - details can contain settings/credential values
        pass
    print(f"release_launcher: {category}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
