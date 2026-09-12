"""Synthetic option chains for the I-O3 engine tests.

Deliberately hand-built rather than loaded: every print, every gap and every
underlying close is chosen by the test, so a fill, an exclusion or a counter can
be asserted against arithmetic the reader can do on paper.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date

from signalforge.backtest.options_costs import OptionCostModel
from signalforge.backtest.options_engine import (
    DteBasis,
    OptionLeg,
    OptionsEntrySignal,
    OptionStructure,
    StructureType,
)
from signalforge.backtest.options_pricing import IvSource
from signalforge.data import calendar
from signalforge.data.option_chain import (
    ContractPrint,
    ContractRef,
    OptionChainSeries,
    Right,
)
from signalforge.data.series import PriceSeries

# The worked example of D2 §9.3, so its published arithmetic is the fixture.
SHORT_STRIKE = 500.0
LONG_STRIKE = 495.0
EXPIRY = date(2024, 3, 15)  # third Friday, an XNYS session
SHORT_TICKER = "O:SPY240315P00500000"
LONG_TICKER = "O:SPY240315P00495000"


def worked_example_cost_model(*, spread_multiplier: float = 1.0) -> OptionCostModel:
    """D2 §9.3's inputs.  No field is defaulted — that is the point of §7.4."""
    return OptionCostModel(
        commission_per_contract=0.65,
        commission_min_per_order=0.0,
        exchange_fee_per_contract=0.05,
        spread_pct_of_last_print=0.03,
        spread_abs_floor_cents=5.0,
        tick_grid=((math.inf, 0.01),),
        assignment_fee=0.0,
        exercise_fee=0.0,
        spread_multiplier=spread_multiplier,
    )


def sessions_between(start: date, end: date) -> tuple[date, ...]:
    return calendar.sessions(start, end)


def put_contract(
    ticker: str,
    strike: float,
    first_print_session: date,
    *,
    underlying: str = "SPY",
    expiration: date = EXPIRY,
    shares_per_contract: int = 100,
    exercise_style: str = "american",
) -> ContractRef:
    return ContractRef(
        option_ticker=ticker,
        underlying_symbol=underlying,
        right=Right.PUT,
        strike=strike,
        expiration=expiration,
        shares_per_contract=shares_per_contract,
        exercise_style=exercise_style,
        first_print_session=first_print_session,
    )


def flat_print(price: float) -> ContractPrint:
    return ContractPrint(open=price, high=price, low=price, close=price, volume=1000.0)


@dataclass(frozen=True, slots=True)
class ChainFixture:
    chain: OptionChainSeries
    underlying: PriceSeries
    session_dates: tuple[date, ...]

    def index_of(self, d: date) -> int:
        return self.session_dates.index(d)


def build_fixture(
    session_dates: tuple[date, ...],
    underlying_closes: dict[date, float],
    leg_prices: dict[str, dict[date, float]],
    contracts: list[ContractRef],
    *,
    symbol: str = "SPY",
) -> ChainFixture:
    prints: dict[date, dict[str, ContractPrint]] = {}
    for ticker, by_date in leg_prices.items():
        for d, px in by_date.items():
            prints.setdefault(d, {})[ticker] = flat_print(px)
    chain = OptionChainSeries.from_rows(
        symbol,
        contracts=contracts,
        underlying_closes={d: underlying_closes[d] for d in session_dates},
        prints=prints,
    )
    rows = [
        (
            d,
            underlying_closes[d],
            underlying_closes[d],
            underlying_closes[d],
            underlying_closes[d],
            1e6,
        )
        for d in session_dates
    ]
    return ChainFixture(
        chain=chain, underlying=PriceSeries.from_bars(symbol, rows), session_dates=session_dates
    )


def credit_spread(
    contracts: int = 1,
    *,
    short: ContractRef | None = None,
    long_: ContractRef | None = None,
) -> OptionStructure:
    first = date(2024, 2, 1)
    short_ref = short or put_contract(SHORT_TICKER, SHORT_STRIKE, first)
    long_ref = long_ or put_contract(LONG_TICKER, LONG_STRIKE, first)
    return OptionStructure(
        structure_type=StructureType.VERTICAL_CREDIT,
        underlying_symbol="SPY",
        legs=(OptionLeg(short_ref, -1), OptionLeg(long_ref, +1)),
        contracts=contracts,
    )


def signal_at(
    index: int,
    structure: OptionStructure | None = None,
    *,
    profit_target_pct_of_credit: float = 0.50,
    stop_multiple_of_credit: float = 2.0,
    time_stop_dte: int = 0,
    time_stop_dte_basis: DteBasis = DteBasis.CALENDAR,
    pin_band_pct: float = 0.005,
    strike_increment: float = 5.0,
    assignment_itm_threshold_pct: float = 0.01,
) -> OptionsEntrySignal:
    return OptionsEntrySignal(
        structure=structure or credit_spread(),
        entry_session_index=index,
        profit_target_pct_of_credit=profit_target_pct_of_credit,
        stop_multiple_of_credit=stop_multiple_of_credit,
        time_stop_dte=time_stop_dte,
        time_stop_dte_basis=time_stop_dte_basis,
        pin_band_pct=pin_band_pct,
        strike_increment=strike_increment,
        assignment_itm_threshold_pct=assignment_itm_threshold_pct,
        iv_source=IvSource.LOCAL_BS_INVERTED,
        q_source="test:q_per_underlying",
        r_source="test:r_per_session",
        reason="fixture",
    )
