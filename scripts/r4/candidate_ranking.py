"""R4-K: does relative-strength ranking pick the better same-day candidates?

Pre-registration: docs/research/PREREGISTRATION_r4_candidate_ranking_2026-11-10.md (commit 1b8cc3a)
Results file:     docs/research/RESULTS_r4_candidate_ranking_2026-11-10.md

Read-only research on a private scratch copy of the database, development window only
(bars end 2025-09-05). The R3-C study script (``scripts/r3/capacity_admission.py``) is
imported unmodified: its loader, signal table, ranking keys, order functions and replay
are the ones used here.

Definitions fixed in this file before any outcome was computed (the pre-registration
left them open; each is listed under "Deviations and clarifications" in the results):

* Candidate: every (symbol, signal session) in R3-C's signal table for the book.
* Fill validity: the funded replay's own two checks at the next open (crossed or invalid
  stop; reward-to-risk below the library floor). A refused signal has no outcome.
* Outcome: taken alone at the next open and closed by the funded replay's exit rules
  (gap through the stop at a later open, stop, target, time stop, end of data), fills
  rounded to the cent exactly as the replay rounds them, base costs, divided by the
  planned risk ``close_t - stop_t``. The window end is the replay's end-of-data close.
* IS / OOS: by entry session (on or before 2022-02-10 = IS).
* Key order: R3-C's (highest first; ties and missing keys by symbol, missing last).
* Statistics on signal sessions with at least 3 candidates that have an outcome.
* Tercile of position r (0 = highest key) among n candidates: floor(3 (r + 0.5) / n).
* Random-2 band: ranking i uses R3-C's random-order grid of seed 20261110 + i.
* Bootstrap: calendar months (of the signal session) holding a qualifying session are the
  blocks; each of 10,000 resamples draws that many months with replacement; the null is
  the resampled mean minus the observed mean; one-sided p with the +1 correction.
* Non-overlapping subset (descriptive): signals a one-position-per-symbol account that
  takes every signal it sees would be offered.

Stages (``python candidate_ranking.py <stage>``):

  prepare   per book: load, signal table and keys (R3-C functions, with their no-look-ahead
            assertions and poison test), candidate table with isolated outcomes, identity
            check against the R3-C alphabetical replay. Stops the study if it fails.
  analyze   pre-registered statistics and descriptive facts -> sessions CSVs, summary.json
  report    results markdown from the saved outputs

Research signal only - no order was placed.
"""
# ruff: noqa: E501 - markdown table rows and their f-strings are kept on one line

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import multiprocessing as mp
import os
import pickle
import subprocess
import sys
import time
from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import date
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np

HERE = Path(__file__).resolve()
WORKTREE = HERE.parents[2]
R3_DIR = HERE.parents[1] / "r3"
sys.path.insert(0, str(R3_DIR))

import capacity_admission as ca  # noqa: E402 - R3-C, imported unmodified
import funded_replay_report as frr  # noqa: E402

from signalforge.data.series import PriceSeries  # noqa: E402

# ----------------------------------------------------------------------------- fixed scope
PREREG = "docs/research/PREREGISTRATION_r4_candidate_ranking_2026-11-10.md"
RESULTS = WORKTREE / "docs/research/RESULTS_r4_candidate_ranking_2026-11-10.md"
PRIMARY_BOOK = "trend_continuation.medium_swing"
PRIMARY_KEY = "K1"
KEYS = ca.KEYS  # ("K1", "K2", "K3")
PERIODS = ("IS", "OOS")
SEED0 = 20261110
N_RANDOM = 1000
N_BOOT = 10000
MIN_CANDIDATES = 3
TOP_N = 2
ALPHA = 0.05
BAND_PCT = 95.0
TOL = 1e-9
CENT = Decimal("0.01")
CANDIDATE = "candidate"
NOT_CANDIDATE = "not_a_candidate_outcome"
VALIDITY_REASONS = ("invalid_or_crossed_stop", "reward_risk")
COUNT_BINS = ("0", "1", "2", "3", "4", "5", "6-10", "11-20", "21-40", "41+")
BOOK_LABELS = {
    "trend_continuation.medium_swing": "TC medium (11)",
    "high52_breakout.medium_swing": "high52 (11)",
    "trend_continuation.short_swing": "TC short (3)",
    "relative_strength.medium_swing": "RS medium (3)",
}
MAX_WORKERS = 2

assert SEED0 == ca.SEED0 and ca.BOOKS[0][0] == PRIMARY_BOOK


def default_out() -> Path:
    return ca.default_db().parent.parent / "out" / "r4-ranking"


def penalty_of(cm: Any, spread_bps: float) -> float:
    """Per-side fill penalty, the expression ``run_funded_replay`` uses."""
    return (cm.slippage_bps + (spread_bps / 2 if cm.half_spread_fill_penalty else 0)) / 10000


# ----------------------------------------------------------------------------- isolated outcome
def isolated_outcome(
    o: list[float],
    h: list[float],
    lo: list[float],
    c: list[float],
    entry_i: int,
    stop: float,
    target: float | None,
    time_bars: int,
    last: int,
    penalty: float,
    min_rr: float,
) -> dict[str, Any]:
    """One signal taken alone at the open of ``entry_i`` and closed by the funded replay's
    rules, with no other position, cash limit or cap. ``last`` is the last session of the
    window (end of data). Arithmetic and rounding are the replay's own lines."""
    raw = o[entry_i]
    fill = Decimal(str(raw * (1 + penalty))).quantize(CENT, rounding=ROUND_CEILING)
    fill_f = float(fill)
    out: dict[str, Any] = {"entry_open": raw, "entry_fill": fill}
    if not math.isfinite(stop) or stop <= 0 or stop >= fill_f:
        return {**out, "status": NOT_CANDIDATE, "refusal": "invalid_or_crossed_stop"}
    if target is not None and (
        not math.isfinite(target) or (target - fill_f) / (fill_f - stop) < min_rr
    ):
        return {**out, "status": NOT_CANDIDATE, "refusal": "reward_risk"}
    for i in range(entry_i, last + 1):
        if i > entry_i and o[i] <= stop:  # only a later open can gap through the stop
            raw_exit, why = o[i], "gap_stop"
        elif lo[i] <= stop:
            raw_exit, why = stop, "stop"
        elif target is not None and h[i] >= target:
            raw_exit, why = target, "target"
        elif i - entry_i >= time_bars:
            raw_exit, why = c[i], "time_stop"
        elif i == last:
            raw_exit, why = c[i], "end_of_data"
        else:
            continue
        exit_fill = Decimal(str(raw_exit * (1 - penalty))).quantize(CENT, rounding=ROUND_FLOOR)
        return {
            **out,
            "status": CANDIDATE,
            "refusal": "",
            "exit_index": i,
            "exit_reason": why,
            "exit_raw": raw_exit,
            "exit_fill": exit_fill,
            "per_share": float(exit_fill - fill),
        }
    raise AssertionError("no exit resolved")


def self_test_isolated() -> None:
    """Synthetic bars pin each rule of ``isolated_outcome`` (penalty 0 keeps prices round)."""

    def run(o, h, lo, c, stop, target, bars=3, last=None, pen=0.0):
        return isolated_outcome(
            o, h, lo, c, 1, stop, target, bars, len(o) - 1 if last is None else last, pen, 1.5
        )

    flat = [10.0] * 8
    r = run(flat, [10.5] * 8, [9.8] * 8, flat, 9.0, 12.0)  # nothing hit: time stop at bar 1+3
    assert (r["exit_reason"], r["exit_index"], r["per_share"]) == ("time_stop", 4, 0.0)
    r = run(flat, [10.5] * 8, [9.8] * 8, flat, 9.0, 12.0, last=3)  # window ends first
    assert (r["exit_reason"], r["exit_index"]) == ("end_of_data", 3)
    r = run(flat, [10.5, 10.5, 12.5] + [10.5] * 5, [9.8] * 8, flat, 9.0, 12.0)
    assert (r["exit_reason"], r["exit_index"], r["per_share"]) == ("target", 2, 2.0)
    r = run(flat, [10.5, 10.5, 12.5] + [10.5] * 5, [9.8, 9.8, 8.9] + [9.8] * 5, flat, 9.0, 12.0)
    assert (r["exit_reason"], r["per_share"]) == ("stop", -1.0)  # stop before target
    r = run([10.0, 10.0, 8.5] + [10.0] * 5, [10.5] * 8, [9.8, 9.8, 8.0] + [9.8] * 5, flat, 9.0, 12.0)
    assert (r["exit_reason"], r["exit_index"], r["per_share"]) == ("gap_stop", 2, -1.5)
    r = run(flat, [10.5] * 8, [9.8, 8.9] + [9.8] * 6, flat, 9.0, 12.0)  # stop on the entry session
    assert (r["exit_reason"], r["exit_index"], r["per_share"]) == ("stop", 1, -1.0)
    r = run([10.0, 13.0] + [13.0] * 6, [13.5] * 8, [12.5] * 8, [13.0] * 8, 9.0, 12.0)
    assert r["refusal"] == "reward_risk"  # open above the target
    r = run([10.0, 11.5] + [11.5] * 6, [12.0] * 8, [11.0] * 8, [11.5] * 8, 9.0, 12.0)
    assert r["refusal"] == "reward_risk"  # (12 - 11.5) / (11.5 - 9) < 1.5
    r = run([10.0, 8.9] + [9.0] * 6, [9.5] * 8, [8.5] * 8, [9.0] * 8, 9.0, 12.0)
    assert r["refusal"] == "invalid_or_crossed_stop"
    # cent rounding: buy rounds up, sell rounds down
    r = run(flat, [10.5] * 8, [9.8] * 8, flat, 9.0, 12.0, pen=0.00055)
    assert str(r["entry_fill"]) == "10.01" and str(r["exit_fill"]) == "9.99"
    assert abs(r["per_share"] + 0.02) < 1e-12


# ----------------------------------------------------------------------------- keys: no look-ahead
def _same(a: float, b: float) -> bool:
    return a == b or (math.isnan(a) and math.isnan(b))


def _close_enough(a: float, b: float) -> bool:
    if math.isnan(a) or math.isnan(b):
        return math.isnan(a) and math.isnan(b)
    return abs(a - b) <= 1e-12 * max(1.0, abs(a), abs(b))


def verify_keys(book: ca.Book) -> dict[str, Any]:
    """Every key of every candidate, checked three ways.

    1. R3-C's ``ranking_keys`` on prefixes that end on the signal session (asserted).
    2. R3-C's poison test on every candidate, not a sample: all bars after the signal
       session set to NaN, values identical.
    3. The key formulas written out here on raw arrays, reading indices <= t only."""
    spy = book.data["SPY"]

    def poisoned(b: PriceSeries, t: int) -> PriceSeries:
        arrays = [a.copy() for a in (b.open, b.high, b.low, b.close, b.volume)]
        for a in arrays:
            a[t + 1 :] = np.nan
        return PriceSeries(b.symbol, b.dates, *arrays)

    spy_c = spy.close
    checked = 0
    for t, lst in enumerate(book.day_signals):
        if not lst:
            continue
        spy_visible = spy.head(t)
        spy_poison = poisoned(spy, t)
        assert spy_visible.dates[-1] == book.dates[t] and len(spy_visible) == t + 1
        for symbol, sig in lst:
            bars = book.data[symbol]
            stored = book.keys[(t, symbol)]
            visible = bars.head(t)
            assert visible.dates[-1] == book.dates[t] and len(visible) == t + 1
            prefix = ca.ranking_keys(visible, spy_visible, t, sig.stop_price)
            poison = ca.ranking_keys(poisoned(bars, t), spy_poison, t, sig.stop_price)
            cl, vol = bars.close, bars.volume
            k1 = (
                float(cl[t] / cl[t - 63] - 1.0) - float(spy_c[t] / spy_c[t - 63] - 1.0)
                if t >= 63
                else float("nan")
            )
            k2 = float(vol[t] / vol[t - 19 : t].mean()) if t >= 19 else float("nan")
            k3 = (float(cl[t]) - sig.stop_price) / float(cl[t])
            assert all(_same(a, b) for a, b in zip(prefix, stored, strict=True)), (t, symbol)
            assert all(_same(a, b) for a, b in zip(poison, stored, strict=True)), (t, symbol)
            assert all(
                _close_enough(a, b) for a, b in zip((k1, k2, k3), stored, strict=True)
            ), (t, symbol, (k1, k2, k3), stored)
            checked += 1
    assert checked == len(book.keys)
    return {"keys_checked": checked, "prefix": "passed", "poison": "passed", "formula": "passed"}


# ----------------------------------------------------------------------------- R3-C cache
class _R3Unpickler(pickle.Unpickler):
    """R3-C pickled its ``Book`` while running as ``__main__``."""

    def find_class(self, module: str, name: str) -> Any:
        if module in ("__main__", "__mp_main__") and name == "Book":
            return ca.Book
        return super().find_class(module, name)


