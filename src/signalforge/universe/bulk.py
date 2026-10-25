"""Grouped-daily bulk archive: one provider payload per session, stored
verbatim (gzip) with a checksum, indexed by ``BulkFile``. Resumable and
budgeted: a run stops cleanly at its runtime or storage budget and the next
run continues from where the archive left off."""

from __future__ import annotations

import gzip
import hashlib
import json
import time
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from signalforge.config import get_settings
from signalforge.config.paths import data_dir
from signalforge.data.adapters.base import AdapterError
from signalforge.db.models import BulkFile
from signalforge.killswitch import ensure_not_engaged
from signalforge.observability import get_logger

_log = get_logger("universe.bulk")

_BASE_URL = "https://api.massive.com"
_RETRY_STATUS = frozenset({429, 500, 502, 503, 504})
_MAX_ATTEMPTS = 4
_RATE_LIMIT_BACKOFF_S = 61.0
_MIN_LOOKBACK_DAYS = 3 * 366  # floor; the walk-back window scales with the requested sessions
DEFAULT_SOURCE = "massive_grouped"


class GroupedDailyClient:
    """Read-only client for ``GET /v2/aggs/grouped/locale/us/market/stocks/{date}``.
    The key travels only in the Authorization header and is scrubbed from any
    text that leaves this class."""

    def __init__(
        self,
        api_key: str | None = None,
        *,
        client: httpx.Client | None = None,
        spacing_s: float = 2.0,
    ) -> None:
        settings = get_settings()
        self._key = settings.market_data_api_key.get_secret_value() if api_key is None else api_key
        self._client = client
        self._spacing = spacing_s
        self._last = 0.0

    def fetch_grouped(self, session_date: date) -> str:
        ensure_not_engaged()
        if not self._key:
            raise AdapterError("universe bulk: MARKET_DATA_API_KEY missing")
        path = f"/v2/aggs/grouped/locale/us/market/stocks/{session_date.isoformat()}?adjusted=true"
        return self._get(path)

    def get_json(self, path: str) -> dict[str, Any]:
        body = json.loads(self._get(path))
        return body if isinstance(body, dict) else {"results": body}

    def _get(self, path: str) -> str:
        last_status: int | None = None
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            if self._client is None:
                wait = self._spacing - (time.monotonic() - self._last)
                while wait > 0:
                    ensure_not_engaged()
                    time.sleep(min(0.2, wait))
                    wait = self._spacing - (time.monotonic() - self._last)
            ensure_not_engaged()
            self._last = time.monotonic()
            getter = self._client.get if self._client is not None else httpx.get
            try:
                resp = getter(
                    _BASE_URL + path,
                    headers={"Authorization": f"Bearer {self._key}"},
                    timeout=60.0,
                    follow_redirects=False,
                )
            except httpx.HTTPError:
                if attempt >= _MAX_ATTEMPTS:
                    raise AdapterError("universe bulk: network request failed") from None
                time.sleep(min(30.0, 1.5 * 2 ** (attempt - 1)))
                continue
            if resp.status_code == 200:
                # Defensive scrub in case a provider ever echoes the credential.
                # Real keys are long random strings; guard the length so a
                # short test key can never corrupt legitimate JSON content.
                text = resp.text
                if len(self._key) >= 16:
                    text = text.replace(self._key, "[REDACTED]")
                return text
            last_status = resp.status_code
            if resp.status_code in _RETRY_STATUS and attempt < _MAX_ATTEMPTS:
                retry_after = resp.headers.get("retry-after", "")
                if retry_after.replace(".", "", 1).isdigit():
                    delay = float(retry_after)
                elif resp.status_code == 429:
                    # The key's limit is per rolling minute and is shared with
                    # the EOD ingest; a short backoff just spends the remaining
                    # attempts inside the same window.
                    delay = _RATE_LIMIT_BACKOFF_S
                else:
                    delay = min(30.0, 1.5 * 2 ** (attempt - 1))
                time.sleep(delay)
                continue
            break
        raise AdapterError(f"universe bulk: HTTP {last_status}", rate_limited=last_status == 429)


def archive_dir() -> Path:
    p = data_dir() / "raw_bulk" / "grouped_daily"
    p.mkdir(parents=True, exist_ok=True)
    return p


