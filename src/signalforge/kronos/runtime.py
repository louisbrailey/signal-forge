"""Bounded subprocess with no inherited credentials and offline model loading."""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
import selectors
import signal
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from .worker import normalise_mode

HOME = Path.home() / "my-stack/Kronos"
PYTHON = HOME / ".venv/bin/python"
TIMEOUT = 90.0
MAX_OUTPUT = 128 * 1024


class KronosUnavailable(Exception):
    """Safe user-facing replay failure; subprocess diagnostics are not exposed."""


KronosError = KronosUnavailable


def runtime_status() -> dict[str, Any]:
    return {
        "configured": PYTHON.is_file() and (HOME / "model/kronos.py").is_file(),
        "configuration_only": True,
        "offline": True,
    }


def environment() -> dict[str, str]:
    return {
        "HOME": str(Path.home()),
        "PATH": "/usr/bin:/bin",
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "HF_HUB_DISABLE_TELEMETRY": "1",
        "HF_HUB_DISABLE_IMPLICIT_TOKEN": "1",
        "TOKENIZERS_PARALLELISM": "false",
        "PYTHONNOUSERSITE": "1",
        "OMP_NUM_THREADS": "4",
        "MKL_NUM_THREADS": "4",
    }


def run_worker(payload: bytes) -> bytes:
    """Cap combined stdout/stderr while streaming; kill/reap on every failure."""
    process = subprocess.Popen(  # noqa: S603
        [str(PYTHON), "-I", str(Path(__file__).with_name("worker.py")), str(HOME)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=environment(),
        cwd=HOME,
        start_new_session=True,
    )
    assert process.stdin and process.stdout and process.stderr
    output = bytearray()
    total = 0
    deadline = time.monotonic() + TIMEOUT
    try:
        with selectors.DefaultSelector() as selector:
            os.set_blocking(process.stdin.fileno(), False)
            selector.register(process.stdin, selectors.EVENT_WRITE)
            selector.register(process.stdout, selectors.EVENT_READ)
            selector.register(process.stderr, selectors.EVENT_READ)
            pending = memoryview(payload)
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise KronosError("Local model timed out")
                for key, _ in selector.select(min(remaining, 0.1)):
                    if key.fileobj is process.stdin:
                        count = os.write(key.fd, pending[:4096])
                        pending = pending[count:]
                        if not pending:
                            selector.unregister(key.fileobj)
                            process.stdin.close()
                        continue
                    chunk = os.read(key.fd, 4096)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    total += len(chunk)
                    if total > MAX_OUTPUT:
                        raise KronosError("Local model output exceeded limit")
                    if key.fileobj is process.stdout:
                        output.extend(chunk)
            process.wait(timeout=max(0.001, deadline - time.monotonic()))
        if process.returncode:
            raise KronosError("Local inference failed; check cached runtime")
        return bytes(output)
    finally:
        # Also terminate descendants if the worker exited before them.
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
        process.wait()
        for stream in (process.stdin, process.stdout, process.stderr):
            stream.close()


def infer(
    history: list[dict[str, Any]], dates: list[str], mode: dict[str, Any] | None = None
) -> list[list[float]]:
    """Run one bounded inference. ``mode`` is study-only; ``None`` is production (eval)."""
    try:
        resolved = normalise_mode(mode)
    except ValueError:
        raise KronosError("Invalid inference mode") from None
    if not runtime_status()["configured"]:
        raise KronosError("Cached local Kronos runtime is unavailable")
    payload = json.dumps(
        {"history": history, "dates": dates, "mode": resolved}, allow_nan=False
    ).encode()
    if len(payload) > 64 * 1024:
        raise KronosError("Inference input exceeded limit")
    # OS lock bounds concurrent inference across dashboard processes too.
    lockpath = Path(tempfile.gettempdir()) / f"signalforge-kronos-{os.getuid()}.lock"
    try:
        fd = os.open(lockpath, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    except OSError:
        raise KronosUnavailable("Local inference lock is unavailable") from None
    with os.fdopen(fd, "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise KronosError("Kronos replay is busy") from None
        try:
            result = json.loads(run_worker(payload))
            # The worker reports the mode it actually ran in; never trust it silently.
            if result["eval"] is not resolved["eval"]:
                raise KronosError("Local inference ran in an unexpected model mode")
            paths: list[list[float]] = result["paths"]
            return paths
        except KronosError:
            raise
        except Exception:
            raise KronosError("Local inference failed; check cached runtime") from None
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)
