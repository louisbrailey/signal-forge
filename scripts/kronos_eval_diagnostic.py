"""Pre-registered Kronos eval-mode diagnostic (read-only database, local inference).

Explains the null of the first Kronos skill study: the worker never called ``.eval()``,
so every earlier forecast was produced with dropout active. Three arms are run once:

* ``A0`` replication of the pre-fix behaviour (train mode, T=1.0, top_p=0.9, 3 paths)
* ``A1`` = A0 with the model and tokenizer in eval mode
* ``A2`` (primary) eval mode, T=0.6, top_p=0.9, 10 seeded paths

Sub-commands:

* ``plan``   — list every pre-registered window and check bar counts with plain SQL.
               No inference, no model load.
* ``run``    — run every window of the chosen arm(s) not yet completed (resume-safe),
               appending to ``<out>/<arm>/calls.jsonl``.
* ``report`` — regenerate ``summary.json`` and the Markdown report from the ledgers
               only (no inference).

The database is opened READ-ONLY (``mode=ro``); nothing here writes to it. Inference
goes through ``signalforge.kronos.service.study_replay`` and shares the one-process OS
lock with the ``/kronos`` dashboard. This script never imports paper, execution, risk,
alerts, llm or the live scan. It is NOT an integration gate (ADR 0004 is closed).
Design: ``docs/research/kronos/PREREGISTRATION_2026-10-03_kronos_eval_mode_diagnostic.md``.
Nothing produced here is a trading instruction.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from signalforge.data.calendar import sessions
from signalforge.kronos import service, study

REPO = Path(__file__).resolve().parents[1]
DEFAULT_DB = Path.home() / "signal-forge" / "data" / "signalforge.sqlite"
DEFAULT_OUT = REPO / "docs" / "research" / "kronos" / "2026-10-03-diagnostic"
FIRST_STUDY_CALLS = REPO / "docs" / "research" / "kronos" / "2026-10-02" / "calls.jsonl"
REPORT_NAME = "KRONOS_EVAL_MODE_DIAGNOSTIC_2026-10-03.md"
HF_HUB = Path.home() / ".cache" / "huggingface" / "hub"
HF_REPOS = ("models--NeoQuasar--Kronos-small", "models--NeoQuasar--Kronos-Tokenizer-base")

SPY = "SPY"
SECTORS = ("XLB", "XLC", "XLE", "XLF", "XLI", "XLK", "XLP", "XLRE", "XLU", "XLV", "XLY")
SYMBOLS = (SPY, *SECTORS)
HORIZONS = (5, 20)
ORIGIN_START = date(2025, 9, 30)
ORIGIN_END = date(2026, 8, 31)
ORIGIN_STEP = 5
ARMS: dict[str, dict[str, Any]] = {
    "A0": {"eval": False, "T": 1.0, "top_p": 0.9, "samples": 3, "return_paths": True},
    "A1": {"eval": True, "T": 1.0, "top_p": 0.9, "samples": 3, "return_paths": True},
    "A2": {"eval": True, "T": 0.6, "top_p": 0.9, "samples": 10, "return_paths": True},
}
ARM_LABELS = {
    "A0": "replication of pre-fix behaviour (train mode, T=1.0, top_p=0.9, 3 paths)",
    "A1": "A0 + eval mode on model and tokenizer",
    "A2": "PRIMARY: eval mode, T=0.6, top_p=0.9, 10 paths",
}
PRIMARY_ARM = "A2"
BUSY_RETRIES = 5
BUSY_SLEEP_S = 30.0
N_BOOT = 10_000
BOOT_SEED = 20261003
BLOCK_SENSITIVITY = {5: 1, 20: 4}
NICE_TARGET = 15

STOPPING_RULE = (
    "Run A0–A2 once; if A2's upper 95% CI for the error ratio is not below 1.0 at either "
    'horizon AND mean rank IC has |t| < 2, STOP and record "no zero-shot skill; not a '
    'settings artefact"; no further arms, knobs, lookbacks or model sizes. If either '
    "passes, record which and stop anyway — any follow-up is a new pre-registration. "
    "Volatility is reported but cannot rescue the price gate."
)
NULL_VERDICT = "no zero-shot skill; not a settings artefact"

EXPECTATIONS = {
    "A0": "Reproduces the first study: error ratio vs unchanged above 1 at both horizons.",
    "A1": "Eval mode lowers error relative to A0 (dropout noise removed), but a mean of 3 "
    "sampled paths is still noisy against a deterministic baseline; ratio >= 1.",
    "A2": "Ratio close to but NOT below 1 (upper 95% CI not below 1.0 at either horizon); "
    "mean rank IC indistinguishable from 0 (|t| < 2) at both horizons; direction at or "
    "below the majority-class rate; coverage below the finite-sample reference "
    "(under-dispersion at T=0.6); trailing-20-day vol at least as good as Kronos vol.",
    "verdict": f'Expected verdict: "{NULL_VERDICT}".',
}


@dataclass(frozen=True)
class Window:
    symbol: str
    horizon: int
    origin: date
    heldout_end: date

    @property
    def key(self) -> str:
        return f"{self.symbol}|{self.horizon}|{self.heldout_end.isoformat()}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "horizon": self.horizon,
            "origin": self.origin.isoformat(),
            "heldout_end": self.heldout_end.isoformat(),
            "key": self.key,
        }


# ---------------------------------------------------------------------------
# Design (mechanical rules; no selection on outcome)
# ---------------------------------------------------------------------------


def origins() -> list[date]:
    """Every 5th XNYS session from 2025-09-30 through 2026-08-31 inclusive."""
    return list(sessions(ORIGIN_START, ORIGIN_END))[::ORIGIN_STEP]


def heldout_end_for(origin: date, horizon: int) -> date:
    after = sessions(origin + timedelta(days=1), origin + timedelta(days=60))
    return after[horizon - 1]


def build_windows() -> list[Window]:
    return [
        Window(symbol, h, origin, heldout_end_for(origin, h))
        for origin in origins()
        for symbol in SYMBOLS
        for h in HORIZONS
    ]


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
# Call ledger (one per arm)
# ---------------------------------------------------------------------------


def calls_path(out_dir: Path, arm: str) -> Path:
    return out_dir / arm / "calls.jsonl"


def read_ledger(path: Path) -> dict[str, dict[str, Any]]:
    """Latest record per key (a later retry supersedes an earlier failure)."""
    latest: dict[str, dict[str, Any]] = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rec = json.loads(line)
                latest[rec["key"]] = rec
    return latest


def append_call(out_dir: Path, arm: str, record: dict[str, Any]) -> None:
    path = calls_path(out_dir, arm)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, sort_keys=True, allow_nan=False) + "\n")


def git_sha() -> str | None:
    try:
        proc = subprocess.run(
            ["/usr/bin/git", "rev-parse", "HEAD"],
            cwd=REPO,
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except OSError:
        return None
    return proc.stdout.strip() or None


def execute_window(session: Session, arm: str, window: Window, sha: str | None) -> dict[str, Any]:
    """One study replay with the pre-registered retry policy; returns the ledger record."""
    mode = ARMS[arm]
    base: dict[str, Any] = {
        "arm": arm,
        "mode": mode,
        "window": window.to_dict(),
        "key": window.key,
        "git_sha": sha,
    }
    busy = 0
    timeouts = 0
    while True:
        started = time.monotonic()
        try:
            result = service.study_replay(
                session, window.symbol, window.horizon, as_of=window.heldout_end, mode=mode
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
        expected = {k: mode[k] for k in ("eval", "T", "top_p", "samples")}
        if result["inference"] != expected:
            raise AssertionError(f"{window.key}: inference mode mismatch")
        context_closes = [b["close"] for b in result["history"]]
        metrics = study.diagnostic_window_metrics(
            context_closes=context_closes, actual=result["actual"], paths=result["paths"]
        )
        return {
            **base,
            "status": "ok",
            "latency_s": round(latency, 3),
            "busy_retries": busy,
            "timeout_retries": timeouts,
            "context_closes_tail": context_closes[-21:],
            "result": {
                k: result[k]
                for k in (
                    "id",
                    "ticker",
                    "model",
                    "input_start",
                    "input_end",
                    "heldout_start",
                    "heldout_end",
                    "dates",
                    "actual",
                    "predicted",
                    "paths",
                    "inference",
                    "seed",
                )
            },
            "metrics": metrics,
        }


def run_arm(engine: Engine, out_dir: Path, arm: str, windows: list[Window]) -> None:
    done = {k for k, r in read_ledger(calls_path(out_dir, arm)).items() if r["status"] == "ok"}
    todo = [w for w in windows if w.key not in done]
    print(
        f"[{arm}] {len(windows)} windows, {len(done)} already complete, {len(todo)} to run",
        flush=True,
    )
    sha = git_sha()
    latencies: list[float] = []
    with Session(engine) as session:
        for i, window in enumerate(todo, 1):
            record = execute_window(session, arm, window, sha)
            append_call(out_dir, arm, record)
            if record["status"] == "ok":
                latencies.append(record["latency_s"])
                m = record["metrics"]
                print(
                    f"[{arm} {i}/{len(todo)}] {window.key} ok {record['latency_s']:.1f}s "
                    f"r_hat={m['r_hat']:+.4f} r={m['r']:+.4f}",
                    flush=True,
                )
            else:
                print(
                    f"[{arm} {i}/{len(todo)}] {window.key} FAILED: {record['reason']}", flush=True
                )
            session.rollback()  # never hold a transaction between calls
    if latencies:
        print(
            f"[{arm}] completed {len(latencies)} calls, mean latency "
            f"{sum(latencies) / len(latencies):.1f}s",
            flush=True,
        )


# ---------------------------------------------------------------------------
# Analysis (ledger only; no inference)
# ---------------------------------------------------------------------------


def _by_origin(records: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for r in sorted(records, key=lambda r: (r["window"]["origin"], r["window"]["symbol"])):
        out.setdefault(r["window"]["origin"], []).append(r)
    return out


def _error_ratio(groups: dict[str, list[dict[str, Any]]], block: int) -> dict[str, Any]:
    num = [sum(r["metrics"]["abs_err_model"] for r in g) for g in groups.values()]
    den = [sum(r["metrics"]["abs_err_unchanged"] for r in g) for g in groups.values()]
    return study.cluster_bootstrap_log_ratio(num, den, n_boot=N_BOOT, seed=BOOT_SEED, block=block)


def _rank_ic(groups: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    ics: list[float] = []
    dropped: list[str] = []
    for origin, group in groups.items():
        by_symbol = {r["window"]["symbol"]: r["metrics"] for r in group}
        if any(s not in by_symbol for s in SECTORS):
            dropped.append(origin)
            continue
        ic = study.spearman(
            [by_symbol[s]["r_hat"] for s in SECTORS], [by_symbol[s]["r"] for s in SECTORS]
        )
        if ic is None:
            dropped.append(origin)
            continue
        ics.append(ic)
    out: dict[str, Any] = {"origins_dropped": dropped, "per_origin": ics}
    if len(ics) >= 2:
        out.update(study.rank_ic_summary(ics))
    else:
        out.update({"n": len(ics), "mean": None, "sd": None, "t_stat": None})
        out["share_positive"] = None
    return out


def _direction(groups: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    hits = np.array([sum(r["metrics"]["direction_hit"] for r in g) for g in groups.values()])
    ups = np.array([sum(r["metrics"]["r_sign"] > 0 for r in g) for g in groups.values()])
    downs = np.array([sum(r["metrics"]["r_sign"] < 0 for r in g) for g in groups.values()])
    counts = np.array([len(g) for g in groups.values()])
    n = int(counts.sum())
    accuracy = float(hits.sum() / n)
    majority = float(max(ups.sum(), downs.sum()) / n)
    idx = study.bootstrap_cluster_indices(len(groups), n_boot=N_BOOT, seed=BOOT_SEED)
    b_n = counts[idx].sum(axis=1)
    draws = hits[idx].sum(axis=1) / b_n - (
        np.maximum(ups[idx].sum(axis=1), downs[idx].sum(axis=1)) / b_n
    )
    return {
        "n": n,
        "accuracy": accuracy,
        "majority_class_rate": majority,
        "majority_class": "up" if ups.sum() >= downs.sum() else "down",
        "share_predicted_up": None,
        "difference": study.bootstrap_summary(accuracy - majority, draws),
    }


def _volatility(
    records: list[dict[str, Any]], groups: dict[str, list[dict[str, Any]]]
) -> dict[str, Any]:
    def err(r: dict[str, Any], key: str) -> float:
        return abs(float(r["metrics"][key]) - float(r["metrics"]["vol_realised"]))

    num = [sum(err(r, "vol_predicted") for r in g) for g in groups.values()]
    den = [sum(err(r, "vol_trailing20") for r in g) for g in groups.values()]
    realised = [r["metrics"]["vol_realised"] for r in records]
    return {
        "mae_kronos": float(np.mean([err(r, "vol_predicted") for r in records])),
        "mae_trailing20": float(np.mean([err(r, "vol_trailing20") for r in records])),
        "mae_ratio": study.cluster_bootstrap_log_ratio(num, den, n_boot=N_BOOT, seed=BOOT_SEED),
        "spearman_kronos": study.spearman(
            [r["metrics"]["vol_predicted"] for r in records], realised
        ),
        "spearman_trailing20": study.spearman(
            [r["metrics"]["vol_trailing20"] for r in records], realised
        ),
        "mean_vol_predicted": float(np.mean([r["metrics"]["vol_predicted"] for r in records])),
        "mean_vol_trailing20": float(np.mean([r["metrics"]["vol_trailing20"] for r in records])),
        "mean_vol_realised": float(np.mean(realised)),
    }


def analyse_horizon(records: list[dict[str, Any]], horizon: int) -> dict[str, Any] | None:
    recs = [r for r in records if r["status"] == "ok" and r["window"]["horizon"] == horizon]
    if not recs:
        return None
    groups = _by_origin(recs)
    n_paths = {r["metrics"]["n_paths"] for r in recs}
    logs = [
        math.log(r["metrics"]["abs_err_model"] / r["metrics"]["abs_err_unchanged"])
        for r in recs
        if r["metrics"]["abs_err_model"] > 0 and r["metrics"]["abs_err_unchanged"] > 0
    ]
    direction = _direction(groups)
    direction["share_predicted_up"] = float(np.mean([r["metrics"]["r_hat"] > 0 for r in recs]))
    block = BLOCK_SENSITIVITY[horizon]
    return {
        "horizon": horizon,
        "n_calls": len(recs),
        "n_origins": len(groups),
        "error_ratio": _error_ratio(groups, 1),
        "error_ratio_block_sensitivity": _error_ratio(groups, block),
        "per_call_log_ratio": {
            "mean": float(np.mean(logs)) if logs else None,
            "geometric_mean_ratio": math.exp(float(np.mean(logs))) if logs else None,
            "n_defined": len(logs),
            "n_undefined": len(recs) - len(logs),
        },
        "mae_model": float(np.mean([r["metrics"]["abs_err_model"] for r in recs])),
        "mae_unchanged": float(np.mean([r["metrics"]["abs_err_unchanged"] for r in recs])),
        "mean_r_hat": float(np.mean([r["metrics"]["r_hat"] for r in recs])),
        "mean_r": float(np.mean([r["metrics"]["r"] for r in recs])),
        "rank_ic": _rank_ic(groups),
        "direction": direction,
        "coverage": {
            "n": len(recs),
            "rate": float(np.mean([r["metrics"]["covered_10_90"] for r in recs])),
            "nominal": 0.8,
            "n_paths": sorted(n_paths),
            "finite_sample_reference": study.quantile_band_reference_coverage(max(n_paths)),
        },
        "volatility": _volatility(recs, groups),
    }


def analyse_arm(calls: dict[str, dict[str, Any]], planned: int) -> dict[str, Any]:
    records = list(calls.values())
    ok = [r for r in records if r["status"] == "ok"]
    horizons = {str(h): analyse_horizon(records, h) for h in HORIZONS}
    present = [h for h in HORIZONS if horizons[str(h)] is not None]
    adjusted = study.holm_adjust(
        [horizons[str(h)]["error_ratio"]["p_two_sided"] for h in present]  # type: ignore[index]
    )
    for h, p in zip(present, adjusted, strict=True):
        horizons[str(h)]["error_ratio"]["p_holm"] = p  # type: ignore[index]
    latencies = [r["latency_s"] for r in ok]
    return {
        "planned": planned,
        "recorded": len(records),
        "ok": len(ok),
        "failed": [
            {"key": r["key"], "reason": r.get("reason")}
            for r in sorted(records, key=lambda r: r["key"])
            if r["status"] != "ok"
        ],
        "latency_s": {
            "mean": float(np.mean(latencies)) if latencies else None,
            "max": float(np.max(latencies)) if latencies else None,
            "total_h": float(np.sum(latencies) / 3600) if latencies else None,
        },
        "git_shas": sorted({str(r.get("git_sha")) for r in records}),
        "horizons": horizons,
    }


def verdict(primary: dict[str, Any]) -> dict[str, Any]:
    """Mechanical application of the pre-registered stopping rule to arm A2."""
    ratio_pass: list[str] = []
    ic_pass: list[str] = []
    detail: dict[str, Any] = {}
    complete = True
    for h in HORIZONS:
        res = primary["horizons"][str(h)]
        if res is None or res["rank_ic"]["t_stat"] is None:
            complete = False
            continue
        upper = res["error_ratio"]["ratio_ci"][1]
        t = res["rank_ic"]["t_stat"]
        detail[str(h)] = {
            "error_ratio": res["error_ratio"]["ratio"],
            "error_ratio_ci": res["error_ratio"]["ratio_ci"],
            "error_ratio_upper_below_1": upper < 1.0,
            "error_ratio_p_holm": res["error_ratio"].get("p_holm"),
            "rank_ic_mean": res["rank_ic"]["mean"],
            "rank_ic_t": t,
            "rank_ic_abs_t_ge_2": abs(t) >= 2.0,
        }
        if upper < 1.0:
            ratio_pass.append(f"h={h}")
        if abs(t) >= 2.0:
            sign = "positive" if t > 0 else "NEGATIVE (not skill)"
            ic_pass.append(f"h={h} (t={t:+.2f}, {sign})")
    if not complete:
        text_ = "INCOMPLETE: arm A2 does not have both horizons; no verdict."
    elif not ratio_pass and not ic_pass:
        text_ = NULL_VERDICT
    else:
        parts = []
        if ratio_pass:
            parts.append("error-ratio condition passed at " + ", ".join(ratio_pass))
        if ic_pass:
            parts.append("rank-IC condition passed at " + ", ".join(ic_pass))
        text_ = (
            "; ".join(parts) + ". Diagnostic stops anyway; any follow-up is a new pre-registration."
        )
    return {
        "rule": STOPPING_RULE,
        "complete": complete,
        "error_ratio_condition_passed_at": ratio_pass,
        "rank_ic_condition_passed_at": ic_pass,
        "null_verdict_recorded": complete and not ratio_pass and not ic_pass,
        "verdict": text_,
        "detail": detail,
    }


def replication_check(a0: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """A0 vs the first study's ledger on coinciding keys (integrity check, not a metric)."""
    first = read_ledger(FIRST_STUDY_CALLS)
    diffs: list[float] = []
    keys: list[str] = []
    for key, rec in sorted(a0.items()):
        other = first.get(key)
        if rec["status"] != "ok" or other is None or other.get("status") != "ok":
            continue
        a = rec["result"]["predicted"]
        b = other["result"]["predicted"]
        if len(a) != len(b):
            continue
        keys.append(key)
        diffs.append(max(abs(x - y) for x, y in zip(a, b, strict=True)))
    return {
        "first_study_ledger": str(FIRST_STUDY_CALLS.relative_to(REPO)),
        "coinciding_keys": len(keys),
        "max_abs_diff_predicted": max(diffs) if diffs else None,
        "identical_keys": sum(d == 0 for d in diffs),
        "keys": keys,
    }


