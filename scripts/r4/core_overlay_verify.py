"""R4-O: independent re-computation of the overlay accounts (verification only).

This script shares no code with ``core_overlay.py`` or the R3-C module. It reads

* SPY bars and dividend rows from the scratch database with plain SQL, bounded to the
  development window (nothing after 2025-09-05 is selected);
* the daily marks the study saved (``marks_base.npz``: book equity E and cash C);
* R3-C's ``runs.csv`` and the study's own ``replays.csv``, ``spy_legs.csv`` and
  ``summary.json``, to compare against.

Checks
  1. SPY's overnight and intraday legs rebuilt with pandas equal ``spy_legs.csv``.
  2. Every saved mark path ends on the final equity of its R3-C row.
  3. Every overlay account rebuilt with a vectorised units-of-index formula (no
     recursion) reproduces the study's final value, net return, CAGR, max drawdown,
     Sharpe, increments, sleeve share and shortfall counts.
  4. The three-part split of the increment equals three direct re-runs of the account
     (pay-ins credited at the close with a free sleeve; flows at the open with a free
     sleeve; flows at the open with the cost).
  5. Cell medians, win counts, the five conditions and the verdicts recomputed from
     ``replays.csv`` equal ``summary.json``.

It is not a study arm and carries no verdict. Research signal only - no order was placed.
"""

from __future__ import annotations

import json
import math
import os
import sqlite3
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

K0 = 30000.0
COST = 5.5e-4
PERIODS = {
    "IS": (date(2016, 10, 17), date(2022, 2, 10)),
    "OOS": (date(2022, 2, 11), date(2025, 9, 5)),
}
WINDOW = ("2016-10-17", "2025-09-05")
SCRATCH = Path(
    "/private/tmp/claude-501/-Users-louisbrailey-Projects-signal-forge/"
    "ec635db8-8e7c-46dd-bc95-83c88a678e74/scratchpad"
)
FORBIDDEN = (
    "/Users/louisbrailey/Projects/signal-forge/data",
    "/Users/louisbrailey/Projects/signal-forge-releases",
)


def paths() -> tuple[Path, Path, Path]:
    data_dir = os.environ.get("SIGNALFORGE_DATA_DIR")
    db = (Path(data_dir) if data_dir else SCRATCH / "r3/db") / "signalforge.sqlite"
    out = db.parent.parent / "out" / "r4-overlay"
    r3c = db.parent.parent / "out" / "capacity"
    for p in (db, out, r3c):
        if any(str(p.resolve()).startswith(f) for f in FORBIDDEN):
            raise SystemExit(f"refusing to touch operating path {p}")
    return db, out, r3c


def legs_from_database(db: Path) -> pd.DataFrame:
    with sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True) as c:
        c.execute("PRAGMA query_only=ON")
        bars = pd.read_sql_query(
            """SELECT b.session_date AS session, b.open, b.close
            FROM ohlcv_daily b JOIN instrument i ON i.id=b.instrument_id
            WHERE i.symbol='SPY' AND b.source='massive' AND b.session_date BETWEEN ? AND ?
            ORDER BY b.session_date""",
            c,
            params=WINDOW,
        )
        divs = pd.read_sql_query(
            """SELECT ex_dividend_date AS session, cash_amount FROM dividend_event
            WHERE symbol='SPY' AND ex_dividend_date BETWEEN ? AND ?""",
            c,
            params=WINDOW,
        )
        assert c.execute("SELECT count(*) FROM split_event WHERE symbol='SPY'").fetchone()[0] == 0
    assert bars["session"].is_unique and divs["session"].is_unique
    assert bars["session"].max() == WINDOW[1]
    df = bars.merge(divs, on="session", how="left").fillna({"cash_amount": 0.0})
    df["day"] = pd.to_datetime(df["session"]).dt.date
    df["period"] = np.where(df["day"] <= PERIODS["IS"][1], "IS", "OOS")
    first = df.groupby("period")["session"].transform("min") == df["session"]
    df["dividend"] = np.where(first, 0.0, df["cash_amount"])
    df["r_on"] = np.where(first, 0.0, (df["open"] + df["dividend"]) / df["close"].shift(1) - 1.0)
    df["r_id"] = df["close"] / df["open"] - 1.0
    return df


