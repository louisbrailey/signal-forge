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

Safety rules: SEALED_PASS required (re-checked every
cycle); the kill switch and audited data holds block OPENING only, never closing
or marking; declined entries are stored as ``SKIPPED`` so a later cycle can never
open them late; CLOSED rows are immutable and disagreements go to ``divergence``.

Admission audit (H2): append-only ``AppSettingHistory`` rows under
``crypto_hourly_admission:<book_id>`` record exact enrollment and conservative
no-admission cutoffs. An inhibition refuses ALL unseen fills through its last
observation, extended through the first clear observation, even if bars arrived
late or replay failed. Already stored positions still reconcile normally.

Legacy H1 books lack this exact-enrollment attestation: their start, trades and
results stay intact, but all unseen entries are held as ``enrollment_hold``.
There is NO automatic migration using the floored start or DB insertion time.
Resumption requires a separately reviewed provenance migration or a new versioned
book; clearing the ordinary data hold cannot grant enrollment. Historical results
are never recertified by this code.
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
from signalforge.config import paths
from signalforge.data.series import PriceSeries
from signalforge.db.models import (
    AppSettingHistory,
    CryptoHourlyPaperBook,
    CryptoHourlyPaperTrade,
    CurrencySealedTest,
)
from signalforge.db.session import has_write_intent, set_write_intent
from signalforge.killswitch import get_kill_switch
from signalforge.research.fx.harness import FxGates, ResearchMarket, backtest
from signalforge.research.fx.hourly import load_hourly_series
from signalforge.research.fx.sealed import HOURLY_MARKET_KEY
from signalforge.research.fx.sealed import _lookup as _lookup_registered
from signalforge.research.fx.strategies import FxStrategy
from signalforge.settings_store import get_setting

PAPER_VERSION = "CRYPTO-PAPER-H1"
ADMISSION_VERSION = "CRYPTO-PAPER-H2"
OBSERVATION_DAYS = 180
DEFAULT_RISK_USD = 100.0  # illustration only: results are recorded in R
_PRICE_TOL = 1e-6
HOLDS_SETTING = "crypto_paper_data_holds"  # shared with the daily book, keyed by strategy
# A cycle whose read phase another cycle of the same book overtakes is replayed
# again from fresh data; this many attempts, then it refuses (writes nothing).
_MAX_CYCLE_ATTEMPTS = 3


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
    holds = get_setting(session, HOLDS_SETTING, {})
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


def _audit_key(book: CryptoHourlyPaperBook) -> str:
    return f"crypto_hourly_admission:{book.id}"


def _audit_time(value: Any) -> datetime:
    stamp = datetime.fromisoformat(value)
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ValueError("admission audit requires an exact, timezone-aware timestamp")
    return _utc(stamp)


def _append_admission(session: Session, book: CryptoHourlyPaperBook, event: dict[str, Any]) -> None:
    session.add(
        AppSettingHistory(
            key=_audit_key(book),
            old_value_json=None,
            new_value_json={"version": ADMISSION_VERSION, **event},
            changed_by="crypto-hourly-paper",
        )
    )


@dataclass(slots=True)
class _AdmissionState:
    enrolled_at: datetime | None = None
    cutoffs: list[tuple[datetime, str]] = field(default_factory=list)
    pending_reason: str = ""
    kill_seen_at: datetime | None = None
    hold_seen_id: int = 0
    hold: str = "exact enrollment unavailable; legacy book needs reviewed migration"

    def block_reason(self, entry_at: datetime) -> str:
        if self.hold:
            return "enrollment_hold"
        return next((reason for through, reason in self.cutoffs if entry_at <= through), "")


