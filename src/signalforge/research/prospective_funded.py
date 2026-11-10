"""Append-only, separately frozen forward books; no operating/study DB imports."""

from __future__ import annotations

import difflib
import hashlib
import json
import os
import tempfile
from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import asdict, replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, cast

from signalforge.backtest.actions import Dividend, Split, TickerChange
from signalforge.backtest.engine import EntrySignal, SignalFn
from signalforge.data.calendar import sessions
from signalforge.data.series import PriceSeries
from signalforge.domain import Direction
from signalforge.research import action_replay
from signalforge.research.action_replay import ActionDataset
from signalforge.research.strategy_scope import resolve_strategy_scope

# Collection-protocol code: how sessions are recorded, how vendor bar revisions are
# quarantined and how missed sessions are blocked. An operator amendment may change
# only these digest inputs; every other frozen input (strategies, the action-aware
# replay and its costs/risk limits, data and calendar code) must stay byte-identical.
COLLECTOR_PROTOCOL_FILES = (
    "research/prospective_funded.py",
    "scripts/funded_forward.py",
)
# Frozen report fields that every collection must repeat exactly.
FROZEN_REPORT_FIELDS = ("metadata", "risk_limits", "drawdown_entry_halt_pct")
FROZEN_SCENARIO_FIELDS = ("cost_model", "spread_bps")

InputKey = tuple[str, str, str]  # (bar|split|dividend, symbol, ISO session)


def _digest_inputs() -> dict[str, Path]:
    root = Path(__file__).resolve().parents[1]
    paths: set[Path] = set()
    for directory in ("research", "backtest", "risk", "config"):
        paths.update((root / directory).rglob("*.py"))
    paths.update(
        root / p
        for p in ("data/series.py", "data/calendar.py", "domain.py", "data/accounting_snapshot.py")
    )
    inputs = {str(path.relative_to(root)): path for path in sorted(paths)}
    repo = root.parents[1]
    for name in ("scripts/funded_forward.py", "scripts/action_replay_report.py", "uv.lock"):
        inputs[name] = repo / name
    return inputs


def code_digest(overrides: Mapping[str, bytes] | None = None) -> str:
    """Frozen-code identity; ``overrides`` substitutes named inputs (amendment proof)."""
    inputs = _digest_inputs()
    overrides = overrides or {}
    if set(overrides) - set(inputs):
        raise ValueError("Unknown code digest input")
    h = hashlib.sha256()
    for name, path in inputs.items():
        h.update(name.encode())
        h.update(overrides[name] if name in overrides else path.read_bytes())
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


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def accepted_code_digest(root: Path) -> str:
    """Frozen digest, advanced only by an unbroken chain of operator amendments."""
    plan_bytes = (root / "plan.json").read_bytes()
    digest = cast(str, json.loads(plan_bytes)["code_digest"])
    amendments = root / "amendments"
    paths = sorted(amendments.glob("*.json")) if amendments.exists() else []
    for sequence, path in enumerate(paths, 1):
        amendment = json.loads(path.read_text())
        if (
            amendment["sequence"] != sequence
            or amendment["plan_sha256"] != _sha256(plan_bytes)
            or amendment["from_code_digest"] != digest
        ):
            raise ValueError("Frozen forward code amendment chain is broken; collector halted")
        digest = amendment["to_code_digest"]
    return digest


def validate_plan(root: Path) -> dict[str, Any]:
    plan: dict[str, Any] = json.loads((root / "plan.json").read_text())
    if code_digest() != accepted_code_digest(root):
        raise ValueError("Frozen forward code changed; collector halted, create a new study")
    return plan