def analyse(out_dir: Path) -> dict[str, Any]:
    planned = len(build_windows())
    ledgers = {arm: read_ledger(calls_path(out_dir, arm)) for arm in ARMS}
    arms = {arm: analyse_arm(ledgers[arm], planned) for arm in ARMS}
    return {
        "design": {
            "symbols": list(SYMBOLS),
            "rank_ic_symbols": list(SECTORS),
            "origins": [d.isoformat() for d in origins()],
            "horizons": list(HORIZONS),
            "lookback": service.LOOKBACK,
            "arms": ARMS,
            "primary_arm": PRIMARY_ARM,
            "n_boot": N_BOOT,
            "bootstrap_seed": BOOT_SEED,
            "block_sensitivity": {str(k): v for k, v in BLOCK_SENSITIVITY.items()},
            "not_an_integration_gate": True,
        },
        "expectations": EXPECTATIONS,
        "arms": arms,
        "replication_check_A0_vs_first_study": replication_check(ledgers["A0"]),
        "stopping_rule": verdict(arms[PRIMARY_ARM]),
    }


# ---------------------------------------------------------------------------
# Provenance and report
# ---------------------------------------------------------------------------


def hf_provenance() -> dict[str, Any]:
    out: dict[str, Any] = {}
    for repo in HF_REPOS:
        root = HF_HUB / repo / "snapshots"
        dirs = sorted(p for p in root.iterdir() if p.is_dir()) if root.is_dir() else []
        entry: dict[str, Any] = {"snapshots": [d.name for d in dirs]}
        entry.update(study.sha256_of_tree(dirs))
        out[repo] = entry
    return out