def compare_with_r3c_cache(book: ca.Book) -> dict[str, Any]:
    """The signal table rebuilt here against the one R3-C saved and used for its grid."""
    path = ca.default_out() / "cache" / f"{book.strategy}.pkl"
    # Trusted input: written by R3-C's own prepare stage into the private scratch folder.
    with path.open("rb") as fh:
        cached = _R3Unpickler(fh).load()
    keys_same = cached.keys.keys() == book.keys.keys() and all(
        all(_same(a, b) for a, b in zip(cached.keys[k], v, strict=True))
        for k, v in book.keys.items()
    )
    out = {
        "dates_identical": cached.dates == book.dates,
        "symbols_identical": cached.selected == book.selected,
        "signals_identical": cached.day_signals == book.day_signals,
        "keys_identical": keys_same,
        "bars_identical": all(
            np.array_equal(getattr(cached.data[s], f), getattr(book.data[s], f))
            for s in book.data
            for f in ("open", "high", "low", "close", "volume")
        ),
        "dividends_identical": cached.dividends == book.dividends,
    }
    out["passed"] = all(out.values())
    return out


# ----------------------------------------------------------------------------- candidate table
def _ohlc(book: ca.Book) -> dict[str, tuple[list[float], ...]]:
    return {
        s: tuple(a.tolist() for a in (b.open, b.high, b.low, b.close))
        for s, b in ((s, book.data[s]) for s in book.selected)
    }


def build_candidates(book: ca.Book, penalty: float, min_rr: float) -> list[dict[str, Any]]:
    """One row per (signal session, symbol) of the book's signal table."""
    dates = book.dates
    last = len(dates) - 1
    ohlc = _ohlc(book)
    rows: list[dict[str, Any]] = []
    for t, lst in enumerate(book.day_signals):
        for symbol, sig in lst:
            o, h, lo, c = ohlc[symbol]
            close_t = c[t]
            planned = close_t - sig.stop_price
            if not (math.isfinite(planned) and planned > 0):
                raise AssertionError(f"planned risk not positive: {symbol} {dates[t]}")
            entry_i = t + 1
            iso = isolated_outcome(
                o, h, lo, c, entry_i, sig.stop_price, sig.target_price, sig.time_stop_bars,
                last, penalty, min_rr,
            )  # fmt: skip
            k1, k2, k3 = book.keys[(t, symbol)]
            period = "IS" if dates[entry_i] <= ca.IS_END else "OOS"
            row: dict[str, Any] = {
                "book": book.strategy,
                "symbol": symbol,
                "t": t,
                "signal_session": str(dates[t]),
                "entry_session": str(dates[entry_i]),
                "period": period,
                "close_signal": close_t,
                "stop": sig.stop_price,
                "target": sig.target_price,
                "time_stop_bars": sig.time_stop_bars,
                "planned_risk": planned,
                "K1": k1,
                "K2": k2,
                "K3": k3,
                "entry_open": iso["entry_open"],
                "entry_fill": str(iso["entry_fill"]),
                "status": iso["status"],
                "refusal": iso["refusal"],
                "exit_index": None,
                "exit_session": "",
                "exit_reason": "",
                "exit_fill": "",
                "sessions_held": None,
                "per_share": None,
                "outcome_r": None,
                "open_at_window_end": False,
                "exit_after_is_end": False,
            }
            if iso["status"] == CANDIDATE:
                x = iso["exit_index"]
                row.update(
                    exit_index=x,
                    exit_session=str(dates[x]),
                    exit_reason=iso["exit_reason"],
                    exit_fill=str(iso["exit_fill"]),
                    sessions_held=x - entry_i,
                    per_share=iso["per_share"],
                    outcome_r=iso["per_share"] / planned,
                    open_at_window_end=iso["exit_reason"] == "end_of_data",
                    exit_after_is_end=period == "IS" and dates[x] > ca.IS_END,
                )
            rows.append(row)
    assert len(rows) == len(book.keys)
    # One position per symbol: which signals fall inside an earlier candidate's holding
    # window (entered at or before the signal session and not yet exited at its close).
    by_symbol: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_symbol[r["symbol"]].append(r)
    for lst in by_symbol.values():
        assert [r["t"] for r in lst] == sorted(r["t"] for r in lst)
        chain_exit = -1  # exit index of the last candidate a one-position account took
        any_exit = -1  # latest exit index of any earlier candidate
        for r in lst:
            r["inside_any_earlier_window"] = r["t"] < any_exit
            r["inside_held_window"] = r["t"] < chain_exit
            if r["status"] == CANDIDATE:
                any_exit = max(any_exit, r["exit_index"])
                if not r["inside_held_window"]:
                    chain_exit = r["exit_index"]
    return rows


CANDIDATE_FIELDS = [
    "book", "symbol", "signal_session", "entry_session", "period", "close_signal", "stop",
    "target", "time_stop_bars", "planned_risk", "K1", "K2", "K3", "entry_open", "entry_fill",
    "status", "refusal", "exit_session", "exit_reason", "exit_fill", "sessions_held",
    "per_share", "outcome_r", "open_at_window_end", "exit_after_is_end",
    "inside_any_earlier_window", "inside_held_window",
]  # fmt: skip


def write_csv(path: Path, fields: list[str], rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: ("" if r.get(k) is None else r.get(k)) for k in fields})


# ----------------------------------------------------------------------------- identity check
def identity_check(
    book: ca.Book, rows: list[dict[str, Any]], caps: ca.Caps, r3c_cells: list[dict[str, Any]]
) -> dict[str, Any]:
    """Every admitted trade of the R3-C alphabetical, outright-rejection replay on the
    operating caps (both periods, base costs) against the isolated outcome of the same
    symbol and signal session.

    The replay is run twice: R3-C's local loop, and a fresh library ``run_funded_replay``
    that builds its own signals; the two must be identical before trades are compared.
    A trade the IS replay liquidates at its last close (2022-02-10) is compared with the
    isolated outcome computed on the same horizon; every other trade is compared with
    the candidate table itself."""
    cm, spread = frr.COST_CASES[ca.BASE]
    penalty = penalty_of(cm, spread)
    min_rr = ca.make_limits(caps).min_reward_to_risk
    dates = book.dates
    didx = {str(d): i for i, d in enumerate(dates)}
    ohlc = _ohlc(book)
    cand = {(r["t"], r["symbol"]): r for r in rows}
    signals = {(t, s): sig for t, lst in enumerate(book.day_signals) for s, sig in lst}
    cells = []
    for period in PERIODS:
        t0 = time.perf_counter()
        loc, _stats = ca.local_replay(
            book, period, caps, cm, spread, order=("alpha",), trim=False
        )
        ref = ca.library_replay(book, period, caps, cm, spread, table_backed=False)
        library_identical = (
            ref.fills == loc.fills
            and ref.marks == loc.marks
            and ref.decisions == loc.decisions
            and ref.costs == loc.costs
            and ref.corporate_events == loc.corporate_events
        )
        final_equity = loc.marks[-1]["net_liquidation_usd"]
        (recorded,) = [
            c for c in r3c_cells if c["cap_set"] == caps.name and c["period"] == period
        ]
        matches_r3c = (
            len(loc.fills) == recorded["local_fills"]
            and final_equity == recorded["local_final_equity_usd"]
        )
        horizon = (book.n_is if period == "IS" else len(dates)) - 1
        # pair each buy with the sell that closes it
        open_buy: dict[str, dict[str, Any]] = {}
        trades: list[tuple[dict[str, Any], dict[str, Any]]] = []
        for f in loc.fills:
            if f["side"] == "buy":
                assert f["symbol"] not in open_buy
                open_buy[f["symbol"]] = f
            else:
                trades.append((open_buy.pop(f["symbol"]), f))
        assert not open_buy
        max_diff = 0.0
        max_diff_trade = ""
        mismatches: list[str] = []
        period_end = 0
        period_end_differs = 0
        reasons: Counter[str] = Counter()
        for b, s in trades:
            symbol = b["symbol"]
            t = didx[b["signal_day"]]
            row = cand.get((t, symbol))
            tag = f"{symbol} {b['signal_day']}"
            if row is None or row["status"] != CANDIDATE:
                mismatches.append(f"{tag}: admitted trade has no candidate outcome")
                continue
            buy, sell = Decimal(b["price"]), Decimal(s["price"])
            shares = b["shares"]
            assert shares == s["shares"] and didx[b["day"]] == t + 1
            # base costs carry no commission, so the per-share result is sell - buy
            assert Decimal(b["commission"]) == 0 == Decimal(s["commission"])
            assert Decimal(s["realized_pnl_usd"]) == (sell - buy) * shares
            replay_r = float(sell - buy) / row["planned_risk"]
            ended = s["reason"] == "end_of_data"
            reasons[s["reason"]] += 1
            if period == "IS":
                sig = signals[(t, symbol)]
                iso = isolated_outcome(
                    *ohlc[symbol], t + 1, sig.stop_price, sig.target_price,
                    sig.time_stop_bars, horizon, penalty, min_rr,
                )  # fmt: skip
                iso_r = iso["per_share"] / row["planned_risk"]
                iso_exit, iso_reason, iso_fill = iso["exit_index"], iso["exit_reason"], str(iso["exit_fill"])
                same_as_table = (
                    iso_exit == row["exit_index"]
                    and iso_reason == row["exit_reason"]
                    and iso_r == row["outcome_r"]
                )
                if ended:
                    period_end += 1
                    period_end_differs += int(not same_as_table)
                elif not same_as_table:
                    mismatches.append(f"{tag}: IS-horizon outcome differs from the table")
            else:
                iso_r, iso_exit = row["outcome_r"], row["exit_index"]
                iso_reason, iso_fill = row["exit_reason"], row["exit_fill"]
                period_end += int(ended)
            diff = abs(replay_r - iso_r)
            if diff > max_diff:
                max_diff, max_diff_trade = diff, tag
            if (
                diff > TOL
                or row["entry_fill"] != b["price"]
                or iso_fill != s["price"]
                or str(dates[iso_exit]) != s["day"]
                or iso_reason != s["reason"]
            ):
                mismatches.append(
                    f"{tag}: replay {replay_r!r} ({s['reason']} {s['day']} {s['price']}) vs "
                    f"isolated {iso_r!r} ({iso_reason} {dates[iso_exit]} {iso_fill})"
                )
        # the replay's own refusals at the open against the table's flags
        refusals: Counter[str] = Counter()
        decisions_checked = 0
        for d in loc.decisions:
            t = didx[d["day"]] - 1
            row = cand.get((t, d["symbol"]))
            decisions_checked += 1
            if row is None:
                mismatches.append(f"{d['symbol']} {d['day']}: decision without a candidate row")
                continue
            if d["status"] == "rejected" and d["reason"] in VALIDITY_REASONS:
                refusals[d["reason"]] += 1
                if row["status"] != NOT_CANDIDATE or row["refusal"] != d["reason"]:
                    mismatches.append(f"{d['symbol']} {d['day']}: refusal {d['reason']} not flagged")
            else:
                assert d["signal_day"] == row["signal_session"]
                if row["status"] != CANDIDATE:
                    mismatches.append(f"{d['symbol']} {d['day']}: flagged refused but replay sized it")
        cell = {
            "cap_set": caps.name,
            "period": period,
            "fills": len(loc.fills),
            "final_equity_usd": final_equity,
            "r3c_recorded_fills": recorded["local_fills"],
            "r3c_recorded_final_equity_usd": recorded["local_final_equity_usd"],
            "matches_r3c_record": matches_r3c,
            "library_identical": library_identical,
            "trades_compared": len(trades),
            "exit_reasons": dict(sorted(reasons.items())),
            "period_end_trades": period_end,
            "period_end_trades_differing_from_table": period_end_differs,
            "max_abs_diff_r": max_diff,
            "max_abs_diff_trade": max_diff_trade,
            "decisions_checked": decisions_checked,
            "refusals_at_open_checked": dict(sorted(refusals.items())),
            "mismatches": len(mismatches),
            "first_mismatches": mismatches[:10],
            "seconds": round(time.perf_counter() - t0, 1),
        }
        cell["passed"] = bool(
            library_identical and matches_r3c and not mismatches and max_diff <= TOL
        )
        cells.append(cell)
    return {"cells": cells, "passed": all(c["passed"] for c in cells)}


# ----------------------------------------------------------------------------- prepare stage
def _single_thread() -> None:
    for var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
        os.environ[var] = "1"