def amend_collector(
    root: Path,
    previous_sources: Mapping[str, bytes],
    reason: str,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Operator-only, append-only acceptance of a collection-protocol code change.

    ``previous_sources`` are the collector protocol files of the currently accepted
    code. Substituting them back must reproduce the accepted digest exactly. That
    proves only that every input OUTSIDE ``COLLECTOR_PROTOCOL_FILES`` is unchanged
    (strategies, the action-aware replay with its costs and risk limits, data code);
    the protocol files themselves (record checks, review counting, kill-switch calls)
    may change, so their full unified diffs are stored in the amendment for audit.
    The plan (universe, strategies, decision rules, review floors) is never rewritten,
    and each collection must still repeat the first record's books and cost/risk
    configuration exactly.
    """
    accepted = accepted_code_digest(root)
    current = code_digest()
    if not reason.strip():
        raise ValueError("Amendment requires an operator reason")
    if set(previous_sources) != set(COLLECTOR_PROTOCOL_FILES):
        raise ValueError("Amendment requires every accepted collector protocol file")
    if current == accepted:
        raise ValueError("Amendment refused: accepted code is unchanged")
    if code_digest(previous_sources) != accepted:
        raise ValueError(
            "Amendment refused: code outside the collector protocol changed, "
            "or the previous sources are not the accepted code"
        )
    inputs = _digest_inputs()
    changed = {}
    for name in COLLECTOR_PROTOCOL_FILES:
        before, after = previous_sources[name], inputs[name].read_bytes()
        if before == after:
            continue
        diff = difflib.unified_diff(
            before.decode(errors="replace").splitlines(keepends=True),
            after.decode(errors="replace").splitlines(keepends=True),
            f"accepted/{name}",
            f"amended/{name}",
        )
        changed[name] = {
            "accepted_sha256": _sha256(before),
            "amended_sha256": _sha256(after),
            "unified_diff": "".join(diff),
        }
    directory = root / "amendments"
    sequence = len(list(directory.glob("*.json"))) + 1 if directory.exists() else 1
    value = {
        "schema": "funded-forward-amendment-v1",
        "sequence": sequence,
        "created_at": (now or datetime.now(UTC)).isoformat(),
        "plan_sha256": _sha256((root / "plan.json").read_bytes()),
        "from_code_digest": accepted,
        "to_code_digest": current,
        "changed_files": changed,
        "unchanged": (
            "Every frozen code input outside the changed collector protocol files "
            "(strategies, action-aware replay, costs, risk limits, data code) is "
            "byte-identical to the accepted code. The protocol file changes are the "
            "unified diffs above and are not proven harmless by the digest."
        ),
        "reason": reason.strip(),
        "disclaimer": "Research signal only — no order was placed.",
    }
    write_once(directory / f"{sequence:04d}.json", value)
    return value


def _event_record(event: Split | Dividend) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(json.dumps(asdict(event), default=str, sort_keys=True)))


def input_rows(dataset: ActionDataset, through: date) -> dict[InputKey, Any]:
    """Replay inputs on or before ``through``: OHLCV per bar, events per effective day."""
    rows: dict[InputKey, Any] = {}
    for symbol, bars in dataset.series.items():
        for i, day in enumerate(bars.dates):
            if day <= through:
                rows[("bar", symbol, str(day))] = [
                    float(a[i]) for a in (bars.open, bars.high, bars.low, bars.close, bars.volume)
                ]
    for event in dataset.splits:
        if event.day <= through:
            rows.setdefault(("split", event.symbol, str(event.day)), []).append(
                _event_record(event)
            )
    for dividend in dataset.dividends:
        if dividend.ex_date <= through:
            key = ("dividend", dividend.symbol, str(dividend.ex_date))
            rows.setdefault(key, []).append(_event_record(dividend))
    return rows


def apply_retained(dataset: ActionDataset, retained: Mapping[InputKey, Any]) -> ActionDataset:
    """Restore first-recorded bars (``None`` = absent) over a later vendor snapshot."""
    if not retained:
        return dataset
    if any(k != "bar" for k, _, _ in retained):
        raise ValueError("Previously collected raw inputs changed; only bars are retained")
    if any(s not in dataset.series for _, s, _ in retained):
        raise ValueError("Previously collected raw inputs changed; retained symbol missing")
    series = dict(dataset.series)
    for symbol, bars in dataset.series.items():
        pins = {d: v for (k, s, d), v in retained.items() if k == "bar" and s == symbol}
        if not pins:
            continue
        rows = {
            str(day): [
                float(a[i]) for a in (bars.open, bars.high, bars.low, bars.close, bars.volume)
            ]
            for i, day in enumerate(bars.dates)
        }
        for day, value in pins.items():
            if value is None:
                rows.pop(day, None)
            else:
                rows[day] = value
        series[symbol] = PriceSeries.from_bars(
            symbol,
            [(date.fromisoformat(d), v[0], v[1], v[2], v[3], v[4]) for d, v in rows.items()],
        )
    return replace(dataset, series=series)


def retain_recorded_inputs(
    vendor: ActionDataset,
    previous_vendor: ActionDataset,
    retained: Mapping[InputKey, Any],
    previous_through: date,
) -> tuple[ActionDataset, list[dict[str, Any]]]:
    """Quarantine vendor revisions of already-recorded bars.

    Every OHLCV bar on or before ``previous_through`` keeps the value first recorded
    by the study; the revised vendor value is returned as an auditable revision event
    and is never applied, so prior decisions, fills and marks cannot change. A split
    or dividend added, removed or changed on or before ``previous_through`` still
    fails closed: share and cash accounting would otherwise run on known-wrong events.
    """
    if set(vendor.series) != set(previous_vendor.series):
        raise ValueError("Previously collected raw inputs changed; symbol coverage differs")
    new = input_rows(vendor, previous_through)
    old = input_rows(previous_vendor, previous_through)
    kept: dict[InputKey, Any] = dict(retained)
    events = []
    for key in sorted(set(new) | set(old)):
        if new.get(key) == old.get(key):
            continue
        if key[0] != "bar":
            raise ValueError(
                "Previously collected raw inputs changed; corporate event revised "
                "on or before the last recorded session"
            )
        events.append(
            {
                "kind": key[0],
                "symbol": key[1],
                "day": key[2],
                "vendor_previous": old.get(key),
                "vendor_revised": new.get(key),
                "retained": kept.setdefault(key, old.get(key)),
            }
        )
    return apply_retained(vendor, kept), events


def entry_signal_days(missed: Iterable[date]) -> frozenset[date]:
    """Close-signal sessions whose entries a gap makes retroactive.

    For each missed session ``D`` the replay must not fill: entries at ``D``'s open
    (signalled at the close before ``D``) or entries at the next session's open
    (signalled at ``D``'s close, which no collection recorded before that open).
    """
    days: set[date] = set()
    for day in missed:
        if sessions(day, day) != (day,):
            raise ValueError("Blocked entry day is not a market session")
        days.add(sessions(day - timedelta(days=10), day - timedelta(days=1))[-1])
        days.add(day)
    return frozenset(days)


def without_entries_on(fn: SignalFn, signal_days: frozenset[date]) -> SignalFn:
    """Drops LONG entry signals generated on ``signal_days``; nothing else changes.

    A dropped long signal never becomes a pending next-open entry. Non-long signals
    still reach the replay unchanged: their ``long_only`` records on already-recorded
    sessions must keep matching the earlier collections.
    """

    def _fn(series: PriceSeries, t: int) -> EntrySignal | None:
        sig = fn(series, t)
        if sig is not None and sig.direction is Direction.LONG and series.dates[t] in signal_days:
            return None
        return sig

    return _fn


@contextmanager
def entries_blocked(signal_days: frozenset[date]) -> Iterator[None]:
    """Wraps every replay signal function for one ``action_replay.compare`` call.

    ``action_replay`` (compare, costs, risk limits, strategy loop) stays byte-identical
    to the frozen code, so it is not an amendable collector file; the block is applied
    from here by substituting the module's ``signal_fn_for`` and always restoring it.
    """
    original = action_replay.signal_fn_for

    def _wrapped(*args: Any, **kwargs: Any) -> SignalFn:
        return without_entries_on(original(*args, **kwargs), signal_days)

    action_replay.signal_fn_for = _wrapped
    try:
        yield
    finally:
        action_replay.signal_fn_for = original


def forward_compare(
    dataset: ActionDataset,
    plan: Mapping[str, Any],
    blocked_entry_sessions: tuple[date, ...],
) -> dict[str, Any]:
    """The frozen ``compare`` with no entries from any missed session's signals."""
    signal_days = entry_signal_days(blocked_entry_sessions)
    with entries_blocked(signal_days):
        report = action_replay.compare(
            dataset,
            plan["metadata"],
            entry_start=date.fromisoformat(plan["first_entry_session"]),
            evaluation_start=date.fromisoformat(plan["first_observation_session"]),
            prospective=True,
            strategy_specs=plan["strategies"],
        )
    if blocked_entry_sessions:
        report["blocked_entry_sessions"] = [str(d) for d in blocked_entry_sessions]
        report["entry_blocked_signal_days"] = sorted(str(d) for d in signal_days)
    return report


def _check_no_stale_entries(report: Mapping[str, Any], signal_days: frozenset[date]) -> None:
    stale = {str(d) for d in signal_days}
    for book in report["books"].values():
        for outcome in book["scenarios"].values():
            for fill in outcome["result"]["fills"]:
                if fill["side"] == "buy" and fill.get("signal_day") in stale:
                    raise ValueError(
                        "Missed sessions were not blocked from entries; no retroactive trading"
                    )


def _spec(book: Mapping[str, Any]) -> dict[str, Any]:
    # git_sha is runtime provenance of the running checkout, not a decision rule.
    return {k: v for k, v in (book.get("strategy_spec") or {}).items() if k != "git_sha"}


def _check_frozen_configuration(report: Mapping[str, Any], last: Mapping[str, Any]) -> None:
    """Books, strategy specs, costs and risk limits must repeat the last record exactly."""
    old = json.loads(json.dumps(last["report"], default=str))
    new = json.loads(json.dumps(report, default=str))
    if set(new["books"]) != set(old["books"]) or any(
        new.get(k) != old.get(k) for k in FROZEN_REPORT_FIELDS
    ):
        raise ValueError("Previously collected book configuration changed; no rewrite")
    for name, book in old["books"].items():
        if (
            set(new["books"][name]["scenarios"]) != set(book["scenarios"])
            or _spec(new["books"][name]) != _spec(book)
            or any(
                new["books"][name]["scenarios"][label].get(k) != scenario.get(k)
                for label, scenario in book["scenarios"].items()
                for k in FROZEN_SCENARIO_FIELDS
            )
        ):
            raise ValueError("Previously collected book configuration changed; no rewrite")


def collection_state(root: Path, through: date) -> dict[str, Any]:
    """What the next collection must honour: missed sessions and retained inputs."""
    plan = validate_plan(root)
    records = root / "collections"
    paths = sorted(records.glob("*.json")) if records.exists() else []
    last = json.loads(paths[-1].read_text()) if paths else None
    if last is not None and last["through"] >= str(through):
        raise ValueError("Out-of-order collection")
    expected = date.fromisoformat(plan["first_observation_session"])
    if last is not None:
        day = date.fromisoformat(last["through"])
        expected = sessions(day + timedelta(days=1), day + timedelta(days=10))[0]
    if through < expected:
        raise ValueError("Collection is outside prospective observation window")
    missed = [d for d in sessions(expected, through) if d != through]
    prior = (last or {}).get("blocked_entry_sessions", [])
    return {
        "last": last,
        "previous_through": last["through"] if last else None,
        "missed": missed,
        "blocked": tuple(sorted({date.fromisoformat(d) for d in prior} | set(missed))),
        "retained": {
            (r["kind"], r["symbol"], r["day"]): r["value"]
            for r in (last or {}).get("retained_inputs", [])
        },
    }


def record_collection(
    root: Path,
    through: date,
    report: dict[str, Any],
    *,
    vendor_revisions: Iterable[dict[str, Any]] = (),
    collected_at: datetime | None = None,
) -> dict[str, Any]:
    """Append one session. Missed sessions are recorded, never backfilled or traded.

    A gap since the last record is listed as missed. The report must admit no entry
    signalled on the close before a missed session or on a missed session's own close
    (``entry_signal_days``), so nothing is filled on a signal no collection recorded.
    Vendor bar revisions arrive already quarantined: the raw-input fingerprint and
    prior decisions, fills, marks and corporate events must still match exactly, and
    books, strategy specs, costs and risk limits must repeat the last record exactly,
    otherwise the study stops (no rewrite).
    """
    plan = validate_plan(root)
    first = date.fromisoformat(plan["first_observation_session"])
    if through < first or through.isoformat() != report["end"]:
        raise ValueError("Collection is outside prospective observation window")
    elapsed = sessions(first, through)
    if len(elapsed) > plan["maximum_sessions"]:
        raise ValueError("Planned collection horizon completed; review required")
    path = root / "collections" / f"{through}.json"
    if path.exists():
        saved = json.loads(path.read_text())
        if saved["report"] != json.loads(json.dumps(report, default=str)):
            raise ValueError("Cannot rewrite a forward collection")
        return cast(dict[str, Any], saved)
    state = collection_state(root, through)
    blocked = [str(d) for d in state["blocked"]]
    if report.get("blocked_entry_sessions", []) != blocked:
        raise ValueError("Missed sessions were not blocked from entries; no retroactive trading")
    signal_days = entry_signal_days(state["blocked"])
    _check_no_stale_entries(report, signal_days)
    last = state["last"]
    revisions = [dict(r) for r in vendor_revisions]
    if revisions and (last is None or any(r["day"] > last["through"] for r in revisions)):
        raise ValueError("Previously collected raw inputs changed outside recorded history")
    if any(r["kind"] != "bar" for r in revisions):
        raise ValueError("Previously collected raw inputs changed; only bars are retained")
    if last is not None:
        _check_frozen_configuration(report, last)
        if (
            report["input_prefix_fingerprints"][last["through"]]
            != last["report"]["input_prefix_fingerprints"][last["through"]]
        ):
            raise ValueError("Previously collected raw inputs changed; no rewrite")
        # Changed decisions are a block, never a retrospective rewrite.
        for book, entry in last["report"]["books"].items():
            for label, outcome in entry["scenarios"].items():
                new = report["books"][book]["scenarios"][label]["result"]
                old = outcome["result"]
                for key in ("marks", "fills", "decisions", "corporate_events"):
                    prefix = [r for r in new[key] if r["day"] <= last["through"]]
                    if prefix != old[key]:
                        raise ValueError("Previously collected history changed; no rewrite")
    retained = dict(state["retained"])
    for r in revisions:
        retained.setdefault((r["kind"], r["symbol"], r["day"]), r["retained"])
    value = {
        "through": str(through),
        "collected_at": (collected_at or datetime.now(UTC)).isoformat(),
        "plan_sha256": _sha256((root / "plan.json").read_bytes()),
        "code_digest": accepted_code_digest(root),
        "elapsed_sessions": len(elapsed),
        # Missed sessions are not observations: review floors count only recorded ones.
        "observed_sessions": len(elapsed) - len(blocked),
        "missed_sessions": [str(d) for d in state["missed"]],
        "blocked_entry_sessions": blocked,
        "entry_blocked_signal_days": sorted(str(d) for d in signal_days),
        "vendor_revisions": revisions,
        "retained_inputs": [
            {"kind": k, "symbol": s, "day": d, "value": v}
            for (k, s, d), v in sorted(retained.items())
        ],
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
        "missed_sessions": latest.get("blocked_entry_sessions", []),
        "retained_vendor_revisions": len(latest.get("retained_inputs", [])),
        "books": books,
        "automatic_promotion": False,
        "disclaimer": "Research signal only — no order was placed.",
    }
