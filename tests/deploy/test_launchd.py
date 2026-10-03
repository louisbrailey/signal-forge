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


def _load(path: Path) -> dict[str, Any]:
    with path.open("rb") as fh:
        return plistlib.load(fh)


@pytest.fixture(params=PLIST_PATHS, ids=[p.name for p in PLIST_PATHS])
def plist(request: pytest.FixtureRequest) -> tuple[Path, dict[str, Any]]:
    path: Path = request.param
    return path, _load(path)


def test_exactly_two_plists_are_present() -> None:
    names = {p.name for p in PLIST_PATHS}
    assert names == {"com.signalforge.api.plist", "com.signalforge.worker.plist"}


def test_plist_parses_and_label_matches_filename(plist: tuple[Path, dict[str, Any]]) -> None:
    path, data = plist
    assert data["Label"] == path.stem  # "com.signalforge.worker.plist" -> "com.signalforge.worker"


def test_program_arguments_start_with_an_absolute_venv_bin_path(
    plist: tuple[Path, dict[str, Any]],
) -> None:
    """The program is an absolute path inside the plist's OWN checkout venv.

    The plists are hand-reviewed files for the one Mac that loads them, so they
    carry that machine's absolute paths (README: "edit them if the repo lives
    elsewhere"). Where *this* test happens to run — CI, a worktree, a clone in
    another directory — says nothing about whether they are right. What must
    hold everywhere is internal consistency: launchd runs with no shell, no
    PATH inheritance and no working directory of ours, so the program must be
    absolute and must come from ``<WorkingDirectory>/.venv/bin`` — never from a
    venv belonging to some other tree.
    """
    _path, data = plist
    args = data["ProgramArguments"]
    assert isinstance(args, list) and args
    program = Path(args[0])
    assert program.is_absolute(), program
    workdir = Path(data["WorkingDirectory"])
    assert workdir.is_absolute(), workdir
    venv_bin = workdir / ".venv" / "bin"
    assert program.parent == venv_bin, f"{program} is not under {venv_bin}"


def test_path_env_leads_with_the_same_venv_bin(plist: tuple[Path, dict[str, Any]]) -> None:
    _path, data = plist
    venv_bin = Path(data["WorkingDirectory"]) / ".venv" / "bin"
    first = data["EnvironmentVariables"]["PATH"].split(":")[0]
    assert Path(first) == venv_bin, f"PATH starts with {first}, expected {venv_bin}"


def test_keep_alive_and_run_at_load_are_true(plist: tuple[Path, dict[str, Any]]) -> None:
    _path, data = plist
    assert data["RunAtLoad"] is True
    assert data["KeepAlive"] is True


def test_log_paths_are_under_library_logs_signalforge(plist: tuple[Path, dict[str, Any]]) -> None:
    _path, data = plist
    out = data["StandardOutPath"]
    err = data["StandardErrorPath"]
    assert LOG_DIR_SUFFIX in out, out
    assert LOG_DIR_SUFFIX in err, err
    assert Path(out).is_absolute()
    assert Path(err).is_absolute()


def test_worker_plist_invokes_the_scheduler_cli() -> None:
    data = _load(LAUNCHD_DIR / "com.signalforge.worker.plist")
    assert data["ProgramArguments"][-3:] == ["-m", "signalforge.cli", "run-scheduler"]


def test_api_plist_does_not_run_the_scheduler_cli() -> None:
    data = _load(LAUNCHD_DIR / "com.signalforge.api.plist")
    assert "run-scheduler" not in data["ProgramArguments"]
