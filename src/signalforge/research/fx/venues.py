"""Per-venue crypto cost model (2026-11-08).

Background: ``docs/research/RESULTS_crypto_executability_2026-11-08.md``. The
harness bundles a half-spread and a ~10 bps taker fee into one per-pair figure
(``CRYPTO_SPREAD_BPS``), which is roughly a futures cost. A :class:`VenueCost`
keeps the parts apart so a development-window backtest, or a paper trade, can
be costed at a named venue's real fee tier.

Fee tiers are DATA here, one frozen spec per named venue, not constants spread
through the harness:

``harness_default``
    Exactly today's harness numbers (half-spread = ``CRYPTO_SPREAD_BPS/2 - 10``,
    10 bps taker, no contract fee, no funding). It is the default everywhere;
    passing it changes nothing.
``coinbase_spot_intro``
    Coinbase spot, Intro tier: maker 50 / taker 90 bps. Spot cannot short.
``coinbase_cfm_intro``
    Coinbase US futures (CFM perp-style contracts), Intro tier: maker 9.5 /
    taker 10 bps plus an estimated $0.15 per contract per side
    (exchange + NFA + clearing). Funding is a parameter, default 0
    (:meth:`VenueCost.with_funding`).

Conventions (stated once, used by the harness and the paper venue report):

* Every fill is charged as a TAKER fill. Maker figures are recorded for
  reference only: stop, trailing and time exits are market exits in practice.
* The half-spread per pair is the harness's own estimate on every venue; no
  venue's book was measured.
* A per-contract fee is ``fee_usd / (contract_size * price)`` of notional. The
  harness converts it at a fixed REFERENCE price per pair (the 2026-11-08
  perp-style contract prices) because the contract sizes are set for today's
  prices; converting at a 2015 price would charge hundreds of bps per side.
  The paper venue report converts it at each trade's own fill price.
* Funding is charged to every position as a holding cost irrespective of side
  (conservative: shorts normally receive positive funding).

Research arithmetic only: nothing here reaches paper, alerts or execution.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from signalforge.research.fx.harness import CRYPTO_DEFAULT_SPREAD_BPS, CRYPTO_SPREAD_BPS

# The taker fee the harness folds into CRYPTO_SPREAD_BPS (see its comment).
HARNESS_TAKER_BPS = 10.0

# Coinbase CFM perp-style contracts: contract size (base units) and the last
# price on 2026-11-08 (Coinbase futures product list, ``*-20DEC30-CDE``).
CFM_CONTRACT_SIZE: dict[str, float] = {
    "BTCUSD": 0.01,
    "ETHUSD": 0.1,
    "SOLUSD": 5.0,
    "XRPUSD": 500.0,
    "DOGEUSD": 5000.0,
    "ADAUSD": 1000.0,
    "LINKUSD": 50.0,
    "AVAXUSD": 10.0,
    "LTCUSD": 5.0,
    "BNBUSD": 1.0,
}
CFM_REFERENCE_PRICE_USD: dict[str, float] = {
    "BTCUSD": 75690.0,
    "ETHUSD": 2224.0,
    "SOLUSD": 89.03,
    "XRPUSD": 1.1515,
    "DOGEUSD": 0.07114,
    "ADAUSD": 0.1795,
    "LINKUSD": 10.626,
    "AVAXUSD": 8.16,
    "LTCUSD": 51.44,
    "BNBUSD": 697.1,
}
CFM_REFERENCE_DATE = "2026-11-08"


@dataclass(frozen=True, slots=True)
class VenueCost:
    """One venue's cost schedule. All rates are basis points of notional."""

    name: str
    description: str
    half_spread_bps: dict[str, float]
    default_half_spread_bps: float
    maker_bps: float
    taker_bps: float
    contract_fee_usd: float = 0.0  # per contract per side
    contract_size: dict[str, float] = field(default_factory=dict)
    reference_price_usd: dict[str, float] = field(default_factory=dict)
    funding_bps_per_year: float = 0.0
    can_short: bool = True

    def half_spread(self, pair: str) -> float:
        return self.half_spread_bps.get(pair, self.default_half_spread_bps)

    def contract_fee_bps(self, pair: str, price: float | None = None) -> float:
        """The per-contract fee as bps of notional at ``price`` (default: the
        pair's reference price). Zero on a venue without a contract fee."""
        if not self.contract_fee_usd:
            return 0.0
        size = self.contract_size.get(pair)
        px = price if price is not None else self.reference_price_usd.get(pair)
        if size is None or px is None or size <= 0 or px <= 0:
            raise ValueError(f"{self.name}: no contract size or price for {pair}")
        return self.contract_fee_usd / (size * px) * 10_000.0

    def side_bps(self, pair: str, price: float | None = None) -> float:
        """All-in cost of one taker fill, excluding the harness's slippage."""
        return self.half_spread(pair) + self.taker_bps + self.contract_fee_bps(pair, price)

    def engine_spread_bps(self, pair: str) -> float:
        """The ``spread_bps`` argument the backtest engine expects: it charges
        ``spread_bps / 2`` (plus slippage) on each side."""
        return 2.0 * self.side_bps(pair)

    def with_funding(self, bps_per_year: float) -> VenueCost:
        return replace(self, funding_bps_per_year=float(bps_per_year))


