"""Admission chronology, delayed bars and restart safety; no real providers."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest
from freezegun import freeze_time
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from signalforge import scheduler
from signalforge.backtest.engine import SimTrade
from signalforge.config import get_settings
from signalforge.data.series import PriceSeries
from signalforge.db.models import AppSettingHistory, CryptoHourlyPaperBook, CryptoHourlyPaperTrade
from signalforge.db.session import get_sessionmaker
from signalforge.domain import Direction
from signalforge.killswitch import get_kill_switch
from signalforge.paper import crypto_hourly_ledger as hl
from signalforge.settings_store import set_setting
from tests.paper.test_crypto_hourly_ledger import KEY, _sealed


def _at(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 11, 8, hour, minute, tzinfo=UTC)


def _trade(hour: int, *, end: int = 18, reason: str = "eod") -> SimTrade:
    return SimTrade(
        symbol="BTCUSD",
        direction=Direction.LONG,
        entry_date=_at(hour),
        entry_price=100,
        exit_date=_at(end),
        exit_price=102,
        bars_held=end - hour,
        pnl_r=0.2,
        pnl_pct=2,
        pnl_dollars=20,
        mae_r=0,
        mfe_r=0.2,
        costs_bps=1,
        exit_reason=reason,
    )


@pytest.fixture
def feed(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Exercise the real replay boundary and reconciliation, fake only engine/data."""
    data: dict[str, Any] = {"trades": [], "last": 18}

    def load(*args: Any) -> PriceSeries:
        dates = tuple(_at(h) for h in range(10, data["last"] + 1))
        prices = np.full(len(dates), 100.0)
        return PriceSeries("BTCUSD", dates, prices, prices, prices, prices, prices)

    monkeypatch.setattr(hl, "load_hourly_series", load)
    monkeypatch.setattr(hl, "backtest", lambda *a, **k: SimpleNamespace(trades=data["trades"]))
    monkeypatch.setattr(hl, "_signal_stop", lambda *a: 90.0)
    return data


def _rows(session: Session) -> list[CryptoHourlyPaperTrade]:
    session.rollback()  # see commits made by the registered job's other sessions
    session.expire_all()
    return list(
        session.scalars(select(CryptoHourlyPaperTrade).order_by(CryptoHourlyPaperTrade.entry_at))
    )


