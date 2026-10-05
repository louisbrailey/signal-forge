#!/usr/bin/env python3
"""Read-only forward paper-validation measurement for Signal Forge.

Regenerates every number in SHORT_SWING_FORWARD_2026-10-03.md. Standard library
only. The database is opened with SQLite URI ``mode=ro`` plus
``PRAGMA query_only=ON``; nothing is written to it and no application code,
provider, or CLI is invoked. Research measurement only - no order was placed.

Usage:
    python3 paper_validation_query.py [--db PATH] [--csv OUT.csv]
"""
from __future__ import annotations

import argparse
import csv
import json
import sqlite3
from collections import Counter, defaultdict
from datetime import date, timedelta

DB = "/Users/louisbrailey/signal-forge/data/signalforge.sqlite"
START = "2026-09-10"  # paper probation activation
SRC = "massive"  # approved-scope bar source
SLIP = (3.0 + 5.0 / 2.0) / 10_000.0  # ledger: slippage 3 bps + half of 5 bps spread
# Approved scopes (strategy_promotion_evaluation ids 43 and 45, passed=1).
SCOPE = {2: 3, 3: 11}  # strategy_version_id -> dataset_snapshot_id
NAME = {2: "v2 short_swing", 3: "v3 medium_swing"}
POLICY_A = {"per_trade": 0.5, "open_risk": 1.5, "symbol": 5.0}  # live effective limits
POLICY_B = {"per_trade": 1.0, "open_risk": 3.0, "symbol": 5.0}  # counterfactual only

SQL_TRADES = """
SELECT t.id trade_id, t.decision, t.created_at, t.plan_json,
       json_extract(t.signal_snapshot_json,'$.decision.note') note,
       c.id cand_id, c.strategy_version_id sv, c.scan_run_id, c.risk_dollars,
       c.entry_zone_low, c.entry_zone_high, c.time_stop_days, i.symbol, i.sector,
       p.id pos_id, p.qty, p.avg_price, p.stop_level, p.target_level,
       p.opened_at, p.closed_at, p.realized_pnl,
       f.spread_cost, f.slippage, f.commission
FROM paper_trade t
JOIN paper_account a ON a.id = t.account_id AND a.name = 'default'
JOIN candidate c ON c.id = t.candidate_id
JOIN instrument i ON i.id = c.instrument_id
LEFT JOIN paper_position p ON p.id = t.position_id
LEFT JOIN paper_order o ON o.candidate_id = c.id AND o.account_id = a.id
LEFT JOIN paper_fill f ON f.order_id = o.id
WHERE t.created_at >= ? ORDER BY t.id
"""
SQL_BARS = """
SELECT o.session_date, o.open, o.high, o.low, o.close,
       (o.is_adjusted = 1 AND o.is_simulated = 0 AND o.quality_flags = '[]') ok
FROM ohlcv_daily o JOIN instrument i ON i.id = o.instrument_id
WHERE i.symbol = ? AND o.source = ? AND o.session_date >= '2026-09-01'
ORDER BY o.session_date
"""
SQL_CANDS = """
SELECT c.id cand_id, c.strategy_version_id sv, c.scan_run_id, r.started_at,
       date(c.created_at) decided_on, i.symbol, c.direction, c.entry_zone_low,
       c.entry_zone_high, c.invalidation_level stop, c.target_level target,
       c.time_stop_days, c.risk_dollars, c.quality_gate_status status,
       c.failed_gates, t.decision,
       json_extract(t.signal_snapshot_json,'$.decision.note') note
FROM candidate c
JOIN scan_run r ON r.id = c.scan_run_id
JOIN instrument i ON i.id = c.instrument_id
LEFT JOIN paper_trade t ON t.candidate_id = c.id
WHERE r.started_at >= ? AND r.source = ?
  AND ((c.strategy_version_id = 2 AND r.dataset_snapshot_id = 3)
    OR (c.strategy_version_id = 3 AND r.dataset_snapshot_id = 11))
ORDER BY c.id
"""


def money(x: float) -> float:
    return round(x + 1e-9, 2)