HARNESS_DEFAULT = VenueCost(
    name="harness_default",
    description="Today's harness costs: half-spread + 10 bps taker per side (CRYPTO_SPREAD_BPS).",
    half_spread_bps={p: s / 2 - HARNESS_TAKER_BPS for p, s in CRYPTO_SPREAD_BPS.items()},
    default_half_spread_bps=CRYPTO_DEFAULT_SPREAD_BPS / 2 - HARNESS_TAKER_BPS,
    maker_bps=HARNESS_TAKER_BPS,
    taker_bps=HARNESS_TAKER_BPS,
)
COINBASE_SPOT_INTRO = VenueCost(
    name="coinbase_spot_intro",
    description="Coinbase spot, Intro tier: maker 50 / taker 90 bps; long only (no shorting).",
    half_spread_bps=dict(HARNESS_DEFAULT.half_spread_bps),
    default_half_spread_bps=HARNESS_DEFAULT.default_half_spread_bps,
    maker_bps=50.0,
    taker_bps=90.0,
    can_short=False,
)
COINBASE_CFM_INTRO = VenueCost(
    name="coinbase_cfm_intro",
    description=(
        "Coinbase US futures (CFM perp-style), Intro tier: maker 9.5 / taker 10 bps plus "
        f"~$0.15 per contract per side; contract fee at {CFM_REFERENCE_DATE} reference prices; "
        "funding 0 unless set."
    ),
    half_spread_bps=dict(HARNESS_DEFAULT.half_spread_bps),
    default_half_spread_bps=HARNESS_DEFAULT.default_half_spread_bps,
    maker_bps=9.5,
    taker_bps=10.0,
    contract_fee_usd=0.15,
    contract_size=dict(CFM_CONTRACT_SIZE),
    reference_price_usd=dict(CFM_REFERENCE_PRICE_USD),
)

VENUES: dict[str, VenueCost] = {
    v.name: v for v in (HARNESS_DEFAULT, COINBASE_SPOT_INTRO, COINBASE_CFM_INTRO)
}


def get_venue(name: str, *, funding_bps_per_year: float | None = None) -> VenueCost:
    try:
        venue = VENUES[name]
    except KeyError:
        raise ValueError(f"unknown venue {name!r}; expected one of {sorted(VENUES)}") from None
    return venue if funding_bps_per_year is None else venue.with_funding(funding_bps_per_year)


def funding_cost_r(
    *, bars_held: int, bar_days: float, bps_per_year: float, entry_over_risk: float
) -> float:
    """Funding of one position in R: held ``bars_held + 1`` bars (the entry
    bar counts), charged on notional, divided by the trade's risk."""
    if bps_per_year <= 0:
        return 0.0
    years = (bars_held + 1) * bar_days / 365.0
    return bps_per_year / 10_000.0 * years * entry_over_risk


__all__ = [
    "COINBASE_CFM_INTRO",
    "COINBASE_SPOT_INTRO",
    "HARNESS_DEFAULT",
    "VENUES",
    "VenueCost",
    "funding_cost_r",
    "get_venue",
]