def archived_sessions(session: Session, *, source: str = DEFAULT_SOURCE) -> list[date]:
    """Session dates with an OK bulk file, newest first."""
    return list(
        session.scalars(
            select(BulkFile.session_date)
            .where(BulkFile.source == source, BulkFile.status == "ok")
            .order_by(BulkFile.session_date.desc())
        )
    )


def archive_bytes(session: Session, *, source: str = DEFAULT_SOURCE) -> int:
    return int(
        session.scalar(
            select(func.coalesce(func.sum(BulkFile.bytes_gz), 0)).where(BulkFile.source == source)
        )
        or 0
    )


def load_bulk_rows(bf: BulkFile) -> list[dict[str, Any]]:
    with gzip.open(bf.path, "rt", encoding="utf-8") as fh:
        body = json.load(fh)
    rows = body.get("results") or []
    return [r for r in rows if isinstance(r, dict)]


def _last_completed_session_et(now: datetime | None = None) -> date:
    """Yesterday in America/New_York — never the (possibly incomplete) current session."""
    n = (now or datetime.now(UTC)).astimezone(ZoneInfo("America/New_York"))
    return n.date() - timedelta(days=1)


def archive_session(
    session: Session,
    client: GroupedDailyClient,
    session_date: date,
    *,
    source: str = DEFAULT_SOURCE,
) -> BulkFile:
    """Fetch + store one session's grouped payload. Idempotent: an existing
    ``ok``/``empty`` row is returned untouched; a ``failed`` row is retried."""
    existing = session.scalar(
        select(BulkFile).where(BulkFile.source == source, BulkFile.session_date == session_date)
    )
    if existing is not None and existing.status in ("ok", "empty"):
        return existing
    # The existence check above opened a transaction; close it so the paced
    # network fetch below runs with NO lock held (write intent re-engages
    # at the first write after the fetch).
    session.commit()

    fetched_at = datetime.now(UTC)
    try:
        text = client.fetch_grouped(session_date)
        body = json.loads(text)
        rows = body.get("results") or []
        count = int(body.get("resultsCount") or len(rows))
    except (AdapterError, ValueError) as exc:
        row = existing or BulkFile(
            source=source,
            session_date=session_date,
            path="",
            sha256="",
            bytes_gz=0,
            bytes_raw=0,
            row_count=0,
            adjusted_as_of=fetched_at.date(),
            fetched_at=fetched_at,
        )
        row.status = "failed"
        row.detail = str(exc)[:300]
        row.fetched_at = fetched_at
        if existing is None:
            session.add(row)
        session.flush()
        raise

    if count == 0 or not rows:
        row = existing or BulkFile(source=source, session_date=session_date, path="", sha256="")
        row.bytes_gz = 0
        row.bytes_raw = len(text.encode("utf-8"))
        row.row_count = 0
        row.adjusted_as_of = fetched_at.date()
        row.fetched_at = fetched_at
        row.status = "empty"
        row.detail = "no results (holiday / non-session)"
        if existing is None:
            session.add(row)
        session.flush()
        return row

    path = archive_dir() / f"{session_date.isoformat()}.json.gz"
    raw = text.encode("utf-8")
    with gzip.open(path, "wb", compresslevel=6) as fh:
        fh.write(raw)
    row = existing or BulkFile(source=source, session_date=session_date)
    row.path = str(path)
    row.sha256 = hashlib.sha256(raw).hexdigest()
    row.bytes_gz = path.stat().st_size
    row.bytes_raw = len(raw)
    row.row_count = len(rows)
    row.adjusted_as_of = fetched_at.date()
    row.fetched_at = fetched_at
    row.status = "ok"
    row.detail = ""
    if existing is None:
        session.add(row)
    session.flush()
    return row


def reindex_archive(session: Session, *, source: str = DEFAULT_SOURCE) -> int:
    """Re-create ``BulkFile`` rows for gz files already on disk that have no
    index row (e.g. a later step failed and rolled the transaction back).
    Cheap: only unindexed files are parsed. Returns the number re-indexed."""
    indexed = {
        d
        for (d,) in session.execute(
            select(BulkFile.session_date).where(BulkFile.source == source)
        ).all()
    }
    n = 0
    for path in sorted(archive_dir().glob("*.json.gz")):
        try:
            d = date.fromisoformat(path.stem.replace(".json", ""))
        except ValueError:
            continue
        if d in indexed:
            continue
        try:
            with gzip.open(path, "rb") as fh:
                raw = fh.read()
            body = json.loads(raw)
            rows = body.get("results") or []
        except (OSError, ValueError):
            continue
        if not rows:
            continue
        mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
        session.add(
            BulkFile(
                source=source,
                session_date=d,
                path=str(path),
                sha256=hashlib.sha256(raw).hexdigest(),
                bytes_gz=path.stat().st_size,
                bytes_raw=len(raw),
                row_count=len(rows),
                adjusted_as_of=mtime.date(),
                fetched_at=mtime,
                status="ok",
                detail="re-indexed from disk",
            )
        )
        n += 1
    if n:
        session.flush()
        _log.info("universe.reindex_archive", reindexed=n)
    return n


