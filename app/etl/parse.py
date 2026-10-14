"""Step 2 of the ETL: turn nested FDA JSON into flat pandas tables.

Each FDA record is one product with lists inside it (packages, active
ingredients, routes). A relational database wants one row per thing, so we
"explode" each list into its own table that points back to the product.

Every row keeps ``source_row``, the position of the FDA record it came from,
so the validator can trace any problem back to the original record.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

PRODUCT_COLUMNS = [
    "product_ndc",
    "generic_name",
    "brand_name",
    "labeler_name",
    "dosage_form",
    "marketing_category",
    "product_type",
    "finished",
    "marketing_start_date",
    "spl_id",
]


@dataclass
class ParsedData:
    products: pd.DataFrame  # one row per FDA record
    packages: pd.DataFrame  # source_row, product_ndc, package_ndc, description
    ingredients: pd.DataFrame  # source_row, product_ndc, name, strength
    routes: pd.DataFrame  # source_row, product_ndc, route
    source_records: int
    source_last_updated: str | None = None


def read_records(path: Path) -> tuple[list[dict[str, Any]], str | None]:
    """Read the FDA JSON file. Returns the records and the FDA ``last_updated`` date."""
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    records: list[dict[str, Any]] = payload["results"]
    last_updated = payload.get("meta", {}).get("last_updated")
    return records, last_updated


def parse_records(records: list[dict[str, Any]], last_updated: str | None = None) -> ParsedData:
    frame = pd.DataFrame.from_records(records)
    for column in [*PRODUCT_COLUMNS, "packaging", "active_ingredients", "route"]:
        if column not in frame.columns:
            frame[column] = None  # a field missing from every record still gets a column
    frame["source_row"] = range(len(frame))

    products = frame[["source_row", *PRODUCT_COLUMNS]].copy()
    products = products.astype(object).where(products.notna(), None)

    packages = _explode_dicts(frame, "packaging", {"package_ndc": None, "description": None})
    ingredients = _explode_dicts(frame, "active_ingredients", {"name": None, "strength": None})

    routes = frame[["source_row", "product_ndc", "route"]].explode("route")
    routes = routes[routes["route"].notna()].reset_index(drop=True)

    return ParsedData(
        products=products.reset_index(drop=True),
        packages=packages,
        ingredients=ingredients,
        routes=routes,
        source_records=len(frame),
        source_last_updated=last_updated,
    )


def _explode_dicts(frame: pd.DataFrame, column: str, fields: dict[str, None]) -> pd.DataFrame:
    """One output row per item in a list-of-dicts column, keeping only ``fields``."""
    exploded = frame[["source_row", "product_ndc", column]].explode(column)
    exploded = exploded[exploded[column].notna()].reset_index(drop=True)
    items = pd.DataFrame.from_records(
        [{key: item.get(key) for key in fields} for item in exploded[column]],
        columns=list(fields),
    )
    result = pd.concat([exploded[["source_row", "product_ndc"]], items], axis=1)
    return result.astype(object).where(result.notna(), None)
