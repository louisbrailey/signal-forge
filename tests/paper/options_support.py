"""Fixtures for the options paper suite (I-O6).

Everything is hand-built and SIMULATED. No real print, no real underlying bar, no
vendor row: every number the tests assert against is chosen here so the arithmetic
is reproducible on paper.

The structure is a SPY short put vertical, because that is decision 12's first
structure. The strikes and the underlying level are chosen so the whole book fits
inside decision 4's $250 per-structure cap at a 2-wide, which is what makes the
limit tests meaningful rather than incidental.
"""

from __future__ import annotations

import math
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from signalforge.backtest.options_costs import OptionCostModel
from signalforge.db.models import (
    Candidate,
    CandidateOptionStructure,
    Instrument,
    OHLCVDaily,
    OptionAggregateDaily,
    OptionContract,
    OptionsReconcileReport,
    PaperAccount,
    ScanRun,
    Strategy,
    StrategyVersion,
)
from signalforge.domain import (
    Direction,
    Horizon,
    LatencyCategory,
    QualityGate,
    StrategyStatus,
)
from signalforge.paper.options_ledger import (
    OPTIONS_STRUCTURE_KIND,
    OptionsPricingContext,
)

UNDERLYING = "SPY"
SPOT = 450.0
#: 2026-03-20 is the third Friday of March 2026 — an XNYS session, so
#: ``options_calendar.force_close_session`` resolves to the Thursday before it.
EXPIRY = date(2026, 3, 20)
SHORT_STRIKE = 430.0
LONG_STRIKE = 428.0
SHORT_TICKER = "O:SPY260320P00430000"
LONG_TICKER = "O:SPY260320P00428000"

#: Sessions used by the tests. 2026-02-17 and 2026-02-18 are a Tuesday and a
#: Wednesday (2026-02-16 is Presidents' Day), so signal -> fill is t -> t+1.
SIGNAL_SESSION = date(2026, 2, 17)
FILL_SESSION = date(2026, 2, 18)

OPTIONS_ACCOUNT = "options"
OPTIONS_ACCOUNT_CASH = Decimal("25000")


def cost_model(*, spread_multiplier: float = 1.0) -> OptionCostModel:
    """A deliberately cheap, explicit model. No field is defaulted (D2 §7.4): a
    zero-cost model makes gate 4b pass vacuously, because ``2 x 0 == 0``."""
    return OptionCostModel(
        commission_per_contract=0.65,
        commission_min_per_order=0.0,
        exchange_fee_per_contract=0.05,
        spread_pct_of_last_print=0.01,
        spread_abs_floor_cents=1.0,
        tick_grid=((math.inf, 0.01),),
        assignment_fee=0.0,
        exercise_fee=0.0,
        spread_multiplier=spread_multiplier,
    )


def pricing(*, spread_multiplier: float = 1.0, beta_to_spy: float = 1.0) -> OptionsPricingContext:
    return OptionsPricingContext(
        cost_model=cost_model(spread_multiplier=spread_multiplier),
        risk_free_rate=0.04,
        dividend_yield=0.013,
        q_source="fixture:trailing_12m_yield",
        beta_to_spy=beta_to_spy,
    )


def options_account(session: Session, *, cash: Decimal = OPTIONS_ACCOUNT_CASH) -> PaperAccount:
    """Decision 13's separate SIMULATED account. Created deliberately, never as a
    schema side effect."""
    acct = PaperAccount(name=OPTIONS_ACCOUNT, initial_cash=cash, cash=cash)
    session.add(acct)
    session.flush()
    return acct


def equity_account(session: Session, *, cash: Decimal = Decimal("30000")) -> PaperAccount:
    acct = PaperAccount(name="default", initial_cash=cash, cash=cash)
    session.add(acct)
    session.flush()
    return acct


