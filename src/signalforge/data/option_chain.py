"""Point-in-time option-chain view (D2 §3) — the data view the engine rests on.

Mirrors :class:`signalforge.data.series.PriceSeries`'s ``head(t)`` contract, for
the same reason: a strategy at session ``t`` is *handed* the truncated view and
cannot opt out, so look-ahead is a structural impossibility rather than a review
item.

Three properties are load-bearing and each is enforced by a type, not a comment:

* :meth:`OptionChainSeries.head` truncates the session list **and** the visible
  contract set (D2 §3.3).  A ``head`` that truncated sessions but left
  ``contracts`` at full extent would let a feature read a strike that did not yet
  exist, and the leakage harness would not catch it.
* **Visibility rule (D2 §3.3 / correction C5).**  ``OptionContract`` carries no
  listing date and ``ingested_at`` is our retrieval time, so "which contracts
  existed on 2024-03-15" is not answerable from the schema.  The only
  data-grounded rule is: a contract is visible at session ``t`` only if it has
  **printed** at some session ``<= t``.  Disclosed cost: it biases strike
  selection toward already-traded (more liquid) strikes; the strategy layer
  reports ``target_strike_invisible_count`` against it.
* :meth:`OptionChainSeries.print_at` returns ``ContractPrint | None`` and the
  ``None`` is a **first-class liquidity fact**.  It is never coerced to 0.0, to
  the previous session's close, or to a model price.  A :class:`Mark` is a
  *different type* precisely so that a fill function cannot be handed one.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from types import MappingProxyType


class Right(StrEnum):
    CALL = "call"
    PUT = "put"


@dataclass(frozen=True, slots=True)
class ContractRef:
    """Reference metadata for one contract, plus its derived first print session.

    ``shares_per_contract`` is READ from the stored row and never defaulted here.
    D2 correction C6: the adapter writes ``int(r.get("shares_per_contract", 100))``,
    so a vendor *omission* is indistinguishable from a vendor-confirmed 100 and the
    downstream ``== 100`` assertion is weaker than it looks.  Until the data layer
    records the provenance of that field (D1), the engine's refusal counter is the
    only visible handle on it.
    """

    option_ticker: str
    underlying_symbol: str
    right: Right
    strike: float
    expiration: date
    shares_per_contract: int
    exercise_style: str
    first_print_session: date


@dataclass(frozen=True, slots=True)
class ContractPrint:
    """A settled daily bar for one contract.  Only this type can be filled on."""

    open: float
    high: float
    low: float
    close: float
    volume: float
    vwap: float | None = None
    transactions: int | None = None

    @property
    def last_print(self) -> float:
        """The fill reference (D2 §6.1): the close, never the thin daily open."""
        return self.close


@dataclass(frozen=True, slots=True)
class Mark:
    """A *modelled* value for a contract that did not print.

    The firewall (D2 §6.4), stated because the type alone does not say it: a
    ``Mark`` participates in reported unrealised diagnostics ONLY — never in an
    exit trigger, never in R, never in realised P&L, never in any gated statistic.
    Fill functions accept :class:`ContractPrint` and refuse this type.
    """

    value: float
    iv_source: str


@dataclass(frozen=True, slots=True)
class ChainSession:
    session_date: date
    underlying_close: float
    prints: Mapping[str, ContractPrint]


@dataclass(frozen=True, slots=True)
class OptionChainSeries:
    """Sessions indexed by the **underlying's** session list (D2 §3.5).

    Index ``t`` therefore means the same thing here and in the underlying
    ``PriceSeries``, which is what lets one ``t`` address both in a chain feature
    and what lets the existing IS/OOS boundary arithmetic be reused unchanged.
    """

    underlying: str
    sessions: tuple[ChainSession, ...]
    contracts: Mapping[str, ContractRef]

    def __post_init__(self) -> None:
        dates = [s.session_date for s in self.sessions]
        if dates != sorted(dates):
            raise ValueError("OptionChainSeries.sessions must be ordered by session_date")
        if len(set(dates)) != len(dates):
            raise ValueError("OptionChainSeries.sessions must have unique session_date")

    def __len__(self) -> int:
        return len(self.sessions)

    def session_dates(self) -> tuple[date, ...]:
        return tuple(s.session_date for s in self.sessions)

    def index_of(self, d: date) -> int | None:
        for i, s in enumerate(self.sessions):
            if s.session_date == d:
                return i
        return None

    def head(self, t: int) -> OptionChainSeries:
        """Sessions ``0..t`` inclusive **and** the contract set visible at ``t``."""
        if t < 0:
            raise IndexError("t must be >= 0")
        sessions = self.sessions[: t + 1]
        as_of = sessions[-1].session_date if sessions else None
        visible = (
            {
                k: c
                for k, c in self.contracts.items()
                if as_of is not None and c.first_print_session <= as_of
            }
            if as_of is not None
            else {}
        )
        return OptionChainSeries(
            underlying=self.underlying,
            sessions=sessions,
            contracts=MappingProxyType(dict(sorted(visible.items()))),
        )

    def print_at(self, t: int, ticker: str) -> ContractPrint | None:
        """The print for ``ticker`` at session ``t``, or ``None``.

        ``None`` is the answer, not a missing value: it means the contract did not
        trade.  Never substitute a default.
        """
        if not (0 <= t < len(self.sessions)):
            return None
        return self.sessions[t].prints.get(ticker)

    def printed_tickers(self, t: int) -> frozenset[str]:
        if not (0 <= t < len(self.sessions)):
            return frozenset()
        return frozenset(self.sessions[t].prints)

    def visible_contracts(self, t: int) -> Mapping[str, ContractRef]:
        if not (0 <= t < len(self.sessions)):
            return MappingProxyType({})
        as_of = self.sessions[t].session_date
        return MappingProxyType(
            dict(
                sorted((k, c) for k, c in self.contracts.items() if c.first_print_session <= as_of)
            )
        )

    def underlying_close(self, t: int) -> float | None:
        if not (0 <= t < len(self.sessions)):
            return None
        return self.sessions[t].underlying_close

    # -- construction --------------------------------------------------------

    @classmethod
    def from_rows(
        cls,
        underlying: str,
        *,
        contracts: Iterable[ContractRef],
        underlying_closes: Mapping[date, float],
        prints: Mapping[date, Mapping[str, ContractPrint]],
    ) -> OptionChainSeries:
        """Build from already-loaded rows.

        ``underlying_closes`` defines the session index (D2 §3.5): a session with
        an option print but no underlying bar is a data defect and is **excluded**
        rather than interpolated — the caller counts it and surfaces the count
        (D2 §3.4).  ``first_print_session`` on each :class:`ContractRef` is the
        caller's derived ``min(session_date)`` over that contract's bars.
        """
        sessions = tuple(
            ChainSession(
                session_date=d,
                underlying_close=underlying_closes[d],
                prints=MappingProxyType(dict(sorted(prints.get(d, {}).items()))),
            )
            for d in sorted(underlying_closes)
        )
        refs = {c.option_ticker: c for c in contracts}
        return cls(
            underlying=underlying.strip().upper(),
            sessions=sessions,
            contracts=MappingProxyType(dict(sorted(refs.items()))),
        )
