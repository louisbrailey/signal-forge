"""Persist option contract metadata + delayed chain snapshots (education only).

Staged and resumable per underlying; deduplicates contracts on
(option_ticker, source); records a raw-payload audit line and a coverage summary.
No recommendations, no alerts, no execution — this only fills local tables the
learning UI and the simulators read from.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from signalforge.data.adapters.base import AdapterError
from signalforge.data.adapters.massive_options import MassiveOptionsAdapter
from signalforge.db.models import OptionContract, OptionQuoteSnapshot
from signalforge.db.types import utcnow
from signalforge.observability import get_logger

_log = get_logger("options.ingest")


@dataclass(slots=True)
class OptionsCoverage:
    underlying: str
    contracts_seen: int = 0
    contracts_written: int = 0
    snapshots_written: int = 0
    expirations: list[str] = field(default_factory=list)
    strike_min: float | None = None
    strike_max: float | None = None
    greeks_present: int = 0
    iv_present: int = 0
    error: str | None = None


def ingest_options_for_underlying(
    session: Session,
    adapter: MassiveOptionsAdapter,
    underlying: str,
    *,
    expiration_min_days: int = 14,
    expiration_max_days: int = 120,
    strike_pct: float = 0.25,
    reference_price: float | None = None,
) -> OptionsCoverage:
    u = underlying.upper().strip()
    cov = OptionsCoverage(underlying=u)
    today = date.today()
    exp_lo = today + timedelta(days=expiration_min_days)
    exp_hi = today + timedelta(days=expiration_max_days)
    strike_lo = reference_price * (1 - strike_pct) if reference_price else None
    strike_hi = reference_price * (1 + strike_pct) if reference_price else None

    try:
        contracts = adapter.fetch_contracts(
            u,
            expiration_gte=exp_lo,
            expiration_lte=exp_hi,
            strike_gte=strike_lo,
            strike_lte=strike_hi,
        )
    except AdapterError as exc:
        cov.error = str(exc)
        _log.warning("options.contracts_failed", underlying=u, error=str(exc))
        return cov

    cov.contracts_seen = len(contracts)
    existing = {
        t
        for (t,) in session.execute(
            select(OptionContract.option_ticker).where(
                OptionContract.underlying_symbol == u,
                OptionContract.source == adapter.provider_name,
            )
        )
    }
    now = utcnow()
    strikes: list[float] = []
    exps: set[str] = set()
    for c in contracts:
        strikes.append(c.strike_price)
        exps.add(c.expiration_date.isoformat())
        if c.option_ticker in existing:
            continue
        session.add(
            OptionContract(
                option_ticker=c.option_ticker,
                underlying_symbol=u,
                contract_type=c.contract_type,
                strike_price=c.strike_price,
                expiration_date=c.expiration_date,
                exercise_style=c.exercise_style,
                shares_per_contract=c.shares_per_contract,
                source=adapter.provider_name,
                ingested_at=now,
            )
        )
        cov.contracts_written += 1
    session.flush()
    cov.expirations = sorted(exps)
    cov.strike_min = min(strikes) if strikes else None
    cov.strike_max = max(strikes) if strikes else None

    try:
        snaps = adapter.fetch_chain_snapshot(
            u,
            strike_gte=strike_lo,
            strike_lte=strike_hi,
            expiration_gte=exp_lo,
            expiration_lte=exp_hi,
        )
    except AdapterError as exc:
        cov.error = str(exc)
        return cov

    for s in snaps:
        session.add(
            OptionQuoteSnapshot(
                option_ticker=s.option_ticker,
                underlying_symbol=u,
                as_of=s.as_of,
                source=s.source,
                latency_category=s.latency_category,
                underlying_price=s.underlying_price,
                day_close=s.day_close,
                day_volume=s.day_volume,
                day_vwap=s.day_vwap,
                day_last_updated=s.day_last_updated,
                last_trade_price=s.last_trade_price,
                last_trade_size=s.last_trade_size,
                last_trade_at=s.last_trade_at,
                open_interest=s.open_interest,
                break_even_price=s.break_even_price,
                vendor_iv=s.vendor_iv,
                vendor_greeks_json=s.vendor_greeks,
                quality_flags=s.quality_flags,
            )
        )
        cov.snapshots_written += 1
        cov.greeks_present += 1 if s.vendor_greeks else 0
        cov.iv_present += 1 if s.vendor_iv is not None else 0
    session.flush()
    _log.info(
        "options.ingest_done",
        underlying=u,
        contracts=cov.contracts_written,
        snapshots=cov.snapshots_written,
        as_of=datetime.now(UTC).isoformat(),
    )
    return cov
