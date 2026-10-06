"""Read-only rejection funnel for ONE options snapshot — counts only, pre-sealed span only.

For every (underlying, monthly cycle) signal session in the snapshot's window that
falls on or before the pre-sealed end, this script replays the FROZEN
``OptionsShortVertical`` v0.1.2 selection step by step and records the first
stage at which it stops:

    a_no_chain_rows             no option print on the signal session at all
    b_no_expiry_in_dte_window   the cycle's expiry is not visible, or its first
                                DTE <= 35 session falls outside [28, 45]
    q_missing                   no sourced dividend yield on the session (gate 0.g)
    e_no_print_eligible_leg     liquidity: zero print-eligible contracts on the
                                chosen side/expiry (D5 §2.4 volume/transactions)
    c_no_short_in_delta_band    no OTM print-eligible strike with |delta| in band
    d_no_wing_at_exact_width    no print-eligible strike at EXACTLY K_short -/+ $8
    f_credit_floor              adverse net credit / (width x 100) < 0.150
    g_op1_risk_fit              hard max loss > the OP-1 per-structure cap ($900)
    selectable                  every stage cleared — a structure WOULD be entered

The stage order is the strategy's own (``short_vertical.py``), so the funnel
measures what the frozen code does, not a re-ordering of it.  Two deliberate
differences from the engine are disclosed rather than hidden:

* the engine goes flat between cycles and skips a signal session while a prior
  structure is still open; this funnel evaluates EVERY cycle's signal session,
  so its counts are an upper bound on attempts (D5 §4.2: at 35 DTE the previous
  cycle's time stop precedes the next signal session, so the bound is tight);
* stage (d) is decomposed with two counterfactual counts that the strategy
  never computes: whether the exact wing strike is STORED but not print-eligible
  (a liquidity miss) or NOT STORED at all (never collected by the ladder), and the
  histogram of the nearest realised widths.

**Nothing priced leaves this script.**  Prices, IVs, deltas and credits are
computed in memory because the frozen selection needs them, exactly as the
dry-run evaluation computes them, and only COUNTS, strike identities and dates
are written.  No P&L, return, or per-strike volume is emitted (IO2_RUNBOOK §0,
D1 §10.2).  The database is opened with ``mode=ro``; nothing is written and no
provider is called.

Usage:
    python scripts/options_rejection_breakdown.py \
        [--db PATH] [--snapshot-key KEY] [--sealed-days 365] [--out FILE.md] [--json FILE]
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from itertools import pairwise
from pathlib import Path
from statistics import median

from signalforge.data import options_calendar
from signalforge.data.option_chain import ContractPrint, ContractRef, OptionChainSeries, Right
from signalforge.data.series import PriceSeries
from signalforge.options import blackscholes
from signalforge.research.options_strategies.short_vertical import (
    OPTIONS_PER_STRUCTURE_MAX_LOSS,
    PREREGISTERED_COST_MODEL,
    OptionsShortVertical,
    ShortVerticalParams,
)

_DEFAULT_DB = Path.home() / "signal-forge" / "data" / "signalforge.sqlite"
DEFAULT_SNAPSHOT_KEY = "options_idx3_massive_2023-09-04_2026-09-04_0ae681d590"
#: The underlying-bar label the evidence assembler defaults to
#: (``assemble_options_evidence(source="massive")``).
UNDERLYING_BAR_SOURCE = "massive"
#: ``options_corporate_actions.Q_SERIES_SOURCE`` — restated rather than imported
#: so this script never imports the adapter-adjacent module.
Q_SERIES_SOURCE = "vendor_dividends"
#: ``run_underlying`` / ``run_options_backtest`` default.
WARMUP = 50
#: ``cli.options evaluate-promotion --sealed-days`` default (D5 §5).
DEFAULT_SEALED_DAYS = 365

STAGES: tuple[str, ...] = (
    "a_no_chain_rows",
    "b_no_expiry_in_dte_window",
    "q_missing",
    "e_no_print_eligible_leg",
    "c_no_short_in_delta_band",
    "d_no_wing_at_exact_width",
    "f_credit_floor",
    "g_op1_risk_fit",
    "selectable",
)

QLookup = Callable[[str, date], float | None]


# --------------------------------------------------------------------------- #
# read-only loading (plain sqlite3, mode=ro, no ORM session)
# --------------------------------------------------------------------------- #
def open_readonly(path: Path) -> sqlite3.Connection:
    """Open ``path`` read-only.  A missing file is an error, never a new database."""
    if not path.is_file():
        raise FileNotFoundError(path)
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    con.execute("PRAGMA query_only = 1")
    return con


@dataclass(frozen=True, slots=True)
class SnapshotScope:
    snapshot_id: int
    key: str
    symbols: tuple[str, ...]
    window_start: date
    window_end: date
    option_source: str
    ingestion_run_ids: tuple[int, ...]


def load_snapshot(con: sqlite3.Connection, key: str) -> SnapshotScope:
    row = con.execute(
        "SELECT id, symbols_json, options_scope_json FROM data_snapshot WHERE key = ?", (key,)
    ).fetchone()
    if row is None:
        raise LookupError(f"no data_snapshot with key {key!r}")
    snapshot_id, symbols_json, scope_json = row
    scope = json.loads(scope_json) if scope_json else {}
    if not scope:
        raise LookupError(f"data_snapshot {key!r} carries no options_scope_json")
    option_source = str(((scope.get("option_data") or {}).get("source")) or "")
    if not option_source:
        raise LookupError(f"data_snapshot {key!r} records no option_data.source")
    window = scope["window"]
    return SnapshotScope(
        snapshot_id=int(snapshot_id),
        key=key,
        symbols=tuple(sorted(str(s).upper() for s in json.loads(symbols_json))),
        window_start=date.fromisoformat(window["start"]),
        window_end=date.fromisoformat(window["end"]),
        option_source=option_source,
        ingestion_run_ids=tuple(int(i) for i in scope.get("ingestion_run_ids", [])),
    )


def load_underlying(
    con: sqlite3.Connection, symbol: str, start: date, end: date, *, source: str
) -> PriceSeries:
    """Unadjusted closes, as ``options_evidence.UNDERLYING_ADJUSTED = False`` loads them."""
    rows = con.execute(
        "SELECT o.session_date, o.open, o.high, o.low, o.close, o.volume "
        "FROM ohlcv_daily o JOIN instrument i ON i.id = o.instrument_id "
        "WHERE i.symbol = ? AND o.source = ? AND o.session_date >= ? AND o.session_date <= ? "
        "ORDER BY o.session_date",
        (symbol.upper(), source, start.isoformat(), end.isoformat()),
    ).fetchall()
    bars = [
        (date.fromisoformat(d), float(o), float(h), float(lo), float(c), float(v or 0.0))
        for d, o, h, lo, c, v in rows
    ]
    return PriceSeries.from_bars(symbol.upper(), bars)


def load_chain(
    con: sqlite3.Connection,
    symbol: str,
    start: date,
    end: date,
    *,
    option_source: str,
    series: PriceSeries,
) -> OptionChainSeries | None:
    """The same construction as ``options_evidence.load_option_chain_series``."""
    if not len(series):
        return None
    closes = dict(zip(series.dates, series.close, strict=True))
    meta_rows = con.execute(
        "SELECT option_ticker, underlying_symbol, contract_type, strike_price, expiration_date, "
        "shares_per_contract, exercise_style FROM option_contract "
        "WHERE underlying_symbol = ? AND source = ?",
        (symbol.upper(), option_source),
    ).fetchall()
    if not meta_rows:
        return None
    meta = {r[0]: r for r in meta_rows}
    bar_rows = con.execute(
        "SELECT option_ticker, session_date, open, high, low, close, volume, vwap, transactions "
        "FROM option_aggregate_daily WHERE underlying_symbol = ? AND source = ? "
        "AND session_date >= ? AND session_date <= ? ORDER BY session_date, option_ticker",
        (symbol.upper(), option_source, start.isoformat(), end.isoformat()),
    ).fetchall()
    if not bar_rows:
        return None
    prints: dict[date, dict[str, ContractPrint]] = {}
    first_seen: dict[str, date] = {}
    for ticker, sdate, o, h, low, c, vol, vwap, txns in bar_rows:
        if ticker not in meta:
            continue
        d = date.fromisoformat(sdate)
        prints.setdefault(d, {})[ticker] = ContractPrint(
            open=float(o),
            high=float(h),
            low=float(low),
            close=float(c),
            volume=float(vol or 0.0),
            vwap=float(vwap) if vwap is not None else None,
            transactions=int(txns) if txns is not None else None,
        )
        if ticker not in first_seen or d < first_seen[ticker]:
            first_seen[ticker] = d
    contracts = [
        ContractRef(
            option_ticker=t,
            underlying_symbol=str(meta[t][1]),
            right=Right(str(meta[t][2])),
            strike=float(meta[t][3]),
            expiration=date.fromisoformat(str(meta[t][4])),
            shares_per_contract=int(meta[t][5]),
            exercise_style=str(meta[t][6]),
            first_print_session=d,
        )
        for t, d in sorted(first_seen.items())
    ]
    if not contracts:
        return None
    return OptionChainSeries.from_rows(
        symbol, contracts=contracts, underlying_closes=closes, prints=prints
    )


def load_q_lookup(
    con: sqlite3.Connection, symbols: Sequence[str], *, source: str = Q_SERIES_SOURCE
) -> QLookup:
    """Exact-session match, ``None`` otherwise — ``build_q_lookup``'s contract."""
    table: dict[tuple[str, date], float] = {}
    for sym in symbols:
        for s_date, q in con.execute(
            "SELECT session_date, q FROM dividend_yield_daily WHERE symbol = ? AND source = ?",
            (sym.upper(), source),
        ):
            table[(sym.upper(), date.fromisoformat(s_date))] = float(q)

    def lookup(symbol: str, session_date: date) -> float | None:
        return table.get((symbol.upper(), session_date))

    return lookup


