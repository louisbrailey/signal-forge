"""Crypto paper ledger (CRYPTO-PAPER-1) — simulated, prospective, broker-free.

What it is
    A forward record of what a SEALED_PASS crypto research strategy does on
    bars that did not exist when it was tested. Each daily cycle replays the
    exact backtest engine (same rules, same costs, next-open fills) over the
    completed daily bars and records only trades ENTERED after the book's fixed
    ``start_date``. Parity with the research result is therefore structural,
    not a second implementation that could drift.

What it is not
    Not an order path. There is no adapter, account, credential or network call
    here, and import contract S18 forbids this module from reaching
    the order-execution layer, alerts, the LLM layer or the equity/options paper
    books. ``SEALED_PASS`` plus a positive paper record is evidence for a later
    operator decision; nothing here promotes, arms or sizes a real trade.

Safety rules
    * A book can only be created for a strategy whose current version has a
      ``SEALED_PASS`` sealed test, and only with an explicit confirmation.
    * The kill switch blocks OPENING (no new trade row is recorded while it is
      engaged) and never blocks CLOSING or marking existing trades.
    * CLOSED rows are immutable. If a replay disagrees with a stored trade
      (e.g. the vendor revised a bar), the disagreement is written to
      ``divergence`` and the stored values are kept.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from signalforge.backtest.costs import CostModel
from signalforge.backtest.engine import SimTrade, run_backtest
from signalforge.data.series import PriceSeries
from signalforge.db.models import CryptoPaperBook, CryptoPaperTrade, CurrencySealedTest
from signalforge.killswitch import get_kill_switch
from signalforge.research.fx.harness import CRYPTO_MARKET, FxGates, load_series
from signalforge.research.fx.strategies import CRYPTO_STRATEGIES, FxStrategy

PAPER_VERSION = "CRYPTO-PAPER-1"
OBSERVATION_DAYS = 180
DEFAULT_RISK_USD = 100.0  # illustration only: results are recorded in R
_PRICE_TOL = 1e-6


class PaperBookRefused(RuntimeError):
    """A book may not be created or cycled."""


def _strategy(key: str) -> FxStrategy:
    for s in CRYPTO_STRATEGIES:
        if s.key == key:
            return s
    raise PaperBookRefused(f"unknown crypto strategy {key!r}")


def _sealed_pass(session: Session, key: str) -> CurrencySealedTest:
    row = session.scalar(
        select(CurrencySealedTest).where(
            CurrencySealedTest.market == CRYPTO_MARKET.name,
            CurrencySealedTest.version == CRYPTO_MARKET.version,
            CurrencySealedTest.strategy_key == key,
        )
    )
    if row is None or row.verdict != "SEALED_PASS":
        state = "no sealed test" if row is None else row.verdict
        raise PaperBookRefused(
            f"{key} {CRYPTO_MARKET.version} has {state}; a paper book needs SEALED_PASS"
        )
    return row


def get_book(session: Session, key: str) -> CryptoPaperBook | None:
    return session.scalar(
        select(CryptoPaperBook).where(
            CryptoPaperBook.strategy_key == key,
            CryptoPaperBook.version == CRYPTO_MARKET.version,
        )
    )


def start_book(
    session: Session,
    key: str,
    *,
    now: datetime | None = None,
    risk_usd: float = DEFAULT_RISK_USD,
) -> CryptoPaperBook:
    """Create the book. ``start_date`` is today (UTC): only signals on bars
    completed from today onward can produce a trade."""
    _strategy(key)
    sealed = _sealed_pass(session, key)
    if get_book(session, key) is not None:
        raise PaperBookRefused(f"a paper book for {key} {CRYPTO_MARKET.version} already exists")
    today = (now or datetime.now(UTC)).astimezone(UTC).date()
    book = CryptoPaperBook(
        strategy_key=key,
        version=CRYPTO_MARKET.version,
        sealed_test_id=sealed.id,
        pairs=list(sealed.pairs),
        start_date=today,
        observation_end=today + timedelta(days=OBSERVATION_DAYS),
        risk_usd_per_trade=risk_usd,
    )
    session.add(book)
    session.commit()
    return book


@dataclass(slots=True)
class CycleReport:
    strategy_key: str
    last_bar: str | None = None
    opened: list[str] = field(default_factory=list)
    closed: list[str] = field(default_factory=list)
    marked: list[str] = field(default_factory=list)
    skipped_open_kill_switch: list[str] = field(default_factory=list)
    divergences: list[str] = field(default_factory=list)


def _replay(
    session: Session, book: CryptoPaperBook, strat: FxStrategy, pair: str
) -> tuple[list[SimTrade], PriceSeries]:
    series = load_series(session, pair, CRYPTO_MARKET)
    if not len(series):
        return [], series
    gates = FxGates()
    out = run_backtest(
        series,
        strat.signal,
        cost_model=CostModel(slippage_bps=gates.slippage_bps),
        spread_bps=CRYPTO_MARKET.spread(pair),
        warmup=strat.warmup,
    )
    trades = [t for t in out.trades if t.entry_date > book.start_date]
    return trades, series


def _differs(a: float | None, b: float) -> bool:
    return a is None or abs(a - b) > _PRICE_TOL * max(1.0, abs(b))


def run_cycle(session: Session, key: str, *, now: datetime | None = None) -> CycleReport:
    book = get_book(session, key)
    if book is None:
        raise PaperBookRefused(f"no paper book for {key}; create one with crypto paper start")
    _sealed_pass(session, key)  # re-checked every cycle
    strat = _strategy(key)
    engaged = get_kill_switch().state().active
    rep = CycleReport(strategy_key=key)
    last_bars: list[date] = []
    for pair in book.pairs:
        trades, series = _replay(session, book, strat, pair)
        last_bar = series.dates[-1] if len(series) else None
        if last_bar is not None:
            last_bars.append(last_bar)
        index = {d: i for i, d in enumerate(series.dates)}
        stored = {
            r.entry_date: r
            for r in session.scalars(
                select(CryptoPaperTrade).where(
                    CryptoPaperTrade.book_id == book.id, CryptoPaperTrade.pair == pair
                )
            )
        }
        seen: set[date] = set()
        for t in trades:
            seen.add(t.entry_date)
            still_open = t.exit_reason == "eod" and t.exit_date == last_bar
            tag = f"{pair} {t.direction.value} {t.entry_date}"
            row = stored.get(t.entry_date)
            if row is None:
                if engaged:
                    rep.skipped_open_kill_switch.append(tag)
                    continue
                row = CryptoPaperTrade(
                    book_id=book.id,
                    pair=pair,
                    direction=t.direction.value,
                    entry_date=t.entry_date,
                    entry_price=t.entry_price,
                    stop_price=_signal_stop(strat, series, index[t.entry_date]),
                    costs_bps=t.costs_bps,
                    reason=t.reason[:64],
                    divergence="",
                )
                session.add(row)
                rep.opened.append(tag)
            if row.status == "CLOSED":
                if (
                    row.exit_date != t.exit_date
                    or _differs(row.exit_price, t.exit_price)
                    or still_open
                ):
                    note = f"replay now {t.exit_reason} {t.exit_date} {t.exit_price}"
                    if row.divergence != note[:300]:
                        row.divergence = note[:300]
                        rep.divergences.append(f"{tag}: {note}")
                continue
            if _differs(row.entry_price, t.entry_price):
                note = f"replay entry {t.entry_price} != stored {row.entry_price}"
                if row.divergence != note[:300]:
                    row.divergence = note[:300]
                    rep.divergences.append(f"{tag}: {note}")
            row.bars_held = t.bars_held
            if still_open:
                row.mark_r = t.pnl_r
                row.marked_at = t.exit_date
                rep.marked.append(f"{tag} {t.pnl_r:+.2f}R")
            else:
                row.status = "CLOSED"
                row.exit_date = t.exit_date
                row.exit_price = t.exit_price
                row.exit_reason = t.exit_reason
                row.pnl_r = t.pnl_r
                row.mark_r = None
                rep.closed.append(f"{tag} {t.exit_reason} {t.pnl_r:+.2f}R")
        for entry, row in stored.items():
            if entry not in seen:
                note = "replay no longer produces this trade"
                if row.divergence != note:
                    row.divergence = note
                    rep.divergences.append(f"{pair} {row.direction} {entry}: {note}")
    book.last_cycle_at = now or datetime.now(UTC)
    if last_bars:
        book.last_bar_date = min(last_bars)
        rep.last_bar = book.last_bar_date.isoformat()
    session.commit()
    return rep


def _signal_stop(strat: FxStrategy, series: PriceSeries, entry_idx: int) -> float:
    """The stop the rule set on the signal bar (the bar before the entry fill)."""
    t = entry_idx - 1
    sig = strat.signal(series.head(t), t)
    if sig is None:  # cannot happen for an engine trade; fail loudly, never guess
        raise PaperBookRefused(f"no signal on {series.dates[t]} for a recorded entry")
    return float(sig.stop_price)


def status(session: Session, key: str) -> dict[str, Any]:
    book = get_book(session, key)
    if book is None:
        return {"strategy_key": key, "book": None}
    rows: Sequence[CryptoPaperTrade] = list(
        session.scalars(
            select(CryptoPaperTrade)
            .where(CryptoPaperTrade.book_id == book.id)
            .order_by(CryptoPaperTrade.entry_date)
        )
    )
    closed = [r for r in rows if r.status == "CLOSED" and r.pnl_r is not None]
    pnl = [float(r.pnl_r) for r in closed if r.pnl_r is not None]
    sealed = session.get(CurrencySealedTest, book.sealed_test_id)
    return {
        "strategy_key": key,
        "version": book.version,
        "paper_version": PAPER_VERSION,
        "start_date": book.start_date.isoformat(),
        "observation_end": book.observation_end.isoformat(),
        "last_bar_date": book.last_bar_date.isoformat() if book.last_bar_date else None,
        "open": [
            {
                "pair": r.pair,
                "direction": r.direction,
                "entry_date": r.entry_date.isoformat(),
                "entry_price": r.entry_price,
                "stop_price": round(r.stop_price, 6),
                "mark_r": r.mark_r,
            }
            for r in rows
            if r.status == "OPEN"
        ],
        "closed_trades": len(closed),
        "expectancy_r": (sum(pnl) / len(pnl)) if pnl else None,
        "total_r": sum(pnl),
        "illustrative_usd": sum(pnl) * book.risk_usd_per_trade,
        "sealed_expectancy_r": (
            (sealed.result or {}).get("metrics", {}).get("expectancy_r") if sealed else None
        ),
        "divergences": [f"{r.pair} {r.entry_date}: {r.divergence}" for r in rows if r.divergence],
        "notice": "SIMULATED paper book. No order was placed; no broker is connected.",
    }


__all__ = [
    "OBSERVATION_DAYS",
    "PAPER_VERSION",
    "PaperBookRefused",
    "get_book",
    "run_cycle",
    "start_book",
    "status",
]
