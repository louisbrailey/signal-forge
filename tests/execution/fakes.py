"""A fake ``BrokerAdapter`` for the I-E4 tests — deliberately NOT an adapter.

``brokers/paper_reference.py`` is I-E3 and is being built on another branch.
Nothing here depends on it, and nothing here is an adapter the system could
ever use: it is a test double that satisfies the ``BrokerAdapter`` protocol so
the cycle, reconciliation and arming paths can be driven end to end without a
network, without a vendor, and without waiting on a parallel branch.

Every method is a plain in-memory answer that the test sets up front, and every
one of them can be told to raise — because "the adapter could not be reached" is
a distinct verdict from "the adapter said no", and several of the rules under
test are about exactly that difference.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

from signalforge.execution.intents import (
    AccountSnapshot,
    ComboOrderIntent,
    MarketClock,
    OrderIntent,
    OrderResult,
    OrderStatus,
    PositionSnapshot,
)
from signalforge.execution.protocol import IsPaperProof
from signalforge.execution.states import OrderState

__all__ = ["FakeAdapter", "FakePosition"]


@dataclass(frozen=True, slots=True)
class FakePosition:
    """A ``PositionSnapshot`` plus the originating id reconciliation reads.

    A real ``PositionSnapshot`` carries no originating ``client_order_id`` — the
    broker does not owe us one — so an adapter that CAN supply it does, and one
    that cannot yields nothing, which §10 treats as a divergence rather than as a
    pass. This double exercises both.
    """

    snapshot: PositionSnapshot
    originating_client_order_id: str = ""

    @property
    def legs(self) -> tuple:  # pragma: no cover - trivial delegation
        return self.snapshot.legs


@dataclass
class FakeAdapter:
    name: str = "paper_reference"
    account_id: str = "PAPER-ACCOUNT-1"
    host: str = "paper.example.invalid"
    equity: float = 25_000.0
    buying_power: float = 25_000.0
    positions_: list[FakePosition] = field(default_factory=list)
    open_orders_: list[OrderStatus] = field(default_factory=list)
    clock_: MarketClock | None = None
    is_paper_proven: bool = True
    raise_on: frozenset[str] = frozenset()
    cancel_all_calls: int = 0
    placed: list[str] = field(default_factory=list)

    def _maybe_raise(self, method: str) -> None:
        if method in self.raise_on:
            raise ConnectionError(f"fake adapter: {method}() is unreachable")

    def is_paper(self) -> IsPaperProof:
        self._maybe_raise("is_paper")
        return IsPaperProof(
            proven=self.is_paper_proven,
            observed_account_id=self.account_id,
            observed_host=self.host,
            expected_account_id=self.account_id if self.is_paper_proven else "",
            checked_at=datetime.now(UTC),
            failure_reason="" if self.is_paper_proven else "stubbed mismatch",
        )

    def account(self) -> AccountSnapshot:
        self._maybe_raise("account")
        return AccountSnapshot(
            account_id=self.account_id, equity=self.equity, buying_power=self.buying_power
        )

    def positions(self) -> Sequence[FakePosition]:
        self._maybe_raise("positions")
        return list(self.positions_)

    def open_orders(self) -> Sequence[OrderStatus]:
        self._maybe_raise("open_orders")
        return list(self.open_orders_)

    def order_status(self, client_order_id: str) -> OrderStatus | None:
        self._maybe_raise("order_status")
        for order in self.open_orders_:
            if order.client_order_id == client_order_id:
                return order
        return None

    def place(self, intent: OrderIntent) -> OrderResult:
        self._maybe_raise("place")
        self.placed.append(intent.client_order_id)
        return OrderResult(client_order_id=intent.client_order_id, state=OrderState.FILLED)

    def place_combo(self, intent: ComboOrderIntent) -> OrderResult:
        self._maybe_raise("place_combo")
        self.placed.append(intent.client_order_id)
        return OrderResult(client_order_id=intent.client_order_id, state=OrderState.FILLED)

    def cancel(self, client_order_id: str) -> OrderResult:
        self._maybe_raise("cancel")
        return OrderResult(client_order_id=client_order_id, state=OrderState.CANCELLED)

    def cancel_all(self) -> Sequence[OrderResult]:
        self._maybe_raise("cancel_all")
        self.cancel_all_calls += 1
        out = [
            OrderResult(client_order_id=o.client_order_id, state=OrderState.CANCELLED)
            for o in self.open_orders_
        ]
        self.open_orders_ = []
        return out

    def clock(self) -> MarketClock:
        self._maybe_raise("clock")
        if self.clock_ is not None:
            return self.clock_
        return MarketClock(is_open=True, as_of=datetime.now(UTC))
