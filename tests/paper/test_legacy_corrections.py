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

The tests in the first half exercise ``resolution="reopen"`` (kept available);
the VOID tests at the end exercise the default resolution (operator decision
2026-10-04: the two MSFT trades are voided, not re-opened).

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
from signalforge.paper.auto_simulate import _has_open_position
from signalforge.paper.corrections import voided_position_ids
from signalforge.paper.ledger import accept_candidate, mark_to_market
from signalforge.paper.legacy_corrections import (
    ACTOR,
    FIELD_CASH,
    FIELD_CLOSED_AT,
    FIELD_ENTRY_COST,
    FIELD_REALIZED,
    FIELD_VOID,
    FIELD_VOID_ENTRY_CASH,
    correct_legacy,
    find_invalid_exits,
)
from signalforge.paper.portfolio import portfolio_snapshot
from signalforge.research.health_monitor import closed_paper_r_multiples

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

    rep = correct_legacy(session, confirm=False, resolution="reopen")
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
    dry = correct_legacy(session, confirm=False, resolution="reopen")

    rep = correct_legacy(session, confirm=True, resolution="reopen")
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
    correct_legacy(session, confirm=True, resolution="reopen")
    session.commit()
    once = _state(session)

    again = correct_legacy(session, confirm=True, resolution="reopen")
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

    rep = correct_legacy(session, confirm=True, resolution="reopen")
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

    rep = correct_legacy(session, confirm=True, resolution="reopen")
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

    dry = runner.invoke(app, ["paper", "correct-legacy", "--dry-run", "--resolution", "reopen"])
    assert dry.exit_code == 0, dry.output
    assert "DRY RUN — nothing written" in dry.output
    assert "cash 29830.16 -> 24835.50" in dry.output
    assert "no order was placed" in dry.output
    assert _state(session) == before

    done = runner.invoke(app, ["paper", "correct-legacy", "--confirm", "--resolution", "reopen"])
    assert done.exit_code == 0, done.output
    assert "CONFIRMED — written" in done.output
    session.rollback()  # end this session's read snapshot; the CLI used its own session
    after = _state(session)
    assert after["cash"] == Decimal("24835.50") and after["corrections"] == 8


# --------------------------------------------------------------------------
# VOID — the default resolution (operator decision 2026-10-04)
#
# Hand arithmetic for the MSFT fixture (two legacy trades, same book):
#   legacy cash                                             29,830.16
#   trade A (a) exit proceeds back out: 5 * 516.45 - 83.50 = 2,498.75
#                                                        -> 27,331.41
#   trade A (b) entry notional returned: 5 * 516.45      = 2,582.25
#                                                        -> 29,913.66
#   trade B (a)                                - 2,498.75 -> 27,414.91
#   trade B (b)                                + 2,582.25 -> 29,997.16
#   double-counted pre-fix entry cost, 2 * 1.42 = + 2.84 -> 30,000.00
# i.e. cash is back at initial_cash: neither trade ever happened. No position
# is open before or after, so equity == cash: 29,830.16 -> 30,000.00 (+169.84
# = the two reversed -83.50 losses + the two 1.42 double-counted costs).
# --------------------------------------------------------------------------

VOID_CASH = Decimal("30000.00")