# --------------------------------------------------------------------------- #
# the funnel
# --------------------------------------------------------------------------- #
@dataclass(slots=True)
class SignalSessionRecord:
    """One (underlying, cycle) signal session — identities and counts only."""

    underlying: str
    session_date: str
    expiry: str | None
    side: str | None
    stage: str
    dte: int | None = None
    #: stage-d decomposition (strike identities, never prices)
    short_strike: float | None = None
    wing_target: float | None = None
    nearest_width: float | None = None
    exact_wing_stored: bool | None = None
    exact_wing_print_eligible: bool | None = None
    #: stage-c decomposition
    otm_print_eligible: int | None = None
    otm_with_invertible_iv: int | None = None
    #: free-text sub-reason for stages (b) and (d); identities and counts only
    note: str = ""


@dataclass(slots=True)
class UnderlyingFunnel:
    underlying: str
    chain_sessions: int
    presealed_sessions: int
    signal_sessions: int
    counts: dict[str, int] = field(default_factory=dict)
    nearest_width_histogram: dict[str, int] = field(default_factory=dict)
    d_exact_wing_stored_not_eligible: int = 0
    d_exact_wing_not_stored: int = 0
    records: list[SignalSessionRecord] = field(default_factory=list)
    skipped_reason: str | None = None


