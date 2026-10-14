"""Inventory use cases: stock levels, receiving lots, FEFO dispensing, alerts."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import ColumnElement, Select, case, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import InstrumentedAttribute, Session

from app.db.models import DispenseRecord, InventoryLot, Package, Product, ReorderRule
from app.domain.errors import ConflictError, InvalidLotError, NotFoundError
from app.domain.fefo import Allocation, LotStock, plan_fefo


@dataclass(frozen=True)
class StockLine:
    package_ndc: str
    product_ndc: str
    drug_name: str
    package_description: str | None
    usable_quantity: int
    expired_quantity: int
    lot_count: int
    next_expiration: date | None
    reorder_threshold: int | None

    @property
    def below_threshold(self) -> bool:
        return self.reorder_threshold is not None and self.usable_quantity < self.reorder_threshold


@dataclass(frozen=True)
class DispenseResult:
    package_ndc: str
    quantity: int
    allocations: list[Allocation]
    remaining_usable: int


def drug_name_column() -> ColumnElement[str]:
    """ "Brand (generic)" when they differ, otherwise whichever name exists."""
    same_or_missing = or_(
        Product.brand_name.is_(None),
        Product.generic_name.is_(None),
        func.lower(Product.brand_name) == func.lower(Product.generic_name),
    )
    return case(
        (same_or_missing, func.coalesce(Product.brand_name, Product.generic_name, "")),
        else_=Product.brand_name + " (" + Product.generic_name + ")",
    )


def stock_columns(today: date) -> list[ColumnElement[Any] | InstrumentedAttribute[Any]]:
    """The columns of a StockLine, aggregated over a package's lots."""
    not_expired = InventoryLot.expiration_date >= today
    return [
        Package.package_ndc,
        Package.product_ndc,
        drug_name_column(),
        Package.description,
        func.coalesce(func.sum(InventoryLot.quantity).filter(not_expired), 0),
        func.coalesce(func.sum(InventoryLot.quantity).filter(~not_expired), 0),
        func.count(InventoryLot.id),
        func.min(InventoryLot.expiration_date).filter(not_expired, InventoryLot.quantity > 0),
        ReorderRule.reorder_threshold,
    ]


def expiring_query(today: date, days: int, include_expired: bool) -> Select[InventoryLot]:
    """Lots that still have stock and expire within ``days`` days.

    Written as a range on expiration_date plus ``quantity > 0`` so it matches
    the partial index ix_inventory_lots_expiring exactly.
    """
    conditions = [
        InventoryLot.quantity > 0,
        InventoryLot.expiration_date <= today + timedelta(days),
    ]
    if not include_expired:
        conditions.append(InventoryLot.expiration_date >= today)
    return (
        select(InventoryLot)
        .where(*conditions)
        .order_by(InventoryLot.expiration_date, InventoryLot.id)
    )


