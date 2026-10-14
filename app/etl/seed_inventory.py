"""Step 5 of the ETL: create SYNTHETIC inventory for a sample of real packages.

The drugs are real FDA data, but the stock levels, lot numbers, and
expiration dates are made up (seeded random numbers and Faker), because real
pharmacy inventory is private. Some lots are generated already expired or
expiring soon, so the expiration alerts and FEFO logic have something to do.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta

from faker import Faker
from sqlalchemy import Engine, insert, select, text

from app.db.models import InventoryLot, Package, Product, ReorderRule
from app.etl.load import batches

STOCKED_PRODUCT_TYPES = ("HUMAN PRESCRIPTION DRUG", "HUMAN OTC DRUG")


@dataclass(frozen=True)
class SeedStats:
    packages: int
    lots: int
    reorder_rules: int


def seed_inventory(
    engine: Engine, packages: int = 20_000, seed: int = 42, today: date | None = None
) -> SeedStats:
    """Replace all inventory with fresh synthetic lots for ``packages`` random packages."""
    today = today or date.today()
    rng = random.Random(seed)
    fake = Faker()
    fake.seed_instance(seed)

    with engine.begin() as conn:
        conn.execute(
            text("TRUNCATE dispense_records, inventory_lots, reorder_rules RESTART IDENTITY")
        )
        candidates = list(
            conn.scalars(
                select(Package.package_ndc)
                .join(Product)
                .where(Product.product_type.in_(STOCKED_PRODUCT_TYPES))
                .order_by(Package.package_ndc)
            )
        )
        sample = rng.sample(candidates, min(packages, len(candidates)))

        lots: list[dict[str, object]] = []
        rules: list[dict[str, object]] = []
        for package_ndc in sample:
            lot_numbers: set[str] = set()
            for _ in range(rng.randint(1, 4)):
                lot_number = fake.bothify("??#####").upper()
                while lot_number in lot_numbers:
                    lot_number = fake.bothify("??#####").upper()
                lot_numbers.add(lot_number)
                # Mostly 2 months to 2 years out; about 1 in 12 already expired.
                expires = today + timedelta(days=rng.randint(-45, 730))
                received = today - timedelta(days=rng.randint(5, 400))
                lots.append(
                    {
                        "package_ndc": package_ndc,
                        "lot_number": lot_number,
                        "quantity": rng.randint(5, 400),
                        "expiration_date": expires,
                        "received_at": datetime.combine(received, time(9), tzinfo=UTC),
                    }
                )
            rules.append({"package_ndc": package_ndc, "reorder_threshold": rng.randint(50, 300)})

        for batch in batches(lots):
            conn.execute(insert(InventoryLot), batch)
        for batch in batches(rules):
            conn.execute(insert(ReorderRule), batch)

    return SeedStats(packages=len(sample), lots=len(lots), reorder_rules=len(rules))