@dataclass(slots=True)
class BackfillReport:
    fetched: int = 0
    skipped_existing: int = 0
    empty: int = 0
    failed: int = 0
    sessions_archived: int = 0
    archive_bytes: int = 0
    seconds: float = 0.0
    stopped_reason: str = ""
    failures: list[str] = field(default_factory=list)


def backfill(
    session: Session,
    client: GroupedDailyClient,
    *,
    sessions: int,
    runtime_budget_s: float,
    storage_budget_bytes: int,
    source: str = DEFAULT_SOURCE,
    now: datetime | None = None,
    deadline: float | None = None,
) -> BackfillReport:
    """Walk back from the last completed session until ``sessions`` OK files
    exist, stopping cleanly at the runtime or storage budget. Re-runs resume
    (existing ok/empty rows are skipped without a request).

    The walk always TOPS UP first: it fetches every session newer than the
    most recent archived one before the ``sessions`` target is consulted.
    Incident 2026-09-09..10-24: the loop was gated on ``len(have) < sessions``
    alone, so once the archive held 420 files no new session was ever fetched,
    the archive froze at 2026-09-08 and the screen kept re-reading it."""
    t0 = time.monotonic()
    deadline = deadline if deadline is not None else t0 + runtime_budget_s
    rep = BackfillReport()
    reindex_archive(session, source=source)
    have = set(archived_sessions(session, source=source))
    known: dict[date, str] = dict(
        session.execute(
            select(BulkFile.session_date, BulkFile.status).where(BulkFile.source == source)
        ).all()  # type: ignore[arg-type]
    )
    d = _last_completed_session_et(now)
    walked = 0
    max_walk = max(_MIN_LOOKBACK_DAYS, int(sessions * 1.6) + 30)  # ~252 sessions/365 days
    # Topped up once the walk reaches an already-archived session; an empty
    # index has nothing newer to top up to.
    topped_up = not any(v in ("ok", "empty") for v in known.values())
    while (len(have) < sessions or not topped_up) and walked < max_walk:
        walked += 1
        cur = d
        d -= timedelta(days=1)
        if cur.weekday() >= 5:
            continue
        if known.get(cur) in ("ok", "empty"):
            topped_up = True
            rep.skipped_existing += 1
            if known[cur] == "ok":
                have.add(cur)
            continue
        if time.monotonic() > deadline:
            rep.stopped_reason = "runtime budget reached"
            break
        if archive_bytes(session, source=source) >= storage_budget_bytes:
            rep.stopped_reason = "storage budget reached"
            break
        try:
            row = archive_session(session, client, cur, source=source)
            # one short write transaction per archived session — never hold the
            # SQLite write lock across the next paced HTTP request
            session.commit()
        except (AdapterError, ValueError) as exc:
            session.commit()  # persist the 'failed' index row, release the lock
            rep.failed += 1
            rep.failures.append(f"{cur.isoformat()}: {exc}")
            if rep.failed >= 3:
                rep.stopped_reason = "3 consecutive fetch failures"
                break
            continue
        if row.status == "ok":
            rep.fetched += 1
            have.add(cur)
        else:
            rep.empty += 1
    if not rep.stopped_reason and len(have) < sessions:
        rep.stopped_reason = "lookback limit reached"
    rep.sessions_archived = len(have)
    rep.archive_bytes = archive_bytes(session, source=source)
    rep.seconds = round(time.monotonic() - t0, 1)
    _log.info(
        "universe.backfill",
        fetched=rep.fetched,
        skipped=rep.skipped_existing,
        empty=rep.empty,
        failed=rep.failed,
        sessions=rep.sessions_archived,
        stopped=rep.stopped_reason,
    )
    return rep