def prepare_book(args: tuple[str, int, int, str, str, dict[str, Any], list[dict[str, Any]]]) -> dict[str, Any]:
    strategy, snapshot_id, version_id, db, out_dir, caps_dict, r3c_cells = args
    _single_thread()
    started = time.perf_counter()
    out = Path(out_dir)
    caps = ca.Caps(**caps_dict)
    book = ca.load_book(Path(db), strategy, snapshot_id, version_id)
    assert book.dates[-1] == ca.DEV_END and max(book.dates) < ca.NEVER_ON_OR_AFTER
    table_info = ca.build_signal_table(book)  # R3-C: prefix assertions and its poison test
    keys_info = verify_keys(book)
    cache_info = compare_with_r3c_cache(book)
    cm, spread = frr.COST_CASES[ca.BASE]
    assert cm.commission(100) == 0.0  # base costs carry no commission
    penalty = penalty_of(cm, spread)
    min_rr = ca.make_limits(caps).min_reward_to_risk
    rows = build_candidates(book, penalty, min_rr)
    identity = identity_check(book, rows, caps, r3c_cells)
    write_csv(out / f"candidates_{strategy}.csv", CANDIDATE_FIELDS, rows)
    (out / "cache").mkdir(parents=True, exist_ok=True)
    payload = {
        "strategy": strategy,
        "snapshot_id": snapshot_id,
        "version_id": version_id,
        "dates": book.dates,
        "selected": book.selected,
        "n_is": book.n_is,
        "keys": book.keys,
        "rows": rows,
    }
    with (out / "cache" / f"{strategy}.pkl").open("wb") as fh:
        pickle.dump(payload, fh, protocol=pickle.HIGHEST_PROTOCOL)
    return {
        "strategy": strategy,
        "snapshot_id": snapshot_id,
        "strategy_version_id": version_id,
        "symbols": len(book.selected),
        "skipped_symbols": sorted(book.skipped),
        "sessions": {"full": len(book.dates), "IS": book.n_is, "OOS": len(book.dates) - book.n_is},
        "first_bar": str(book.dates[0]),
        "last_bar": str(book.dates[-1]),
        "penalty_per_side": penalty,
        "min_reward_to_risk": min_rr,
        "table": table_info,
        "keys_no_lookahead": keys_info,
        "r3c_cache": cache_info,
        "signals": len(rows),
        "identity": identity,
        "passed": bool(identity["passed"] and cache_info["passed"]),
        "seconds": round(time.perf_counter() - started, 1),
    }


def _git(*args: str) -> str:
    try:
        return subprocess.run(  # noqa: S603 - fixed read-only git query
            ["git", "-C", str(WORKTREE), *args],  # noqa: S607
            capture_output=True, text=True, check=True, timeout=30,
        ).stdout.strip()  # fmt: skip
    except Exception as exc:  # noqa: BLE001
        return f"unavailable ({exc.__class__.__name__})"


def _blob_matches_commit(path: Path, rev: str) -> bool:
    """True only when both git queries return a 40-hex object id and they agree (fails closed without git)."""
    hexdigits = set("0123456789abcdef")
    blob, committed = _git("hash-object", str(path)), _git("rev-parse", rev)
    return len(blob) == 40 and set(blob) <= hexdigits and blob == committed


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json_default(x: Any) -> Any:
    if isinstance(x, np.generic):
        return x.item()
    return str(x)


def stage_prepare(out: Path, db: Path, workers: int, books: list[str]) -> int:
    self_test_isolated()
    r3c_identity = json.loads((ca.default_out() / "identity.json").read_text())
    if not r3c_identity["passed"]:
        raise SystemExit("R3-C identity check did not pass; nothing to build on")
    caps = {c.name: c for c in ca.read_operating_caps(db)}["operating"]
    (recorded_caps,) = [c for c in r3c_identity["cap_sets"] if c["name"] == "operating"]
    assert asdict(caps) == recorded_caps, (asdict(caps), recorded_caps)
    print("operating caps:", asdict(caps), flush=True)
    r3c_cells = {b["strategy"]: b["cells"] for b in r3c_identity["books"]}
    tasks = [
        (s, snap, vid, str(db), str(out), asdict(caps), r3c_cells[s])
        for s, snap, vid in ca.BOOKS
        if s in books
    ]
    started = time.perf_counter()
    with mp.get_context("spawn").Pool(min(workers, len(tasks))) as pool:
        reports = pool.map(prepare_book, tasks, chunksize=1)
    identity = {
        "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "git_head": _git("rev-parse", "HEAD"),
        "script_sha256": _sha256(HERE),
        "r3c_script_sha256": _sha256(R3_DIR / "capacity_admission.py"),
        "r3c_script_matches_commit": _blob_matches_commit(
            R3_DIR / "capacity_admission.py", "HEAD:scripts/r3/capacity_admission.py"
        ),
        "database": str(db),
        "operating_caps": asdict(caps),
        "tolerance": TOL,
        "books": reports,
        "passed": all(r["passed"] for r in reports),
        "seconds": round(time.perf_counter() - started, 1),
    }
    (out / "identity.json").write_text(json.dumps(identity, indent=2, default=_json_default) + "\n")
    for r in reports:
        print(
            f"{r['strategy']}: {r['signals']} signals | signal table vs R3-C cache "
            f"{'identical' if r['r3c_cache']['passed'] else 'DIFFERENT'} | keys checked "
            f"{r['keys_no_lookahead']['keys_checked']} | identity {'PASS' if r['passed'] else 'FAIL'} | {r['seconds']}s",
            flush=True,
        )
        for c in r["identity"]["cells"]:
            print(
                f"   {c['cap_set']} {c['period']:3s} fills {c['fills']} final {c['final_equity_usd']} "
                f"(R3-C {c['r3c_recorded_fills']} / {c['r3c_recorded_final_equity_usd']}) library "
                f"{'identical' if c['library_identical'] else 'DIFFERENT'} | trades {c['trades_compared']} "
                f"period-end {c['period_end_trades']} max|diff| {c['max_abs_diff_r']:.3g} R | refusals "
                f"{c['refusals_at_open_checked']} | mismatches {c['mismatches']} "
                f"{'ok' if c['passed'] else 'MISMATCH'}",
                flush=True,
            )
            for m in c["first_mismatches"]:
                print("      ", m, flush=True)
    if not identity["passed"]:
        print("IDENTITY CHECK FAILED - study stops here", flush=True)
        return 2
    return 0