def _cycle_classification(
    chain: OptionChainSeries, t: int, today: date, p: ShortVerticalParams
) -> tuple[str, date | None, int | None]:
    """``("signal", expiry, dte)``, ``("skipped_window", expiry, dte)`` or ``("none", None, None)``.

    The arithmetic is ``OptionsShortVertical._cycle_expiry`` restated so the
    window-skip branch can be counted instead of collapsing into ``None``.
    """
    prev = chain.sessions[t - 1].session_date
    expiries = sorted(
        {
            c.expiration
            for c in chain.visible_contracts(t).values()
            if c.expiration >= today and options_calendar.is_expiry(c.expiration, monthly_only=True)
        }
    )
    for expiry in expiries:
        dte = options_calendar.calendar_dte(today, expiry)
        if dte > p.dte_target:
            continue
        if options_calendar.calendar_dte(prev, expiry) <= p.dte_target:
            continue
        if not (p.dte_window_lo <= dte <= p.dte_window_hi):
            return "skipped_window", expiry, dte
        return "signal", expiry, dte
    return "none", None, None


def _calendar_signal_sessions(
    chain: OptionChainSeries, *, window_start: date, window_end: date, p: ShortVerticalParams
) -> dict[date, date]:
    """``{session_date: expiry}`` for every monthly expiry in the window whose first
    ``DTE <= dte_target`` chain session exists — the cycles the strategy SHOULD see.
    """
    dates = chain.session_dates()
    out: dict[date, date] = {}
    for expiry in options_calendar.expiries_between(window_start, window_end, monthly_only=True):
        for i, d in enumerate(dates):
            if i < 1:
                continue
            if options_calendar.calendar_dte(d, expiry) <= p.dte_target:
                out[d] = expiry
                break
    return out