def provenance(engine: Engine, db: Path) -> dict[str, Any]:
    return {
        "git_sha_at_report": git_sha(),
        "db": db_facts(engine, db),
        "model": service.MODEL,
        "seed_base": 42,
        "lookback": service.LOOKBACK,
        "hf": hf_provenance(),
    }


def _f(v: float | None, nd: int = 3) -> str:
    return "n/a" if v is None else f"{v:.{nd}f}"


def _pct(v: float | None) -> str:
    return "n/a" if v is None else f"{100 * v:.1f}%"


def headline_rows(summary: dict[str, Any]) -> list[str]:
    rows = [
        "| Arm | h | calls | error ratio vs unchanged [95% CI] | Holm p | rank IC mean (t; "
        "share>0) | direction vs majority | 10–90% coverage (ref) | vol MAE ratio "
        "Kronos/trailing-20 [95% CI] | vol Spearman Kronos / trailing |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for arm in ARMS:
        for h in HORIZONS:
            res = summary["arms"][arm]["horizons"][str(h)]
            if res is None:
                rows.append(f"| {arm} | {h} | 0 | n/a | n/a | n/a | n/a | n/a | n/a | n/a |")
                continue
            er = res["error_ratio"]
            ic = res["rank_ic"]
            d = res["direction"]
            c = res["coverage"]
            v = res["volatility"]
            vr = v["mae_ratio"]
            rows.append(
                f"| {arm} | {h} | {res['n_calls']} | {_f(er['ratio'])} "
                f"[{_f(er['ratio_ci'][0])}, {_f(er['ratio_ci'][1])}] | {_f(er.get('p_holm'), 4)} "
                f"| {_f(ic['mean'])} (t={_f(ic['t_stat'], 2)}; {_pct(ic['share_positive'])}) "
                f"| {_pct(d['accuracy'])} vs {_pct(d['majority_class_rate'])} "
                f"| {_pct(c['rate'])} ({_pct(c['finite_sample_reference'])}) "
                f"| {_f(vr['ratio'])} [{_f(vr['ratio_ci'][0])}, {_f(vr['ratio_ci'][1])}] "
                f"| {_f(v['spearman_kronos'])} / {_f(v['spearman_trailing20'])} |"
            )
    return rows


def render_markdown(summary: dict[str, Any], prov: dict[str, Any]) -> str:
    L: list[str] = []
    L.append("# Kronos eval-mode diagnostic — results (2026-10-03)")
    L.append("")
    L.append(f"> {service.NOTICE}")
    L.append("")
    L.append(
        "Pre-registration: `docs/research/kronos/PREREGISTRATION_2026-10-03_kronos_eval_mode_"
        "diagnostic.md`. This diagnostic explains the null of the first study; it is **not "
        "an integration gate** (ADR 0004 is closed; any integration is a new ADR). Generated "
        "by `scripts/kronos_eval_diagnostic.py report` from the per-arm `calls.jsonl` "
        "ledgers only."
    )
    L.append("")
    sr = summary["stopping_rule"]
    L.append("## Stopping-rule verdict")
    L.append("")
    L.append("Rule (verbatim from the pre-registration):")
    L.append("")
    L.append(f"> {sr['rule']}")
    L.append("")
    L.append(f"**Verdict: {sr['verdict']}**")
    L.append("")
    for h in HORIZONS:
        d = sr["detail"].get(str(h))
        if d is None:
            continue
        L.append(
            f"- A2 h={h}: error ratio {_f(d['error_ratio'])} "
            f"[{_f(d['error_ratio_ci'][0])}, {_f(d['error_ratio_ci'][1])}], upper bound "
            f"{'below' if d['error_ratio_upper_below_1'] else 'NOT below'} 1.0 "
            f"(Holm p {_f(d['error_ratio_p_holm'], 4)}); mean rank IC {_f(d['rank_ic_mean'])}, "
            f"t = {_f(d['rank_ic_t'], 2)} (|t| {'>= 2' if d['rank_ic_abs_t_ge_2'] else '< 2'})."
        )
    L.append(
        "- Volatility is reported below but cannot rescue the price gate. No further arms, "
        "knobs, lookbacks or model sizes are run under this pre-registration."
    )
    L.append("")
    L.append("## Headline table")
    L.append("")
    for arm in ARMS:
        L.append(f"- **{arm}** — {ARM_LABELS[arm]}")
    L.append("")
    L.extend(headline_rows(summary))
    L.append("")
    L.append(
        "Error ratio = Σ|predicted − realised h-day log return| / Σ|realised h-day log "
        "return| over all 12 symbols and origins (below 1 = better than predicting zero "
        "return); CI = origin-cluster percentile bootstrap, 10,000 draws. Rank IC = "
        "per-origin Spearman across the 11 sector ETFs. Coverage reference = expected "
        "coverage of a perfectly calibrated ensemble of that many paths (nominal 80%). "
        "Only A2's error ratio and rank IC enter the stopping rule; everything else is "
        "descriptive. h=20 windows overlap (origins are 5 sessions apart), so the h=20 CI "
        "is too narrow and the h=20 t-statistic too large."
    )
    L.append("")
    L.append("## Expectations next to outcomes")
    L.append("")
    for arm in ARMS:
        L.append(f"### {arm} — {ARM_LABELS[arm]}")
        L.append("")
        L.append(f"- Expected (pre-registered): {summary['expectations'][arm]}")
        a = summary["arms"][arm]
        L.append(
            f"- Calls: {a['ok']} ok of {a['planned']} planned ({len(a['failed'])} failed); mean "
            f"latency {_f(a['latency_s']['mean'], 2)} s, total "
            f"{_f(a['latency_s']['total_h'], 2)} h."
        )
        for h in HORIZONS:
            res = a["horizons"][str(h)]
            if res is None:
                L.append(f"- h={h}: no completed calls.")
                continue
            er = res["error_ratio"]
            bs = res["error_ratio_block_sensitivity"]
            pc = res["per_call_log_ratio"]
            ic = res["rank_ic"]
            d = res["direction"]
            c = res["coverage"]
            v = res["volatility"]
            L.append(f"- **h={h}** ({res['n_calls']} calls, {res['n_origins']} origins)")
            L.append(
                f"  - Error ratio vs unchanged {_f(er['ratio'])} "
                f"[{_f(er['ratio_ci'][0])}, {_f(er['ratio_ci'][1])}], bootstrap p "
                f"{_f(er['p_two_sided'], 4)}, Holm p {_f(er.get('p_holm'), 4)}; block-bootstrap "
                f"sensitivity (block {bs['block']}) CI [{_f(bs['ratio_ci'][0])}, "
                f"{_f(bs['ratio_ci'][1])}]. Mean |error| model {_f(res['mae_model'], 4)} vs "
                f"unchanged {_f(res['mae_unchanged'], 4)} (log-return units). Per-call "
                f"geometric-mean ratio {_f(pc['geometric_mean_ratio'])} "
                f"({pc['n_undefined']} undefined)."
            )
            L.append(
                f"  - Mean predicted h-day log return {res['mean_r_hat']:+.4f} vs realised "
                f"{res['mean_r']:+.4f}; share of calls predicted up "
                f"{_pct(d['share_predicted_up'])}."
            )
            L.append(
                f"  - Rank IC mean {_f(ic['mean'])}, t = {_f(ic['t_stat'], 2)}, share positive "
                f"{_pct(ic['share_positive'])} over {ic['n']} origins "
                f"({len(ic['origins_dropped'])} dropped)."
            )
            diff = d["difference"]
            L.append(
                f"  - Direction {_pct(d['accuracy'])} vs majority-class "
                f"({d['majority_class']}) rate {_pct(d['majority_class_rate'])}; difference "
                f"{100 * diff['estimate']:+.1f} pp [{100 * diff['ci'][0]:+.1f}, "
                f"{100 * diff['ci'][1]:+.1f}]."
            )
            L.append(
                f"  - 10–90% quantile coverage {_pct(c['rate'])} (nominal 80%; finite-sample "
                f"reference for {max(c['n_paths'])} paths {_pct(c['finite_sample_reference'])})."
            )
            vr = v["mae_ratio"]
            L.append(
                f"  - Volatility: MAE Kronos {_f(v['mae_kronos'], 5)} vs trailing-20 "
                f"{_f(v['mae_trailing20'], 5)}, ratio {_f(vr['ratio'])} "
                f"[{_f(vr['ratio_ci'][0])}, {_f(vr['ratio_ci'][1])}]; Spearman with realised "
                f"vol: Kronos {_f(v['spearman_kronos'])}, trailing-20 "
                f"{_f(v['spearman_trailing20'])}. Mean daily vol: predicted "
                f"{_f(v['mean_vol_predicted'], 5)}, trailing {_f(v['mean_vol_trailing20'], 5)}, "
                f"realised {_f(v['mean_vol_realised'], 5)}."
            )
        L.append("")
    L.append(f"- {summary['expectations']['verdict']} Outcome: **{sr['verdict']}**")
    L.append("")
    rc = summary["replication_check_A0_vs_first_study"]
    L.append("## Integrity check — A0 vs the first study")
    L.append("")
    L.append(
        f"{rc['coinciding_keys']} A0 keys coincide with `{rc['first_study_ledger']}`; "
        f"{rc['identical_keys']} have bit-identical `predicted`; maximum absolute difference "
        f"{'n/a' if rc['max_abs_diff_predicted'] is None else repr(rc['max_abs_diff_predicted'])}. "
        "Expected 0: A0 is the pre-fix behaviour with the same seeds and inputs."
    )
    L.append("")
    L.append("## Failed calls")
    L.append("")
    any_failed = False
    for arm in ARMS:
        for f in summary["arms"][arm]["failed"]:
            any_failed = True
            L.append(f"- {arm} `{f['key']}`: {f['reason']}")
    if not any_failed:
        L.append("None. Every planned call of every arm completed.")
    L.append("")
    L.append("## Reproducibility")
    L.append("")
    L.append(f"- Git SHA at report time: `{prov['git_sha_at_report']}`")
    for arm in ARMS:
        L.append(
            f"- Git SHA(s) recorded by {arm} calls: "
            f"{', '.join(f'`{s}`' for s in summary['arms'][arm]['git_shas']) or 'n/a'}"
        )
    db = prov["db"]
    L.append(
        f"- DB `{db['path']}` opened `mode=ro`; size {db['size_bytes']:,} bytes; mtime "
        f"{db['mtime_utc']}; max massive `session_date` {db['max_session_date_massive']}."
    )
    for repo, entry in prov["hf"].items():
        L.append(
            f"- Weights `{repo}` snapshot(s) {entry['snapshots']}; combined sha256 "
            f"`{entry['combined_sha256']}`"
        )
        for name, digest in entry["files"].items():
            L.append(f"  - `{name}` sha256 `{digest}`")
    L.append(
        f"- Model `{prov['model']}`, lookback {prov['lookback']}, path seeds "
        f"{prov['seed_base']}+i, bootstrap seed {BOOT_SEED} ({N_BOOT:,} draws)."
    )
    L.append(
        "- Regenerate: `uv run python scripts/kronos_eval_diagnostic.py report` "
        "(ledger only, no inference)."
    )
    L.append("")
    return "\n".join(L)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def cmd_plan(args: argparse.Namespace) -> None:
    engine = open_readonly(args.db)
    windows = build_windows()
    print(f"Kronos eval-mode diagnostic plan (db={args.db}, read-only; no inference)")
    print(f"Symbols: {list(SYMBOLS)}; horizons {HORIZONS}; lookback {service.LOOKBACK}")
    for arm, mode in ARMS.items():
        print(f"Arm {arm}: {json.dumps(mode, sort_keys=True)}  # {ARM_LABELS[arm]}")
    grid = origins()
    print(f"Origins ({len(grid)}): {[d.isoformat() for d in grid]}")
    bad: list[str] = []
    for origin in grid:
        ends = {h: heldout_end_for(origin, h) for h in HORIZONS}
        flags = []
        for symbol in SYMBOLS:
            ok = True
            for h in HORIZONS:
                w = Window(symbol, h, origin, ends[h])
                if not check_window_bars(engine, w)["ok"]:
                    ok = False
                    bad.append(w.key)
            flags.append(f"{symbol}:{'ok' if ok else 'BAD'}")
        print(
            f"  origin={origin} heldout_end h5={ends[5]} h20={ends[20]} "
            f"bars 133/148 {' '.join(flags)}"
        )
    n = len(windows)
    print(f"Windows per arm: {n}; arms: {len(ARMS)}; total calls: {n * len(ARMS)}")
    print(f"Bar-count problems: {len(bad)} {bad if bad else ''}".rstrip())
    for per_call in (3, 10):
        print(f"Projected runtime per arm at {per_call}s/call: {n * per_call / 3600:.1f} h")
    print(f"DB facts: {json.dumps(db_facts(engine, args.db), sort_keys=True)}")


def cmd_run(args: argparse.Namespace) -> None:
    current = os.nice(0)
    if current < NICE_TARGET:
        os.nice(NICE_TARGET - current)
    engine = open_readonly(args.db)
    windows = build_windows()
    for arm in args.arm or list(ARMS):
        run_arm(engine, args.out, arm, windows)


def cmd_report(args: argparse.Namespace) -> None:
    engine = open_readonly(args.db)
    summary = analyse(args.out)
    if not any(summary["arms"][arm]["recorded"] for arm in ARMS):
        raise SystemExit(f"No calls recorded under {args.out}")
    prov = provenance(engine, args.db)
    summary["provenance"] = prov
    summary_path = args.out / "summary.json"
    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8"
    )
    md_path = args.out / REPORT_NAME
    md_path.write_text(render_markdown(summary, prov), encoding="utf-8")
    print(f"wrote {summary_path}\nwrote {md_path}")
    print(f"Verdict: {summary['stopping_rule']['verdict']}")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    sub = ap.add_subparsers(dest="command", required=True)
    sub.add_parser("plan").set_defaults(func=cmd_plan)
    run = sub.add_parser("run")
    run.add_argument("--arm", action="append", choices=list(ARMS), help="repeatable; default all")
    run.set_defaults(func=cmd_run)
    sub.add_parser("report").set_defaults(func=cmd_report)
    args = ap.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main(sys.argv[1:])
