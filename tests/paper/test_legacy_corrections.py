"""``signalforge paper correct-legacy``: append-only repair of legacy ledger rows.

The fixture reproduces the live MSFT case from the 2026-10-03 forward-validation
report, with rows written exactly as the pre-2026-10-02 ledger wrote them:

* trade A: MSFT x5 filled 516.45 after the 2026-09-25 close, stop 499.75. The old
  mark tested the ENTRY-day bar (low 497.25 < stop) and closed it at 00:00 UTC on
  2026-09-25 — before it was opened — for (499.75 - 516.45) * 5 = -83.50.
* trade B: the same signal re-emitted by a Saturday re-scan (2026-09-26), opened
  and "stopped" the same way.
* both entries were debited notional + cost although the cost was already inside
  the fill price: 0.65 spread + 0.77 slippage = 1.42 double-counted, each.

Legacy cash, by hand: 30,000 - 2 * (5 * 516.45 + 1.42) + 2 * (5 * 499.75)
= 30,000 - 5,167.34 + 4,997.50 = 29,830.16.

Offline: fixture bars only; the live database is never opened.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from typer.testing import CliRunner

from signalforge.cli import app
from signalforge.db.models import (
    AuditLog,
    Candidate,
    Instrument,
    OHLCVDaily,
    PaperAccount,
    PaperFill,
    PaperOrder,
    PaperPosition,
    PaperTrade,
    ScanRun,
    Strategy,
    StrategyVersion,
    TradeCorrection,
)
from signalforge.domain import (
    Direction,
    Horizon,
    LatencyCategory,
    PaperDecision,
    PositionSide,
    QualityGate,
)
from signalforge.paper import ledger
from signalforge.paper.ledger import mark_to_market
from signalforge.paper.legacy_corrections import (
    ACTOR,
    FIELD_CASH,
    FIELD_CLOSED_AT,
    FIELD_ENTRY_COST,
    FIELD_REALIZED,
    correct_legacy,
    find_invalid_exits,
)

SOURCE = "fixture_legacy"
NOW = datetime(2026, 10, 3, 12, 0, tzinfo=UTC)  # Saturday; the 10-02 bar is complete
LEGACY_CASH = Decimal("29830.16")

#: (session, open, high, low, close). The 09-25 low is BELOW the 499.75 stop —
#: that is the entry-day bar the old ledger wrongly tested. No later bar touches
#: the stop (lows >= 505) or the 549.01 target.
BARS = [
    (date(2026, 9, 25), 515.0, 518.0, 497.25, 516.0),
    (date(2026, 9, 28), 516.0, 519.0, 508.0, 512.0),
    (date(2026, 9, 29), 512.0, 515.0, 505.0, 510.0),
    (date(2026, 9, 30), 510.0, 514.0, 506.0, 513.0),
    (date(2026, 10, 1), 513.0, 518.0, 509.0, 515.0),
    (date(2026, 10, 2), 515.0, 519.0, 512.0, 517.53),
]


@pytest.fixture(autouse=True)
def _frozen_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ledger, "utcnow", lambda: NOW)


def _legacy_trade(
    session: Session,
    acct: PaperAccount,
    inst: Instrument,
    ver: StrategyVersion,
    run: ScanRun,
    opened_at: datetime,
    *,
    post_fix: bool = False,
) -> PaperTrade:
    cand = Candidate(
        scan_run_id=run.id,
        instrument_id=inst.id,
        strategy_version_id=ver.id,
        horizon=Horizon.MEDIUM_SWING,
        direction=Direction.LONG,
        entry_zone_low=515.17,
        entry_zone_high=517.17,
        invalidation_level=499.75,
        target_level=549.01,
        target_logic="entry + 3 ATR",
        time_stop_days=40,
        reward_risk_estimate=2.0,
        risk_dollars=84.85,
        risk_pct_of_account=0.28,
        liquidity_json={},
        slippage_assumption_json={},
        event_risk_json={},
        portfolio_context_json={},
        data_freshness_json={},
        ranking_json={},
        reasons_qualify=["trend"],
        reasons_fail=["gap"],
        quality_gate_status=QualityGate.PASSED,
        failed_gates=[],
        rank_in_horizon=1,
    )
    session.add(cand)
    session.flush()
    order = PaperOrder(
        account_id=acct.id,
        candidate_id=cand.id,
        instrument_id=inst.id,
        side=PositionSide.LONG,
        qty=5,
        order_type="market",
        submitted_at=opened_at,
        assumptions_json={"reference_price": 516.17},
    )
    session.add(order)
    session.flush()
    session.add(
        PaperFill(
            order_id=order.id,
            price=Decimal("516.45"),
            qty=5,
            spread_cost=Decimal("0.65"),
            slippage=Decimal("0.77"),
            commission=Decimal("0"),
            filled_at=opened_at,
        )
    )
    entry_day = opened_at.date()
    pos = PaperPosition(
        account_id=acct.id,
        instrument_id=inst.id,
        strategy_version_id=ver.id,
        horizon=Horizon.MEDIUM_SWING,
        side=PositionSide.LONG,
        qty=5,
        avg_price=Decimal("516.45"),
        stop_level=499.75,
        target_level=549.01,
        # the old rule: entry + 40 CALENDAR days
        time_stop_date=datetime(2026, 11, 4, tzinfo=UTC),
        opened_at=opened_at,
        # the defect: closed at 00:00 UTC of the entry day, before it was opened.
        # (A post-fix row instead closes at a LATER session's 16:00 ET close.)
        closed_at=(
            datetime(2026, 9, 30, 20, 0, tzinfo=UTC)
            if post_fix
            else datetime(entry_day.year, entry_day.month, entry_day.day, tzinfo=UTC)
        ),
        realized_pnl=Decimal("-83.50"),
    )
    session.add(pos)
    session.flush()
    trade = PaperTrade(
        account_id=acct.id,
        candidate_id=cand.id,
        position_id=pos.id,
        decision=PaperDecision.ACCEPTED,
        signal_snapshot_json={"scan": {"source": SOURCE}, "symbol": inst.symbol},
        # pre-fix plan: no ``risk_decision`` — that is how a legacy row is recognised
        plan_json={"time_stop_days": 40, "shares": 5, "fill_price": 516.45}
        | ({"risk_decision": {"policy": "conservative-long-only-v1"}} if post_fix else {}),
        actor="auto_simulate",
        created_at=opened_at,
    )
    session.add(trade)
    session.flush()
    return trade


def _seed(session: Session, bars: list[tuple[date, float, float, float, float]]) -> list[int]:
    acct = PaperAccount(name="default", initial_cash=Decimal("30000"), cash=LEGACY_CASH)
    inst = Instrument(symbol="MSFT", name="Microsoft", instrument_type="stock", sector="")
    strat = Strategy(name="tc", horizon=Horizon.MEDIUM_SWING)
    session.add_all([acct, inst, strat])
    session.flush()
    ver = StrategyVersion(strategy_id=strat.id, version="0.3.0", git_sha="x", spec_json={})
    run = ScanRun(
        horizon=Horizon.MEDIUM_SWING,
        started_at=datetime(2026, 9, 25, 21, 30, tzinfo=UTC),
        config_hash="h",
        source=SOURCE,
    )
    session.add_all([ver, run])
    session.flush()
    for d, o, h, low, c in bars:
        session.add(
            OHLCVDaily(
                instrument_id=inst.id,
                session_date=d,
                open=o,
                high=h,
                low=low,
                close=c,
                volume=20_000_000,
                adj_close=c,
                source=SOURCE,
                latency_category=LatencyCategory.HISTORICAL,
                is_simulated=True,
                is_adjusted=True,
                ingested_at=datetime(2026, 10, 2, 21, 30, tzinfo=UTC),
                quality_flags=[],
            )
        )
    a = _legacy_trade(session, acct, inst, ver, run, datetime(2026, 9, 25, 21, 31, tzinfo=UTC))
    b = _legacy_trade(session, acct, inst, ver, run, datetime(2026, 9, 26, 21, 30, tzinfo=UTC))
    session.flush()
    return [a.id, b.id]


def _trade_rows(session: Session) -> str:
    rows = session.scalars(select(PaperTrade).order_by(PaperTrade.id)).all()
    return json.dumps(
        [
            [
                t.id,
                t.account_id,
                t.candidate_id,
                t.position_id,
                t.decision.value,
                t.signal_snapshot_json,
                t.plan_json,
                t.actor,
                t.created_at.isoformat(),
            ]
            for t in rows
        ],
        sort_keys=True,
    )


def _state(session: Session) -> dict[str, object]:
    session.expire_all()
    acct = session.scalar(select(PaperAccount).where(PaperAccount.name == "default"))
    assert acct is not None
    return {
        "cash": Decimal(acct.cash),
        "positions": [
            (p.id, p.closed_at, Decimal(p.realized_pnl), p.time_stop_date)
            for p in session.scalars(select(PaperPosition).order_by(PaperPosition.id))
        ],
        "corrections": session.scalar(select(func.count()).select_from(TradeCorrection)),
        "audits": session.scalar(select(func.count()).select_from(AuditLog)),
        "trades": _trade_rows(session),
    }


def test_finder_selects_only_exits_not_after_the_entry_bar(session: Session) -> None:
    ids = _seed(session, BARS)
    found = find_invalid_exits(session)
    assert [t.id for _, t in found] == ids
    for pos, _ in found:
        assert pos.closed_at is not None and pos.closed_at.date() <= pos.opened_at.date()


def test_dry_run_reports_every_change_and_writes_nothing(session: Session) -> None:
    _seed(session, BARS)
    session.commit()
    before = _state(session)

    rep = correct_legacy(session, confirm=False)
    session.commit()

    assert _state(session) == before  # nothing at all was written
    assert rep.confirm is False and len(rep.exits) == 2 and len(rep.entry_costs) == 2
    text = "\n".join(rep.lines())
    assert "DRY RUN — nothing written" in text
    assert "exit proceeds 2498.75 taken back" in text
    assert "re-opened" in text
    assert "+1.42" in text
    # 29,830.16 - 2 * 2,498.75 + 2 * 1.42 = 24,835.50 (= 30,000 - 2 * 2,582.25)
    assert "cash 29830.16 -> 24835.50 (delta -4994.66)" in text
    assert "WARNING duplicate open positions after correction: MSFT" in text


def test_confirm_reverses_the_invalid_exits_and_credits_the_double_counted_costs(
    session: Session,
) -> None:
    trade_ids = _seed(session, BARS)
    session.commit()
    before = _state(session)
    dry = correct_legacy(session, confirm=False)

    rep = correct_legacy(session, confirm=True)
    session.commit()
    after = _state(session)

    # The dry run printed exactly what --confirm then did.
    assert rep.lines()[1:] == dry.lines()[1:]

    # paper_trade rows (immutable, S9) are byte-for-byte untouched.
    assert after["trades"] == before["trades"]

    # Both positions are open again under the corrected chronology: no bar AFTER
    # entry reaches the stop or target. Time stop is now the 40th session after
    # entry: Sep 28-30 (3), Oct 1-2 (5), Oct 5-30 (25), Nov 2-20 (40) = 2026-11-20.
    for _pid, closed_at, realized, time_stop in after["positions"]:  # type: ignore[union-attr]
        assert closed_at is None
        assert realized == Decimal("0")
        assert time_stop == datetime(2026, 11, 20, tzinfo=UTC)

    # Cash: 29,830.16 - 2 * 2,498.75 (proceeds back out) + 2 * 1.42 (cost credit)
    # = 24,835.50 = 30,000 - 2 * (5 * 516.45): initial cash less the two open notionals.
    assert after["cash"] == Decimal("24835.50")

    rows = session.scalars(select(TradeCorrection).order_by(TradeCorrection.id)).all()
    assert len(rows) == 8 and rep.corrections_written == 8
    assert {r.actor for r in rows} == {ACTOR}
    by_trade = {
        tid: {r.field: (r.old_value, r.new_value) for r in rows if r.paper_trade_id == tid}
        for tid in trade_ids
    }
    first, second = (by_trade[t] for t in trade_ids)
    assert first[FIELD_CLOSED_AT] == ("2026-09-25T00:00:00+00:00", "")
    assert first[FIELD_REALIZED] == ("-83.50", "0.00")
    assert first[FIELD_CASH] == ("29830.16", "27331.41")  # - 2,498.75
    assert second[FIELD_CLOSED_AT] == ("2026-09-26T00:00:00+00:00", "")
    assert second[FIELD_CASH] == ("27331.41", "24832.66")  # - 2,498.75
    for fields in (first, second):
        assert fields[FIELD_ENTRY_COST] == ("1.42", "0.00")
    assert all("Original paper_trade untouched" in r.reason for r in rows if "exit" in r.field)

    # The duplicate is reported, not silently merged or voided.
    assert rep.duplicates == [
        {"account": "default", "symbol": "MSFT", "position_ids": [1, 2], "qty": 10}
    ]

    # The re-opened positions are ordinary open positions for the next mark:
    # unrealized = (517.53 - 516.45) * 5 * 2 = 10.80.
    mtm = mark_to_market(session)
    assert (mtm.checked, mtm.closed) == (2, 0)
    assert mtm.unrealized_pnl == pytest.approx(10.80)


def test_confirm_is_idempotent(session: Session) -> None:
    _seed(session, BARS)
    session.commit()
    correct_legacy(session, confirm=True)
    session.commit()
    once = _state(session)

    again = correct_legacy(session, confirm=True)
    session.commit()

    assert again.changed is False and again.corrections_written == 0
    assert "nothing to correct" in "\n".join(again.lines())
    assert _state(session) == once


def test_position_stopped_on_a_later_bar_is_re_resolved_not_left_open(session: Session) -> None:
    """Corrected chronology can still END in a stop — on a bar after entry.

    09-29 now trades down to 495 (open 512): stop 499.75 is hit that day. Exit
    fill = min(499.75, 512) * (1 - 0.00055) = 499.4751 -> 499.48; realized =
    (499.48 - 516.45) * 5 = -84.85; the close is stamped at that session's
    16:00 ET close (20:00 UTC)."""
    bars = [b if b[0] != date(2026, 9, 29) else (b[0], 512.0, 515.0, 495.0, 498.0) for b in BARS]
    trade_ids = _seed(session, bars)
    session.commit()

    rep = correct_legacy(session, confirm=True)
    session.commit()
    state = _state(session)

    for _pid, closed_at, realized, _ts in state["positions"]:  # type: ignore[union-attr]
        assert closed_at == datetime(2026, 9, 29, 20, 0, tzinfo=UTC)
        assert realized == Decimal("-84.85")
    # 30,000 - 2 * 2,582.25 (entries) + 2 * 2,497.40 (valid exits) = 29,830.30
    assert state["cash"] == Decimal("29830.30")
    assert all("re-resolved: closed 2026-09-29" in e["outcome"] for e in rep.exits)
    assert rep.duplicates == []
    row = session.scalar(
        select(TradeCorrection).where(
            TradeCorrection.paper_trade_id == trade_ids[0],
            TradeCorrection.field == FIELD_REALIZED,
        )
    )
    assert row is not None and (row.old_value, row.new_value) == ("-83.50", "-84.85")
    # Chronology is now valid everywhere: no exit on or before its entry day.
    assert find_invalid_exits(session) == []
    closes = session.scalars(
        select(AuditLog).where(AuditLog.action == "paper.position_closed")
    ).all()
    assert {a.after_json["market_date"] for a in closes} == {"2026-09-29"}


def test_post_fix_trades_are_not_credited_and_valid_exits_are_not_reversed(
    session: Session,
) -> None:
    """A trade written by the current ledger (``risk_decision`` in its plan) paid
    its cost once, and an exit on a bar after entry is valid: neither is touched."""
    legacy_ids = _seed(session, BARS)
    acct = session.scalar(select(PaperAccount))
    inst = session.scalar(select(Instrument))
    ver = session.scalar(select(StrategyVersion))
    run = session.scalar(select(ScanRun))
    assert acct is not None and inst is not None and ver is not None and run is not None
    modern = _legacy_trade(
        session, acct, inst, ver, run, datetime(2026, 9, 28, 21, 30, tzinfo=UTC), post_fix=True
    )
    session.commit()

    rep = correct_legacy(session, confirm=True)
    session.commit()

    assert [e["paper_trade_id"] for e in rep.exits] == legacy_ids
    assert [c["paper_trade_id"] for c in rep.entry_costs] == legacy_ids
    pos = session.get(PaperPosition, modern.position_id)
    assert pos is not None
    session.refresh(pos)
    assert pos.closed_at == datetime(2026, 9, 30, 20, 0, tzinfo=UTC)
    assert pos.realized_pnl == Decimal("-83.50")
    assert (
        session.scalar(
            select(func.count())
            .select_from(TradeCorrection)
            .where(TradeCorrection.paper_trade_id == modern.id)
        )
        == 0
    )


def test_cli_requires_exactly_one_mode_and_dry_run_writes_nothing(
    session: Session, db_url: str
) -> None:
    _seed(session, BARS)
    session.commit()
    before = _state(session)
    runner = CliRunner()

    assert runner.invoke(app, ["paper", "correct-legacy"]).exit_code == 2
    assert runner.invoke(app, ["paper", "correct-legacy", "--dry-run", "--confirm"]).exit_code == 2
    assert _state(session) == before

    dry = runner.invoke(app, ["paper", "correct-legacy", "--dry-run"])
    assert dry.exit_code == 0, dry.output
    assert "DRY RUN — nothing written" in dry.output
    assert "cash 29830.16 -> 24835.50" in dry.output
    assert "no order was placed" in dry.output
    assert _state(session) == before

    done = runner.invoke(app, ["paper", "correct-legacy", "--confirm"])
    assert done.exit_code == 0, done.output
    assert "CONFIRMED — written" in done.output
    session.rollback()  # end this session's read snapshot; the CLI used its own session
    after = _state(session)
    assert after["cash"] == Decimal("24835.50") and after["corrections"] == 8