def _b_reason(
    chain: OptionChainSeries,
    head: OptionChainSeries,
    t: int,
    kind: str,
    dte: int | None,
    expected_expiry: date | None,
    p: ShortVerticalParams,
) -> str:
    """Why stage (b) stopped: a window skip, an expiry with no stored contracts at
    all, or contracts stored but not yet visible (first print after the session)."""
    if kind == "skipped_window":
        return (
            f"first DTE<={p.dte_target} session has DTE {dte}, outside "
            f"[{p.dte_window_lo}, {p.dte_window_hi}]"
        )
    if expected_expiry is None:
        return "no cycle expiry resolvable"
    stored = [c for c in chain.contracts.values() if c.expiration == expected_expiry]
    if not stored:
        return f"no contracts stored for expiry {expected_expiry.isoformat()}"
    visible = [c for c in head.visible_contracts(t).values() if c.expiration == expected_expiry]
    if not visible:
        return (
            f"{len(stored)} contracts stored for {expected_expiry.isoformat()} but none had "
            "printed by the signal session"
        )
    return "cycle expiry resolved to a different cycle"


def _bucket(width: float) -> str:
    return f"{round(width * 2) / 2:g}"


def funnel_underlying(
    chain: OptionChainSeries,
    series: PriceSeries,
    strategy: OptionsShortVertical,
    *,
    window_start: date,
    pre_sealed_end: date,
    window_end: date,
    warmup: int = WARMUP,
) -> UnderlyingFunnel:
    p = strategy.params
    n = len(chain)
    presealed = sum(1 for d in chain.session_dates() if d <= pre_sealed_end)
    out = UnderlyingFunnel(
        underlying=chain.underlying,
        chain_sessions=n,
        presealed_sessions=presealed,
        signal_sessions=0,
        counts=dict.fromkeys(STAGES, 0),
    )
    expected = _calendar_signal_sessions(
        chain, window_start=window_start, window_end=window_end, p=p
    )
    hist: Counter[str] = Counter()
    for t in range(max(warmup, 1), n - 1):
        today = chain.sessions[t].session_date
        if today > pre_sealed_end:
            break
        head = chain.head(t)
        kind, expiry, dte = _cycle_classification(head, t, today, p)
        if kind == "none" and today not in expected:
            continue  # not a signal session for any cycle
        out.signal_sessions += 1
        rec = SignalSessionRecord(
            underlying=chain.underlying,
            session_date=today.isoformat(),
            expiry=(
                (expiry or expected.get(today)).isoformat()
                if (expiry or expected.get(today))
                else None
            ),
            side=None,
            stage="",
            dte=dte,
        )
        spot = chain.sessions[t].underlying_close
        if not head.printed_tickers(t) or spot <= 0.0:
            rec.stage = "a_no_chain_rows"
        elif kind != "signal" or expiry is None:
            rec.stage = "b_no_expiry_in_dte_window"
            rec.note = _b_reason(chain, head, t, kind, dte, expected.get(today), p)
        else:
            rec.stage = _stages_c_to_g(strategy, head, series, t, today, spot, expiry, rec)
        out.counts[rec.stage] += 1
        if rec.stage == "d_no_wing_at_exact_width":
            if rec.nearest_width is not None:
                hist[_bucket(rec.nearest_width)] += 1
            if rec.exact_wing_stored:
                out.d_exact_wing_stored_not_eligible += 1
            else:
                out.d_exact_wing_not_stored += 1
        out.records.append(rec)
    out.nearest_width_histogram = dict(sorted(hist.items(), key=lambda kv: float(kv[0])))
    return out


