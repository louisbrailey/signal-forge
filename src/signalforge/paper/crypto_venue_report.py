"""Crypto paper books repriced at named venues — READ-ONLY report (2026-11-08).

For every daily (CRYPTO-PAPER-1) and hourly (CRYPTO-PAPER-H1) crypto paper book
this lists the closed and open trades with R as recorded and R repriced at
``coinbase_spot_intro`` and ``coinbase_cfm_intro``
(:mod:`signalforge.research.fx.venues`), plus a subtotal of the book's LONG
trades. It writes nothing, places nothing and changes no book.

The LONG subtotals are the PARENT rule's long trades, not a ``*_long`` rule's
book (CRYPTO-5 / CRYPTO-H5 have none). They are nearly the trades those rules
would take, and from 2026-11-09 these bars fall inside the ``*_long`` rules'
future sealed window, so watching them here means that window is not an unseen
holdout (see ``SEALED_NOT_BEFORE`` in :mod:`signalforge.research.fx.sealed`).

What the ledgers lack, and the approximation used
    A paper trade stores its cost-loaded entry fill ROUNDED to 4 decimals, the
    signal stop (exact), the recorded R (exact), ``costs_bps`` (2 x the per-side
    cost the replay charged) and bars held. It does not store the raw (pre-cost)
    entry open, the raw exit price, or, for an open trade, the mark price. So:

    * raw entry = stored entry fill / (1 + d x side cost);
    * the cost-loaded exit (or mark) is rebuilt from the recorded R:
      ``exit_fill = entry_fill + d x R x |entry_fill - stop|``, and the raw exit
      = exit_fill / (1 - d x side cost). At the recorded cost this reproduces the
      recorded R exactly; the only approximation is the 4-decimal rounding of
      the stored entry fill (negligible for BTC/ETH, up to ~0.005R for DOGE/ADA);
    * an open trade is repriced as if closed at its last mark at the venue's
      exit cost (the mark is the replay's ``eod`` exit at the last close).

    Venue cost per side = the harness slippage (1 bp) + the venue's half-spread
    + taker fee + per-contract fee converted at the trade's own entry/exit price.
    Funding (CFM) is charged on notional over ``bars_held + 1`` bars, default 0.
    Spot cannot short: a SHORT row's spot figure is what the fills would have
    cost, not an executable trade, and a subtotal that contains a SHORT row
    reports no figure (``None``, "n/a") for a venue that cannot short.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from signalforge.db.models import (
    CryptoHourlyPaperBook,
    CryptoHourlyPaperTrade,
    CryptoPaperBook,
    CryptoPaperTrade,
)
from signalforge.research.fx.harness import FxGates
from signalforge.research.fx.venues import (
    COINBASE_CFM_INTRO,
    COINBASE_SPOT_INTRO,
    HARNESS_DEFAULT,
    VenueCost,
    funding_cost_r,
)

REPORT_VENUES: tuple[VenueCost, ...] = (COINBASE_SPOT_INTRO, COINBASE_CFM_INTRO)
NOTICE = "READ-ONLY report of SIMULATED paper books. Nothing was written; no order was placed."
LONG_NOTE = (
    "LONG subtotals are the parent rule's LONG trades, not a *_long rule's book. They overlap "
    "the *_long rules' future sealed window (from 2026-11-09), which is therefore not an unseen "
    "holdout."
)


def reprice_r(
    *,
    pair: str,
    direction: str,
    entry_fill: float,
    stop: float,
    r_recorded: float,
    costs_bps: float,
    bars_held: int,
    bar_days: float,
    venue: VenueCost,
    slippage_bps: float | None = None,
) -> float:
    """One paper trade's R at ``venue`` (see the module docstring)."""
    d = 1 if direction == "LONG" else -1
    slip = FxGates().slippage_bps if slippage_bps is None else slippage_bps
    s0 = costs_bps / 2.0 / 10_000.0
    raw_entry = entry_fill / (1 + d * s0)
    exit_fill = entry_fill + d * r_recorded * abs(entry_fill - stop)
    raw_exit = exit_fill / (1 - d * s0)
    ce = (slip + venue.side_bps(pair, price=raw_entry)) / 10_000.0
    cx = (slip + venue.side_bps(pair, price=raw_exit)) / 10_000.0
    ef = raw_entry * (1 + d * ce)
    xf = raw_exit * (1 - d * cx)
    risk = abs(ef - stop)
    if risk <= 0:
        raise ValueError(f"{pair} {direction}: zero risk at {venue.name}")
    r = d * (xf - ef) / risk
    return r - funding_cost_r(
        bars_held=bars_held,
        bar_days=bar_days,
        bps_per_year=venue.funding_bps_per_year,
        entry_over_risk=ef / risk,
    )


