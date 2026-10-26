"""Prospective comparison books, using the unchanged paper ledger in a PRIVATE DB.

No scheduler registration, source writes, alerts, execution imports or promotion.
The experiment manifest, model calls and book choices are append-only.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import math
import sqlite3
from dataclasses import asdict
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, Table, create_engine, event, func, select, text
from sqlalchemy.orm import Session

from signalforge.data.calendar import last_closed_session, rth_bounds_utc, sessions
from signalforge.db.base import Base
from signalforge.db.models import (
    Candidate,
    Instrument,
    OHLCVDaily,
    PaperAccount,
    PaperFill,
    PaperOrder,
    PaperPosition,
    ScanRun,
    StrategyVersion,
)
from signalforge.domain import Direction, Horizon, QualityGate, StrategyStatus
from signalforge.killswitch import ensure_not_engaged
from signalforge.kronos.shadow import forecast, inputs
from signalforge.paper.auto_simulate import _has_open_position, accepted_today, max_per_day
from signalforge.paper.ledger import _acceptance_freshness, accept_candidate, mark_to_market
from signalforge.research.approval_scope import (
    approved_scopes,
    current_spec_json_hash,
    scan_scope_matches,
)
from signalforge.settings_store import effective_research_config, set_setting

PROTOCOL = "kronos-comparison-v1"
ARMS = ("baseline", "filtered", "matched")
NOTICE = "Research signal only — no order was placed."
ROOT = Path(__file__).resolve().parents[3]
PARENTS = {"candidate", "instrument", "scan_run", "strategy_version", "strategy", "data_snapshot"}


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def file_hash(path: Path) -> str:
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def artifacts(roots: list[Path]) -> dict[str, str]:
    result = {}
    for root in roots:
        if not root.exists():
            raise ValueError("Required pinned artifact is unavailable")
        paths = sorted(p for p in root.rglob("*") if p.is_file()) if root.is_dir() else [root]
        paths = [p for p in paths if "__pycache__" not in p.parts and p.suffix != ".pyc"]
        if not paths or len(paths) > 20000:
            raise ValueError("Invalid artifact inventory")
        for p in paths:
            result[str(p.absolute())] = file_hash(p)
    return result


def code_hash() -> str:
    paths: list[Path] = []
    for package in ("paper", "config", "experiments", "kronos", "data", "db", "research", "risk"):
        paths.extend((ROOT / "src/signalforge" / package).rglob("*.py"))
    paths.extend(
        [
            ROOT / "uv.lock",
            ROOT / "pyproject.toml",
            ROOT / "scripts/kronos_comparison.py",
            ROOT / "docs/KRONOS-COMPARISON-PLAN.md",
            ROOT / "src/signalforge/domain.py",
            ROOT / "src/signalforge/settings_store.py",
        ]
    )
    return digest({str(p.relative_to(ROOT)): file_hash(p) for p in sorted(paths)})


def source_engine(path: Path) -> Engine:
    if not path.is_file():
        raise ValueError("Source database must exist")
    engine = create_engine("sqlite:///" + path.resolve().as_uri() + "?mode=ro&uri=true")

    @event.listens_for(engine, "connect")
    def readonly_connection(connection: Any, record: Any) -> None:
        connection.isolation_level = None

    @event.listens_for(engine, "begin")
    def snapshot(connection: Any) -> None:
        # SQLite legacy mode otherwise does not BEGIN on SELECT: a source
        # writer could change rows between reads in one logical Session.
        connection.exec_driver_sql("BEGIN")

    return engine


def _private_engine(path: Path) -> Engine:
    engine = create_engine("sqlite:///" + str(path))

    @event.listens_for(engine, "connect")
    def configure(connection: Any, record: Any) -> None:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA max_page_count=65536")

    return engine


def _scopes_hash(session: Session, version: int) -> str:
    return digest(
        json.loads(
            json.dumps([asdict(s) for s in approved_scopes(session, version)], default=sorted)
        )
    )


def freeze(
    source: Path,
    directory: Path,
    model_roots: list[Path],
    *,
    horizon: Horizon = Horizon.SHORT_SWING,
) -> dict[str, Any]:
    """Create once; no inference and no historical outcomes are evaluated."""
    if horizon not in (Horizon.SHORT_SWING, Horizon.MEDIUM_SWING):
        raise ValueError("Only daily short and medium swing experiments")
    if directory.exists():
        raise ValueError("Experiment directory must be new")
    if len(model_roots) < 3:
        raise ValueError("Pin model weights, tokenizer and model implementation")
    pinned = artifacts(model_roots)
    src = source_engine(source)
    try:
        with Session(src) as s:
            cfg = effective_research_config(s)
            daily_cap = max_per_day(s)
            versions = {
                str(v.id): digest(v.spec_json)
                for v in s.scalars(
                    select(StrategyVersion).where(
                        StrategyVersion.status == StrategyStatus.PAPER_APPROVED
                    )
                )
                if v.strategy.horizon == horizon
                and v.strategy.status == StrategyStatus.PAPER_APPROVED
            }
            scopes = {v: _scopes_hash(s, int(v)) for v in versions}
    finally:
        src.dispose()
    if not versions:
        raise ValueError("No approved strategy versions for this horizon")
    frozen_at = datetime.now(UTC)
    study_days = [
        d
        for d in sessions(frozen_at.date(), frozen_at.date() + timedelta(days=500))
        if (bounds := rth_bounds_utc(d)) is not None and bounds[1] > frozen_at
    ][:252]
    manifest = {
        "protocol": PROTOCOL,
        "horizon": horizon.value,
        "frozen_at": frozen_at.isoformat(),
        "study_days": [str(d) for d in study_days],
        "source": str(source.resolve()),
        "kill_switch_path": str(source.resolve().parent / "kill_switch.json"),
        "config": cfg.model_dump(mode="json"),
        "versions": versions,
        "approval_scopes": scopes,
        "max_accepts_per_book_per_day": daily_cap,
        "artifacts": pinned,
        "artifact_roots": [str(p.absolute()) for p in model_roots],
        "code_hash": code_hash(),
        "initial_cash": 10000,
        "sessions": 252,
        "seed": 42817,
        "max_candidates_per_session": 250,
        "slippage_bps": 3.0,
        "min_closed_baseline_trades": 100,
        "bootstrap_block_sessions": 21,
        "bootstrap_samples": 5000,
        "final_analysis_only": True,
        "notice": NOTICE,
    }
    manifest["hash"] = digest(manifest)
    directory.mkdir(parents=True, mode=0o700)
    dbpath = directory / "books.sqlite"
    engine = _private_engine(dbpath)
    Base.metadata.create_all(engine)
    try:
        with engine.begin() as c:
            c.exec_driver_sql("PRAGMA max_page_count=65536")
            c.exec_driver_sql(
                "CREATE TABLE comparison_final (id INTEGER PRIMARY KEY "
                "CHECK(id=1), payload TEXT NOT NULL)"
            )
            c.exec_driver_sql(
                "CREATE TABLE comparison_manifest (id INTEGER PRIMARY KEY "
                "CHECK(id=1), payload TEXT NOT NULL)"
            )
            c.exec_driver_sql(
                "INSERT INTO comparison_manifest VALUES (1,?)", (json.dumps(manifest),)
            )
            c.exec_driver_sql(
                "CREATE TABLE comparison_batch (day TEXT PRIMARY KEY, status TEXT, payload TEXT)"
            )
            c.exec_driver_sql(
                "CREATE TABLE comparison_forecast (day TEXT, symbol TEXT, "
                "horizon INTEGER, payload TEXT, PRIMARY KEY(day,symbol,horizon))"
            )
            c.exec_driver_sql(
                "CREATE TABLE comparison_choice (day TEXT, candidate "
                "INTEGER, arm TEXT, payload TEXT, PRIMARY KEY(day,candidate,arm))"
            )
            c.exec_driver_sql(
                "CREATE TABLE comparison_daily (day TEXT, book TEXT, "
                "payload TEXT, PRIMARY KEY(day,book))"
            )
            c.exec_driver_sql(
                "CREATE TABLE comparison_attempt (day TEXT, symbol TEXT, "
                "horizon INTEGER, PRIMARY KEY(day,symbol,horizon))"
            )
            c.exec_driver_sql(
                "CREATE TRIGGER frozen_batch BEFORE UPDATE OF payload ON "
                "comparison_batch BEGIN SELECT RAISE(ABORT,'immutable input batch'); END"
            )
            for table in (
                "comparison_final",
                "comparison_attempt",
                "comparison_manifest",
                "comparison_forecast",
                "comparison_choice",
                "comparison_daily",
                "paper_trade",
            ):
                for action in ("UPDATE", "DELETE"):
                    c.exec_driver_sql(
                        f"CREATE TRIGGER freeze_{table}_{action} BEFORE {action} ON {table} "
                        "BEGIN SELECT RAISE(ABORT,'immutable experiment record'); END"
                    )
        with Session(engine) as s, s.begin():
            for version in versions:
                for arm in ARMS:
                    s.add(
                        PaperAccount(
                            name=_account_name(int(version), arm), initial_cash=10000, cash=10000
                        )
                    )
            set_setting(s, "research_overrides", manifest["config"], actor=PROTOCOL)
            set_setting(s, "alerts_enabled", False, actor=PROTOCOL)
            set_setting(s, "auto_simulate_qualified_signals", False, actor=PROTOCOL)
    finally:
        engine.dispose()
    dbpath.chmod(0o600)
    (directory / "manifest.json").write_text(json.dumps(manifest, indent=2))
    (directory / "manifest.json").chmod(0o600)
    return manifest


def open_books(directory: Path) -> tuple[Engine, dict[str, Any]]:
    path = directory / "books.sqlite"
    if path.is_symlink() or not path.is_file():
        raise ValueError("Missing private experiment database")
    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as c:
        manifest = json.loads(
            c.execute("SELECT payload FROM comparison_manifest WHERE id=1").fetchone()[0]
        )
    expected = manifest.pop("hash")
    if expected != digest(manifest) or manifest["protocol"] != PROTOCOL:
        raise ValueError("Manifest mismatch")
    manifest["hash"] = expected
    if path.resolve() == Path(manifest["source"]).resolve():
        raise ValueError("Operating database cannot be an experiment")
    if manifest["code_hash"] != code_hash():
        raise ValueError("Code changed; use frozen checkout, not a revised experiment")
    return _private_engine(path.resolve()), manifest


def _copy_row(src: Session, dst: Session, table: Table, row_id: int, seen: set) -> None:
    key = (table.name, row_id)
    if key in seen:
        return
    if table.name not in PARENTS or len(seen) > 5000:
        raise ValueError("Unsupported provenance dependency")
    seen.add(key)
    row = src.execute(select(table).where(table.c.id == row_id)).mappings().one()
    existing = dst.execute(select(table).where(table.c.id == row_id)).mappings().first()
    if existing:
        if digest(dict(existing)) != digest(dict(row)):
            raise ValueError("Previously captured metadata was revised")
        return
    for col in table.columns:
        for fk in col.foreign_keys:
            if row[col.name] is not None:
                _copy_row(src, dst, fk.column.table, row[col.name], seen)
    dst.execute(table.insert().values(**dict(row)))


def matched_ids(ids: list[int], k: int, manifest_hash: str, day: str, version: int) -> set[int]:
    if not 0 <= k <= len(ids):
        raise ValueError("Invalid matched sample size")
    return set(sorted(ids, key=lambda i: digest([42817, manifest_hash, day, version, i]))[:k])


def _bars(
    src: Session, dst: Session, symbols: list[str], start: date, end: date, now: datetime
) -> None:
    observed: dict[str, set[date]] = {symbol: set() for symbol in symbols}
    for bar in src.scalars(
        select(OHLCVDaily)
        .join(Instrument)
        .where(
            Instrument.symbol.in_(symbols),
            OHLCVDaily.source == "massive",
            OHLCVDaily.session_date >= start,
            OHLCVDaily.session_date <= end,
        )
        .order_by(OHLCVDaily.session_date, OHLCVDaily.instrument_id)
    ):
        instrument = src.get(Instrument, bar.instrument_id)
        assert instrument is not None
        symbol = instrument.symbol
        observed[symbol].add(bar.session_date)
        vals = [bar.open, bar.high, bar.low, bar.close, bar.volume]
        if (
            bar.is_simulated
            or not bar.is_adjusted
            or bar.quality_flags
            or bar.ingested_at > now
            or not all(math.isfinite(x) for x in vals)
            or not 0 < bar.low <= min(bar.open, bar.close) <= max(bar.open, bar.close) <= bar.high
            or bar.volume < 0
        ):
            raise ValueError("Invalid or future market observation")
        row = {c.name: getattr(bar, c.name) for c in OHLCVDaily.__table__.columns}
        old = dst.get(OHLCVDaily, bar.id)
        if old:
            if digest(row) != digest(
                {c.name: getattr(old, c.name) for c in OHLCVDaily.__table__.columns}
            ):
                raise ValueError("Previously captured market data revised")
        else:
            _copy_row(src, dst, Base.metadata.tables["instrument"], bar.instrument_id, set())
            dst.add(OHLCVDaily(**row))
    expected = set(sessions(start, end))
    if any(days != expected for days in observed.values()):
        raise ValueError("Missing market sessions; portfolio progression blocked")
    dst.flush()


def _record(s: Session, table: str, columns: str, values: tuple) -> None:
    s.connection().exec_driver_sql(
        f"INSERT INTO {table} ({columns}) VALUES ({','.join('?' for _ in values)})",  # noqa: S608
        values,
    )


def _account_name(version: int, arm: str) -> str:
    return f"experiment-v{version}-{arm}"


def _snapshot(s: Session, day: date) -> None:
    for acct in s.scalars(select(PaperAccount).order_by(PaperAccount.id)):
        positions = list(
            s.scalars(select(PaperPosition).where(PaperPosition.account_id == acct.id))
        )
        value = 0.0
        for pos in positions:
            if pos.closed_at is None:
                bar = s.scalar(
                    select(OHLCVDaily).where(
                        OHLCVDaily.instrument_id == pos.instrument_id,
                        OHLCVDaily.session_date == day,
                        OHLCVDaily.source == "massive",
                    )
                )
                if bar is None:
                    raise ValueError("Missing current portfolio mark")
                value += pos.qty * bar.close
        fills = list(
            s.scalars(
                select(PaperFill)
                .join_from(PaperFill, Base.metadata.tables["paper_order"])
                .where(Base.metadata.tables["paper_order"].c.account_id == acct.id)
            )
        )
        row = {
            "equity": float(acct.cash) + value,
            "cash": float(acct.cash),
            "invested": value,
            "realized": sum(float(p.realized_pnl or 0) for p in positions),
            "open_positions": sum(p.closed_at is None for p in positions),
            "closed_trades": sum(p.closed_at is not None for p in positions),
            "winning_trades": sum(
                p.closed_at is not None and p.realized_pnl > 0 for p in positions
            ),
            "gross_profit": sum(
                float(p.realized_pnl or 0) for p in positions if (p.realized_pnl or 0) > 0
            ),
            "gross_loss": -sum(
                float(p.realized_pnl or 0) for p in positions if (p.realized_pnl or 0) < 0
            ),
            "entry_costs": sum(float(f.commission + f.slippage + f.spread_cost) for f in fills),
        }
        _record(s, "comparison_daily", "day,book,payload", (str(day), acct.name, json.dumps(row)))


def _guard(manifest: dict[str, Any]) -> None:
    ensure_not_engaged()
    path = Path(manifest["kill_switch_path"])
    if path.exists():
        try:
            active = json.loads(path.read_text())["active"]
        except (OSError, ValueError, KeyError) as exc:
            raise ValueError("Operating emergency stop unreadable") from exc
        if active is not False:
            raise ValueError("Operating emergency stop active or invalid")


def _cancelled(manifest: dict[str, Any]) -> bool:
    try:
        _guard(manifest)
    except Exception:
        return True
    return False


def _advance(directory: Path, *, collect: bool = True) -> dict[str, Any]:
    """Resume at most one closed session; never backfill missed decisions."""
    ensure_not_engaged()
    engine, manifest = open_books(directory)
    _guard(manifest)
    src_engine = source_engine(Path(manifest["source"]))
    now = datetime.now(UTC)
    origin = last_closed_session(now)
    day = str(origin)
    if day < manifest["study_days"][0]:
        engine.dispose()
        src_engine.dispose()
        return {"status": "not_started", "first_session": manifest["study_days"][0]}
    collect = collect and day <= manifest["study_days"][-1]
    try:
        if (
            collect
            and artifacts([Path(p) for p in manifest["artifact_roots"]]) != manifest["artifacts"]
        ):
            raise ValueError("Pinned model artifacts changed")
        with Session(engine) as dst, Session(src_engine) as src:
            pending = dst.scalar(
                text(
                    "SELECT day FROM comparison_batch WHERE status != "
                    "'complete' ORDER BY day LIMIT 1"
                )
            )
            if pending:
                origin, day = date.fromisoformat(pending), pending
            batch = dst.execute(
                text("SELECT status,payload FROM comparison_batch WHERE day=:day"), {"day": day}
            ).first()
            if batch and batch[0] == "complete":
                return {"status": "already_complete", "day": day}
            if not batch:
                close = rth_bounds_utc(origin)
                if close is None or now < close[1]:
                    raise ValueError("No completed origin session")
                cfg = effective_research_config(src)
                if (
                    cfg.model_dump(mode="json") != manifest["config"]
                    or max_per_day(src) != manifest["max_accepts_per_book_per_day"]
                ):
                    raise ValueError("Operating research config changed; new experiment required")
                last = dst.scalar(text("SELECT MAX(day) FROM comparison_daily"))
                start = (
                    date.fromisoformat(last)
                    if last
                    else date.fromisoformat(manifest["study_days"][0])
                )
                held_symbols = list(dst.scalars(select(Instrument.symbol)))
                _bars(src, dst, held_symbols, start, origin, now)
                # Progress EVERY missing session with the real ledger, not one final mark.
                for d in sessions(start, origin):
                    if last and str(d) <= last:
                        continue
                    for account in dst.scalars(select(PaperAccount)):
                        _guard(manifest)
                        mark_to_market(dst, account_name=account.name, as_of=d)
                    if d != origin:
                        _snapshot(dst, d)
                candidates = []
                histories = {}
                if collect and origin >= datetime.fromisoformat(manifest["frozen_at"]).date():
                    rows = list(
                        src.scalars(
                            select(Candidate)
                            .join(Instrument)
                            .join(ScanRun)
                            .where(
                                Candidate.horizon == Horizon(manifest["horizon"]),
                                Candidate.quality_gate_status == QualityGate.PASSED,
                                Candidate.direction == Direction.LONG,
                                Candidate.structure_kind.is_(None),
                                Candidate.created_at
                                >= max(close[1], datetime.fromisoformat(manifest["frozen_at"])),
                                Candidate.created_at <= now,
                                ScanRun.finished_at <= now,
                                ScanRun.source == "massive",
                                Instrument.symbol.in_(cfg.universe),
                            )
                            .order_by(
                                Candidate.strategy_version_id,
                                Candidate.rank_in_horizon.nulls_last(),
                                Candidate.id,
                            )
                            .limit(251)
                        )
                    )
                    if len(rows) > manifest["max_candidates_per_session"]:
                        raise ValueError("Candidate capacity exceeded")
                    for cand in rows:
                        v = src.get(StrategyVersion, cand.strategy_version_id)
                        run = src.get(ScanRun, cand.scan_run_id)
                        if (
                            v is None
                            or v.status != StrategyStatus.PAPER_APPROVED
                            or v.strategy.status != StrategyStatus.PAPER_APPROVED
                            or manifest["versions"].get(str(v.id)) != digest(v.spec_json)
                        ):
                            continue
                        if _scopes_hash(src, v.id) != manifest["approval_scopes"][str(v.id)]:
                            raise ValueError("Approval scope changed; new experiment required")
                        assert run is not None
                        if not scan_scope_matches(
                            approved_scopes(src, v.id),
                            dataset_snapshot_id=run.dataset_snapshot_id,
                            config_hash=run.config_hash,
                            spec_json_hash=current_spec_json_hash(src, v.id) or "",
                            source=run.source,
                            universe=frozenset(run.universe_json),
                        ):
                            continue
                        inst = src.get(Instrument, cand.instrument_id)
                        assert inst is not None
                        if (
                            inst.instrument_type not in ("stock", "etf")
                            or inst.symbol not in run.universe_json
                        ):
                            continue
                        _acceptance_freshness(src, cand, now)
                        if src.scalar(
                            select(OHLCVDaily.id).where(
                                OHLCVDaily.instrument_id == inst.id,
                                OHLCVDaily.source == "massive",
                                OHLCVDaily.session_date <= origin,
                                OHLCVDaily.ingested_at > now,
                            )
                        ):
                            raise ValueError("Future ingestion timestamp in forecast history")
                        _copy_row(src, dst, Base.metadata.tables["candidate"], cand.id, set())
                        histories[inst.symbol] = inputs(src, inst.symbol, origin)
                        candidates.append(
                            {
                                "id": cand.id,
                                "version": v.id,
                                "symbol": inst.symbol,
                                "source_scope_verified": True,
                                "approval_scopes": json.loads(
                                    json.dumps(
                                        [asdict(scope) for scope in approved_scopes(src, v.id)],
                                        default=sorted,
                                    )
                                ),
                            }
                        )
                    if len(histories) > 25:
                        raise ValueError("Model call capacity exceeded")
                    _bars(src, dst, list(histories), origin, origin, now)
                payload: dict[str, Any] = {
                    "captured_at": now.isoformat(),
                    "candidates": candidates,
                    "histories": histories,
                    "collect": collect,
                }
                _record(
                    dst,
                    "comparison_batch",
                    "day,status,payload",
                    (day, "captured", json.dumps(payload)),
                )
                dst.commit()
            else:
                payload = json.loads(batch[1])
        # Source transaction is closed BEFORE model calls. Each attempt is durable.
        horizon = 5 if manifest["horizon"] == Horizon.SHORT_SWING else 20
        for symbol, history in payload["histories"].items():
            _guard(manifest)
            with Session(engine) as dst:
                params = {"day": day, "symbol": symbol, "horizon": horizon}
                clause = "day=:day AND symbol=:symbol AND horizon=:horizon"
                if dst.execute(
                    text("SELECT 1 FROM comparison_forecast WHERE " + clause), params  # noqa: S608
                ).first():
                    continue
                attempted = dst.execute(
                    text("SELECT 1 FROM comparison_attempt WHERE " + clause), params  # noqa: S608
                ).first()
                if not attempted:
                    _record(dst, "comparison_attempt", "day,symbol,horizon", (day, symbol, horizon))
                    dst.commit()
                result = {"status": "missing", "reason": "interrupted_attempt"}
                if not attempted and datetime.now(UTC).date() == origin:
                    try:
                        result = forecast(
                            history, symbol, horizon, cancelled=lambda: _cancelled(manifest)
                        )
                        result.update(status="complete", completed_at=datetime.now(UTC).isoformat())
                    except Exception as exc:
                        result = {"status": "missing", "reason": type(exc).__name__}
                _record(
                    dst,
                    "comparison_forecast",
                    "day,symbol,horizon,payload",
                    (day, symbol, horizon, json.dumps(result)),
                )
                dst.commit()
        if (
            payload["histories"]
            and artifacts([Path(p) for p in manifest["artifact_roots"]]) != manifest["artifacts"]
        ):
            raise ValueError("Model artifacts changed during inference")
        with Session(engine) as dst, dst.begin():
            if (
                dst.scalar(text("SELECT status FROM comparison_batch WHERE day=:day"), {"day": day})
                == "complete"
            ):
                return {"status": "already_complete", "day": day}
            current = datetime.now(UTC)
            # Historical API assumes an end-of-UTC-date valuation. Never apply it
            # after midnight or with observations from later than the decision.
            late = current.date() != origin or not payload["collect"]
            predictions = {
                r[0]: json.loads(r[1])
                for r in dst.execute(
                    text("SELECT symbol,payload FROM comparison_forecast WHERE day=:day"),
                    {"day": day},
                )
            }
            groups: dict[int, list[dict]] = {}
            for c in payload["candidates"]:
                groups.setdefault(c["version"], []).append(c)
            for version, group in groups.items():
                positive = set()
                for c in group:
                    p = predictions.get(c["symbol"], {})
                    if p.get("status") == "complete":
                        terminal = sum(path[-1] for path in p["paths"]) / 3
                        if terminal > p["unchanged_baseline"] * 1.0011:
                            positive.add(c["id"])
                matched = matched_ids(
                    [c["id"] for c in group], len(positive), manifest["hash"], day, version
                )
                for arm in ARMS:
                    name = _account_name(version, arm)
                    if not dst.scalar(select(PaperAccount.id).where(PaperAccount.name == name)):
                        dst.add(
                            PaperAccount(
                                name=name, initial_cash=10000, cash=10000, strategy_version_id=None
                            )
                        )
                        dst.flush()
                    for c in group:
                        selected = arm == "baseline" or c["id"] in (
                            positive if arm == "filtered" else matched
                        )
                        decision = {
                            "selected": selected,
                            "status": "not_selected",
                            "captured_at": payload["captured_at"],
                            "decision_at": current.isoformat(),
                            "notice": NOTICE,
                        }
                        if selected and late:
                            decision.update(
                                status="missed", reason="capture_not_completed_on_origin_date"
                            )
                        elif selected:
                            _guard(manifest)
                            try:
                                entry_account = dst.scalar(
                                    select(PaperAccount).where(PaperAccount.name == name)
                                )
                                candidate = dst.get(Candidate, c["id"])
                                assert entry_account is not None and candidate is not None
                                if _has_open_position(
                                    dst, entry_account.id, candidate.instrument_id
                                ):
                                    raise ValueError("open position already exists in this book")
                                if (
                                    accepted_today(dst, entry_account.id, current)
                                    >= manifest["max_accepts_per_book_per_day"]
                                ):
                                    raise ValueError("frozen per-book daily acceptance cap reached")
                                with dst.begin_nested():
                                    accepted = accept_candidate(
                                        dst,
                                        c["id"],
                                        account_name=name,
                                        as_of=origin,
                                        actor=PROTOCOL,
                                        note=manifest["hash"],
                                        slippage_bps=3.0,
                                    )
                                    order = dst.get(PaperOrder, accepted.order_id)
                                    fill = dst.get(PaperFill, accepted.fill_id)
                                    position = dst.get(PaperPosition, accepted.position_id)
                                    assert (
                                        order is not None
                                        and fill is not None
                                        and position is not None
                                    )
                                    order.submitted_at = current
                                    fill.filled_at = current
                                    position.opened_at = current
                                decision.update(status="accepted", position_id=accepted.position_id)
                            except ValueError as exc:
                                decision.update(status="risk_rejected", reason=str(exc))
                        _record(
                            dst,
                            "comparison_choice",
                            "day,candidate,arm,payload",
                            (day, c["id"], arm, json.dumps(decision)),
                        )
            _snapshot(dst, origin)
            dst.execute(
                text("UPDATE comparison_batch SET status='complete' WHERE day=:day"), {"day": day}
            )
        return {
            "status": "complete",
            "day": day,
            "candidates": len(payload["candidates"]),
            "notice": NOTICE,
        }
    finally:
        engine.dispose()
        src_engine.dispose()


def advance(directory: Path, *, collect: bool = True) -> dict[str, Any]:
    """Single writer; lock is private to this experiment, not the operating worker."""
    if not (directory / "books.sqlite").is_file():
        raise ValueError("Missing private experiment database")
    with (directory / "writer.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError("Comparison writer already running") from exc
        return _advance(directory, collect=collect)


def status(directory: Path) -> dict[str, Any]:
    """Operational counts only. No interim equity/P&L/selection performance."""
    engine, manifest = open_books(directory)
    try:
        with Session(engine) as s:
            return {
                "protocol": PROTOCOL,
                "manifest_hash": manifest["hash"],
                "first_session": manifest["study_days"][0],
                "last_session": manifest["study_days"][-1],
                "books": s.scalar(select(func.count()).select_from(PaperAccount)),
                "completed_batches": s.scalar(
                    text("SELECT COUNT(*) FROM comparison_batch WHERE status='complete'")
                ),
                "forecasts": s.scalar(text("SELECT COUNT(*) FROM comparison_forecast")),
                "finalized": bool(s.scalar(text("SELECT COUNT(*) FROM comparison_final"))),
                "performance": "sealed until final analysis",
                "notice": NOTICE,
            }
    finally:
        engine.dispose()