def _stages_c_to_g(
    strategy: OptionsShortVertical,
    head: OptionChainSeries,
    series: PriceSeries,
    t: int,
    today: date,
    spot: float,
    expiry: date,
    rec: SignalSessionRecord,
) -> str:
    """Replay ``OptionsShortVertical.__call__`` from the side choice onward."""
    p = strategy.params
    right = strategy._side(series.head(t), t)
    rec.side = right.value
    q = strategy.q_lookup(head.underlying, today) if strategy.q_lookup is not None else None
    if q is None:
        return "q_missing"
    t_years = max((expiry - today).days, 0) / 365.0
    if t_years <= 0.0:
        return "b_no_expiry_in_dte_window"
    candidates = strategy._selectable(head, t, expiry, right, p)
    if not candidates:
        return "e_no_print_eligible_leg"

    # stage-c decomposition: how many OTM print-eligible strikes exist, and how
    # many of them invert to a usable IV (the strategy's own precondition).
    call = right is Right.CALL
    otm = [
        (ref, pr)
        for ref, pr in candidates
        if ((ref.strike < spot) if right is Right.PUT else (ref.strike > spot))
    ]
    invertible = 0
    for ref, pr in otm:
        sigma = blackscholes.implied_vol(
            pr.last_print, spot, ref.strike, t_years, strategy.risk_free_rate, call=call, q=q
        )
        if sigma is not None and sigma > 0.0:
            invertible += 1
    rec.otm_print_eligible = len(otm)
    rec.otm_with_invertible_iv = invertible

    short_ref, short_print = strategy._pick_short(candidates, spot, t_years, q, right, p)
    if short_ref is None or short_print is None:
        return "c_no_short_in_delta_band"
    rec.short_strike = short_ref.strike
    target = (
        short_ref.strike - p.width_usd if right is Right.PUT else short_ref.strike + p.width_usd
    )
    rec.wing_target = target

    long_ref, long_print = strategy._pick_wing(candidates, short_ref, right, p)
    width = abs(short_ref.strike - long_ref.strike) if long_ref is not None else None
    rec.nearest_width = width
    # counterfactuals on the STORED chain (print-eligible or not), identities only
    stored_same = [
        c for c in head.visible_contracts(t).values() if c.expiration == expiry and c.right is right
    ]
    rec.exact_wing_stored = any(abs(c.strike - target) <= 1e-3 for c in stored_same)
    rec.exact_wing_print_eligible = any(abs(ref.strike - target) <= 1e-3 for ref, _ in candidates)
    if long_ref is None or long_print is None or width is None or width <= 0.0:
        rec.note = "no print-eligible strike further OTM than K_short at all"
        return "d_no_wing_at_exact_width"
    if abs(width - p.width_usd) > p.width_tolerance_pct * p.width_usd + 1e-3:
        rec.note = (
            "exact wing strike not stored"
            if not rec.exact_wing_stored
            else "exact wing strike stored but not print-eligible"
        )
        return "d_no_wing_at_exact_width"

    if not strategy._credit_floor_clears(
        short_print, long_print, short_ref, long_ref, spot, today, expiry, width, p
    ):
        return "f_credit_floor"
    r_hard = (
        width * short_ref.shares_per_contract
        + PREREGISTERED_COST_MODEL.commission(2)
        + PREREGISTERED_COST_MODEL.fees(2)
    )
    if r_hard > OPTIONS_PER_STRUCTURE_MAX_LOSS:
        return "g_op1_risk_fit"
    return "selectable"


# --------------------------------------------------------------------------- #
# the stored strike grid (identities only)
# --------------------------------------------------------------------------- #
@dataclass(slots=True)
class ExpiryGrid:
    underlying: str
    expiry: str
    right: str
    n_strikes: int
    min_strike: float
    max_strike: float
    median_spacing: float | None
    spacings: dict[str, int]
    widths_nearest_8: tuple[float, ...]
    pairs_exactly_8: int
    strikes: tuple[float, ...]


def _achievable_widths(strikes: Sequence[float], *, max_width: float) -> Counter[float]:
    """Every strike-to-strike distance up to ``max_width`` present in the grid,
    with the number of strike pairs that realise it."""
    ks = sorted(set(strikes))
    widths: Counter[float] = Counter()
    for i, a in enumerate(ks):
        for b in ks[i + 1 :]:
            w = round(b - a, 3)
            if w > max_width:
                break
            widths[w] += 1
    return widths


