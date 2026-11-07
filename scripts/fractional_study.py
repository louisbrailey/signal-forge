"""Compare fractional and whole-share R1 books on the same local snapshot."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import multiprocessing
import os
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict
from decimal import Decimal
from functools import cache
from pathlib import Path
from tempfile import TemporaryDirectory

import fractional_lots
import refinement_rules
import refinement_study as r1
from fractional_lots import SHARE_STEP, settle

from signalforge.backtest import funded
from signalforge.research.prospective_funded import code_digest, write_once

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / "docs/research/FRACTIONAL_STUDY_2026-11-06.md"
OVERLAY = ROOT / "scripts/research_overlays/funded_fractional.patch"
# Checksum of the original funded replay source, shared by R1 and its archive.
FUNDED_SHA256 = (
    "d42aecef22445ae02eaeef336d87a205e3f40715f42ced3c3dfe6a3f6e71220f"  # pragma: allowlist secret
)


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def record_digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


@cache
def load_fractional_engine():
    source = Path(funded.__file__)
    if sha256(source) != FUNDED_SHA256:
        raise ValueError("R2 requires the pinned whole-share replay source")

    with TemporaryDirectory(prefix="signalforge-fractional-") as temporary:
        directory = Path(temporary)
        patched = directory / "funded.py"
        patched.write_bytes(source.read_bytes())
        subprocess.run(  # noqa: S603 - fixed local overlay applied in an empty directory
            ["git", "apply", "--whitespace=error", str(OVERLAY)],  # noqa: S607
            cwd=directory,
            env={key: value for key, value in os.environ.items() if not key.startswith("GIT_")},
            check=True,
            capture_output=True,
        )
        spec = importlib.util.spec_from_file_location("_signalforge_r2_funded", patched)
        if spec is None or spec.loader is None:
            raise ValueError("Cannot load the fractional replay overlay")
        engine = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = engine
        try:
            spec.loader.exec_module(engine)
        except Exception:
            del sys.modules[spec.name]
            raise
        return engine.run_funded_replay, sha256(patched)


def audit_entries(book):
    accepted = {
        (decision["day"], decision["symbol"]): decision
        for decision in book["decisions"]
        if decision["status"] == "accepted"
    }
    buys = [fill for fill in book["fills"] if fill["side"] == "buy"]
    if len(accepted) != len(buys):
        raise ValueError("Fractional entry count does not reconcile to decisions")
    max_fraction = Decimal(0)
    for fill in buys:
        decision = accepted.pop((fill["day"], fill["symbol"]))
        quantity = Decimal(fill["shares"])
        debit = settle(Decimal(fill["price"]), quantity, buy=True)
        equity = Decimal(decision["pre_entry_equity_usd"])
        if (
            quantity < SHARE_STEP
            or quantity % SHARE_STEP
            or quantity != Decimal(decision["shares"])
            or debit != Decimal(decision["entry_notional_usd"])
            or equity <= 0
            or debit > equity * Decimal("0.05")
            or fill["signal_day"] >= fill["day"]
        ):
            raise ValueError("Fractional entry violated sizing, settlement, or timing policy")
        max_fraction = max(max_fraction, debit / equity)
    if any(Decimal(mark["cash_usd"]) < 0 for mark in book["marks"]):
        raise ValueError("Fractional book has negative cash")
    return {"verified_entries": len(buys), "max_entry_equity_fraction": str(max_fraction)}


def case_path(directory, job):
    return directory / ("__".join(job) + ".json")


def compare_job(job, whole_path):
    whole = r1.load_record(whole_path, job)
    if r1.run_case(job) != whole:
        raise ValueError(f"Pinned whole-share book does not reproduce for {job}")
    engine, _ = load_fractional_engine()
    fractional = r1.run_case(job, replay_engine=engine, study="R2")
    fractional["whole_sha256"] = record_digest(whole)
    fractional["whole_metrics"] = {arm: book["metrics"] for arm, book in whole["arms"].items()}
    fractional["entry_audits"] = {
        arm: audit_entries(book) for arm, book in fractional["arms"].items()
    }
    return fractional


def save_case(path, job, result):
    # Share quantities retain their exact decimal strings in the audit file.
    payload = json.loads(json.dumps(result, default=str, allow_nan=False))
    write_once(path, {"job": job, "sha256": record_digest(payload), "data": payload})


def metrics_only(result):
    return result | {
        "arms": {arm: {"metrics": book["metrics"]} for arm, book in result["arms"].items()}
    }


def replay_identity():
    dataset = r1._CTX["dataset"]
    _, patched_digest = load_fractional_engine()
    sources = [
        Path(__file__),
        Path(fractional_lots.__file__),
        Path(refinement_rules.__file__),
        Path(r1.__file__),
        OVERLAY,
        PROTOCOL,
        ROOT / "scripts/action_replay_report.py",
    ]
    return {
        "manifest_hash": dataset.manifest_hash,
        "archived_source_digest": code_digest(),
        "fractional_source_sha256": patched_digest,
        "source_hashes": {str(path.relative_to(ROOT)): sha256(path) for path in sources},
        "metadata": r1._CTX["metadata"],
        "ticker_changes": [asdict(change) for change in dataset.ticker_changes],
    }


def initialize_worker(snapshot, database, listing, identity):
    r1.initialize(snapshot, database, listing)
    if replay_identity() != identity:
        raise ValueError("R2 worker source or inputs differ from the study design")


def run(args):
    whole_directory, output = args.whole.resolve(), args.output.resolve()
    if output.is_relative_to(whole_directory) or output.is_relative_to(args.snapshot.resolve()):
        raise ValueError("Use a separate R2 output directory")
    if output.exists() and not args.resume:
        raise ValueError("Output exists. Resume the exact R2 study explicitly")
    initargs = (args.snapshot, args.database, args.listing_evidence)
    r1.initialize(*initargs)
    keys = sorted(r1._CTX["strategies"])
    if r1._CTX["dataset"].manifest_hash != r1.EXPECTED_MANIFEST or set(keys) != r1.EXPECTED_KEYS:
        raise ValueError("R2 requires the R1 snapshot and exact ten-strategy registry")
    whole_complete = json.loads((whole_directory / "completed.json").read_text())
    if (whole_complete["jobs"], whole_complete["cases"]) != (231, 441):
        raise ValueError("Complete R1 results are required")
    identity = replay_identity()
    design = {
        **identity,
        "protocol": "R2-fractional-v1",
        "whole_design_sha256": sha256(whole_directory / "design.json"),
        "whole_summary_sha256": sha256(whole_directory / "summary.json"),
        "share_step": str(SHARE_STEP),
        "promotion_eligible": False,
    }
    output.mkdir(parents=True, exist_ok=args.resume)
    write_once(output / "design.json", design)

    records = {}
    stages = (("development", "2021", "2022", "2023"), ("2024", "2025", "2026"))
    with ProcessPoolExecutor(
        max_workers=args.workers,
        mp_context=multiprocessing.get_context("spawn"),
        initializer=initialize_worker,
        initargs=(*initargs, identity),
    ) as pool:
        for stage, periods in enumerate(stages):
            futures = {}
            for job in (
                (key, year, cost)
                for key in [*keys, "simple_spy"]
                for year in periods
                for cost in r1.CASES
            ):
                path, whole_path = case_path(output, job), case_path(whole_directory, job)
                if path.exists():
                    result = r1.load_record(path, job)
                    if result["whole_sha256"] != record_digest(r1.load_record(whole_path, job)):
                        raise ValueError(f"Whole-share source changed for {job}")
                    records[job] = metrics_only(result)
                else:
                    futures[pool.submit(compare_job, job, whole_path)] = job
            for future in as_completed(futures):
                job = futures.pop(future)
                result = future.result()
                save_case(case_path(output, job), job, result)
                records[job] = metrics_only(result)
                print(json.dumps({"complete": job, "verified_jobs": len(records)}), flush=True)
            if stage == 0:
                write_once(output / "validation-disposition.json", r1.verdicts(records, keys))
                print(json.dumps({"validation_recorded_before_followup": True}), flush=True)
    summary = [records[job] for job in sorted(records)]
    write_once(
        output / "summary.json",
        {"records": summary, "disclaimer": "Research signal only — no order was placed."},
    )
    write_once(
        output / "completed.json",
        {"jobs": len(summary), "books_per_share_model": sum(len(r["arms"]) for r in summary)},
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("whole", type=Path, help="Read-only R1 result directory")
    parser.add_argument("output", type=Path)
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--listing-evidence", type=Path)
    parser.add_argument("--workers", type=int, default=2, choices=range(1, 5))
    parser.add_argument("--resume", action="store_true")
    run(parser.parse_args())
