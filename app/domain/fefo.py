"""FEFO: First Expiring, First Out.

When a pharmacy hands out medicine, it should use the stock that expires
soonest first, so less medicine goes to waste. This module decides which lots
to take from. It is a pure function: it does not touch the database, which
makes it easy to test every edge case.

Rules:
* Lots that are already expired are never used.
* A lot is usable up to and including its expiration date.
* Lots are used in order of expiration date. Ties go to the lot received
  first, then to the lower lot id, so the result is always the same.
* If the usable lots together do not have enough, nothing is taken and an
  ``InsufficientStockError`` explains how much is available.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime

from app.domain.errors import InsufficientStockError


@dataclass(frozen=True, slots=True)
class LotStock:
    lot_id: int
    lot_number: str
    quantity: int
    expiration_date: date
    received_at: datetime


@dataclass(frozen=True, slots=True)
class Allocation:
    """Take ``quantity`` units from this lot."""

    lot_id: int
    lot_number: str
    quantity: int
    expiration_date: date


def usable_lots(lots: Iterable[LotStock], today: date) -> list[LotStock]:
    """Lots with stock that have not expired, in FEFO order."""
    usable = [lot for lot in lots if lot.quantity > 0 and lot.expiration_date >= today]
    return sorted(usable, key=lambda lot: (lot.expiration_date, lot.received_at, lot.lot_id))


def plan_fefo(lots: Iterable[LotStock], quantity: int, today: date) -> list[Allocation]:
    """Decide how many units to take from each lot to dispense ``quantity`` units."""
    if quantity <= 0:
        raise ValueError("quantity must be positive")

    ordered = usable_lots(lots, today)
    available = sum(lot.quantity for lot in ordered)
    if available < quantity:
        raise InsufficientStockError(
            f"Requested {quantity} units but only {available} usable units are in stock",
            requested=quantity,
            available=available,
        )

    plan: list[Allocation] = []
    remaining = quantity
    for lot in ordered:
        take = min(lot.quantity, remaining)
        plan.append(Allocation(lot.lot_id, lot.lot_number, take, lot.expiration_date))
        remaining -= take
        if remaining == 0:
            break
    return plan
