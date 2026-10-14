"""schema: reference tables, inventory tables, ETL bookkeeping

Revision ID: 0001
Revises:
Create Date: 2026-10-13

Only primary keys, foreign keys, unique constraints, and foreign key indexes
here. The performance indexes live in 0002 so they can be measured.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SEARCH_TEXT_SQL = "lower(coalesce(brand_name, '') || ' ' || coalesce(generic_name, ''))"


def upgrade() -> None:
    # pg_trgm gives us trigram similarity, used by fuzzy search.
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    op.create_table(
        "products",
        sa.Column("product_ndc", sa.String(20), nullable=False),
        sa.Column("generic_name", sa.Text(), nullable=True),
        sa.Column("brand_name", sa.Text(), nullable=True),
        sa.Column("labeler_name", sa.Text(), nullable=True),
        sa.Column("dosage_form", sa.Text(), nullable=True),
        sa.Column("marketing_category", sa.Text(), nullable=True),
        sa.Column("product_type", sa.Text(), nullable=True),
        sa.Column("search_text", sa.Text(), sa.Computed(SEARCH_TEXT_SQL, persisted=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("product_ndc", name=op.f("pk_products")),
    )
    op.create_table(
        "routes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_routes")),
        sa.UniqueConstraint("name", name=op.f("uq_routes_name")),
    )
    op.create_table(
        "packages",
        sa.Column("package_ndc", sa.String(20), nullable=False),
        sa.Column("product_ndc", sa.String(20), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["product_ndc"], ["products.product_ndc"], name=op.f("fk_packages_product_ndc_products")
        ),
        sa.PrimaryKeyConstraint("package_ndc", name=op.f("pk_packages")),
    )
    op.create_index(op.f("ix_packages_product_ndc"), "packages", ["product_ndc"])
    op.create_table(
        "active_ingredients",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("product_ndc", sa.String(20), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("strength", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["product_ndc"],
            ["products.product_ndc"],
            name=op.f("fk_active_ingredients_product_ndc_products"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_active_ingredients")),
    )
    op.create_index(
        op.f("ix_active_ingredients_product_ndc"), "active_ingredients", ["product_ndc"]
    )
    op.create_table(
        "product_routes",
        sa.Column("product_ndc", sa.String(20), nullable=False),
        sa.Column("route_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["product_ndc"],
            ["products.product_ndc"],
            name=op.f("fk_product_routes_product_ndc_products"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["route_id"], ["routes.id"], name=op.f("fk_product_routes_route_id_routes")
        ),
        sa.PrimaryKeyConstraint("product_ndc", "route_id", name=op.f("pk_product_routes")),
    )
    op.create_index(op.f("ix_product_routes_route_id"), "product_routes", ["route_id"])

    op.create_table(
        "inventory_lots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("package_ndc", sa.String(20), nullable=False),
        sa.Column("lot_number", sa.String(40), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("expiration_date", sa.Date(), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("quantity >= 0", name=op.f("ck_inventory_lots_non_negative_quantity")),
        sa.ForeignKeyConstraint(
            ["package_ndc"],
            ["packages.package_ndc"],
            name=op.f("fk_inventory_lots_package_ndc_packages"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_inventory_lots")),
        sa.UniqueConstraint("package_ndc", "lot_number", name="uq_inventory_lots_package_lot"),
    )
    op.create_table(
        "reorder_rules",
        sa.Column("package_ndc", sa.String(20), nullable=False),
        sa.Column("reorder_threshold", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "reorder_threshold >= 0", name=op.f("ck_reorder_rules_non_negative_threshold")
        ),
        sa.ForeignKeyConstraint(
            ["package_ndc"],
            ["packages.package_ndc"],
            name=op.f("fk_reorder_rules_package_ndc_packages"),
        ),
        sa.PrimaryKeyConstraint("package_ndc", name=op.f("pk_reorder_rules")),
    )
    op.create_table(
        "dispense_records",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("package_ndc", sa.String(20), nullable=False),
        sa.Column("lot_id", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("reference", sa.String(100), nullable=True),
        sa.Column("dispensed_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("quantity > 0", name=op.f("ck_dispense_records_positive_quantity")),
        sa.ForeignKeyConstraint(
            ["lot_id"],
            ["inventory_lots.id"],
            name=op.f("fk_dispense_records_lot_id_inventory_lots"),
        ),
        sa.ForeignKeyConstraint(
            ["package_ndc"],
            ["packages.package_ndc"],
            name=op.f("fk_dispense_records_package_ndc_packages"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_dispense_records")),
    )
    op.create_index(op.f("ix_dispense_records_lot_id"), "dispense_records", ["lot_id"])
    op.create_index(op.f("ix_dispense_records_package_ndc"), "dispense_records", ["package_ndc"])

    op.create_table(
        "etl_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("source_records", sa.Integer(), nullable=False),
        sa.Column("products_inserted", sa.Integer(), nullable=False),
        sa.Column("products_updated", sa.Integer(), nullable=False),
        sa.Column("products_unchanged", sa.Integer(), nullable=False),
        sa.Column("packages_inserted", sa.Integer(), nullable=False),
        sa.Column("packages_updated", sa.Integer(), nullable=False),
        sa.Column("packages_unchanged", sa.Integer(), nullable=False),
        sa.Column("issues_found", sa.Integer(), nullable=False),
        sa.Column("rows_dropped", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_etl_runs")),
    )


def downgrade() -> None:
    for table in (
        "etl_runs",
        "dispense_records",
        "reorder_rules",
        "inventory_lots",
        "product_routes",
        "active_ingredients",
        "packages",
        "routes",
        "products",
    ):
        op.drop_table(table)
