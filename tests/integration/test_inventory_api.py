"""Inventory endpoints on top of real packages, with lots created by each test."""

import threading
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import DispenseRecord, InventoryLot, ReorderRule
from app.domain.errors import InsufficientStockError
from app.services.inventory import InventoryService

pytestmark = pytest.mark.integration

TODAY = date.today()
LIPITOR = "58151-155-77"  # real package: Lipitor 10 mg, 90 tablets
LANTUS = "50090-1398-0"  # real package: Lantus Solostar


def add_lot(
    db: Session, package: str, number: str, qty: int, days: int, received_days_ago: int = 30
) -> int:
    lot = InventoryLot(
        package_ndc=package,
        lot_number=number,
        quantity=qty,
        expiration_date=TODAY + timedelta(days=days),
        received_at=datetime.now(UTC) - timedelta(days=received_days_ago),
    )
    db.add(lot)
    db.commit()
    return lot.id


@pytest.fixture
def stocked(client: TestClient, db: Session) -> Iterator[dict[str, int]]:
    """Lipitor: 5 units expiring soon, 50 later, 100 already expired. Reorder at 100."""
    lots = {
        "soon": add_lot(db, LIPITOR, "SOON01", 5, days=10),
        "later": add_lot(db, LIPITOR, "LATER01", 50, days=200),
        "expired": add_lot(db, LIPITOR, "OLD01", 100, days=-3),
    }
    db.add(ReorderRule(package_ndc=LIPITOR, reorder_threshold=100))
    db.add(ReorderRule(package_ndc=LANTUS, reorder_threshold=10))  # no lots at all
    db.commit()
    yield lots


def test_stock_sums_lots_and_separates_expired(client: TestClient, stocked: dict[str, int]) -> None:
    body = client.get("/inventory").json()
    assert body["total"] == 1
    line = body["items"][0]
    assert line["package_ndc"] == LIPITOR
    assert line["drug_name"] == "Lipitor (atorvastatin calcium)"
    assert line["usable_quantity"] == 55
    assert line["expired_quantity"] == 100
    assert line["lot_count"] == 3
    assert line["next_expiration"] == (TODAY + timedelta(days=10)).isoformat()
    assert line["below_threshold"] is True
    assert client.get("/inventory", params={"package_ndc": LANTUS}).json()["total"] == 0


def test_dispense_uses_fefo_and_records_lots(
    client: TestClient, stocked: dict[str, int], db: Session
) -> None:
    response = client.post(
        "/inventory/dispense", json={"package_ndc": LIPITOR, "quantity": 20, "reference": "RX-1"}
    )

    assert response.status_code == 200
    body = response.json()
    assert [(a["lot_number"], a["quantity"]) for a in body["allocations"]] == [
        ("SOON01", 5),
        ("LATER01", 15),
    ]
    assert body["remaining_usable"] == 35
    records = db.scalars(select(DispenseRecord).order_by(DispenseRecord.id)).all()
    assert [(r.lot_id, r.quantity, r.reference) for r in records] == [
        (stocked["soon"], 5, "RX-1"),
        (stocked["later"], 15, "RX-1"),
    ]
    expired = db.get(InventoryLot, stocked["expired"])
    assert expired is not None and expired.quantity == 100  # expired stock never touched


def test_dispense_more_than_usable_changes_nothing(
    client: TestClient, stocked: dict[str, int], db: Session
) -> None:
    response = client.post("/inventory/dispense", json={"package_ndc": LIPITOR, "quantity": 56})

    assert response.status_code == 409
    assert response.json()["error"] == {
        "code": "insufficient_stock",
        "message": "Requested 56 units but only 55 usable units are in stock",
        "details": {"requested": 56, "available": 55},
    }
    assert db.scalar(select(func.sum(InventoryLot.quantity))) == 155
    assert db.scalar(select(func.count()).select_from(DispenseRecord)) == 0


