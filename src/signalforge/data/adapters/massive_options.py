"""Read-only options-data adapter (education / simulation only).

This adapter only reads market data (any order path lives solely in the execution
layer, off by default); no recommendations, no alerts. Coverage is
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
import time
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
# Pacing / retry, ported verbatim in shape from the equities adapter
# (``massive.py``) — D1 §7.6, blocker D4. The options adapter previously made a
# SINGLE unretried attempt and raised immediately on 429, which is how a
# multi-day backfill turns into a multi-day stream of unretried rate limits.
_RETRY_STATUS = frozenset({429, 500, 502, 503, 504})
_MAX_ATTEMPTS = 5
_BACKOFF_BASE_S = 1.5
_BACKOFF_CAP_S = 30.0
# Kill-switch responsiveness: the pacing wait and the backoff sleep are broken
# into short chunks with ``ensure_not_engaged()`` inside them. The honest bound
# on kill latency is NOT a chunk size — an in-flight HTTP request is not
# cancelled — so it is ``max(pacing chunk, backoff chunk, _TIMEOUT)`` = 20 s
# (D1 §7.6, F45). Tightening it is a change to ``_TIMEOUT`` plus in-flight
# cancellation, not a property this code has.
_PACING_CHUNK_S = 0.1
_BACKOFF_CHUNK_S = 0.2


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


@dataclass(frozen=True, slots=True)
class ContractsPage:
    """A contracts listing plus the accounting that says whether it is COMPLETE.

    ``_paginate`` stops silently at ``_MAX_PAGES`` and the row parser silently
    skips anything malformed, so a truncated or row-dropped ladder is otherwise
    indistinguishable from a complete one — and the point-in-time ladder is
    exactly what the strike selection is computed from (D1 §3.4, §2.3
    mitigation 1). A caller that needs a *complete* ladder must check
    ``is_complete``; a cycle whose ladder is incomplete is excluded, never
    silently shortened.
    """

    rows: tuple[OptionContractRow, ...]
    pages_walked: int
    next_url_exhausted: bool  # True => pagination ended naturally
    page_cap_hit: bool  # True => stopped at _MAX_PAGES with more to come
    rows_unparseable: int

    @property
    def is_complete(self) -> bool:
        return self.next_url_exhausted and not self.page_cap_hit and self.rows_unparseable == 0


@dataclass(frozen=True, slots=True)
class DividendRow:
    """One declared cash dividend. Reference data — never a price series."""

    symbol: str
    ex_dividend_date: date
    cash_amount: float
    declaration_date: date | None
    record_date: date | None
    pay_date: date | None
    frequency: int | None
    dividend_type: str
    currency: str
    source: str


@dataclass(frozen=True, slots=True)
class SplitRow:
    """One executed share split. Reference data — never a price series."""

    symbol: str
    execution_date: date
    split_from: float
    split_to: float
    source: str

    @property
    def ratio(self) -> float:
        """Shares after / shares before (a 10:1 split is 10.0)."""
        return self.split_to / self.split_from if self.split_from else 0.0


@dataclass(frozen=True, slots=True)
class OptionAggregateRow:
    """One settled daily bar for a single option contract. Always HISTORICAL."""

    option_ticker: str
    underlying_symbol: str
    session_date: date
    open: float
    high: float
    low: float
    close: float
    volume: float
    vwap: float | None
    transactions: int | None
    source: str
    latency_category: LatencyCategory  # HISTORICAL — settled end-of-day bars


def _ns_to_dt(ns: Any) -> datetime | None:
    try:
        return datetime.fromtimestamp(float(ns) / 1e9, tz=UTC)
    except (TypeError, ValueError, OverflowError):
        return None


def _ms_to_date(ms: Any) -> date | None:
    try:
        return datetime.fromtimestamp(float(ms) / 1e3, tz=UTC).date()
    except (TypeError, ValueError, OverflowError):
        return None


class MassiveOptionsAdapter:
    provider_name = "massive_options"

    def __init__(
        self,
        api_key: str | None = None,
        *,
        client: httpx.Client | None = None,
        min_request_spacing_s: float | None = None,
    ) -> None:
        s = get_settings()
        self._key = (
            (s.options_api_key.get_secret_value() or s.market_data_api_key.get_secret_value())
            if api_key is None
            else api_key
        )
        self._client = client
        # Precedence (D1 §7.6): explicit argument, then OPTIONS_MIN_REQUEST_SPACING_S,
        # then the equities figure the repo actually documents (12.1 s). Never a
        # literal here — the options rate limit is undocumented (OQ-2), so the
        # inherited equities pace is the only defensible default.
        self._spacing_s = (
            min_request_spacing_s
            if min_request_spacing_s is not None
            else (
                s.options_min_request_spacing_s
                if s.options_min_request_spacing_s is not None
                else s.market_data_min_request_spacing_s
            )
        )
        self._last_request = 0.0

    @property
    def min_request_spacing_s(self) -> float:
        """The pacing actually in force — recorded on the run's provenance."""
        return self._spacing_s

    def _sleep(self, seconds: float) -> None:
        # short chunks so the kill switch stays responsive during a backoff
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            ensure_not_engaged()
            time.sleep(min(_BACKOFF_CHUNK_S, max(0.0, end - time.monotonic())))

    def _pace(self) -> None:
        # Injected test clients skip the wait (as the equities adapter does), so
        # the offline suite never sleeps for a rate limit that isn't there.
        while self._client is None:
            if time.monotonic() - self._last_request >= self._spacing_s:
                break
            ensure_not_engaged()
            time.sleep(_PACING_CHUNK_S)
        ensure_not_engaged()
        self._last_request = time.monotonic()

    @staticmethod
    def _retry_after_s(resp: httpx.Response, fallback: float) -> float:
        raw = resp.headers.get("retry-after", "")
        try:
            return min(_BACKOFF_CAP_S, max(0.0, float(raw)))
        except (TypeError, ValueError):
            return fallback

    def _get(self, path: str) -> dict[str, Any]:
        ensure_not_engaged()
        if not self._key:
            raise AdapterError("options adapter: no API key configured")
        getter = self._client.get if self._client is not None else httpx.get
        last_status: int | None = None
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            self._pace()
            try:
                resp = getter(
                    _BASE + path,
                    headers={"Authorization": f"Bearer {self._key}"},
                    timeout=_TIMEOUT,
                    follow_redirects=False,
                )
            except httpx.HTTPError:
                if attempt >= _MAX_ATTEMPTS:
                    raise AdapterError("options adapter: network request failed") from None
                self._sleep(min(_BACKOFF_CAP_S, _BACKOFF_BASE_S * 2 ** (attempt - 1)))
                continue
            last_status = resp.status_code
            if resp.status_code == 200:
                try:
                    body = resp.json()
                except ValueError:
                    raise AdapterError("options adapter: non-JSON response") from None
                return body if isinstance(body, dict) else {"results": body}
            if resp.status_code in (401, 403):
                # Terminal, never retried: burning a multi-day budget against an
                # entitlement wall is how a long run becomes a long no-op.
                raise AdapterError(
                    "options adapter: not authorized for this data", rate_limited=False
                )
            if resp.status_code in _RETRY_STATUS and attempt < _MAX_ATTEMPTS:
                backoff = min(_BACKOFF_CAP_S, _BACKOFF_BASE_S * 2 ** (attempt - 1))
                self._sleep(self._retry_after_s(resp, backoff))
                continue
            break
        if last_status == 429:
            raise AdapterError("options adapter: rate limited", rate_limited=True)
        raise AdapterError(f"options adapter: HTTP {last_status}")

    def _paginate(self, path: str) -> Iterator[dict[str, Any]]:
        yield from self._paginate_counted(path)[0]

    def _paginate_counted(self, path: str) -> tuple[list[dict[str, Any]], int, bool, bool]:
        """``(rows, pages_walked, next_url_exhausted, page_cap_hit)``.

        The plain ``_paginate`` cannot tell a complete listing from one truncated
        at ``_MAX_PAGES``; this one can, and every caller that needs a complete
        ladder uses it (D1 §3.4).
        """
        rows: list[dict[str, Any]] = []
        pages = 0
        next_path: str | None = path
        while next_path and pages < _MAX_PAGES:
            body = self._get(next_path)
            rows.extend(body.get("results", []) or [])
            nxt = body.get("next_url") or ""
            next_path = re.sub(r"^https?://[^/]+", "", nxt) if nxt else None
            pages += 1
        # Truthiness, not ``is None``: a ``next_url`` that strips to an empty
        # path is a listing that ended, not one truncated at the page cap, and
        # mislabelling it would exclude a cycle whose ladder was complete.
        return rows, pages, not next_path, bool(next_path)

    def fetch_contracts(
        self,
        underlying: str,
        *,
        expiration_gte: date,
        expiration_lte: date,
        strike_gte: float | None = None,
        strike_lte: float | None = None,
        limit: int = 250,
        expired: bool | None = None,
        as_of: date | None = None,
    ) -> list[OptionContractRow]:
        """Contracts listing. ``expired`` / ``as_of`` are opt-in and OFF by default.

        ``expired=True`` is what makes an EXPIRED series visible at all — the
        endpoint otherwise defaults to live contracts, so a listing call for a
        2023 expiry returns zero rows (D1 §7.0 / Appendix P: ``expired=true``
        works on this entitlement). ``as_of`` pins the listing to the state of
        the world on that date; without it the ladder for an expired series is
        its END-OF-LIFE ladder, which carries the strike-selection lookahead of
        D1 §3.3a. Both default to ``None`` so every existing call site issues a
        byte-identical request.
        """
        return list(
            self.fetch_contracts_page(
                underlying,
                expiration_gte=expiration_gte,
                expiration_lte=expiration_lte,
                strike_gte=strike_gte,
                strike_lte=strike_lte,
                limit=limit,
                expired=expired,
                as_of=as_of,
            ).rows
        )

    def fetch_contracts_page(
        self,
        underlying: str,
        *,
        expiration_gte: date,
        expiration_lte: date,
        strike_gte: float | None = None,
        strike_lte: float | None = None,
        limit: int = 250,
        expired: bool | None = None,
        as_of: date | None = None,
    ) -> ContractsPage:
        """As ``fetch_contracts``, but with the pagination / parse accounting."""
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
        if expired is not None:
            q += f"&expired={'true' if expired else 'false'}"
        if as_of is not None:
            q += f"&as_of={as_of.isoformat()}"
        raw, pages, exhausted, cap_hit = self._paginate_counted(q)
        out: list[OptionContractRow] = []
        unparseable = 0
        for r in raw:
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
                unparseable += 1
                continue
        return ContractsPage(
            rows=tuple(out),
            pages_walked=pages,
            next_url_exhausted=exhausted,
            page_cap_hit=cap_hit,
            rows_unparseable=unparseable,
        )

    def fetch_dividends(self, symbol: str, *, limit: int = 1000) -> list[DividendRow]:
        """Declared cash dividends for one underlying (reference data only).

        The continuous dividend yield ``q`` may never be left at its 0.0 default
        (map §2.4a, gate 0.g). This is the rank-1 source for it.
        """
        u = symbol.upper().strip()
        q = f"/v3/reference/dividends?ticker={u}&limit={min(limit, 1000)}&sort=ex_dividend_date"
        out: list[DividendRow] = []
        for r in self._paginate(q):
            ex = _d(r.get("ex_dividend_date"))
            amt = _f(r.get("cash_amount"))
            if ex is None or amt is None:
                continue
            out.append(
                DividendRow(
                    symbol=u,
                    ex_dividend_date=ex,
                    cash_amount=amt,
                    declaration_date=_d(r.get("declaration_date")),
                    record_date=_d(r.get("record_date")),
                    pay_date=_d(r.get("pay_date")),
                    frequency=_i(r.get("frequency")),
                    dividend_type=str(r.get("dividend_type", "") or ""),
                    currency=str(r.get("currency", "USD") or "USD"),
                    source=self.provider_name,
                )
            )
        out.sort(key=lambda x: x.ex_dividend_date)
        return out

    def fetch_splits(self, symbol: str, *, limit: int = 1000) -> list[SplitRow]:
        """Executed share splits for one underlying (reference data only).

        Option strikes are NOT back-adjusted while the stored equity series IS
        (D1 §2.3) — without this the point-in-time reference price for a
        pre-split cycle is off by the split factor and the whole chain silently
        returns nothing.
        """
        u = symbol.upper().strip()
        q = f"/v3/reference/splits?ticker={u}&limit={min(limit, 1000)}&sort=execution_date"
        out: list[SplitRow] = []
        for r in self._paginate(q):
            ex = _d(r.get("execution_date"))
            frm = _f(r.get("split_from"))
            to = _f(r.get("split_to"))
            if ex is None or not frm or not to:
                continue
            out.append(
                SplitRow(
                    symbol=u,
                    execution_date=ex,
                    split_from=frm,
                    split_to=to,
                    source=self.provider_name,
                )
            )
        out.sort(key=lambda x: x.execution_date)
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

    def fetch_option_aggregates(
        self,
        option_ticker: str,
        *,
        start: date,
        end: date,
        adjusted: bool = True,
    ) -> list[OptionAggregateRow]:
        """Settled daily bars for one option contract over ``[start, end]``.

        Read-only historical data. Every row is stamped ``HISTORICAL`` — this
        endpoint never carries a live or delayed price. Rows are returned in
        ascending date order, de-duplicated by session date.
        """
        u = option_ticker.split(":", 1)[-1][:6].upper() if ":" in option_ticker else ""
        adj = "true" if adjusted else "false"
        q = (
            f"/v2/aggs/ticker/{option_ticker}/range/1/day/"
            f"{start.isoformat()}/{end.isoformat()}?adjusted={adj}&sort=asc&limit=50000"
        )
        out: list[OptionAggregateRow] = []
        seen: set[date] = set()
        for r in self._paginate(q):
            d = _ms_to_date(r.get("t"))
            if d is None or d in seen:
                continue
            try:
                row = OptionAggregateRow(
                    option_ticker=option_ticker,
                    underlying_symbol=u,
                    session_date=d,
                    open=float(r["o"]),
                    high=float(r["h"]),
                    low=float(r["l"]),
                    close=float(r["c"]),
                    volume=float(r.get("v", 0.0) or 0.0),
                    vwap=_f(r.get("vw")),
                    transactions=_i(r.get("n")),
                    source=self.provider_name,
                    latency_category=LatencyCategory.HISTORICAL,
                )
            except (KeyError, ValueError, TypeError):
                continue
            seen.add(d)
            out.append(row)
        out.sort(key=lambda x: x.session_date)
        return out


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


def _d(x: Any) -> date | None:
    try:
        return date.fromisoformat(str(x)) if x else None
    except (TypeError, ValueError):
        return None