def account(E: np.ndarray, C: np.ndarray, r_on: np.ndarray, r_id: np.ndarray, c: float) -> dict:
    """Units of a total-return index, vectorised: every flow buys or sells units at the
    open-of-session index level; the sleeve is units times the close level."""
    level_close = np.cumprod((1.0 + r_on) * (1.0 + r_id))
    level_open = level_close / (1.0 + r_id)
    flows = np.diff(np.concatenate(([K0], C)))
    trades = flows - c * np.abs(flows)
    trades[0] += K0 - c * K0  # the opening purchase with the starting cash
    units = np.cumsum(trades / level_open)
    sleeve = units * level_close
    return {"K": sleeve, "V": (E - C) + sleeve, "F": flows}


def account_pay_ins_at_close(
    E: np.ndarray, C: np.ndarray, r_on: np.ndarray, r_id: np.ndarray, c_open: float
) -> np.ndarray:
    """A plain loop: withdrawals leave at the open, pay-ins arrive at the close, no cost on
    flows (the opening purchase keeps its cost, as in the reference). Returns V."""
    k, c_prev = K0, K0
    out = np.empty(len(E))
    for t in range(len(E)):
        f = C[t] - c_prev
        k = k * (1.0 + r_on[t])
        if t == 0:
            k -= c_open * K0
        k = (k + min(f, 0.0)) * (1.0 + r_id[t]) + max(f, 0.0)
        out[t] = (E[t] - C[t]) + k
        c_prev = C[t]
    return out


def metrics(values: np.ndarray, period: str) -> dict[str, float]:
    start, end = PERIODS[period]
    s = pd.Series(np.concatenate(([K0], values)))
    rets = s.pct_change().dropna()
    years = ((end - start).days + 1) / 365.25
    growth = s.iloc[-1] / K0
    return {
        "net_return_pct": (growth - 1.0) * 100.0,
        "cagr_pct": (growth ** (1.0 / years) - 1.0) * 100.0,
        "max_drawdown_pct": float(((s.cummax() - s) / s.cummax()).max() * 100.0),
        "sharpe": float(rets.mean() / rets.std(ddof=1) * math.sqrt(252)),
    }


def close(a: float, b: float, tol: float) -> bool:
    return abs(a - b) <= tol * max(1.0, abs(a), abs(b))


