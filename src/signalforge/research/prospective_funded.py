"""Append-only, separately frozen forward books; no operating/study DB imports."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, cast

from signalforge.backtest.actions import TickerChange
from signalforge.data.calendar import sessions
from signalforge.research.strategy_scope import resolve_strategy_scope


def code_digest() -> str:
    root = Path(__file__).resolve().parents[1]
    paths: set[Path] = set()
    for directory in ("research", "backtest", "risk", "config"):
        paths.update((root / directory).rglob("*.py"))
    paths.update(
        root / p
        for p in ("data/series.py", "data/calendar.py", "domain.py", "data/accounting_snapshot.py")
    )
    h = hashlib.sha256()
    for path in sorted(paths):
        h.update(str(path.relative_to(root)).encode())
        h.update(path.read_bytes())
    repo = root.parents[1]
    for name in ("scripts/funded_forward.py", "scripts/action_replay_report.py", "uv.lock"):
        h.update(name.encode())
        h.update((repo / name).read_bytes())
    return h.hexdigest()


def write_once(path: Path, value: dict[str, Any]) -> None:
    """Exclusive creation; a different prior record is never overwritten."""
    content = json.dumps(value, default=str, sort_keys=True, indent=2)
    if path.exists():
        if path.read_text() != content:
            raise ValueError("Immutable record conflict")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as f:
        temp = Path(f.name)
        f.write(content)
        f.flush()
        os.fsync(f.fileno())
    try:
        try:
            os.link(temp, path)  # atomic exclusive installation; never overwrites
        except FileExistsError:
            if path.read_text() != content:
                raise ValueError("Immutable record conflict") from None
    finally:
        temp.unlink()


def freeze(
    root: Path,
    metadata: dict[str, dict[str, str]],
    changes: tuple[TickerChange, ...],
    symbols: list[str],
    start: date,
    *,
    now: datetime | None = None,
    strategy_specs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    from dataclasses import asdict
    from zoneinfo import ZoneInfo

    selected = resolve_strategy_scope(strategy_specs)
    now = now or datetime.now(UTC)
    today = now.astimezone(ZoneInfo("America/New_York")).date()
    future = sessions(today + timedelta(days=1), today + timedelta(days=10))
    first, entry = future[0], future[1]
    if (root / "plan.json").exists():
        raise ValueError("Plan exists; never refreeze against observed outcomes")
    changes = tuple(c for c in changes if c.old in symbols and c.new in symbols)
    metadata = {s: metadata[s] for s in symbols if s not in {c.old for c in changes}}
    plan = {
        "schema": "funded-forward-v1",
        "created_at": now.isoformat(),
        "first_observation_session": str(first),
        "first_entry_session": str(entry),
        "history_start": str(start),
        "code_digest": code_digest(),
        "metadata": metadata,
        "symbols": symbols,
        "ticker_changes": [asdict(c) for c in changes],
        "strategies": [asdict(s.spec()) for s in selected],
        "capital_per_book_usd": "10000",
        "minimum_sessions_before_review": 126,
        "minimum_closed_trades_per_book": 30,
        "minimum_trend_regimes": 2,
        "minimum_trades_per_regime": 10,
        "maximum_sessions": 252,
        "cache_cap_bytes": 2 * 1024**3,
        "policy": "All five daily baselines; base/stress costs; no tuning or auto-promotion.",
        "disclaimer": "Research signal only — no order was placed.",
    }
    write_once(root / "plan.json", plan)
    return cast(dict[str, Any], json.loads((root / "plan.json").read_text()))


def validate_plan(root: Path) -> dict[str, Any]:
    plan: dict[str, Any] = json.loads((root / "plan.json").read_text())
    if plan["code_digest"] != code_digest():
        raise ValueError("Frozen forward code changed; collector halted, create a new study")
    return plan


def record_collection(
    root: Path, through: date, report: dict[str, Any], *, collected_at: datetime | None = None
) -> dict[str, Any]:
    plan = validate_plan(root)
    first = date.fromisoformat(plan["first_observation_session"])
    if through < first or through.isoformat() != report["end"]:
        raise ValueError("Collection is outside prospective observation window")
    elapsed = sessions(first, through)
    if len(elapsed) > plan["maximum_sessions"]:
        raise ValueError("Planned collection horizon completed; review required")
    records = root / "collections"
    previous = sorted(records.glob("*.json")) if records.exists() else []
    path = records / f"{through}.json"
    if path.exists():
        saved = json.loads(path.read_text())
        if saved["report"] != json.loads(json.dumps(report, default=str)):
            raise ValueError("Cannot rewrite a forward collection")
        return cast(dict[str, Any], saved)
    expected = first
    if previous:
        last_day = date.fromisoformat(previous[-1].stem)
        expected = sessions(last_day + timedelta(days=1), last_day + timedelta(days=10))[0]
    if through != expected:
        raise ValueError(
            "Missing prospective session; retrospective backfill is not forward evidence"
        )
    if previous:
        last = json.loads(previous[-1].read_text())
        if last["through"] >= str(through):
            raise ValueError("Out-of-order collection")
        if (
            report["input_prefix_fingerprints"][last["through"]]
            != last["report"]["input_prefix_fingerprints"][last["through"]]
        ):
            raise ValueError("Previously collected raw inputs changed; no rewrite")
        # Revisions or changed decisions are a block, never a retrospective rewrite.
        for book, entry in last["report"]["books"].items():
            for label, outcome in entry["scenarios"].items():
                new = report["books"][book]["scenarios"][label]["result"]
                old = outcome["result"]
                for key in ("marks", "fills", "decisions", "corporate_events"):
                    prefix = [r for r in new[key] if r["day"] <= last["through"]]
                    if prefix != old[key]:
                        raise ValueError("Previously collected history changed; no rewrite")
    value = {
        "through": str(through),
        "collected_at": (collected_at or datetime.now(UTC)).isoformat(),
        "plan_sha256": hashlib.sha256((root / "plan.json").read_bytes()).hexdigest(),
        "observed_sessions": len(elapsed),
        "status": "COLLECTING_UNVALIDATED",
        "report": report,
    }
    write_once(path, value)
    return value


def review_readiness(root: Path) -> dict[str, Any]:
    """Counts only until all preregistered review floors pass; never auto-promotes."""
    plan = validate_plan(root)
    records = sorted((root / "collections").glob("*.json"))
    if not records:
        return {
            "status": "WAITING_FOR_FUTURE_EVIDENCE",
            "observed_sessions": 0,
            "first_observation_session": plan["first_observation_session"],
        }
    latest = json.loads(records[-1].read_text())
    books = {}
    for name, book in latest["report"]["books"].items():
        for scenario, outcome in book["scenarios"].items():
            opens = {}
            regimes: dict[str, int] = {}
            closed = 0
            for fill in outcome["result"]["fills"]:
                if fill["side"] == "buy":
                    opens[fill["symbol"]] = fill
                else:
                    buy = opens.pop(fill["symbol"])
                    regime = latest["report"]["regime_by_session"][buy["signal_day"]]["trend"]
                    regimes[regime] = regimes.get(regime, 0) + 1
                    closed += 1
            ready = (
                latest["observed_sessions"] >= plan["minimum_sessions_before_review"]
                and closed >= plan["minimum_closed_trades_per_book"]
                and sum(n >= plan["minimum_trades_per_regime"] for n in regimes.values())
                >= plan["minimum_trend_regimes"]
            )
            books[f"{name}/{scenario}"] = {
                "closed_trades": closed,
                "regime_counts": regimes,
                "status": "EVIDENCE_REVIEW_REQUIRED" if ready else "INSUFFICIENT_EVIDENCE",
            }
    return {
        "status": "UNVALIDATED",
        "observed_sessions": latest["observed_sessions"],
        "books": books,
        "automatic_promotion": False,
        "disclaimer": "Research signal only — no order was placed.",
    }