def _admission_state(session: Session, book: CryptoHourlyPaperBook) -> _AdmissionState:
    """Read immutable events, never infer enrollment from legacy timestamps."""
    state = _AdmissionState()
    events = session.scalars(
        select(AppSettingHistory.new_value_json)
        .where(AppSettingHistory.key == _audit_key(book))
        .order_by(AppSettingHistory.id)
    )
    try:
        for i, event in enumerate(events):
            if event["version"] != ADMISSION_VERSION:
                raise ValueError("unknown admission version")
            kind = event["kind"]
            if kind == "enrolled" and i == 0:
                enrolled = _audit_time(event["at"])
                first_fill = enrolled.replace(minute=0, second=0, microsecond=0) + timedelta(
                    hours=1
                )
                if first_fill != _utc(book.start_at):
                    raise ValueError("enrollment boundary disagrees with book")
                state.enrolled_at, state.hold = enrolled, ""
            elif kind in ("blocked", "resumed") and event["reason"] in ("kill_switch", "data_hold"):
                through = _audit_time(event["at"])
                state.cutoffs.append((through, event["reason"]))
                state.pending_reason = event["reason"] if kind == "blocked" else ""
                if event.get("kill_seen_at"):
                    acknowledged = _audit_time(event["kill_seen_at"])
                    if acknowledged > through:
                        raise ValueError("acknowledged transition has no covering refusal cutoff")
                    state.kill_seen_at = max(state.kill_seen_at or acknowledged, acknowledged)
                state.hold_seen_id = max(state.hold_seen_id, int(event.get("hold_seen_id", 0)))
            else:
                raise ValueError("invalid admission event")
    except (KeyError, TypeError, ValueError):
        state.hold = "invalid admission audit; new entries held pending reviewed repair"
    return state


def _inhibition_event(
    session: Session, book: CryptoHourlyPaperBook, at: datetime, forced_reason: str = ""
) -> dict[str, Any] | None:
    """Also catch a full engage/release or audited hold between job ticks.
    Latest release is enough: refuse ALL unseen fills through this observation,
    without guessing the missing onset. A pending event survives process death.
    """
    state = _admission_state(session, book)
    kill = get_kill_switch().state()
    # Missing state is the kill switch's documented fresh-install state; its
    # synthetic changed_at is not a release. Corrupt state reads as active.
    kill_at = _utc(kill.changed_at) if paths.kill_switch_state_path().exists() else None
    # Completion is NOT an observation: a kill can engage and release after
    # the last switch read but before last_cycle_at is stamped. A transition
    # is acknowledged only by a durable admission event carrying its cutoff.
    # Existing H2 histories already have this field; no history is rewritten.
    since = state.kill_seen_at or state.enrolled_at
    unseen_release = bool(kill_at and (since is None or kill_at > since) and not kill.active)
    unseen_hold = False
    hold_seen_id = state.hold_seen_id
    for h in session.scalars(
        select(AppSettingHistory).where(
            AppSettingHistory.key == HOLDS_SETTING,
            AppSettingHistory.id > state.hold_seen_id,
            AppSettingHistory.created_at >= (state.enrolled_at or _utc(book.start_at)),
        )
    ):
        hold_seen_id = max(hold_seen_id, h.id)
        for value in (h.old_value_json, h.new_value_json):
            if value is not None and (not isinstance(value, dict) or value.get(book.strategy_key)):
                unseen_hold = True
    reason = forced_reason or (
        "kill_switch"
        if kill.active
        else "data_hold" if _open_block_reason(session, book.strategy_key) else ""
    )
    pending = bool(reason)
    reason = (
        reason
        or state.pending_reason
        or ("kill_switch" if unseen_release else "data_hold" if unseen_hold else "")
    )
    if not reason:
        return None
    return {
        "kind": "blocked" if pending else "resumed",
        # The state read can occur after the caller sampled `at`. Never
        # acknowledge a transition newer than the cutoff protecting it.
        "at": max(at, kill_at or at).isoformat(),
        "reason": reason,
        "kill_seen_at": kill_at.isoformat() if kill_at else None,
        "hold_seen_id": hold_seen_id,
    }


