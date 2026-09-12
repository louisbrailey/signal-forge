"""launchd plist sanity checks (deploy/launchd/*.plist).

These are static-file checks only: no network, no `.env`, and no assertion
that the referenced binaries actually exist on disk (CI may not have a
`.venv` at all) — `make launchd-check` (``plutil -lint``) already covers
syntactic validity on this Mac; this suite checks the *content* invariants
the runbook (docs/RUNBOOK_ALWAYS_ON.md) and README depend on.
"""

from __future__ import annotations

import plistlib
import subprocess
from pathlib import Path
from typing import Any

import pytest

from tests.support import REPO_ROOT

LAUNCHD_DIR = REPO_ROOT / "deploy" / "launchd"
PLIST_PATHS = sorted(LAUNCHD_DIR.glob("*.plist"))

LOG_DIR_SUFFIX = "Library/Logs/signalforge/"


def _main_checkout() -> Path | None:
    """The MAIN checkout's root, or ``None`` if it cannot be resolved.

    ``tests.support.REPO_ROOT`` is derived from this file's location, so inside
    a git worktree it is the *worktree's* root — and a worktree has no ``.venv``
    of its own. The plists carry absolute paths into the ONE venv that launchd
    actually loads, which lives in the main checkout, so deriving the expected
    venv from ``REPO_ROOT`` makes this check fail in every worktree for a reason
    that has nothing to do with the plists.

    ``git rev-parse --git-common-dir`` names the **shared** git directory — the
    main checkout's ``.git``, not the worktree's ``.git`` file — so its parent
    is the tree the plists were written against. In a plain checkout it names
    that same ``.git`` and the answer is ``REPO_ROOT``.
    """
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    common = Path(completed.stdout.strip())
    if not common.is_absolute():
        common = (REPO_ROOT / common).resolve()
    return common.parent if common.name == ".git" else None


#: True when this file lives in a git worktree: there, ``.git`` is a FILE
#: pointing at the shared git directory rather than a directory of its own.
IN_WORKTREE = (REPO_ROOT / ".git").is_file()
MAIN_CHECKOUT = _main_checkout()
VENV_BIN = (MAIN_CHECKOUT or REPO_ROOT) / ".venv" / "bin"


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
    _path, data = plist
    args = data["ProgramArguments"]
    assert isinstance(args, list) and args
    program = Path(args[0])
    # Strict everywhere: an absolute path is the whole point — launchd runs
    # with no shell, no PATH inheritance and no working directory of ours.
    assert program.is_absolute()
    if MAIN_CHECKOUT is None:
        pytest.skip(
            "cannot resolve the main checkout: `git rev-parse --git-common-dir` from "
            f"{REPO_ROOT} did not name a .git directory (git missing, or not a work tree). "
            "The plists name the MAIN checkout's .venv, which this run cannot locate; the "
            "absolute-path assertion above still ran."
        )
    assert program.parent == VENV_BIN, f"{program} is not under {VENV_BIN}"


def test_the_expected_venv_comes_from_the_main_checkout_not_a_worktree() -> None:
    """The resolution itself, asserted — otherwise a silently-wrong
    ``MAIN_CHECKOUT`` would make the check above vacuous in a worktree."""
    if MAIN_CHECKOUT is None:
        pytest.skip("the main checkout could not be resolved from this directory")
    assert (MAIN_CHECKOUT / ".git").is_dir(), f"{MAIN_CHECKOUT} is not a main checkout"
    if IN_WORKTREE:
        assert MAIN_CHECKOUT != REPO_ROOT, (
            "in a worktree the main checkout must resolve to a DIFFERENT tree; resolving to "
            "the worktree itself is the bug this helper exists to fix"
        )
    else:
        assert MAIN_CHECKOUT == REPO_ROOT


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
