"""Real isolated subprocesses, disposable Git releases and sentinel-only envs."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import sysconfig
import venv
from dataclasses import dataclass
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SENTINEL = "fake-launcher-sentinel-do-not-display"


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(
        ["/usr/bin/git", "-C", str(root), *args], text=True, stderr=subprocess.DEVNULL
    ).strip()


def commit(root: Path) -> str:
    git(root, "add", ".")
    git(
        root,
        "-c",
        "user.name=Launcher test",
        "-c",
        "user.email=launcher@example.invalid",
        "-c",
        "commit.gpgsign=false",
        "commit",
        "-qm",
        "fixture",
    )
    return git(root, "rev-parse", "HEAD")


def database(path: Path, revision: str = "fixture_head") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE alembic_version (version_num TEXT NOT NULL)")
        connection.execute("INSERT INTO alembic_version VALUES (?)", (revision,))
        connection.execute("CREATE TABLE app_setting (key TEXT, value_json TEXT)")
        connection.execute(
            "INSERT INTO app_setting VALUES ('auto_simulate_qualified_signals', 'true')"
        )


@dataclass
class Release:
    root: Path
    canonical: Path
    sha: str
    db: Path

    @property
    def env_file(self) -> Path:
        return self.canonical / ".env"

    def run(
        self,
        command: str = "api",
        *,
        check: bool = True,
        env: dict[str, str] | None = None,
        flags: tuple[str, ...] = ("-I", "-S"),
        sha: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        # Do not inherit a developer's process settings or credentials.
        process_env = {"PATH": "/usr/bin:/bin", "HOME": str(self.canonical)}
        process_env.update(env or {})
        argv = [
            str(self.root / ".venv/bin/python"),
            *flags,
            str(self.root / "deploy/run_release.py"),
            command,
            "--release-root",
            str(self.root),
            "--canonical-root",
            str(self.canonical),
            "--expected-sha",
            sha or self.sha,
        ]
        if check:
            argv.append("--check-only")
        result = subprocess.run(
            argv,
            cwd=self.canonical.parent,
            env=process_env,
            text=True,
            capture_output=True,
            timeout=30,
        )
        assert SENTINEL not in result.stdout + result.stderr
        return result


@pytest.fixture(scope="module")
def dependency_tree(tmp_path_factory: pytest.TempPathFactory) -> Path:
    target = tmp_path_factory.mktemp("release-dependencies")
    site = Path(sysconfig.get_path("purelib"))
    for name in (
        "pydantic",
        "pydantic_core",
        "pydantic_settings",
        "annotated_types",
        "typing_extensions.py",
        "typing_inspection",
        "dotenv",
        "sqlalchemy",
    ):
        source = site / name
        if source.is_dir():
            shutil.copytree(
                source,
                target / name,
                copy_function=os.link,
                ignore=shutil.ignore_patterns("__pycache__"),
            )
        else:
            os.link(source, target / name)
    return target


@pytest.fixture
def release(tmp_path: Path, dependency_tree: Path) -> Release:
    root = tmp_path / "release"
    canonical = tmp_path / "canonical"
    (root / "deploy").mkdir(parents=True)
    (canonical / "runtime").mkdir(parents=True)
    (canonical / "data").mkdir()
    shutil.copyfile(ROOT / "deploy/run_release.py", root / "deploy/run_release.py")
    (root / ".gitignore").write_text(".venv/\n.env\n__pycache__/\n")
    package = root / "src/signalforge"
    package.mkdir(parents=True)
    for name in ("__init__.py", "domain.py"):
        shutil.copyfile(ROOT / "src/signalforge" / name, package / name)
    shutil.copytree(
        ROOT / "src/signalforge/config",
        package / "config",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    versions = package / "db/migrations/versions"
    versions.mkdir(parents=True)
    (versions / "initial.py").write_text(
        "revision: str = 'fixture_head'\ndown_revision: str | None = None\ndepends_on = None\n"
        "raise AssertionError('migration modules must never execute')\n"
    )
    (package / "service_probe.py").write_text("""
