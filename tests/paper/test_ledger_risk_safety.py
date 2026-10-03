"""Offline acceptance limits and accounting/temporal regression tests."""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select

from signalforge.db.models import Instrument, OHLCVDaily, PaperFill, PaperPosition, PaperTrade
from signalforge.domain import Direction, LatencyCategory, PositionSide
from signalforge.paper.ledger import accept_candidate, mark_to_market
from signalforge.settings_store import set_setting

ON = date(2024, 2, 1)


def accept(session, candidate, **kw):
    return accept_candidate(session, candidate.id, as_of=ON, **kw)


def holding(session, account, candidate, *, qty=1, price=100, sector="Tech", stop=99):
    inst = Instrument(
        symbol=f"HELD{len(list(session.scalars(select(Instrument))))}",
        name="held",
        instrument_type="stock",
        sector=sector,
    )
    session.add(inst)
    session.flush()
    pos = PaperPosition(
        account_id=account.id,
        instrument_id=inst.id,
        horizon=candidate.horizon,
        side=PositionSide.LONG,
        qty=qty,
        avg_price=Decimal(str(price)),
        stop_level=stop,
        opened_at=datetime(2024, 2, 1, tzinfo=UTC),
    )
    session.add(pos)
    session.flush()
    session.add(
        OHLCVDaily(
            instrument_id=inst.id,
            session_date=ON,
            open=price,
            high=price,
            low=price,
            close=price,
            adj_close=price,
            volume=1000000,
            source="fixture_held",
            is_adjusted=True,
            is_simulated=True,
            latency_category=LatencyCategory.HISTORICAL,
            ingested_at=datetime(2024, 2, 1, 21, 30, tzinfo=UTC),
            quality_flags=[],
        )
    )
    session.flush()
    return pos


def bar(session, candidate, day, *, open=100, high=101, low=99, close=100):
    session.add(
        OHLCVDaily(
            instrument_id=candidate.instrument_id,
            session_date=day,
            open=open,
            high=high,
            low=low,
            close=close,
            adj_close=close,
            volume=1000000,
            source="fixture_safety",
            is_adjusted=True,
            ingested_at=datetime.combine(day, datetime.min.time(), tzinfo=UTC).replace(
                hour=21, minute=30
            ),
            is_simulated=True,
            latency_category=LatencyCategory.HISTORICAL,
            quality_flags=[],
        )
    )
    session.flush()


@pytest.mark.parametrize("risk", [0, -1, float("nan"), float("inf"), 0.01])
def test_invalid_or_subshare_risk_never_falls_back(session, passing_candidate, account, risk):
    passing_candidate.risk_dollars = risk
    with pytest.raises(ValueError):
        accept(session, passing_candidate)
    assert account.cash == Decimal("10000")
    assert session.scalar(select(PaperTrade)) is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("direction", Direction.SHORT),
        ("invalidation_level", 100),
        ("invalidation_level", 101),
        ("entry_zone_low", float("inf")),
    ],
)
def test_invalid_long_plan_rejected(session, passing_candidate, field, value):
    setattr(passing_candidate, field, value)
    with pytest.raises(ValueError):
        accept(session, passing_candidate)


@pytest.mark.parametrize("slippage", [-1, float("nan"), float("inf")])
def test_invalid_slippage_rejected(session, passing_candidate, slippage):
    with pytest.raises(ValueError):
        accept(session, passing_candidate, slippage_bps=slippage)


def test_floor_uses_actual_rounded_fill_and_cash_pays_cost_once(
    session, passing_candidate, account
):
    passing_candidate.risk_dollars = 11.9  # old round(11.9 / 4) gave 3 shares
    res = accept(session, passing_candidate)
    fill = session.get(PaperFill, res.fill_id)
    assert res.shares == 2
    assert fill.price == Decimal("100.06")
    assert fill.price == Decimal(str(res.fill_price))
    assert (fill.price - Decimal("96")) * res.shares <= Decimal("11.9")
    assert account.cash == Decimal("10000") - fill.price * res.shares


def test_initial_position_cap_and_repeat_acceptance_share_same_symbol_budget(
    session, passing_candidate, account
):
    res = accept(session, passing_candidate)
    assert res.shares == 4  # 5% * 10000 / 100.06
    before = account.cash
    bar(session, passing_candidate, ON)  # current valid mark: rejection must be concentration
    with pytest.raises(ValueError, match="limits"):
        accept(session, passing_candidate)
    assert account.cash == before
    assert len(list(session.scalars(select(PaperTrade)))) == 1