def _note_inhibition(
    session: Session, book: CryptoHourlyPaperBook, at: datetime, reason: str = ""
) -> None:
    """WRITE phase only. Never replace or remove an earlier refusal."""
    if event := _inhibition_event(session, book, at, reason):
        _append_admission(session, book, event)


def record_admission_state(session: Session, key: str, *, now: datetime | None = None) -> None:
    """Durably refuse inhibited history BEFORE ingestion/replay can fail.

    Uses a short writer only when needed, then restores the caller's intent.
    The first clear observation extends a pending cutoff through that instant.
    Ordinary clear cycles add no event and acquire no write lock here.
    """
    restore = has_write_intent(session)
    if session.in_transaction():
        session.commit()
    try:
        set_write_intent(session, False)
        book = get_book(session, key)
        if book is None:
            raise PaperBookRefused(f"no hourly paper book for {key}")
        at = _utc(now or datetime.now(UTC))
        event = _inhibition_event(session, book, at)
        session.commit()
        if event:
            set_write_intent(session, True)
            _note_inhibition(
                session, book, at, event["reason"] if event["kind"] == "blocked" else ""
            )
            session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        set_write_intent(session, restore)


def start_book(
    session: Session,
    key: str,
    *,
    now: datetime | None = None,
    risk_usd: float = DEFAULT_RISK_USD,
) -> CryptoHourlyPaperBook:
    """Enroll at the exact instant; first fill is STRICTLY after enrollment,
    including creation exactly on an hour. Persist the attestation atomically."""
    market, _ = _resolve(key)
    sealed = _sealed_pass(session, key)
    if reason := _open_block_reason(session, key):
        raise PaperBookRefused(f"{key}: data hold: {reason}")
    if get_book(session, key) is not None:
        raise PaperBookRefused(f"an hourly paper book for {key} {market.version} already exists")
    enrolled_at = _utc(now or datetime.now(UTC))
    start_at = enrolled_at.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
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
    session.flush()
    _append_admission(session, book, {"kind": "enrolled", "at": enrolled_at.isoformat()})
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


@dataclass(slots=True)
class _PairReplay:
    """One pair's replay, computed in the READ phase of a cycle."""

    pair: str
    trades: list[SimTrade]
    series: PriceSeries
    last_bar: datetime | None
    index: dict[datetime, int]
    # Signal stop of every replayed entry not stored when the pair was read.
    stops: dict[datetime, float]
    # The pair's stored rows as the replay saw them (see :func:`_rows_state`).
    state: tuple[tuple[Any, ...], ...]


def _book_state(session: Session, book_id: int) -> tuple[Any, ...] | None:
    """What the last committed cycle stamped on the book, read past the
    identity map (``expire_on_commit=False`` keeps loaded instances stale)."""
    b = CryptoHourlyPaperBook
    row = session.execute(
        select(b.last_cycle_at, b.last_bar_at).where(b.id == book_id)
    ).one_or_none()
    return tuple(row) if row is not None else None


def _rows_state(session: Session, book_id: int, pair: str) -> tuple[tuple[Any, ...], ...]:
    """Every field a cycle writes on a pair's stored rows, read past the
    identity map. Equal in the read and write phase means no other cycle of
    this book touched the pair in between."""
    t = CryptoHourlyPaperTrade
    return tuple(
        tuple(r)
        for r in session.execute(
            select(
                t.entry_at,
                t.status,
                t.exit_at,
                t.exit_price,
                t.exit_reason,
                t.marked_at,
                t.mark_r,
                t.bars_held,
                t.divergence,
            )
            .where(t.book_id == book_id, t.pair == pair)
            .order_by(t.entry_at)
        )
    )