@dataclass(slots=True)
class _Sub:
    """A subtotal; a ``None`` value (a short at a venue that cannot short)
    makes that venue's total ``None``."""

    n: int = 0
    total: dict[str, float | None] = field(default_factory=dict)

    def add(self, values: dict[str, float | None]) -> None:
        self.n += 1
        for k, v in values.items():
            prev = self.total.get(k, 0.0)
            self.total[k] = None if v is None or prev is None else prev + v

    def as_dict(self) -> dict[str, Any]:
        return {
            "n": self.n,
            "total_r": dict(self.total),
            "expectancy_r": (
                {k: None if v is None else v / self.n for k, v in self.total.items()}
                if self.n
                else {}
            ),
        }


def _stamp(v: date | datetime | None) -> str | None:
    return None if v is None else v.isoformat()


def _book_rows(
    session: Session, book: Any, trade_model: Any, entry_col: str, venues: Sequence[VenueCost]
) -> dict[str, Any]:
    hourly = trade_model is CryptoHourlyPaperTrade
    bar_days = 1.0 / 24.0 if hourly else 1.0
    rows = list(
        session.scalars(
            select(trade_model)
            .where(trade_model.book_id == book.id)
            .order_by(getattr(trade_model, entry_col))
        )
    )
    trades: list[dict[str, Any]] = []
    subs = {k: _Sub() for k in ("closed", "closed_long", "open", "open_long")}
    max_check = 0.0
    for r in rows:
        if r.status not in ("OPEN", "CLOSED"):
            continue
        rec = r.pnl_r if r.status == "CLOSED" else r.mark_r
        item: dict[str, Any] = {
            "pair": r.pair,
            "direction": r.direction,
            "status": r.status,
            "entry": _stamp(getattr(r, entry_col)),
            "exit": _stamp(getattr(r, "exit_at" if hourly else "exit_date")),
            "exit_reason": r.exit_reason,
            "entry_fill": r.entry_price,
            "stop": r.stop_price,
            "bars_held": r.bars_held,
            "r_recorded": rec,
            "r_venue": {},
        }
        if rec is not None:
            kw = {
                "pair": r.pair,
                "direction": r.direction,
                "entry_fill": float(r.entry_price),
                "stop": float(r.stop_price),
                "r_recorded": float(rec),
                "costs_bps": float(r.costs_bps),
                "bars_held": int(r.bars_held),
                "bar_days": bar_days,
            }
            check = reprice_r(**kw, venue=HARNESS_DEFAULT)
            max_check = max(max_check, abs(check - float(rec)))
            item["r_venue"] = {v.name: reprice_r(**kw, venue=v) for v in venues}
            values: dict[str, float | None] = {"recorded": float(rec), **item["r_venue"]}
            if r.direction == "SHORT":
                values.update({v.name: None for v in venues if not v.can_short})
            key = "closed" if r.status == "CLOSED" else "open"
            subs[key].add(values)
            if r.direction == "LONG":
                subs[f"{key}_long"].add(values)
        trades.append(item)
    return {
        "strategy_key": book.strategy_key,
        "version": book.version,
        "bars": "hourly" if hourly else "daily",
        "pairs": list(book.pairs),
        "start": _stamp(book.start_at if hourly else book.start_date),
        "last_bar": _stamp(book.last_bar_at if hourly else book.last_bar_date),
        "skipped": sum(1 for r in rows if r.status == "SKIPPED"),
        "trades": trades,
        "subtotals": {k: v.as_dict() for k, v in subs.items()},
        "harness_default_max_abs_error_r": max_check,
    }


