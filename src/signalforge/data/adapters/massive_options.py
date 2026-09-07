"""Read-only options-data adapter (education / simulation only).

No order placement, no broker contact, no recommendations, no alerts. Coverage is
deliberately narrow: the caller passes a small set of liquid underlyings and
expiration / strike bounds — never "every contract".

Per-field latency is explicit and conservative:
* ``day_*`` and ``last_trade_*``  -> DELAYED (>= 15 minutes; never "live")
* ``open_interest``               -> END_OF_DAY (published once daily)
* vendor ``greeks`` / ``iv``      -> passed through verbatim; usually absent on
  the current entitlement, in which case they are ``None`` and the simulators'
  locally-computed Greeks are used instead (clearly labelled).

The API key travels only in the Authorization header and is scrubbed from every
error string.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

import httpx

from signalforge.config import get_settings
from signalforge.data.adapters.base import AdapterError
from signalforge.domain import LatencyCategory
from signalforge.killswitch import ensure_not_engaged

_BASE = "https://api.massive.com"
_TIMEOUT = 20.0
_MAX_PAGES = 20  # a hard cap so a bad filter can't walk the whole tape


@dataclass(frozen=True, slots=True)
class OptionContractRow:
    option_ticker: str
    underlying_symbol: str
    contract_type: str  # call | put
    strike_price: float
    expiration_date: date
    exercise_style: str
    shares_per_contract: int
    source: str


@dataclass(frozen=True, slots=True)
class OptionSnapshotRow:
    option_ticker: str
    underlying_symbol: str
    as_of: datetime  # our retrieval time (UTC)
    source: str
    latency_category: LatencyCategory  # DELAYED — the price fields are delayed
    underlying_price: float | None
    day_close: float | None
    day_volume: float | None
    day_vwap: float | None
    day_last_updated: datetime | None
    last_trade_price: float | None
    last_trade_size: float | None
    last_trade_at: datetime | None
    open_interest: int | None  # END_OF_DAY field
    break_even_price: float | None
    vendor_iv: float | None  # None when not entitled
    vendor_greeks: dict[str, Any] = field(default_factory=dict)
    quality_flags: list[str] = field(default_factory=list)


def _ns_to_dt(ns: Any) -> datetime | None:
    try:
        return datetime.fromtimestamp(float(ns) / 1e9, tz=UTC)
    except (TypeError, ValueError, OverflowError):
        return None


class MassiveOptionsAdapter:
    provider_name = "massive_options"

    def __init__(self, api_key: str | None = None, *, client: httpx.Client | None = None) -> None:
        s = get_settings()
        self._key = (
            (s.options_api_key.get_secret_value() or s.market_data_api_key.get_secret_value())
            if api_key is None
            else api_key
        )
        self._client = client

    def _get(self, path: str) -> dict[str, Any]:
        ensure_not_engaged()
        if not self._key:
            raise AdapterError("options adapter: no API key configured")
        getter = self._client.get if self._client is not None else httpx.get
        try:
            resp = getter(
                _BASE + path,
                headers={"Authorization": f"Bearer {self._key}"},
                timeout=_TIMEOUT,
                follow_redirects=False,
            )
        except httpx.HTTPError:
            raise AdapterError("options adapter: network request failed") from None
        if resp.status_code in (401, 403):
            raise AdapterError("options adapter: not authorized for this data", rate_limited=False)
        if resp.status_code == 429:
            raise AdapterError("options adapter: rate limited", rate_limited=True)
        if resp.status_code != 200:
            raise AdapterError(f"options adapter: HTTP {resp.status_code}")
        try:
            body = resp.json()
        except ValueError:
            raise AdapterError("options adapter: non-JSON response") from None
        return body if isinstance(body, dict) else {"results": body}

    def _paginate(self, path: str) -> Iterator[dict[str, Any]]:
        pages = 0
        next_path: str | None = path
        while next_path and pages < _MAX_PAGES:
            body = self._get(next_path)
            yield from body.get("results", []) or []
            nxt = body.get("next_url") or ""
            next_path = re.sub(r"^https?://[^/]+", "", nxt) if nxt else None
            pages += 1

    def fetch_contracts(
        self,
        underlying: str,
        *,
        expiration_gte: date,
        expiration_lte: date,
        strike_gte: float | None = None,
        strike_lte: float | None = None,
        limit: int = 250,
    ) -> list[OptionContractRow]:
        u = underlying.upper().strip()
        q = (
            f"/v3/reference/options/contracts?underlying_ticker={u}"
            f"&expiration_date.gte={expiration_gte}&expiration_date.lte={expiration_lte}"
            f"&limit={min(limit, 1000)}&sort=expiration_date"
        )
        if strike_gte is not None:
            q += f"&strike_price.gte={strike_gte}"
        if strike_lte is not None:
            q += f"&strike_price.lte={strike_lte}"
        out: list[OptionContractRow] = []
        for r in self._paginate(q):
            try:
                out.append(
                    OptionContractRow(
                        option_ticker=str(r["ticker"]),
                        underlying_symbol=u,
                        contract_type=str(r.get("contract_type", "")),
                        strike_price=float(r["strike_price"]),
                        expiration_date=date.fromisoformat(str(r["expiration_date"])),
                        exercise_style=str(r.get("exercise_style", "american")),
                        shares_per_contract=int(r.get("shares_per_contract", 100)),
                        source=self.provider_name,
                    )
                )
            except (KeyError, ValueError, TypeError):
                continue
        return out

    def fetch_chain_snapshot(
        self,
        underlying: str,
        *,
        strike_gte: float | None = None,
        strike_lte: float | None = None,
        expiration_gte: date | None = None,
        expiration_lte: date | None = None,
        limit: int = 250,
    ) -> list[OptionSnapshotRow]:
        u = underlying.upper().strip()
        q = f"/v3/snapshot/options/{u}?limit={min(limit, 250)}"
        if strike_gte is not None:
            q += f"&strike_price.gte={strike_gte}"
        if strike_lte is not None:
            q += f"&strike_price.lte={strike_lte}"
        if expiration_gte is not None:
            q += f"&expiration_date.gte={expiration_gte}"
        if expiration_lte is not None:
            q += f"&expiration_date.lte={expiration_lte}"
        now = datetime.now(UTC)
        rows: list[OptionSnapshotRow] = []
        for r in self._paginate(q):
            details = r.get("details") or {}
            day = r.get("day") or {}
            lt = r.get("last_trade") or {}
            ua = r.get("underlying_asset") or {}
            greeks = r.get("greeks") or {}
            iv = r.get("implied_volatility")
            flags: list[str] = []
            if not greeks:
                flags.append("vendor_greeks_absent")
            if iv is None:
                flags.append("vendor_iv_absent")
            rows.append(
                OptionSnapshotRow(
                    option_ticker=str(details.get("ticker", "")),
                    underlying_symbol=u,
                    as_of=now,
                    source=self.provider_name,
                    latency_category=LatencyCategory.DELAYED,
                    underlying_price=_f(ua.get("price")),
                    day_close=_f(day.get("close")),
                    day_volume=_f(day.get("volume")),
                    day_vwap=_f(day.get("vwap")),
                    day_last_updated=_ns_to_dt(day.get("last_updated")),
                    last_trade_price=_f(lt.get("price")),
                    last_trade_size=_f(lt.get("size")),
                    last_trade_at=_ns_to_dt(lt.get("sip_timestamp")),
                    open_interest=_i(r.get("open_interest")),
                    break_even_price=_f(r.get("break_even_price")),
                    vendor_iv=_f(iv),
                    vendor_greeks=dict(greeks),
                    quality_flags=flags,
                )
            )
        return rows


def _f(x: Any) -> float | None:
    try:
        return float(x) if x is not None else None
    except (TypeError, ValueError):
        return None


def _i(x: Any) -> int | None:
    try:
        return int(x) if x is not None else None
    except (TypeError, ValueError):
        return None
