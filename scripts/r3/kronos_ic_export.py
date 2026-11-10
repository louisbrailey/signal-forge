"""R3 Kronos cross-sectional IC study -- step 1: export bars and resolve the universe.

Pre-registration: docs/research/kronos/PREREGISTRATION_2026-11-10_kronos_cross_sectional_ic.md

Runs in the Signal Forge venv against a READ-ONLY scratch copy of the operating database.
Reads only ``massive`` daily bars dated on or before 2025-09-05 (the last development
session). Writes one compact ``bars.npz`` plus the universe lists the inference and
analysis scripts consume. Nothing here touches Kronos, the network or the operating DB.

Universe (pre-registered): members of
``docs/research/diagnostics/universe500_selection_presealed.json`` (485 common stocks +
15 ETFs) with a persisted ``massive`` adjusted daily bar on every XNYS session from
2023-12-01 to 2025-09-05. The contrast window additionally requires every session from
2022-06-01. The tier-3 fallback list is the subset that is also a complete member of
data snapshot 11 (every XNYS session 2016-10-17..2025-09-05, the project's standing
definition of a complete snapshot member).

``amount`` column: production (src/signalforge/kronos/worker.py) hands upstream only
open/high/low/close/volume, and upstream (model/kronos.py, KronosPredictor.predict) then
fills ``amount = volume * mean(open, high, low, close)`` row by row. The export stores
exactly that expression, evaluated with pandas the way upstream evaluates it.

Research signal only -- no order was placed.
"""

# Report prose, table headers and help strings are kept on one line.
# ruff: noqa: E501

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
from datetime import UTC, date, datetime
from pathlib import Path

import numpy as np
import pandas as pd

LAST_DEV_SESSION = date(2025, 9, 5)
EXPORT_START = date(2021, 6, 1)  # room for the 252-session look-back of the simple ranks
TEST_COVER_START = date(2023, 12, 1)
CONTRAST_COVER_START = date(2022, 6, 1)
SNAPSHOT_ID = 11
SNAPSHOT_COMPLETE_START = date(2016, 10, 17)
PRICE_COLS = ["open", "high", "low", "close"]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def bars_content_sha256(path: Path) -> str:
    """SHA-256 over the arrays in bars.npz. A re-export of unchanged data gives the same value;
    the zip container itself does not, because it stores timestamps."""
    z = np.load(path, allow_pickle=False)
    h = hashlib.sha256()
    for key in sorted(z.files):
        a = np.ascontiguousarray(z[key])
        h.update(f"{key}|{a.dtype}|{a.shape}|".encode())
        h.update(a.tobytes())
    return h.hexdigest()