class Ctx:
    def __init__(self, db: str) -> None:
        self.con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        self.con.row_factory = sqlite3.Row
        self.con.execute("PRAGMA query_only=ON")
        self._bars: dict[str, list[sqlite3.Row]] = {}
        self.asof = self.bars("SPY")[-1]["session_date"]

    def bars(self, sym: str) -> list[sqlite3.Row]:
        if sym not in self._bars:
            self._bars[sym] = self.con.execute(SQL_BARS, (sym, SRC)).fetchall()
        return self._bars[sym]

    def close_on_or_before(self, sym: str, d: str) -> tuple[str, float]:
        b = [x for x in self.bars(sym) if x["session_date"] <= d]
        return b[-1]["session_date"], b[-1]["close"]


def simulate(ctx: Ctx, sym: str, fill: float, stop: float, target: float | None,
             entered: str, ts_days: int) -> dict:
    """Ledger exit rules (paper/ledger.py mark_to_market) on stored daily bars:
    only bars AFTER the entry date; stop checked before target on the same bar;
    stop fills at min(stop, open); time stop = close of first bar on/after
    entry date + time_stop_days CALENDAR days; exit pays 5.5 bps."""
    ts = (date.fromisoformat(entered) + timedelta(days=ts_days)).isoformat()
    rps = fill - money(stop * (1 - SLIP))
    n, last, clean = 0, None, True
    for b in ctx.bars(sym):
        if b["session_date"] <= entered:
            continue
        n, last, clean = n + 1, b, clean and bool(b["ok"])
        reason, px = None, None
        if b["low"] <= stop:
            reason, px = "stop", min(stop, b["open"])
        elif target is not None and b["high"] >= target:
            reason, px = "target", target
        elif b["session_date"] >= ts:
            reason, px = "time_stop", b["close"]
        if reason:
            ex = money(px * (1 - SLIP))
            return dict(state=reason, exit_date=b["session_date"], exit_px=ex, bars=n,
                        pps=ex - fill, r=(ex - fill) / rps, rps=rps, clean=clean)
    mark = last["close"] if last else fill
    return dict(state="open" if last else "no_bars", exit_date=last["session_date"] if last else None,
                exit_px=mark, bars=n, pps=mark - fill, r=(mark - fill) / rps, rps=rps, clean=clean)


def hdr(s: str) -> None:
    print(f"\n## {s}")


