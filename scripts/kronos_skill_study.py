"""Pre-registered Kronos forecast-skill study (read-only database, local inference).

Sub-commands:

* ``plan``   — list every pre-registered window and check bar counts with plain SQL.
               No inference, no model load.
* ``pilot``  — run the first three Tier A calls, print measured latency and the
               projected total. Results are appended to ``calls.jsonl`` like any run.
* ``run``    — run every window not yet completed (resume-safe), appending results.
* ``report`` — regenerate ``summary.json`` and ``KRONOS_SKILL_STUDY_<date>.md``
               from ``calls.jsonl`` only (no inference).

The database is opened READ-ONLY (``mode=ro``); nothing here writes to it. Inference
goes through ``signalforge.kronos.service.replay`` and therefore shares the one-process
OS lock with the ``/kronos`` dashboard. This script never imports paper, execution,
risk, alerts, llm or the live scan. Design: ``docs/research/kronos/PREREGISTRATION_
2026-10-03_kronos_skill.md``. Nothing produced here is a trading instruction.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from signalforge.data.calendar import session_count, sessions
from signalforge.kronos import service, study

DEFAULT_DB = Path.home() / "signal-forge" / "data" / "signalforge.sqlite"
DEFAULT_OUT = Path(__file__).resolve().parents[1] / "docs" / "research" / "kronos"
HF_HUB = Path.home() / ".cache" / "huggingface" / "hub"
HF_REPOS = ("models--NeoQuasar--Kronos-small", "models--NeoQuasar--Kronos-Tokenizer-base")
HORIZONS = (5, 20)
TIER_A_SYMBOL = "SPY"
TIER_B_SYMBOLS = ("XLB", "XLC", "XLE", "XLF", "XLI", "XLK", "XLP", "XLRE", "XLU", "XLV", "XLY")
EXPLORATORY_ORIGINS = (date(2025, 2, 27), date(2025, 3, 31))
TIER_C_MIN_SESSIONS = 2400
TIER_C_COUNT = 8
TIER_C_SALT = "kronos-study-2026|"
BUSY_RETRIES = 5
BUSY_SLEEP_S = 30.0
PERMUTATION_ALPHA = 0.05
BH_Q = 0.10
EXPECTED_COVERAGE = 0.5  # 3-sample min-max band: (n-1)/(n+1) = 0.5


@dataclass(frozen=True)
class Window:
    tier: str
    symbol: str
    horizon: int
    origin: date
    heldout_end: date
    label: str  # "primary" | "overlap_possible" | "pooled" | "exploratory"

    @property
    def key(self) -> str:
        return f"{self.symbol}|{self.horizon}|{self.heldout_end.isoformat()}"

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["origin"] = self.origin.isoformat()
        d["heldout_end"] = self.heldout_end.isoformat()
        d["key"] = self.key
        return d


# ---------------------------------------------------------------------------
# Design (mechanical rules; no selection on outcome)
# ---------------------------------------------------------------------------


def month_end_sessions(start: date, end: date) -> list[date]:
    last: dict[tuple[int, int], date] = {}
    for d in sessions(start, end):
        last[(d.year, d.month)] = d
    return [last[k] for k in sorted(last)]


def heldout_end_for(origin: date, horizon: int) -> date:
    after = sessions(origin + timedelta(days=1), origin + timedelta(days=60))
    return after[horizon - 1]


def tier_a_origins() -> list[date]:
    """Last XNYS session of each month 2025-09 .. 2026-08 (12 origins)."""
    return month_end_sessions(date(2025, 9, 1), date(2026, 8, 31))


def tier_b_origins() -> list[date]:
    return tier_a_origins()[::2]


def tier_c_symbols(engine: Engine) -> list[str]:
    """Eight symbols with >= 2400 continuous massive sessions, lowest salted sha256."""
    excluded = {TIER_A_SYMBOL, *TIER_B_SYMBOLS}
    rows = _sql(
        engine,
        "SELECT i.symbol, COUNT(*), MIN(o.session_date), MAX(o.session_date) "
        "FROM ohlcv_daily o JOIN instrument i ON i.id = o.instrument_id "
        "WHERE o.source = 'massive' AND o.is_simulated = 0 "
        "GROUP BY i.symbol HAVING COUNT(*) >= :n",
        {"n": TIER_C_MIN_SESSIONS},
    )
    eligible = []
    for symbol, count, first, last in rows:
        if symbol in excluded:
            continue
        if session_count(date.fromisoformat(first), date.fromisoformat(last)) != count:
            continue
        eligible.append(symbol)
    eligible.sort(key=lambda s: hashlib.sha256((TIER_C_SALT + s).encode()).hexdigest())
    return eligible[:TIER_C_COUNT]


def build_windows(engine: Engine | None, tiers: set[str]) -> list[Window]:
    out: list[Window] = []
    if "A" in tiers:
        for origin in tier_a_origins():
            for h in HORIZONS:
                out.append(
                    Window("A", TIER_A_SYMBOL, h, origin, heldout_end_for(origin, h), "primary")
                )
        for origin in EXPLORATORY_ORIGINS:
            for h in HORIZONS:
                out.append(
                    Window(
                        "A",
                        TIER_A_SYMBOL,
                        h,
                        origin,
                        heldout_end_for(origin, h),
                        "overlap_possible",
                    )
                )
    if "B" in tiers:
        for symbol in TIER_B_SYMBOLS:
            for origin in tier_b_origins():
                for h in HORIZONS:
                    out.append(Window("B", symbol, h, origin, heldout_end_for(origin, h), "pooled"))
    if "C" in tiers:
        if engine is None:
            raise SystemExit("Tier C needs the database to choose symbols")
        for symbol in tier_c_symbols(engine):
            for origin in tier_b_origins():
                for h in HORIZONS:
                    out.append(
                        Window("C", symbol, h, origin, heldout_end_for(origin, h), "exploratory")
                    )
    return out


# ---------------------------------------------------------------------------
# Database (read-only)
# ---------------------------------------------------------------------------


def open_readonly(path: Path) -> Engine:
    if not path.is_file():
        raise SystemExit(f"Database not found: {path}")
    return create_engine(f"sqlite+pysqlite:///file:{path}?mode=ro&uri=true")


def _sql(
    engine: Engine, statement: str, params: dict[str, Any] | None = None
) -> list[tuple[Any, ...]]:
    with engine.connect() as conn:
        return [tuple(r) for r in conn.execute(text(statement), params or {}).fetchall()]


def check_window_bars(engine: Engine, window: Window) -> dict[str, Any]:
    """Plain SQL: the 128+h latest massive bars at/before heldout_end must end there and
    the context must end at the origin. No inference, no ORM, no quality inspection."""
    need = service.LOOKBACK + window.horizon
    rows = _sql(
        engine,
        "SELECT o.session_date FROM ohlcv_daily o JOIN instrument i ON i.id = o.instrument_id "
        "WHERE i.symbol = :s AND o.source = 'massive' AND o.is_simulated = 0 "
        "AND o.session_date <= :end ORDER BY o.session_date DESC LIMIT :n",
        {"s": window.symbol, "end": window.heldout_end.isoformat(), "n": need},
    )
    dates = [str(r[0]) for r in rows]
    ok = (
        len(dates) == need
        and dates[0] == window.heldout_end.isoformat()
        and dates[window.horizon] == window.origin.isoformat()
    )
    return {"bars": len(dates), "needed": need, "ok": ok}


def db_facts(engine: Engine, path: Path) -> dict[str, Any]:
    st = path.stat()
    (max_date,) = _sql(engine, "SELECT MAX(session_date) FROM ohlcv_daily WHERE source='massive'")[
        0
    ]
    return {
        "path": str(path),
        "size_bytes": st.st_size,
        "mtime_utc": datetime.fromtimestamp(st.st_mtime, UTC).isoformat(),
        "max_session_date_massive": str(max_date),
    }


# ---------------------------------------------------------------------------
# Call ledger
# ---------------------------------------------------------------------------


def calls_path(out_dir: Path) -> Path:
    return out_dir / "calls.jsonl"


def load_calls(out_dir: Path) -> dict[str, dict[str, Any]]:
    """Latest record per key (a later retry supersedes an earlier failure)."""
    latest: dict[str, dict[str, Any]] = {}
    p = calls_path(out_dir)
    if p.is_file():
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rec = json.loads(line)
                latest[rec["key"]] = rec
    return latest


def append_call(out_dir: Path, record: dict[str, Any]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    with calls_path(out_dir).open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, sort_keys=True, allow_nan=False) + "\n")


def execute_window(session: Session, window: Window) -> dict[str, Any]:
    """One replay with the pre-registered retry policy; returns the ledger record."""
    base: dict[str, Any] = {"window": window.to_dict(), "key": window.key}
    busy = 0
    timeouts = 0
    while True:
        started = time.monotonic()
        try:
            result = service.replay(
                session, window.symbol, window.horizon, as_of=window.heldout_end
            )
        except ValueError as exc:
            return {**base, "status": "failed", "reason": f"invalid: {exc}", "latency_s": None}
        except service.KronosError as exc:
            msg = str(exc)
            if "busy" in msg and busy < BUSY_RETRIES:
                busy += 1
                print(f"  busy ({busy}/{BUSY_RETRIES}); sleeping {BUSY_SLEEP_S:.0f}s", flush=True)
                time.sleep(BUSY_SLEEP_S)
                continue
            if "timed out" in msg and timeouts < 1:
                timeouts += 1
                print("  timeout; retrying once", flush=True)
                continue
            return {
                **base,
                "status": "failed",
                "reason": msg,
                "busy_retries": busy,
                "timeout_retries": timeouts,
                "latency_s": round(time.monotonic() - started, 3),
            }
        latency = time.monotonic() - started
        if result["input_end"] != window.origin.isoformat():
            raise AssertionError(f"{window.key}: input_end {result['input_end']} != origin")
        if result["heldout_end"] != window.heldout_end.isoformat():
            raise AssertionError(f"{window.key}: heldout_end mismatch")
        context_closes = [b["close"] for b in result["history"]]
        metrics = study.window_metrics(
            context_closes=context_closes,
            actual=result["actual"],
            predicted=result["predicted"],
            lower=result["lower"],
            upper=result["upper"],
        )
        stored = {k: v for k, v in result.items() if k not in {"history", "provenance"}}
        return {
            **base,
            "status": "ok",
            "latency_s": round(latency, 3),
            "busy_retries": busy,
            "timeout_retries": timeouts,
            "context_closes_tail": context_closes[-20:],
            "result": stored,
            "metrics": metrics,
        }


def run_windows(engine: Engine, out_dir: Path, windows: list[Window]) -> list[float]:
    done = {k for k, r in load_calls(out_dir).items() if r["status"] == "ok"}
    todo = [w for w in windows if w.key not in done]
    print(f"{len(windows)} windows, {len(done)} already complete, {len(todo)} to run", flush=True)
    latencies: list[float] = []
    with Session(engine) as session:
        for i, window in enumerate(todo, 1):
            print(f"[{i}/{len(todo)}] {window.key}", flush=True)
            record = execute_window(session, window)
            append_call(out_dir, record)
            if record["status"] == "ok":
                latencies.append(record["latency_s"])
                m = record["metrics"]
                print(
                    f"  ok {record['latency_s']:.1f}s mae={m['mae']:.3f} "
                    f"ratio_drift={m['baselines']['drift']['mae_ratio']:.3f}",
                    flush=True,
                )
            else:
                print(f"  FAILED: {record['reason']}", flush=True)
            session.rollback()  # never hold a transaction between calls
    return latencies


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------


def _ok_records(
    calls: dict[str, dict[str, Any]], tier: str, label: str, horizon: int
) -> list[dict[str, Any]]:
    return sorted(
        (
            r
            for r in calls.values()
            if r["status"] == "ok"
            and r["window"]["tier"] == tier
            and r["window"]["label"] == label
            and r["window"]["horizon"] == horizon
        ),
        key=lambda r: (r["window"]["origin"], r["window"]["symbol"]),
    )


def _ratio_test(records: list[dict[str, Any]], baseline: str) -> dict[str, Any] | None:
    logs = [r["metrics"]["baselines"][baseline]["log_mae_ratio"] for r in records]
    if not logs or any(v is None for v in logs):
        return None
    t = study.sign_flip_permutation_test(logs, alternative="two-sided")
    one_sided = study.sign_flip_permutation_test(logs, alternative="less")
    return {
        "n": t["n"],
        "geometric_mean_ratio": math.exp(t["mean"]),
        "ci95_ratio": [math.exp(t["ci"][0]), math.exp(t["ci"][1])],
        "p_two_sided": t["p_value"],
        "p_one_sided_less": one_sided["p_value"],
        "per_origin_ratio": [r["metrics"]["baselines"][baseline]["mae_ratio"] for r in records],
        "origins": [r["window"]["origin"] for r in records],
        "permutations": t["permutations"],
    }


def analyse(calls: dict[str, dict[str, Any]]) -> dict[str, Any]:
    summary: dict[str, Any] = {"calls_total": len(calls)}
    summary["failed"] = [
        {"key": r["key"], "reason": r.get("reason")}
        for r in sorted(calls.values(), key=lambda r: r["key"])
        if r["status"] != "ok"
    ]

    # Primary family: Tier A, 12 primary origins, MAE ratio vs drift and unchanged, h=20 and h=5.
    primary: dict[str, Any] = {}
    p_raw: list[float] = []
    names: list[str] = []
    for h in (20, 5):
        recs = _ok_records(calls, "A", "primary", h)
        for baseline in ("drift", "unchanged"):
            name = f"h{h}_mae_ratio_vs_{baseline}"
            t = _ratio_test(recs, baseline)
            primary[name] = t
            if t is not None:
                names.append(name)
                p_raw.append(t["p_two_sided"])
    holm = study.holm_adjust(p_raw)
    for name, adj in zip(names, holm, strict=True):
        primary[name]["p_holm"] = adj
        primary[name]["passes_g2"] = (
            adj < PERMUTATION_ALPHA
            and primary[name]["ci95_ratio"][1] < 1
            and primary[name]["geometric_mean_ratio"] < 1
            and (not name.startswith("h20") or primary[name]["geometric_mean_ratio"] <= 0.95)
        )
    summary["primary_tier_a"] = {"alpha_holm": PERMUTATION_ALPHA, "tests": primary}

    # Secondary family: direction and calibration, BH q=0.10.
    secondary: dict[str, Any] = {}
    s_raw: list[float] = []
    s_names: list[str] = []
    for h in (20, 5):
        recs = _ok_records(calls, "A", "primary", h)
        if not recs:
            continue
        hits = [r["metrics"]["directional_accuracy_end"] for r in recs]
        b = study.binomial_test_exact(sum(hits), len(hits), 0.5)
        secondary[f"h{h}_direction_end_vs_50pct"] = b
        s_names.append(f"h{h}_direction_end_vs_50pct")
        s_raw.append(b["p_two_sided"])
        diffs = [
            r["metrics"]["directional_accuracy_end"]
            - r["metrics"]["baselines"]["drift"]["directional_accuracy_end"]
            for r in recs
        ]
        d = study.sign_flip_permutation_test([float(v) for v in diffs], alternative="two-sided")
        secondary[f"h{h}_direction_end_vs_drift_sign"] = {
            "mean_diff": d["mean"],
            "p_two_sided": d["p_value"],
            "ci95": d["ci"],
            "model_rate": b["rate"],
            "drift_rate": sum(
                r["metrics"]["baselines"]["drift"]["directional_accuracy_end"] for r in recs
            )
            / len(recs),
        }
        s_names.append(f"h{h}_direction_end_vs_drift_sign")
        s_raw.append(d["p_value"])
        cov_end = [r["metrics"]["coverage_end"] for r in recs]
        c = study.binomial_test_exact(sum(cov_end), len(cov_end), EXPECTED_COVERAGE)
        c["per_bar_coverage_rate_mean"] = sum(r["metrics"]["coverage_rate"] for r in recs) / len(
            recs
        )
        c["mean_band_width_rel"] = sum(r["metrics"]["mean_band_width_rel"] for r in recs) / len(
            recs
        )
        c["any_band_degenerate"] = any(r["metrics"]["band_degenerate"] for r in recs)
        c["per_bar_hit_rate_mean"] = sum(r["metrics"]["per_bar_hit_rate"] for r in recs) / len(recs)
        secondary[f"h{h}_coverage_end_vs_50pct"] = c
        s_names.append(f"h{h}_coverage_end_vs_50pct")
        s_raw.append(c["p_two_sided"])
    bh = study.benjamini_hochberg_adjust(s_raw)
    for name, adj in zip(s_names, bh, strict=True):
        secondary[name]["p_bh"] = adj
    summary["secondary_tier_a"] = {"q_bh": BH_Q, "tests": secondary}

    # Exploratory overlap_possible origins: descriptive only.
    summary["exploratory_overlap_possible"] = {
        f"h{h}": [
            {
                "origin": r["window"]["origin"],
                "mae_ratio_vs_drift": r["metrics"]["baselines"]["drift"]["mae_ratio"],
                "mae_ratio_vs_unchanged": r["metrics"]["baselines"]["unchanged"]["mae_ratio"],
                "direction_end": r["metrics"]["directional_accuracy_end"],
            }
            for r in _ok_records(calls, "A", "overlap_possible", h)
        ]
        for h in (20, 5)
    }

    # Tier B / C pooled: cluster bootstrap over origins, effect + CI only.
    for tier, label in (("B", "pooled"), ("C", "exploratory")):
        pooled: dict[str, Any] = {}
        for h in (20, 5):
            recs = _ok_records(calls, tier, label, h)
            for baseline in ("drift", "unchanged"):
                clusters: dict[str, list[float]] = {}
                for r in recs:
                    v = r["metrics"]["baselines"][baseline]["log_mae_ratio"]
                    if v is not None:
                        clusters.setdefault(r["window"]["origin"], []).append(v)
                if not clusters:
                    pooled[f"h{h}_mae_ratio_vs_{baseline}"] = None
                    continue
                cb = study.cluster_bootstrap_mean([clusters[k] for k in sorted(clusters)])
                pooled[f"h{h}_mae_ratio_vs_{baseline}"] = {
                    "clusters": cb["clusters"],
                    "n": cb["n"],
                    "geometric_mean_ratio": math.exp(cb["mean"]),
                    "ci95_ratio": [math.exp(cb["ci"][0]), math.exp(cb["ci"][1])],
                    "n_boot": cb["n_boot"],
                    "seed": cb["seed"],
                    "symbols": sorted({r["window"]["symbol"] for r in recs}),
                }
        summary[f"tier_{tier.lower()}_pooled"] = pooled
    return summary


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------


def git_sha() -> str | None:
    try:
        proc = subprocess.run(
            ["/usr/bin/git", "rev-parse", "HEAD"],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except OSError:
        return None
    return proc.stdout.strip() or None


def hf_snapshot_dirs(repo: str) -> list[Path]:
    root = HF_HUB / repo / "snapshots"
    return sorted(p for p in root.iterdir() if p.is_dir()) if root.is_dir() else []


def hf_provenance() -> dict[str, Any]:
    out: dict[str, Any] = {}
    for repo in HF_REPOS:
        dirs = hf_snapshot_dirs(repo)
        entry: dict[str, Any] = {"snapshots": [d.name for d in dirs]}
        entry.update(study.sha256_of_tree(dirs))
        cutoff = None
        for d in dirs:
            readme = d / "README.md"
            if readme.is_file():
                for line in readme.read_text(encoding="utf-8", errors="replace").splitlines():
                    if "cutoff" in line.lower() or "cut-off" in line.lower():
                        cutoff = line.strip()
                        break
        entry["model_card_data_cutoff_line"] = cutoff
        out[repo] = entry
    return out


def provenance(engine: Engine, db: Path) -> dict[str, Any]:
    return {
        "git_sha": git_sha(),
        "db": db_facts(engine, db),
        "runtime_status": service.runtime_status(),
        "model": service.MODEL,
        "seed": 42,
        "samples": 3,
        "lookback": service.LOOKBACK,
        "hf": hf_provenance(),
    }


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

EXPECTATIONS = {
    "G2": "Null expected: geometric-mean MAE ratio vs drift and vs unchanged near 1 at both "
    "horizons; Holm-adjusted p >= 0.05. n=12 is low power, so a true 5% improvement would "
    "usually NOT be detected.",
    "G3": "Null expected: horizon-end directional accuracy within binomial noise of 50% and "
    "not distinguishable from the drift sign.",
    "G4": "Coverage of the 3-sample min-max band near its (n-1)/(n+1) = 50% nominal rate; "
    "bands non-degenerate. A clearly lower rate means the spread understates uncertainty.",
    "G5": "Null expected: Tier B pooled MAE ratio vs drift CI at h=20 includes 1.",
}


def _fmt(v: float | None, nd: int = 3) -> str:
    return "n/a" if v is None else f"{v:.{nd}f}"


def render_markdown(summary: dict[str, Any], prov: dict[str, Any], run_date: str) -> str:
    L: list[str] = []
    L.append(f"# Kronos forecast-skill study — results ({run_date})")
    L.append("")
    L.append(f"> {service.NOTICE}")
    L.append("")
    L.append(
        "Pre-registration: `PREREGISTRATION_2026-10-03_kronos_skill.md`. Every outcome is "
        "reported, including nulls and failures. Nothing here changes any strategy, "
        "threshold, risk rule or trade. Research signal only — no order was placed."
    )
    L.append("")
    L.append("## Pre-registered expectations next to outcomes")
    L.append("")
    L.append("| Gate | Pre-registered expectation | Outcome |")
    L.append("|---|---|---|")
    prim = summary["primary_tier_a"]["tests"]
    g2 = []
    for name, t in prim.items():
        if t is None:
            g2.append(f"{name}: no data")
        else:
            g2.append(
                f"{name}: ratio {t['geometric_mean_ratio']:.3f} "
                f"CI [{t['ci95_ratio'][0]:.3f}, {t['ci95_ratio'][1]:.3f}] "
                f"p={t['p_two_sided']:.4f} Holm={t.get('p_holm', float('nan')):.4f} "
                f"{'PASS' if t.get('passes_g2') else 'fail'}"
            )
    L.append(f"| G2 skill | {EXPECTATIONS['G2']} | {'<br>'.join(g2)} |")
    sec = summary["secondary_tier_a"]["tests"]
    g3 = []
    g4 = []
    for name, t in sec.items():
        if "direction_end_vs_50pct" in name:
            g3.append(
                f"{name}: {t['successes']}/{t['trials']} p={t['p_two_sided']:.4f} "
                f"BH={t['p_bh']:.4f}"
            )
        elif "drift_sign" in name:
            g3.append(
                f"{name}: model {t['model_rate']:.2f} vs drift {t['drift_rate']:.2f} "
                f"p={t['p_two_sided']:.4f} BH={t['p_bh']:.4f}"
            )
        else:
            g4.append(
                f"{name}: {t['successes']}/{t['trials']} p={t['p_two_sided']:.4f} "
                f"BH={t['p_bh']:.4f}; "
                f"per-bar {t['per_bar_coverage_rate_mean']:.2f}; width/close "
                f"{t['mean_band_width_rel']:.4f}; degenerate={t['any_band_degenerate']}"
            )
    L.append(f"| G3 direction | {EXPECTATIONS['G3']} | {'<br>'.join(g3) or 'no data'} |")
    L.append(f"| G4 calibration | {EXPECTATIONS['G4']} | {'<br>'.join(g4) or 'no data'} |")
    g5 = []
    for name, t in summary["tier_b_pooled"].items():
        if t is None:
            g5.append(f"{name}: no data")
        else:
            g5.append(
                f"{name}: ratio {t['geometric_mean_ratio']:.3f} "
                f"CI [{t['ci95_ratio'][0]:.3f}, {t['ci95_ratio'][1]:.3f}] "
                f"(n={t['n']}, {t['clusters']} origin clusters)"
            )
    L.append(f"| G5 Tier B pooled | {EXPECTATIONS['G5']} | {'<br>'.join(g5) or 'no data'} |")
    L.append("")
    L.append("Per-origin MAE ratios (Tier A primary):")
    L.append("")
    for name, t in prim.items():
        if t is not None:
            L.append(
                f"- {name}: "
                + ", ".join(
                    f"{o} {r:.3f}" for o, r in zip(t["origins"], t["per_origin_ratio"], strict=True)
                )
            )
    L.append("")
    L.append("## Exploratory origins (overlap_possible, excluded from every family)")
    L.append("")
    for h, rows in summary["exploratory_overlap_possible"].items():
        for r in rows:
            L.append(
                f"- {h} {r['origin']}: ratio vs drift {r['mae_ratio_vs_drift']:.3f}, vs unchanged "
                f"{r['mae_ratio_vs_unchanged']:.3f}, direction {r['direction_end']}"
            )
    if not any(summary["exploratory_overlap_possible"].values()):
        L.append("- none run")
    if summary.get("tier_c_pooled"):
        L.append("")
        L.append("## Tier C (optional, exploratory)")
        L.append("")
        for name, t in summary["tier_c_pooled"].items():
            if t is not None:
                L.append(
                    f"- {name}: ratio {t['geometric_mean_ratio']:.3f} CI "
                    f"[{t['ci95_ratio'][0]:.3f}, {t['ci95_ratio'][1]:.3f}] "
                    f"symbols {', '.join(t['symbols'])}"
                )
    L.append("")
    L.append("## Failed calls")
    L.append("")
    if summary["failed"]:
        for f in summary["failed"]:
            L.append(f"- `{f['key']}`: {f['reason']}")
    else:
        L.append("- none")
    L.append("")
    L.append("## Reproducibility")
    L.append("")
    db = prov["db"]
    L.append(f"- git SHA: `{prov['git_sha']}`")
    L.append(
        f"- database: `{db['path']}` size {db['size_bytes']} bytes, mtime {db['mtime_utc']}, "
        f"max massive session_date {db['max_session_date_massive']}"
    )
    L.append(f"- runtime_status(): `{json.dumps(prov['runtime_status'], sort_keys=True)}`")
    L.append(
        f"- model: `{prov['model']}`, seed {prov['seed']}, samples {prov['samples']}, "
        f"lookback {prov['lookback']}"
    )
    for repo, h in prov["hf"].items():
        L.append(
            f"- `{repo}` snapshots {h['snapshots']}: combined weights sha256 "
            f"`{h['combined_sha256']}`"
        )
        for f, d in h["files"].items():
            L.append(f"  - `{f}`: `{d}`")
        L.append(
            "  - model-card data-cutoff line: "
            f"{h['model_card_data_cutoff_line'] or 'not present in cached README'}"
        )
    L.append(
        f"- calls analysed: {summary['calls_total']}; regenerate with "
        "`scripts/kronos_skill_study.py report`"
    )
    L.append("")
    return "\n".join(L)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def cmd_plan(args: argparse.Namespace) -> None:
    engine = open_readonly(args.db)
    windows = build_windows(engine, set(args.tier))
    print(f"Kronos forecast-skill study plan (db={args.db}, read-only)")
    print(
        f"Tiers: {''.join(sorted(set(args.tier)))}; horizons {HORIZONS}; "
        f"lookback {service.LOOKBACK}"
    )
    print(f"Tier A origins: {[d.isoformat() for d in tier_a_origins()]}")
    print(f"Tier B origins: {[d.isoformat() for d in tier_b_origins()]}")
    if "C" in args.tier:
        print(f"Tier C symbols: {tier_c_symbols(engine)}")
    bad = 0
    by_tier: dict[str, int] = {}
    for w in windows:
        chk = check_window_bars(engine, w)
        by_tier[w.tier] = by_tier.get(w.tier, 0) + 1
        flag = "ok " if chk["ok"] else "BAD"
        bad += not chk["ok"]
        print(
            f"  {flag} {w.tier} {w.label:16} {w.symbol:5} h={w.horizon:2} origin={w.origin} "
            f"heldout_end={w.heldout_end} bars={chk['bars']}/{chk['needed']}"
        )
    n = len(windows)
    print(f"Windows: {n} total {by_tier}; bar-count problems: {bad}")
    for per_call in (50, 90):
        print(f"Projected runtime at {per_call}s/call: {n * per_call / 3600:.1f} h")
    print(f"DB facts: {json.dumps(db_facts(engine, args.db), sort_keys=True)}")


def cmd_pilot(args: argparse.Namespace) -> None:
    engine = open_readonly(args.db)
    windows = [w for w in build_windows(engine, {"A"}) if w.label == "primary"][:3]
    total = len(build_windows(engine, set(args.tier)))
    latencies = run_windows(engine, args.out, windows)
    if latencies:
        mean = sum(latencies) / len(latencies)
        print(f"Measured latency: {[round(v, 1) for v in latencies]} mean {mean:.1f}s")
        print(f"Projected total for {total} windows: {total * mean / 3600:.1f} h")
    else:
        print("No successful pilot call; see calls.jsonl")


def cmd_run(args: argparse.Namespace) -> None:
    engine = open_readonly(args.db)
    windows = build_windows(engine, set(args.tier))
    latencies = run_windows(engine, args.out, windows)
    if latencies:
        print(
            f"Completed {len(latencies)} calls, mean latency {sum(latencies) / len(latencies):.1f}s"
        )


def cmd_report(args: argparse.Namespace) -> None:
    engine = open_readonly(args.db)
    calls = load_calls(args.out)
    if not calls:
        raise SystemExit(f"No calls recorded in {calls_path(args.out)}")
    summary = analyse(calls)
    prov = provenance(engine, args.db)
    run_date = args.out.name
    summary_path = args.out / "summary.json"
    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8"
    )
    md_path = args.out / f"KRONOS_SKILL_STUDY_{run_date}.md"
    md_path.write_text(render_markdown(summary, prov, run_date), encoding="utf-8")
    print(f"wrote {summary_path}\nwrote {md_path}")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument(
        "--run-date", default=os.environ.get("KRONOS_STUDY_RUN_DATE", date.today().isoformat())
    )
    ap.add_argument("--out-root", type=Path, default=DEFAULT_OUT)
    ap.add_argument(
        "--tier", action="append", choices=["A", "B", "C"], help="repeatable; default A and B"
    )
    sub = ap.add_subparsers(dest="command", required=True)
    sub.add_parser("plan").set_defaults(func=cmd_plan)
    sub.add_parser("pilot").set_defaults(func=cmd_pilot)
    sub.add_parser("run").set_defaults(func=cmd_run)
    sub.add_parser("report").set_defaults(func=cmd_report)
    args = ap.parse_args(argv)
    args.tier = args.tier or ["A", "B"]
    args.out = args.out_root / args.run_date
    args.func(args)


if __name__ == "__main__":
    main(sys.argv[1:])
