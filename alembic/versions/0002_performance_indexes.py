"""performance indexes for search, ingredient lookup, and expiring lots

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-13

Kept in its own migration so the benchmark (python -m app.cli benchmark) can
measure the three key queries with and without these indexes. See
docs/PERFORMANCE.md for the measured timings.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Fuzzy name search. A GIN index of trigrams (3 letter chunks) lets
    #    PostgreSQL find similar names without comparing against every row.
    op.execute(
        "CREATE INDEX ix_products_search_text_trgm ON products USING gin (search_text gin_trgm_ops)"
    )
    # 2. Ingredient lookup by name prefix ("metformin" matches
    #    "METFORMIN HYDROCHLORIDE"). text_pattern_ops makes LIKE 'abc%' use the
    #    B-tree no matter which collation the database uses.
    op.execute(
        "CREATE INDEX ix_active_ingredients_name_prefix "
        "ON active_ingredients (lower(name) text_pattern_ops)"
    )
    # 3. Expiring lots. A partial B-tree index: only lots that still have stock
    #    are indexed, because empty lots never need an expiry alert.
    op.execute(
        "CREATE INDEX ix_inventory_lots_expiring "
        "ON inventory_lots (expiration_date) WHERE quantity > 0"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_inventory_lots_expiring")
    op.execute("DROP INDEX IF EXISTS ix_active_ingredients_name_prefix")
    op.execute("DROP INDEX IF EXISTS ix_products_search_text_trgm")