# ----------------------------------------------------------------------------- statistics
def key_order(cands: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    """R3-C's order: highest first; ties and missing keys by symbol, missing last."""

    def sort_key(r: dict[str, Any]) -> tuple[int, float, str]:
        v = r[key]
        return (0, -v, r["symbol"]) if math.isfinite(v) else (1, 0.0, r["symbol"])

    return sorted(cands, key=sort_key)


def average_ranks(x: np.ndarray) -> np.ndarray:
    order = np.argsort(x, kind="mergesort")
    sx = x[order]
    ranks = np.empty(len(x))
    i = 0
    while i < len(x):
        j = i
        while j + 1 < len(x) and sx[j + 1] == sx[i]:
            j += 1
        ranks[order[i : j + 1]] = (i + j) / 2 + 1
        i = j + 1
    return ranks


def spearman_in_key_order(outcomes: np.ndarray) -> float | None:
    """Spearman correlation between key rank and outcome for candidates listed in key
    order (first = highest key = highest rank). Tied outcomes share their average rank;
    undefined when every outcome is the same."""
    n = len(outcomes)
    key_rank = np.arange(n, 0, -1, dtype=float)
    out_rank = average_ranks(outcomes)
    if np.ptp(out_rank) == 0:
        return None
    return float(np.corrcoef(key_rank, out_rank)[0, 1])


def month_block_bootstrap(values: np.ndarray, months: list[tuple[int, int]]) -> dict[str, Any]:
    """Calendar-month block bootstrap of a mean over sessions, null recentred on zero
    (the convention of R3's entry-execution study)."""
    uniq = sorted(set(months))
    out: dict[str, Any] = {"sessions": int(len(values)), "months": len(uniq)}
    if len(values) == 0:
        return {**out, "mean": None, "p_one_sided": None}
    if len(uniq) < 2:  # one block cannot be resampled
        return {**out, "mean": float(np.mean(values)), "p_one_sided": None}
    idx = {m: i for i, m in enumerate(uniq)}
    mi = np.array([idx[m] for m in months])
    sums = np.bincount(mi, weights=values, minlength=len(uniq))
    counts = np.bincount(mi, minlength=len(uniq)).astype(float)
    observed = float(sums.sum() / counts.sum())
    rng = np.random.default_rng(SEED0)
    draws = rng.integers(0, len(uniq), size=(N_BOOT, len(uniq)))
    means = sums[draws].sum(axis=1) / counts[draws].sum(axis=1)
    null = means - observed
    p = (1 + int(np.count_nonzero(null >= observed))) / (N_BOOT + 1)
    lo, hi = np.percentile(means, [2.5, 97.5])
    return {
        **out,
        "first_month": f"{uniq[0][0]}-{uniq[0][1]:02d}",
        "last_month": f"{uniq[-1][0]}-{uniq[-1][1]:02d}",
        "mean": observed,
        "bootstrap_se": float(means.std(ddof=1)),
        "pct_interval_95": [float(lo), float(hi)],
        "share_resamples_le_0": float(np.mean(means <= 0)),
        "p_one_sided": float(p),
    }


def _month(r: dict[str, Any]) -> tuple[int, int]:
    d = date.fromisoformat(r["signal_session"])
    return (d.year, d.month)


def session_records(valid: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[int, list[dict[str, Any]]], dict[str, Any]]:
    """Per-session statistics for every signal session with at least MIN_CANDIDATES
    candidates in ``valid`` (rows that have an outcome), and the pooled tercile sums."""
    groups: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for r in valid:
        groups[r["t"]].append(r)
    for t in groups:
        groups[t] = sorted(groups[t], key=lambda r: r["symbol"])
    terc = {k: {p: [[0.0, 0] for _ in range(3)] for p in PERIODS} for k in KEYS}
    recs = []
    for t in sorted(groups):
        cs = groups[t]
        n = len(cs)
        if n < MIN_CANDIDATES:
            continue
        period = cs[0]["period"]
        assert all(r["period"] == period for r in cs)
        outs = np.array([r["outcome_r"] for r in cs])
        mean_all = float(outs.mean())
        alpha2 = float(outs[:TOP_N].mean())  # rows are in symbol order
        rec: dict[str, Any] = {
            "t": t,
            "signal_session": cs[0]["signal_session"],
            "entry_session": cs[0]["entry_session"],
            "period": period,
            "n": n,
            "mean_all": mean_all,
            "alpha2_mean": alpha2,
            "alpha2_lift": alpha2 - mean_all,
            "alpha2": "|".join(r["symbol"] for r in cs[:TOP_N]),
        }
        for k in KEYS:
            order = key_order(cs, k)
            o = np.array([r["outcome_r"] for r in order])
            top2 = float(o[:TOP_N].mean())
            rec[f"top2_mean_{k}"] = top2
            rec[f"lift_{k}"] = top2 - mean_all
            rec[f"lift_vs_alpha2_{k}"] = top2 - alpha2
            rec[f"ic_{k}"] = spearman_in_key_order(o)
            rec[f"top2_{k}"] = "|".join(r["symbol"] for r in order[:TOP_N])
            rec[f"missing_{k}"] = sum(1 for r in cs if not math.isfinite(r[k]))
            finite = [r[k] for r in cs if math.isfinite(r[k])]
            rec[f"tied_{k}"] = int(len(set(finite)) != len(finite))
            for pos, r in enumerate(order):
                bucket = (3 * (2 * pos + 1)) // (2 * n)
                terc[k][period][bucket][0] += r["outcome_r"]
                terc[k][period][bucket][1] += 1
        recs.append(rec)
    return recs, groups, terc


def key_period_stats(recs: list[dict[str, Any]], key: str, period: str) -> dict[str, Any]:
    rs = [r for r in recs if r["period"] == period]
    months = [_month(r) for r in rs]
    lifts = np.array([r[f"lift_{key}"] for r in rs], dtype=float)
    ic_rs = [r for r in rs if r[f"ic_{key}"] is not None]
    ics = np.array([r[f"ic_{key}"] for r in ic_rs], dtype=float)
    boot_lift = month_block_bootstrap(lifts, months)
    boot_ic = month_block_bootstrap(ics, [_month(r) for r in ic_rs])
    out = {
        "sessions": len(rs),
        "candidates": int(sum(r["n"] for r in rs)),
        "months": boot_lift["months"],
        "mean_of_session_means": float(np.mean([r["mean_all"] for r in rs])) if rs else None,
        "top2_mean": float(np.mean([r[f"top2_mean_{key}"] for r in rs])) if rs else None,
        "top2_lift": boot_lift["mean"],
        "top2_lift_bootstrap": boot_lift,
        "top2_lift_p": boot_lift["p_one_sided"],
        "sessions_lift_positive": int(np.count_nonzero(lifts > 0)),
        "rank_ic": boot_ic["mean"],
        "rank_ic_bootstrap": boot_ic,
        "rank_ic_p": boot_ic["p_one_sided"],
        "rank_ic_sessions": len(ic_rs),
        "rank_ic_undefined_sessions": len(rs) - len(ic_rs),
        "sessions_with_missing_key": sum(1 for r in rs if r[f"missing_{key}"]),
        "sessions_with_tied_key": sum(1 for r in rs if r[f"tied_{key}"]),
        "top2_most_frequent": [
            {"symbol": sym, "sessions": cnt, "share": cnt / len(rs)}
            for sym, cnt in Counter(x for r in rs for x in r[f"top2_{key}"].split("|")).most_common(3)
        ],
        "lift_vs_alphabetical_two": float(np.mean([r[f"lift_vs_alpha2_{key}"] for r in rs])) if rs else None,
    }
    by_year: dict[int, list[float]] = defaultdict(list)
    for r in rs:
        by_year[int(r["signal_session"][:4])].append(r[f"lift_{key}"])
    out["by_year"] = {
        str(y): {"sessions": len(v), "top2_lift": float(np.mean(v))} for y, v in sorted(by_year.items())
    }
    return out


def padded_sessions(
    recs: list[dict[str, Any]], groups: dict[int, list[dict[str, Any]]], selected: list[str]
) -> dict[str, np.ndarray]:
    """Qualifying sessions as rectangular arrays (symbol index, outcome, validity mask)."""
    index = {s: j for j, s in enumerate(selected)}
    width = max(r["n"] for r in recs)
    sym = np.zeros((len(recs), width), dtype=np.intp)
    mask = np.zeros((len(recs), width), dtype=bool)
    outs = np.zeros((len(recs), width))
    for a, rec in enumerate(recs):
        cs = groups[rec["t"]]
        sym[a, : len(cs)] = [index[r["symbol"]] for r in cs]
        outs[a, : len(cs)] = [r["outcome_r"] for r in cs]
        mask[a, : len(cs)] = True
    return {
        "sym": sym,
        "mask": mask,
        "outs": outs,
        "entry_rows": np.array([rec["t"] + 1 for rec in recs])[:, None],
        "mean_all": np.array([rec["mean_all"] for rec in recs]),
        "is_mask": np.array([rec["period"] == "IS" for rec in recs]),
    }


def random_pick(seed_index: int, n_dates: int, n_symbols: int, pad: dict[str, np.ndarray]) -> np.ndarray:
    """Columns of the TOP_N candidates a random ranking puts first on each session.

    Ranking i gives every (session, symbol) one uniform priority from
    ``numpy.random.default_rng(SEED0 + i)`` on the full calendar x sorted-symbols grid, read
    on the entry session's row, lowest first: R3-C's random order of that seed."""
    prio = np.random.default_rng(SEED0 + seed_index).random((n_dates, n_symbols))
    p = prio[pad["entry_rows"], pad["sym"]]
    p[~pad["mask"]] = np.inf
    return np.argpartition(p, TOP_N - 1, axis=1)[:, :TOP_N]


def random_band(pad: dict[str, np.ndarray] | None, n_dates: int, n_symbols: int) -> np.ndarray:
    """Top-2 lift of N_RANDOM random within-day rankings; column 0 = IS, 1 = OOS."""
    band = np.full((N_RANDOM, 2), np.nan)
    if pad is None:
        return band
    is_mask = pad["is_mask"]
    for i in range(N_RANDOM):
        two = random_pick(i, n_dates, n_symbols, pad)
        lift = np.take_along_axis(pad["outs"], two, axis=1).mean(axis=1) - pad["mean_all"]
        if is_mask.any():
            band[i, 0] = lift[is_mask].mean()
        if (~is_mask).any():
            band[i, 1] = lift[~is_mask].mean()
    return band


def verify_orders(
    recs: list[dict[str, Any]],
    groups: dict[int, list[dict[str, Any]]],
    payload: dict[str, Any],
    pad: dict[str, np.ndarray] | None,
) -> dict[str, Any]:
    """This file's key order and random pick against R3-C's own order functions, on
    every qualifying session."""
    ns = SimpleNamespace(dates=payload["dates"], selected=payload["selected"], keys=payload["keys"])
    checked = 0
    for k in KEYS:
        order_fn = ca.make_order(ns, ("key", k))
        for rec in recs:
            cs = groups[rec["t"]]
            mine = [r["symbol"] for r in key_order(cs, k)]
            theirs = [s for s, _ in order_fn(rec["t"] + 1, {r["symbol"]: r for r in cs})]
            assert mine == theirs, (k, rec["signal_session"])
            checked += 1
    random_checked = 0
    if pad is not None:
        selected = payload["selected"]
        for i in (0, ca.N_SEEDS - 1, N_RANDOM - 1):
            order_fn = ca.make_order(ns, ("random", SEED0 + i))
            two = random_pick(i, len(payload["dates"]), len(selected), pad)
            for a, rec in enumerate(recs):
                cs = groups[rec["t"]]
                theirs = [s for s, _ in order_fn(rec["t"] + 1, {r["symbol"]: r for r in cs})][:TOP_N]
                mine = {selected[pad["sym"][a, j]] for j in two[a]}
                assert mine == set(theirs) and len(mine) == TOP_N, (i, rec["signal_session"])
                random_checked += 1
    return {"key_orders_checked": checked, "random_orders_checked": random_checked}


def band_stats(band: np.ndarray, col: int, observed: dict[str, float | None]) -> dict[str, Any]:
    v = band[:, col]
    if np.isnan(v).all():
        return {"rankings": 0}
    out = {
        "rankings": int(len(v)),
        "p5": float(np.percentile(v, 5)),
        "p50": float(np.percentile(v, 50)),
        "p95": float(np.percentile(v, BAND_PCT)),
        "mean": float(v.mean()),
        "min": float(v.min()),
        "max": float(v.max()),
        "sd": float(v.std(ddof=1)),
    }
    for k, obs in observed.items():
        if obs is not None:
            out[f"{k}_percentile"] = float(np.mean(v < obs) * 100)
            out[f"{k}_rankings_at_or_above"] = int(np.count_nonzero(v >= obs))
            out[f"{k}_above_p95"] = bool(obs > out["p95"])
    return out


def _bin(n: int) -> str:
    if n <= 5:
        return str(n)
    if n <= 10:
        return "6-10"
    if n <= 20:
        return "11-20"
    if n <= 40:
        return "21-40"
    return "41+"


SESSION_FIELDS = (
    ["signal_session", "entry_session", "period", "n", "mean_all", "alpha2", "alpha2_mean", "alpha2_lift"]
    + [f"{f}_{k}" for k in KEYS for f in ("top2", "top2_mean", "lift", "lift_vs_alpha2", "ic", "missing", "tied")]
)


def analyze_book(args: tuple[str, str]) -> dict[str, Any]:
    strategy, out_dir = args
    _single_thread()
    started = time.perf_counter()
    out = Path(out_dir)
    # Trusted input: written by this script's own prepare stage into the scratch folder.
    with (out / "cache" / f"{strategy}.pkl").open("rb") as fh:
        payload = pickle.load(fh)  # noqa: S301 - this script's own cache
    rows = payload["rows"]
    dates = payload["dates"]
    n = len(dates)
    n_is = payload["n_is"]
    valid = [r for r in rows if r["status"] == CANDIDATE]
    refused = [r for r in rows if r["status"] == NOT_CANDIDATE]
    assert len(valid) + len(refused) == len(rows)

    # ---- scope and plain descriptive facts
    scope: dict[str, Any] = {"signals": len(rows), "by_period": {}}
    per_t = Counter(r["t"] for r in valid)
    for period in PERIODS:
        pr = [r for r in rows if r["period"] == period]
        pv = [r for r in valid if r["period"] == period]
        t_range = range(ca.WARMUP, n_is - 1) if period == "IS" else range(n_is - 1, n - 1)
        hist = Counter(_bin(per_t.get(t, 0)) for t in t_range)
        on3 = sum(1 for r in pv if per_t[r["t"]] >= MIN_CANDIDATES)
        outs = np.array([r["outcome_r"] for r in pv])
        scope["by_period"][period] = {
            "signal_sessions_in_period": len(t_range),
            "first_signal_session": str(dates[t_range[0]]),
            "last_signal_session": str(dates[t_range[-1]]),
            "signals": len(pr),
            "refused_at_open": dict(sorted(Counter(r["refusal"] for r in pr if r["refusal"]).items())),
            "candidates_with_outcome": len(pv),
            "sessions_by_candidate_count": {b: hist.get(b, 0) for b in COUNT_BINS},
            "sessions_with_any_candidate": sum(1 for t in t_range if per_t.get(t, 0) >= 1),
            "sessions_with_min_candidates": sum(1 for t in t_range if per_t.get(t, 0) >= MIN_CANDIDATES),
            "candidates_on_sessions_with_min": on3,
            "share_of_candidates_on_sessions_with_min": on3 / len(pv) if pv else None,
            "max_candidates_in_a_session": max((per_t.get(t, 0) for t in t_range), default=0),
            "mean_outcome_all_candidates": float(outs.mean()) if len(outs) else None,
            "share_positive_outcome": float(np.mean(outs > 0)) if len(outs) else None,
            "exit_reasons": dict(sorted(Counter(r["exit_reason"] for r in pv).items())),
            "open_at_window_end": sum(1 for r in pv if r["open_at_window_end"]),
            "exit_after_is_end": sum(1 for r in pv if r["exit_after_is_end"]),
            "signals_inside_held_window": sum(1 for r in pr if r["inside_held_window"]),
            "candidates_inside_held_window": sum(1 for r in pv if r["inside_held_window"]),
            "signals_inside_any_earlier_window": sum(1 for r in pr if r["inside_any_earlier_window"]),
            "candidates_inside_any_earlier_window": sum(1 for r in pv if r["inside_any_earlier_window"]),
            "candidates_key_missing": {k: sum(1 for r in pv if not math.isfinite(r[k])) for k in KEYS},
        }

    # ---- pre-registered statistics on all candidates
    recs, groups, terc = session_records(valid)
    pad = padded_sessions(recs, groups, payload["selected"]) if recs else None
    order_check = verify_orders(recs, groups, payload, pad)
    write_csv(out / f"sessions_{strategy}.csv", SESSION_FIELDS, recs)
    band = random_band(pad, n, len(payload["selected"]))
    np.savetxt(
        out / f"random_band_{strategy}.csv", band, delimiter=",", header="top2_lift_IS,top2_lift_OOS", comments=""
    )
    stats: dict[str, Any] = {}
    for k in KEYS:
        stats[k] = {}
        for period in PERIODS:
            s = key_period_stats(recs, k, period)
            s["terciles"] = {
                name: {"candidates": cnt, "mean_outcome": (total / cnt if cnt else None)}
                for name, (total, cnt) in zip(("top", "middle", "bottom"), terc[k][period], strict=True)
            }
            stats[k][period] = s
    alpha2 = {}
    for period in PERIODS:
        rs = [r for r in recs if r["period"] == period]
        alpha2[period] = {
            "sessions": len(rs),
            "alphabetical_two_mean": float(np.mean([r["alpha2_mean"] for r in rs])) if rs else None,
            "alphabetical_two_lift_vs_all": float(np.mean([r["alpha2_lift"] for r in rs])) if rs else None,
        }
    random2 = {}
    for col, period in enumerate(PERIODS):
        observed = {k: stats[k][period]["top2_lift"] for k in KEYS}
        observed["alpha2"] = alpha2[period]["alphabetical_two_lift_vs_all"]
        random2[period] = band_stats(band, col, observed)

    # ---- clarification detail: sessions in which the key is missing (R3-C order = symbol order)
    missing_detail = {}
    for k in KEYS:
        missing_detail[k] = {}
        for period in PERIODS:
            rs = [r for r in recs if r["period"] == period]
            hit = [r for r in rs if r[f"missing_{k}"]]
            if not hit:
                continue
            keep = [r for r in rs if not r[f"missing_{k}"]]
            keep_ic = [r for r in keep if r[f"ic_{k}"] is not None]
            missing_detail[k][period] = {
                "sessions_with_missing_key": len(hit),
                "sessions_all_missing": sum(1 for r in hit if r[f"missing_{k}"] == r["n"]),
                "first": hit[0]["signal_session"],
                "last": hit[-1]["signal_session"],
                "top2_lift_excluding_them": float(np.mean([r[f"lift_{k}"] for r in keep])) if keep else None,
                "rank_ic_excluding_them": float(np.mean([r[f"ic_{k}"] for r in keep_ic])) if keep_ic else None,
            }

    # ---- descriptive: candidates a one-position-per-symbol account would be offered
    kept = [r for r in valid if not r["inside_held_window"]]
    recs_no, _groups_no, _terc_no = session_records(kept)
    write_csv(out / f"sessions_nonoverlap_{strategy}.csv", SESSION_FIELDS, recs_no)
    non_overlap: dict[str, Any] = {"candidates_kept": len(kept), "stats": {}}
    for k in KEYS:
        non_overlap["stats"][k] = {}
        for period in PERIODS:
            s = key_period_stats(recs_no, k, period)
            non_overlap["stats"][k][period] = {
                f: s[f]
                for f in (
                    "sessions", "candidates", "months", "mean_of_session_means", "top2_mean", "top2_lift",
                    "top2_lift_p", "rank_ic", "rank_ic_p", "lift_vs_alphabetical_two",
                )
            }  # fmt: skip
    return {
        "strategy": strategy,
        "snapshot_id": payload["snapshot_id"],
        "strategy_version_id": payload["version_id"],
        "symbols": len(payload["selected"]),
        "scope": scope,
        "order_check": order_check,
        "stats": stats,
        "random2_band": random2,
        "alphabetical_two": alpha2,
        "missing_key_detail": missing_detail,
        "non_overlap": non_overlap,
        "seconds": round(time.perf_counter() - started, 1),
    }


def decision(book: dict[str, Any]) -> dict[str, Any]:
    """The pre-registered rule, applied mechanically to the primary book and key."""
    s = book["stats"][PRIMARY_KEY]
    band = book["random2_band"]["OOS"]
    is_, oos = s["IS"], s["OOS"]
    conditions = {
        "top2_lift_positive_is": bool(is_["top2_lift"] > 0),
        "top2_lift_positive_oos": bool(oos["top2_lift"] > 0),
        "oos_one_sided_p_below_0.05": bool(oos["top2_lift_p"] < ALPHA),
        "rank_ic_positive_is": bool(is_["rank_ic"] > 0),
        "rank_ic_positive_oos": bool(oos["rank_ic"] > 0),
        "oos_top2_lift_above_random2_p95": bool(oos["top2_lift"] > band["p95"]),
    }
    return {
        "book": PRIMARY_BOOK,
        "key": PRIMARY_KEY,
        "values": {
            "top2_lift_is": is_["top2_lift"],
            "top2_lift_oos": oos["top2_lift"],
            "oos_one_sided_p": oos["top2_lift_p"],
            "rank_ic_is": is_["rank_ic"],
            "rank_ic_oos": oos["rank_ic"],
            "random2_p95_oos": band["p95"],
        },
        "conditions": conditions,
        "confirmed": all(conditions.values()),
        "verdict": "confirmed" if all(conditions.values()) else "not confirmed",
    }


def _identity(out: Path) -> dict[str, Any]:
    identity = json.loads((out / "identity.json").read_text())
    if not identity["passed"]:
        raise SystemExit("identity check has not passed; nothing may be run or reported")
    return identity


def stage_analyze(out: Path, workers: int, books: list[str]) -> int:
    identity = _identity(out)
    if identity["script_sha256"] != _sha256(HERE):
        raise SystemExit("script changed since the prepare stage; run prepare again")
    done = {b["strategy"] for b in identity["books"]}
    todo = [b for b, _, _ in ca.BOOKS if b in books and b in done]
    started = time.perf_counter()
    with mp.get_context("spawn").Pool(min(workers, len(todo))) as pool:
        results = pool.map(analyze_book, [(b, str(out)) for b in todo], chunksize=1)
    by_book = {r["strategy"]: r for r in results}
    summary = {
        "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "git_head": _git("rev-parse", "HEAD"),
        "script_sha256": _sha256(HERE),
        "preregistration": PREREG,
        "database": identity["database"],
        "parameters": {
            "primary_book": PRIMARY_BOOK,
            "primary_key": PRIMARY_KEY,
            "min_candidates": MIN_CANDIDATES,
            "top_n": TOP_N,
            "random_rankings": N_RANDOM,
            "bootstrap_resamples": N_BOOT,
            "seed": SEED0,
            "alpha": ALPHA,
            "band_percentile": BAND_PCT,
            "is_end": str(ca.IS_END),
            "window": [str(ca.FULL_START), str(ca.DEV_END)],
            "workers": workers,
        },
        "books": by_book,
        "decision": decision(by_book[PRIMARY_BOOK]) if PRIMARY_BOOK in by_book else None,
        "seconds": round(time.perf_counter() - started, 1),
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2, default=_json_default) + "\n")
    for b in todo:
        r = by_book[b]
        for k in KEYS:
            for period in PERIODS:
                s = r["stats"][k][period]
                if not s["sessions"]:
                    continue
                band = r["random2_band"][period]
                print(
                    f"{b} {k} {period}: sessions {s['sessions']} candidates {s['candidates']} "
                    f"top-2 lift {s['top2_lift']:+.4f} p {s['top2_lift_p']:.4f} IC {s['rank_ic']:+.4f} "
                    f"p {s['rank_ic_p']:.4f} | random-2 p95 {band['p95']:+.4f} "
                    f"percentile {band[f'{k}_percentile']:.1f}",
                    flush=True,
                )
    if summary["decision"]:
        print("decision:", json.dumps(summary["decision"], indent=1), flush=True)
    return 0


