"""Real hermetic child processes exercise bounds without loading Kronos."""

import fcntl
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from signalforge.kronos import runtime


@pytest.fixture(autouse=True)
def isolated_runtime_tempdir(monkeypatch, tmp_path):
    """Every runtime test uses a private lock directory, never the live lock."""
    monkeypatch.setattr(runtime.tempfile, "tempdir", str(tmp_path))


def child(monkeypatch, code):
    original = subprocess.Popen

    def launch(args, **kwargs):
        return original([sys.executable, "-I", "-c", code], **kwargs)

    monkeypatch.setattr(runtime, "HOME", Path(tempfile.gettempdir()))
    monkeypatch.setattr(runtime.subprocess, "Popen", launch)


def test_credentials_not_inherited(monkeypatch):
    monkeypatch.setenv("SECRET_TOKEN", "never-pass")
    monkeypatch.setenv("HF_TOKEN", "never-pass")
    child(monkeypatch, "import os,json; print(json.dumps(dict(os.environ)))")
    env = json.loads(runtime.run_worker(b"{}"))
    assert "SECRET_TOKEN" not in env and "HF_TOKEN" not in env
    assert env["HF_HUB_OFFLINE"] == "1"
    assert env["HF_HUB_DISABLE_IMPLICIT_TOKEN"] == "1"


@pytest.mark.parametrize("stream", ["stdout", "stderr"])
def test_output_cap(monkeypatch, stream):
    child(monkeypatch, f"import sys; sys.{stream}.write('x'*200000)")
    with pytest.raises(runtime.KronosUnavailable, match="output exceeded"):
        runtime.run_worker(b"{}")


def test_timeout(monkeypatch):
    child(monkeypatch, "import time; time.sleep(5)")
    monkeypatch.setattr(runtime, "TIMEOUT", 0.1)
    with pytest.raises(runtime.KronosUnavailable, match="timed out"):
        runtime.run_worker(b"{}")


def test_failed_child_sanitized(monkeypatch):
    child(monkeypatch, "import sys; print('sensitive detail', file=sys.stderr); sys.exit(1)")
    with pytest.raises(
        runtime.KronosUnavailable, match=r"^Local inference failed; check cached runtime$"
    ):
        runtime.run_worker(b"{}")


def test_cross_process_lock(monkeypatch, tmp_path):
    monkeypatch.setattr(runtime, "runtime_status", lambda: {"configured": True})
    path = Path(tempfile.gettempdir()) / f"signalforge-kronos-{os.getuid()}.lock"
    assert path.parent == tmp_path
    with path.open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(runtime.KronosUnavailable, match="busy"):
            runtime.infer([], [])


def test_worker_blocks_network():
    from signalforge.kronos.worker import offline

    with pytest.raises(RuntimeError, match="Network disabled"):
        offline("socket.connect", ())
