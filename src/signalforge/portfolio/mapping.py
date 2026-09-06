"""Broker-CSV column maps. Pure string handling — no I/O, no network (invariant S2)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PositionColumns:
    symbol: tuple[str, ...]
    quantity: tuple[str, ...]
    cost_basis: tuple[str, ...] = ()
    market_value: tuple[str, ...] = ()
    account: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class TransactionColumns:
    date: tuple[str, ...]
    action: tuple[str, ...]
    symbol: tuple[str, ...]
    quantity: tuple[str, ...] = ()
    price: tuple[str, ...] = ()
    amount: tuple[str, ...] = ()


POSITION_FORMATS: dict[str, PositionColumns] = {
    "generic_positions": PositionColumns(
        symbol=("symbol", "ticker"),
        quantity=("quantity", "qty", "shares"),
        cost_basis=("cost basis", "cost", "cost_basis"),
        market_value=("market value", "value", "current value"),
        account=("account", "account name"),
    ),
    "fidelity_positions": PositionColumns(
        symbol=("symbol",),
        quantity=("quantity",),
        cost_basis=("cost basis total", "cost basis"),
        market_value=("current value",),
        account=("account name", "account number"),
    ),
    "schwab_positions": PositionColumns(
        symbol=("symbol",),
        quantity=("qty (quantity)", "quantity"),
        cost_basis=("cost basis",),
        market_value=("mkt val (market value)", "market value"),
    ),
}

TRANSACTION_FORMATS: dict[str, TransactionColumns] = {
    "fidelity_history": TransactionColumns(
        date=("run date", "date"),
        action=("action",),
        symbol=("symbol",),
        quantity=("quantity",),
        price=("price ($)", "price"),
        amount=("amount ($)", "amount"),
    ),
    "generic_history": TransactionColumns(
        date=("date", "trade date"),
        action=("action", "type", "transaction type"),
        symbol=("symbol", "ticker"),
        quantity=("quantity", "qty", "shares"),
        price=("price",),
        amount=("amount", "net amount"),
    ),
}


def pick(header: list[str], candidates: tuple[str, ...]) -> str | None:
    lowered = {h.strip().lower(): h for h in header}
    for c in candidates:
        if c in lowered:
            return lowered[c]
    return None