def main() -> int:
    db, out, r3c = paths()
    failures: list[str] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        print(f"{'PASS' if ok else 'FAIL'}  {name}{('  ' + detail) if detail else ''}", flush=True)
        if not ok:
            failures.append(name)

    # 1. SPY legs
    legs = legs_from_database(db)
    saved = pd.read_csv(out / "spy_legs.csv")
    same_rows = len(saved) == len(legs) and list(saved["session"]) == list(legs["session"])
    worst = (
        max(
            float(np.max(np.abs(saved[col].to_numpy() - legs[theirs].to_numpy())))
            for col, theirs in (
                ("r_on", "r_on"),
                ("r_id", "r_id"),
                ("dividend_ex_date", "dividend"),
                ("open", "open"),
                ("close", "close"),
            )
        )
        if same_rows
        else float("inf")
    )
    check(
        "1. SPY legs rebuilt from the database equal spy_legs.csv",
        same_rows and worst < 1e-12 and list(saved["period"]) == list(legs["period"]),
        f"{len(legs)} sessions, largest difference {worst:.1e}",
    )
    by_period = {p: legs[legs["period"] == p].reset_index(drop=True) for p in PERIODS}
    for p, (start, end) in PERIODS.items():
        assert by_period[p]["day"].iloc[0] == start and by_period[p]["day"].iloc[-1] == end

    marks = np.load(out / "marks_base.npz")
    rows = pd.read_csv(out / "replays.csv")
    rows = rows[rows["cost_case"] == "base"].reset_index(drop=True)
    r3 = pd.read_csv(r3c / "runs.csv", dtype={"final_equity_usd": str})
    r3 = r3[(r3["cost_case"] == "base") & (r3["arm"] == "random") & (r3["trim"] == 0)]
    r3 = r3.set_index(["book", "cap_set", "period", "order"])
    check("replays.csv has 640 base-cost rows", len(rows) == 640 and len(r3) == 640)

    refs = {}
    for p, lg in by_period.items():
        idle = np.full(len(lg), K0)
        path = account(idle, idle, lg["r_on"].to_numpy(), lg["r_id"].to_numpy(), COST)["V"]
        refs[p] = {"path": path, **metrics(path, p)}

    # 2-4. every replay
    ties = worst_final = worst_metric = worst_split = 0.0
    bad_counts = 0
    for row in rows.itertuples(index=False):
        key = f"{row.book}|{row.cap_set}|{row.period}|{row.order}"
        E, C = marks[f"{key}|E"], marks[f"{key}|C"]
        lg = by_period[row.period]
        r_on, r_id = lg["r_on"].to_numpy(), lg["r_id"].to_numpy()
        theirs = r3.loc[(row.book, row.cap_set, row.period, row.order)]
        ties = max(ties, abs(E[-1] - float(theirs["final_equity_usd"])))
        acct = account(E, C, r_on, r_id, COST)
        V, K = acct["V"], acct["K"]
        m, ref = metrics(V, row.period), refs[row.period]
        worst_final = max(worst_final, abs(V[-1] - row.account_final_usd))
        for mine, saved_value in (
            (m["net_return_pct"], row.account_net_return_pct),
            (m["cagr_pct"], row.account_cagr_pct),
            (m["max_drawdown_pct"], row.account_max_drawdown_pct),
            (m["sharpe"], row.account_sharpe),
            (m["net_return_pct"] - ref["net_return_pct"], row.inc_net_return_pts),
            (m["cagr_pct"] - ref["cagr_pct"], row.inc_cagr_pts),
            (m["sharpe"] - ref["sharpe"], row.inc_sharpe),
            (m["max_drawdown_pct"] - ref["max_drawdown_pct"], row.inc_max_drawdown_pts),
            (float(np.mean(K / V) * 100.0), row.mean_sleeve_share_pct),
            (
                float(np.max(-K[K < 0] / V[K < 0]) * 100.0) if (K < 0).any() else 0.0,
                row.max_shortfall_pct_of_account,
            ),
        ):
            worst_metric = max(worst_metric, abs(mine - saved_value))
        bad_counts += int(np.count_nonzero(K < 0)) != row.shortfall_sessions
        # the three parts as differences between three direct accounts
        free_open = account(E, C, r_on, r_id, 0.0)["V"][-1] - COST * K0 * np.prod(
            (1.0 + r_on) * (1.0 + r_id)
        )
        at_close = account_pay_ins_at_close(E, C, r_on, r_id, COST)[-1]
        remainder = (at_close - ref["path"][-1]) / K0 * 100.0
        exit_day = (free_open - at_close) / K0 * 100.0
        cost = (V[-1] - free_open) / K0 * 100.0
        worst_split = max(
            worst_split,
            abs(remainder - row.part_a_pts),
            abs(exit_day - row.part_b_pts),
            abs(cost - row.part_cost_pts),
        )
    check("2. every mark path ends on its R3-C final equity", ties < 0.005, f"largest {ties:.1e}")
    check(
        "3. accounts rebuilt as units of a total-return index equal the study's",
        worst_final < 1e-6 and worst_metric < 1e-8 and bad_counts == 0,
        f"final value within ${worst_final:.1e}, metrics within {worst_metric:.1e}, "
        f"shortfall counts differing: {bad_counts}",
    )
    check(
        "4. the three parts of the increment equal three direct accounts",
        worst_split < 1e-8,
        f"largest difference {worst_split:.1e} points",
    )

    # 5. cells and verdicts
    summary = json.loads((out / "summary.json").read_text())
    cells = {(c["book"], c["cap_set"], c["period"]): c for c in summary["analysis"]["cells"]}
    worst_cell = 0.0
    cond_same = True
    passes: dict[tuple[str, str], dict[str, bool]] = {}
    for (book, cap, period), g in rows.groupby(["book", "cap_set", "period"], sort=False):
        c = cells[(book, cap, period)]
        assert len(g) == 40 and g["order"].is_unique
        spy_dd = refs[period]["max_drawdown_pct"]
        mine = {
            "net": g["inc_net_return_pts"].median(),
            "sharpe": g["inc_sharpe"].median(),
            "wins": int((g["inc_net_return_pts"] > 0).sum()),
            "dd": g["account_max_drawdown_pct"].median(),
            "short": g["max_shortfall_pct_of_account"].max(),
        }
        for a, b in (
            (mine["net"], c["inc_net_return_pts"]["p50"]),
            (mine["sharpe"], c["inc_sharpe"]["p50"]),
            (mine["dd"], c["account_max_drawdown_pct_p50"]),
            (g["account_net_return_pct"].quantile(0.05), c["account_net_return_pct"]["p5"]),
            (g["account_net_return_pct"].median(), c["account_net_return_pct"]["p50"]),
            (g["account_net_return_pct"].quantile(0.95), c["account_net_return_pct"]["p95"]),
            (g["account_sharpe"].median(), c["account_sharpe"]["p50"]),
            (g["standalone_net_return_pct"].median(), c["standalone_net_return_pct"]["p50"]),
            (refs[period]["net_return_pct"], c["spy"]["net_return_pct"]),
            (float(mine["wins"]), float(c["orders_positive_net_increment"])),
            (float(g["shortfall_sessions"].sum()), float(c["shortfall_sessions"])),
        ):
            worst_cell = max(worst_cell, abs(a - b))
        cond = {
            "median_net_increment_positive": mine["net"] > 0,
            "median_sharpe_increment_positive": mine["sharpe"] > 0,
            "at_least_36_orders_positive": mine["wins"] >= 36,
            "median_max_dd_within_2_pts_of_spy": mine["dd"] - spy_dd <= 2.0,
            "implementable_as_stated": mine["short"] <= 1.0,
        }
        cond_same &= cond == c["conditions"] and all(cond.values()) == c["period_pass"]
        passes.setdefault((book, cap), {})[period] = all(cond.values())
    verdicts = {
        (v["book"], v["cap_set"]): v["account_level_candidate"]
        for v in summary["analysis"]["verdicts"]
    }
    mine_verdicts = {k: v["IS"] and v["OOS"] for k, v in passes.items()}
    check(
        "5. cell medians, win counts, conditions and verdicts equal summary.json",
        worst_cell < 1e-8 and cond_same and mine_verdicts == verdicts and len(verdicts) == 8,
        f"largest difference {worst_cell:.1e}; candidates: {sum(mine_verdicts.values())} of 8",
    )
    print(
        "reference (independent): "
        + ", ".join(f"{p} {refs[p]['net_return_pct']:+.2f}%" for p in PERIODS),
        flush=True,
    )

    # Plain facts quoted in the results file (no check, no verdict).
    above = rows["inc_net_return_pts"] > 0
    print(
        f"replays ending above the reference: {int(above.sum())} of {len(rows)} "
        f"(IS {int(above[rows['period'] == 'IS'].sum())}, "
        f"OOS {int(above[rows['period'] == 'OOS'].sum())})",
        flush=True,
    )
    lift = rows["account_net_return_pct"] - rows["standalone_net_return_pct"]
    print(
        f"account minus standalone book, net return: smallest {lift.min():+.2f} points, "
        f"median {lift.median():+.2f}, largest {lift.max():+.2f}; "
        f"accounts above their standalone book: {int((lift > 0).sum())} of {len(rows)}",
        flush=True,
    )
    print("first session with a book flow (earliest .. latest over the 40 orders):", flush=True)
    for (book, cap, period), g in rows.groupby(["book", "cap_set", "period"], sort=False):
        days = by_period[period]["session"].to_numpy()
        firsts = []
        for order in g["order"]:
            cash = marks[f"{book}|{cap}|{period}|{order}|C"]
            moved = np.flatnonzero(np.diff(np.concatenate(([K0], cash))) != 0)
            firsts.append(days[moved[0]] if len(moved) else "never")
        flow = float(g["first_session_flow_usd"].abs().max())
        print(
            f"  {book:34s} {cap:9s} {period:3s} {min(firsts)} .. {max(firsts)}"
            f"   largest first-session flow ${flow:,.2f}",
            flush=True,
        )
    print("ALL CHECKS PASSED" if not failures else f"FAILED: {failures}", flush=True)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
