"""R3 dead-approvals diagnosis (read-only; no pre-registration needed).

Why two of the four PAPER_APPROVED strategy versions earn nothing in the
operating paper book. This script:

* runs NO scan, NO promotion evaluation and NO strategy backtest;
* opens the scratch database read-only (``mode=ro`` URL from the environment);
* loads the SPY regime proxy for the development window 2016-10-17..2025-09-05
  (source ``massive``) — to count regime LABELS, never returns;
* (repair pass, sections 9-10) also loads, always ending 2025-09-05 and always
  source ``massive``: SPY from its first massive bar, and the bar DATES of the
  symbols of dataset snapshots 3 and 11 — only to place each symbol's
  in-sample/out-of-sample boundary. No return, level or price is computed or
  printed from any of them;
* replays the readiness rule of ``scripts/kronos_comparison_collect.py`` on the
  recorded scan audit payloads (identity fields only). No study manifest, book
  or collection file is opened;
* reads candidate/scan/paper rows as metadata only (counts, gate strings,
  timestamps) and never prints a price, a level or a P&L.

Run (cwd must be a directory without a .env):

    PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=<wt>/src:<wt>/scripts MARKET_DATA_PROVIDER=massive \
    SIGNALFORGE_DATA_DIR=<scratch>/db \
    DATABASE_URL="sqlite+pysqlite:///file:<scratch>/db/signalforge.sqlite?mode=ro&uri=true" \
    <venv>/bin/python <wt>/scripts/r3/dead_approvals_diag.py <out_dir>

Research signal only — no order was placed.
"""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select, text

from signalforge.backtest.regime import label_regimes
from signalforge.data.calendar import last_closed_session, rth_bounds_utc
from signalforge.data.series import PriceSeries
from signalforge.db.models import (
    BacktestMetric,
    BacktestRun,
    DataSnapshot,
    Strategy,
    StrategyPromotionEvaluation,
    StrategyVersion,
)
from signalforge.db.session import session_scope
from signalforge.domain import Horizon, StrategyStatus
from signalforge.research.approval_scope import (
    approved_scopes,
    current_spec_json_hash,
    scan_scope_matches,
)
from signalforge.research.approved_scope_scan import approved_scan_groups
from signalforge.research.backtest_runner import _is_boundary
from signalforge.research.persistence import (
    latest_oos_metric,
    oos_scope_failures,
    spec_json_hash,
)
from signalforge.research.regime import Trend, regime_lookup
from signalforge.research.scan import _oos_metric_failures, _oos_regime_coverage
from signalforge.research.strategies import default_strategies
from signalforge.settings_store import effective_research_config

DEV_START = date(2016, 10, 17)
DEV_END = date(2025, 9, 5)  # last development session; nothing later is loaded
SINCE = "2026-09-25"  # scan_run.started_at (UTC) lower bound for part C
VERSIONS = (2, 3, 5, 13)
EXPECTED_RUN = {2: 53, 3: 55, 5: 54, 13: 49}
SCOPE_SNAPSHOTS = (3, 11)
# The versions the scouts' map (maps/constraints.md section 1) says the frozen
# kronos-comparison-v2-medium book pins. The manifest itself is NOT opened; the
# set is re-derived below from the freeze rule (experiments/comparison.py:151-160).
KRONOS_MEDIUM_PINNED = frozenset({"3", "5", "13"})
MIN_DAILY_BARS = 60  # run_strategy_over_universe(min_bars=60) for daily strategies

OUT: dict[str, Any] = {}
FAILED: list[str] = []