def strike_grid(
    chain: OptionChainSeries, *, window_start: date, window_end: date, width_usd: float = 8.0
) -> list[ExpiryGrid]:
    out: list[ExpiryGrid] = []
    by_key: dict[tuple[date, Right], set[float]] = {}
    for c in chain.contracts.values():
        if window_start <= c.expiration <= window_end:
            by_key.setdefault((c.expiration, c.right), set()).add(c.strike)
    for (expiry, right), ks_set in sorted(by_key.items(), key=lambda kv: (kv[0][0], kv[0][1])):
        ks = sorted(ks_set)
        gaps = [round(b - a, 3) for a, b in pairwise(ks) if b > a]
        widths = _achievable_widths(ks, max_width=2.0 * width_usd)
        nearest = tuple(sorted(widths, key=lambda w: (abs(w - width_usd), w))[:3])
        out.append(
            ExpiryGrid(
                underlying=chain.underlying,
                expiry=expiry.isoformat(),
                right=right.value,
                n_strikes=len(ks),
                min_strike=ks[0],
                max_strike=ks[-1],
                median_spacing=median(gaps) if gaps else None,
                spacings=dict(sorted(Counter(f"{g:g}" for g in gaps).items(), key=_num_key)),
                widths_nearest_8=nearest,
                pairs_exactly_8=widths.get(round(width_usd, 3), 0),
                strikes=tuple(ks),
            )
        )
    return out


def _num_key(kv: tuple[str, int]) -> float:
    return float(kv[0])


# --------------------------------------------------------------------------- #
# rendering — counts, identities, dates
# --------------------------------------------------------------------------- #
def _pct(n: int, d: int) -> str:
    return f"{(n / d):.0%}" if d else "-"