@pytest.mark.parametrize(
    "key,value,shares",
    [
        ("max_position_concentration_pct", 2, 1),
        ("per_trade_risk_pct", 0.05, 1),
        ("max_portfolio_exposure_pct", 2, 1),
        ("max_correlated_exposure_pct", 2, 1),
        ("max_daily_portfolio_risk_pct", 0.05, 1),
    ],
)
def test_stricter_effective_override_wins(session, passing_candidate, key, value, shares):
    set_setting(session, "research_overrides", {"risk": {key: value}})
    assert accept(session, passing_candidate).shares == shares


def test_current_equity_not_initial_cash_or_candidate_context(session, passing_candidate, account):
    account.cash = Decimal("2000")
    passing_candidate.portfolio_context_json = {"account_equity": 1000000}
    with pytest.raises(ValueError, match="limits"):
        accept(session, passing_candidate)  # 5% of 2000 cannot fund a share at 100.06


def test_cash_and_reserved_collateral_limit_size(session, passing_candidate, account):
    set_setting(session, "research_overrides", {"risk": {"max_portfolio_exposure_pct": 100}})
    holding(session, account, passing_candidate, qty=99, sector="Other", stop=100)
    account.cash = Decimal("150")
    assert accept(session, passing_candidate).shares == 1
    assert account.cash == Decimal("49.94")


def test_reserved_collateral_is_not_spendable(session, passing_candidate, account):
    account.collateral_reserved = Decimal("9950")
    with pytest.raises(ValueError, match="limits"):
        accept(session, passing_candidate)
    assert account.cash == Decimal("10000")


@pytest.mark.parametrize("sector,expected", [("Tech", 0), (None, 4)])
def test_sector_cap_aggregates_known_sector(session, passing_candidate, account, sector, expected):
    # Equity = 10000; Tech already owns 1950 of its 2000 cap.
    holding(session, account, passing_candidate, qty=195, price=10, sector=sector, stop=10)
    account.cash = Decimal("8050")
    if expected:
        assert accept(session, passing_candidate).shares == expected
    else:
        with pytest.raises(ValueError, match="limits"):
            accept(session, passing_candidate)


def test_existing_open_risk_blocks_new_allocation(session, passing_candidate, account):
    holding(session, account, passing_candidate, qty=10, price=100, stop=80, sector="Other")
    account.cash = Decimal("9000")
    with pytest.raises(ValueError, match="limits"):
        accept(session, passing_candidate)


def test_no_preentry_or_same_day_high_low_lookahead(session, passing_candidate):
    passing_candidate.target_level = 100.5
    res = accept(session, passing_candidate)
    bar(session, passing_candidate, ON, high=120, low=80)
    assert mark_to_market(session, as_of=date(2024, 1, 31)).closed == 0
    assert mark_to_market(session, as_of=ON).closed == 0
    assert session.get(PaperPosition, res.position_id).closed_at is None


def test_first_eligible_stop_gap_and_costs_conserve_account_value(
    session, passing_candidate, account
):
    res = accept(session, passing_candidate)
    snapshot = dict(session.get(PaperTrade, res.paper_trade_id).plan_json)
    bar(session, passing_candidate, date(2024, 2, 2), open=90, high=95, low=89, close=94)
    bar(session, passing_candidate, date(2024, 2, 3), high=120, low=99, close=115)
    mtm = mark_to_market(session, as_of=date(2024, 2, 20))
    pos = session.get(PaperPosition, res.position_id)
    assert pos.closed_at.date() == date(2024, 2, 2)
    # Gap to 90, then one adverse spread/slippage adjustment: 89.95.
    assert pos.realized_pnl == (Decimal("89.95") - Decimal("100.06")) * res.shares
    assert account.cash == Decimal("10000") + pos.realized_pnl
    assert mtm.realized_pnl == float(pos.realized_pnl)
    assert session.get(PaperTrade, res.paper_trade_id).plan_json == snapshot
    assert mark_to_market(session, as_of=date(2024, 2, 20)).closed == 0


def test_stale_bar_does_not_trigger_future_time_stop(session, passing_candidate):
    res = accept(session, passing_candidate)
    bar(session, passing_candidate, date(2024, 2, 2))
    assert mark_to_market(session, as_of=date(2024, 2, 20)).closed == 0
    assert session.get(PaperPosition, res.position_id).closed_at is None


