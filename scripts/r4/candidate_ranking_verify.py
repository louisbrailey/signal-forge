"""R4-K verification: an independent recomputation (no new study arm, no new statistic).

Run after ``candidate_ranking.py all`` with the same environment. It imports neither the
study script nor R3-C; it uses pandas and its own code paths:

1. bars read straight from the database (source 'massive', sessions to 2025-09-05); the
   three keys and the isolated outcome of every signal recomputed from them, the first
   exit found by array search instead of a session loop;
2. the pre-registered statistics (top-2 lift, rank IC, terciles) and the descriptive
   ones (alphabetical two, by year) for every book, key and period, from the candidate
   CSVs;
3. the bootstrap p-values of the primary book by explicit resampling of month lists;
4. three random rankings of the random-2 band, recomputed with a per-session sort;
5. the one-position-per-symbol flags and the K1 lift on the kept candidates.

Everything is compared with summary.json and the saved CSVs; any difference is an error.
Base costs (3 bps slippage plus half of a 5 bps spread, no commission) and the 1.5
reward-to-risk floor are written out here rather than read from the library.

Research signal only - no order was placed.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from pathlib import Path

import numpy as np
import pandas as pd

DATA_DIR = Path(os.environ["SIGNALFORGE_DATA_DIR"])
DB = DATA_DIR / "signalforge.sqlite"
OUT = DATA_DIR.parent / "out" / "r4-ranking"
START, END, IS_END = "2016-10-17", "2025-09-05", "2022-02-10"
PENALTY = (3.0 + 5.0 / 2) / 10000
MIN_RR = 1.5
SEED0 = 20261110
N_BOOT = 10000
KEYS = ("K1", "K2", "K3")
PERIODS = ("IS", "OOS")
PRIMARY = "trend_continuation.medium_swing"
CENT = Decimal("0.01")
TOL = 1e-9
FORBIDDEN = ("/Users/louisbrailey/Projects/signal-forge/data", "/Users/louisbrailey/Projects/signal-forge-releases")

errors: list[str] = []


def check(ok: bool, message: str) -> None:
    if not ok:
        errors.append(message)


def near(a: float | None, b: float | None, tol: float = TOL) -> bool:
    if a is None or b is None:
        return a is None and b is None
    if np.isnan(a) or np.isnan(b):
        return bool(np.isnan(a) and np.isnan(b))
    return abs(a - b) <= tol * max(1.0, abs(a), abs(b))


def load_bars(con: sqlite3.Connection, symbol: str) -> pd.DataFrame:
    return pd.read_sql_query(
        "SELECT b.session_date d,b.open,b.high,b.low,b.close,b.volume FROM ohlcv_daily b "
        "JOIN instrument i ON i.id=b.instrument_id WHERE i.symbol=? AND b.source='massive' "
        "AND b.session_date BETWEEN ? AND ? ORDER BY 1",
        con,
        params=(symbol, START, END),
    )


def outcome(o, h, lo, c, e: int, stop: float, target: float, bars_max: int) -> tuple:
    """(status, exit index, exit reason, entry fill, exit fill, per-share result)."""
    last = len(o) - 1
    fill = Decimal(str(float(o[e]) * (1 + PENALTY))).quantize(CENT, rounding=ROUND_CEILING)
    f = float(fill)
    if not (0 < stop < f):
        return ("invalid_or_crossed_stop", None, "", fill, None, None)
    if (target - f) / (f - stop) < MIN_RR:
        return ("reward_risk", None, "", fill, None, None)
    hi = min(e + bars_max, last)
    stop_hits = np.flatnonzero(lo[e : hi + 1] <= stop)
    target_hits = np.flatnonzero(h[e : hi + 1] >= target)
    first_stop = int(stop_hits[0]) if len(stop_hits) else None
    first_target = int(target_hits[0]) if len(target_hits) else None
    if first_stop is not None and (first_target is None or first_stop <= first_target):
        i = e + first_stop
        gap = i > e and float(o[i]) <= stop
        raw, why = (float(o[i]), "gap_stop") if gap else (stop, "stop")
    elif first_target is not None:
        i, raw, why = e + first_target, target, "target"
    else:
        i, raw = hi, float(c[hi])
        why = "time_stop" if hi == e + bars_max else "end_of_data"
    exit_fill = Decimal(str(raw * (1 - PENALTY))).quantize(CENT, rounding=ROUND_FLOOR)
    return ("candidate", i, why, fill, exit_fill, float(exit_fill - fill))


def ordered(d: pd.DataFrame, key: str) -> pd.DataFrame:
    """Rows of qualifying sessions in key order: highest first, ties by symbol, missing last."""
    d = d.assign(_miss=d[key].isna())
    d = d.sort_values(
        ["signal_session", "_miss", key, "symbol"], ascending=[True, True, False, True], kind="mergesort"
    )
    d["pos"] = d.groupby("signal_session").cumcount()
    return d


def qualifying(valid: pd.DataFrame) -> pd.DataFrame:
    n = valid.groupby("signal_session")["symbol"].transform("size")
    return valid[n >= 3].assign(n=n[n >= 3])


def explicit_bootstrap(values: pd.Series, sessions: pd.Series) -> float:
    """One-sided p by concatenating the sessions of the months drawn, one resample at a time."""
    month = sessions.str.slice(0, 7)
    names = sorted(month.unique())
    by_month = [values[month == m].to_numpy() for m in names]
    observed = float(values.mean())
    rng = np.random.default_rng(SEED0)
    draws = rng.integers(0, len(names), size=(N_BOOT, len(names)))
    hits = 0
    for row in draws:
        resampled = float(np.concatenate([by_month[j] for j in row]).mean())
        hits += (resampled - observed) >= observed
    return (1 + hits) / (N_BOOT + 1)


def main() -> int:
    for path in (DB, OUT):
        assert not any(str(path.resolve()).startswith(f) for f in FORBIDDEN), path
    summary = json.loads((OUT / "summary.json").read_text())
    identity = json.loads((OUT / "identity.json").read_text())
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    con.execute("PRAGMA query_only=ON")
    spy = load_bars(con, "SPY")
    calendar = list(spy.d)
    assert calendar[0] == START and calendar[-1] == END and max(calendar) < "2025-09-07"
    row_of = {d: i for i, d in enumerate(calendar)}
    spy_close = spy.close.to_numpy()
    bars_cache: dict[str, pd.DataFrame] = {}

    for book, b in summary["books"].items():
        cand = pd.read_csv(OUT / f"candidates_{book}.csv", float_precision="round_trip", keep_default_na=False, na_values=["", "nan"])
        for col in ("refusal", "exit_session", "exit_reason"):
            cand[col] = cand[col].fillna("")
        check(len(cand) == b["scope"]["signals"], f"{book}: signal count")

        # ---- 1. keys and outcomes from the database
        diffs = {"K1": 0.0, "K2": 0.0, "K3": 0.0, "outcome_r": 0.0}
        for symbol, rows in cand.groupby("symbol"):
            if symbol not in bars_cache:
                bars_cache[symbol] = load_bars(con, symbol)
            df = bars_cache[symbol]
            check(list(df.d) == calendar, f"{book} {symbol}: calendar")
            o, h, lo, c, vol = (df[x].to_numpy() for x in ("open", "high", "low", "close", "volume"))
            for r in rows.itertuples():
                t = row_of[r.signal_session]
                e = t + 1
                check(calendar[e] == r.entry_session, f"{book} {symbol} {r.signal_session}: entry session")
                check((r.period == "IS") == (calendar[e] <= IS_END), f"{book} {symbol} {r.signal_session}: period")
                check(float(c[t]) == r.close_signal, f"{book} {symbol} {r.signal_session}: close")
                k1 = (c[t] / c[t - 63] - 1.0) - (spy_close[t] / spy_close[t - 63] - 1.0) if t >= 63 else float("nan")
                k2 = vol[t] / vol[t - 19 : t].mean()
                k3 = (c[t] - r.stop) / c[t]
                for name, mine, theirs in (("K1", k1, r.K1), ("K2", k2, r.K2), ("K3", k3, r.K3)):
                    check(near(float(mine), float(theirs), 1e-12), f"{book} {symbol} {r.signal_session}: {name}")
                    if not (np.isnan(mine) or np.isnan(theirs)):
                        diffs[name] = max(diffs[name], abs(float(mine) - float(theirs)))
                status, x, why, fill, exit_fill, per_share = outcome(o, h, lo, c, e, r.stop, r.target, int(r.time_stop_bars))
                tag = f"{book} {symbol} {r.signal_session}"
                check(str(fill) == f"{r.entry_fill:.2f}", f"{tag}: entry fill")
                if status != "candidate":
                    check(r.status == "not_a_candidate_outcome" and r.refusal == status, f"{tag}: refusal")
                    continue
                check(r.status == "candidate", f"{tag}: status")
                check(calendar[x] == r.exit_session and why == r.exit_reason, f"{tag}: exit {why} {calendar[x]}")
                check(str(exit_fill) == f"{r.exit_fill:.2f}", f"{tag}: exit fill")
                mine = per_share / (float(c[t]) - r.stop)
                check(near(mine, r.outcome_r, 1e-12), f"{tag}: outcome {mine} vs {r.outcome_r}")
                diffs["outcome_r"] = max(diffs["outcome_r"], abs(mine - r.outcome_r))
        print(f"{book}: {len(cand)} signals recomputed from the database; largest differences {diffs}", flush=True)

        # ---- 5. one position per symbol
        inside = {}
        for _symbol, rows in cand.sort_values(["symbol", "signal_session"]).groupby("symbol"):
            last_exit = ""
            for r in rows.itertuples():
                inside[r.Index] = r.signal_session < last_exit
                if r.status == "candidate" and not inside[r.Index]:
                    last_exit = r.exit_session
        mine_inside = pd.Series(inside).reindex(cand.index)
        check(bool((mine_inside == cand.inside_held_window.astype(bool)).all()), f"{book}: held-window flags")

        valid = cand[cand.status == "candidate"]
        kept = valid[~mine_inside[valid.index]]
        for label, subset, ref in (("all", valid, b["stats"]), ("kept", kept, b["non_overlap"]["stats"])):
            q = qualifying(subset)
            for key in KEYS:
                d = ordered(q, key)
                day_mean = d.groupby("signal_session")["outcome_r"].mean()
                top2 = d[d.pos < 2].groupby("signal_session")["outcome_r"].mean()
                lift = top2 - day_mean
                d = d.assign(
                    krank=d.n - d.pos,
                    orank=d.groupby("signal_session")["outcome_r"].rank(method="average"),
                    bucket=(3 * (2 * d.pos + 1)) // (2 * d.n),
                )
                ic = d.groupby("signal_session").apply(
                    lambda x: np.corrcoef(x.krank, x.orank)[0, 1] if x.orank.nunique() > 1 else np.nan,
                    include_groups=False,
                )
                alpha = q.sort_values(["signal_session", "symbol"])
                alpha2 = alpha[alpha.groupby("signal_session").cumcount() < 2].groupby("signal_session")["outcome_r"].mean()
                period_of = d.groupby("signal_session")["period"].first()
                for period in PERIODS:
                    m = period_of == period
                    s = ref[key][period]
                    tag = f"{book} {label} {key} {period}"
                    check(int(m.sum()) == s["sessions"], f"{tag}: sessions {int(m.sum())} vs {s['sessions']}")
                    if not m.sum():
                        continue
                    check(int(d[d.period == period].shape[0]) == s["candidates"], f"{tag}: candidates")
                    check(near(float(lift[m].mean()), s["top2_lift"]), f"{tag}: lift {lift[m].mean()} vs {s['top2_lift']}")
                    check(near(float(ic[m].mean()), s["rank_ic"]), f"{tag}: IC {ic[m].mean()} vs {s['rank_ic']}")
                    check(
                        near(float((top2 - alpha2)[m].mean()), s["lift_vs_alphabetical_two"]), f"{tag}: alphabetical two"
                    )
                    if label != "all":
                        continue
                    terc = d[d.period == period].groupby("bucket")["outcome_r"].agg(["mean", "size"])
                    for j, name in enumerate(("top", "middle", "bottom")):
                        check(
                            near(float(terc.loc[j, "mean"]), s["terciles"][name]["mean_outcome"])
                            and int(terc.loc[j, "size"]) == s["terciles"][name]["candidates"],
                            f"{tag}: tercile {name}",
                        )
                    years = lift[m].groupby(lift[m].index.str.slice(0, 4)).agg(["mean", "size"])
                    for y, e2 in s["by_year"].items():
                        check(
                            near(float(years.loc[y, "mean"]), e2["top2_lift"]) and int(years.loc[y, "size"]) == e2["sessions"],
                            f"{tag}: year {y}",
                        )
                    check(len(years) == len(s["by_year"]), f"{tag}: years")
                    # ---- 3. bootstrap p by explicit resampling (primary book only: it is slow)
                    if book == PRIMARY:
                        sess = pd.Series(lift[m].index, index=lift[m].index)
                        p_lift = explicit_bootstrap(lift[m], sess)
                        p_ic = explicit_bootstrap(ic[m], sess)
                        check(near(p_lift, s["top2_lift_p"], 1e-12), f"{tag}: lift p {p_lift} vs {s['top2_lift_p']}")
                        check(near(p_ic, s["rank_ic_p"], 1e-12), f"{tag}: IC p {p_ic} vs {s['rank_ic_p']}")
                        print(f"   {tag}: lift {lift[m].mean():+.6f} p {p_lift:.4f} | IC {ic[m].mean():+.6f} p {p_ic:.4f}", flush=True)
        print(f"{book}: statistics recomputed with pandas for all candidates and for the kept subset", flush=True)

        # ---- 4. three random rankings, per-session sort
        snapshot = int(b["snapshot_id"])
        universe = json.loads(con.execute("SELECT symbols_json FROM data_snapshot WHERE id=?", (snapshot,)).fetchone()[0])
        counts = dict(
            con.execute(
                "SELECT i.symbol, COUNT(*) FROM ohlcv_daily b JOIN instrument i ON i.id=b.instrument_id "
                "WHERE b.source='massive' AND b.session_date BETWEEN ? AND ? GROUP BY i.symbol",
                (START, END),
            ).fetchall()
        )
        selected = sorted(s for s in universe if counts.get(s, 0) == len(calendar))
        check(len(selected) == b["symbols"], f"{book}: universe {len(selected)} vs {b['symbols']}")
        col_of = {s: j for j, s in enumerate(selected)}
        band = pd.read_csv(OUT / f"random_band_{book}.csv", float_precision="round_trip")
        q = qualifying(valid)
        groups = [(sess, g) for sess, g in q.groupby("signal_session")]
        for i in (0, 500, 999):
            prio = np.random.default_rng(SEED0 + i).random((len(calendar), len(selected)))
            lifts: dict[str, list[float]] = {"IS": [], "OOS": []}
            for sess, g in groups:
                row = prio[row_of[sess] + 1]
                pick = g.assign(_p=[row[col_of[s]] for s in g.symbol]).sort_values(["_p", "symbol"]).head(2)
                lifts[g.period.iloc[0]].append(float(pick.outcome_r.mean() - g.outcome_r.mean()))
            for col, period in (("top2_lift_IS", "IS"), ("top2_lift_OOS", "OOS")):
                if lifts[period]:
                    check(near(float(np.mean(lifts[period])), float(band.loc[i, col])), f"{book}: random ranking {i} {period}")
        for period in PERIODS:
            col = f"top2_lift_{period}"
            if band[col].notna().any():
                check(near(float(np.percentile(band[col], 95)), b["random2_band"][period]["p95"]), f"{book}: band p95 {period}")
        print(f"{book}: random rankings 0, 500 and 999 and the band's 95th percentile reproduced", flush=True)

    # ---- the decision, from the recomputed pieces already compared above
    dec = summary["decision"]
    p = summary["books"][PRIMARY]["stats"]["K1"]
    band95 = summary["books"][PRIMARY]["random2_band"]["OOS"]["p95"]
    rule = (
        p["IS"]["top2_lift"] > 0
        and p["OOS"]["top2_lift"] > 0
        and p["OOS"]["top2_lift_p"] < 0.05
        and p["IS"]["rank_ic"] > 0
        and p["OOS"]["rank_ic"] > 0
        and p["OOS"]["top2_lift"] > band95
    )
    check(rule == dec["confirmed"], "decision")
    check(identity["passed"] is True, "identity")
    print(f"decision recomputed: {'confirmed' if rule else 'not confirmed'} (summary: {dec['verdict']})", flush=True)
    if errors:
        print(f"VERIFICATION FAILED: {len(errors)} differences", flush=True)
        for e in errors[:40]:
            print("  ", e, flush=True)
        return 1
    print("verification passed: no difference", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