def table(cols: list[str], rows: list[list]) -> None:
    print("| " + " | ".join(cols) + " |")
    print("|" + "|".join("---" for _ in cols) + "|")
    for r in rows:
        print("| " + " | ".join(str(x) for x in r) + " |")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=DB)
    ap.add_argument("--csv", default=None, help="write per-candidate hypothetical outcomes")
    a = ap.parse_args()
    ctx = Ctx(a.db)
    acct = ctx.con.execute("SELECT initial_cash, cash FROM paper_account WHERE name='default'").fetchone()
    init, cash_now = float(acct["initial_cash"]), float(acct["cash"])
    sessions = [b["session_date"] for b in ctx.bars("SPY") if b["session_date"] >= START]
    print(f"as-of bar date {ctx.asof}; sessions since {START}: {len(sessions)}; "
          f"initial cash {init:.2f}; ledger cash {cash_now:.2f}")

    trades = ctx.con.execute(SQL_TRADES, (START,)).fetchall()
    acc = [t for t in trades if t["decision"] == "ACCEPTED"]
    print("decisions:", dict(Counter((NAME[t['sv']], t['decision']) for t in trades)))

    # ---- 1. trade ledger -------------------------------------------------
    hdr("1 Trade ledger (ACCEPTED rows; table paper_trade/paper_position/paper_fill)")
    led = []
    for t in acc:
        plan = json.loads(t["plan_json"])
        rd = plan.get("risk_decision")
        fill, qty = float(t["avg_price"]), t["qty"]
        rps = fill - money(t["stop_level"] * (1 - SLIP))
        risk = float(rd["accepted_risk_dollars"]) if rd else rps * qty
        od = t["opened_at"][:10]
        if t["closed_at"]:
            xd, pnl, state = t["closed_at"][:10], float(t["realized_pnl"]), "closed(legacy)"
            xpx = fill + pnl / qty
        else:
            xd, xpx = ctx.close_on_or_before(t["symbol"], ctx.asof)
            pnl, state = (xpx - fill) * qty, "open"
        hold = len([b for b in ctx.bars(t["symbol"]) if od < b["session_date"] <= xd])
        cost = float(t["spread_cost"]) + float(t["slippage"]) + float(t["commission"])
        notional = fill * qty
        sd0, s0 = ctx.close_on_or_before("SPY", od)
        sd1, s1 = ctx.close_on_or_before("SPY", max(xd, sd0))
        spy = notional * (s1 / s0 - 1)
        led.append(dict(t=t, rd=rd, fill=fill, qty=qty, risk=risk, od=od, xd=xd, xpx=xpx, pnl=pnl,
                        state=state, hold=hold, cost=cost, notional=notional, spy=spy, rps=rps,
                        postfix=rd is not None))
    table(["trade", "ver", "sym", "entry", "fill", "qty", "exit/mark", "px", "state", "risk$", "P&L$",
           "R", "sessions", "entry cost$", "cost bps", "cost % |gross|", "SPY same-$", "post-fix"],
          [[x["t"]["trade_id"], NAME[x["t"]["sv"]][:2], x["t"]["symbol"], x["od"], f"{x['fill']:.2f}",
            x["qty"], x["xd"], f"{x['xpx']:.2f}", x["state"], f"{x['risk']:.2f}", f"{x['pnl']:+.2f}",
            f"{x['pnl'] / x['risk']:+.2f}", x["hold"], f"{x['cost']:.2f}",
            f"{1e4 * x['cost'] / x['notional']:.1f}",
            f"{100 * x['cost'] / abs(x['pnl'] + x['cost']):.1f}" if abs(x["pnl"] + x["cost"]) > 1e-9 else "n/a",
            f"{x['spy']:+.2f}", "yes" if x["postfix"] else "no"] for x in led])
    for label, sel in (("v2 since 09-10", [x for x in led if x["t"]["sv"] == 2]),
                       ("v2+v3 since 09-10", led),
                       ("v2 post-fix", [x for x in led if x["t"]["sv"] == 2 and x["postfix"]]),
                       ("v2+v3 post-fix", [x for x in led if x["postfix"]])):
        risk = sum(x["risk"] for x in sel)
        print(f"{label}: n={len(sel)} closed={sum(x['state'] != 'open' for x in sel)} "
              f"P&L={sum(x['pnl'] for x in sel):+.2f} sumR={sum(x['pnl'] / x['risk'] for x in sel):+.2f} "
              f"planned risk={risk:.2f} entry costs={sum(x['cost'] for x in sel):.2f} "
              f"SPY same-$={sum(x['spy'] for x in sel):+.2f}")

    # ---- 2. equity curve ---------------------------------------------------
    hdr("2 Equity curve (reconstructed: cash events + massive closes)")
    recon = init - sum(x["notional"] for x in led) + sum(
        x["notional"] + x["pnl"] for x in led if x["state"] != "open")
    resid = cash_now - recon
    prefix_cost = sum(x["cost"] for x in led if not x["postfix"])
    print(f"cash reconstruction {recon:.2f} vs ledger {cash_now:.2f}: residual {resid:+.2f} "
          f"(sum of pre-fix entry costs = {prefix_cost:.2f}; consistent with the legacy double-count)")
    curve, peak, mdd, mdd_day = [], init, 0.0, None
    for d in sessions:
        cash, mv = init, 0.0
        for x in led:
            if x["od"] > d:
                continue
            cash -= x["notional"] + (0 if x["postfix"] else x["cost"])
            if x["state"] != "open":
                cash += x["notional"] + x["pnl"]
            else:
                mv += x["qty"] * ctx.close_on_or_before(x["t"]["symbol"], d)[1]
        eq = cash + mv
        peak = max(peak, eq)
        if peak - eq > mdd:
            mdd, mdd_day = peak - eq, d
        spy = init * ctx.close_on_or_before("SPY", d)[1] / ctx.close_on_or_before("SPY", START)[1]
        curve.append((d, cash, mv, eq, spy))
    table(["date", "cash", "positions MV", "equity", "cum P&L", "SPY B&H $30k", "SPY P&L"],
          [[d, f"{c:.2f}", f"{m:.2f}", f"{e:.2f}", f"{e - init:+.2f}", f"{s:.2f}", f"{s - init:+.2f}"]
           for d, c, m, e, s in curve if d >= "2026-09-24" or d == START])
    mean_risk = sum(x["risk"] for x in led) / len(led)
    eq_now = curve[-1][3]
    print(f"final equity {eq_now:.2f} cum P&L {eq_now - init:+.2f} ({100 * (eq_now / init - 1):+.3f}%); "
          f"max drawdown ${mdd:.2f} on {mdd_day} = {mdd / mean_risk:.2f}R (R = mean planned risk "
          f"${mean_risk:.2f}) = {mdd / (init * 0.005):.2f} x the $150 per-trade budget")
    print(f"SPY buy-and-hold {START}->{ctx.asof}: {curve[-1][4] - init:+.2f} "
          f"({100 * (curve[-1][4] / init - 1):+.2f}%)")
    opens = [x for x in led if x["state"] == "open"]
    open_risk = sum(max(0.0, x["xpx"] - money(x["t"]["stop_level"] * (1 - SLIP))) * x["qty"] for x in opens)
    print(f"open positions {len(opens)}; open stop risk at marks ${open_risk:.2f} = "
          f"{100 * open_risk / eq_now:.2f}% of equity (cap 1.5% = ${eq_now * 0.015:.2f}; "
          f"{100 * open_risk / (eq_now * 0.015):.0f}% used); realised {sum(x['pnl'] for x in led if x['state'] != 'open'):+.2f}; "
          f"unrealised {sum(x['pnl'] for x in opens):+.2f}")

    # ---- 3. concentration ---------------------------------------------------
    hdr("3 Concentration at as-of marks")
    by = defaultdict(float)
    for x in opens:
        by[x["t"]["symbol"]] += x["qty"] * x["xpx"]
    gross = sum(by.values())
    table(["symbol", "sector (instrument.sector)", "MV $", "% equity", "vs 5% cap", "share of gross"],
          [[s, repr(next(x["t"]["sector"] for x in opens if x["t"]["symbol"] == s)), f"{v:.2f}",
            f"{100 * v / eq_now:.2f}", "OVER" if v / eq_now > 0.05 else "ok", f"{100 * v / gross:.1f}%"]
           for s, v in sorted(by.items(), key=lambda kv: -kv[1])])
    n_sector = ctx.con.execute("SELECT count(*) FROM instrument WHERE trim(sector) <> ''").fetchone()[0]
    print(f"gross {gross:.2f} = {100 * gross / eq_now:.1f}% of equity (cap 60%); cash {cash_now:.2f}; "
          f"instruments with a non-blank sector: {n_sector}")

    # ---- 5. not-simulated candidates ----------------------------------------
    hdr("5 Approved-scope candidates and hypothetical outcomes (table candidate/scan_run)")
    cands = ctx.con.execute(SQL_CANDS, (START, SRC)).fetchall()
    rows, seen = [], set()
    for c in cands:
        if c["decision"] == "ACCEPTED":
            disp = "ACCEPTED"
        elif c["decision"] == "WATCH":
            disp = "WATCH daily cap"
        elif c["decision"] == "REJECTED":
            disp = "REJECTED open position" if "open paper position" in (c["note"] or "") else "REJECTED other"
        elif c["status"] == "NO_TRADE":
            disp = "NO_TRADE quality gate"
        else:
            disp = "PASSED undecided"
        ref = (c["entry_zone_low"] + c["entry_zone_high"]) / 2
        fill = money(ref * (1 + SLIP))
        sim = simulate(ctx, c["symbol"], fill, c["stop"], c["target"], c["decided_on"], c["time_stop_days"])
        key = (c["sv"], c["symbol"], round(c["entry_zone_low"], 4), round(c["stop"], 4))
        first = key not in seen
        seen.add(key)
        shares = int(min(c["risk_dollars"] // sim["rps"], init * 0.005 // sim["rps"], init * 0.05 // fill))
        rows.append(dict(c=c, disp=disp, fill=fill, first=first, shares=shares,
                         usd=shares * sim["pps"], **sim))
    print("dispositions:", dict(Counter((NAME[r['c']['sv']], r['disp']) for r in rows)))
    print("\nPASSED but not simulated (every row):")
    table(["cand", "ver", "scan", "decided", "sym", "disposition", "fill", "stop", "target", "bars",
           "state", "exit/mark", "R", "shares@policy", "$@policy", "dup"],
          [[r["c"]["cand_id"], NAME[r["c"]["sv"]][:2], r["c"]["scan_run_id"], r["c"]["decided_on"],
            r["c"]["symbol"], r["disp"], f"{r['fill']:.2f}", f"{r['c']['stop']:.2f}",
            f"{r['c']['target']:.2f}", r["bars"], r["state"], f"{r['exit_px']:.2f}", f"{r['r']:+.2f}",
            r["shares"], f"{r['usd']:+.2f}", "" if r["first"] else "dup"]
           for r in rows if r["c"]["status"] == "PASSED" and r["disp"] != "ACCEPTED"])
    print("\nSummary (unique = first candidate per strategy/symbol/entry band/stop; later re-emissions dropped):")
    agg = defaultdict(list)
    for r in rows:
        if r["disp"] != "ACCEPTED":
            agg[(NAME[r["c"]["sv"]], r["disp"])].append(r)
            agg[("v2+v3", r["disp"])].append(r)
    out = []
    for (ver, disp), rs in sorted(agg.items()):
        u = [r for r in rs if r["first"]]
        st = Counter(r["state"] for r in u)
        out.append([ver, disp, len(rs), len(u), st["stop"], st["target"], st["time_stop"],
                    st["open"] + st["no_bars"], f"{sum(r['r'] for r in u):+.2f}",
                    f"{sum(r['r'] for r in u) / len(u):+.3f}", f"{sum(r['usd'] for r in u):+.2f}",
                    sum(not r["clean"] for r in u)])
    table(["scope", "disposition", "n rows", "n unique", "stop", "target", "time", "open/no bars",
           "sum R", "mean R", "$@policy size", "untrusted bars"], out)
    gates = Counter()
    for r in rows:
        for g in json.loads(r["c"]["failed_gates"]):
            gates[(NAME[r["c"]["sv"]], g.split(" — ")[0][:70])] += 1
    print("failed-gate counts:", dict(gates))
    if a.csv:
        with open(a.csv, "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["candidate_id", "strategy_version_id", "scan_run_id", "decided_on", "symbol",
                        "disposition", "fill", "stop", "target", "time_stop_days", "bars", "state",
                        "exit_date", "exit_or_mark", "R", "policy_shares", "policy_usd", "first_of_episode",
                        "bars_clean"])
            for r in rows:
                c = r["c"]
                w.writerow([c["cand_id"], c["sv"], c["scan_run_id"], c["decided_on"], c["symbol"], r["disp"],
                            r["fill"], c["stop"], c["target"], c["time_stop_days"], r["bars"], r["state"],
                            r["exit_date"], round(r["exit_px"], 2), round(r["r"], 4), r["shares"],
                            round(r["usd"], 2), int(r["first"]), int(r["clean"])])
        print(f"wrote {len(rows)} rows to {a.csv}")

    # ---- 6. risk utilisation and counterfactual --------------------------------
    hdr("6 Risk utilisation and sizing counterfactual (replay of acceptance-time share caps)")

    def caps(x: dict, pol: dict) -> tuple[int, str]:
        rd, t = x["rd"], x["t"]
        if rd:
            eq, orb, symb = float(rd["equity"]), float(rd["open_risk_before"]), float(rd["symbol_before"])
            cash, gross_b = float(rd["cash"]), float(rd["gross_before"])
        else:  # legacy rows carry no risk_decision: rebuild state from prior-close marks
            prior = [y for y in led if y["t"]["trade_id"] < t["trade_id"] and y["state"] == "open"]
            mk = {y["t"]["symbol"]: ctx.close_on_or_before(y["t"]["symbol"], x["od"])[1] for y in prior}
            gross_b = sum(y["qty"] * mk[y["t"]["symbol"]] for y in prior)
            cash = init - sum(
                (y["notional"] + y["cost"]) - ((y["notional"] + y["pnl"]) if y["state"] != "open" else 0)
                for y in led if y["t"]["trade_id"] < t["trade_id"])
            eq = cash + gross_b
            orb = sum(max(0.0, mk[y["t"]["symbol"]] - money(y["t"]["stop_level"] * (1 - SLIP))) * y["qty"]
                      for y in prior)
            symb = sum(y["qty"] * mk[y["t"]["symbol"]] for y in prior if y["t"]["symbol"] == t["symbol"])
        b = {"candidate_risk": (t["risk_dollars"], x["rps"]),
             "per_trade_risk": (eq * pol["per_trade"] / 100, x["rps"]),
             "open_risk": (eq * pol["open_risk"] / 100 - orb, x["rps"]),
             "cash": (cash, x["fill"]),
             "symbol": (eq * pol["symbol"] / 100 - symb, x["fill"]),
             "gross": (eq * 0.60 - gross_b, x["fill"])}
        sc = {k: int(v // u) if v > 0 else 0 for k, (v, u) in b.items()}
        n = min(sc.values())
        return n, "/".join(k for k, v in sc.items() if v == n)

    out, tot = [], {"act": 0.0, "A": 0.0, "B": 0.0}
    for x in led:
        na, ba = caps(x, POLICY_A)
        nb, bb = caps(x, POLICY_B)
        pps = x["pnl"] / x["qty"]
        eq_ref = float(x["rd"]["equity"]) if x["rd"] else init
        tot["act"] += x["pnl"]; tot["A"] += na * pps; tot["B"] += nb * pps
        out.append([x["t"]["trade_id"], x["t"]["symbol"], x["qty"], f"{100 * x['risk'] / eq_ref:.3f}%",
                    f"{100 * x['risk'] / (eq_ref * 0.005):.0f}%", f"{100 * x['notional'] / eq_ref:.2f}%",
                    na, ba, f"{na * pps:+.2f}", nb, bb, f"{nb * pps:+.2f}"])
    table(["trade", "sym", "actual sh", "risk % eq", "% of 0.5% budget", "notional % eq",
           "sh @0.5/1.5", "binding", "P&L", "sh @1.0/3.0", "binding", "P&L"], out)
    print(f"totals: actual {tot['act']:+.2f} | replay 0.5%/1.5% {tot['A']:+.2f} | "
          f"replay 1.0%/3.0% {tot['B']:+.2f}; trade count {len(led)} in all three (daily cap and "
          f"one-position-per-symbol rule are unchanged)")
    print("post-fix binding_caps as recorded:",
          [(x["t"]["symbol"], x["rd"]["binding_caps"], x["rd"]["share_caps"]) for x in led if x["rd"]])
    blocks = Counter()
    for t in trades:
        if t["decision"] != "ACCEPTED":
            blocks[(NAME[t["sv"]], t["decision"], (t["note"] or "")[:60])] += 1
    for k, v in sorted(blocks.items()):
        print(f"  blocked x{v}: {k}")
    per_day = Counter(t["created_at"][:10] for t in acc)
    print("accepted per UTC day:", dict(per_day), "| scan days with approved-scope PASSED:",
          sorted({r['c']['started_at'][:10] for r in rows if r['c']['status'] == 'PASSED'}))

    # ---- 7. caveats inputs -----------------------------------------------------
    hdr("7 Caveat inputs")
    days = sorted({r[0] for r in ctx.con.execute(
        "SELECT date(started_at) FROM scan_run WHERE started_at >= ? AND source = ? "
        "AND dataset_snapshot_id IN (3, 11)", (START, SRC))})
    print(f"approved-scope scan days: {len(days)}; sessions without one:",
          [d for d in sessions if d not in days])
    for sv in (2, 3):
        spec = json.loads(ctx.con.execute("SELECT spec_json FROM strategy_version WHERE id=?", (sv,)).fetchone()[0])
        print(NAME[sv], "exit_logic:", spec.get("exit_logic"), "| parameters:", spec.get("parameters"))
    msft = next(x for x in led if x["t"]["trade_id"] == 2)
    s = simulate(ctx, "MSFT", msft["fill"], msft["t"]["stop_level"], msft["t"]["target_level"], msft["od"], 40)
    print(f"legacy trade 2 (MSFT) under corrected chronology: {s['state']} after {s['bars']} bars, "
          f"mark {s['exit_px']:.2f}, P&L {s['pps'] * msft['qty']:+.2f} ({s['r']:+.2f}R) vs recorded {msft['pnl']:+.2f}")


if __name__ == "__main__":
    main()