@pytest.fixture
def fresh_live(session, passing_candidate, monkeypatch):
    from signalforge.db.models import ScanRun
    from signalforge.paper import ledger

    now = datetime(2024, 2, 2, 22, tzinfo=UTC)
    monkeypatch.setattr(ledger, "utcnow", lambda: now)
    run = session.get(ScanRun, passing_candidate.scan_run_id)
    run.source = "fixture_safety"
    run.started_at = run.finished_at = passing_candidate.created_at = now
    bar(session, passing_candidate, date(2024, 2, 2))
    return now, run


def test_live_acceptance_records_source_and_freshness(session, passing_candidate, fresh_live):
    res = accept_candidate(session, passing_candidate.id)
    trade = session.get(PaperTrade, res.paper_trade_id)
    assert trade.plan_json["acceptance_context"]["market_date"] == "2024-02-02"
    assert trade.plan_json["acceptance_context"]["source"] == "fixture_safety"
    pos = session.get(PaperPosition, res.position_id)
    assert pos.opened_at == fresh_live[0]
    # The same day's already observed low cannot close this post-close entry.
    assert mark_to_market(session).closed == 0


@pytest.mark.parametrize("field", ["started_at", "finished_at", "created_at"])
@pytest.mark.parametrize("days", [-2, 1])
def test_live_rejects_stale_and_future_timestamps(
    session, passing_candidate, fresh_live, field, days
):
    from datetime import timedelta

    from signalforge.paper.ledger import AutoSimulateForbidden

    now, run = fresh_live
    setattr(passing_candidate if field == "created_at" else run, field, now + timedelta(days=days))
    with pytest.raises(AutoSimulateForbidden, match="timestamp"):
        accept_candidate(session, passing_candidate.id)
    assert session.scalar(select(PaperTrade)) is None


def test_live_cannot_substitute_another_sources_fresh_bar(session, passing_candidate, fresh_live):
    from signalforge.paper.ledger import AutoSimulateForbidden

    fresh_live[1].source = "massive_grouped"
    with pytest.raises(AutoSimulateForbidden, match="source-qualified"):
        accept_candidate(session, passing_candidate.id)


def test_weekend_uses_fridays_completed_bar(session, passing_candidate, fresh_live, monkeypatch):
    from signalforge.paper import ledger

    saturday = datetime(2024, 2, 3, 10, tzinfo=UTC)
    monkeypatch.setattr(ledger, "utcnow", lambda: saturday)
    res = accept_candidate(session, passing_candidate.id)
    assert (
        session.get(PaperTrade, res.paper_trade_id).plan_json["acceptance_context"]["market_date"]
        == "2024-02-02"
    )
    assert mark_to_market(session).closed == 0


def test_mark_uses_accepted_source_and_preserves_valid_chronology(
    session, passing_candidate, fresh_live, monkeypatch
):
    from signalforge.db.models import AuditLog
    from signalforge.paper import ledger

    res = accept_candidate(session, passing_candidate.id)
    bar(session, passing_candidate, date(2024, 2, 5), open=90, high=95, low=89, close=94)
    # Conflicting source cannot hide the stop.
    other = OHLCVDaily(
        instrument_id=passing_candidate.instrument_id,
        session_date=date(2024, 2, 5),
        open=100,
        high=120,
        low=99,
        close=115,
        adj_close=115,
        volume=10000,
        source="other",
        is_simulated=True,
        latency_category=LatencyCategory.HISTORICAL,
        ingested_at=datetime(2024, 2, 5, 22, tzinfo=UTC),
        quality_flags=[],
    )
    session.add(other)
    session.flush()
    monkeypatch.setattr(ledger, "utcnow", lambda: datetime(2024, 2, 5, 22, tzinfo=UTC))
    assert mark_to_market(session).closed == 1
    pos = session.get(PaperPosition, res.position_id)
    assert pos.closed_at > pos.opened_at
    assert pos.closed_at == datetime(2024, 2, 5, 21, tzinfo=UTC)
    audit = session.scalar(select(AuditLog).where(AuditLog.action == "paper.position_closed"))
    assert audit.after_json["source"] == "fixture_safety"
    assert audit.after_json["market_date"] == "2024-02-05"


def test_direct_automatic_acceptance_cannot_bypass_guard(session, passing_candidate):
    from signalforge.paper.ledger import AutoSimulateForbidden

    with pytest.raises(AutoSimulateForbidden, match="off"):
        accept(session, passing_candidate, actor="auto_simulate")


