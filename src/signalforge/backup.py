"""Local database backup + restore (ARCHITECTURE.md §12).

Uses SQLite's online backup API for a consistent snapshot while the app runs.
Optional symmetric encryption via ``gpg`` (or ``age``) if installed and a
passphrase is supplied at runtime — the passphrase is never stored.
"""

from __future__ import annotations

import shutil
import sqlite3
import subprocess
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from signalforge.config import get_settings, paths
from signalforge.observability import get_logger

_log = get_logger("backup")


def _gpg_bin() -> str | None:
    return shutil.which("gpg")


def _run_gpg(args: list[str], passphrase: str) -> None:
    gpg = _gpg_bin()
    if gpg is None:
        raise RuntimeError("gpg is not installed")
    subprocess.run(  # noqa: S603 - fixed argv, no shell
        [gpg, "--batch", "--yes", "--passphrase-fd", "0", *args],
        input=passphrase.encode(),
        check=True,
    )


def _sqlite_path() -> Path:
    url = get_settings().database_url
    for prefix in ("sqlite+pysqlite:///", "sqlite:///"):
        if url.startswith(prefix):
            return Path(url[len(prefix) :]).expanduser().resolve()
    raise RuntimeError(f"backup supports SQLite only; DATABASE_URL is {url!r}")


@dataclass(frozen=True, slots=True)
class BackupResult:
    path: Path
    bytes: int
    encrypted: bool


def create_backup(
    *, out_dir: Path | None = None, gpg_passphrase: str | None = None
) -> BackupResult:
    src = _sqlite_path()
    if not src.exists():
        raise FileNotFoundError(f"database not found: {src}")
    dest_dir = out_dir or paths.backups_dir()
    dest_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    snapshot = dest_dir / f"signalforge-{stamp}.sqlite"

    with closing(sqlite3.connect(src)) as source, closing(sqlite3.connect(snapshot)) as target:
        source.backup(target)  # online, consistent
    _log.info("backup.snapshot", path=str(snapshot), bytes=snapshot.stat().st_size)

    if gpg_passphrase:
        if _gpg_bin() is None:
            _log.warning(
                "backup.gpg_missing", detail="gpg not installed; keeping plaintext snapshot"
            )
            return BackupResult(snapshot, snapshot.stat().st_size, encrypted=False)
        enc = snapshot.with_suffix(snapshot.suffix + ".gpg")
        _run_gpg(
            ["--symmetric", "--cipher-algo", "AES256", "-o", str(enc), str(snapshot)],
            gpg_passphrase,
        )
        snapshot.unlink()
        _log.info("backup.encrypted", path=str(enc))
        return BackupResult(enc, enc.stat().st_size, encrypted=True)

    return BackupResult(snapshot, snapshot.stat().st_size, encrypted=False)


def restore_backup(backup_path: Path, *, gpg_passphrase: str | None = None) -> Path:
    """Overwrite the live database with ``backup_path``. Caller must confirm first."""
    dest = _sqlite_path()
    backup_path = backup_path.expanduser().resolve()
    if not backup_path.exists():
        raise FileNotFoundError(backup_path)

    working = backup_path
    if backup_path.suffix == ".gpg":
        if not gpg_passphrase:
            raise ValueError("an encrypted backup needs a passphrase to restore")
        working = backup_path.with_suffix("")
        _run_gpg(["-o", str(working), "-d", str(backup_path)], gpg_passphrase)

    # keep a pre-restore copy of the current db
    if dest.exists():
        shutil.copy2(dest, dest.with_suffix(dest.suffix + ".pre-restore"))
    shutil.copy2(working, dest)
    # drop stale WAL sidecars so a fresh open does not replay the old journal
    for sidecar in (f"{dest}-wal", f"{dest}-shm"):
        Path(sidecar).unlink(missing_ok=True)
    _log.warning("backup.restored", from_=str(backup_path), to=str(dest))
    return dest
