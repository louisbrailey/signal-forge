"""Hourly crypto paper ledger (CRYPTO-PAPER-H1) — simulated, prospective, broker-free.

The hourly twin of :mod:`signalforge.paper.crypto_ledger`, built 2026-11-04 so a
SEALED_PASS *hourly* rule (CRYPTO-H4 ``crypto_h_donchian168_trail72_volx``) can
produce a forward record. Each cycle replays the exact research backtest
(``research.fx.harness.backtest``: the frozen engine, or its trailing-exit twin
when the rule declares one) over the completed hourly bars of
``crypto_bar_intraday`` and records only trades ENTERED at or after the book's
fixed ``start_at``. Parity with the sealed test is structural.

What it is not: not an order path. No adapter, account, credential or network
call lives here (import contract S18H). ``SEALED_PASS`` plus a positive paper
record is evidence for a later operator decision; nothing here arms anything.

Safety rules, identical to the daily book: SEALED_PASS required (re-checked every
cycle); the kill switch and audited data holds block OPENING only, never closing
or marking; declined entries are stored as ``SKIPPED`` so a later cycle can never
open them late; CLOSED rows are immutable and disagreements go to ``divergence``.
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
from signalforge.db.models import CryptoHourlyPaperBook, CryptoHourlyPaperTrade, CurrencySealedTest
from signalforge.killswitch import get_kill_switch
from signalforge.research.fx.harness import FxGates, ResearchMarket, backtest
from signalforge.research.fx.hourly import load_hourly_series
from signalforge.research.fx.sealed import HOURLY_MARKET_KEY
from signalforge.research.fx.sealed import _lookup as _lookup_registered
from signalforge.research.fx.strategies import FxStrategy
from signalforge.settings_store import get_setting

PAPER_VERSION = "CRYPTO-PAPER-H1"
OBSERVATION_DAYS = 180
DEFAULT_RISK_USD = 100.0  # illustration only: results are recorded in R
_PRICE_TOL = 1e-6
HOLDS_SETTING = "crypto_paper_data_holds"  # shared with the daily book, keyed by strategy


class PaperBookRefused(RuntimeError):
    """A book may not be created or cycled."""


def _utc(stamp: date | datetime) -> datetime:
    """Normalise a bar stamp to an aware UTC datetime. Hourly series carry
    datetimes; a bare ``date`` (never produced by the hourly loader, but the
    engine's type allows it) is taken as that day's 00:00 UTC."""
    if not isinstance(stamp, datetime):
        return datetime(stamp.year, stamp.month, stamp.day, tzinfo=UTC)
    return stamp.replace(tzinfo=UTC) if stamp.tzinfo is None else stamp.astimezone(UTC)


def _open_block_reason(session: Session, key: str) -> str:
    holds = get_setting(session, HOLDS_SETTING, {}) or {}
    if not isinstance(holds, dict):
        return "invalid crypto paper data-hold configuration"
    return str(holds.get(key, ""))


def _resolve(key: str) -> tuple[ResearchMarket, FxStrategy]:
    """The pre-registered HOURLY version a key belongs to and its frozen rule —
    the same registry the hourly sealed test used."""
    try:
        market, strat, _gates = _lookup_registered(HOURLY_MARKET_KEY, key)
    except ValueError as exc:
        raise PaperBookRefused(f"unknown hourly crypto strategy {key!r}: {exc}") from None
    return market, strat


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
            f"{key} {market.version} has {state}; an hourly paper book needs SEALED_PASS"
        )
    return row


def get_book(session: Session, key: str) -> CryptoHourlyPaperBook | None:
    market, _ = _resolve(key)
    return session.scalar(
        select(CryptoHourlyPaperBook).where(
            CryptoHourlyPaperBook.strategy_key == key,
            CryptoHourlyPaperBook.version == market.version,
        )
    )


def start_book(
    session: Session,
    key: str,
    *,
    now: datetime | None = None,
    risk_usd: float = DEFAULT_RISK_USD,
) -> CryptoHourlyPaperBook:
    """Create the book. ``start_at`` is the current hour (UTC, floored): only
    entries on bars completed from that hour onward can produce a trade."""
    market, _ = _resolve(key)
    sealed = _sealed_pass(session, key)
    if reason := _open_block_reason(session, key):
        raise PaperBookRefused(f"{key}: data hold: {reason}")
    if get_book(session, key) is not None:
        raise PaperBookRefused(f"an hourly paper book for {key} {market.version} already exists")
    start_at = _utc(now or datetime.now(UTC)).replace(minute=0, second=0, microsecond=0)
    book = CryptoHourlyPaperBook(
        strategy_key=key,
        version=market.version,
        sealed_test_id=sealed.id,
        pairs=list(sealed.pairs),
        start_at=start_at,
        observation_end=start_at + timedelta(days=OBSERVATION_DAYS),
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


def _replay(
    session: Session, book: CryptoHourlyPaperBook, strat: FxStrategy, pair: str
) -> tuple[list[SimTrade], PriceSeries]:
    market, _ = _resolve(book.strategy_key)
    series = load_hourly_series(session, pair)
    if not len(series):
        return [], series
    gates = FxGates()
    out = backtest(
        strat,
        series,
        cost_model=CostModel(slippage_bps=gates.slippage_bps),
        spread_bps=market.spread(pair),
    )
    start = _utc(book.start_at)
    trades = [t for t in out.trades if _utc(t.entry_date) >= start]
    return trades, series


def _differs(a: float | None, b: float) -> bool:
    return a is None or abs(a - b) > _PRICE_TOL * max(1.0, abs(b))


def _signal_stop(strat: FxStrategy, series: PriceSeries, entry_idx: int) -> float:
    """The stop the rule set on the signal bar (the bar before the entry fill)."""
    t = entry_idx - 1
    sig = strat.signal(series.head(t), t)
    if sig is None:  # cannot happen for an engine trade; fail loudly, never guess
        raise PaperBookRefused(f"no signal on {series.dates[t]} for a recorded entry")
    return float(sig.stop_price)


def run_cycle(session: Session, key: str, *, now: datetime | None = None) -> CycleReport:
    book = get_book(session, key)
    if book is None:
        raise PaperBookRefused(
            f"no hourly paper book for {key}; create one with crypto paper-hourly start"
        )
    _sealed_pass(session, key)  # re-checked every cycle
    _, strat = _resolve(key)
    engaged = get_kill_switch().state().active
    rep = CycleReport(strategy_key=key, data_hold=_open_block_reason(session, key))
    last_bars: list[datetime] = []
    for pair in book.pairs:
        trades, series = _replay(session, book, strat, pair)
        last_bar = _utc(series.dates[-1]) if len(series) else None
        if last_bar is not None:
            last_bars.append(last_bar)
        index = {_utc(d): i for i, d in enumerate(series.dates)}
        stored = {
            _utc(r.entry_at): r
            for r in session.scalars(
                select(CryptoHourlyPaperTrade).where(
                    CryptoHourlyPaperTrade.book_id == book.id,
                    CryptoHourlyPaperTrade.pair == pair,
                )
            )
        }
        seen: set[datetime] = set()
        for t in trades:
            entry_at = _utc(t.entry_date)
            exit_at = _utc(t.exit_date)
            seen.add(entry_at)
            still_open = t.exit_reason == "eod" and exit_at == last_bar
            tag = f"{pair} {t.direction.value} {entry_at.isoformat()}"
            row = stored.get(entry_at)
            if row is not None and row.status == "SKIPPED":
                continue  # declined under the kill switch or a hold — never opened later
            if row is None:
                if engaged or rep.data_hold:
                    session.add(
                        CryptoHourlyPaperTrade(
                            book_id=book.id,
                            pair=pair,
                            direction=t.direction.value,
                            entry_at=entry_at,
                            entry_price=t.entry_price,
                            stop_price=_signal_stop(strat, series, index[entry_at]),
                            status="SKIPPED",
                            exit_reason="kill_switch" if engaged else "data_hold",
                            costs_bps=t.costs_bps,
                            reason=t.reason[:64],
                            divergence="",
                        )
                    )
                    (
                        rep.skipped_open_kill_switch if engaged else rep.skipped_open_data_hold
                    ).append(tag)
                    continue
                row = CryptoHourlyPaperTrade(
                    book_id=book.id,
                    pair=pair,
                    direction=t.direction.value,
                    entry_at=entry_at,
                    entry_price=t.entry_price,
                    stop_price=_signal_stop(strat, series, index[entry_at]),
                    costs_bps=t.costs_bps,
                    reason=t.reason[:64],
                    divergence="",
                )
                session.add(row)
                rep.opened.append(tag)
            if row.status == "CLOSED":
                if (
                    (row.exit_at is None or _utc(row.exit_at) != exit_at)
                    or _differs(row.exit_price, t.exit_price)
                    or still_open
                ):
                    note = f"replay now {t.exit_reason} {exit_at.isoformat()} {t.exit_price}"
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
                row.marked_at = exit_at
                rep.marked.append(f"{tag} {t.pnl_r:+.2f}R")
            else:
                row.status = "CLOSED"
                row.exit_at = exit_at
                row.exit_price = t.exit_price
                row.exit_reason = t.exit_reason
                row.pnl_r = t.pnl_r
                row.mark_r = None
                rep.closed.append(f"{tag} {t.exit_reason} {t.pnl_r:+.2f}R")
        for entry_at, row in stored.items():
            if entry_at not in seen and row.status != "SKIPPED":
                note = "replay no longer produces this trade"
                if row.divergence != note:
                    row.divergence = note
                    rep.divergences.append(f"{pair} {row.direction} {entry_at.isoformat()}: {note}")
    book.last_cycle_at = _utc(now or datetime.now(UTC))
    if last_bars:
        book.last_bar_at = min(last_bars)
        rep.last_bar = book.last_bar_at.isoformat()
    session.commit()
    return rep


def status(session: Session, key: str) -> dict[str, Any]:
    book = get_book(session, key)
    if book is None:
        return {"strategy_key": key, "book": None}
    rows: Sequence[CryptoHourlyPaperTrade] = list(
        session.scalars(
            select(CryptoHourlyPaperTrade)
            .where(CryptoHourlyPaperTrade.book_id == book.id)
            .order_by(CryptoHourlyPaperTrade.entry_at)
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
        "start_at": _utc(book.start_at).isoformat(),
        "observation_end": _utc(book.observation_end).isoformat(),
        "last_bar_at": _utc(book.last_bar_at).isoformat() if book.last_bar_at else None,
        "pairs": list(book.pairs),
        "open": [
            {
                "pair": r.pair,
                "direction": r.direction,
                "entry_at": _utc(r.entry_at).isoformat(),
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
        "divergences": [
            f"{r.pair} {_utc(r.entry_at).isoformat()}: {r.divergence}" for r in rows if r.divergence
        ],
        "notice": "SIMULATED hourly paper book. No order was placed; no broker is connected.",
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