def test_automatic_fresh_acceptance_then_stale_replay_refusal(session, monkeypatch):
    from datetime import timedelta

    from signalforge.paper import ledger
    from signalforge.paper.ledger import AutoSimulateForbidden, assert_auto_simulate_allowed
    from signalforge.research import approval_scope
    from tests.paper.test_auto_simulate import SPEC_HASH, _seed

    now = datetime(2024, 2, 2, 22, tzinfo=UTC)
    monkeypatch.setattr(ledger, "utcnow", lambda: now)
    monkeypatch.setattr(approval_scope, "current_spec_json_hash", lambda _s, _v: SPEC_HASH)
    run, candidates = _seed(session)
    cand = candidates[0]
    run.started_at = run.finished_at = cand.created_at = now
    bar(session, cand, date(2024, 2, 2))
    # Bind to the actual approved source, not the generic helper's source.
    row = session.scalar(select(OHLCVDaily).where(OHLCVDaily.session_date == date(2024, 2, 2)))
    row.source = "massive"
    row.is_simulated = False
    set_setting(session, "auto_simulate_qualified_signals", True)
    assert_auto_simulate_allowed(session, cand)
    res = accept_candidate(session, cand.id, actor="auto_simulate")
    assert res.shares > 0
    monkeypatch.setattr(ledger, "utcnow", lambda: now + timedelta(days=3))
    with pytest.raises(AutoSimulateForbidden, match="stale"):
        assert_auto_simulate_allowed(session, cand)
    with pytest.raises(AutoSimulateForbidden, match="stale"):
        accept_candidate(session, cand.id, actor="auto_simulate")


def test_loose_config_is_narrowed_without_mutation_and_reduction_is_frozen(
    session, passing_candidate, account
):
    from signalforge.settings_store import effective_research_config

    set_setting(
        session,
        "research_overrides",
        {
            "risk": {
                "per_trade_risk_pct": 10,
                "max_daily_portfolio_risk_pct": 10,
                "max_position_concentration_pct": 10,
                "max_correlated_exposure_pct": 30,
            }
        },
    )
    before = effective_research_config(session).model_dump(mode="json")
    passing_candidate.risk_dollars = 1000
    passing_candidate.invalidation_level = 60
    res = accept(session, passing_candidate)
    assert res.shares == 1  # 0.5% risk ceiling, not the persisted 10%
    evidence = session.get(PaperTrade, res.paper_trade_id).plan_json["risk_decision"]
    assert evidence["effective_limits"]["per_trade_risk_pct"] == 0.5
    assert evidence["effective_limits"]["max_daily_portfolio_risk_pct"] == 1.5
    assert evidence["effective_limits"]["max_position_concentration_pct"] == 5
    assert evidence["effective_limits"]["max_correlated_exposure_pct"] == 20
    assert evidence["reduced"] is True
    assert "per_trade_risk" in evidence["binding_caps"]
    assert "per_trade_risk_pct" in evidence["limit_overrides_narrowed"]
    assert Decimal(evidence["accepted_risk_dollars"]) <= Decimal("50")
    assert effective_research_config(session).model_dump(mode="json") == before


def test_loose_aggregate_risk_config_cannot_exceed_one_point_five_percent(
    session, passing_candidate, account
):
    set_setting(session, "research_overrides", {"risk": {"max_daily_portfolio_risk_pct": 10}})
    holding(session, account, passing_candidate, qty=10, price=100, stop=85, sector="Other")
    account.cash = Decimal("9000")
    with pytest.raises(ValueError, match="limits"):
        accept(session, passing_candidate)


def test_preclose_partial_daily_bar_does_not_authorize_postclose_acceptance(
    session, passing_candidate, fresh_live
):
    from signalforge.paper.ledger import AutoSimulateForbidden

    row = session.scalar(select(OHLCVDaily).where(OHLCVDaily.session_date == date(2024, 2, 2)))
    row.ingested_at = datetime(2024, 2, 2, 20, tzinfo=UTC)
    with pytest.raises(AutoSimulateForbidden, match="source-qualified"):
        accept_candidate(session, passing_candidate.id)


def test_explicit_replay_has_consistent_fill_and_position_times(session, passing_candidate):
    from signalforge.db.models import PaperOrder

    res = accept(session, passing_candidate)
    pos = session.get(PaperPosition, res.position_id)
    fill = session.get(PaperFill, res.fill_id)
    order = session.get(PaperOrder, res.order_id)
    assert pos.opened_at == fill.filled_at == order.submitted_at
    assert pos.opened_at.date() == ON
    assert (
        session.get(PaperTrade, res.paper_trade_id).plan_json["acceptance_context"]["mode"]
        == "historical_replay"
    )