def h(title: str) -> None:
    print("\n" + "=" * 100)
    print(title)
    print("=" * 100)


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  [{'OK' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    OUT.setdefault("identity_checks", []).append({"name": name, "ok": bool(ok), "detail": detail})
    if not ok:
        FAILED.append(name)


def gate_category(g: str) -> str:
    if g.startswith("OOS regime coverage"):
        return "A_regime_coverage"
    if g.startswith("OOS provenance mismatch"):
        return "oos_provenance_mismatch"
    if g.startswith("OOS scope mismatch"):
        return "oos_scope_mismatch"
    if g.startswith("no out-of-sample backtest"):
        return "no_oos_backtest_on_record"
    if g.startswith("reward/risk"):
        return "reward_risk"
    if g.startswith("risk:"):
        return "risk_sizing"
    if g.startswith("OOS trades"):
        return "oos_trades"
    if g.startswith("OOS expectancy CI"):
        return "oos_ci"
    if g.startswith("OOS expectancy"):
        return "oos_expectancy"
    return "other"


def as_utc(raw: str) -> datetime:
    return datetime.fromisoformat(raw).replace(tzinfo=UTC)


def main(out_dir: Path) -> int:
    with session_scope() as s:
        cfg = effective_research_config(s)
        q = cfg.quality_gates
        p = cfg.promotion

        strategies = {}
        for strat in default_strategies():
            spec = strat.spec()
            ver = s.scalar(
                select(StrategyVersion)
                .join(Strategy, StrategyVersion.strategy_id == Strategy.id)
                .where(Strategy.name == spec.name, StrategyVersion.version == spec.version)
            )
            if ver is not None and ver.id in VERSIONS:
                strategies[ver.id] = (strat, spec, ver)

        # ------------------------------------------------------------------ #
        h("0. Identity checks (STOP if any fails)")
        scan_cfg = s.execute(
            text(
                "SELECT config_hash FROM scan_run WHERE source='massive' "
                "ORDER BY started_at DESC, id DESC LIMIT 1"
            )
        ).scalar()
        check(
            "effective research config_hash == newest approved-scope scan_run.config_hash",
            cfg.config_hash == scan_cfg,
            f"{cfg.config_hash[:16]} vs {str(scan_cfg)[:16]}",
        )
        check("all four versions resolve to a default strategy", set(strategies) == set(VERSIONS))
        for vid in VERSIONS:
            strat, spec, ver = strategies[vid]
            newest = s.execute(
                select(
                    StrategyPromotionEvaluation.id,
                    StrategyPromotionEvaluation.spec_json_hash,
                    StrategyPromotionEvaluation.config_hash,
                )
                .where(
                    StrategyPromotionEvaluation.strategy_version_id == vid,
                    StrategyPromotionEvaluation.passed.is_(True),
                )
                .order_by(
                    StrategyPromotionEvaluation.evaluated_at.desc(),
                    StrategyPromotionEvaluation.id.desc(),
                )
            ).first()
            assert newest is not None
            check(
                f"sv{vid} {spec.name}: status PAPER_APPROVED (version + strategy)",
                ver.status.value == "paper_approved"
                and ver.strategy.status.value == "paper_approved",
            )
            check(
                f"sv{vid}: spec_json_hash(worktree code) == newest passing evaluation {newest.id}",
                spec_json_hash(spec) == newest.spec_json_hash,
                spec_json_hash(spec)[:12],
            )
            check(
                f"sv{vid}: newest passing evaluation config_hash == effective config_hash",
                newest.config_hash == cfg.config_hash,
                newest.config_hash[:12],
            )
            metric = latest_oos_metric(s, spec)
            check(
                f"sv{vid}: latest_oos_metric run == {EXPECTED_RUN[vid]}",
                metric is not None and metric.run_id == EXPECTED_RUN[vid],
                f"run {metric.run_id if metric else None}",
            )
            run = s.get(BacktestRun, EXPECTED_RUN[vid])
            assert run is not None
            check(
                f"sv{vid}: run {run.id} is a development-window record (date_end <= 2025-09-07)",
                run.date_end <= date(2025, 9, 7)
                and (run.params_json or {}).get("purpose") == "development_oos",
                f"{run.date_start}..{run.date_end}",
            )
            rows = s.scalars(
                select(BacktestMetric).where(
                    BacktestMetric.run_id == run.id, BacktestMetric.phase == "oos_by_regime"
                )
            ).all()
            total = sum(int(float(r.metrics_json.get("n_trades", 0))) for r in rows)
            oos_n = int(float(metric.metrics_json["n_trades"])) if metric else -1
            check(
                f"sv{vid}: sum(oos_by_regime n_trades) == out_of_sample n_trades",
                total == oos_n,
                f"{total} vs {oos_n}",
            )
        # Repair pass: two more identities the new sections rest on.
        medium_approved = {
            str(v.id)
            for v in s.scalars(
                select(StrategyVersion).where(
                    StrategyVersion.status == StrategyStatus.PAPER_APPROVED
                )
            )
            if v.strategy.horizon == Horizon.MEDIUM_SWING
            and v.strategy.status == StrategyStatus.PAPER_APPROVED
        }
        check(
            "freeze rule (experiments/comparison.py:151-160) on current statuses: PAPER_APPROVED "
            "MEDIUM_SWING versions == {3, 5, 13}, the set the scouts' map gives for the Kronos "
            "medium book",
            medium_approved == set(KRONOS_MEDIUM_PINNED),
            str(sorted(medium_approved, key=int)),
        )
        other_snaps = s.execute(
            text(
                "SELECT count(*) FROM scan_run WHERE source='massive' AND started_at >= :since "
                "AND (dataset_snapshot_id IS NULL OR dataset_snapshot_id NOT IN (3, 11))"
            ),
            {"since": SINCE},
        ).scalar()
        check(
            f"every source='massive' scan_run since {SINCE} is on dataset snapshot 3 or 11 "
            "(so 'approved-scope scan run' == source='massive' scan_run)",
            other_snaps == 0,
            f"{other_snaps} others",
        )
        if FAILED:
            print("\nIDENTITY CHECK FAILED — stopping before any result:", FAILED)
            (out_dir / "diag.json").write_text(json.dumps(OUT, indent=1, default=str))
            return 2

        # ------------------------------------------------------------------ #
        h("1. Thresholds in force (effective config = env base + app_setting.research_overrides)")
        overrides = s.execute(
            text("SELECT value_json FROM app_setting WHERE key='research_overrides'")
        ).scalar()
        ov = json.loads(overrides) if isinstance(overrides, str) else (overrides or {})
        thresholds = {
            "quality_gates.min_oos_regimes": q.min_oos_regimes,
            "quality_gates.min_trades_per_regime": q.min_trades_per_regime,
            "quality_gates.min_oos_trades": q.min_oos_trades,
            "quality_gates.min_oos_expectancy_r": q.min_oos_expectancy_r,
            "quality_gates.min_oos_ci_low_r": q.min_oos_ci_low_r,
            "quality_gates.require_backtest": q.require_backtest,
            "promotion.min_regimes_covered": p.min_regimes_covered,
            "promotion.min_trades_per_regime": p.min_trades_per_regime,
            "risk.min_reward_to_risk": cfg.risk.min_reward_to_risk,
            "research_overrides keys": sorted(ov),
            "research_overrides has quality_gates": "quality_gates" in ov,
            "research_overrides has promotion": "promotion" in ov,
            "'quality_gates' in SCOPE_HASH_FIELDS": "quality_gates" in cfg.SCOPE_HASH_FIELDS,
            "'promotion' in SCOPE_HASH_FIELDS": "promotion" in cfg.SCOPE_HASH_FIELDS,
            "config_hash": cfg.config_hash,
        }
        for k, v in thresholds.items():
            print(f"  {k}: {v}")
        OUT["thresholds"] = thresholds

        # What the scope hash would become under each threshold option (pure
        # arithmetic on the config object; nothing is written anywhere).
        from signalforge.config.research import ResearchConfig

        base = cfg.model_dump(mode="json")
        what_if = {}
        for label, patch in (
            ("min_oos_regimes=1", {"min_oos_regimes": 1}),
            ("min_trades_per_regime=4", {"min_trades_per_regime": 4}),
        ):
            merged = json.loads(json.dumps(base))
            merged["quality_gates"].update(patch)
            what_if[label] = ResearchConfig.model_validate(merged).config_hash
        merged = json.loads(json.dumps(base))
        merged["promotion"]["min_regimes_covered"] = 2
        what_if["promotion.min_regimes_covered=2 (control: not a scope field)"] = (
            ResearchConfig.model_validate(merged).config_hash
        )
        print("  config_hash if the threshold were changed (computed in memory only):")
        for k, v in what_if.items():
            print(f"    {k}: {v[:16]}  changed={v != cfg.config_hash}")
        OUT["what_if_config_hash"] = {
            k: {"hash": v, "changed": v != cfg.config_hash} for k, v in what_if.items()
        }

        # ------------------------------------------------------------------ #
        h("2. Per-regime OOS rows of the latest development OOS run, and the scan gate's verdict")
        per_run: dict[int, Any] = {}
        for vid in VERSIONS:
            strat, spec, ver = strategies[vid]
            run_id = EXPECTED_RUN[vid]
            rows = s.scalars(
                select(BacktestMetric)
                .where(BacktestMetric.run_id == run_id, BacktestMetric.phase == "oos_by_regime")
                .order_by(BacktestMetric.segment)
            ).all()
            by_label = {
                str(r.metrics_json.get("regime_label", r.segment)): int(
                    float(r.metrics_json.get("n_trades", 0))
                )
                for r in rows
            }
            by_trend: dict[str, int] = {}
            for label, n in by_label.items():
                by_trend[label.split("/", 1)[0]] = by_trend.get(label.split("/", 1)[0], 0) + n
            n_cov, covered = _oos_regime_coverage(s, run_id, q.min_trades_per_regime)
            verdict = "PASS" if n_cov >= q.min_oos_regimes else "FAIL"
            print(f"\n  sv{vid} {spec.name} v{spec.version} — backtest_run {run_id}")
            for label, n in sorted(by_label.items()):
                print(f"    {label:<14} n_trades={n}")
            print(f"    by trend: {dict(sorted(by_trend.items()))}")
            print(
                f"    _oos_regime_coverage(min_trades={q.min_trades_per_regime}) -> {n_cov} "
                f"{covered}; need {q.min_oos_regimes} -> {verdict}"
            )
            second = sorted((n for t, n in by_trend.items() if t != "bull"), reverse=True)
            per_run[vid] = {
                "strategy": spec.name,
                "run_id": run_id,
                "by_label": by_label,
                "by_trend": by_trend,
                "covered": covered,
                "n_covered": n_cov,
                "verdict": verdict,
                "largest_non_bull_trend_count": second[0] if second else 0,
                "margin_over_floor": (second[0] if second else 0) - q.min_trades_per_regime,
            }
        OUT["per_run_regimes"] = per_run

        # ------------------------------------------------------------------ #
        h("3. Promotion gate 6 evidence of the evaluation each run is linked to")
        gate6 = {}
        for vid in VERSIONS:
            run = s.get(BacktestRun, EXPECTED_RUN[vid])
            assert run is not None
            ev_id = (run.params_json or {}).get("promotion_evaluation_id")
            ev = s.get(StrategyPromotionEvaluation, ev_id)
            assert ev is not None
            g6 = next(g for g in ev.gates_json if g.get("number") == 6)  # gate 6 ONLY
            evd = g6.get("evidence") or {}
            gate6[vid] = {
                "evaluation_id": ev.id,
                "passed": g6.get("passed"),
                "trades_per_regime": evd.get("trades_per_regime"),
                "min_trades_per_regime": evd.get("min_trades_per_regime"),
                "n_trades_considered": evd.get("n_trades_considered"),
                "unbucketed_total": (evd.get("unbucketed") or {}).get("total"),
            }
            print(f"  sv{vid} evaluation {ev.id}: {gate6[vid]}")
        OUT["gate6"] = gate6

        # ------------------------------------------------------------------ #
        h("4. Replay of the scan's OOS-evidence gates (real functions, recorded rows only)")
        snaps = {sid: s.get(DataSnapshot, sid) for sid in SCOPE_SNAPSHOTS}
        replay: dict[str, Any] = {}
        for vid in VERSIONS:
            strat, spec, ver = strategies[vid]
            metric = latest_oos_metric(s, spec)
            assert metric is not None
            for sid in SCOPE_SNAPSHOTS:
                snap = snaps[sid]
                assert snap is not None
                symbols = list(snap.symbols_json)
                failures: list[str] = []
                failures.extend(
                    oos_scope_failures(
                        s,
                        metric,
                        spec,
                        config_hash=cfg.config_hash,
                        dataset_snapshot_id=sid,
                        source="massive",
                        symbols=symbols,
                    )
                )
                failures.extend(_oos_metric_failures(metric.metrics_json, metric.ci_json, q))
                n_cov, covered = _oos_regime_coverage(s, metric.run_id, q.min_trades_per_regime)
                if n_cov < q.min_oos_regimes:
                    failures.append(
                        f"OOS regime coverage: {n_cov} regime(s) with "
                        f">={q.min_trades_per_regime} trades ({', '.join(covered) or 'none'}) "
                        f"< {q.min_oos_regimes} required — single-regime edge"
                    )
                guard = scan_scope_matches(
                    approved_scopes(s, vid),
                    dataset_snapshot_id=sid,
                    config_hash=cfg.config_hash,
                    spec_json_hash=current_spec_json_hash(s, vid) or "",
                    source="massive",
                    universe=frozenset(x.upper() for x in symbols),
                )
                key = f"sv{vid}@snapshot{sid}"
                replay[key] = {
                    "evidence_run": metric.run_id,
                    "oos_gate_failures": failures,
                    "auto_sim_scope_guard_matches": bool(guard),
                }
                print(
                    f"  {key:<18} evidence run {metric.run_id}: "
                    f"{failures if failures else 'NO FAILURE'}  | "
                    f"auto-sim scope guard matches: {guard}"
                )
        OUT["scan_gate_replay"] = replay

        # ------------------------------------------------------------------ #
        h("5. Approved scopes and the scan groups the next approved-scope scan would run")
        scopes_out = {}
        for vid in VERSIONS:
            scopes = approved_scopes(s, vid)
            scopes_out[vid] = [
                {
                    "evaluation_id": sc.evaluation_id,
                    "dataset_snapshot_id": sc.dataset_snapshot_id,
                    "config_hash": sc.config_hash[:12],
                    "n_universe": len(sc.universe),
                    "sources": sorted(sc.sources),
                    "matches_current_config": sc.config_hash == cfg.config_hash,
                }
                for sc in scopes
            ]
            print(f"  sv{vid}: {scopes_out[vid]}")
        groups, skipped = approved_scan_groups(s, cfg)
        groups_out = [
            {
                "horizon": g.horizon.value,
                "dataset_snapshot_id": g.dataset_snapshot_id,
                "source": g.source,
                "n_symbols": len(g.symbols),
                "strategy_version_ids": list(g.strategy_version_ids),
            }
            for g in groups
        ]
        print("  groups:", groups_out)
        print("  skipped:", skipped)
        OUT["approved_scopes"] = scopes_out
        OUT["scan_groups"] = groups_out
        OUT["scan_groups_skipped"] = skipped

        # ------------------------------------------------------------------ #
        h("6. Paper books and switches")
        accounts = [
            dict(r._mapping)
            for r in s.execute(
                text(
                    "SELECT id, name, strategy_version_id, initial_cash, created_at "
                    "FROM paper_account ORDER BY id"
                )
            )
        ]
        for a in accounts:
            print("  ", a)
        settings = {
            r[0]: r[1]
            for r in s.execute(
                text(
                    "SELECT key, value_json FROM app_setting WHERE key IN "
                    "('auto_simulate_qualified_signals','auto_simulate_max_per_day')"
                )
            )
        }
        print("  settings:", settings)
        book_audit = [
            dict(r._mapping)
            for r in s.execute(
                text(
                    "SELECT id, ts, actor, entity, after_json FROM audit_log "
                    "WHERE action='paper.book_created' ORDER BY id"
                )
            )
        ]
        print("  paper.book_created audit rows:", book_audit)
        decisions = [
            dict(r._mapping)
            for r in s.execute(
                text(
                    "SELECT c.strategy_version_id AS sv, pt.decision, count(*) AS n "
                    "FROM paper_trade pt JOIN candidate c ON c.id=pt.candidate_id "
                    "GROUP BY 1,2 ORDER BY 1,2"
                )
            )
        ]
        print("  paper_trade decisions by version:", decisions)
        OUT["paper_accounts"] = accounts
        OUT["auto_sim_settings"] = settings
        OUT["book_created_audit"] = book_audit
        OUT["paper_decisions_by_version"] = decisions

        # ------------------------------------------------------------------ #
        h(f"7. Candidate counts since {SINCE} (scan_run.started_at, UTC) — counts only, no prices")
        approved: dict[int, dict[str, Any]] = {}
        for vid in VERSIONS:
            strat, spec, ver = strategies[vid]
            scopes = approved_scopes(s, vid)
            approved[vid] = {
                "horizon": spec.horizon.value,
                "snapshots": sorted({sc.dataset_snapshot_id for sc in scopes}),
                "config_hashes": {sc.config_hash for sc in scopes},
                "universes": {sc.dataset_snapshot_id: sc.universe for sc in scopes},
            }
        scan_rows = s.execute(
            text(
                "SELECT id, started_at, source, dataset_snapshot_id, horizon, config_hash, "
                "universe_json, scanned_count, candidate_count FROM scan_run "
                "WHERE started_at >= :since AND source='massive' ORDER BY started_at, id"
            ),
            {"since": SINCE},
        ).all()
        scans: dict[int, dict[str, Any]] = {}
        for r in scan_rows:
            uni = r.universe_json
            uni = json.loads(uni) if isinstance(uni, str) else (uni or [])
            scans[r.id] = {
                "started": as_utc(str(r.started_at)),
                "session": last_closed_session(as_utc(str(r.started_at))),
                "snapshot": r.dataset_snapshot_id,
                "horizon": str(r.horizon),
                "config_hash": r.config_hash,
                "universe": frozenset(x.upper() for x in uni),
                "scanned": r.scanned_count,
            }

        def in_scope(vid: int, scan: dict[str, Any]) -> bool:
            a = approved[vid]
            return (
                scan["horizon"] == a["horizon"]
                and scan["snapshot"] in a["snapshots"]
                and scan["config_hash"] in a["config_hashes"]
                and scan["universe"] == a["universes"].get(scan["snapshot"])
            )

        cand_rows = s.execute(
            text(
                "SELECT c.id, c.strategy_version_id AS sv, c.scan_run_id, c.quality_gate_status "
                "AS st, c.failed_gates, c.created_at, i.symbol FROM candidate c "
                "JOIN scan_run sr ON sr.id=c.scan_run_id "
                "JOIN instrument i ON i.id=c.instrument_id "
                "WHERE sr.started_at >= :since AND sr.source='massive' "
                "AND c.strategy_version_id IN (2,3,5,13) ORDER BY c.id"
            ),
            {"since": SINCE},
        ).all()
        part_c: dict[str, Any] = {}
        for vid in VERSIONS:
            strat, spec, ver = strategies[vid]
            scope_scans = {sid: sc for sid, sc in scans.items() if in_scope(vid, sc)}
            live = {sid: sc for sid, sc in scope_scans.items() if sc["scanned"] > 0}
            sig_rows: Counter[str] = Counter()
            sig_days: dict[str, set[tuple[date, str]]] = defaultdict(set)
            # The daily cap is counted per book per UTC day (paper/auto_simulate.py:88-102,
            # "since 00:00 UTC today"), and auto-simulation runs right after the scan, so
            # the cap unit of a row is the UTC date its scan started on.
            sig_utc: dict[str, set[tuple[date, str]]] = defaultdict(set)
            status: Counter[str] = Counter()
            out_of_scope_rows = 0
            utc_day_mismatch = 0
            per_session: dict[date, dict[str, Any]] = {}
            per_utc_day: dict[date, dict[str, Any]] = {}
            for c in cand_rows:
                if c.sv != vid:
                    continue
                if c.scan_run_id not in scope_scans:
                    out_of_scope_rows += 1
                    continue
                sc = scope_scans[c.scan_run_id]
                gates = c.failed_gates
                gates = json.loads(gates) if isinstance(gates, str) else (gates or [])
                cats = sorted({gate_category(g) for g in gates})
                sig = "+".join(cats) if cats else "PASSED"
                status[str(c.st)] += 1
                sig_rows[sig] += 1
                sig_days[sig].add((sc["session"], c.symbol))
                utc_day = sc["started"].date()
                if as_utc(str(c.created_at)).date() != utc_day:
                    utc_day_mismatch += 1
                sig_utc[sig].add((utc_day, c.symbol))
                d = per_session.setdefault(
                    sc["session"], {"scans": set(), "rows": 0, "symbols": set(), "sigs": Counter()}
                )
                d["scans"].add(c.scan_run_id)
                d["rows"] += 1
                d["symbols"].add(c.symbol)
                d["sigs"][sig] += 1
                u = per_utc_day.setdefault(
                    utc_day, {"scans": set(), "rows": 0, "symbols": set(), "sessions": set()}
                )
                u["scans"].add(c.scan_run_id)
                u["rows"] += 1
                u["symbols"].add(c.symbol)
                u["sessions"].add(sc["session"])
            sessions_scanned = sorted({sc["session"] for sc in live.values()})
            res = {
                "strategy": spec.name,
                "approved_snapshots": approved[vid]["snapshots"],
                "in_scope_scans": len(scope_scans),
                "in_scope_scans_that_scanned": len(live),
                "sessions_with_in_scope_scan": len(sessions_scanned),
                "first_session": str(sessions_scanned[0]) if sessions_scanned else None,
                "last_session": str(sessions_scanned[-1]) if sessions_scanned else None,
                "candidate_rows_in_scope": sum(status.values()),
                "status": dict(status),
                "rows_by_failure_signature": dict(sig_rows),
                "distinct_session_symbol_by_signature": {k: len(v) for k, v in sig_days.items()},
                "distinct_symbols_by_signature": {
                    k: len({sym for _, sym in v}) for k, v in sig_days.items()
                },
                "sessions_by_signature": {k: len({d for d, _ in v}) for k, v in sig_days.items()},
                "candidate_rows_out_of_scope_massive_scans": out_of_scope_rows,
            }
            cap = int(settings.get("auto_simulate_max_per_day", 2) or 2)

            def cap_bound(pairs: set[tuple[date, str]], cap: int = cap) -> tuple[int, int]:
                by_day: dict[date, set[str]] = defaultdict(set)
                for d, sym in pairs:
                    by_day[d].add(sym)
                return sum(min(cap, len(v)) for v in by_day.values()), len(by_day)

            # The code's cap unit: accepted trades per book per UTC day.
            res["rows_whose_candidate_utc_day_differs_from_scan_utc_day"] = utc_day_mismatch
            res["utc_days_with_in_scope_rows"] = len(per_utc_day)
            res["utc_days_by_signature"] = {k: cap_bound(v)[1] for k, v in sig_utc.items()}
            res["cap_bound_per_utc_day_by_signature"] = {
                k: cap_bound(v)[0] for k, v in sig_utc.items()
            }
            all_utc: set[tuple[date, str]] = set()
            for v in sig_utc.values():
                all_utc |= v
            res["cap_bound_per_utc_day_all_in_scope_rows"] = cap_bound(all_utc)[0]
            # Per-session figure, kept for comparison only: NOT the code's cap unit.
            res["cap_bound_per_session_by_signature_NOT_the_code_unit"] = {
                k: cap_bound(v)[0] for k, v in sig_days.items()
            }
            part_c[f"sv{vid}"] = res
            print(f"\n  sv{vid} {spec.name}")
            for k, v in res.items():
                print(f"    {k}: {v}")
            if vid in (5, 13):
                print(
                    "    per session (session date | scans | rows | distinct symbols | signatures):"
                )
                for d in sorted(per_session):
                    e = per_session[d]
                    print(
                        f"      {d} | {sorted(e['scans'])} | {e['rows']} | {len(e['symbols'])} | "
                        f"{dict(e['sigs'])}"
                    )
                res["per_session"] = {
                    str(d): {
                        "scans": sorted(e["scans"]),
                        "rows": e["rows"],
                        "distinct_symbols": len(e["symbols"]),
                        "signatures": dict(e["sigs"]),
                    }
                    for d, e in sorted(per_session.items())
                }
                res["in_scope_scan_sessions"] = [str(d) for d in sessions_scanned]
                print(
                    "    per UTC day, the daily cap's unit "
                    "(UTC day | scans | rows | distinct symbols | sessions | min(cap, symbols)):"
                )
                for d in sorted(per_utc_day):
                    e = per_utc_day[d]
                    print(
                        f"      {d} | {sorted(e['scans'])} | {e['rows']} | {len(e['symbols'])} | "
                        f"{sorted(str(x) for x in e['sessions'])} | {min(cap, len(e['symbols']))}"
                    )
                res["per_utc_day"] = {
                    str(d): {
                        "scans": sorted(e["scans"]),
                        "rows": e["rows"],
                        "distinct_symbols": len(e["symbols"]),
                        "sessions": sorted(str(x) for x in e["sessions"]),
                        "min_cap_symbols": min(cap, len(e["symbols"])),
                    }
                    for d, e in sorted(per_utc_day.items())
                }
        OUT["part_c"] = part_c

        # ---- 7b. context: why sv5 has so few in-scope sessions; sv13 since its fix ----
        from signalforge.data.calendar import sessions as xnys_sessions

        # exchange calendar only; no bar is read
        window_sessions = list(xnys_sessions(date(2026, 9, 25), date(2026, 11, 9)))
        audit_rows = s.execute(
            text(
                "SELECT id, ts, action, after_json FROM audit_log WHERE action LIKE "
                "'approved_scope_scan.%' AND ts >= :since ORDER BY id"
            ),
            {"since": SINCE},
        ).all()
        scan_by_session: dict[date, dict[str, Any]] = {}
        for r in audit_rows:
            payload = json.loads(r.after_json) if isinstance(r.after_json, str) else r.after_json
            sess = last_closed_session(as_utc(str(r.ts)))
            e = scan_by_session.setdefault(sess, {"any_run": False, "versions": set()})
            for run in payload.get("runs") or []:
                if int(run.get("scanned") or 0) > 0:
                    e["any_run"] = True
                    e["versions"].update(run.get("strategy_version_ids") or [])
        sv5_sessions = set(part_c["sv5"].get("in_scope_scan_sessions", []))
        # Pre-repair method, kept only to show what changed: it classified a session from
        # COMPLETED-scan audit rows, so a job that failed after its first scan looked like
        # "no scan" (review finding: session 2026-10-06, scan_run 238, audit 242 job.failed).
        gap_by_audit: dict[str, list[str]] = {
            "no_scan_that_scanned_anything": [],
            "scan_ran_without_sv5_group": [],
        }
        for d in window_sessions:
            if str(d) in sv5_sessions:
                continue
            e = scan_by_session.get(d)
            if e is None or not e["any_run"]:
                gap_by_audit["no_scan_that_scanned_anything"].append(str(d))
            elif 5 not in e["versions"]:
                gap_by_audit["scan_ran_without_sv5_group"].append(str(d))
            else:
                gap_by_audit.setdefault("other", []).append(str(d))
        # Repaired method: classify from the scan_run rows themselves.
        ran_by_session: dict[date, list[int]] = defaultdict(list)
        for sid, sc in scans.items():
            if (sc["scanned"] or 0) > 0:
                ran_by_session[sc["session"]].append(sid)
        gap: dict[str, list[str]] = {
            "no_approved_scope_scan_run_scanned_anything": [],
            "approved_scope_scan_run_scanned_but_none_in_sv5_scope": [],
        }
        gap_scan_ids: dict[str, list[int]] = {}
        for d in window_sessions:
            if str(d) in sv5_sessions:
                continue
            ids = sorted(ran_by_session.get(d, []))
            if not ids:
                gap["no_approved_scope_scan_run_scanned_anything"].append(str(d))
            else:
                gap["approved_scope_scan_run_scanned_but_none_in_sv5_scope"].append(str(d))
                gap_scan_ids[str(d)] = ids
        reclassified = sorted(
            set(gap_by_audit["scan_ran_without_sv5_group"])
            ^ set(gap["approved_scope_scan_run_scanned_but_none_in_sv5_scope"])
        )
        failed_jobs = [
            {
                "audit": r.id,
                "ts_utc": str(r.ts),
                "session": str(last_closed_session(as_utc(str(r.ts)))),
                "job": r.entity,
            }
            for r in s.execute(
                text(
                    "SELECT id, ts, entity FROM audit_log WHERE action='job.failed' AND entity "
                    "IN ('approved_scope_scan','catchup_approved_scope_scan') AND ts >= :since "
                    "ORDER BY id"
                ),
                {"since": SINCE},
            )
        ]
        # When was version 5 out of the scan groups (i.e. not PAPER_APPROVED)? Read off the
        # completed-scan audit payloads and the promotion audit rows.
        completed: list[tuple[int, datetime, bool]] = []
        audited_scan_ids: set[int] = set()
        for r in audit_rows:
            if r.action != "approved_scope_scan.completed":
                continue
            payload = json.loads(r.after_json) if isinstance(r.after_json, str) else r.after_json
            lists5 = any(
                5 in (run.get("strategy_version_ids") or [])
                for run in (payload.get("runs") or [])
                if isinstance(run, dict)
            )
            completed.append((r.id, as_utc(str(r.ts)), lists5))
            for run in payload.get("runs") or []:
                if isinstance(run, dict) and type(run.get("scan_run_id")) is int:
                    audited_scan_ids.add(run["scan_run_id"])
        # Reconciliation with maps/paper-funnel.md, whose scan counts come from the
        # completed-scan audit payloads (its Q1), not from scan_run rows.
        recon: dict[str, Any] = {}
        for vid in VERSIONS:
            ids = sorted(sid for sid, sc in scans.items() if in_scope(vid, sc))
            listed = [sid for sid in ids if sid in audited_scan_ids]
            recon[f"sv{vid}"] = {
                "in_scope_scan_runs": len(ids),
                "of_which_scanned": sum(1 for sid in ids if (scans[sid]["scanned"] or 0) > 0),
                "listed_in_a_completed_scan_audit": len(listed),
                "listed_and_scanned": sum(1 for sid in listed if (scans[sid]["scanned"] or 0) > 0),
                "scan_runs_not_in_any_completed_audit": [
                    {
                        "scan": sid,
                        "started_utc": str(scans[sid]["started"]),
                        "session": str(scans[sid]["session"]),
                        "scanned": scans[sid]["scanned"],
                    }
                    for sid in ids
                    if sid not in audited_scan_ids
                ],
            }
        without = [c for c in completed if not c[2]]
        assert without, "expected a stretch of completed scans without a version-5 group"
        first_wo, last_wo = without[0], without[-1]
        before = [c for c in completed if c[2] and c[0] < first_wo[0]]
        after = [c for c in completed if c[2] and c[0] > last_wo[0]]
        promo_rows = s.execute(
            text(
                "SELECT id, ts, before_json FROM audit_log WHERE action='strategy.promote' AND "
                "entity LIKE 'relative_strength.medium_swing%' AND ts >= :since ORDER BY id"
            ),
            {"since": SINCE},
        ).all()
        repromo = None
        for r in promo_rows:
            b = (
                json.loads(r.before_json)
                if isinstance(r.before_json, str)
                else (r.before_json or {})
            )
            if b.get("status") == "experimental":
                repromo = (r.id, as_utc(str(r.ts)))
                break
        assert repromo is not None, "expected an experimental -> paper_approved audit row"
        stretch = {
            "completed_scan_audits_since": len(completed),
            "audits_without_a_version5_group": len(without),
            "first_audit_without": {"audit": first_wo[0], "ts_utc": str(first_wo[1])},
            "last_audit_without": {"audit": last_wo[0], "ts_utc": str(last_wo[1])},
            "the_audits_without_are_one_contiguous_run": all(
                not c[2] for c in completed if first_wo[0] <= c[0] <= last_wo[0]
            ),
            "last_audit_with_the_group_before": (
                {"audit": before[-1][0], "ts_utc": str(before[-1][1])} if before else None
            ),
            "first_audit_with_the_group_after": (
                {"audit": after[0][0], "ts_utc": str(after[0][1])} if after else None
            ),
            "repromotion_experimental_to_paper_approved": {
                "audit": repromo[0],
                "ts_utc": str(repromo[1]),
            },
        }
        by_state: dict[str, list[str]] = {
            "not_approved (session close inside first-audit-without .. re-promotion)": [],
            "status_not_established (close after the last scan with the group, before the "
            "first without)": [],
            "approved (close at or after re-promotion, or before the gap)": [],
        }
        state_keys = list(by_state)
        for d in window_sessions:
            if str(d) in sv5_sessions:
                continue
            bounds = rth_bounds_utc(d)
            assert bounds is not None
            close = bounds[1]
            if first_wo[1] <= close < repromo[1]:
                by_state[state_keys[0]].append(str(d))
            elif before and before[-1][1] < close < first_wo[1]:
                by_state[state_keys[1]].append(str(d))
            else:
                by_state[state_keys[2]].append(str(d))
        snap3 = frozenset(x.upper() for x in snaps[3].symbols_json)
        snap11 = frozenset(x.upper() for x in snaps[11].symbols_json)
        shadow_pairs: set[tuple[date, str]] = set()
        for c in cand_rows:
            if c.sv != 5 or c.scan_run_id not in scans:
                continue
            sc = scans[c.scan_run_id]
            if (
                sc["snapshot"] == 11
                and c.symbol.upper() in snap3
                and str(sc["session"]) not in sv5_sessions
            ):
                shadow_pairs.add((sc["session"], c.symbol))
        sv5_union = set()
        for c in cand_rows:
            if c.sv == 5 and c.scan_run_id in scans and in_scope(5, scans[c.scan_run_id]):
                sv5_union.add(c.symbol)
        v13_eval = s.get(StrategyPromotionEvaluation, 51)
        v13_run = s.get(BacktestRun, 49)
        assert v13_eval is not None and v13_run is not None
        approved_at = v13_eval.evaluated_at.replace(tzinfo=UTC)
        recorded_at = v13_run.created_at.replace(tzinfo=UTC)
        v13_scans = sorted(
            (sc["started"], sid, sc["session"], sc["scanned"])
            for sid, sc in scans.items()
            if in_scope(13, sc) and sc["started"] >= approved_at
        )
        v13_rows_by_scan = Counter(c.scan_run_id for c in cand_rows if c.sv == 13)
        ctx = {
            "xnys_sessions_2026-09-25..2026-11-09": len(window_sessions),
            "sv5_sessions_with_in_scope_scan": len(sv5_sessions),
            "sv5_sessions_without_in_scope_scan": {k: len(v) for k, v in gap.items()},
            "sv5_sessions_without_in_scope_scan_dates": gap,
            "approved_scope_scan_runs_that_scanned_on_the_second_group": gap_scan_ids,
            "pre_repair_classification_from_completed_audits_only": {
                k: len(v) for k, v in gap_by_audit.items()
            },
            "pre_repair_classification_dates": gap_by_audit,
            "sessions_classified_differently_by_the_two_methods": reclassified,
            "approved_scope_scan_job_failures_since": failed_jobs,
            "scan_counts_scan_run_rows_vs_completed_audit_payloads": recon,
            "sv5_absent_from_scan_groups": stretch,
            "sv5_sessions_without_in_scope_scan_by_approval_state": {
                k: len(v) for k, v in by_state.items()
            },
            "sv5_sessions_without_in_scope_scan_by_approval_state_dates": by_state,
            "sv5_distinct_symbols_in_scope_all_signatures": len(sv5_union),
            "snapshot3_symbols": len(snap3),
            "snapshot3_symbols_also_in_snapshot11": len(snap3 & snap11),
            "sv5_out_of_scope_signal_days_on_approved_symbols_when_no_in_scope_scan": len(
                shadow_pairs
            ),
            "sv5_out_of_scope_sessions_with_such_signals": len({d for d, _ in shadow_pairs}),
            "sv5_out_of_scope_sessions_with_such_signals_dates": sorted(
                {str(d) for d, _ in shadow_pairs}
            ),
            "sv13_approved_at_utc": str(approved_at),
            "sv13_oos_run_49_recorded_at_utc": str(recorded_at),
            "sv13_in_scope_scans_since_approval": [
                {
                    "scan": sid,
                    "started_utc": str(st),
                    "session": str(sess),
                    "scanned": n,
                    "sv13_candidates": v13_rows_by_scan.get(sid, 0),
                    "after_run_49": st > recorded_at,
                }
                for st, sid, sess, n in v13_scans
            ],
        }
        print("\n  7b. context")
        for k, v in ctx.items():
            print(f"    {k}: {v}")
        OUT["part_c_context"] = ctx

        # All-time totals per version (context for the headline).
        totals = [
            dict(r._mapping)
            for r in s.execute(
                text(
                    "SELECT strategy_version_id AS sv, count(*) AS candidates, "
                    "sum(quality_gate_status='PASSED') AS passed, min(created_at) AS first, "
                    "max(created_at) AS last FROM candidate WHERE strategy_version_id IN "
                    "(2,3,5,13) GROUP BY 1 ORDER BY 1"
                )
            )
        ]
        print("\n  all-time candidate totals:", totals)
        OUT["all_time_candidate_totals"] = totals

        # ------------------------------------------------------------------ #
        h("8. SPY regime labels, development window only (labels, not returns)")
        proxy = PriceSeries.load(s, "SPY", DEV_START, DEV_END, source="massive")
        assert len(proxy) > 0 and proxy.dates[-1] <= DEV_END, "sealed bar loaded — abort"
        b_lab = regime_lookup(proxy)  # labeller B: research/regime.py (strategies + scan gate)
        a_lab = label_regimes(proxy)  # labeller A: backtest/regime.py (promotion gate 6)
        boundary = _is_boundary(proxy)
        dates = list(proxy.dates)

        def a_bucket(lbl: str) -> str:
            if lbl == "warmup":
                return "warmup"
            if lbl == "range_bound":
                return "range"
            return "bull" if lbl.startswith("bull") else "bear"

        days_b = Counter(b_lab[d].trend.value for d in dates)
        days_b_oos = Counter(b_lab[d].trend.value for d in dates if d > boundary)
        # Every possible relative_strength trade: signal day i has trend BULL,
        # entry is day i+1. Gate 6 buckets it by labeller A on day i+1; the scan
        # gate buckets it by labeller B's trend on day i+1.
        pairs_all: Counter[tuple[str, str]] = Counter()
        pairs_oos: Counter[tuple[str, str]] = Counter()
        flips_oos: list[dict[str, str]] = []
        for i in range(len(dates) - 1):
            if b_lab[dates[i]].trend is not Trend.BULL:
                continue
            entry = dates[i + 1]
            key = (a_bucket(a_lab[entry]), b_lab[entry].trend.value)
            pairs_all[key] += 1
            if entry > boundary:
                pairs_oos[key] += 1
                if b_lab[entry].trend is not Trend.BULL:
                    flips_oos.append(
                        {
                            "signal_day": str(dates[i]),
                            "entry_day": str(entry),
                            "entry_label_B": f"{b_lab[entry].trend.value}/{b_lab[entry].vol.value}",
                            "entry_label_A": a_lab[entry],
                        }
                    )
        spy = {
            "bars": len(proxy),
            "first": str(dates[0]),
            "last": str(dates[-1]),
            "is_oos_boundary_full_history_symbol": str(boundary),
            "sessions_by_trend_B_window": dict(days_b),
            "sessions_by_trend_B_oos": dict(days_b_oos),
            "bull_signal_days_window": sum(pairs_all.values()),
            "bull_signal_days_with_oos_entry": sum(pairs_oos.values()),
            "entry_day_labels_given_bull_signal_window": {
                f"A={a}|B={b}": n for (a, b), n in sorted(pairs_all.items())
            },
            "entry_day_labels_given_bull_signal_oos": {
                f"A={a}|B={b}": n for (a, b), n in sorted(pairs_oos.items())
            },
            "oos_entry_days_not_bull_after_bull_signal": flips_oos,
        }
        for k, v in spy.items():
            print(f"  {k}: {v}")
        OUT["spy_regime_labels"] = spy

        # ------------------------------------------------------------------ #
        h(
            "9. Kronos collector readiness rule (scripts/kronos_comparison_collect.py trigger) "
            "replayed on recorded scan audits — identity fields only, no study file opened"
        )
        scan_ident = {
            r.id: {
                "snapshot": r.dataset_snapshot_id,
                "source": r.source,
                "horizon": str(r.horizon),
                "finished": r.finished_at,
            }
            for r in s.execute(
                text("SELECT id, dataset_snapshot_id, source, horizon, finished_at FROM scan_run")
            )
        }

        def collector_covered(payload: Any, horizon: str) -> set[str]:
            """Coverage part of trigger(): release 21e87a3 lines 102-130 (worktree 110-138).

            NOT replayed: the job-status and time-window conditions (job ok; close <=
            scan.started <= scan.finished <= audit.ts). They do not depend on which
            versions are approved."""
            covered: set[str] = set()
            if not isinstance(payload, dict):
                return covered
            for item in payload.get("runs", []):
                if not isinstance(item, dict) or item.get("horizon") != horizon:
                    continue
                versions = item.get("strategy_version_ids")
                if (
                    item.get("source") != "massive"
                    or not isinstance(versions, list)
                    or not versions
                    or any(type(v) is not int for v in versions)
                    or type(item.get("scan_run_id")) is not int
                ):
                    continue
                scan = scan_ident.get(item["scan_run_id"])
                if (
                    scan is None
                    or scan["snapshot"] != item.get("dataset_snapshot_id")
                    or scan["source"] != "massive"
                    or scan["horizon"] != horizon
                    or scan["finished"] is None
                ):
                    continue
                covered.update(str(v) for v in versions)
            return covered

        def without_version(payload: dict[str, Any], vid: int) -> dict[str, Any]:
            """The same payload as it would be recorded with ``vid`` not PAPER_APPROVED:
            approved_scan_groups builds groups from PAPER_APPROVED versions only
            (release research/approved_scope_scan.py:199-204), so the version leaves its
            group and a group left empty does not exist."""
            runs = []
            for item in payload.get("runs", []):
                if not isinstance(item, dict):
                    continue
                versions = item.get("strategy_version_ids")
                if isinstance(versions, list) and vid in versions:
                    rest = [v for v in versions if v != vid]
                    if not rest:
                        continue
                    item = {**item, "strategy_version_ids": rest}
                runs.append(item)
            return {**payload, "runs": runs}

        pinned = set(KRONOS_MEDIUM_PINNED)
        rest_pinned = pinned - {"5"}
        all_completed = s.execute(
            text(
                "SELECT id, ts, after_json FROM audit_log WHERE "
                "action='approved_scope_scan.completed' AND actor='scheduler' ORDER BY id"
            )
        ).all()
        per_audit = []
        for r in all_completed:
            payload = json.loads(r.after_json) if isinstance(r.after_json, str) else r.after_json
            if not isinstance(payload, dict) or payload.get("readiness_enforced") is not True:
                continue  # the deployed collector ignores these (release line 97-101)
            cov = collector_covered(payload, "MEDIUM_SWING")
            cov_wo = collector_covered(without_version(payload, 5), "MEDIUM_SWING")
            per_audit.append(
                {
                    "audit": r.id,
                    "ts_utc": str(r.ts),
                    "covered_medium_swing": sorted(cov, key=int),
                    "ready_for_pinned_3_5_13": pinned <= cov,
                    "covered_without_version5_group": sorted(cov_wo, key=int),
                    "ready_for_pinned_3_5_13_without_version5_group": pinned <= cov_wo,
                    "ready_for_a_book_pinning_only_3_13_without_version5_group": rest_pinned
                    <= cov_wo,
                }
            )
        in_stretch = [r for r in all_completed if first_wo[0] <= r.id <= last_wo[0]]
        plain5 = plain3 = rule3 = rule5 = with_source = 0
        for r in in_stretch:
            payload = json.loads(r.after_json) if isinstance(r.after_json, str) else r.after_json
            items = [i for i in (payload.get("runs") or []) if isinstance(i, dict)]
            medium = [i for i in items if i.get("horizon") == "MEDIUM_SWING"]
            plain5 += any(5 in (i.get("strategy_version_ids") or []) for i in items)
            plain3 += any(3 in (i.get("strategy_version_ids") or []) for i in medium)
            with_source += bool(items) and all("source" in i for i in items)
            cov = collector_covered(payload, "MEDIUM_SWING")
            rule3 += "3" in cov
            rule5 += "5" in cov
        kc = {
            "pinned_versions_medium_book_per_map_and_freeze_rule_manifest_not_opened": sorted(
                pinned, key=int
            ),
            "completed_scan_audits_all_time": len(all_completed),
            "of_which_readiness_enforced_true": len(per_audit),
            "readiness_enforced_audits_ready_for_pinned_3_5_13": sum(
                a["ready_for_pinned_3_5_13"] for a in per_audit
            ),
            "readiness_enforced_audits_ready_without_version5_group": sum(
                a["ready_for_pinned_3_5_13_without_version5_group"] for a in per_audit
            ),
            "readiness_enforced_audits_ready_for_a_3_13_book_without_version5_group": sum(
                a["ready_for_a_book_pinning_only_3_13_without_version5_group"] for a in per_audit
            ),
            "latest_readiness_enforced_audit": per_audit[-1] if per_audit else None,
            "stretch_when_version5_was_experimental": {
                "audits": len(in_stretch),
                "first_audit": first_wo[0],
                "last_audit": last_wo[0],
                "audits_listing_version5_in_any_run": plain5,
                "audits_listing_version3_in_a_medium_swing_run": plain3,
                "audits_whose_run_items_all_carry_a_source_key": with_source,
                "audits_where_the_full_rule_covers_version3": rule3,
                "audits_where_the_full_rule_covers_version5": rule5,
            },
        }
        for k, v in kc.items():
            print(f"  {k}: {v}")
        print("  every readiness-enforced audit:")
        for a in per_audit:
            print(f"    {a}")
        OUT["kronos_collector_readiness_replay"] = {**kc, "per_audit": per_audit}

        # ------------------------------------------------------------------ #
        h(
            "10. Label-flip slots: sessions where SPY's trend label leaves bull overnight, "
            "inside each symbol's out-of-sample segment (dates and labels only, <= 2025-09-05)"
        )
        spy_full = PriceSeries.load(s, "SPY", date(1990, 1, 1), DEV_END, source="massive")
        assert len(spy_full) > 0 and spy_full.dates[-1] <= DEV_END, "sealed bar loaded — abort"
        long_start = spy_full.dates[0]  # SPY's first massive bar

        def flip_slots(symbols: list[str], start: date) -> dict[str, Any]:
            px = PriceSeries.load(s, "SPY", start, DEV_END, source="massive")
            assert len(px) > 0 and px.dates[-1] <= DEV_END, "sealed bar loaded — abort"
            lab = regime_lookup(px)
            ds = list(px.dates)
            flips = [
                (ds[i], ds[i + 1])
                for i in range(len(ds) - 1)
                if lab[ds[i]].trend is Trend.BULL and lab[ds[i + 1]].trend is not Trend.BULL
            ]
            groups: dict[tuple[int, str, str, int], list[str]] = {}
            slots = lacking = 0
            skipped: list[str] = []
            entry_labels: Counter[str] = Counter()
            for sym in sorted(symbols):
                ser = PriceSeries.load(s, sym, start, DEV_END, source="massive")
                if len(ser) < MIN_DAILY_BARS:
                    skipped.append(sym)
                    continue
                assert ser.dates[-1] <= DEV_END, "sealed bar loaded — abort"
                b = _is_boundary(ser)
                have = set(ser.dates)
                k = 0
                for sig_day, entry in flips:
                    if entry > b:
                        k += 1
                        entry_labels[lab[entry].trend.value] += 1
                        if sig_day not in have or entry not in have:
                            lacking += 1
                slots += k
                groups.setdefault((len(ser), str(ser.dates[0]), str(b), k), []).append(sym)
            return {
                "window": f"{start}..{DEV_END}",
                "spy_bars": len(px),
                "symbols": len(symbols),
                "symbols_skipped_under_60_bars": skipped,
                "bull_to_non_bull_overnight_flips_whole_window": len(flips),
                "groups": [
                    {
                        "symbols": len(v),
                        "bars": nb,
                        "first_bar": first,
                        "oos_starts_after": b,
                        "flip_sessions_in_oos": k,
                        "names_if_3_or_fewer": v if len(v) <= 3 else None,
                    }
                    for (nb, first, b, k), v in sorted(groups.items())
                ],
                "symbol_x_flip_session_slots_in_oos": slots,
                "slots_by_entry_day_trend": dict(entry_labels),
                "slots_where_the_symbol_lacks_a_bar_on_signal_or_entry_day": lacking,
            }

        snap3_syms = [str(x) for x in snaps[3].symbols_json]
        snap11_syms = [str(x) for x in snaps[11].symbols_json]
        slot_runs = {
            "snapshot3_24_symbols_approved_window": flip_slots(snap3_syms, DEV_START),
            "snapshot3_24_symbols_from_spy_first_massive_bar": flip_slots(snap3_syms, long_start),
            "snapshot11_150_symbols_approved_window": flip_slots(snap11_syms, DEV_START),
        }
        sv5_neutral = int(per_run[5]["by_trend"].get("neutral", 0))
        base_slots = slot_runs["snapshot3_24_symbols_approved_window"][
            "symbol_x_flip_session_slots_in_oos"
        ]
        floor = q.min_trades_per_regime
        arithmetic = {
            "spy_first_massive_bar": str(long_start),
            "sv5_neutral_trades_recorded_run_54": sv5_neutral,
            "slots_approved_scope": base_slots,
            "observed_fill_rate": f"{sv5_neutral}/{base_slots}",
            "floor_min_trades_per_regime": floor,
        }
        for name, res in slot_runs.items():
            n = res["symbol_x_flip_session_slots_in_oos"]
            arithmetic[f"expected_neutral_trades_at_observed_rate__{name}"] = round(
                n * sv5_neutral / base_slots, 2
            )
        arithmetic["plain_proportion_150_over_24"] = round(
            sv5_neutral * len(snap11_syms) / len(snap3_syms), 2
        )
        sec8_entries = sorted(f["entry_day"] for f in flips_oos)
        full_hist = max(
            g["flip_sessions_in_oos"]
            for g in slot_runs["snapshot3_24_symbols_approved_window"]["groups"]
        )
        arithmetic["consistency_full_history_symbols_have_the_section8_flip_count"] = (
            full_hist == len(sec8_entries)
        )
        for name, res in slot_runs.items():
            print(f"\n  {name}")
            for k, v in res.items():
                if k == "groups":
                    print(
                        "    groups (symbols | bars | first bar | OOS starts after | flips in OOS):"
                    )
                    for g in v:
                        extra = f" {g['names_if_3_or_fewer']}" if g["names_if_3_or_fewer"] else ""
                        print(
                            f"      {g['symbols']} | {g['bars']} | {g['first_bar']} | "
                            f"{g['oos_starts_after']} | {g['flip_sessions_in_oos']}{extra}"
                        )
                else:
                    print(f"    {k}: {v}")
        print("\n  arithmetic (NOT a measurement; no strategy was run):")
        for k, v in arithmetic.items():
            print(f"    {k}: {v}")
        OUT["flip_slots"] = {"runs": slot_runs, "arithmetic": arithmetic}

    (out_dir / "diag.json").write_text(json.dumps(OUT, indent=1, default=str))
    print(f"\nwrote {out_dir / 'diag.json'}")
    print("Research signal only — no order was placed.")
    return 0


if __name__ == "__main__":
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    raise SystemExit(main(out))