# ----------------------------------------------------------------------------- report
def _n(x: float | None, digits: int = 3, signed: bool = True) -> str:
    if x is None or (isinstance(x, float) and not math.isfinite(x)):
        return "n/a"
    if round(x, digits) == 0:
        x = 0.0  # no "-0.000"
    return f"{x:+.{digits}f}" if signed else f"{x:.{digits}f}"


def _p(x: float | None) -> str:
    return "n/a" if x is None else f"{x:.4f}"


def _yn(flag: bool) -> str:
    return "yes" if flag else "no"


def _dir(x: float) -> str:
    return "better" if x > 0 else "worse"


def _stats_rows(book: dict[str, Any], keys: tuple[str, ...]) -> list[str]:
    rows = []
    for k in keys:
        for period in PERIODS:
            s = book["stats"][k][period]
            band = book["random2_band"][period]
            if not s["sessions"]:
                rows.append(f"| {k} | {period} | 0 | 0 | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a |")
                continue
            t = s["terciles"]
            rows.append(
                f"| {k} | {period} | {s['sessions']} | {s['candidates']} | {_n(s['mean_of_session_means'])} | "
                f"{_n(s['top2_mean'])} | {_n(s['top2_lift'], 4)} | {_p(s['top2_lift_p'])} | "
                f"{_n(band['p5'])} / {_n(band['p50'])} / {_n(band['p95'])} | {band[f'{k}_percentile']:.1f} | "
                f"{_n(s['rank_ic'], 4)} | {_p(s['rank_ic_p'])} | "
                f"{_n(t['top']['mean_outcome'])} / {_n(t['middle']['mean_outcome'])} / {_n(t['bottom']['mean_outcome'])} | "
                f"{t['top']['candidates']} / {t['middle']['candidates']} / {t['bottom']['candidates']} |"
            )
    return rows


STATS_HEADER = [
    "| Key | Period | Sessions | Candidates | Day's mean, all candidates (R) | Top-2 mean (R) | Top-2 lift (R) | Bootstrap p | Random-2 lift p5 / p50 / p95 (R) | Share of the 1,000 random picks below the lift (%) | Rank IC | IC bootstrap p | Tercile mean, top / middle / bottom (R) | Tercile candidates |",
    "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
]


def standout_cells(summary: dict[str, Any]) -> tuple[int, list[dict[str, Any]]]:
    """Control and descriptive cells (everything except the primary book's K1) whose top-2
    lift is above the random-2 95th percentile of their own book and period."""
    total = 0
    hits = []
    for name, b in summary["books"].items():
        for k in KEYS:
            if name == PRIMARY_BOOK and k == PRIMARY_KEY:
                continue
            for period in PERIODS:
                s = b["stats"][k][period]
                if not s["sessions"]:
                    continue
                total += 1
                band = b["random2_band"][period]
                if band[f"{k}_above_p95"]:
                    hits.append(
                        {
                            "book": name,
                            "key": k,
                            "period": period,
                            "lift": s["top2_lift"],
                            "p": s["top2_lift_p"],
                            "percentile": band[f"{k}_percentile"],
                            "sessions": s["sessions"],
                            "pick": s["top2_most_frequent"][0],
                        }
                    )
    return total, hits


def answer_paragraphs(summary: dict[str, Any]) -> list[str]:
    books = summary["books"]
    dec = summary["decision"]
    v = dec["values"]
    c = dec["conditions"]
    primary = books[PRIMARY_BOOK]
    ps = primary["stats"][PRIMARY_KEY]
    band = primary["random2_band"]
    # The pre-registration states four conditions; two of them are "in IS and in OOS", recorded as six flags.
    four = [
        c["top2_lift_positive_is"] and c["top2_lift_positive_oos"],
        c["oos_one_sided_p_below_0.05"],
        c["rank_ic_positive_is"] and c["rank_ic_positive_oos"],
        c["oos_top2_lift_above_random2_p95"],
    ]
    n_true = sum(four)
    held = "None of the four pre-registered conditions holds" if n_true == 0 else f"{n_true} of the four pre-registered conditions hold"
    measured = (
        f"On trend_continuation.medium, on days with at least three candidates, the two with the highest 63-session relative "
        f"strength (K1) did {abs(v['top2_lift_is']):.3f} R {_dir(v['top2_lift_is'])} than the day's average candidate in IS "
        f"({ps['IS']['sessions']:,} sessions) and {abs(v['top2_lift_oos']):.3f} R {_dir(v['top2_lift_oos'])} in OOS "
        f"({ps['OOS']['sessions']:,} sessions; one-sided p = {v['oos_one_sided_p']:.2f}); the within-day rank IC is "
        f"{_n(v['rank_ic_is'])} and {_n(v['rank_ic_oos'])}."
    )
    if dec["confirmed"]:
        lead = (
            "**Confirmed: the two highest-ranked same-day candidates did better than the rest.** " + measured + " "
            f"All four pre-registered conditions hold, including an OOS lift above the 95th percentile of 1,000 random two-a-day picks "
            f"({_n(v['random2_p95_oos'])} R), so K1 is confirmed as an admission ranker for this book."
        )
    else:
        lead = (
            "**Not confirmed: ranking same-day candidates by relative strength did not pick the better ones.** " + measured + " "
            f"{held}, so K1 is not confirmed as an admission ranker and, as pre-registered, "
            "the R3-C result for K1 on this book is read as admission luck."
        )
    scale = (
        f"For scale, 1,000 random picks of two a day move the OOS lift between {_n(band['OOS']['p5'])} and {_n(band['OOS']['p95'])} R "
        f"(5th to 95th percentile). The K1 lift is above {band['OOS']['K1_percentile']:.1f}% of them in OOS and "
        f"{band['IS']['K1_percentile']:.1f}% in IS; the bar was the 95th percentile in OOS. The average candidate itself earned "
        f"{_n(primary['scope']['by_period']['IS']['mean_outcome_all_candidates'])} R in IS and "
        f"{_n(primary['scope']['by_period']['OOS']['mean_outcome_all_candidates'])} R in OOS after base costs. That average was positive in "
        "both periods, but no test of it was pre-registered or run here, and these are development data in which many signals "
        "repeat inside an open holding window of the same symbol. K1 does not say which same-day signals did better."
        if not dec["confirmed"]
        else f"For scale, 1,000 random picks of two a day move the OOS lift between {_n(band['OOS']['p5'])} and {_n(band['OOS']['p95'])} R "
        f"(5th to 95th percentile); the K1 lift is above {band['OOS']['K1_percentile']:.1f}% of them in OOS and {band['IS']['K1_percentile']:.1f}% in IS."
    )
    ctrl = [
        f"{k} {_n(primary['stats'][k]['IS']['top2_lift'])} / {_n(primary['stats'][k]['OOS']['top2_lift'])} R" for k in ("K2", "K3")
    ]
    others = [
        f"{BOOK_LABELS[name]} {_n(b['stats']['K1']['IS']['top2_lift'])} / {_n(b['stats']['K1']['OOS']['top2_lift'])} R"
        for name, b in books.items()
        if name != PRIMARY_BOOK
    ]
    total, hits = standout_cells(summary)
    hit_text = "; ".join(f"{h['key']} on {BOOK_LABELS[h['book']]} in {h['period']}" for h in hits) or "none"
    rest = (
        "Controls and descriptions, no verdict (top-2 lift, IS / OOS): on the same book " + ", ".join(ctrl) + "; K1 on the other "
        "three books " + "; ".join(others) + f". Of these {total} control and descriptive cells, {len(hits)} "
        f"{'is' if len(hits) == 1 else 'are'} above the random-2 95th percentile ({hit_text}); about {total * 0.05:.0f} would be by chance."
    )
    return [lead, scale, rest]