def _new_msft_candidate(session: Session) -> Candidate:
    """A fresh MSFT signal in the same book, identical in shape to the legacy one."""
    old = session.scalars(select(Candidate).order_by(Candidate.id)).first()
    assert old is not None
    cand = Candidate(
        scan_run_id=old.scan_run_id,
        instrument_id=old.instrument_id,
        strategy_version_id=old.strategy_version_id,
        horizon=old.horizon,
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
    return cand


def test_void_is_the_default_and_restores_cash_and_equity(session: Session) -> None:
    trade_ids = _seed(session, BARS)
    session.commit()
    before = _state(session)
    dry = correct_legacy(session, confirm=False)  # default resolution

    rep = correct_legacy(session, confirm=True)
    session.commit()
    after = _state(session)

    assert rep.resolution == "void" and dry.resolution == "void"
    assert rep.lines()[1:] == dry.lines()[1:]  # the dry run printed exactly what was done
    assert after["trades"] == before["trades"]  # paper_trade rows byte-for-byte untouched

    # Positions stay CLOSED (closed_at as recorded), realised P&L reversed to 0.
    assert [(c, r) for _pid, c, r, _ts in after["positions"]] == [  # type: ignore[union-attr]
        (datetime(2026, 9, 25, tzinfo=UTC), Decimal("0")),
        (datetime(2026, 9, 26, tzinfo=UTC), Decimal("0")),
    ]
    assert after["cash"] == VOID_CASH  # see the hand arithmetic above

    rows = session.scalars(select(TradeCorrection).order_by(TradeCorrection.id)).all()
    # per trade: realised, exit cash, entry cash, void status (4) + cost credit (1)
    assert len(rows) == 10 and rep.corrections_written == 10
    assert {r.actor for r in rows} == {ACTOR}
    by_trade = {
        tid: {r.field: (r.old_value, r.new_value) for r in rows if r.paper_trade_id == tid}
        for tid in trade_ids
    }
    first, second = (by_trade[t] for t in trade_ids)
    assert first == {
        FIELD_REALIZED: ("-83.50", "0.00"),  # (a)
        FIELD_CASH: ("29830.16", "27331.41"),  # (a) - 2,498.75
        FIELD_VOID_ENTRY_CASH: ("27331.41", "29913.66"),  # (b) + 2,582.25
        FIELD_VOID: ("closed", "void"),  # (c)
        FIELD_ENTRY_COST: ("1.42", "0.00"),  # (b) the double-counted cost
    }
    assert second == {
        FIELD_REALIZED: ("-83.50", "0.00"),
        FIELD_CASH: ("29913.66", "27414.91"),
        FIELD_VOID_ENTRY_CASH: ("27414.91", "29997.16"),
        FIELD_VOID: ("closed", "void"),
        FIELD_ENTRY_COST: ("1.42", "0.00"),
    }
    assert FIELD_CLOSED_AT not in first  # the position is not re-opened
    assert voided_position_ids(session) == {1, 2}
    assert rep.duplicates == [] and rep.exits == []

    # Book cash AND equity, before and after (no open position either side).
    assert rep.books == [
        {
            "account": "default",
            "cash_before": "29830.16",
            "cash_after": "30000.00",
            "delta": "+169.84",
            "equity_before": "29830.16",
            "equity_after": "30000.00",
            "equity_delta": "+169.84",
        }
    ]
    snap = portfolio_snapshot(session)
    assert snap["n_open"] == 0
    assert snap["equity_estimate"] == pytest.approx(30000.00)
    assert snap["realized_pnl"] == pytest.approx(0.0)
    # Nothing is open, so the next mark has nothing to do.
    mtm = mark_to_market(session)
    assert (mtm.checked, mtm.closed) == (0, 0)
    # A voided trade is not closed-trade performance evidence.
    ver = session.scalar(select(StrategyVersion))
    assert ver is not None
    assert closed_paper_r_multiples(session, ver.id) == []


def test_void_dry_run_prints_exact_rows_cash_and_equity_and_writes_nothing(
    session: Session,
) -> None:
    _seed(session, BARS)
    session.commit()
    before = _state(session)

    rep = correct_legacy(session, confirm=False)
    session.commit()

    assert _state(session) == before  # nothing at all was written
    assert voided_position_ids(session) == set()
    text = "\n".join(rep.lines())
    assert "DRY RUN — nothing written" in text
    assert "resolution for invalid legacy exits: void" in text
    assert "invalid legacy trades VOIDED: 2" in text
    assert "exit proceeds 2498.75 taken back; entry notional 2582.25 returned" in text
    assert (
        "book default: cash 29830.16 -> 30000.00 (delta +169.84); "
        "equity 29830.16 -> 30000.00 (delta +169.84)"
    ) in text
    assert "trade_correction rows: 10" in text
    # The exact rows, in write order.
    assert [
        (r["paper_trade_id"], r["field"], r["old_value"], r["new_value"]) for r in rep.rows
    ] == [
        (1, FIELD_REALIZED, "-83.50", "0.00"),
        (1, FIELD_CASH, "29830.16", "27331.41"),
        (1, FIELD_VOID_ENTRY_CASH, "27331.41", "29913.66"),
        (1, FIELD_VOID, "closed", "void"),
        (2, FIELD_REALIZED, "-83.50", "0.00"),
        (2, FIELD_CASH, "29913.66", "27414.91"),
        (2, FIELD_VOID_ENTRY_CASH, "27414.91", "29997.16"),
        (2, FIELD_VOID, "closed", "void"),
        (1, FIELD_ENTRY_COST, "1.42", "0.00"),
        (2, FIELD_ENTRY_COST, "1.42", "0.00"),
    ]
    for r in rep.rows:
        assert (
            f"row: paper_trade_id={r['paper_trade_id']} field={r['field']} "
            f"old={r['old_value']!r} new={r['new_value']!r}"
        ) in text


def test_void_is_idempotent_and_reopen_never_touches_a_voided_trade(session: Session) -> None:
    _seed(session, BARS)
    session.commit()
    correct_legacy(session, confirm=True)
    session.commit()
    once = _state(session)
    assert find_invalid_exits(session) == []  # voided rows are resolved

    for resolution in ("void", "reopen"):
        again = correct_legacy(session, confirm=True, resolution=resolution)  # type: ignore[arg-type]
        session.commit()
        assert again.changed is False and again.corrections_written == 0
        assert "nothing to correct" in "\n".join(again.lines())
        assert _state(session) == once


def test_voided_position_blocks_no_entry_and_counts_toward_no_cap(session: Session) -> None:
    """After the void, a new MSFT signal is sized as if the book were empty.

    Book: cash = equity = 30,000. Fill 516.17 * (1 + 0.00055) = 516.4539 -> 516.45;
    stop fill 499.75 * (1 - 0.00055) = 499.4751 -> 499.48; risk/share 16.97.
      candidate risk 84.85 / 16.97            -> 5
      per-trade 0.5% = 150 / 16.97            -> 8
      open risk 1.5% (configured) = 450/16.97 -> 26   (nothing open)
      symbol 10% = 3,000 / 516.45             -> 5    (nothing held in MSFT)
      sector 20% = 6,000 / 516.45             -> 11   (UNKNOWN bucket empty)
    => 5 shares. Had the two voided positions counted (10 sh * 517.53 = 5,175.30
    of MSFT, over the 3,000 symbol budget) no share would be allowed — which is
    exactly what ``reopen`` produces, asserted in the next test."""
    _seed(session, BARS)
    session.commit()
    correct_legacy(session, confirm=True)
    session.commit()
    acct = session.scalar(select(PaperAccount))
    inst = session.scalar(select(Instrument))
    assert acct is not None and inst is not None
    assert _has_open_position(session, acct.id, inst.id) is False  # does not block the symbol

    cand = _new_msft_candidate(session)
    res = accept_candidate(session, cand.id, as_of=date(2026, 10, 2))
    session.commit()

    assert res.shares == 5
    trade = session.scalars(select(PaperTrade).order_by(PaperTrade.id.desc())).first()
    assert trade is not None
    risk = trade.plan_json["risk_decision"]
    assert Decimal(risk["equity"]) == Decimal("30000")
    for key in ("gross_before", "open_risk_before", "symbol_before", "sector_before"):
        assert Decimal(risk[key]) == 0, key
    assert risk["share_caps"]["open_risk"] == 26
    assert risk["share_caps"]["symbol"] == 5
    assert risk["share_caps"]["sector"] == 11
    session.refresh(acct)
    assert acct.cash == Decimal("30000") - 5 * Decimal("516.45")
    # Only the new position is open; the voided ones stay closed and voided.
    open_ids = [
        p.id
        for p in session.scalars(select(PaperPosition).where(PaperPosition.closed_at.is_(None)))
    ]
    assert open_ids == [3]
    assert voided_position_ids(session) == {1, 2}


def test_reopen_by_contrast_fills_the_symbol_cap(session: Session) -> None:
    """Control for the test above: with ``reopen`` the same two positions are
    open exposure (5,175.30 of MSFT > the 10% symbol budget) and block the entry."""
    _seed(session, BARS)
    session.commit()
    correct_legacy(session, confirm=True, resolution="reopen")
    session.commit()
    cand = _new_msft_candidate(session)
    with pytest.raises(ValueError, match="limits"):
        accept_candidate(session, cand.id, as_of=date(2026, 10, 2))


def test_cli_defaults_to_void_and_validates_resolution(session: Session, db_url: str) -> None:
    _seed(session, BARS)
    session.commit()
    before = _state(session)
    runner = CliRunner()

    assert (
        runner.invoke(app, ["paper", "correct-legacy", "--dry-run", "--resolution", "x"]).exit_code
        == 2
    )
    assert (
        runner.invoke(
            app, ["paper", "correct-legacy", "--dry-run", "--void", "--resolution", "reopen"]
        ).exit_code
        == 2
    )

    for args in (["--dry-run"], ["--dry-run", "--void"], ["--dry-run", "--resolution", "void"]):
        dry = runner.invoke(app, ["paper", "correct-legacy", *args])
        assert dry.exit_code == 0, dry.output
        assert "DRY RUN — nothing written" in dry.output
        assert "invalid legacy trades VOIDED: 2" in dry.output
        assert "cash 29830.16 -> 30000.00" in dry.output
        assert "equity 29830.16 -> 30000.00" in dry.output
        assert "field=legacy_void.position.status old='closed' new='void'" in dry.output
        assert "no order was placed" in dry.output
        assert _state(session) == before

    done = runner.invoke(app, ["paper", "correct-legacy", "--confirm"])
    assert done.exit_code == 0, done.output
    assert "CONFIRMED — written" in done.output
    session.rollback()  # end this session's read snapshot; the CLI used its own session
    after = _state(session)
    assert after["cash"] == VOID_CASH and after["corrections"] == 10
    assert after["trades"] == before["trades"]