def render_markdown(
    scope: SnapshotScope,
    *,
    pre_sealed_end: date,
    funnels: Sequence[UnderlyingFunnel],
    grids: Sequence[ExpiryGrid],
    params: ShortVerticalParams,
    db_path: Path,
) -> str:
    lines: list[str] = []
    lines.append(f"# Rejection breakdown — snapshot {scope.snapshot_id} (`{scope.key}`)")
    lines.append("")
    lines.append(
        f"Underlyings {', '.join(scope.symbols)}; window {scope.window_start} .. "
        f"{scope.window_end}; **pre-sealed span only: signal sessions on or before "
        f"{pre_sealed_end}**; option source `{scope.option_source}`; underlying bars "
        f"`{UNDERLYING_BAR_SOURCE}`; ingestion run(s) {list(scope.ingestion_run_ids)}; "
        f"database opened `mode=ro` at `{db_path}`."
    )
    lines.append("")
    lines.append(
        f"Frozen parameters replayed (v0.1.2, not changed here): short |delta| target "
        f"{params.short_delta_target} +/- {params.delta_tolerance}, cap {params.max_short_delta}; "
        f"DTE target {params.dte_target} in [{params.dte_window_lo}, {params.dte_window_hi}]; "
        f"width EXACTLY ${params.width_usd:.2f} (tolerance {params.width_tolerance_pct:.0%}); "
        f"credit floor {params.min_credit_to_width} of width at the adverse fill; print "
        f"eligibility volume >= {params.min_leg_volume}, transactions >= "
        f"{params.min_leg_transactions}; OP-1 cap ${OPTIONS_PER_STRUCTURE_MAX_LOSS:,.0f}."
    )
    lines.append("")
    lines.append("## Funnel — counts of signal sessions by the FIRST stage that stops them")
    lines.append("")
    header = "| stage | " + " | ".join(f.underlying for f in funnels) + " | total |"
    lines.append(header)
    lines.append("|---|" + "---|" * (len(funnels) + 1))
    lines.append(
        "| chain sessions (pre-sealed) | "
        + " | ".join(f"{f.presealed_sessions}" for f in funnels)
        + f" | {sum(f.presealed_sessions for f in funnels)} |"
    )
    lines.append(
        "| signal sessions evaluated | "
        + " | ".join(f"{f.signal_sessions}" for f in funnels)
        + f" | {sum(f.signal_sessions for f in funnels)} |"
    )
    for stage in STAGES:
        row = [f.counts.get(stage, 0) for f in funnels]
        lines.append(f"| {stage} | " + " | ".join(str(c) for c in row) + f" | {sum(row)} |")
    lines.append("")
    lines.append("### Stage (d) decomposition — where the exact $8 wing went")
    lines.append("")
    lines.append(
        "| underlying | d total | exact wing STORED but not print-eligible | "
        "exact wing NOT STORED | nearest realised width histogram (width: sessions) |"
    )
    lines.append("|---|---|---|---|---|")
    for f in funnels:
        h = ", ".join(f"{k}: {v}" for k, v in f.nearest_width_histogram.items()) or "-"
        lines.append(
            f"| {f.underlying} | {f.counts.get('d_no_wing_at_exact_width', 0)} | "
            f"{f.d_exact_wing_stored_not_eligible} | {f.d_exact_wing_not_stored} | {h} |"
        )
    lines.append("")
    lines.append("### Conditional pass rates (counts only)")
    lines.append("")
    lines.append(
        "| underlying | reached (c) | passed (c) | reached (d) | passed (d) | "
        "reached (f) | passed (f) | selectable |"
    )
    lines.append("|---|---|---|---|---|---|---|---|")
    for f in funnels:
        c = f.counts
        reached_c = sum(c[s] for s in STAGES[4:])
        passed_c = sum(c[s] for s in STAGES[5:])
        reached_d = passed_c
        passed_d = sum(c[s] for s in STAGES[6:])
        reached_f = passed_d
        passed_f = sum(c[s] for s in STAGES[7:])
        lines.append(
            f"| {f.underlying} | {reached_c} | {passed_c} ({_pct(passed_c, reached_c)}) | "
            f"{reached_d} | {passed_d} ({_pct(passed_d, reached_d)}) | {reached_f} | "
            f"{passed_f} ({_pct(passed_f, reached_f)}) | {c['selectable']} |"
        )
    lines.append("")
    lines.append("### Per-signal-session records (identities only)")
    lines.append("")
    lines.append(
        "| underlying | session | expiry | DTE | side | stage | K_short | wing target | "
        "nearest width | exact wing stored | exact wing eligible | OTM eligible | OTM invertible | "
        "note |"
    )
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for f in funnels:
        for r in f.records:
            lines.append(
                f"| {r.underlying} | {r.session_date} | {r.expiry or '-'} | "
                f"{'-' if r.dte is None else r.dte} | {r.side or '-'} | {r.stage} | "
                f"{'-' if r.short_strike is None else f'{r.short_strike:g}'} | "
                f"{'-' if r.wing_target is None else f'{r.wing_target:g}'} | "
                f"{'-' if r.nearest_width is None else f'{r.nearest_width:g}'} | "
                f"{'-' if r.exact_wing_stored is None else r.exact_wing_stored} | "
                f"{'-' if r.exact_wing_print_eligible is None else r.exact_wing_print_eligible} | "
                f"{'-' if r.otm_print_eligible is None else r.otm_print_eligible} | "
                f"{'-' if r.otm_with_invertible_iv is None else r.otm_with_invertible_iv} | "
                f"{r.note or '-'} |"
            )
    lines.append("")
    lines.append("## Stored strike grid per (underlying, expiry, right)")
    lines.append("")
    lines.append(
        "| underlying | expiry | right | n | min | max | median spacing | spacing histogram | "
        "widths nearest $8 | pairs exactly $8 |"
    )
    lines.append("|---|---|---|---|---|---|---|---|---|---|")
    for g in grids:
        sp = ", ".join(f"{k}: {v}" for k, v in g.spacings.items())
        lines.append(
            f"| {g.underlying} | {g.expiry} | {g.right} | {g.n_strikes} | {g.min_strike:g} | "
            f"{g.max_strike:g} | {'-' if g.median_spacing is None else f'{g.median_spacing:g}'} | "
            f"{sp} | {', '.join(f'{w:g}' for w in g.widths_nearest_8)} | {g.pairs_exactly_8} |"
        )
    lines.append("")
    lines.append("### Strikes present (identities)")
    lines.append("")
    for g in grids:
        lines.append(
            f"- {g.underlying} {g.expiry} {g.right}: " + ", ".join(f"{k:g}" for k in g.strikes)
        )
    lines.append("")
    return "\n".join(lines)


