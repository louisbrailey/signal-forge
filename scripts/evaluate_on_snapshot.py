"""Run the full 10-gate promotion evaluation for ONE default strategy on ONE keyed
DataSnapshot (the CLI's ``--dataset`` only knows three fixed names).

This WRITES to the database it is pointed at (StrategyPromotionEvaluation, a
StrategySealedTest for a never-sealed (version, snapshot) pair, and — on a pass —
PAPER_APPROVED status). Therefore:

* it refuses to run without ``--confirm``;
* it prints the sealed-look ledger line the hardened pipeline emits, so the look
  spent is disclosed;
* run it against the LIVE database only with the worker stopped, and against a
  scratch copy (``DATABASE_URL=...``) for rehearsals.

Window and proxy default to exactly those of the snapshot-3 approvals
(2016-09-10 .. 2026-09-08, SPY) so results are comparable.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date

from sqlalchemy import select

from signalforge.db.models import DataSnapshot
from signalforge.db.session import session_scope
from signalforge.research.promotion import evaluate_promotion
from signalforge.research.strategies import default_strategies
from signalforge.settings_store import effective_research_config


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--strategy", required=True, help="e.g. trend_continuation.medium_swing")
    ap.add_argument("--snapshot-key", required=True)
    ap.add_argument("--source", default="massive")
    ap.add_argument("--start", default="2016-09-10")
    ap.add_argument("--end", default="2026-09-08")
    ap.add_argument("--confirm", action="store_true", help="actually write the evaluation")
    args = ap.parse_args()

    strat = next(
        (s for s in default_strategies() if s.spec().name == args.strategy), None
    )
    if strat is None:
        print(f"unknown strategy {args.strategy!r}; known: {[s.spec().name for s in default_strategies()]}")
        return 2
    if not args.confirm:
        print("dry run — pass --confirm to write the evaluation (spends a sealed look for a "
              "never-sealed (version, snapshot) pair).")
        return 0

    with session_scope(write=True) as s:
        snap = s.scalar(select(DataSnapshot).where(DataSnapshot.key == args.snapshot_key))
        if snap is None:
            print(f"no DataSnapshot with key {args.snapshot_key!r}")
            return 2
        cfg = effective_research_config(s)
        res = evaluate_promotion(
            s,
            strat,
            symbols=list(snap.symbols_json),
            start=date.fromisoformat(args.start),
            end=date.fromisoformat(args.end),
            source=args.source,
            config=cfg,
            dataset_snapshot=snap,
        )
        print(f"{args.strategy} on {snap.key!r} (id {snap.id}, {len(snap.symbols_json)} symbols)")
        print(f"  passed={res.passed} verdict={getattr(res, 'verdict', '')!r}")
        for g in getattr(res, "gates", []) or []:
            name = getattr(g, "name", None) or (g.get("name") if isinstance(g, dict) else str(g))
            ok = getattr(g, "passed", None) if not isinstance(g, dict) else g.get("passed")
            detail = getattr(g, "detail", "") if not isinstance(g, dict) else g.get("detail", "")
            print(f"  [{'PASS' if ok else 'FAIL'}] {name}: {str(detail)[:220]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