@pytest.mark.parametrize("fault", ["stale", "flagged", "unadjusted", "simulated_real_source"])
def test_existing_marks_must_be_current_clean_adjusted_and_source_appropriate(
    session, passing_candidate, account, fault
):
    pos = holding(session, account, passing_candidate, qty=10, sector="Other", stop=99)
    account.cash = Decimal("9000")
    row = session.scalar(select(OHLCVDaily).where(OHLCVDaily.instrument_id == pos.instrument_id))
    if fault == "stale":
        row.session_date = date(2024, 1, 31)
    elif fault == "flagged":
        row.quality_flags = ["suspect"]
    elif fault == "unadjusted":
        row.is_adjusted = False
    else:
        row.source = "massive"
    with pytest.raises(ValueError, match="mark"):
        accept(session, passing_candidate)
    assert session.scalar(select(PaperTrade)) is None


@pytest.mark.parametrize("fault", ["flagged", "unadjusted", "simulated_real_source"])
def test_live_acceptance_rechecks_bar_quality(session, passing_candidate, fresh_live, fault):
    from signalforge.paper.ledger import AutoSimulateForbidden

    row = session.scalar(select(OHLCVDaily).where(OHLCVDaily.session_date == date(2024, 2, 2)))
    if fault == "flagged":
        row.quality_flags = ["suspect"]
    elif fault == "unadjusted":
        row.is_adjusted = False
    else:
        row.source = fresh_live[1].source = "massive"
        session.flush()
    with pytest.raises(AutoSimulateForbidden, match="flagged, unadjusted or simulated"):
        accept_candidate(session, passing_candidate.id)


def test_higher_custom_slippage_is_budgeted_and_used_on_exit(session, passing_candidate, account):
    passing_candidate.risk_dollars = 10
    res = accept(session, passing_candidate, slippage_bps=100)
    trade = session.get(PaperTrade, res.paper_trade_id)
    risk = trade.plan_json["risk_decision"]
    assert risk["exit_slippage_bps"] == 100
    assert res.shares == 1  # two shares would exceed $10 including adverse stop fill
    assert Decimal(risk["accepted_risk_dollars"]) <= 10
    bar(session, passing_candidate, date(2024, 2, 2), open=100, low=95)
    mark_to_market(session, as_of=date(2024, 2, 2))
    pos = session.get(PaperPosition, res.position_id)
    assert pos.realized_pnl == -Decimal(risk["accepted_risk_dollars"])
    assert account.cash == Decimal("10000") + pos.realized_pnl


@pytest.mark.parametrize(
    "field,value",
    [
        ("quality_flags", ["vendor_mismatch"]),
        ("is_adjusted", False),
        ("high", float("inf")),
        ("low", 0),
        ("open", 200),
        ("volume", -1),
    ],
)
def test_bad_exit_history_never_changes_cash_or_closes(
    session, passing_candidate, account, field, value
):
    res = accept(session, passing_candidate)
    bar(session, passing_candidate, date(2024, 2, 2), open=90, high=95, low=89, close=94)
    row = session.scalar(
        select(OHLCVDaily).where(
            OHLCVDaily.instrument_id == passing_candidate.instrument_id,
            OHLCVDaily.session_date == date(2024, 2, 2),
        )
    )
    setattr(row, field, value)
    session.flush()
    cash = account.cash
    with pytest.raises(ValueError):
        mark_to_market(session, as_of=date(2024, 2, 5))
    assert account.cash == cash
    assert session.get(PaperPosition, res.position_id).closed_at is None


def test_simulated_bar_cannot_close_a_real_source_position(session, passing_candidate, account):
    from signalforge.db.models import ScanRun

    session.get(ScanRun, passing_candidate.scan_run_id).source = "massive"
    res = accept(session, passing_candidate)
    bar(session, passing_candidate, date(2024, 2, 2), open=90, high=95, low=89, close=94)
    row = session.scalar(
        select(OHLCVDaily).where(
            OHLCVDaily.instrument_id == passing_candidate.instrument_id,
            OHLCVDaily.session_date == date(2024, 2, 2),
        )
    )
    row.source = "massive"
    session.flush()
    cash = account.cash
    with pytest.raises(ValueError, match="untrusted"):
        mark_to_market(session, as_of=date(2024, 2, 5))
    assert account.cash == cash
    assert session.get(PaperPosition, res.position_id).closed_at is None
