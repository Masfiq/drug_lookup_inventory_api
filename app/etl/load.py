"""Step 4 of the ETL: load the clean tables into PostgreSQL.

Safe to run twice (idempotent):
* products and packages use INSERT ... ON CONFLICT DO UPDATE ("upsert"), so a
  second run updates rows instead of failing on duplicate keys;
* the update only fires when a value actually changed (IS DISTINCT FROM), which
  lets us count inserted, updated, and unchanged rows: a free "what changed"
  report every time the FDA data is refreshed;
* ingredients and routes for the loaded products are deleted and re-inserted.

Everything happens in ONE transaction, sent in batches of ``BATCH_SIZE`` rows.
If anything fails, PostgreSQL rolls the whole load back, so the API never sees
a half-loaded database. Products that disappear from the FDA file are not
deleted (pharmacy inventory may still point at their packages); they are
counted as ``products_not_in_source``.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, TypeVar, cast

import pandas as pd
from sqlalchemy import (
    Connection,
    Engine,
    Table,
    delete,
    func,
    insert,
    literal_column,
    select,
    tuple_,
)
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db.models import (
    ActiveIngredient,
    Base,
    EtlRun,
    Package,
    Product,
    ProductRoute,
    Route,
)
from app.etl.validate import ValidationResult

BATCH_SIZE = 5000
T = TypeVar("T")

PRODUCT_FIELDS = [
    "generic_name",
    "brand_name",
    "labeler_name",
    "dosage_form",
    "marketing_category",
    "product_type",
]
PACKAGE_FIELDS = ["product_ndc", "description"]


@dataclass
class TableChanges:
    inserted: int = 0
    updated: int = 0
    unchanged: int = 0


@dataclass
class LoadStats:
    products: TableChanges = field(default_factory=TableChanges)
    packages: TableChanges = field(default_factory=TableChanges)
    ingredients: int = 0
    product_routes: int = 0
    route_names: int = 0
    products_not_in_source: int = 0
    seconds: float = 0.0


def batches(rows: Sequence[T], size: int = BATCH_SIZE) -> Iterator[list[T]]:
    for start in range(0, len(rows), size):
        yield list(rows[start : start + size])


def records(frame: pd.DataFrame, columns: list[str]) -> list[dict[str, Any]]:
    """DataFrame rows as plain dicts, ready to pass to an INSERT."""
    return [{str(k): v for k, v in row.items()} for row in frame[columns].to_dict("records")]


def _upsert(
    conn: Connection, model: type[Base], key: str, fields: list[str], rows: list[dict[str, Any]]
) -> TableChanges:
    """Insert new rows, update changed rows, leave identical rows alone. Counts each."""
    table = cast(Table, model.__table__)
    changes = TableChanges()
    for batch in batches(rows):
        insert_stmt = pg_insert(table)
        set_: dict[str, Any] = {name: insert_stmt.excluded[name] for name in fields}
        if "updated_at" in table.c:
            set_["updated_at"] = func.now()
        upsert = insert_stmt.on_conflict_do_update(
            index_elements=[key],
            set_=set_,
            where=tuple_(*[table.c[name] for name in fields]).is_distinct_from(
                tuple_(*[insert_stmt.excluded[name] for name in fields])
            ),
        ).returning(table.c[key], literal_column("(xmax = 0)").label("inserted"))
        returned = conn.execute(upsert, batch).all()
        inserted = sum(1 for row in returned if row.inserted)
        changes.inserted += inserted
        changes.updated += len(returned) - inserted
        changes.unchanged += len(batch) - len(returned)  # WHERE was false: nothing changed
    return changes


def load(engine: Engine, result: ValidationResult, source: str = "") -> LoadStats:
    started = datetime.now(UTC)
    stats = LoadStats()
    products = records(result.products, ["product_ndc", *PRODUCT_FIELDS])
    packages = records(result.packages, ["package_ndc", *PACKAGE_FIELDS])
    ingredients = records(result.ingredients, ["product_ndc", "name", "strength"])
    loaded_ndcs = [str(row["product_ndc"]) for row in products]

    with engine.begin() as conn:  # one transaction: all or nothing
        existing = set(conn.scalars(select(Product.product_ndc)))
        stats.products_not_in_source = len(existing - set(loaded_ndcs))

        stats.products = _upsert(conn, Product, "product_ndc", PRODUCT_FIELDS, products)
        stats.packages = _upsert(conn, Package, "package_ndc", PACKAGE_FIELDS, packages)

        # Child rows: replace them for every product in this file.
        for ndcs in batches(loaded_ndcs):
            conn.execute(delete(ActiveIngredient).where(ActiveIngredient.product_ndc.in_(ndcs)))
            conn.execute(delete(ProductRoute).where(ProductRoute.product_ndc.in_(ndcs)))
        for batch in batches(ingredients):
            conn.execute(insert(ActiveIngredient), batch)
        stats.ingredients = len(ingredients)

        route_names = sorted({str(name) for name in result.routes["route"]})
        if route_names:
            conn.execute(
                pg_insert(Route).on_conflict_do_nothing(index_elements=["name"]),
                [{"name": name} for name in route_names],
            )
        route_ids = {name: id_ for name, id_ in conn.execute(select(Route.name, Route.id))}
        stats.route_names = len(route_names)
        links: list[dict[str, Any]] = [
            {"product_ndc": ndc, "route_id": route_ids[str(route)]}
            for ndc, route in zip(result.routes["product_ndc"], result.routes["route"], strict=True)
        ]
        for batch in batches(links):
            conn.execute(insert(ProductRoute), batch)
        stats.product_routes = len(links)

        finished = datetime.now(UTC)
        stats.seconds = round((finished - started).total_seconds(), 1)
        conn.execute(
            insert(EtlRun),
            {
                "started_at": started,
                "finished_at": finished,
                "source": source,
                "source_records": result.source_records,
                "products_inserted": stats.products.inserted,
                "products_updated": stats.products.updated,
                "products_unchanged": stats.products.unchanged,
                "packages_inserted": stats.packages.inserted,
                "packages_updated": stats.packages.updated,
                "packages_unchanged": stats.packages.unchanged,
                "issues_found": result.issues_found,
                "rows_dropped": result.rows_dropped,
            },
        )
    return stats
