"""SQLAlchemy models.

Reference data (real, from the FDA NDC Directory):
    products, packages, active_ingredients, routes, product_routes

Inventory data (synthetic, for practice):
    inventory_lots, reorder_rules, dispense_records

Bookkeeping:
    etl_runs (one row per data load, including what changed)

Performance indexes (trigram and B-tree) are added in the second migration so
their effect can be measured before and after. See docs/PERFORMANCE.md.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import (
    CheckConstraint,
    Computed,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

# Lowercased "brand generic" text that fuzzy search runs against.
SEARCH_TEXT_SQL = "lower(coalesce(brand_name, '') || ' ' || coalesce(generic_name, ''))"


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


# ----- reference data (real FDA data) ---------------------------------------


class Product(Base):
    """One drug product, for example "Lipitor 20 mg tablet" made by one labeler."""

    __tablename__ = "products"
    __table_args__ = (
        Index(
            "ix_products_search_text_trgm",
            "search_text",
            postgresql_using="gin",
            postgresql_ops={"search_text": "gin_trgm_ops"},
        ),
    )

    product_ndc: Mapped[str] = mapped_column(String(20), primary_key=True)
    generic_name: Mapped[str | None] = mapped_column(Text)
    brand_name: Mapped[str | None] = mapped_column(Text)
    labeler_name: Mapped[str | None] = mapped_column(Text)
    dosage_form: Mapped[str | None] = mapped_column(Text)
    marketing_category: Mapped[str | None] = mapped_column(Text)
    product_type: Mapped[str | None] = mapped_column(Text)
    search_text: Mapped[str] = mapped_column(Text, Computed(SEARCH_TEXT_SQL, persisted=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    packages: Mapped[list[Package]] = relationship(
        back_populates="product", order_by="Package.package_ndc"
    )
    ingredients: Mapped[list[ActiveIngredient]] = relationship(
        back_populates="product", order_by="ActiveIngredient.id"
    )
    routes: Mapped[list[Route]] = relationship(secondary="product_routes", order_by="Route.name")


class Package(Base):
    """A sellable package of a product, for example "90 tablets in 1 bottle"."""

    __tablename__ = "packages"

    package_ndc: Mapped[str] = mapped_column(String(20), primary_key=True)
    product_ndc: Mapped[str] = mapped_column(ForeignKey("products.product_ndc"), index=True)
    description: Mapped[str | None] = mapped_column(Text)

    product: Mapped[Product] = relationship(back_populates="packages")


class ActiveIngredient(Base):
    __tablename__ = "active_ingredients"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_ndc: Mapped[str] = mapped_column(
        ForeignKey("products.product_ndc", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(Text)
    strength: Mapped[str | None] = mapped_column(Text)

    product: Mapped[Product] = relationship(back_populates="ingredients")


# Expression index for ingredient prefix search, LIKE 'metformin%' on lower(name).
# Declared after the class because it refers to the mapped column.
Index(
    "ix_active_ingredients_name_prefix",
    func.lower(ActiveIngredient.name).label("name_lower"),
    postgresql_ops={"name_lower": "text_pattern_ops"},
)


class Route(Base):
    """A route of administration such as ORAL. Each name is stored once."""

    __tablename__ = "routes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)


class ProductRoute(Base):
    """Link table: a product has many routes and a route belongs to many products."""

    __tablename__ = "product_routes"

    product_ndc: Mapped[str] = mapped_column(
        ForeignKey("products.product_ndc", ondelete="CASCADE"), primary_key=True
    )
    route_id: Mapped[int] = mapped_column(ForeignKey("routes.id"), primary_key=True, index=True)


# ----- inventory (synthetic) ------------------------------------------------


class InventoryLot(Base):
    """A batch of one package received from a supplier. Lots expire on a date."""

    __tablename__ = "inventory_lots"
    __table_args__ = (
        CheckConstraint("quantity >= 0", name="non_negative_quantity"),
        UniqueConstraint("package_ndc", "lot_number", name="uq_inventory_lots_package_lot"),
        Index(
            "ix_inventory_lots_expiring", "expiration_date", postgresql_where=text("quantity > 0")
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    package_ndc: Mapped[str] = mapped_column(ForeignKey("packages.package_ndc"))
    lot_number: Mapped[str] = mapped_column(String(40))
    quantity: Mapped[int] = mapped_column(Integer)
    expiration_date: Mapped[date] = mapped_column(Date)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    package: Mapped[Package] = relationship()


class ReorderRule(Base):
    __tablename__ = "reorder_rules"
    __table_args__ = (CheckConstraint("reorder_threshold >= 0", name="non_negative_threshold"),)

    package_ndc: Mapped[str] = mapped_column(ForeignKey("packages.package_ndc"), primary_key=True)
    reorder_threshold: Mapped[int] = mapped_column(Integer)


class DispenseRecord(Base):
    """Which lot each dispensed unit came from. Needed to trace patients in a recall."""

    __tablename__ = "dispense_records"
    __table_args__ = (CheckConstraint("quantity > 0", name="positive_quantity"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    package_ndc: Mapped[str] = mapped_column(ForeignKey("packages.package_ndc"), index=True)
    lot_id: Mapped[int] = mapped_column(ForeignKey("inventory_lots.id"), index=True)
    quantity: Mapped[int] = mapped_column(Integer)
    reference: Mapped[str | None] = mapped_column(String(100))
    dispensed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# ----- bookkeeping ----------------------------------------------------------


class EtlRun(Base):
    """One data load: when it ran and what changed compared to the previous load."""

    __tablename__ = "etl_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    source: Mapped[str] = mapped_column(Text)
    source_records: Mapped[int] = mapped_column(Integer)
    products_inserted: Mapped[int] = mapped_column(Integer)
    products_updated: Mapped[int] = mapped_column(Integer)
    products_unchanged: Mapped[int] = mapped_column(Integer)
    packages_inserted: Mapped[int] = mapped_column(Integer)
    packages_updated: Mapped[int] = mapped_column(Integer)
    packages_unchanged: Mapped[int] = mapped_column(Integer)
    issues_found: Mapped[int] = mapped_column(Integer)
    rows_dropped: Mapped[int] = mapped_column(Integer)
