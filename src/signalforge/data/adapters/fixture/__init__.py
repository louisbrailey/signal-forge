"""Deterministic, offline fixture adapter.

Produces reproducible synthetic OHLCV, a quarterly earnings calendar, and (empty)
corporate actions so the app, seed data, and the test suite never depend on a
network or an API key. Every datum is stamped ``is_simulated=True`` and
``latency_category=HISTORICAL`` — it can never be shown as "live" (invariant S7).
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta

from signalforge.data.calendar import rth_bounds_utc, sessions
from signalforge.data.adapters.base import (
    AdapterCapability,
    CorporateActionRecord,
    DailyBar,
    EarningsRecord,
    FeedType,
    IntradayBar,
    LatencyCategory,
    Provenance,
)

_BAR_MINUTES = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "1h": 60}

PROVIDER_NAME = "fixture"

# Symbols the fixture treats as ETFs (no earnings events).
_ETF_SYMBOLS = frozenset(
    {
        "SPY", "QQQ", "IWM", "DIA",
        "XLK", "XLF", "XLE", "XLV", "XLY", "XLP", "XLI", "XLB", "XLU", "XLRE", "XLC",
    }
)


def _seed_float(*parts: str) -> float:
    digest = hashlib.sha256("|".join(parts).encode()).hexdigest()
    return int(digest[:8], 16) / 0xFFFFFFFF  # in [0, 1]


class FixtureMarketDataAdapter:
    """Implements :class:`~signalforge.data.adapters.base.MarketDataAdapter`."""

    provider_name = PROVIDER_NAME

    @property
    def capabilities(self) -> Sequence[AdapterCapability]:
        def cap(feed_type: FeedType) -> AdapterCapability:
            return AdapterCapability(
                provider_name=PROVIDER_NAME,
                feed_type=feed_type,
                latency_category=LatencyCategory.HISTORICAL,
                supports_point_in_time=True,
                entitlement_note="Deterministic simulated data — not a market feed.",
                is_simulated=True,
            )

        return (
            cap(FeedType.BAR_DAILY),
            cap(FeedType.BAR_INTRADAY),
            cap(FeedType.CORP_ACTION),
            cap(FeedType.EARNINGS_CAL),
        )

    def _provenance(self) -> Provenance:
        return Provenance(
            source=PROVIDER_NAME,
            latency_category=LatencyCategory.HISTORICAL,
            retrieved_at=datetime.now(UTC),
            is_simulated=True,
        )

    def fetch_daily_bars(self, symbol: str, start: date, end: date) -> Sequence[DailyBar]:
        if end < start:
            raise ValueError("end must be >= start")
        base = 50.0 + 150.0 * _seed_float(symbol, "base")
        drift = (_seed_float(symbol, "drift") - 0.5) * 0.002
        vol = 0.01 + 0.02 * _seed_float(symbol, "vol")

        # Walk deterministically from a fixed epoch so a window is a slice of one series.
        epoch = date(2015, 1, 1)
        price = base
        bars: list[DailyBar] = []
        day = epoch
        idx = 0
        prov = self._provenance()
        while day <= end:
            if day.weekday() < 5:  # Mon-Fri; holidays handled by the session calendar later
                wobble = math.sin(idx / 7.0) * vol + (_seed_float(symbol, str(idx)) - 0.5) * vol
                price = max(1.0, price * (1.0 + drift + wobble))
                if day >= start:
                    spread = price * vol
                    op = price - spread * (_seed_float(symbol, str(idx), "o") - 0.5)
                    cl = price + spread * (_seed_float(symbol, str(idx), "c") - 0.5)
                    hi = max(op, cl) + spread * _seed_float(symbol, str(idx), "h")
                    lo = min(op, cl) - spread * _seed_float(symbol, str(idx), "l")
                    volume = round(1_000_000 * (0.5 + _seed_float(symbol, str(idx), "v")), 0)
                    bars.append(
                        DailyBar(
                            symbol=symbol,
                            session_date=day,
                            open=round(op, 4),
                            high=round(hi, 4),
                            low=round(lo, 4),
                            close=round(cl, 4),
                            volume=volume,
                            adj_close=round(cl, 4),
                            provenance=prov,
                        )
                    )
                idx += 1
            day += timedelta(days=1)
        return bars

    def fetch_intraday_bars(
        self, symbol: str, start: datetime, end: datetime, *, bar_size: str = "5m"
    ) -> Sequence[IntradayBar]:
        if bar_size not in _BAR_MINUTES:
            raise ValueError(f"unsupported bar_size {bar_size!r}")
        if start.tzinfo is None or end.tzinfo is None:
            raise ValueError("intraday start/end must be timezone-aware")
        if end < start:
            raise ValueError("end must be >= start")
        step = timedelta(minutes=_BAR_MINUTES[bar_size])
        prov = self._provenance()
        daily = {
            b.session_date: b.close
            for b in self.fetch_daily_bars(symbol, start.date(), end.date())
        }
        vol = 0.01 + 0.02 * _seed_float(symbol, "vol")
        out: list[IntradayBar] = []
        for d in sessions(start.date(), end.date()):
            bounds = rth_bounds_utc(d)
            if bounds is None:
                continue
            level = daily.get(d, 50.0 + 150.0 * _seed_float(symbol, "base"))
            t, close_dt = bounds
            k = 0
            price = level * (1.0 + (_seed_float(symbol, d.isoformat(), "o") - 0.5) * vol)
            while t < close_dt:
                seed = (symbol, d.isoformat(), str(k))
                price = max(1.0, price * (1.0 + (_seed_float(*seed) - 0.5) * vol * 0.4))
                spread = price * vol * 0.3
                op = price
                cl = price * (1.0 + (_seed_float(*seed, "c") - 0.5) * vol * 0.3)
                hi = max(op, cl) + spread * _seed_float(*seed, "h")
                lo = min(op, cl) - spread * _seed_float(*seed, "l")
                if start <= t <= end:
                    out.append(
                        IntradayBar(
                            symbol=symbol.upper(),
                            bar_start=t,
                            bar_size=bar_size,
                            session="rth",
                            open=round(op, 4),
                            high=round(hi, 4),
                            low=round(lo, 4),
                            close=round(cl, 4),
                            volume=round(20_000 * (0.5 + _seed_float(*seed, "v")), 0),
                            provenance=prov,
                        )
                    )
                price = cl
                t += step
                k += 1
        return out

    def fetch_corporate_actions(
        self, symbol: str, start: date, end: date
    ) -> Sequence[CorporateActionRecord]:
        # The fixture series is already "adjusted"; no discrete actions modelled.
        return ()

    def fetch_earnings(
        self, symbol: str, start: date, end: date
    ) -> Sequence[EarningsRecord]:
        if symbol.upper() in _ETF_SYMBOLS:
            return ()
        # Quarterly, on a symbol-specific day offset so they are not all identical.
        offset = int(_seed_float(symbol, "eps_day") * 20)  # 0..19
        out: list[EarningsRecord] = []
        for year in range(start.year, end.year + 1):
            for month in (1, 4, 7, 10):
                d = date(year, month, 15) + timedelta(days=offset)
                if start <= d <= end:
                    tod = "amc" if _seed_float(symbol, str(year), str(month)) > 0.5 else "bmo"
                    out.append(
                        EarningsRecord(
                            symbol=symbol, scheduled_for=d, time_of_day=tod, confirmed=True
                        )
                    )
        return out

    def raw_payload(self, symbol: str, start: date, end: date) -> str:
        """A stable text blob recorded to the raw-payload cache for audit/replay."""
        return json.dumps(
            {
                "provider": PROVIDER_NAME,
                "symbol": symbol,
                "start": start.isoformat(),
                "end": end.isoformat(),
                "note": "SIMULATED — deterministic fixture series (seed = sha256 of symbol).",
            },
            sort_keys=True,
        )