def venue_report(
    session: Session, *, venues: Sequence[VenueCost] = REPORT_VENUES
) -> dict[str, Any]:
    """Every crypto paper book, repriced. Reads only."""
    books: list[dict[str, Any]] = []
    for b in session.scalars(select(CryptoPaperBook).order_by(CryptoPaperBook.id)):
        books.append(_book_rows(session, b, CryptoPaperTrade, "entry_date", venues))
    for hb in session.scalars(select(CryptoHourlyPaperBook).order_by(CryptoHourlyPaperBook.id)):
        books.append(_book_rows(session, hb, CryptoHourlyPaperTrade, "entry_at", venues))
    return {
        "venues": [
            {
                "name": v.name,
                "description": v.description,
                "taker_bps": v.taker_bps,
                "contract_fee_usd": v.contract_fee_usd,
                "funding_bps_per_year": v.funding_bps_per_year,
                "can_short": v.can_short,
            }
            for v in venues
        ],
        "books": books,
        "approximation": (
            "Ledgers store cost-loaded fills rounded to 4 dp and no raw entry/exit or mark "
            "price; raw prices are rebuilt from costs_bps and the recorded R. Open trades are "
            "repriced as closed at the last mark."
        ),
        "long_note": LONG_NOTE,
        "notice": NOTICE,
    }


def _fmt(v: float | None) -> str:
    return "n/a" if v is None else f"{v:+.3f}"


def render_text(report: dict[str, Any]) -> str:
    names = [v["name"] for v in report["venues"]]
    short = {"coinbase_spot_intro": "spot", "coinbase_cfm_intro": "cfm"}
    cols = [short.get(n, n) for n in names]
    lines = ["Crypto paper books repriced by venue (READ-ONLY)"]
    for v in report["venues"]:
        lines.append(f"  {v['name']}: {v['description']}")
    for b in report["books"]:
        lines += [
            "",
            f"{b['strategy_key']} {b['version']} ({b['bars']}): {', '.join(b['pairs'])}; "
            f"from {b['start']}, bars through {b['last_bar']}; skipped {b['skipped']}",
            f"  {'status':6} {'pair':8} {'dir':5} {'entry':25} {'R rec':>8} "
            + " ".join(f"{c:>8}" for c in cols),
        ]
        for t in b["trades"]:
            rv = t["r_venue"]
            flag = " (spot cannot short)" if t["direction"] == "SHORT" else ""
            lines.append(
                f"  {t['status']:6} {t['pair']:8} {t['direction']:5} {t['entry']:25} "
                f"{_fmt(t['r_recorded']):>8} "
                + " ".join(f"{_fmt(rv.get(n)):>8}" for n in names)
                + flag
            )
        for label, key in (
            ("closed, all", "closed"),
            ("closed, parent LONG trades", "closed_long"),
            ("open marks, all", "open"),
            ("open marks, parent LONG trades", "open_long"),
        ):
            sub = b["subtotals"][key]
            if not sub["n"]:
                lines.append(f"  {label}: none")
                continue
            tot = sub["total_r"]
            lines.append(
                f"  {label}: n={sub['n']} total R recorded {tot['recorded']:+.3f}; "
                + "; ".join(f"{c} {_fmt(tot[n])}" for c, n in zip(cols, names, strict=True))
            )
        lines.append(
            f"  check: harness_default reprices recorded R within "
            f"{b['harness_default_max_abs_error_r']:.1e}R"
        )
    lines += [
        "",
        f"Approximation: {report['approximation']}",
        report["long_note"],
        report["notice"],
    ]
    return "\n".join(lines)


__all__ = ["LONG_NOTE", "REPORT_VENUES", "render_text", "reprice_r", "venue_report"]
