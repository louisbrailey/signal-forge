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
    * The kill switch blocks OPENING and never blocks CLOSING or marking
      existing trades. A trade declined while it is engaged is stored as
      ``SKIPPED`` so a later cycle (switch released) can never open it late.
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
from signalforge.backtest.engine import SimTrade
from signalforge.data.series import PriceSeries
from signalforge.db.models import CryptoPaperBook, CryptoPaperTrade, CurrencySealedTest
from signalforge.db.session import has_write_intent, set_write_intent
from signalforge.killswitch import get_kill_switch
from signalforge.research.fx.harness import FxGates, ResearchMarket, backtest, load_series
from signalforge.research.fx.sealed import _lookup as _lookup_registered
from signalforge.research.fx.strategies import FxStrategy
from signalforge.settings_store import get_setting

PAPER_VERSION = "CRYPTO-PAPER-1"
OBSERVATION_DAYS = 180
DEFAULT_RISK_USD = 100.0  # illustration only: results are recorded in R
_PRICE_TOL = 1e-6
# A cycle whose read phase another cycle of the same book overtakes is replayed
# again from fresh data; this many attempts, then it refuses (writes nothing).
_MAX_CYCLE_ATTEMPTS = 3


class PaperBookRefused(RuntimeError):
    """A book may not be created or cycled."""


def _open_block_reason(session: Session, key: str) -> str:
    """Audited operational data holds block new entries, never position exits."""
    holds = get_setting(session, "crypto_paper_data_holds", {}) or {}
    if not isinstance(holds, dict):
        return "invalid crypto paper data-hold configuration"
    return str(holds.get(key, ""))


def _resolve(key: str) -> tuple[ResearchMarket, FxStrategy]:
    """The pre-registered crypto version a strategy key belongs to (CRYPTO-1,
    CRYPTO-2, ...) and its frozen rule — the SAME registry the sealed test
    used, so a book can only ever replay the rule that was sealed. Keys are
    unique across versions by construction (``_u10`` suffixes)."""
    try:
        market, strat, _gates = _lookup_registered("crypto", key)
    except ValueError as exc:
        raise PaperBookRefused(f"unknown crypto strategy {key!r}: {exc}") from None
    return market, strat


def _strategy(key: str) -> FxStrategy:
    return _resolve(key)[1]


def _sealed_pass(session: Session, key: str) -> CurrencySealedTest:
    market, _ = _resolve(key)
    row = session.scalar(
        select(CurrencySealedTest).where(
            CurrencySealedTest.market == market.name,
            CurrencySealedTest.version == market.version,
            CurrencySealedTest.strategy_key == key,
        )
    )
    if row is None or row.verdict != "SEALED_PASS":
        state = "no sealed test" if row is None else row.verdict
        raise PaperBookRefused(
            f"{key} {market.version} has {state}; a paper book needs SEALED_PASS"
        )
    return row


