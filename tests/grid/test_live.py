"""The live (paper) grid job: kill switch, disabled flag, idempotency, wiring."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from signalforge.config.research import GridConfig
from signalforge.db.models import AuditLog, GridPosition, GridTradeRow, PaperAccount
from signalforge.grid.live import ensure_grid_account, run_grid_daily
from tests.grid.conftest import GRID_SOURCE, BarWriter

# Same hand-derived path as the engine tests: anchor 100, a 5% drop on d2 filling
# at d3's open, then a 5% rise on d4 filling at d5's open.
_CLOSES = [100.0, 100.0, 94.90, 94.90, 99.70, 99.70]
_OPENS = [100.0, 100.0, 94.90, 90.00, 99.70, 101.00]
_START = date(2024, 1, 2)


def _cfg(**kw: object) -> GridConfig:
    base: dict[str, object] = {
        "enabled": True,
        "universe_name": "test",
        "universe_size": 5,
        "starting_cash": 1_000.0,
        "per_symbol_cap": 50.0,
        "source": GRID_SOURCE,
    }
    base.update(kw)
    return GridConfig.model_validate(base)


def _run(session: Session, day_index: int, **kw: object) -> object:
    return run_grid_daily(
        session,
        cfg=_cfg(**kw),
        as_of=_START + timedelta(days=day_index),
        symbols=["AAA"],
    )


def test_disabled_flag_is_a_no_op(session: Session, write_bars: BarWriter) -> None:
    write_bars("AAA", _CLOSES, _OPENS)
    res = run_grid_daily(session, cfg=_cfg(enabled=False), as_of=_START, symbols=["AAA"])
    assert res.ran is False
    assert "enabled" in res.reason
    assert session.scalar(select(PaperAccount).where(PaperAccount.name == "grid")) is None
    assert not list(session.scalars(select(GridTradeRow)))


def test_kill_switch_blocks_the_job(session: Session, write_bars: BarWriter) -> None:
    from signalforge.killswitch import KillSwitchEngaged, get_kill_switch

    write_bars("AAA", _CLOSES, _OPENS)
    get_kill_switch().engage(reason="test", actor="test")
    try:
        with pytest.raises(KillSwitchEngaged):
            run_grid_daily(session, cfg=_cfg(), as_of=_START, symbols=["AAA"])
    finally:
        get_kill_switch().release(reason="test", actor="test")
    assert not list(session.scalars(select(GridTradeRow)))


def test_first_run_only_establishes_the_anchor(session: Session, write_bars: BarWriter) -> None:
    write_bars("AAA", _CLOSES, _OPENS)
    res = _run(session, 1)  # decision close = d0 (100.0), fill session = d1
    assert res.ran and res.tracking_started == 1 and res.trades == 0  # type: ignore[attr-defined]
    pos = session.scalar(select(GridPosition).where(GridPosition.symbol == "AAA"))
    assert pos is not None
    assert float(pos.anchor_price) == pytest.approx(100.0)
    assert float(pos.qty) == 0.0
    assert not list(session.scalars(select(GridTradeRow)))


def test_buy_then_sell_matches_the_engine(session: Session, write_bars: BarWriter) -> None:
    write_bars("AAA", _CLOSES, _OPENS)
    _run(session, 1)  # anchor 100.0
    _run(session, 2)  # d1 close 100.0 -> no trigger
    r3 = _run(session, 3)  # d2 close 94.90 -> BUY, fills at d3 open 90.00
    assert r3.buys == 1  # type: ignore[attr-defined]

    trade = session.scalar(select(GridTradeRow).where(GridTradeRow.side == "buy"))
    assert trade is not None
    assert trade.session_date == _START + timedelta(days=3)
    assert float(trade.anchor_before) == pytest.approx(100.0)
    assert float(trade.anchor_after) == pytest.approx(94.90)
    # Next-open fill with the cost model applied against the trade.
    assert float(trade.price) == pytest.approx(90.00 * (1 + (3.0 + 2.5) / 10_000.0), rel=1e-9)
    assert 0.0 < float(trade.qty) < 1.0
    assert trade.evidence_json["bars"]["decision_close"] == pytest.approx(94.90)
    assert trade.evidence_json["bars"]["session_open"] == pytest.approx(90.00)
    assert "params" in trade.evidence_json and "cost" in trade.evidence_json

    acct = session.scalar(select(PaperAccount).where(PaperAccount.name == "grid"))
    assert acct is not None
    assert float(acct.cash) == pytest.approx(1_000.0 - float(trade.usd), abs=1e-5)

    audit = session.scalar(select(AuditLog).where(AuditLog.action == "grid.trade"))
    assert audit is not None and "AAA" in audit.entity

    _run(session, 4)  # d3 close 94.90 -> no trigger
    r5 = _run(session, 5)  # d4 close 99.70 -> SELL, fills at d5 open 101.00
    assert r5.sells == 1  # type: ignore[attr-defined]
    sell = session.scalar(select(GridTradeRow).where(GridTradeRow.side == "sell"))
    assert sell is not None
    assert float(sell.anchor_after) == pytest.approx(99.70)
    assert float(sell.qty) == pytest.approx(float(trade.qty))  # capped at holdings
    pos = session.scalar(select(GridPosition).where(GridPosition.symbol == "AAA"))
    assert pos is not None and float(pos.qty) == 0.0


def test_idempotent_per_symbol_and_session(session: Session, write_bars: BarWriter) -> None:
    write_bars("AAA", _CLOSES, _OPENS)
    _run(session, 1)
    _run(session, 2)
    first = _run(session, 3)
    assert first.buys == 1  # type: ignore[attr-defined]
    acct = session.scalar(select(PaperAccount).where(PaperAccount.name == "grid"))
    assert acct is not None
    cash_after_first = float(acct.cash)
    pos = session.scalar(select(GridPosition).where(GridPosition.symbol == "AAA"))
    assert pos is not None
    qty_after_first, anchor_after_first = float(pos.qty), float(pos.anchor_price)

    again = _run(session, 3)  # exact same session — must be a no-op
    assert again.buys == 0 and again.already_done == 1  # type: ignore[attr-defined]
    assert len(list(session.scalars(select(GridTradeRow)))) == 1
    session.refresh(acct)
    session.refresh(pos)
    assert float(acct.cash) == pytest.approx(cash_after_first)
    assert float(pos.qty) == pytest.approx(qty_after_first)
    assert float(pos.anchor_price) == pytest.approx(anchor_after_first)


def test_grid_trade_uniqueness_is_enforced_by_the_database(
    session: Session, write_bars: BarWriter
) -> None:
    from sqlalchemy.exc import IntegrityError

    write_bars("AAA", _CLOSES, _OPENS)
    _run(session, 1)
    _run(session, 2)
    _run(session, 3)
    row = session.scalar(select(GridTradeRow))
    assert row is not None
    session.add(
        GridTradeRow(
            account_id=row.account_id,
            symbol=row.symbol,
            side="sell",
            qty=row.qty,
            price=row.price,
            usd=row.usd,
            anchor_before=row.anchor_before,
            anchor_after=row.anchor_after,
            session_date=row.session_date,
            evidence_json={},
        )
    )
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()


def test_stale_and_missing_bars_are_reported_not_traded(
    session: Session, write_bars: BarWriter
) -> None:
    write_bars("AAA", _CLOSES, _OPENS)
    # AAA's last bar is d5; asking on d12 makes it 7 calendar days stale (> 5).
    res = run_grid_daily(
        session,
        cfg=_cfg(),
        as_of=_START + timedelta(days=12),
        symbols=["AAA", "NOPE"],
    )
    assert res.stale == 1 and res.no_data == 1  # type: ignore[attr-defined]
    assert not list(session.scalars(select(GridTradeRow)))

    # Far enough past the lookback window there are no bars at all — still no trade.
    far = run_grid_daily(session, cfg=_cfg(), as_of=_START + timedelta(days=90), symbols=["AAA"])
    assert far.no_data == 1 and far.trades == 0  # type: ignore[attr-defined]


def test_dedicated_account_is_separate_from_the_research_account(
    session: Session, write_bars: BarWriter
) -> None:
    from decimal import Decimal

    session.add(PaperAccount(name="default", initial_cash=Decimal("30000"), cash=Decimal("30000")))
    session.flush()
    write_bars("AAA", _CLOSES, _OPENS)
    _run(session, 1)
    _run(session, 2)
    _run(session, 3)

    default = session.scalar(select(PaperAccount).where(PaperAccount.name == "default"))
    grid = session.scalar(select(PaperAccount).where(PaperAccount.name == "grid"))
    assert default is not None and float(default.cash) == 30_000.0  # untouched
    assert grid is not None and float(grid.cash) < 1_000.0


def test_ensure_grid_account_is_idempotent(session: Session) -> None:
    cfg = _cfg()
    a = ensure_grid_account(session, cfg)
    b = ensure_grid_account(session, cfg)
    assert a.id == b.id
    assert float(a.initial_cash) == pytest.approx(float(cfg.starting_cash))


def test_grid_daily_is_registered_as_a_manual_job_and_chained_after_eod() -> None:
    import inspect

    from signalforge import scheduler as sched

    assert "grid_daily" in sched.MANUAL_JOBS
    assert sched.MANUAL_JOBS["grid_daily"] is sched.job_grid_daily
    src = inspect.getsource(sched.job_daily_eod_update)
    assert 'guarded("grid_daily", job_grid_daily)()' in src
    # It runs AFTER the approved-scope scan, on the freshly completed bars.
    assert src.index("approved_scope_scan") < src.index("grid_daily")


def test_grid_config_is_excluded_from_the_approval_scope_hash() -> None:
    from signalforge.config.research import ResearchConfig

    assert "grid" not in ResearchConfig.SCOPE_HASH_FIELDS
    base = ResearchConfig()
    changed = ResearchConfig(grid=GridConfig(enabled=True, per_symbol_cap=123.0))
    assert base.config_hash == changed.config_hash
    assert base.full_config_hash != changed.full_config_hash


def test_scheduled_job_is_a_no_op_while_disabled(db_url: str, write_bars: BarWriter) -> None:
    from signalforge.db.session import session_scope
    from signalforge.scheduler import job_grid_daily

    job_grid_daily()  # default config has research.grid.enabled = False
    with session_scope() as s:
        assert not list(s.scalars(select(GridTradeRow)))
        assert s.scalar(select(PaperAccount).where(PaperAccount.name == "grid")) is None
