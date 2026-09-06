"""Exposure / concentration analytics shared by the risk engine and CSV import."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class Holding:
    symbol: str
    sector: str
    market_value: float  # signed: negative for shorts


@dataclass(frozen=True, slots=True)
class ExposureReport:
    gross_exposure: float
    net_exposure: float
    long_exposure: float
    short_exposure: float
    by_sector_pct: dict[str, float] = field(default_factory=dict)
    largest_position_pct: float = 0.0
    largest_position_symbol: str = ""
    n_positions: int = 0

    def to_dict(self) -> dict[str, object]:
        return {
            "gross_exposure": round(self.gross_exposure, 2),
            "net_exposure": round(self.net_exposure, 2),
            "long_exposure": round(self.long_exposure, 2),
            "short_exposure": round(self.short_exposure, 2),
            "by_sector_pct": {k: round(v, 2) for k, v in self.by_sector_pct.items()},
            "largest_position_pct": round(self.largest_position_pct, 2),
            "largest_position_symbol": self.largest_position_symbol,
            "n_positions": self.n_positions,
        }


def exposure_report(holdings: Iterable[Holding], account_equity: float) -> ExposureReport:
    hs = list(holdings)
    gross = sum(abs(h.market_value) for h in hs)
    net = sum(h.market_value for h in hs)
    longs = sum(h.market_value for h in hs if h.market_value > 0)
    shorts = -sum(h.market_value for h in hs if h.market_value < 0)

    denom = account_equity if account_equity > 0 else (gross or 1.0)
    by_sector: dict[str, float] = {}
    for h in hs:
        by_sector[h.sector or "unknown"] = by_sector.get(h.sector or "unknown", 0.0) + abs(
            h.market_value
        )
    by_sector_pct = {k: v / denom * 100.0 for k, v in by_sector.items()}

    largest_sym, largest_pct = "", 0.0
    for h in hs:
        pct = abs(h.market_value) / denom * 100.0
        if pct > largest_pct:
            largest_sym, largest_pct = h.symbol, pct

    return ExposureReport(
        gross_exposure=gross,
        net_exposure=net,
        long_exposure=longs,
        short_exposure=shorts,
        by_sector_pct=dict(sorted(by_sector_pct.items(), key=lambda kv: -kv[1])),
        largest_position_pct=largest_pct,
        largest_position_symbol=largest_sym,
        n_positions=len(hs),
    )