def _read_pair(
    session: Session, book: CryptoHourlyPaperBook, strat: FxStrategy, pair: str
) -> _PairReplay:
    # One snapshot (a plain BEGIN read transaction): the stored rows and the
    # bars the replay uses are read at the same instant.
    state = _rows_state(session, book.id, pair)
    trades, series = _replay(session, book, strat, pair)
    last_bar = _utc(series.dates[-1]) if len(series) else None
    index = {_utc(d): i for i, d in enumerate(series.dates)}
    known = {_utc(r[0]) for r in state}
    stops = {
        _utc(t.entry_date): _signal_stop(strat, series, index[_utc(t.entry_date)])
        for t in trades
        if _utc(t.entry_date) not in known
    }
    return _PairReplay(pair, trades, series, last_bar, index, stops, state)


def _apply_pair(
    session: Session,
    book: CryptoHourlyPaperBook,
    strat: FxStrategy,
    pr: _PairReplay,
    rep: CycleReport,
    *,
    engaged: bool,
    admission: _AdmissionState,
) -> None:
    """Reconcile one pair's replay with its stored rows (WRITE phase). The
    stored rows are re-read here, inside the write transaction, so a row
    another writer added since the read phase is updated, never duplicated."""
    pair, last_bar = pr.pair, pr.last_bar
    stored = {
        _utc(r.entry_at): r
        for r in session.scalars(
            select(CryptoHourlyPaperTrade)
            .where(
                CryptoHourlyPaperTrade.book_id == book.id,
                CryptoHourlyPaperTrade.pair == pair,
            )
            .execution_options(populate_existing=True)
        )
    }

    def stop_for(entry_at: datetime) -> float:
        stop = pr.stops.get(entry_at)
        return stop if stop is not None else _signal_stop(strat, pr.series, pr.index[entry_at])

    seen: set[datetime] = set()
    for t in pr.trades:
        entry_at = _utc(t.entry_date)
        exit_at = _utc(t.exit_date)
        seen.add(entry_at)
        still_open = t.exit_reason == "eod" and exit_at == last_bar
        tag = f"{pair} {t.direction.value} {entry_at.isoformat()}"
        row = stored.get(entry_at)
        if row is not None and row.status == "SKIPPED":
            continue  # declined under the kill switch or a hold — never opened later
        if row is None:
            blocked = "kill_switch" if engaged else "data_hold" if rep.data_hold else ""
            blocked = blocked or admission.block_reason(entry_at)
            if blocked:
                session.add(
                    CryptoHourlyPaperTrade(
                        book_id=book.id,
                        pair=pair,
                        direction=t.direction.value,
                        entry_at=entry_at,
                        entry_price=t.entry_price,
                        stop_price=stop_for(entry_at),
                        status="SKIPPED",
                        exit_reason=blocked,
                        costs_bps=t.costs_bps,
                        reason=t.reason[:64],
                        divergence="",
                    )
                )
                if blocked == "kill_switch":
                    rep.skipped_open_kill_switch.append(tag)
                else:
                    rep.skipped_open_data_hold.append(tag)
                continue
            row = CryptoHourlyPaperTrade(
                book_id=book.id,
                pair=pair,
                direction=t.direction.value,
                entry_at=entry_at,
                entry_price=t.entry_price,
                stop_price=stop_for(entry_at),
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


def run_cycle(session: Session, key: str, *, now: datetime | None = None) -> CycleReport:
    """Replay every pair and reconcile the book, in two phases (incident
    2026-11-07: a cycle that held ``BEGIN IMMEDIATE`` for its whole replay kept
    the SQLite write lock for 77 minutes after a laptop wake and six other jobs
    failed ``database is locked``).

    * READ phase — plain ``BEGIN`` transactions, one per pair, write lock never
      held: load bars, replay, and work out the signal stop of every entry not
      yet stored. This is all the slow work.
    * WRITE phase — ONE short ``BEGIN IMMEDIATE`` transaction for the whole
      book: re-read the stored rows, apply the replay, commit. A cycle still
      lands all-or-nothing, exactly as before.

    Two cycles of one book can now overlap (the scheduled job plus a manual
    ``crypto paper-hourly run``). The write phase therefore first checks that
    the book stamp and every pair's stored rows are exactly as the read phase
    saw them; if another cycle committed in between, this cycle's replay may be
    older than the stored state, so it writes nothing and replays again from
    fresh data (up to ``_MAX_CYCLE_ATTEMPTS``, then it refuses). Overlapping
    cycles are serialised as they were under the old whole-cycle lock.

    The kill switch and data holds are checked at the start AND again inside
    the write transaction: either one engaged blocks opening (never closing).
    The session is handed back with the write intent it arrived with; any
    pending caller work is committed first (the cycle always committed)."""
    restore = has_write_intent(session)
    if session.in_transaction():
        session.commit()
    try:
        record_admission_state(session, key, now=now)
        for attempt in range(_MAX_CYCLE_ATTEMPTS):
            set_write_intent(session, False)
            book = get_book(session, key)
            if book is None:
                raise PaperBookRefused(
                    f"no hourly paper book for {key}; create one with crypto paper-hourly start"
                )
            _sealed_pass(session, key)  # re-checked every cycle
            _, strat = _resolve(key)
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
            book = session.get(CryptoHourlyPaperBook, book.id, populate_existing=True)
            if book is None:  # cannot happen: its stamp was just re-read under the lock
                raise PaperBookRefused(f"hourly paper book for {key} vanished mid-cycle")
            engaged = engaged or get_kill_switch().state().active
            rep.data_hold = rep.data_hold or _open_block_reason(session, key)
            reason = "kill_switch" if engaged else "data_hold" if rep.data_hold else ""
            _note_inhibition(session, book, _utc(now or datetime.now(UTC)), reason)
            session.flush()  # own new cutoff must be visible with autoflush=False
            admission = _admission_state(session, book)
            for pr in replays:
                _apply_pair(session, book, strat, pr, rep, engaged=engaged, admission=admission)
            book.last_cycle_at = _utc(now or datetime.now(UTC))
            last_bars = [pr.last_bar for pr in replays if pr.last_bar is not None]
            if last_bars:
                book.last_bar_at = min(last_bars)
                rep.last_bar = book.last_bar_at.isoformat()
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
    admission = _admission_state(session, book)
    return {
        "strategy_key": key,
        "version": book.version,
        "data_hold": _open_block_reason(session, key) or admission.hold,
        "paper_version": PAPER_VERSION,
        "admission_version": ADMISSION_VERSION,
        "admission_hold": admission.hold,
        "prospective_performance_eligible": not bool(admission.hold),
        "performance_notice": (
            "Quarantined legacy/invalid enrollment: retained results are historical only; "
            "exclude from prospective performance. No historical outcome was rewritten."
            if admission.hold
            else "H2 admission policy; simulated only."
        ),
        "enrolled_at": admission.enrolled_at.isoformat() if admission.enrolled_at else None,
        "admission_audit_key": _audit_key(book),
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
        "prospective_expectancy_r": (sum(pnl) / len(pnl)) if pnl and not admission.hold else None,
        "total_r": sum(pnl),
        "illustrative_usd": sum(pnl) * book.risk_usd_per_trade,
        "sealed_expectancy_r": (
            (sealed.result or {}).get("metrics", {}).get("expectancy_r") if sealed else None
        ),
        "divergences": [
            f"{r.pair} {_utc(r.entry_at).isoformat()}: {r.divergence}" for r in rows if r.divergence
        ],
        "notice": "SIMULATED hourly paper book. No order was placed; no broker is connected."
        + (
            " QUARANTINED: retained results are historical only; "
            "exclude from prospective performance."
            if admission.hold
            else ""
        ),
    }


__all__ = [
    "OBSERVATION_DAYS",
    "PAPER_VERSION",
    "PaperBookRefused",
    "get_book",
    "record_admission_state",
    "run_cycle",
    "start_book",
    "status",
]