def reading_points(summary: dict[str, Any]) -> list[str]:
    books = summary["books"]
    dec = summary["decision"]
    v = dec["values"]
    primary = books[PRIMARY_BOOK]
    ps = primary["stats"][PRIMARY_KEY]
    sc = primary["scope"]["by_period"]
    no = primary["non_overlap"]["stats"][PRIMARY_KEY]
    band = primary["random2_band"]
    a2 = primary["alphabetical_two"]
    out = []
    out.append(
        "**Against R3-C.** In R3-C's funded replay on the operating caps, K1 ordering earned +32.13% in IS and +15.77% in OOS against "
        "random-order medians of +10.37% and +6.28% (R3-C results file). A replay scores only the 4% to 5% of signals that get in, "
        f"and each admission changes the later ones. Here every candidate is scored once, {ps['IS']['candidates']:,} in IS and "
        f"{ps['OOS']['candidates']:,} in OOS on days with three or more, and the highest-K1 pair is "
        + ("better than the rest in both periods." if v["top2_lift_is"] > 0 and v["top2_lift_oos"] > 0 else "not better than the rest.")
    )
    held_is = sc["IS"]["signals_inside_held_window"] / sc["IS"]["signals"] * 100
    held_oos = sc["OOS"]["signals_inside_held_window"] / sc["OOS"]["signals"] * 100
    one_pos = (
        f"**The one-position view (descriptive).** An account holds one position per symbol, so it would not see {held_is:.0f}% (IS) "
        f"and {held_oos:.0f}% (OOS) of these signals. On the candidates it would be offered, the K1 top-2 lift is "
        f"{_n(no['IS']['top2_lift'])} R in IS (p = {no['IS']['top2_lift_p']:.3f}, {no['IS']['sessions']} sessions) and "
        f"{_n(no['OOS']['top2_lift'])} R in OOS (p = {no['OOS']['top2_lift_p']:.3f}, {no['OOS']['sessions']} sessions)."
    )
    one_pos += (
        " This subset is an addition to the pre-registered statistics, chosen after R3-C was known; its p-values are unadjusted "
        "and it is one of 8 such cells, so it is a description and not evidence for K1."
    )
    if no["IS"]["top2_lift"] > 0 and no["OOS"]["top2_lift"] <= 0:
        one_pos += " The positive IS sign does not carry into OOS."
    out.append(one_pos)
    t_is, t_oos = ps["IS"]["terciles"], ps["OOS"]["terciles"]
    thirds = (
        "**Thirds of the ranking.** Pooled over sessions, the top, middle and bottom third by K1 earned "
        f"{_n(t_is['top']['mean_outcome'])}, {_n(t_is['middle']['mean_outcome'])} and {_n(t_is['bottom']['mean_outcome'])} R in IS, and "
        f"{_n(t_oos['top']['mean_outcome'])}, {_n(t_oos['middle']['mean_outcome'])} and {_n(t_oos['bottom']['mean_outcome'])} R in OOS."
    )
    if t_oos["bottom"]["mean_outcome"] > t_oos["middle"]["mean_outcome"] > t_oos["top"]["mean_outcome"]:
        thirds += " In OOS the order runs the wrong way: the lowest-ranked third did best."
    out.append(thirds)
    wins = sum(
        1
        for b in books.values()
        for period in PERIODS
        if (b["alphabetical_two"][period]["alphabetical_two_lift_vs_all"] or 0) > 0
    )
    cells = sum(1 for b in books.values() for period in PERIODS if b["alphabetical_two"][period]["sessions"])
    out.append(
        "**The alphabetical order was lucky.** The two alphabetically first candidates, which the library order offers first, beat the "
        f"day's average by {_n(a2['IS']['alphabetical_two_lift_vs_all'])} R in IS and {_n(a2['OOS']['alphabetical_two_lift_vs_all'])} R in "
        f"OOS on this book (above {band['IS']['alpha2_percentile']:.1f}% and {band['OOS']['alpha2_percentile']:.1f}% of the random picks), "
        f"and by a positive amount in {wins} of the {cells} book-periods. That is a property of which tickers sort first, not a rule. "
        "R3-C found the same: the alphabetical order sat at the 92.5th to 100th percentile of random orders in five of its eight OOS cells."
    )
    total, hits = standout_cells(summary)
    if hits:
        listed = "; ".join(
            f"{h['key']} on {BOOK_LABELS[h['book']]} in {h['period']}: {_n(h['lift'])} R, p = {h['p']:.3f}, {h['sessions']} sessions, "
            f"most frequent pick {h['pick']['symbol']} on {h['pick']['share'] * 100:.0f}% of them"
            for h in hits
        )
        rs = books.get("relative_strength.medium_swing")
        extra = ""
        if rs:
            rsc = rs["scope"]["by_period"]
            share = (rsc["IS"]["signals_inside_held_window"] + rsc["OOS"]["signals_inside_held_window"]) / (
                rsc["IS"]["signals"] + rsc["OOS"]["signals"]
            )
            extra = (
                f" On relative_strength.medium {share * 100:.0f}% of the signals repeat inside a holding window that is already open, "
                "so its sessions are far from independent."
            )
        out.append(
            f"**Control cells that stand out.** {len(hits)} of the {total} control and descriptive cells are above their random-2 95th "
            f"percentile ({listed}). None was a hypothesis and none carries a verdict. A key that keeps picking the same name on a "
            "23-symbol book measures that name more than it ranks candidates." + extra + " Any of them would need its own pre-registration."
        )
    out.append(
        "**Dependence.** Neighbouring sessions share symbols and holding windows of up to 40 sessions, so they are not independent; the "
        "calendar-month bootstrap allows for part of that. The caveat would weaken a pass"
        + ("." if dec["confirmed"] else "; it does not rescue this result, whose lift has the wrong sign in both periods." if v["top2_lift_is"] <= 0 and v["top2_lift_oos"] <= 0 else "; it does not turn this result into one.")
    )
    return out


def expectation_rows(summary: dict[str, Any]) -> list[tuple[str, str]]:
    dec = summary["decision"]
    v = dec["values"]
    primary = summary["books"][PRIMARY_BOOK]
    band = primary["random2_band"]
    return [
        (
            "Uncertain; R3-C points to a positive lift for this book",
            f"Top-2 lift {_n(v['top2_lift_is'], 4)} R in IS and {_n(v['top2_lift_oos'], 4)} R in OOS; rank IC {_n(v['rank_ic_is'], 4)} and {_n(v['rank_ic_oos'], 4)}.",
        ),
        (
            "A small positive lift that does not clear the bar is the most likely outcome",
            f"{'Cleared the bar' if dec['confirmed'] else 'Did not clear the bar'}"
            + ("" if v["top2_lift_oos"] > 0 else ", and the lift is not positive")
            + f": OOS p {_p(v['oos_one_sided_p'])}; OOS lift above {band['OOS']['K1_percentile']:.1f}% of the random picks "
            f"(95th percentile {_n(v['random2_p95_oos'], 4)} R).",
        ),
    ]


def clarifications(summary: dict[str, Any], identity: dict[str, Any]) -> list[str]:
    books = summary["books"]
    primary = books[PRIMARY_BOOK]
    sc = primary["scope"]["by_period"]
    ib = {b["strategy"]: b for b in identity["books"]}
    pen_bps = ib[PRIMARY_BOOK]["penalty_per_side"] * 10000
    min_rr = ib[PRIMARY_BOOK]["min_reward_to_risk"]
    tot_end = sum(b["scope"]["by_period"]["OOS"]["open_at_window_end"] for b in books.values())
    tot_after = sum(b["scope"]["by_period"]["IS"]["exit_after_is_end"] for b in books.values())
    md = primary["missing_key_detail"]["K1"].get("IS")
    if md:
        assert md["sessions_all_missing"] == md["sessions_with_missing_key"]
    und = sum(b["stats"][k][p]["rank_ic_undefined_sessions"] for b in books.values() for k in KEYS for p in PERIODS)
    tied = sum(b["stats"][k][p]["sessions_with_tied_key"] for b in books.values() for k in KEYS for p in PERIODS)
    keys_checked = sum(b["keys_no_lookahead"]["keys_checked"] for b in identity["books"])
    universes = sorted({(b["snapshot_id"], b["symbols"], b["symbols"] + len(b["skipped_symbols"])) for b in identity["books"]}, reverse=True)
    universe_text = ", ".join(f"{have} of {total} on snapshot {snap}" for snap, have, total in universes)
    orders = sum(b["order_check"]["key_orders_checked"] for b in books.values())
    return [
        "**Nothing pre-registered was changed; three descriptive tables were added.** No key, threshold, horizon, book, "
        "pre-registered statistic or decision rule was added, dropped or changed after results were seen, and the verdict uses only "
        "the pre-registered statistics. Three tables go beyond the statistics the pre-registration lists (top-2 lift, rank IC, rank "
        "buckets, random-2 band): the one-position \"kept\" subset (K1 top-2 lift, bootstrap p and rank IC, 8 cells), the comparison "
        "with the two alphabetically first candidates, and the top-2 lift by calendar year. They were in the script from its first "
        "run, are descriptive and carry no verdict. Their p-values are unadjusted: the kept-subset IS cell on "
        "trend_continuation.medium is one of 8 such cells and is not a finding. The other points below are choices the "
        "pre-registration left open; each was fixed in the script before any outcome was computed. History of this file: after the "
        "first complete run, three descriptive counts were added to the report (sessions with a tied key, the most frequent top-2 "
        "symbol, and where the alphabetical pick sits among the random picks) and its wording was edited. The whole pipeline was "
        "then run again from that script and reproduced every number of the first run exactly (candidate tables and random-2 bands "
        "byte for byte; `summary.json` differs only in the added counts, the timestamps and the script hash). After review the "
        "report text and one git check were changed and only the report stage was run again (see \"Review repairs\" below); no "
        "number changed.",
        "**Candidates.** The signal table is R3-C's `build_signal_table`, rebuilt from the database: every long signal of the version's "
        f"rule on symbols with complete bars ({universe_text}), signal sessions 2016-12-28 to 2025-09-04. Dates, symbols, bars, signals, "
        "keys and dividend rows are identical to the table R3-C saved and used for its grid.",
        f"**Fill validity.** The funded replay's own two checks at the next open, at base costs: the fill (open plus {pen_bps:.1f} bps, "
        f"rounded up to the cent) must be above the stop, and (target − fill) ÷ (fill − stop) must be at least {min_rr}. Because the "
        "target is two planned risks above the signal close, the second check refuses a signal whose open gaps up by more than about "
        "0.2 planned risks. Refusals for size (risk budget, symbol, sector, gross, open-risk, cash, volume, daily cap) depend on the "
        "account and are not part of the isolated outcome; the pre-registration counts a signal \"whether or not a funded account "
        "could have taken it\".",
        f"**Outcome.** (exit fill − entry fill) ÷ (signal-day close − stop). Fills carry the base cost of {pen_bps:.1f} bps a side and are "
        "rounded to the cent exactly as the replay rounds them (buys up, sells down); base costs carry no commission. Dividends are "
        "not part of the outcome. The bars are split-adjusted only, so an ex-dividend drop counts against the holder here, as it "
        "does in the replay's per-share result; the replay credits cash dividends to the account separately, and only for the "
        "symbols that have dividend rows (22 of 147 on snapshot 11, 22 of 23 on snapshot 3; R3-C results, point 17).",
        "**Exits.** The funded replay's rules, in its order: from the session after entry, an open at or below the stop exits at that "
        "open; then low at or below the stop exits at the stop; then high at or above the target exits at the target; then the time "
        "stop exits at the close of the 40th session after entry (10th for trend_continuation.short); then the last session of the "
        "data exits at its close. These differ slightly from the R-engine used for promotion (which fills a gap through the target "
        "at the open, refuses nothing at the open and measures risk from the fill).",
        f"**IS and OOS, and the two period ends.** A candidate belongs to the period of its entry session. An IS-entered candidate "
        f"runs to its own exit even when that falls after 2022-02-10 ({tot_after} candidates across the four books; "
        f"{sc['IS']['exit_after_is_end']} on trend_continuation.medium), so its outcome is the rule's, not the replay window's. "
        f"A candidate still open on 2025-09-05 is closed at that session's close, as the replay does, because no later bar may be "
        f"loaded ({tot_end} candidates across the four books; {sc['OOS']['open_at_window_end']} on trend_continuation.medium). They are "
        "kept in the statistics.",
        "**Identity check.** Run on R3-C's local replay and, in the same pass, on a fresh library `run_funded_replay` of each cell "
        "(identical). Trades the IS replay liquidated at 2022-02-10 are compared with the isolated outcome on that horizon (see the "
        "check above); all others with the candidate table itself.",
        "**Sessions with at least 3 candidates.** Counted on candidates that have an outcome; a refused signal does not count "
        "towards the 3. Which signals are refused is known only at the next open, which is also when the replay decides. Counting "
        "sessions by signals instead would add only sessions with one or two outcomes, where the top two are all the candidates and "
        "the lift is exactly zero; that reading could shrink the mean lift towards zero but could not turn it positive.",
        "**Key order and ties.** R3-C's order: highest key first; ties broken by symbol, alphabetical; a missing key ranks last, in "
        f"symbol order. This file's order was checked against R3-C's own order function on all {orders:,} session-and-key orders. "
        f"{tied} qualifying sessions hold two candidates with the same finite key value (all books and keys), so the tie rule matters "
        "only where K1 is missing. "
        + (
            f"K1 needs 63 earlier sessions, so on the first {md['sessions_with_missing_key']} qualifying sessions of "
            f"trend_continuation.medium ({md['first']} to {md['last']}, all in IS) every candidate's K1 is missing and the \"K1 order\" is the "
            f"symbol order. They are kept, because the pre-registration says every session with at least 3 candidates. Leaving them out "
            f"would give an IS top-2 lift of {_n(md['top2_lift_excluding_them'], 4)} R and an IS rank IC of {_n(md['rank_ic_excluding_them'], 4)} "
            f"(with them: {_n(primary['stats']['K1']['IS']['top2_lift'], 4)} R and {_n(primary['stats']['K1']['IS']['rank_ic'], 4)}); this line is "
            "disclosure, not a study statistic, and OOS is not affected."
            if md
            else "No qualifying session of trend_continuation.medium has a missing K1."
        ),
        f"**No look-ahead in the keys.** R3-C's assertions and poison test ran again inside `build_signal_table`. In addition all "
        f"{keys_checked:,} keys were recomputed three ways and matched: from prefixes that end on the signal session; with every bar "
        "after the signal session set to NaN; and from the formulas written out on raw arrays (K1 = close ÷ close 63 sessions earlier "
        "− 1, minus the same for SPY; K2 = signal-day volume ÷ mean of the 19 sessions before it; K3 = (close − stop) ÷ close).",
        "**Top-2 lift.** Per session: mean outcome of the first two candidates in key order minus the mean outcome of all that "
        "session's candidates (the two included). The statistic is the plain mean over sessions, each session weighted equally.",
        f"**Rank IC.** Spearman: the correlation between key rank (from the order above) and outcome rank, tied outcomes sharing their "
        f"average rank; mean over sessions. A session in which every outcome is identical has no correlation and would be left out of "
        f"the IC mean ({und} such sessions).",
        "**Terciles.** The candidate in position r of n in key order (r = 0 is the highest key) goes to bucket floor(3 × (r + 0.5) ÷ n). "
        "With 3 candidates that is one each; with 4 it is 1 / 2 / 1; with 5 it is 2 / 1 / 2. The table pools all candidates of a "
        "bucket over sessions, so busy sessions weigh more; that is why the tercile means do not average to the day's-mean column, "
        "which weighs every session equally.",
        f"**Random-2 band.** Ranking i (i = 0..{N_RANDOM - 1}) gives each (session, symbol) one uniform priority from "
        f"`numpy.random.default_rng({SEED0} + i)` on the full calendar × sorted-symbols grid, read on the entry session's row, lowest "
        "first: the construction of R3-C's random orders, so rankings 0 to 39 are R3-C's 40 orders (checked against R3-C's order "
        "function). Percentiles use numpy's linear interpolation; \"above\" is strict. One set of 1,000 rankings serves all three keys "
        "and both periods.",
        f"**Bootstrap.** Blocks are the calendar months (of the signal session) that hold at least one qualifying session of the "
        f"period: {primary['stats']['K1']['IS']['months']} in IS and {primary['stats']['K1']['OOS']['months']} in OOS for "
        f"trend_continuation.medium (the rule is gated off in risk-off months, so not every month has one). Each of the {N_BOOT:,} "
        f"resamples draws that many months with replacement (`numpy.random.default_rng({SEED0})`) and takes the mean over the sessions "
        "drawn. The null is the resampled mean minus the observed mean; p is the share of null draws at or above the observed mean, "
        "with the usual +1 correction. This is the convention of R3's entry-execution study.",
        "**Non-overlapping candidates (descriptive).** Per symbol in date order, a signal is \"kept\" when the symbol would not be "
        "held at that close by an account that takes every signal it sees: its signal session is on or after the exit session of the "
        "last kept candidate. The second count in that table uses the stricter reading (inside the holding window of any earlier "
        "candidate, kept or not). A refused signal opens no window.",
        "**Bars and dividends.** Bars come through R3-C's `load_book` (`funded_replay_report._load`, source `massive` only, "
        "quality-gated), not `PriceSeries.load`; the last bar loaded is 2025-09-05. The identity-check replays are R3-C's and need "
        "its dividend rows, so they inherit point 19 of the R3-C results: the library dividend loader reads split rows with no date "
        "bound for the 5 symbols that have a later split. No price after 2025-09-05 is read, and no dividend or split enters a "
        "candidate outcome.",
        "**One hypothesis.** Only trend_continuation.medium / K1 carries a verdict. K2, K3 and the other three books are shown with "
        "the same tables. On the 23-symbol snapshot-3 books the same few names fill the top two again and again, and for "
        "relative_strength.medium K1 is the quantity the entry rule already thresholds.",
        "**Timing.** Both complete runs of the study finished by 12:10 UTC on 2026-11-10, inside the round's 19:00 UTC cut-off. The "
        "verification script was started at 12:10 UTC. The host then appears to have been suspended: the script finished at 22:59 UTC "
        "having used 57 seconds of processor time in 10 hours 49 minutes, and how much of that fell after the host resumed is not "
        "known. So the verification, which only compares, completed after the cut-off; no study number depends on it. No study "
        "computation was started after the cut-off. After it came file comparisons, the reviewers' own checks, and the report-only "
        "run described in the next point.",
        "**Review repairs.** After adversarial review, and after the cut-off, the script was changed in two ways and its report stage "
        "alone was run again (23:11 UTC); that stage reads `summary.json` and `identity.json`, writes this file and computes no "
        "statistic. (a) The check that the imported R3-C script equals the committed blob now fails closed when git is unavailable; "
        "in the recorded run git worked and the blobs were equal, so the recorded flag is unaffected. (b) Report text: the Answer "
        "counts the four pre-registered conditions (the script records them as six flags and the first report said \"0 of the 6\"); "
        "the sentence \"the rule has an edge\" was replaced by a plain description; the added descriptive tables are declared in "
        "point 1 and next to the kept-subset number; and the hand edits made to this file after the second run (the section "
        "\"Independent verification\", the last sentences of \"Outcome\" and \"Sessions with at least 3 candidates\", "
        "\"Timing\") now come from the script, so this file is again what the script writes. The script as it ran and the "
        "hand-edited file are kept beside the raw outputs under `as_run/`.",
    ]