def to_json(
    scope: SnapshotScope,
    *,
    pre_sealed_end: date,
    funnels: Sequence[UnderlyingFunnel],
    grids: Sequence[ExpiryGrid],
) -> dict[str, object]:
    return {
        "snapshot": asdict(scope)
        | {
            "window_start": scope.window_start.isoformat(),
            "window_end": scope.window_end.isoformat(),
        },
        "pre_sealed_end": pre_sealed_end.isoformat(),
        "funnels": [asdict(f) for f in funnels],
        "grids": [asdict(g) for g in grids],
    }


# --------------------------------------------------------------------------- #
# driver
# --------------------------------------------------------------------------- #
def run(
    db_path: Path,
    *,
    snapshot_key: str = DEFAULT_SNAPSHOT_KEY,
    sealed_days: int = DEFAULT_SEALED_DAYS,
    warmup: int = WARMUP,
    bar_source: str = UNDERLYING_BAR_SOURCE,
    q_source: str = Q_SERIES_SOURCE,
) -> tuple[SnapshotScope, date, list[UnderlyingFunnel], list[ExpiryGrid]]:
    con = open_readonly(db_path)
    try:
        scope = load_snapshot(con, snapshot_key)
        sealed_start = scope.window_end - timedelta(days=sealed_days)
        pre_sealed_end = sealed_start - timedelta(days=1)
        if pre_sealed_end <= scope.window_start:
            raise ValueError(f"sealed_days={sealed_days} leaves no pre-sealed span")
        q_lookup = load_q_lookup(con, scope.symbols, source=q_source)
        strategy = OptionsShortVertical(q_lookup=q_lookup, q_source=q_source)
        funnels: list[UnderlyingFunnel] = []
        grids: list[ExpiryGrid] = []
        for sym in scope.symbols:
            series = load_underlying(
                con, sym, scope.window_start, scope.window_end, source=bar_source
            )
            chain = load_chain(
                con,
                sym,
                scope.window_start,
                scope.window_end,
                option_source=scope.option_source,
                series=series,
            )
            if chain is None:
                funnels.append(
                    UnderlyingFunnel(
                        underlying=sym,
                        chain_sessions=0,
                        presealed_sessions=0,
                        signal_sessions=0,
                        counts=dict.fromkeys(STAGES, 0),
                        skipped_reason="no underlying bars or no option chain rows in the window",
                    )
                )
                continue
            funnels.append(
                funnel_underlying(
                    chain,
                    series,
                    strategy,
                    window_start=scope.window_start,
                    pre_sealed_end=pre_sealed_end,
                    window_end=scope.window_end,
                    warmup=warmup,
                )
            )
            grids.extend(
                g
                for g in strike_grid(
                    chain, window_start=scope.window_start, window_end=pre_sealed_end
                )
            )
    finally:
        con.close()
    return scope, pre_sealed_end, funnels, grids


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--db", default=str(_DEFAULT_DB))
    ap.add_argument("--snapshot-key", default=DEFAULT_SNAPSHOT_KEY)
    ap.add_argument("--sealed-days", type=int, default=DEFAULT_SEALED_DAYS)
    ap.add_argument("--out", default="", help="write the markdown report here (else stdout)")
    ap.add_argument("--json", default="", help="also write the machine-readable counts here")
    args = ap.parse_args(argv)

    db_path = Path(args.db).expanduser()
    scope, pre_sealed_end, funnels, grids = run(
        db_path, snapshot_key=args.snapshot_key, sealed_days=args.sealed_days
    )
    md = render_markdown(
        scope,
        pre_sealed_end=pre_sealed_end,
        funnels=funnels,
        grids=grids,
        params=ShortVerticalParams(),
        db_path=db_path,
    )
    if args.out:
        Path(args.out).write_text(md, encoding="utf-8")
        print(f"wrote {args.out}")
    else:
        print(md)
    if args.json:
        Path(args.json).write_text(
            json.dumps(
                to_json(scope, pre_sealed_end=pre_sealed_end, funnels=funnels, grids=grids),
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )
        print(f"wrote {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
