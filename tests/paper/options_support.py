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
from collections.abc import Mapping
from dataclasses import dataclass, field
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
from signalforge.paper.options_marks import UnderlyingNotPriceable

UNDERLYING = "SPY"
SPOT = 450.0
#: 2026-03-20 is the third Friday of March 2026 — an XNYS session, so
#: ``options_calendar.force_close_session`` resolves to the Thursday before it.
EXPIRY = date(2026, 3, 20)
SHORT_STRIKE = 430.0
LONG_STRIKE = 428.0
SHORT_TICKER = "O:SPY260320P00430000"
LONG_TICKER = "O:SPY260320P00428000"

#: A SECOND name, for the multi-underlying book W5b's resolver exists to price.
#: Same strikes and same prints, so any difference a test observes between the
#: two books comes from the pricing context and from nothing else.
UNDERLYING_2 = "IWM"


def tickers_for(symbol: str) -> tuple[str, str]:
    """``(short, long)`` OCC tickers for ``symbol`` at the fixture's strikes."""
    return (f"O:{symbol}260320P00430000", f"O:{symbol}260320P00428000")


#: Sessions used by the tests. 2026-02-17 and 2026-02-18 are a Tuesday and a
#: Wednesday (2026-02-16 is Presidents' Day), so signal -> fill is t -> t+1.
SIGNAL_SESSION = date(2026, 2, 17)
FILL_SESSION = date(2026, 2, 18)

OPTIONS_ACCOUNT = "options"
OPTIONS_ACCOUNT_CASH = Decimal("25000")

#: The ONE source label every fixture row is written under — bars, contracts and
#: prints alike — and therefore the label every read must name. Rows seeded under
#: any other label (see ``test_options_price_sources``) must never be read.
BAR_SOURCE = "fixture"
OPTION_SOURCE = "fixture"


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


def pricing(
    *,
    spread_multiplier: float = 1.0,
    beta_to_spy: float = 1.0,
    dividend_yield: float = 0.013,
    q_source: str = "fixture:trailing_12m_yield",
    underlying_source: str = BAR_SOURCE,
) -> OptionsPricingContext:
    """ONE underlying's context — what the guard and the acceptance take.

    A candidate has exactly one underlying, so a single context is the honest
    shape there. The MARK, EXPIRY and AUTO-SIM jobs take a
    :class:`PricingContextResolver` instead, because they span a book: use
    :func:`resolver` for those.
    """
    return OptionsPricingContext(
        cost_model=cost_model(spread_multiplier=spread_multiplier),
        risk_free_rate=0.04,
        dividend_yield=dividend_yield,
        q_source=q_source,
        underlying_source=underlying_source,
        beta_to_spy=beta_to_spy,
    )


@dataclass(frozen=True)
class FixtureResolver:
    """A hand-built :class:`PricingContextResolver`, per underlying.

    Deliberately NOT ``ResolvedPricing``: that type pins the session it was
    resolved for, which is right in production and wrong in a fixture that marks
    the same book on half a dozen sessions. Everything else is the same contract
    — a name it does not carry is refused BY NAME, never answered with another
    name's ``q``.
    """

    contexts: Mapping[str, OptionsPricingContext]
    unpriceable: Mapping[str, str] = field(default_factory=dict)

    def __call__(self, underlying: str, as_of: date) -> OptionsPricingContext:
        ctx = self.contexts.get(underlying)
        if ctx is not None:
            return ctx
        raise UnderlyingNotPriceable(
            underlying,
            self.unpriceable.get(underlying, "fixture: no context was built for this underlying"),
        )

    @property
    def unpriceable_underlyings(self) -> tuple[str, ...]:
        return tuple(sorted(self.unpriceable))


def resolver(
    *,
    spread_multiplier: float = 1.0,
    beta_to_spy: float = 1.0,
    contexts: Mapping[str, OptionsPricingContext] | None = None,
    unpriceable: Mapping[str, str] | None = None,
) -> FixtureResolver:
    """The default one-name book: SPY, with the fixture's explicit context."""
    if contexts is None:
        contexts = {
            UNDERLYING: pricing(spread_multiplier=spread_multiplier, beta_to_spy=beta_to_spy)
        }
    return FixtureResolver(contexts=dict(contexts), unpriceable=dict(unpriceable or {}))


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


