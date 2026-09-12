"""W1-COMPLETE check + keyed DataSnapshot creation for the expanded research universe.

Pre-registered in docs/research/diagnostics/w1_selection_presealed.md §8.2 / §9.
Read-only by default; ``--create`` writes exactly ONE DataSnapshot row (the keyed
150-symbol universe) and nothing else. Never ingests, never calls a provider.

Rules (W1-COMPLETE): drop a candidate iff
  (a) it has no source='massive' rows at all;
  (b) more than 2.0% of XNYS sessions between its first and last massive bar are absent;
  (c) its first massive bar is later than 2018-09-08.
Any drop => print the replacement (next reserve name, strict rank order) and STOP
without creating the snapshot. The orchestrator ingests the replacement and re-runs.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from sqlalchemy import select

from signalforge.data.calendar import sessions
from signalforge.data.validate import validate_daily
from signalforge.db.models import DataSnapshot, Instrument, OHLCVDaily
from signalforge.db.session import session_scope
from signalforge.research.promotion import get_or_create_dataset_snapshot

SELECTION = Path("docs/research/diagnostics/w1_selection_presealed.json")
KEY = "research_150_massive_10y_presealed_sel"
MAX_MISSING_PCT = 2.0
LATEST_FIRST_BAR = date(2018, 9, 8)
DESCRIPTION = (
    "150-symbol research universe, selection re-derived on a PRE-SEALED liquidity "
    "window under approval A0 (docs/research/diagnostics/w1_selection_presealed.md): "
    "the 15 ETFs of universe_24_ex_meta verbatim plus the top 135 U.S. common stocks by "
    "60-session median dollar volume over 2025-06-11..2025-09-05 (the 60 most recent "
    "massive_grouped sessions on or before 2025-09-07) among the eligible members of "
    "universe_screen_run 3, restricted to list_date <= 2016-10-17. No sealed-window "
    "(>= 2025-09-08) data entered the selection. Selection frozen before any backtest. "
    "Bars are split-adjusted AS OF the fetch date, NOT point-in-time; discovery was "
    "active-only, so the set is survivorship-biased."
)
SOURCE_NOTE = "massive daily; END_OF_DAY; per-symbol history 2016-10-17.."


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--create", action="store_true", help="create the keyed snapshot if complete")
    args = ap.parse_args()

    sel = json.loads(SELECTION.read_text())
    etfs, cs, reserve = sel["etfs"], sel["common_stocks"], sel.get("reserve", [])
    symbols = list(etfs) + list(cs)
    assert len(symbols) == 150 and len(set(symbols)) == 150, len(symbols)
    key = sel.get("snapshot_key", KEY)
    assert key == KEY, key

    drops: list[tuple[str, str]] = []
    with session_scope(write=args.create) as s:
        for sym in symbols:
            inst = s.scalar(select(Instrument).where(Instrument.symbol == sym))
            rows = (
                s.execute(
                    select(OHLCVDaily.session_date)
                    .where(OHLCVDaily.instrument_id == inst.id, OHLCVDaily.source == "massive")
                    .order_by(OHLCVDaily.session_date)
                )
                .scalars()
                .all()
                if inst is not None
                else []
            )
            if not rows:
                drops.append((sym, "(a) no massive rows"))
                continue
            first, last = rows[0], rows[-1]
            expected = sessions(first, min(last, date.today()))
            missing = len(set(expected) - set(rows))
            pct = 100.0 * missing / max(len(expected), 1)
            if pct > MAX_MISSING_PCT:
                drops.append((sym, f"(b) {missing} missing sessions ({pct:.2f}%) {first}..{last}"))
            if first > LATEST_FIRST_BAR:
                drops.append((sym, f"(c) first massive bar {first} > {LATEST_FIRST_BAR}"))

        res = validate_daily(s, symbols, source="massive", persist=False)
        print(f"validate_daily(source=massive, n={len(symbols)}): passed={res.passed}")
        for c in res.checks:
            print(f"  {'OK  ' if c.passed else 'FAIL'} {c.name}: {c.detail[:200]}")

        if drops:
            print("\nW1-COMPLETE: DROPS (snapshot NOT created):")
            used = set(symbols)
            for sym, why in drops:
                repl = next((r for r in reserve if r not in used), None)
                if repl:
                    used.add(repl)
                print(f"  drop {sym}: {why} -> replacement {repl}")
            return 2
        print("\nW1-COMPLETE: all 150 symbols pass (a)/(b)/(c).")

        existing = s.scalar(select(DataSnapshot).where(DataSnapshot.key == key))
        same_set = [
            d.id
            for d in s.scalars(select(DataSnapshot))
            if set(d.symbols_json) == set(symbols) and d.key != key
        ]
        print(
            f"shadowing: existing row with key={key!r}: {existing.id if existing else None}; "
            f"other snapshots with the same symbol set: {same_set}"
        )
        if not args.create:
            print("dry run — pass --create to write the keyed DataSnapshot row.")
            return 0
        if not res.passed:
            print("refusing to create: validate_daily did not pass")
            return 3
        snap = get_or_create_dataset_snapshot(
            s, key=key, symbols=symbols, description=DESCRIPTION, source_note=SOURCE_NOTE
        )
        s.flush()
        print(
            f"created/resolved DataSnapshot id={snap.id} key={snap.key!r} "
            f"n={len(snap.symbols_json)} reusable={snap.reusable_by_new_evaluations}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