def _job(monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setenv("CRYPTO_HOURLY_PAPER_ENABLED", "true")
    monkeypatch.setenv("CRYPTO_INGEST_ENABLED", "true")
    monkeypatch.setenv("MARKET_DATA_PROVIDER", "massive")
    get_settings.cache_clear()
    spec = next(s for s in scheduler.default_job_specs() if s.name == "crypto_hourly_paper")
    return scheduler.build_scheduler(specs=[spec]).get_job(spec.name).func


@pytest.mark.parametrize("minute", [0, 37])
def test_first_fill_strictly_follows_exact_enrollment(
    session: Session, feed: dict[str, Any], minute: int
) -> None:
    with freeze_time(_at(13, minute)):
        _sealed(session)
        book = hl.start_book(session, KEY)
    feed["trades"] = [_trade(13, reason="target"), _trade(14)]
    with freeze_time(_at(19)):
        hl.run_cycle(session, KEY)
    assert book.start_at == _at(14)  # no extra hour for a 13:37 creation
    assert [r.entry_at for r in _rows(session)] == [_at(14)]
    st = hl.status(session, KEY)
    assert st["enrolled_at"] == _at(13, minute).isoformat()


def test_registered_job_refuses_kill_hours_after_clear_and_late_data(
    session: Session, feed: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    from signalforge.data import crypto_intraday

    calls: list[bool] = []

    def ingest(*args: Any, **kwargs: Any) -> Any:
        assert not get_kill_switch().state().active
        calls.append(True)
        return SimpleNamespace(end="fake")

    monkeypatch.setattr(crypto_intraday, "ingest_crypto_hourly", ingest)
    job = _job(monkeypatch)
    with freeze_time(_at(12, 37)):
        _sealed(session)
        hl.start_book(session, KEY)
    with freeze_time(_at(13, 10)):
        feed["last"], feed["trades"] = 13, [_trade(13, end=13)]
        job()  # valid existing position
    with freeze_time(_at(13, 37)):
        get_kill_switch().engage("test")
    with freeze_time(_at(14, 10)):
        # Existing position exits on stored bars under kill. The next entry is
        # absent because ingestion has stopped; a per-trade SKIPPED is impossible.
        feed["last"], feed["trades"] = 14, [_trade(13, end=14, reason="target")]
        job()
    assert len(calls) == 1
    closed_under_kill = [(r.status, r.exit_at) for r in _rows(session)]
    with freeze_time(_at(14, 37)):
        get_kill_switch().release("test")
    with freeze_time(_at(15, 10)):
        # Opening 14:00 was under kill; the bar closes after the 14:37 release.
        feed["last"], feed["trades"] = 15, [
            _trade(13, end=14, reason="target"),
            _trade(14, end=15, reason="target"),
        ]
        job()
    assert [(r.entry_at, r.status) for r in _rows(session)] == [
        (_at(13), "CLOSED"),
        (_at(14), "SKIPPED"),
    ]
    assert _rows(session)[1].exit_reason == "kill_switch"
    with freeze_time(_at(19)):
        feed["last"] = 18
        feed["trades"].append(_trade(16))
        job()
        job()  # unique (book_id, pair, opening timestamp), no duplicated outcomes
    assert [(r.entry_at, r.status) for r in _rows(session)] == [
        (_at(13), "CLOSED"),
        (_at(14), "SKIPPED"),
        (_at(16), "OPEN"),
    ]
    assert closed_under_kill == [("CLOSED", _at(14))]


def test_inhibition_survives_failed_replay_and_new_session(
    session: Session, feed: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    with freeze_time(_at(12, 37)):
        _sealed(session)
        hl.start_book(session, KEY)
    replay = hl._read_pair
    with freeze_time(_at(13, 37)):
        get_kill_switch().engage("test")
        monkeypatch.setattr(
            hl, "_read_pair", lambda *a: (_ for _ in ()).throw(RuntimeError("crash"))
        )
        with pytest.raises(RuntimeError, match="crash"):
            hl.run_cycle(session, KEY)
    monkeypatch.setattr(hl, "_read_pair", replay)
    with freeze_time(_at(15, 10)):
        get_kill_switch().release("test")
        feed["trades"] = [_trade(14)]
        with get_sessionmaker()() as restarted:
            hl.run_cycle(restarted, KEY)
    assert [(r.status, r.exit_reason) for r in _rows(session)] == [("SKIPPED", "kill_switch")]


def test_full_kill_interval_between_ticks_is_conservatively_refused(
    session: Session, feed: dict[str, Any]
) -> None:
    with freeze_time(_at(12, 37)):
        _sealed(session)
        hl.start_book(session, KEY)
    with freeze_time(_at(13, 37)):
        get_kill_switch().engage("test")
    with freeze_time(_at(14, 37)):
        get_kill_switch().release("test")
    with freeze_time(_at(15, 10)):
        feed["trades"] = [_trade(14)]
        hl.run_cycle(session, KEY)
    assert _rows(session)[0].status == "SKIPPED"


@pytest.mark.parametrize("restart", [False, True])
@pytest.mark.parametrize("prior_ack", [False, True])
def test_kill_after_final_observation_before_completion_is_not_acknowledged(
    session: Session,
    feed: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    restart: bool,
    prior_ack: bool,
) -> None:
    """Completion cannot acknowledge a switch transition the cycle never saw."""
    with freeze_time(_at(12, 37)):
        _sealed(session)
        book = hl.start_book(session, KEY)
    if prior_ack:
        with freeze_time(_at(13)):
            get_kill_switch().engage("earlier observed interval")
        with freeze_time(_at(13, 10)):
            get_kill_switch().release("earlier observed interval")
        with freeze_time(_at(13, 20)):
            hl.record_admission_state(session, KEY)
    audit_query = (
        select(AppSettingHistory.id, AppSettingHistory.new_value_json)
        .where(AppSettingHistory.key == hl._audit_key(book))
        .order_by(AppSettingHistory.id)
    )
    before = list(session.execute(audit_query))
    session.commit()
    original_apply = hl._apply_pair
    feed["last"] = 13  # the 14:00 fill is still unseen, as ingestion was paused
    with freeze_time(_at(14) - timedelta(milliseconds=200)) as clock:

        def apply_then_switch(*args: Any, **kwargs: Any) -> None:
            original_apply(*args, **kwargs)
            # AFTER the final switch observation/admission read, BEFORE the
            # completion stamp. The kill spans the next bar's opening fill.
            clock.move_to(_at(14) - timedelta(milliseconds=100))
            get_kill_switch().engage("final-observation race")
            clock.move_to(_at(14) + timedelta(milliseconds=100))
            get_kill_switch().release("final-observation race")
            clock.move_to(_at(14) + timedelta(milliseconds=200))

        with monkeypatch.context() as scoped:
            scoped.setattr(hl, "_apply_pair", apply_then_switch)
            hl.run_cycle(session, KEY)
    assert book.last_cycle_at == _at(14) + timedelta(milliseconds=200)
    assert hl._admission_state(session, book).kill_seen_at == (_at(13, 10) if prior_ack else None)
    session.rollback()
    feed["last"], feed["trades"] = 15, [_trade(14, end=15, reason="target")]
    with freeze_time(_at(15, 10)):
        if restart:
            import signalforge.killswitch as ks

            monkeypatch.setattr(ks, "_default", None)
            with get_sessionmaker()() as recovered:
                hl.run_cycle(recovered, KEY)
        else:
            hl.run_cycle(session, KEY)
    rows = _rows(session)
    assert [(r.entry_at, r.status, r.exit_reason) for r in rows] == [
        (_at(14), "SKIPPED", "kill_switch"),
    ]
    state = hl._admission_state(session, book)
    assert state.kill_seen_at == _at(14) + timedelta(milliseconds=100)
    acknowledged = list(session.execute(audit_query))
    assert acknowledged[: len(before)] == before  # retain all existing H2 history
    with freeze_time(_at(19)):
        feed["last"] = 18
        feed["trades"].append(_trade(16))
        hl.run_cycle(session, KEY)  # the acknowledged interval does not block future fills
        rep = hl.run_cycle(session, KEY)  # replay is idempotent
    assert rep.opened == []
    assert [(r.entry_at, r.status) for r in _rows(session)] == [
        (_at(14), "SKIPPED"),
        (_at(16), "OPEN"),
    ]
    assert list(session.execute(audit_query)) == acknowledged


@pytest.mark.parametrize("missed_ticks", [False, True])
def test_data_hold_cannot_backfill_late_entries(
    session: Session, feed: dict[str, Any], missed_ticks: bool
) -> None:
    with freeze_time(_at(12, 37)):
        _sealed(session)
        hl.start_book(session, KEY)
    with freeze_time(_at(13, 37)):
        set_setting(session, hl.HOLDS_SETTING, {KEY: "missing bars"})
        session.commit()
        if not missed_ticks:
            hl.run_cycle(session, KEY)
    with freeze_time(_at(14, 37)):
        set_setting(session, hl.HOLDS_SETTING, {})
        session.commit()
    with freeze_time(_at(15, 10)):
        feed["trades"] = [_trade(14)]
        hl.run_cycle(session, KEY)
        hl.run_cycle(session, KEY)
    assert [(r.status, r.exit_reason) for r in _rows(session)] == [("SKIPPED", "data_hold")]


def test_acknowledged_release_is_always_covered_by_its_durable_cutoff(
    session: Session, feed: dict[str, Any]
) -> None:
    with freeze_time(_at(12, 37)):
        _sealed(session)
        book = hl.start_book(session, KEY)
    with freeze_time(_at(14) - timedelta(milliseconds=100)):
        get_kill_switch().engage("state read after sampled observation time")
    with freeze_time(_at(14) + timedelta(milliseconds=100)):
        get_kill_switch().release("state read after sampled observation time")
        # The caller sampled `now` just before the state changed. It cannot
        # consume the release while saving a cutoff earlier than that release.
        hl.record_admission_state(session, KEY, now=_at(14) - timedelta(milliseconds=200))
    state = hl._admission_state(session, book)
    assert not state.hold
    assert state.kill_seen_at == _at(14) + timedelta(milliseconds=100)
    assert state.cutoffs[-1][0] >= state.kill_seen_at
    feed["trades"] = [_trade(14)]
    with freeze_time(_at(19)):
        hl.run_cycle(session, KEY)
    assert [(r.status, r.exit_reason) for r in _rows(session)] == [("SKIPPED", "kill_switch")]


@pytest.mark.parametrize("audit", ["missing", "corrupt"])
def test_unknown_enrollment_is_quarantined_without_rewriting_old_results(
    session: Session, feed: dict[str, Any], audit: str
) -> None:
    with freeze_time(_at(12, 37)):
        sealed = _sealed(session)
        # A real legacy book: floored start, no H2 attestation. Do not infer one
        # from created_at or change the original start/observation window.
        book = CryptoHourlyPaperBook(
            strategy_key=KEY,
            version="CRYPTO-H4",
            sealed_test_id=sealed.id,
            pairs=["BTCUSD"],
            start_at=_at(12),
            observation_end=_at(12) + timedelta(days=180),
            risk_usd_per_trade=100,
        )
        session.add(book)
        session.flush()
        if audit == "corrupt":
            session.add(
                AppSettingHistory(
                    key=hl._audit_key(book), old_value_json=None, new_value_json={"broken": True}
                )
            )
        session.add(
            CryptoHourlyPaperTrade(
                book_id=book.id,
                pair="BTCUSD",
                direction="LONG",
                entry_at=_at(12),
                entry_price=100,
                stop_price=90,
                status="CLOSED",
                exit_at=_at(13),
                exit_price=102,
                exit_reason="target",
                pnl_r=0.2,
                divergence="",
            )
        )
        session.add(
            CryptoHourlyPaperTrade(
                book_id=book.id,
                pair="BTCUSD",
                direction="LONG",
                entry_at=_at(13),
                entry_price=100,
                stop_price=90,
                status="OPEN",
                divergence="",
            )
        )
        session.commit()
    feed["trades"] = [_trade(12, end=13, reason="target"), _trade(13), _trade(14)]
    with freeze_time(_at(19)):
        hl.run_cycle(session, KEY)
    rows = _rows(session)
    assert [(r.status, r.exit_reason) for r in rows] == [
        ("CLOSED", "target"),
        ("OPEN", None),
        ("SKIPPED", "enrollment_hold"),
    ]
    assert rows[0].pnl_r == 0.2 and rows[0].exit_at == _at(13)
    assert rows[1].marked_at == _at(18)  # hold never blocks marks
    assert book.start_at == _at(12)
    st = hl.status(session, KEY)
    assert st["admission_hold"] and st["enrolled_at"] is None
    assert st["prospective_performance_eligible"] is False


def test_closed_outcomes_stay_immutable_under_admission_holds(
    session: Session, feed: dict[str, Any]
) -> None:
    with freeze_time(_at(12, 37)):
        _sealed(session)
        hl.start_book(session, KEY)
    feed["trades"] = [_trade(13, end=14, reason="target")]
    with freeze_time(_at(15)):
        hl.run_cycle(session, KEY)
    with freeze_time(_at(16)):
        get_kill_switch().engage("test")
        feed["trades"] = [replace(feed["trades"][0], exit_price=110, pnl_r=1)]
        hl.run_cycle(session, KEY)
    row = _rows(session)[0]
    assert row.exit_price == 102 and row.pnl_r == 0.2
    assert row.divergence


@pytest.mark.parametrize("damage", ["missing", "corrupt", "naive_timestamp"])
def test_damaged_h2_admission_store_fails_closed_but_allows_existing_exit(
    session: Session, feed: dict[str, Any], damage: str
) -> None:
    with freeze_time(_at(12, 37)):
        _sealed(session)
        book = hl.start_book(session, KEY)
    feed["last"], feed["trades"] = 13, [_trade(13, end=13)]
    with freeze_time(_at(13, 10)):
        hl.run_cycle(session, KEY)
    if damage == "missing":
        session.execute(
            delete(AppSettingHistory).where(AppSettingHistory.key == hl._audit_key(book))
        )
    else:
        event = (
            {"broken": True}
            if damage == "corrupt"
            else {
                "version": hl.ADMISSION_VERSION,
                "kind": "blocked",
                "reason": "kill_switch",
                "at": "2026-11-08T14:00:00",
            }
        )
        session.add(
            AppSettingHistory(
                key=hl._audit_key(book),
                old_value_json=None,
                new_value_json=event,
            )
        )
    session.commit()
    feed["last"], feed["trades"] = 18, [_trade(13, end=14, reason="target"), _trade(14)]
    with freeze_time(_at(19)):
        hl.run_cycle(session, KEY)
    assert [(r.status, r.exit_reason) for r in _rows(session)] == [
        ("CLOSED", "target"),
        ("SKIPPED", "enrollment_hold"),
    ]
    st = hl.status(session, KEY)
    assert st["data_hold"] and "QUARANTINED" in st["notice"]
    assert st["prospective_expectancy_r"] is None