def underlying(session: Session, *, symbol: str = UNDERLYING, close: float = SPOT) -> Instrument:
    """The UNDERLYING instrument, typed 'etf' — which is exactly why the equity
    guard's instrument-type check cannot discriminate an options candidate."""
    inst = Instrument(symbol=symbol, name=symbol, instrument_type="etf", sector="Broad Market")
    session.add(inst)
    session.flush()
    d = SIGNAL_SESSION - timedelta(days=20)
    while d <= EXPIRY + timedelta(days=5):
        session.add(
            OHLCVDaily(
                instrument_id=inst.id,
                session_date=d,
                open=close,
                high=close * 1.005,
                low=close * 0.995,
                close=close,
                volume=80_000_000,
                adj_close=close,
                source="fixture",
                latency_category=LatencyCategory.HISTORICAL,
                is_simulated=True,
                ingested_at=datetime.now(UTC),
                quality_flags=[],
            )
        )
        d += timedelta(days=1)
    session.flush()
    return inst


def contracts(session: Session, *, shares_per_contract: int = 100, style: str = "american") -> None:
    for ticker, strike in ((SHORT_TICKER, SHORT_STRIKE), (LONG_TICKER, LONG_STRIKE)):
        session.add(
            OptionContract(
                option_ticker=ticker,
                underlying_symbol=UNDERLYING,
                contract_type="put",
                strike_price=strike,
                expiration_date=EXPIRY,
                exercise_style=style,
                shares_per_contract=shares_per_contract,
                source="fixture",
                ingested_at=datetime.now(UTC),
            )
        )
    session.flush()


def option_prints(
    session: Session,
    *,
    sessions: list[date],
    short_close: float = 1.20,
    long_close: float = 0.70,
    skip: tuple[str, ...] = (),
) -> None:
    """Write one daily bar per contract per session. ``skip`` names tickers that
    DO NOT print — absence is a first-class liquidity fact, never a zero."""
    for d in sessions:
        for ticker, close in ((SHORT_TICKER, short_close), (LONG_TICKER, long_close)):
            if ticker in skip:
                continue
            session.add(
                OptionAggregateDaily(
                    option_ticker=ticker,
                    underlying_symbol=UNDERLYING,
                    session_date=d,
                    open=close,
                    high=close,
                    low=close,
                    close=close,
                    volume=1_000.0,
                    source="fixture",
                    latency_category=LatencyCategory.HISTORICAL,
                    ingested_at=datetime.now(UTC),
                    quality_flags=[],
                )
            )
    session.flush()


def legs_json(
    *, shares_per_contract: int = 100, style: str = "american"
) -> list[dict[str, object]]:
    return [
        {
            "option_ticker": SHORT_TICKER,
            "right": "put",
            "strike": SHORT_STRIKE,
            "expiration": EXPIRY.isoformat(),
            "qty_signed": -1,
            "shares_per_contract": shares_per_contract,
            "exercise_style": style,
        },
        {
            "option_ticker": LONG_TICKER,
            "right": "put",
            "strike": LONG_STRIKE,
            "expiration": EXPIRY.isoformat(),
            "qty_signed": 1,
            "shares_per_contract": shares_per_contract,
            "exercise_style": style,
        },
    ]


def approved_strategy(
    session: Session,
    *,
    status: StrategyStatus = StrategyStatus.PAPER_APPROVED,
    spec_json: dict[str, object] | None = None,
) -> StrategyVersion:
    strat = Strategy(
        name="options_short_vertical.position", horizon=Horizon.POSITION, status=status
    )
    session.add(strat)
    session.flush()
    ver = StrategyVersion(
        strategy_id=strat.id,
        version="0.1.0",
        status=status,
        spec_json=spec_json if spec_json is not None else {},
        git_sha="fixture",
    )
    session.add(ver)
    session.flush()
    return ver