def get_book(session: Session, key: str) -> CryptoPaperBook | None:
    market, _ = _resolve(key)
    return session.scalar(
        select(CryptoPaperBook).where(
            CryptoPaperBook.strategy_key == key,
            CryptoPaperBook.version == market.version,
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
    market, _ = _resolve(key)
    sealed = _sealed_pass(session, key)
    if reason := _open_block_reason(session, key):
        raise PaperBookRefused(f"{key}: data hold: {reason}")
    if get_book(session, key) is not None:
        raise PaperBookRefused(f"a paper book for {key} {market.version} already exists")
    today = (now or datetime.now(UTC)).astimezone(UTC).date()
    book = CryptoPaperBook(
        strategy_key=key,
        version=market.version,
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
    skipped_open_data_hold: list[str] = field(default_factory=list)
    data_hold: str = ""
    divergences: list[str] = field(default_factory=list)
    # Read phases discarded because another cycle of this book committed first.
    concurrent_retries: int = 0


def _replay(
    session: Session, book: CryptoPaperBook, strat: FxStrategy, pair: str
) -> tuple[list[SimTrade], PriceSeries]:
    market, _ = _resolve(book.strategy_key)
    series = load_series(session, pair, market)
    if not len(series):
        return [], series
    gates = FxGates()
    # research.fx.harness.backtest is what the sealed test ran: the frozen
    # engine, or its trailing-exit twin when the rule declares one.
    out = backtest(
        strat,
        series,
        cost_model=CostModel(slippage_bps=gates.slippage_bps),
        spread_bps=market.spread(pair),
    )
    trades = [t for t in out.trades if t.entry_date > book.start_date]
    return trades, series


def _differs(a: float | None, b: float) -> bool:
    return a is None or abs(a - b) > _PRICE_TOL * max(1.0, abs(b))


@dataclass(slots=True)
class _PairReplay:
    """One pair's replay, computed in the READ phase of a cycle."""

    pair: str
    trades: list[SimTrade]
    series: PriceSeries
    last_bar: date | None
    index: dict[date, int]
    # Signal stop of every replayed entry not stored when the pair was read.
    stops: dict[date, float]
    # The pair's stored rows as the replay saw them (see :func:`_rows_state`).
    state: tuple[tuple[Any, ...], ...]


def _book_state(session: Session, book_id: int) -> tuple[Any, ...] | None:
    """What the last committed cycle stamped on the book, read past the
    identity map (``expire_on_commit=False`` keeps loaded instances stale)."""
    b = CryptoPaperBook
    row = session.execute(
        select(b.last_cycle_at, b.last_bar_date).where(b.id == book_id)
    ).one_or_none()
    return tuple(row) if row is not None else None


def _rows_state(session: Session, book_id: int, pair: str) -> tuple[tuple[Any, ...], ...]:
    """Every field a cycle writes on a pair's stored rows, read past the
    identity map. Equal in the read and write phase means no other cycle of
    this book touched the pair in between."""
    t = CryptoPaperTrade
    return tuple(
        tuple(r)
        for r in session.execute(
            select(
                t.entry_date,
                t.status,
                t.exit_date,
                t.exit_price,
                t.exit_reason,
                t.marked_at,
                t.mark_r,
                t.bars_held,
                t.divergence,
            )
            .where(t.book_id == book_id, t.pair == pair)
            .order_by(t.entry_date)
        )
    )


def _read_pair(
    session: Session, book: CryptoPaperBook, strat: FxStrategy, pair: str
) -> _PairReplay:
    # One snapshot (a plain BEGIN read transaction): the stored rows and the
    # bars the replay uses are read at the same instant.
    state = _rows_state(session, book.id, pair)
    trades, series = _replay(session, book, strat, pair)
    last_bar = series.dates[-1] if len(series) else None
    index = {d: i for i, d in enumerate(series.dates)}
    known = {r[0] for r in state}
    stops = {
        t.entry_date: _signal_stop(strat, series, index[t.entry_date])
        for t in trades
        if t.entry_date not in known
    }
    return _PairReplay(pair, trades, series, last_bar, index, stops, state)


def _apply_pair(
    session: Session,
    book: CryptoPaperBook,
    strat: FxStrategy,
    pr: _PairReplay,
    rep: CycleReport,
    *,
    engaged: bool,
) -> None:
    """Reconcile one pair's replay with its stored rows (WRITE phase). The
    stored rows are re-read here, inside the write transaction, so a row
    another writer added since the read phase is updated, never duplicated."""
    pair, last_bar = pr.pair, pr.last_bar
    stored = {
        r.entry_date: r
        for r in session.scalars(
            select(CryptoPaperTrade)
            .where(CryptoPaperTrade.book_id == book.id, CryptoPaperTrade.pair == pair)
            .execution_options(populate_existing=True)
        )
    }

    def stop_for(entry: date) -> float:
        stop = pr.stops.get(entry)
        return stop if stop is not None else _signal_stop(strat, pr.series, pr.index[entry])

    seen: set[date] = set()
    for t in pr.trades:
        seen.add(t.entry_date)
        still_open = t.exit_reason == "eod" and t.exit_date == last_bar
        tag = f"{pair} {t.direction.value} {t.entry_date}"
        row = stored.get(t.entry_date)
        if row is not None and row.status == "SKIPPED":
            continue  # declined while the kill switch was engaged — never opened later
        if row is None:
            if engaged or rep.data_hold:
                # Record the refusal durably: a later cycle (switch released)
                # replays the same history and must not open this trade late.
                session.add(
                    CryptoPaperTrade(
                        book_id=book.id,
                        pair=pair,
                        direction=t.direction.value,
                        entry_date=t.entry_date,
                        entry_price=t.entry_price,
                        stop_price=stop_for(t.entry_date),
                        status="SKIPPED",
                        exit_reason="kill_switch" if engaged else "data_hold",
                        costs_bps=t.costs_bps,
                        reason=t.reason[:64],
                        divergence="",
                    )
                )
                if engaged:
                    rep.skipped_open_kill_switch.append(tag)
                else:
                    rep.skipped_open_data_hold.append(tag)
                continue
            row = CryptoPaperTrade(
                book_id=book.id,
                pair=pair,
                direction=t.direction.value,
                entry_date=t.entry_date,
                entry_price=t.entry_price,
                stop_price=stop_for(t.entry_date),
                costs_bps=t.costs_bps,
                reason=t.reason[:64],
                divergence="",
            )
            session.add(row)
            rep.opened.append(tag)
        if row.status == "CLOSED":
            if row.exit_date != t.exit_date or _differs(row.exit_price, t.exit_price) or still_open:
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
        if entry not in seen and row.status != "SKIPPED":
            note = "replay no longer produces this trade"
            if row.divergence != note:
                row.divergence = note
                rep.divergences.append(f"{pair} {row.direction} {entry}: {note}")


def run_cycle(session: Session, key: str, *, now: datetime | None = None) -> CycleReport:
    """Replay every pair and reconcile the book: a READ phase (plain ``BEGIN``
    per pair — bars, replay, signal stops; the write lock is never held) then
    ONE short ``BEGIN IMMEDIATE`` write transaction that re-reads the stored
    rows and applies the replay, so a cycle lands all-or-nothing as before.
    Same split as the hourly book (incident 2026-11-07, see
    :func:`signalforge.paper.crypto_hourly_ledger.run_cycle`), including its
    overlap guard: if another cycle of this book committed after the read
    phase, nothing is written and the replay runs again from fresh data (up to
    ``_MAX_CYCLE_ATTEMPTS``, then it refuses). The kill switch and data holds
    are checked at the start and again inside the write transaction; either
    one blocks opening, never closing. The session is handed back with the
    write intent it arrived with."""
    restore = has_write_intent(session)
    if session.in_transaction():
        session.commit()
    try:
        for attempt in range(_MAX_CYCLE_ATTEMPTS):
            set_write_intent(session, False)
            book = get_book(session, key)
            if book is None:
                raise PaperBookRefused(
                    f"no paper book for {key}; create one with crypto paper start"
                )
            _sealed_pass(session, key)  # re-checked every cycle
            strat = _strategy(key)
            engaged = get_kill_switch().state().active
            rep = CycleReport(
                strategy_key=key,
                data_hold=_open_block_reason(session, key),
                concurrent_retries=attempt,
            )
            seen = _book_state(session, book.id)
            replays: list[_PairReplay] = []
            for pair in book.pairs:
                replays.append(_read_pair(session, book, strat, pair))
                session.commit()  # end this pair's read snapshot
            set_write_intent(session, True)
            if _book_state(session, book.id) != seen or any(
                _rows_state(session, book.id, pr.pair) != pr.state for pr in replays
            ):
                session.rollback()  # another cycle of this book won: replay again
                continue
            # Fresh instance: the stamp written below must diff against the DB.
            book = session.get(CryptoPaperBook, book.id, populate_existing=True)
            if book is None:  # cannot happen: its stamp was just re-read under the lock
                raise PaperBookRefused(f"paper book for {key} vanished mid-cycle")
            engaged = engaged or get_kill_switch().state().active
            rep.data_hold = rep.data_hold or _open_block_reason(session, key)
            for pr in replays:
                _apply_pair(session, book, strat, pr, rep, engaged=engaged)
            book.last_cycle_at = now or datetime.now(UTC)
            last_bars = [pr.last_bar for pr in replays if pr.last_bar is not None]
            if last_bars:
                book.last_bar_date = min(last_bars)
                rep.last_bar = book.last_bar_date.isoformat()
            session.commit()
            return rep
        raise PaperBookRefused(
            f"{key}: another cycle of this book committed during each of "
            f"{_MAX_CYCLE_ATTEMPTS} replays; nothing written, run the cycle again"
        )
    except Exception:
        session.rollback()
        raise
    finally:
        set_write_intent(session, restore)


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
        "data_hold": _open_block_reason(session, key),
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
        "skipped_kill_switch": sum(
            1 for r in rows if r.status == "SKIPPED" and r.exit_reason == "kill_switch"
        ),
        "skipped_data_hold": sum(
            1 for r in rows if r.status == "SKIPPED" and r.exit_reason == "data_hold"
        ),
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