def atomic_write_json(path: Path, payload: object) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n")
    tmp.replace(path)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument(
        "--worktree", required=True, help="research worktree root (for the frozen universe file)"
    )
    ap.add_argument("--out", required=True, help="output directory for bars.npz and universe lists")
    args = ap.parse_args()

    db_url = os.environ.get("DATABASE_URL", "")
    if "mode=ro" not in db_url:
        raise SystemExit("Refusing to run: DATABASE_URL must be a read-only (mode=ro) scratch copy")
    if "/Projects/signal-forge/data/" in db_url:
        raise SystemExit("Refusing to run against the operating database")

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    universe_path = (
        Path(args.worktree) / "docs/research/diagnostics/universe500_selection_presealed.json"
    )
    frozen = json.loads(universe_path.read_text())
    etfs = list(frozen["etfs"])
    stocks = list(frozen["common_stocks_ranked"])
    if len(etfs) != 15 or len(stocks) != 485 or len(set(etfs) | set(stocks)) != 500:
        raise SystemExit(
            f"Identity check failed: frozen list is {len(stocks)} stocks + {len(etfs)} ETFs"
        )
    members = stocks + etfs  # frozen order: ranked stocks, then ETFs
    is_etf = {s: (s in set(etfs)) for s in members}

    from sqlalchemy import text

    from signalforge.data.calendar import sessions as xnys_sessions
    from signalforge.data.series import PriceSeries
    from signalforge.db.models import DataSnapshot
    from signalforge.db.session import session_scope

    sess = list(xnys_sessions(EXPORT_START, LAST_DEV_SESSION))
    if sess[-1] != LAST_DEV_SESSION or max(sess) > LAST_DEV_SESSION:
        raise SystemExit("Identity check failed: XNYS calendar does not end on 2025-09-05")
    date_index = {d: i for i, d in enumerate(sess)}
    n_dates = len(sess)
    i_test = date_index[TEST_COVER_START]
    i_contrast = date_index[CONTRAST_COVER_START]

    fields = {
        k: np.full((n_dates, len(members)), np.nan, dtype=np.float64)
        for k in ("open", "high", "low", "close", "volume", "amount")
    }
    non_calendar: dict[str, int] = {}
    unsuitable: dict[str, int] = {}
    first_bar: dict[str, str | None] = {}
    with session_scope() as s:
        snap = s.get(DataSnapshot, SNAPSHOT_ID)
        snap_symbols = list(snap.symbols_json)
        # Flags are constant for massive rows in the export window; assert it rather than assume it.
        flag_rows = s.execute(
            text(
                "SELECT COUNT(*), SUM(is_adjusted = 0), SUM(is_simulated <> 0), "
                "SUM(adj_close IS NULL OR adj_close <> close), "
                "SUM(quality_flags IS NOT NULL AND CAST(quality_flags AS TEXT) NOT IN ('[]','{}','null','')) "
                "FROM ohlcv_daily WHERE source = 'massive' AND session_date BETWEEN :a AND :b"
            ),
            {"a": EXPORT_START.isoformat(), "b": LAST_DEV_SESSION.isoformat()},
        ).one()
        flags = {
            "massive_rows_in_export_window": int(flag_rows[0]),
            "not_adjusted": int(flag_rows[1] or 0),
            "simulated": int(flag_rows[2] or 0),
            "adj_close_missing_or_differs_from_close": int(flag_rows[3] or 0),
            "with_quality_flags": int(flag_rows[4] or 0),
        }
        if flags["not_adjusted"] or flags["simulated"]:
            raise SystemExit(
                f"Identity check failed: unadjusted or simulated massive rows present: {flags}"
            )
        # Snapshot-11 completeness (bar counts only, dates <= 2025-09-05).
        n_full = len(xnys_sessions(SNAPSHOT_COMPLETE_START, LAST_DEV_SESSION))
        counts = dict(
            s.execute(
                text(
                    "SELECT i.symbol, COUNT(*) FROM ohlcv_daily b JOIN instrument i ON i.id = b.instrument_id "
                    "WHERE b.source = 'massive' AND b.session_date BETWEEN :a AND :b GROUP BY i.symbol"
                ),
                {"a": SNAPSHOT_COMPLETE_START.isoformat(), "b": LAST_DEV_SESSION.isoformat()},
            ).all()
        )
        snap_complete = [x for x in snap_symbols if counts.get(x, 0) == n_full]
        for j, sym in enumerate(members):
            ps = PriceSeries.load(s, sym, EXPORT_START, LAST_DEV_SESSION, source="massive")
            if len(ps) == 0:
                first_bar[sym] = None
                continue
            if max(ps.dates) > LAST_DEV_SESSION:
                raise SystemExit("Hard-rule violation: a bar after 2025-09-05 was loaded")
            if len(set(ps.dates)) != len(ps.dates):
                raise SystemExit(f"Identity check failed: duplicate sessions for {sym}")
            first_bar[sym] = ps.dates[0].isoformat()
            frame = pd.DataFrame(
                {
                    "open": ps.open,
                    "high": ps.high,
                    "low": ps.low,
                    "close": ps.close,
                    "volume": ps.volume,
                }
            )
            # Upstream's exact fill for a missing amount column (model/kronos.py, predict()).
            frame["amount"] = frame["volume"] * frame[PRICE_COLS].mean(axis=1)
            idx = np.array([date_index.get(d, -1) for d in ps.dates])
            on_cal = idx >= 0
            if not on_cal.all():
                non_calendar[sym] = int((~on_cal).sum())
            vals = {col: frame[col].to_numpy(dtype=np.float64) for col in fields}
            o, h, lo, c, v = (vals[col] for col in ("open", "high", "low", "close", "volume"))
            # Production's suitability test (src/signalforge/kronos/service.py).
            finite = np.ones(len(ps), dtype=bool)
            for x in (o, h, lo, c, v):
                finite &= np.isfinite(x) & (np.abs(x) <= 1e15)
            ok = (
                finite
                & (np.minimum.reduce([o, h, lo, c]) > 0)
                & (v >= 0)
                & (lo <= np.minimum(o, c))
                & (np.maximum(o, c) <= h)
            )
            bad = int((~ok & on_cal).sum())
            for col in fields:
                fields[col][idx[on_cal], j] = vals[col][on_cal]
            if bad:
                unsuitable[sym] = bad
                if not math.isfinite(float(np.sum(c))):
                    raise SystemExit(f"Identity check failed: non-finite close for {sym}")

    have = ~np.isnan(fields["close"])
    in_test = have[i_test:].all(axis=0)
    in_contrast = have[i_contrast:].all(axis=0)
    snap_complete_set = set(snap_complete)
    in_snap11 = np.array([m in snap_complete_set for m in members])

    def exclusion(j: int, start_i: int) -> dict[str, object]:
        missing = int((~have[start_i:, j]).sum())
        return {
            "symbol": members[j],
            "first_bar": first_bar.get(members[j]),
            "missing_sessions": missing,
        }

    test_syms = [m for m, ok in zip(members, in_test, strict=True) if ok]
    contrast_syms = [m for m, ok in zip(members, in_contrast, strict=True) if ok]
    tier3_test = [m for m, ok, sn in zip(members, in_test, in_snap11, strict=True) if ok and sn]
    tier3_contrast = [
        m for m, ok, sn in zip(members, in_contrast, in_snap11, strict=True) if ok and sn
    ]
    # Unsuitable bars (by production's own test) inside an included symbol's required window.
    unsuitable_in_universe = {s_: n for s_, n in unsuitable.items() if s_ in set(test_syms)}

    dates_arr = np.array([d.isoformat() for d in sess])
    if max(dates_arr.tolist()) > LAST_DEV_SESSION.isoformat():
        raise SystemExit("Hard-rule violation: export contains a date after 2025-09-05")
    bars_path = out / "bars.npz"
    tmp = out / "bars.tmp.npz"
    np.savez_compressed(
        tmp,
        dates=dates_arr,
        symbols=np.array(members),
        is_etf=np.array([is_etf[m] for m in members]),
        in_test=in_test,
        in_contrast=in_contrast,
        in_snap11=in_snap11,
        **fields,
    )
    tmp.replace(bars_path)

    def write_universe(name: str, symbols: list[str], cover_start: date, note: str) -> None:
        atomic_write_json(
            out / name,
            {
                "symbols": symbols,
                "n": len(symbols),
                "n_stocks": sum(not is_etf[x] for x in symbols),
                "n_etfs": sum(is_etf[x] for x in symbols),
                "coverage_required_from": cover_start.isoformat(),
                "coverage_required_to": LAST_DEV_SESSION.isoformat(),
                "note": note,
                "frozen_list_sha256": sha256_file(universe_path),
            },
        )

    write_universe(
        "universe_test.json", test_syms, TEST_COVER_START, "tier 1/2 universe, test window"
    )
    write_universe(
        "universe_contrast.json",
        contrast_syms,
        CONTRAST_COVER_START,
        "tier 1/2 universe, contrast window",
    )
    write_universe(
        "universe_snapshot11_test.json",
        tier3_test,
        TEST_COVER_START,
        "tier 3 fallback and exploratory snapshot-11 subset, test window",
    )
    write_universe(
        "universe_snapshot11_contrast.json",
        tier3_contrast,
        CONTRAST_COVER_START,
        "tier 3 fallback, contrast window",
    )

    manifest = {
        "created_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "database_url": db_url,
        "source": "massive",
        "loader": "PriceSeries.load(session, symbol, 2021-06-01, 2025-09-05, source='massive')",
        "export_start": EXPORT_START.isoformat(),
        "last_session": dates_arr[-1].item(),
        "n_sessions": n_dates,
        "n_sessions_test_cover": int(n_dates - i_test),
        "n_sessions_contrast_cover": int(n_dates - i_contrast),
        "frozen_list": str(universe_path),
        "frozen_list_sha256": sha256_file(universe_path),
        "frozen_members": {"stocks": len(stocks), "etfs": len(etfs)},
        "massive_row_flags": flags,
        "universe_test": {
            "n": len(test_syms),
            "n_stocks": sum(not is_etf[x] for x in test_syms),
            "n_etfs": sum(is_etf[x] for x in test_syms),
            "excluded": [exclusion(j, i_test) for j in range(len(members)) if not in_test[j]],
        },
        "universe_contrast": {
            "n": len(contrast_syms),
            "n_stocks": sum(not is_etf[x] for x in contrast_syms),
            "n_etfs": sum(is_etf[x] for x in contrast_syms),
            "excluded": [
                exclusion(j, i_contrast) for j in range(len(members)) if not in_contrast[j]
            ],
        },
        "snapshot11": {
            "members": len(snap_symbols),
            "complete_members": len(snap_complete),
            "complete_definition": f"every XNYS session {SNAPSHOT_COMPLETE_START}..{LAST_DEV_SESSION} ({n_full} sessions) in massive bars",
            "incomplete_members": sorted(set(snap_symbols) - snap_complete_set),
            "complete_members_outside_frozen_list": sorted(snap_complete_set - set(members)),
            "tier3_test_n": len(tier3_test),
            "tier3_contrast_n": len(tier3_contrast),
            "complete_member_list": snap_complete,
        },
        "bars_not_on_xnys_calendar": non_calendar,
        "bars_unsuitable_by_production_test": unsuitable,
        "bars_unsuitable_in_test_universe": unsuitable_in_universe,
        "amount": "volume * mean(open, high, low, close), the fill upstream applies when amount is absent",
        "bars_file": str(bars_path),
        "bars_file_sha256": sha256_file(bars_path),
        "bars_content_sha256": bars_content_sha256(bars_path),
    }
    atomic_write_json(out / "export_manifest.json", manifest)
    brief = {k: manifest[k] for k in ("n_sessions", "last_session", "massive_row_flags")}
    brief["universe_test"] = dict(manifest["universe_test"])
    brief["universe_contrast_n"] = manifest["universe_contrast"]["n"]
    brief["universe_contrast_excluded"] = [
        e["symbol"] for e in manifest["universe_contrast"]["excluded"]
    ]
    brief["snapshot11"] = {
        k: v for k, v in manifest["snapshot11"].items() if k != "complete_member_list"
    }
    brief["non_calendar"] = non_calendar
    brief["unsuitable"] = unsuitable
    brief["bars_content_sha256"] = manifest["bars_content_sha256"]
    print(json.dumps(brief, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