def options_candidate(
    session: Session,
    *,
    instrument: Instrument,
    version: StrategyVersion,
    structure_kind: str | None = OPTIONS_STRUCTURE_KIND,
    structure_type: str = "vertical_credit",
    gate: QualityGate = QualityGate.PASSED,
    direction: Direction = Direction.SHORT,
    contracts_n: int = 1,
    shares_per_contract: int = 100,
    style: str = "american",
    with_structure_row: bool = True,
) -> Candidate:
    run = ScanRun(
        horizon=Horizon.POSITION,
        started_at=datetime.now(UTC),
        finished_at=datetime.now(UTC),
        config_hash="cfg",
        source="fixture",
        dataset_snapshot_id=None,
    )
    session.add(run)
    session.flush()
    cand = Candidate(
        scan_run_id=run.id,
        instrument_id=instrument.id,
        strategy_version_id=version.id,
        horizon=Horizon.POSITION,
        direction=direction,
        entry_zone_low=SPOT - 1.0,
        entry_zone_high=SPOT + 1.0,
        invalidation_level=SHORT_STRIKE,
        target_level=SPOT + 10.0,
        target_logic="credit capture",
        time_stop_days=30,
        reward_risk_estimate=0.5,
        risk_dollars=200.0,
        risk_pct_of_account=0.8,
        liquidity_json={"last_price": SPOT},
        slippage_assumption_json={"modelled": True},
        event_risk_json={"upcoming_earnings": []},
        portfolio_context_json={},
        data_freshness_json={"fresh": True},
        ranking_json={"score": 0.5},
        reasons_qualify=["regime filter passed"],
        reasons_fail=["short premium is short gamma"],
        quality_gate_status=gate,
        failed_gates=[] if gate is QualityGate.PASSED else ["liquidity"],
        rank_in_horizon=1,
        structure_kind=structure_kind,
    )
    session.add(cand)
    session.flush()
    if with_structure_row:
        session.add(
            CandidateOptionStructure(
                candidate_id=cand.id,
                structure_type=structure_type,
                underlying_symbol=UNDERLYING,
                contracts=contracts_n,
                legs_json=legs_json(shares_per_contract=shares_per_contract, style=style),
                net_premium=50.0,
                max_loss_dollars=150.0,
                max_gain_dollars=50.0,
                break_evens_json=[SHORT_STRIKE - 0.5],
                short_leg_delta=-0.18,
                net_delta_shares=8.0,
                net_vega_per_vol_pt=-4.0,
                credit_to_width=0.25,
                dte_at_entry=(EXPIRY - FILL_SESSION).days,
                signal_session=SIGNAL_SESSION,
                fill_session=FILL_SESSION,
            )
        )
        session.flush()
    return cand


def clean_reconcile_report(session: Session, account: PaperAccount, *, as_of: date) -> None:
    """Condition AA is POSITIVE and DATED: without this row the guard refuses."""
    session.add(
        OptionsReconcileReport(
            account_id=account.id,
            as_of=as_of,
            clean=True,
            findings_json=[],
            collateral_reserved_observed=account.collateral_reserved,
            collateral_reserved_expected=account.collateral_reserved,
            open_structures=0,
        )
    )
    session.flush()


def approve_scope(
    session: Session,
    cand: Candidate,
    version: StrategyVersion,
    *,
    snapshot_key: str = "fixture-options-snapshot",
) -> None:
    """Make the five-part equity scope match pass for this candidate's scan.

    The scope machinery compares a live scan against a PASSING promotion
    evaluation on dataset snapshot, config hash, spec hash, source and the exact
    universe. Everything here is a fixture row; nothing is a real evaluation.
    """
    from sqlalchemy import select

    from signalforge.db.models import DataSnapshot, StrategyPromotionEvaluation
    from signalforge.research.approval_scope import current_spec_json_hash

    snap = session.scalar(select(DataSnapshot).where(DataSnapshot.key == snapshot_key))
    if snap is None:
        snap = DataSnapshot(key=snapshot_key, symbols_json=[UNDERLYING])
        session.add(snap)
        session.flush()
    run = session.get(ScanRun, cand.scan_run_id)
    assert run is not None
    run.dataset_snapshot_id = snap.id
    run.universe_json = [UNDERLYING]
    session.add(
        StrategyPromotionEvaluation(
            strategy_version_id=version.id,
            evaluated_at=datetime.now(UTC),
            passed=True,
            gates_json=[],
            dataset_snapshot_id=snap.id,
            config_hash=run.config_hash,
            spec_json_hash=current_spec_json_hash(session, version.id) or "",
            universe_json=[UNDERLYING],
            window_start=SIGNAL_SESSION - timedelta(days=365),
            window_end=SIGNAL_SESSION,
            data_provenance_json={"sources": [run.source]},
        )
    )
    session.flush()
