"""launchd plist sanity checks (deploy/launchd/*.plist).

These are static-file checks only: no network, no `.env`, and no assertion
that the referenced binaries actually exist on disk (CI may not have a
`.venv` at all) — `make launchd-check` (``plutil -lint``) already covers
syntactic validity on this Mac; this suite checks the *content* invariants
the runbook (docs/RUNBOOK_ALWAYS_ON.md) and README depend on.
"""

from __future__ import annotations

import plistlib
from pathlib import Path
from typing import Any

import pytest

from tests.support import REPO_ROOT

LAUNCHD_DIR = REPO_ROOT / "deploy" / "launchd"
PLIST_PATHS = sorted(LAUNCHD_DIR.glob("*.plist"))

LOG_DIR_SUFFIX = "Library/Logs/signalforge/"

PERSISTENT_AGENTS = {
    "com.signalforge.api.plist",
    "com.signalforge.worker.plist",
    "com.signalforge.kronos.plist",
}
PERIODIC_AGENTS = {
    "com.signalforge.kronos-comparison.plist",
    "com.signalforge.intraday-backfill.plist",
}


def _load(path: Path) -> dict[str, Any]:
    with path.open("rb") as fh:
        return plistlib.load(fh)


@pytest.fixture(params=PLIST_PATHS, ids=[p.name for p in PLIST_PATHS])
def plist(request: pytest.FixtureRequest) -> tuple[Path, dict[str, Any]]:
    path: Path = request.param
    return path, _load(path)


def test_expected_services_are_present() -> None:
    names = {p.name for p in PLIST_PATHS}
    assert names == PERSISTENT_AGENTS | PERIODIC_AGENTS


def test_plist_parses_and_label_matches_filename(plist: tuple[Path, dict[str, Any]]) -> None:
    path, data = plist
    assert data["Label"] == path.stem  # "com.signalforge.worker.plist" -> "com.signalforge.worker"


def test_program_arguments_start_with_an_absolute_venv_bin_path(
    plist: tuple[Path, dict[str, Any]],
) -> None:
    """Every program is absolute and comes from the PATH-leading venv.

    Persistent services run from their own checkout venv. The comparison
    collector is intentionally different: its program comes from the operating
    checkout venv while its working directory and PYTHONPATH point at the frozen
    research checkout. That cross-checkout split is part of the frozen protocol,
    not an inconsistency to normalize away.
    """
    path, data = plist
    args = data["ProgramArguments"]
    assert isinstance(args, list) and args
    program = Path(args[0])
    assert program.is_absolute(), program
    workdir = Path(data["WorkingDirectory"])
    assert workdir.is_absolute(), workdir
    path_venv_bin = Path(data["EnvironmentVariables"]["PATH"].split(":")[0])
    assert program.parent == path_venv_bin
    if path.name in PERSISTENT_AGENTS:
        own_venv_bin = workdir / ".venv" / "bin"
        assert program.parent == own_venv_bin, f"{program} is not under {own_venv_bin}"


def test_path_env_leads_with_the_same_venv_bin(plist: tuple[Path, dict[str, Any]]) -> None:
    path, data = plist
    program_bin = Path(data["ProgramArguments"][0]).parent
    first = data["EnvironmentVariables"]["PATH"].split(":")[0]
    assert Path(first) == program_bin, f"PATH starts with {first}, expected {program_bin}"
    if path.name in PERSISTENT_AGENTS:
        own_venv_bin = Path(data["WorkingDirectory"]) / ".venv" / "bin"
        assert Path(first) == own_venv_bin


def test_keep_alive_and_run_at_load_are_true(plist: tuple[Path, dict[str, Any]]) -> None:
    path, data = plist
    assert data["RunAtLoad"] is True
    if path.name in PERSISTENT_AGENTS:
        assert data["KeepAlive"] is True
    else:
        assert path.name in PERIODIC_AGENTS
        assert data.get("KeepAlive", False) is False
        assert isinstance(data["StartInterval"], int) and data["StartInterval"] > 0


def test_log_paths_are_under_library_logs_signalforge(plist: tuple[Path, dict[str, Any]]) -> None:
    path, data = plist
    out = data["StandardOutPath"]
    err = data["StandardErrorPath"]
    assert Path(out).is_absolute()
    assert Path(err).is_absolute()
    if path.name != "com.signalforge.kronos-comparison.plist":
        assert LOG_DIR_SUFFIX in out, out
        assert LOG_DIR_SUFFIX in err, err
    else:
        # The one-shot collector writes bounded atomic status instead of an
        # unbounded launchd log (docs/KRONOS-COMPARISON-COLLECTOR.md).
        assert path.name in PERIODIC_AGENTS
        assert out == err == "/dev/null"


def test_worker_plist_invokes_the_scheduler_cli() -> None:
    data = _load(LAUNCHD_DIR / "com.signalforge.worker.plist")
    assert data["ProgramArguments"][-3:] == ["-m", "signalforge.cli", "run-scheduler"]


def test_api_plist_does_not_run_the_scheduler_cli() -> None:
    data = _load(LAUNCHD_DIR / "com.signalforge.api.plist")
    assert "run-scheduler" not in data["ProgramArguments"]