def render(out: Path) -> str:
    identity = _identity(out)
    summary = json.loads((out / "summary.json").read_text())
    books = summary["books"]
    dec = summary["decision"]
    primary = books[PRIMARY_BOOK]
    ps = primary["stats"][PRIMARY_KEY]
    pband = primary["random2_band"]
    v = dec["values"]
    c = dec["conditions"]
    confirmed = dec["confirmed"]
    L: list[str] = []
    add = L.append

    add("# Results — R4-K: does relative-strength ranking pick the better same-day candidates? (2026-11-10)")
    add("")
    add(
        f"Pre-registration: `{PREREG}` (commit 1b8cc3a, written before any run of this study). Run on a private read-only copy of the "
        "operating database; development window only (bars end 2025-09-05). Descriptive research: no sealed look, no "
        "operating-database write, no change to any frozen study, risk limit or approved version. One hypothesis was pre-registered "
        "(trend_continuation.medium_swing, key K1); everything else is a control or a description."
    )
    add("")
    add(
        "Outcomes are in units of planned risk, written R: one R is the distance from the signal-day close to the signal's stop. IS "
        "means entered on or before 2022-02-10, OOS after it; nothing is fitted, so both are stretches of already-observed "
        "development data."
    )
    add("")
    add("## Answer")
    add("")
    for para in answer_paragraphs(summary):
        add(para)
        add("")

    add("## The pre-registered rule, applied mechanically")
    add("")
    add("trend_continuation.medium_swing on snapshot 11, key K1 (63-session return minus SPY's), signal sessions with at least 3 candidates.")
    add("")
    add("| Condition (all must hold) | IS | OOS | Holds |")
    add("|---|---:|---:|---|")
    add(
        f"| Top-2 lift positive in IS and in OOS | {_n(v['top2_lift_is'], 4)} R | {_n(v['top2_lift_oos'], 4)} R | "
        f"{_yn(c['top2_lift_positive_is'] and c['top2_lift_positive_oos'])} |"
    )
    add(f"| OOS one-sided bootstrap p below 0.05 | (IS p {_p(ps['IS']['top2_lift_p'])}, not in the rule) | {_p(v['oos_one_sided_p'])} | {_yn(c['oos_one_sided_p_below_0.05'])} |")
    add(
        f"| Within-day rank IC positive in IS and in OOS | {_n(v['rank_ic_is'], 4)} | {_n(v['rank_ic_oos'], 4)} | "
        f"{_yn(c['rank_ic_positive_is'] and c['rank_ic_positive_oos'])} |"
    )
    add(
        f"| OOS top-2 lift above the 95th percentile of the random-2 band | (IS band p95 {_n(pband['IS']['p95'], 4)} R, not in the rule) | "
        f"{_n(v['top2_lift_oos'], 4)} R against {_n(v['random2_p95_oos'], 4)} R | {_yn(c['oos_top2_lift_above_random2_p95'])} |"
    )
    add("")
    add(
        f"**Verdict: K1 is {'CONFIRMED' if confirmed else 'NOT CONFIRMED'} as an admission ranker for trend_continuation.medium.**"
        + (
            ""
            if confirmed
            else " As pre-registered, the R3-C candidate (K1 ordering on the operating caps) is then read as admission luck."
        )
    )
    add("")

    add("## Reading the result")
    add("")
    for point in reading_points(summary):
        add(f"- {point}")
    add("")

    add("## What was run")
    add("")
    tot_signals = sum(b["scope"]["signals"] for b in books.values())
    cells_all = [cell for b in identity["books"] for cell in b["identity"]["cells"]]
    add(
        f"- Four candidate tables, {tot_signals:,} signals in all: every long signal each approved rule produces on signal sessions "
        "2016-12-28 to 2025-09-04 on its approved snapshot (R3-C's signal table, rebuilt from the database and identical to the one R3-C saved)."
    )
    add("- Each signal's isolated outcome: taken alone at the next open and closed by the funded replay's own exits at base costs. No account, cash limit, cap or other position enters it.")
    add(f"- Identity check first: {sum(1 for cell in cells_all if cell['passed'])} of {len(cells_all)} replay cells pass (below).")
    add(f"- Statistics exactly as pre-registered: top-2 lift, within-day Spearman rank IC, tercile buckets, {N_RANDOM:,} random two-a-day rankings and a {N_BOOT:,}-resample calendar-month block bootstrap, IS and OOS separately, for K1, K2 and K3 on all four books. No other key, threshold, horizon or book was run. Three descriptive tables beyond those statistics were added (one-position subset, alphabetical comparison, lift by year); see point 1 under Deviations and clarifications.")
    add(f"- {summary['parameters']['workers']} worker processes; prepare {identity['seconds']:.0f} s, analysis {summary['seconds']:.0f} s.")
    add("")

    add("## Identity check (R3-C alphabetical order, outright rejection, operating caps, base costs)")
    add("")
    add(
        "Every admitted trade of the replay is compared with the isolated outcome of the same symbol and signal session: per-share "
        "result divided by planned risk, tolerance 1e-9 R, plus entry price, exit price, exit session and exit reason. The replay is "
        "R3-C's local loop, checked here again against a fresh library `run_funded_replay` (fills, marks, decisions, costs and "
        "dividend events identical) and against the fill count and final equity R3-C recorded."
    )
    add("")
    add("| Book | Period | Fills / final equity $ | Same as R3-C's record | Same as a fresh library replay | Trades compared | Liquidated at the period end | Largest difference (R) | Refusals at the open checked | Mismatches | Passed |")
    add("|---|---|---:|---|---|---:|---:|---:|---:|---:|---|")
    for b in identity["books"]:
        for cell in b["identity"]["cells"]:
            add(
                f"| {BOOK_LABELS[b['strategy']]} | {cell['period']} | {cell['fills']} / {cell['final_equity_usd']} | "
                f"{_yn(cell['matches_r3c_record'])} | {_yn(cell['library_identical'])} | {cell['trades_compared']} | "
                f"{cell['period_end_trades']} | {cell['max_abs_diff_r']:.1e} | {sum(cell['refusals_at_open_checked'].values())} | "
                f"{cell['mismatches']} | {_yn(cell['passed'])} |"
            )
    total_trades = sum(cell["trades_compared"] for cell in cells_all)
    total_end = sum(cell["period_end_trades"] for cell in cells_all)
    worst = max(cell["max_abs_diff_r"] for cell in cells_all)
    is_end = sum(cell["period_end_trades"] for cell in cells_all if cell["period"] == "IS")
    is_end_diff = sum(cell["period_end_trades_differing_from_table"] for cell in cells_all if cell["period"] == "IS")
    assert is_end_diff == is_end  # a window-end exit is never the rule's own exit
    add("")
    add(
        f"{total_trades:,} admitted trades compared; largest difference {worst:.1e} R. {total_end} of them were still open when their "
        f"replay ended and were liquidated at its last close. The {total_end - is_end} at the end of OOS (2025-09-05) sit at the end of the "
        f"data for the candidate table too, so they match it directly. The {is_end} at the end of the IS replay (2022-02-10) were cut "
        "short by the replay window, not by the rule: each matches the isolated outcome computed on that same horizon. The candidate "
        f"table itself lets an IS-entered candidate run to its own later exit, so its outcome for those {is_end} is a different one "
        "(see \"IS and OOS, and the two period ends\" under Deviations and clarifications). Every other trade matches the candidate "
        "table itself. Every refusal the replay made at the open (crossed stop, reward-to-risk) carries the same flag in the candidate table."
    )
    add("")

    add("## Independent verification")
    add("")
    add(
        "`scripts/r4/candidate_ranking_verify.py` imports neither the study script nor R3-C, and found no difference (`verify.log`). "
        "It was started straight after the second run and, because the host was suspended, completed after the round's cut-off "
        "(see \"Timing\" under Deviations and clarifications); no study number depends on it."
    )
    add("")
    add(
        f"- It read the bars straight from the database and recomputed the three keys and the isolated outcome of all {tot_signals:,} "
        "signals, finding the exit by array search instead of a session loop. Largest difference 0 on every key and every outcome; "
        "every refusal, exit session, exit reason and fill price is the same."
    )
    add(
        "- With pandas it recomputed the top-2 lift, the rank IC and the alphabetical comparison for every book, key and period, on "
        "all candidates and on the kept subset, the terciles and by-year lifts on all candidates, and the one-position flags of every signal."
    )
    add(
        "- It reproduced the twelve bootstrap p-values of trend_continuation.medium (lift and IC, three keys, two periods) by "
        "resampling month lists one resample at a time, random rankings 0, 500 and 999 of each book with a per-session sort, the "
        "95th percentile of each random-2 band, and the decision."
    )
    add("")

    add("## Candidates")
    add("")
    add("| Book | Period | Signals | Refused at the open: crossed stop / reward-to-risk | Candidates with an outcome | Mean outcome (R) | Sessions with 3 or more | Candidates on those sessions (share) | Most in one session | Still open at the window end |")
    add("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for name, b in books.items():
        for period in PERIODS:
            s = b["scope"]["by_period"][period]
            ref = s["refused_at_open"]
            share = s["share_of_candidates_on_sessions_with_min"]
            add(
                f"| {BOOK_LABELS[name]} | {period} | {s['signals']} | {ref.get('invalid_or_crossed_stop', 0)} / {ref.get('reward_risk', 0)} | "
                f"{s['candidates_with_outcome']} | {_n(s['mean_outcome_all_candidates'])} | {s['sessions_with_min_candidates']} | "
                f"{s['candidates_on_sessions_with_min']} ({'n/a' if share is None else f'{share * 100:.1f}%'}) | "
                f"{s['max_candidates_in_a_session']} | {s['open_at_window_end']} |"
            )
    add("")
    add(
        "A refused signal is one the funded replay would not fill at the next open: the open is at or below the stop, or the "
        "target is less than 1.5 times the remaining risk away. It is \"not a candidate outcome\" and is left out of every statistic."
    )
    add("")

    add("## Primary and control statistics: trend_continuation.medium_swing (snapshot 11)")
    add("")
    add("K1 is the pre-registered hypothesis. K2 (volume surge) and K3 (stop distance) are controls and carry no verdict.")
    add("")
    L.extend(STATS_HEADER)
    L.extend(_stats_rows(primary, KEYS))
    add("")
    add(
        "How to read the columns. *Top-2 lift* is the mean over sessions of (mean outcome of the two highest-key candidates − mean "
        "outcome of all that session's candidates). *Bootstrap p* is one-sided, from resampling calendar months. *Random-2* is the "
        "same lift for 1,000 random two-a-day picks: it shows how far a pick with no information moves by luck. *Rank IC* is the "
        "within-day Spearman correlation between key and outcome, averaged over sessions. *Terciles* pool every candidate by its "
        "within-day third of the key."
    )
    add("")

    add("## The other three approved books (descriptive, no verdict)")
    add("")
    for name, b in books.items():
        if name == PRIMARY_BOOK:
            continue
        add(f"**{BOOK_LABELS[name]} — {name}**")
        add("")
        L.extend(STATS_HEADER)
        L.extend(_stats_rows(b, KEYS))
        add("")

    add("## Plain descriptive facts (no verdict)")
    add("")
    add("### Signal sessions by number of candidates")
    add("")
    add("| Book | Period | Signal sessions | " + " | ".join(COUNT_BINS) + " |")
    add("|---|---|---:|" + "---:|" * len(COUNT_BINS))
    for name, b in books.items():
        for period in PERIODS:
            s = b["scope"]["by_period"][period]
            add(
                f"| {BOOK_LABELS[name]} | {period} | {s['signal_sessions_in_period']} | "
                + " | ".join(str(s["sessions_by_candidate_count"][x]) for x in COUNT_BINS)
                + " |"
            )
    add("")
    add("Columns are the number of candidates with an outcome on a signal session. The share of candidates that sit on sessions with 3 or more is in the Candidates table above.")
    add("")

    add("### Top-2 lift by calendar year of the signal session (K1)")
    add("")
    years = sorted({y for b in books.values() for p in PERIODS for y in b["stats"]["K1"][p]["by_year"]})
    boundary_year = str(ca.IS_END.year)
    add("| Book | " + " | ".join(years) + " |")
    add("|---|" + "---:|" * len(years))
    for name, b in books.items():
        cells = []
        for y in years:
            parts = []
            for period in PERIODS:
                e = b["stats"]["K1"][period]["by_year"].get(y)
                if y == boundary_year:
                    parts.append(f"{period} {_n(e['top2_lift'])} ({e['sessions']})" if e else f"{period} none")
                elif e:
                    parts.append(f"{_n(e['top2_lift'])} ({e['sessions']})")
            cells.append("; ".join(parts) if parts else "none")
        add(f"| {BOOK_LABELS[name]} | " + " | ".join(cells) + " |")
    add("")
    add(
        f"Lift in R, with the number of sessions in brackets. {boundary_year} holds both periods (IS is entered on or before 2022-02-10); "
        "\"none\" means no session with 3 or more candidates, which is what a risk-off regime gate produces."
    )
    add("")

    add("### Against the two alphabetically first candidates (what the library order admits)")
    add("")
    add("| Book | Period | Sessions | Day's mean, all candidates (R) | Mean of the alphabetical two (R) | Alphabetical two − day's mean (R) | K1 top 2 − alphabetical two (R) | K2 top 2 − alphabetical two (R) | K3 top 2 − alphabetical two (R) |")
    add("|---|---|---:|---:|---:|---:|---:|---:|---:|")
    for name, b in books.items():
        for period in PERIODS:
            a = b["alphabetical_two"][period]
            s = b["stats"]
            add(
                f"| {BOOK_LABELS[name]} | {period} | {a['sessions']} | {_n(s['K1'][period]['mean_of_session_means'])} | "
                f"{_n(a['alphabetical_two_mean'])} | {_n(a['alphabetical_two_lift_vs_all'])} | "
                + " | ".join(_n(s[k][period]["lift_vs_alphabetical_two"]) for k in KEYS)
                + " |"
            )
    add("")
    add("Here the day's mean is replaced by the mean of the two candidates the current alphabetical order would offer first. Means over the same sessions.")
    add("")

    add("### One position per symbol: signals inside an earlier candidate's holding window")
    add("")
    add(
        "The library holds at most one position per symbol, so an account does not see a signal while it holds that symbol. The "
        "isolated table deliberately includes every signal. The table counts the signals that fall inside the holding window of an "
        "earlier candidate, and repeats the primary statistic on the rest."
    )
    add("")
    add("| Book | Period | Signals | Inside the window of an earlier candidate that a one-position account would hold | Inside the window of any earlier candidate | Candidates kept | Sessions with 3 or more kept | Top-2 lift K1, kept only (R) | Bootstrap p | Rank IC K1, kept only | Top-2 lift K1, all candidates (R) |")
    add("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for name, b in books.items():
        for period in PERIODS:
            s = b["scope"]["by_period"][period]
            no = b["non_overlap"]["stats"]["K1"][period]
            kept = s["candidates_with_outcome"] - s["candidates_inside_held_window"]
            add(
                f"| {BOOK_LABELS[name]} | {period} | {s['signals']} | {s['signals_inside_held_window']} "
                f"({s['signals_inside_held_window'] / s['signals'] * 100:.1f}%) | {s['signals_inside_any_earlier_window']} "
                f"({s['signals_inside_any_earlier_window'] / s['signals'] * 100:.1f}%) | {kept} | {no['sessions']} | "
                f"{_n(no['top2_lift'], 4)} | {_p(no['top2_lift_p'])} | {_n(no['rank_ic'], 4)} | {_n(b['stats']['K1'][period]['top2_lift'], 4)} |"
            )
    add("")
    add(
        "\"Kept\" is descriptive and carries no verdict: the candidates a one-position-per-symbol account that takes every signal it "
        "sees would be offered (see \"Non-overlapping candidates\" under Deviations and clarifications). The pre-registered statistic "
        "is the one on all candidates."
    )
    add("")

    add("## Expectations stated in advance, against the outcome")
    add("")
    add("| Expectation in the pre-registration | Outcome |")
    add("|---|---|")
    for left, right in expectation_rows(summary):
        add(f"| {left} | {right} |")
    add("")

    add("## Deviations and clarifications")
    add("")
    for i, text in enumerate(clarifications(summary, identity), 1):
        add(f"{i}. {text}")
    add("")

    add("## What this does and does not license")
    add("")
    add(
        "As pre-registered: the data are the same development sessions R3-C used, so a pass would be a robustness result on an existing "
        "candidate, not independent confirmation; only prospective evidence is clean. "
        + (
            "A pass justifies building ranked admission behind an off-by-default setting and pre-registering a prospective comparison "
            "for the next study generation."
            if confirmed
            else "The rule did not pass, so nothing here supports building ranked admission on K1 for this book."
        )
        + " Nothing here changes the operating scan, ledger, risk limits or any frozen study."
    )
    add("")

    add("## Reproduce")
    add("")
    add("```sh")
    add("cd <scratch>/r3            # a directory with no .env")
    add("PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=<worktree>/src:<worktree>/scripts MARKET_DATA_PROVIDER=massive \\")
    add("SIGNALFORGE_DATA_DIR=<scratch>/r3/db \\")
    add('DATABASE_URL="sqlite+pysqlite:///file:<scratch>/r3/db/signalforge.sqlite?mode=ro&uri=true" \\')
    add("<venv>/bin/python <worktree>/scripts/r4/candidate_ranking.py all        # prepare, analyze, report")
    add("<venv>/bin/python <worktree>/scripts/r4/candidate_ranking_verify.py     # independent recomputation from the saved tables and the database")
    add("```")
    add("")
    add(
        "Raw outputs (not committed), under `<scratch>/r3/out/r4-ranking/`: `identity.json`, `candidates_<book>.csv` (one row per "
        "signal), `sessions_<book>.csv` and `sessions_nonoverlap_<book>.csv` (one row per session with 3 or more candidates), "
        f"`random_band_<book>.csv` ({N_RANDOM:,} rows), `summary.json`, `verify.log` and the stage logs. Script SHA-256 at the run: "
        f"`{summary['script_sha256'][:16]}…`; R3-C script imported unmodified (SHA-256 `{identity['r3c_script_sha256'][:16]}…`, "
        f"{'the same blob as' if identity['r3c_script_matches_commit'] else 'NOT the same blob as'} the committed file)."
        + (
            ""
            if _sha256(HERE) == summary["script_sha256"]
            else f" The script was changed after that run (see \"Review repairs\"); it now has SHA-256 `{_sha256(HERE)[:16]}…`, and "
            "the script as it ran is kept as `as_run/candidate_ranking.py` beside the raw outputs."
        )
    )
    add("")
    add("Research signal only — no order was placed.")
    return "\n".join(L) + "\n"


def stage_report(out: Path) -> int:
    text = render(out)
    (out / "results.md").write_text(text)
    RESULTS.write_text(text)
    print(f"wrote {RESULTS}", flush=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("stage", choices=["prepare", "analyze", "report", "all"])
    p.add_argument("--db", type=Path, default=None, help="scratch database (read-only)")
    p.add_argument("--out", type=Path, default=None, help="raw output folder")
    p.add_argument("--workers", type=int, default=MAX_WORKERS)
    a = p.parse_args(argv)
    if not 1 <= a.workers <= MAX_WORKERS:
        p.error(f"CPU budget for this study is at most {MAX_WORKERS} worker processes")
    a.db = a.db or ca.default_db()
    a.out = a.out or default_out()
    ca._guard_paths(a.db, a.out, RESULTS)  # noqa: SLF001 - R3-C's operating-path guard
    a.out.mkdir(parents=True, exist_ok=True)
    books = [b for b, _, _ in ca.BOOKS]
    stages = ["prepare", "analyze", "report"] if a.stage == "all" else [a.stage]
    for stage in stages:
        print(f"== {stage} ({time.strftime('%H:%M:%S', time.gmtime())} UTC)", flush=True)
        if stage == "prepare":
            code = stage_prepare(a.out, a.db, a.workers, books)
        elif stage == "analyze":
            code = stage_analyze(a.out, a.workers, books)
        else:
            code = stage_report(a.out)
        if code:
            return code
    return 0


if __name__ == "__main__":
    sys.exit(main())