class InventoryService:
    def __init__(self, session: Session, today: date | None = None) -> None:
        self.session = session
        self.today = today or date.today()

    # ----- reads ----------------------------------------------------------

    def stock(
        self, limit: int, offset: int, package_ndc: str | None = None
    ) -> tuple[list[StockLine], int]:
        """Current stock per package, summing all of its lots."""
        stmt = (
            select(*stock_columns(self.today))
            .join(InventoryLot, InventoryLot.package_ndc == Package.package_ndc)
            .join(Product, Product.product_ndc == Package.product_ndc)
            .outerjoin(ReorderRule, ReorderRule.package_ndc == Package.package_ndc)
            .group_by(Package.package_ndc, Product.product_ndc, ReorderRule.reorder_threshold)
            .order_by(Package.package_ndc)
        )
        if package_ndc:
            stmt = stmt.where(Package.package_ndc == package_ndc)
        total = self.session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        rows = self.session.execute(stmt.limit(limit).offset(offset)).all()
        return [StockLine(*row) for row in rows], total

    def expiring(
        self, days: int, limit: int, offset: int, include_expired: bool = False
    ) -> tuple[Sequence[InventoryLot], int]:
        stmt = expiring_query(self.today, days, include_expired)
        total = self.session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        return self.session.scalars(stmt.limit(limit).offset(offset)).all(), total

    def low_stock(self, limit: int, offset: int) -> tuple[list[StockLine], int]:
        """Packages whose usable (not expired) stock is below their reorder threshold."""
        columns = stock_columns(self.today)
        usable = columns[4]
        stmt = (
            select(*columns)
            .select_from(ReorderRule)
            .join(Package, Package.package_ndc == ReorderRule.package_ndc)
            .join(Product, Product.product_ndc == Package.product_ndc)
            .outerjoin(InventoryLot, InventoryLot.package_ndc == ReorderRule.package_ndc)
            .group_by(Package.package_ndc, Product.product_ndc, ReorderRule.reorder_threshold)
            .having(usable < ReorderRule.reorder_threshold)
            .order_by(usable - ReorderRule.reorder_threshold, Package.package_ndc)
        )
        total = self.session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        rows = self.session.execute(stmt.limit(limit).offset(offset)).all()
        return [StockLine(*row) for row in rows], total

    # ----- writes ---------------------------------------------------------

    def receive_lot(
        self,
        package_ndc: str,
        lot_number: str,
        quantity: int,
        expiration_date: date,
        received_at: datetime | None = None,
    ) -> InventoryLot:
        if self.session.get(Package, package_ndc) is None:
            raise NotFoundError(f"No package with NDC {package_ndc}", package_ndc=package_ndc)
        if expiration_date < self.today:
            raise InvalidLotError(
                "Cannot receive a lot that has already expired",
                expiration_date=expiration_date.isoformat(),
            )
        lot = InventoryLot(
            package_ndc=package_ndc,
            lot_number=lot_number,
            quantity=quantity,
            expiration_date=expiration_date,
            received_at=received_at or datetime.now(UTC),
        )
        self.session.add(lot)
        try:
            self.session.commit()
        except IntegrityError:
            self.session.rollback()
            raise ConflictError(
                f"Lot {lot_number} already exists for package {package_ndc}",
                package_ndc=package_ndc,
                lot_number=lot_number,
            ) from None
        return lot

    def dispense(self, package_ndc: str, quantity: int, reference: str | None) -> DispenseResult:
        """Take ``quantity`` units using FEFO, in one transaction.

        1. Lock this package's lots (SELECT ... FOR UPDATE). A second dispense
           for the same package waits here until we commit, so two requests
           can never both take the same units.
        2. Ask the pure ``plan_fefo`` function which lots to use.
        3. Subtract from each lot and write a dispense record per lot.
        4. Commit. If any step fails, nothing is changed.
        """
        if self.session.get(Package, package_ndc) is None:
            raise NotFoundError(f"No package with NDC {package_ndc}", package_ndc=package_ndc)

        lots = self.session.scalars(
            select(InventoryLot)
            .where(InventoryLot.package_ndc == package_ndc, InventoryLot.quantity > 0)
            .order_by(InventoryLot.id)
            .with_for_update()
        ).all()
        stock = [
            LotStock(lot.id, lot.lot_number, lot.quantity, lot.expiration_date, lot.received_at)
            for lot in lots
        ]
        try:
            plan = plan_fefo(stock, quantity, self.today)
        except Exception:
            self.session.rollback()  # release the row locks before reporting the error
            raise

        now = datetime.now(UTC)
        for allocation in plan:
            self.session.execute(
                update(InventoryLot)
                .where(InventoryLot.id == allocation.lot_id)
                .values(quantity=InventoryLot.quantity - allocation.quantity)
            )
            self.session.add(
                DispenseRecord(
                    package_ndc=package_ndc,
                    lot_id=allocation.lot_id,
                    quantity=allocation.quantity,
                    reference=reference,
                    dispensed_at=now,
                )
            )
        self.session.commit()

        remaining = sum(s.quantity for s in stock if s.expiration_date >= self.today) - quantity
        return DispenseResult(package_ndc, quantity, plan, remaining)