import json, os, sys
import signalforge
from signalforge.config.settings import get_settings
from signalforge.config.paths import data_dir
settings = get_settings()
print(json.dumps({
    "argv": sys.argv,
    "cwd": os.getcwd(),
    "python": sys.executable,
    "origin": signalforge.__file__,
    "sys_path": sys.path,
    "data_dir": str(data_dir()),
    "database_url": settings.database_url,
    "api_scheduler_off": os.environ["APP_RUN_SCHEDULER"] == "false",
    "execution_disabled": settings.research.execution.enabled is False,
    "other_research_preserved": settings.research.allow_short_candidates,
    "sentinel_loaded": settings.market_data_api_key.get_secret_value()
        == "fake-launcher-sentinel-do-not-display",
    "notification_unchanged": os.environ.get("NOTIFICATION_PROVIDER") == "",
    "safe_path": os.environ["PYTHONSAFEPATH"] == "1" and sys.flags.safe_path,
    "pythonpath": os.environ["PYTHONPATH"],
    "isolated": bool(sys.flags.isolated and sys.flags.no_site),
}))
""")
    (package / "cli.py").write_text("import signalforge.service_probe\n")
    uvicorn = root / "src/uvicorn"
    uvicorn.mkdir()
    (uvicorn / "__init__.py").write_text("")
    (uvicorn / "__main__.py").write_text("import signalforge.service_probe\n")
    git(root, "init", "-q")
    sha = commit(root)
    venv.EnvBuilder(with_pip=False).create(root / ".venv")
    site = root / f".venv/lib/python{sys.version_info.major}.{sys.version_info.minor}/site-packages"
    shutil.copytree(dependency_tree, site, dirs_exist_ok=True, copy_function=os.link)
    db = canonical / "db/current.sqlite"
    database(db)
    release = Release(root, canonical, sha, db)
    release.env_file.write_text(
        f"MARKET_DATA_API_KEY={SENTINEL}\n"
        "SIGNALFORGE_DATA_DIR=runtime\nDATABASE_URL=sqlite+pysqlite:///db/current.sqlite\n"
        "APP_RUN_SCHEDULER=true\nNOTIFICATION_PROVIDER=\n"
        'RESEARCH={"execution":{"enabled":true},"allow_short_candidates":true}\n'
    )
    return release


def refused(result: subprocess.CompletedProcess[str], category: str) -> None:
    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr == f"release_launcher: {category}\n"


def test_check_only_preserves_paths_and_files_without_app_imports(release: Release) -> None:
    # A real app import would fail. Check mode imports settings only.
    (release.root / "src/signalforge/cli.py").write_text("raise AssertionError('app imported')")
    release.sha = commit(release.root)
    original_db = release.db.read_bytes()
    original_env = release.env_file.read_bytes()
    result = release.run("worker")
    assert result.returncode == 0, result.stderr
    status = json.loads(result.stdout)
    assert status["code_sha"] == release.sha
    assert status["sqlite_path"] == str(release.db)
    assert status["data_dir"] == str(release.canonical / "runtime")
    assert status["package_origin"] == str(release.root / "src/signalforge/__init__.py")
    assert status["env_file"] == str(release.env_file)
    assert status["schema_at_head"] and status["execution_disabled"]
    assert status["api_scheduler_disabled"] and status["python_isolated"]
    assert all(isinstance(value, bool | str) for value in status.values())
    assert release.db.read_bytes() == original_db
    assert release.env_file.read_bytes() == original_env
    assert not (release.root / ".env").exists()
    assert not (release.root / "data").exists()
    assert not list((release.root / "src").rglob("*.pyc"))
    assert git(release.root, "status", "--porcelain") == ""


@pytest.mark.parametrize("command", ["api", "worker"])
def test_exec_uses_release_python_source_and_only_known_command(
    release: Release, command: str
) -> None:
    result = release.run(command, check=False)
    assert result.returncode == 0, result.stderr
    service = json.loads(result.stdout)
    if command == "api":
        assert service["argv"][1:] == [
            "signalforge.app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            "8787",
        ]
    else:
        assert service["argv"][1:] == ["run-scheduler"]
    assert service["python"] == str(release.root / ".venv/bin/python")
    assert service["cwd"] == str(release.root)
    assert service["origin"] == str(release.root / "src/signalforge/__init__.py")
    assert service["pythonpath"] == str(release.root / "src")
    assert service["data_dir"] == str(release.canonical / "runtime")
    assert service["database_url"] == f"sqlite+pysqlite:///{release.db}"
    for key in (
        "api_scheduler_off",
        "execution_disabled",
        "other_research_preserved",
        "sentinel_loaded",
        "notification_unchanged",
        "safe_path",
        "isolated",
    ):
        assert service[key]
    assert all(str(release.canonical) not in path for path in service["sys_path"])


@pytest.mark.parametrize("lowercase", [False, True])
def test_launchd_environment_wins_including_explicit_empty_values(
    release: Release, lowercase: bool
) -> None:
    target = release.canonical / "explicit"
    target.mkdir()
    explicit_db = release.canonical / "explicit.sqlite"
    database(explicit_db)
    env = {
        "SIGNALFORGE_DATA_DIR": "explicit",
        "DATABASE_URL": "sqlite:///explicit.sqlite",
        "MARKET_DATA_API_KEY": "",
        "APP_PORT": "9898",
        "APP_RUN_SCHEDULER": "true",
    }
    if lowercase:
        env = {key.lower(): value for key, value in env.items()}
    result = release.run(check=False, env=env)
    assert result.returncode == 0, result.stderr
    service = json.loads(result.stdout)
    assert service["data_dir"] == str(target)
    assert service["database_url"] == f"sqlite:///{explicit_db}"
    assert not service["sentinel_loaded"]
    assert service["api_scheduler_off"]
    assert service["argv"][-1] == "9898"


def test_default_database_and_data_directory_remain_canonical(release: Release) -> None:
    release.env_file.write_text("MARKET_DATA_API_KEY=fake\n")
    default = release.canonical / "data/signalforge.sqlite"
    database(default)
    result = release.run()
    assert result.returncode == 0, result.stderr
    status = json.loads(result.stdout)
    assert status["data_dir"] == str(release.canonical / "data")
    assert status["sqlite_path"] == str(default)


def test_absolute_database_and_data_directory_remain_unchanged(release: Release) -> None:
    result = release.run(
        env={
            "SIGNALFORGE_DATA_DIR": str(release.canonical / "runtime"),
            "DATABASE_URL": f"sqlite:///{release.db}",
        }
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["sqlite_path"] == str(release.db)


def test_dirty_pythonpath_and_site_hooks_cannot_shadow_release(release: Release) -> None:
    dirty = release.canonical / "signalforge"
    dirty.mkdir()
    marker = release.canonical / "hook-ran"
    (dirty / "__init__.py").write_text(f"raise RuntimeError({SENTINEL!r})")
    site = (
        release.root
        / f".venv/lib/python{sys.version_info.major}.{sys.version_info.minor}/site-packages"
    )
    (site / "evil.pth").write_text(f"import pathlib; pathlib.Path({str(marker)!r}).touch()\n")
    (site / "old-editable.pth").write_text(str(release.canonical) + "\n")
    result = release.run(
        check=False,
        env={"PYTHONPATH": str(release.canonical), "PYTHONHOME": str(release.canonical)},
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["origin"].startswith(str(release.root))
    assert not marker.exists()


@pytest.mark.parametrize("subpath", ["signalforge", "signalforge/config"])
def test_shadowed_source_is_refused_before_import(release: Release, subpath: str) -> None:
    source = release.root / "src" / subpath
    outside = release.canonical / "shadow"
    source.rename(outside)
    (outside / "__init__.py").write_text(f"raise RuntimeError({SENTINEL!r})")
    source.symlink_to(outside, target_is_directory=True)
    release.sha = commit(release.root)
    refused(release.run(), "import_origin")


def test_sha_and_dirty_release_are_refused(release: Release) -> None:
    refused(release.run(sha="0" * 40), "release_sha")
    (release.root / "src/signalforge/__init__.py").write_text(SENTINEL)
    refused(release.run(), "release_dirty")


def test_release_dotenv_is_refused_even_when_ignored(release: Release) -> None:
    (release.root / ".env").write_text(f"MARKET_DATA_API_KEY={SENTINEL}")
    refused(release.run(), "release_environment")


def test_no_site_and_isolation_are_required(release: Release) -> None:
    refused(release.run(flags=("-I",)), "python_isolation")
    refused(release.run(flags=("-S",)), "python_isolation")


def test_shared_canonical_venv_is_refused(release: Release) -> None:
    outside = release.canonical / ".venv"
    (release.root / ".venv").rename(outside)
    (release.root / ".venv").symlink_to(outside, target_is_directory=True)
    release.sha = commit(release.root)
    refused(release.run(), "python_isolation")


def test_no_arbitrary_commands_or_echoed_arguments(release: Release) -> None:
    refused(release.run(command=SENTINEL), "arguments")
    refused(release.run(command="execution"), "arguments")


@pytest.mark.parametrize(
    "contents",
    [
        f"APP_PORT={SENTINEL}\n",
        f"RESEARCH={SENTINEL}\n",
        f"DATABASE_URL=postgresql://user:{SENTINEL}@localhost/private\n",
    ],
)
def test_settings_and_credentialed_database_failures_are_redacted(
    release: Release, contents: str
) -> None:
    release.env_file.write_text("SIGNALFORGE_DATA_DIR=runtime\n" + contents)
    result = release.run()
    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr in {
        "release_launcher: preflight\n",
        "release_launcher: database_backend\n",
    }


def test_dotenv_parse_diagnostics_are_not_disclosed(release: Release) -> None:
    with release.env_file.open("a") as handle:
        handle.write(f"\n{SENTINEL} malformed='unclosed\n")
    result = release.run()
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""


@pytest.mark.parametrize(
    "url", ["sqlite:///:memory:", "sqlite:///file:db?uri=true", "sqlite:///missing.sqlite"]
)
def test_ambiguous_or_missing_database_cannot_create_empty_state(
    release: Release, url: str
) -> None:
    result = release.run(env={"DATABASE_URL": url})
    assert result.returncode == 1 and result.stdout == ""
    assert result.stderr in {
        "release_launcher: database_location\n",
        "release_launcher: database_missing\n",
    }
    assert not (release.canonical / "missing.sqlite").exists()


def test_missing_data_is_not_created(release: Release) -> None:
    refused(release.run(env={"SIGNALFORGE_DATA_DIR": "absent"}), "data_missing")
    assert not (release.canonical / "absent").exists()


def test_migration_required_is_refused_without_running_or_writing(release: Release) -> None:
    with sqlite3.connect(release.db) as connection:
        connection.execute("UPDATE alembic_version SET version_num='old_head'")
    before = release.db.read_bytes()
    refused(release.run(), "migration_required")
    assert release.db.read_bytes() == before


def test_schema_check_observes_committed_wal(release: Release) -> None:
    with sqlite3.connect(release.db) as connection:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA wal_autocheckpoint=0")
        connection.execute("UPDATE alembic_version SET version_num='old_head'")
        connection.commit()
        refused(release.run(), "migration_required")


def test_execution_boundary_cannot_be_ignored_by_settings(release: Release) -> None:
    settings = release.root / "src/signalforge/config/settings.py"
    text = settings.read_text().replace(
        "return Settings()",
        """
    value = Settings()
    object.__setattr__(value.research.execution, "enabled", True)
    return value""",
    )
    settings.write_text(text)
    release.sha = commit(release.root)
    refused(release.run(), "paper_boundary")


@pytest.mark.parametrize("enabled", [True, "true"])
def test_db_research_overlay_cannot_restore_execution(
    release: Release, enabled: bool | str
) -> None:
    with sqlite3.connect(release.db) as connection:
        connection.execute(
            "INSERT INTO app_setting VALUES (?, ?)",
            ("research_overrides", json.dumps({"execution": {"enabled": enabled}})),
        )
    before = release.db.read_bytes()
    refused(release.run(), "paper_boundary")
    assert release.db.read_bytes() == before


def test_disabled_research_overlay_and_unrelated_app_flag_are_preserved(release: Release) -> None:
    with sqlite3.connect(release.db) as connection:
        connection.executemany(
            "INSERT INTO app_setting VALUES (?, ?)",
            [
                ("research_overrides", '{"execution":{"enabled":false}}'),
                ("app_overrides", '{"execution_enabled":true}'),
            ],
        )
    before = release.db.read_bytes()
    result = release.run(check=False)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["execution_disabled"]
    assert release.db.read_bytes() == before


def test_actual_release_migration_metadata_is_supported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "dont_write_bytecode", True)
    spec = importlib.util.spec_from_file_location(
        "release_launcher", ROOT / "deploy/run_release.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    current = tmp_path / "current.sqlite"
    # Latest reviewed source migration; no actual migration module is imported.
    database(current, revision="f3a7c1d9e5b2")  # pragma: allowlist secret
    before = current.read_bytes()
    module._schema_at_head(ROOT, current)
    assert current.read_bytes() == before
