"""FEFO is a pure function, so every rule can be tested without a database."""

from datetime import UTC, date, datetime, timedelta

import pytest

from app.domain.errors import InsufficientStockError
from app.domain.fefo import Allocation, LotStock, plan_fefo, usable_lots

TODAY = date(2026, 6, 1)
RECEIVED = datetime(2026, 1, 1, tzinfo=UTC)


def lot(
    lot_id: int, quantity: int, expires_in_days: int, received_offset_days: int = 0
) -> LotStock:
    return LotStock(
        lot_id=lot_id,
        lot_number=f"LOT{lot_id}",
        quantity=quantity,
        expiration_date=TODAY + timedelta(days=expires_in_days),
        received_at=RECEIVED + timedelta(days=received_offset_days),
    )


def taken(plan: list[Allocation]) -> list[tuple[int, int]]:
    return [(a.lot_id, a.quantity) for a in plan]


def test_uses_the_lot_that_expires_first() -> None:
    lots = [lot(1, 100, expires_in_days=300), lot(2, 100, expires_in_days=30)]
    assert taken(plan_fefo(lots, 10, TODAY)) == [(2, 10)]


def test_spans_several_lots_in_expiry_order() -> None:
    lots = [lot(1, 50, 300), lot(2, 5, 10), lot(3, 20, 100)]
    assert taken(plan_fefo(lots, 40, TODAY)) == [(2, 5), (3, 20), (1, 15)]


def test_never_uses_expired_lots() -> None:
    lots = [lot(1, 100, expires_in_days=-1), lot(2, 30, expires_in_days=60)]
    assert taken(plan_fefo(lots, 30, TODAY)) == [(2, 30)]


def test_lot_expiring_today_is_still_usable() -> None:
    assert taken(plan_fefo([lot(1, 10, expires_in_days=0)], 10, TODAY)) == [(1, 10)]


def test_ties_go_to_the_lot_received_first_then_lower_id() -> None:
    lots = [
        lot(3, 10, 30, received_offset_days=5),
        lot(2, 10, 30, received_offset_days=0),
        lot(1, 10, 30, received_offset_days=5),
    ]
    assert taken(plan_fefo(lots, 25, TODAY)) == [(2, 10), (1, 10), (3, 5)]


def test_empty_lots_are_ignored() -> None:
    lots = [lot(1, 0, 5), lot(2, 10, 50)]
    assert taken(plan_fefo(lots, 10, TODAY)) == [(2, 10)]


def test_exact_amount_uses_everything() -> None:
    lots = [lot(1, 10, 5), lot(2, 10, 50)]
    assert sum(a.quantity for a in plan_fefo(lots, 20, TODAY)) == 20


def test_not_enough_usable_stock_raises_and_reports_available() -> None:
    lots = [lot(1, 500, expires_in_days=-10), lot(2, 30, 10), lot(3, 20, 20)]
    with pytest.raises(InsufficientStockError) as exc:
        plan_fefo(lots, 51, TODAY)
    assert exc.value.details == {"requested": 51, "available": 50}


@pytest.mark.parametrize("bad", [0, -3])
def test_quantity_must_be_positive(bad: int) -> None:
    with pytest.raises(ValueError):
        plan_fefo([lot(1, 10, 10)], bad, TODAY)


def test_usable_lots_orders_and_filters() -> None:
    lots = [lot(1, 5, 90), lot(2, 5, -1), lot(3, 0, 10), lot(4, 5, 10)]
    assert [x.lot_id for x in usable_lots(lots, TODAY)] == [4, 1]


def test_allocation_carries_lot_details() -> None:
    (allocation,) = plan_fefo([lot(7, 10, 45)], 3, TODAY)
    assert allocation == Allocation(7, "LOT7", 3, TODAY + timedelta(days=45))