@pytest.mark.parametrize(
    ("payload", "status"),
    [
        ({"package_ndc": "0000-0000-00", "quantity": 1}, 404),
        ({"package_ndc": LIPITOR, "quantity": 0}, 422),
        ({"package_ndc": LANTUS, "quantity": 1}, 409),  # no stock at all
    ],
)
def test_dispense_errors(
    client: TestClient, stocked: dict[str, int], payload: dict[str, object], status: int
) -> None:
    assert client.post("/inventory/dispense", json=payload).status_code == status


def test_receive_lot(client: TestClient) -> None:
    expires = (TODAY + timedelta(days=365)).isoformat()
    response = client.post(
        "/inventory/lots",
        json={
            "package_ndc": LANTUS,
            "lot_number": "NEW-01",
            "quantity": 40,
            "expiration_date": expires,
        },
    )
    assert response.status_code == 201
    assert response.json()["quantity"] == 40
    line = client.get("/inventory", params={"package_ndc": LANTUS}).json()["items"][0]
    assert line["usable_quantity"] == 40


@pytest.mark.parametrize(
    ("change", "status", "code"),
    [
        ({"package_ndc": "0000-0000-00"}, 404, "not_found"),
        ({"expiration_date": (TODAY - timedelta(days=1)).isoformat()}, 422, "invalid_lot"),
        ({"lot_number": "SOON01"}, 409, "conflict"),  # same lot already received
        ({"quantity": -5}, 422, "validation_error"),
        ({"lot_number": "bad lot!"}, 422, "validation_error"),
    ],
)
def test_receive_lot_errors(
    client: TestClient, stocked: dict[str, int], change: dict[str, object], status: int, code: str
) -> None:
    payload = {
        "package_ndc": LIPITOR,
        "lot_number": "X1",
        "quantity": 10,
        "expiration_date": (TODAY + timedelta(days=90)).isoformat(),
        **change,
    }
    response = client.post("/inventory/lots", json=payload)
    assert response.status_code == status
    assert response.json()["error"]["code"] == code


def test_expiring_lots(client: TestClient, stocked: dict[str, int]) -> None:
    body = client.get("/inventory/expiring", params={"days": 30}).json()
    assert [(i["lot_number"], i["days_until_expiry"]) for i in body["items"]] == [("SOON01", 10)]

    with_expired = client.get(
        "/inventory/expiring", params={"days": 30, "include_expired": True}
    ).json()
    assert [(i["lot_number"], i["days_until_expiry"]) for i in with_expired["items"]] == [
        ("OLD01", -3),
        ("SOON01", 10),
    ]
    assert client.get("/inventory/expiring", params={"days": -1}).status_code == 422


def test_low_stock_counts_only_usable_units(client: TestClient, stocked: dict[str, int]) -> None:
    body = client.get("/inventory/low-stock").json()
    assert body["total"] == 2
    # Worst first: Lipitor is 45 short (55 usable of 100), Lantus is 10 short (0 of 10).
    assert [(i["package_ndc"], i["usable_quantity"]) for i in body["items"]] == [
        (LIPITOR, 55),
        (LANTUS, 0),
    ]
    assert all(i["below_threshold"] for i in body["items"])


def test_concurrent_dispenses_never_oversell(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    """10 requests for 10 units each race for 50 units: exactly 5 can succeed."""
    with session_factory() as session:
        add_lot(session, LANTUS, "RACE01", 30, days=60)
        add_lot(session, LANTUS, "RACE02", 20, days=90)

    barrier = threading.Barrier(10)

    def attempt(_: int) -> bool:
        with session_factory() as session:
            barrier.wait()
            try:
                InventoryService(session).dispense(LANTUS, 10, "race")
                return True
            except InsufficientStockError:
                return False

    with ThreadPoolExecutor(max_workers=10) as pool:
        results = list(pool.map(attempt, range(10)))

    assert results.count(True) == 5
    with session_factory() as session:
        lots = session.scalars(select(InventoryLot).where(InventoryLot.package_ndc == LANTUS)).all()
        assert sum(lot.quantity for lot in lots) == 0
        assert session.scalar(select(func.sum(DispenseRecord.quantity))) == 50
