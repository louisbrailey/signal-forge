"""A synthetic options dataset in the database, for the evidence assembler.

No provider, no network, no real chain: every bar is written by these helpers, so
a coverage fraction, a cluster count or a gate-0 failure is arithmetic the reader
can do on paper.  The strategy is a three-line stub implementing the
``OptionsStrategy`` protocol — the assembler must work for any family, and
binding the test to ``OptionsShortVertical`` would test the strategy instead.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from sqlalchemy.orm import Session

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
from signalforge.data.option_chain import ContractRef, OptionChainSeries, Right
from signalforge.data.series import PriceSeries
from signalforge.db.models import (
    DataSnapshot,
    IngestionRun,
    Instrument,
    OHLCVDaily,
    OptionAggregateDaily,
    OptionContract,
)
from signalforge.db.types import utcnow
from signalforge.domain import FeedType, Horizon, LatencyCategory
from signalforge.research.options_gates import OptionsWindow, StructureIdentity

SOURCE = "massive"
UNDERLYING_LEVEL = 500.0
SHORT_STRIKE = 480.0
LONG_STRIKE = 475.0

# Two monthly third-Friday expiries, so the clustered bootstrap sees more than
# one cluster per underlying and the cluster count is a checkable number.
EXPIRIES = (date(2024, 3, 15), date(2024, 4, 19))
WINDOW_START = date(2024, 1, 2)
WINDOW_END = date(2024, 5, 31)


def window(sealed_days: int = 30) -> OptionsWindow:
    sealed_start = WINDOW_END - timedelta(days=sealed_days)
    return OptionsWindow(
        start=WINDOW_START,
        pre_sealed_end=sealed_start - timedelta(days=1),
        sealed_start=sealed_start,
        end=WINDOW_END,
    )


def option_ticker(symbol: str, expiry: date, right: str, strike: float) -> str:
    cp = "C" if right == "call" else "P"
    return f"O:{symbol}{expiry:%y%m%d}{cp}{round(strike * 1000):08d}"


def cost_model(spread_multiplier: float = 1.0) -> OptionCostModel:
    return OptionCostModel(
        commission_per_contract=0.65,
        commission_min_per_order=0.0,
        exchange_fee_per_contract=0.05,
        spread_pct_of_last_print=0.03,
        spread_abs_floor_cents=5.0,
        tick_grid=((float("inf"), 0.01),),
        assignment_fee=0.0,
        exercise_fee=0.0,
        spread_multiplier=spread_multiplier,
    )


#: D5a §3: a version-fixed width in dollars of strike distance per contract.
STUB_WIDTH_DECLARED: float = 2.0


@dataclass
class StubOptionsStrategy:
    """Enters one short vertical per expiry, on the first session 35+ days out.

    Implements exactly the surface ``options_evidence.OptionsStrategy`` declares,
    and nothing else — which is the point: the assembler must not depend on any
    ``OptionsShortVertical`` detail.
    """

    key: str = "options_stub.medium_swing"
    horizon: Horizon = Horizon.MEDIUM_SWING
    selection_cost_model: OptionCostModel = None  # type: ignore[assignment]
    dte_target: int = 35
    regime_filter: bool = True
    symbols: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.selection_cost_model is None:
            self.selection_cost_model = cost_model()

    def __call__(
        self, chain: OptionChainSeries, underlying: PriceSeries, t: int
    ) -> OptionsEntrySignal | None:
        today = chain.session_dates()[t]
        visible = chain.visible_contracts(t)
        for expiry in EXPIRIES:
            dte = (expiry - today).days
            if not (self.dte_target - 2 <= dte <= self.dte_target + 2):
                continue
            short = visible.get(option_ticker(chain.underlying, expiry, "put", SHORT_STRIKE))
            long_ = visible.get(option_ticker(chain.underlying, expiry, "put", LONG_STRIKE))
            if short is None or long_ is None:
                continue
            return OptionsEntrySignal(
                structure=OptionStructure(
                    structure_type=StructureType.VERTICAL_CREDIT,
                    underlying_symbol=chain.underlying,
                    legs=(OptionLeg(short, -1), OptionLeg(long_, +1)),
                    contracts=1,
                ),
                entry_session_index=t,
                profit_target_pct_of_credit=0.50,
                stop_multiple_of_credit=2.0,
                time_stop_dte=0,
                time_stop_dte_basis=DteBasis.CALENDAR,
                pin_band_pct=0.005,
                strike_increment=5.0,
                assignment_itm_threshold_pct=0.01,
                iv_source=IvSource.LOCAL_BS_INVERTED,
                q_source="test:q_per_underlying",
                r_source="test:r_per_session",
                reason="stub",
            )
        return None

    def sensitivity_axes(self) -> Mapping[str, Sequence[float | int]]:
        return {"dte_target": [33, 35], "width_pct": [0.01, 0.02]}

    def oat_parameters(self) -> Mapping[str, Sequence[float | int]]:
        return {"stop_multiple": [1.5, 3.0]}

    def structure_identity(self) -> StructureIdentity:
        return StructureIdentity(
            structure_type=StructureType.VERTICAL_CREDIT,
            r_basis_formula="R = width x M x contracts - net_credit + entry_costs",
            legs_per_structure=2,
            leg_sign_pattern=(-1, +1),
            width_declared=STUB_WIDTH_DECLARED,
            m_declared=100,
        )

    def mechanical_benchmark(self) -> StubOptionsStrategy:
        return StubOptionsStrategy(
            key=self.key,
            horizon=self.horizon,
            selection_cost_model=self.selection_cost_model,
            dte_target=self.dte_target,
            regime_filter=False,
        )

    def mechanical_spec(self) -> dict[str, object]:
        return {"regime_filter": "REMOVED", "everything_else": "identical"}


class WideGridStrategy(StubOptionsStrategy):
    """A declared grid of 3^5 = 243 points — above ``MAX_GRID_POINTS``."""

    def sensitivity_axes(self) -> Mapping[str, Sequence[float | int]]:
        return {f"axis_{i}": [1, 2, 3] for i in range(5)}


def seed_underlying(session: Session, symbol: str, *, level: float = UNDERLYING_LEVEL) -> None:
    inst = Instrument(symbol=symbol, name=symbol, instrument_type="etf", exchange="ARCX")
    session.add(inst)
    session.flush()
    for i, d in enumerate(calendar.sessions(WINDOW_START, WINDOW_END)):
        # A gentle drift so label_regimes and the Sharpe helpers have variance to
        # read; the option prices below are independent of it on purpose.
        px = level * (1.0 + 0.0004 * i)
        session.add(
            OHLCVDaily(
                instrument_id=inst.id,
                session_date=d,
                open=px,
                high=px,
                low=px,
                close=px,
                adj_close=px,
                volume=1_000_000,
                source=SOURCE,
                latency_category=LatencyCategory.HISTORICAL,
                ingested_at=datetime.now(UTC),
                is_simulated=False,
            )
        )


def seed_chain(session: Session, symbol: str) -> None:
    """A put ladder around the money for each expiry, printing every session."""
    strikes = [460.0, 465.0, 470.0, LONG_STRIKE, SHORT_STRIKE, 485.0, 490.0, 520.0]
    sessions = calendar.sessions(WINDOW_START, WINDOW_END)
    for expiry in EXPIRIES:
        for right in ("put", "call"):
            for k in strikes:
                ticker = option_ticker(symbol, expiry, right, k)
                session.add(
                    OptionContract(
                        option_ticker=ticker,
                        underlying_symbol=symbol,
                        contract_type=right,
                        strike_price=k,
                        expiration_date=expiry,
                        exercise_style="american",
                        shares_per_contract=100,
                        source=SOURCE,
                        ingested_at=utcnow(),
                    )
                )
                for d in sessions:
                    if d > expiry:
                        continue
                    # A decaying short-put premium and a cheaper long wing, so the
                    # structure closes on its profit target rather than a stop.
                    days = max((expiry - d).days, 0)
                    base = 2.0 if k == SHORT_STRIKE else (0.9 if k == LONG_STRIKE else 1.2)
                    px = round(base * (0.2 + 0.8 * days / 40.0), 2)
                    session.add(
                        OptionAggregateDaily(
                            option_ticker=ticker,
                            underlying_symbol=symbol,
                            session_date=d,
                            open=px,
                            high=px,
                            low=px,
                            close=px,
                            volume=1500.0,
                            transactions=40,
                            source=SOURCE,
                            latency_category=LatencyCategory.HISTORICAL,
                            ingested_at=utcnow(),
                            quality_flags=[],
                        )
                    )


def seed_coverage_run(
    session: Session,
    symbols: Sequence[str],
    *,
    cycles_total: int = 10,
    cycles_covered: int = 10,
    bars_written: int = 1000,
    sessions_expected: int = 1000,
    status: str = "ok",
) -> IngestionRun:
    """An ``IngestionRun`` shaped exactly as ``coverage_summary`` reads it."""
    # ``coverage_summary`` computes sessions_expected as
    # sum(cycle.sessions_expected * cycle.contracts_fetched), so one contract per
    # cycle keeps the arithmetic something a reader can check on paper.
    cycles: dict[str, dict[str, object]] = {}
    per_cycle = sessions_expected // max(cycles_total, 1)
    for i in range(cycles_total):
        cycles[f"2024-{i + 1:02d}-15"] = {
            "excluded": None if i < cycles_covered else "ladder_incomplete",
            "selected_calls": 8,
            "selected_puts": 8,
            "contracts_fetched": 1,
            "sessions_expected": per_cycle,
            "shares_per_contract_refusals": 0,
        }
    run = IngestionRun(
        provider=SOURCE,
        feed_type=FeedType.OPTIONS_CHAIN,
        kind="options_cycle_backfill",
        requested_start=WINDOW_START,
        requested_end=WINDOW_END,
        adjusted=True,
        symbols_requested=list(symbols),
        symbols_ok=list(symbols),
        symbols_failed={},
        bars_written=bars_written,
        bars_skipped=0,
        status=status,
        started_at=utcnow(),
        gaps_json={
            "__run__": {
                "cycle_rule": "monthly_third_friday",
                "ladder_id": "LADDER_17",
                "strike_listing_basis": "vendor_as_of",
                "max_total_bars": 2_000_000,
                "max_total_bars_prior": 200_000,
                "pacing_s": 12.0,
            },
            symbols[0]: {"cycles": cycles},
        },
    )
    session.add(run)
    session.flush()
    return run


def seed_snapshot(
    session: Session, symbols: Sequence[str], key: str = "options_w3b_test"
) -> DataSnapshot:
    snap = DataSnapshot(
        key=key,
        symbols_json=list(symbols),
        description="synthetic options snapshot (test)",
        source_note="SIMULATED",
        options_scope_json={
            "schema_version": 1,
            "underlyings": list(symbols),
            "options_config_hash": "testhash",
        },
    )
    session.add(snap)
    session.flush()
    return snap


def seed_everything(
    session: Session, symbols: Sequence[str] = ("SPY", "QQQ")
) -> tuple[DataSnapshot, IngestionRun]:
    for sym in symbols:
        seed_underlying(session, sym)
        seed_chain(session, sym)
    run = seed_coverage_run(session, symbols)
    snap = seed_snapshot(session, symbols)
    session.commit()
    return snap, run


def contract_ref(symbol: str, expiry: date, strike: float, first: date) -> ContractRef:
    return ContractRef(
        option_ticker=option_ticker(symbol, expiry, "put", strike),
        underlying_symbol=symbol,
        right=Right.PUT,
        strike=strike,
        expiration=expiry,
        shares_per_contract=100,
        exercise_style="american",
        first_print_session=first,
    )