def underlying(
    session: Session,
    *,
    symbol: str = UNDERLYING,
    close: float = SPOT,
    source: str = BAR_SOURCE,
    instrument: Instrument | None = None,
) -> Instrument:
    """The UNDERLYING instrument, typed 'etf' — which is exactly why the equity
    guard's instrument-type check cannot discriminate an options candidate.

    ``source`` labels the bars; pass ``instrument`` to add a SECOND source's bars
    to an instrument that already exists."""
    inst = instrument
    if inst is None:
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
                source=source,
                latency_category=LatencyCategory.HISTORICAL,
                is_simulated=True,
                ingested_at=datetime.now(UTC),
                quality_flags=[],
            )
        )
        d += timedelta(days=1)
    session.flush()
    return inst


def contracts(
    session: Session,
    *,
    shares_per_contract: int = 100,
    style: str = "american",
    symbol: str = UNDERLYING,
) -> None:
    short_ticker, long_ticker = tickers_for(symbol)
    for ticker, strike in ((short_ticker, SHORT_STRIKE), (long_ticker, LONG_STRIKE)):
        session.add(
            OptionContract(
                option_ticker=ticker,
                underlying_symbol=symbol,
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
    symbol: str = UNDERLYING,
    source: str = OPTION_SOURCE,
) -> None:
    """Write one daily bar per contract per session. ``skip`` names tickers that
    DO NOT print — absence is a first-class liquidity fact, never a zero.
    ``source`` labels the rows; a second call with another label seeds a rival
    vendor's prints for the same tickers and sessions."""
    short_ticker, long_ticker = tickers_for(symbol)
    for d in sessions:
        for ticker, close in ((short_ticker, short_close), (long_ticker, long_close)):
            if ticker in skip:
                continue
            session.add(
                OptionAggregateDaily(
                    option_ticker=ticker,
                    underlying_symbol=symbol,
                    session_date=d,
                    open=close,
                    high=close,
                    low=close,
                    close=close,
                    volume=1_000.0,
                    source=source,
                    latency_category=LatencyCategory.HISTORICAL,
                    ingested_at=datetime.now(UTC),
                    quality_flags=[],
                )
            )
    session.flush()


def legs_json(
    *, shares_per_contract: int = 100, style: str = "american", symbol: str = UNDERLYING
) -> list[dict[str, object]]:
    short_ticker, long_ticker = tickers_for(symbol)
    return [
        {
            "option_ticker": short_ticker,
            "right": "put",
            "strike": SHORT_STRIKE,
            "expiration": EXPIRY.isoformat(),
            "qty_signed": -1,
            "shares_per_contract": shares_per_contract,
            "exercise_style": style,
        },
        {
            "option_ticker": long_ticker,
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
    symbol: str = UNDERLYING,
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
                underlying_symbol=symbol,
                contracts=contracts_n,
                legs_json=legs_json(
                    shares_per_contract=shares_per_contract, style=style, symbol=symbol
                ),
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
    universe: tuple[str, ...] = (UNDERLYING,),
    option_source: str | None = OPTION_SOURCE,
) -> None:
    """Make the five-part equity scope match pass for this candidate's scan.

    The scope machinery compares a live scan against a PASSING promotion
    evaluation on dataset snapshot, config hash, spec hash, source and the exact
    universe. Everything here is a fixture row; nothing is a real evaluation.

    ``universe`` is EXACT, not a superset: the scan and the evaluation must name
    the same symbols, so a two-name book has to pass both names here.

    ``option_source`` is what the snapshot's ``options_scope_json`` RECORDS as the
    source of its option rows — the one witness ``resolve_option_data_source``
    reads when no cycle-backfill run is pinned, and what the guard's condition
    AC writes onto the position. ``None`` records nothing, so AC refuses.
    """
    from sqlalchemy import select

    from signalforge.db.models import DataSnapshot, StrategyPromotionEvaluation
    from signalforge.research.approval_scope import current_spec_json_hash

    snap = session.scalar(select(DataSnapshot).where(DataSnapshot.key == snapshot_key))
    if snap is None:
        snap = DataSnapshot(
            key=snapshot_key,
            symbols_json=list(universe),
            options_scope_json=(
                {"option_data": {"source": option_source}} if option_source else None
            ),
        )
        session.add(snap)
        session.flush()
    run = session.get(ScanRun, cand.scan_run_id)
    assert run is not None
    run.dataset_snapshot_id = snap.id
    run.universe_json = list(universe)
    session.add(
        StrategyPromotionEvaluation(
            strategy_version_id=version.id,
            evaluated_at=datetime.now(UTC),
            passed=True,
            gates_json=[],
            dataset_snapshot_id=snap.id,
            config_hash=run.config_hash,
            spec_json_hash=current_spec_json_hash(session, version.id) or "",
            universe_json=list(universe),
            window_start=SIGNAL_SESSION - timedelta(days=365),
            window_end=SIGNAL_SESSION,
            data_provenance_json={"sources": [run.source]},
        )
    )
    session.flush()
