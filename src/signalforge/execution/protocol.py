"""The ``BrokerAdapter`` protocol (D6 ADR §3) and the ``is_paper`` proof (§13).

**No vendor package and no HTTP client is imported in this file, ever.** It is a
typing surface: the shapes an adapter must satisfy, and the four conditions that
make an adapter eligible at all. No adapter exists in this phase (I-E2) — the
first one, ``brokers/paper_reference.py``, is local, deterministic and
network-free, and is I-E3.

Four hard eligibility conditions. An adapter failing any ONE is ineligible, and
these are not limitations for the OMS to work around:

======  ===========================================================  ==========
A1      ``place``/``place_combo`` are idempotent on ``client_order_id``  a retry after
        a timeout must never double-fill
A2      a multi-leg structure submits as ONE atomic native combo      leg-by-leg
        order                                                         partial fill
                                                                      manufactures a
                                                                      naked short option
A3      ``is_paper()`` is provable from the broker's OWN response      a misconfigured
        body                                                          base URL is the
                                                                      single most likely
                                                                      way real money gets
                                                                      touched
A4      ``order_status(client_order_id)`` resolves a TERMINAL order,   otherwise the
        not only an open one                                          post-timeout
                                                                      non-duplication
                                                                      procedure cannot be
                                                                      implemented
======  ===========================================================  ==========

A4 is why this protocol departs from the map's §6.2 shape: a filled or rejected
order is by definition not in ``open_orders()``, so ``open_orders()`` alone
cannot distinguish "the broker never saw it" from "the broker filled it and it
is no longer open".

Every method is synchronous and bounded by an explicit timeout; no vendor type
crosses this boundary; and no method accepts free text, a natural-language
field, or any value produced by ``signalforge.llm``.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable

from signalforge.execution.intents import (
    AccountSnapshot,
    ComboOrderIntent,
    MarketClock,
    OrderIntent,
    OrderResult,
    OrderStatus,
    PositionSnapshot,
)

__all__ = [
    "ADAPTER_ELIGIBILITY_CONDITIONS",
    "BrokerAdapter",
    "IsPaperProof",
]

#: Documented here so an adapter review has one list to check against.
ADAPTER_ELIGIBILITY_CONDITIONS: tuple[str, ...] = (
    "A1: place/place_combo are idempotent on client_order_id",
    "A2: a multi-leg structure submits as one atomic native combo order",
    "A3: is_paper() is provable from the broker's own response body",
    "A4: order_status(client_order_id) resolves a terminal order, not only an open one",
)


@dataclass(frozen=True, slots=True)
class IsPaperProof:
    """§13 — a PROOF object, never a bool derived from a local config flag.

    A local flag and the base URL are set in the same place by the same
    mistake, so a flag cannot catch the mistake. ``observed_account_id`` and
    ``observed_host`` are read out of the BROKER'S OWN response; a mismatch, an
    absent field, or an unparseable response is a FAILURE, not a warning, and
    it blocks arming and every subsequent submission.

    ``raw_excerpt`` is stored only after passing through
    ``observability.redact``.
    """

    proven: bool
    observed_account_id: str
    observed_host: str
    expected_account_id: str
    checked_at: datetime
    raw_excerpt: str = ""
    failure_reason: str = ""

    def __post_init__(self) -> None:
        if self.proven and (
            not self.observed_account_id or self.observed_account_id != self.expected_account_id
        ):
            raise ValueError(
                "an IsPaperProof cannot be 'proven' unless the observed account id matches "
                "the expected one read from the armed record"
            )


@runtime_checkable
class BrokerAdapter(Protocol):
    """What the OMS may call. Nothing more, and nothing that takes free text."""

    name: str

    def is_paper(self) -> IsPaperProof:
        """§13. Re-taken EVERY cycle, not once at arm time."""
        ...

    def account(self) -> AccountSnapshot: ...

    def positions(self) -> Sequence[PositionSnapshot]: ...

    def open_orders(self) -> Sequence[OrderStatus]: ...

    def order_status(self, client_order_id: str) -> OrderStatus | None:
        """A1/A4 — resolves a TERMINAL order, not only an open one."""
        ...

    def place(self, intent: OrderIntent) -> OrderResult:
        """Idempotent on ``client_order_id``."""
        ...

    def place_combo(self, intent: ComboOrderIntent) -> OrderResult:
        """ONE atomic multi-leg instruction. There is no loop over legs."""
        ...

    def cancel(self, client_order_id: str) -> OrderResult: ...

    def cancel_all(self) -> Sequence[OrderResult]:
        """Used by the kill-switch drain sequence (§8)."""
        ...

    def clock(self) -> MarketClock:
        """Cross-checked against the local calendar every cycle; disagreement
        blocks (§11)."""
        ...
