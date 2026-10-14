"""Step 3 of the ETL: data quality checks.

Real data is messy. Every check below counts how many rows have the problem,
keeps a few examples, and says what we did about it:

* "dropped": the row cannot be stored safely (for example, it has no key).
* "kept": the row is usable, so we keep it but report it.

Nothing is ever removed without being counted here, and the counts end up in
``reports/data_quality_report.md``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

import pandas as pd

from app.domain.ndc import is_valid_package_ndc, is_valid_product_ndc, package_belongs_to_product
from app.etl.parse import ParsedData

MAX_EXAMPLES = 5


@dataclass
class Issue:
    code: str
    description: str
    action: str  # "dropped" or "kept"
    count: int
    examples: list[str] = field(default_factory=list)


@dataclass
class ValidationResult:
    products: pd.DataFrame
    packages: pd.DataFrame
    ingredients: pd.DataFrame
    routes: pd.DataFrame
    issues: list[Issue]
    source_records: int
    source_last_updated: str | None = None

    @property
    def issues_found(self) -> int:
        return sum(issue.count for issue in self.issues)

    @property
    def rows_dropped(self) -> int:
        return sum(issue.count for issue in self.issues if issue.action == "dropped")

    def issue(self, code: str) -> Issue:
        return next(i for i in self.issues if i.code == code)


def _issue(
    code: str,
    description: str,
    action: str,
    rows: pd.DataFrame,
    describe: Callable[[pd.Series], str],
    count: int | None = None,
) -> Issue:
    """``count`` defaults to ``len(rows)``; pass it when examples are a summary of the rows."""
    examples = [describe(row) for _, row in rows.head(MAX_EXAMPLES).iterrows()]
    return Issue(code, description, action, len(rows) if count is None else count, examples)


def _clean_text(series: pd.Series) -> pd.Series:
    """Strip spaces; empty strings become None."""
    cleaned = series.map(lambda v: v.strip() if isinstance(v, str) else v)
    return cleaned.map(lambda v: None if v == "" else v)


def validate(parsed: ParsedData) -> ValidationResult:
    issues: list[Issue] = []
    products = parsed.products.copy()
    packages = parsed.packages.copy()
    ingredients = parsed.ingredients.copy()
    routes = parsed.routes.copy()

    for frame, columns in (
        (products, ["product_ndc", "generic_name", "brand_name", "labeler_name", "dosage_form"]),
        (packages, ["product_ndc", "package_ndc", "description"]),
        (ingredients, ["name", "strength"]),
        (routes, ["route"]),
    ):
        for column in columns:
            frame[column] = _clean_text(frame[column])

    # 1. Missing product NDC: the product has no key, so it cannot be stored.
    missing = products["product_ndc"].isna()
    issues.append(
        _issue(
            "missing_product_ndc",
            "Product record has no product_ndc (the record and its packages, ingredients, "
            "and routes were not loaded)",
            "dropped",
            products[missing],
            lambda r: f"source record #{r.source_row}",
        )
    )
    products = products[~missing]

    # 2. Malformed product NDC: not 4-4, 5-3, or 5-4 digits. Still a unique key, so kept.
    malformed = ~products["product_ndc"].map(is_valid_product_ndc)
    issues.append(
        _issue(
            "malformed_product_ndc",
            "product_ndc is not in 4-4, 5-3, or 5-4 digit format",
            "kept",
            products[malformed],
            lambda r: str(r.product_ndc),
        )
    )

    # 3. Duplicate product NDC: FDA lists some products more than once (separate
    #    label documents). Keep one listing: finished products first, then the
    #    most recent marketing start date. Packages from every listing are merged.
    ranked = products.assign(
        _finished=products["finished"].map(lambda v: v is True),
        _start=products["marketing_start_date"].map(lambda v: str(v or "")),
        _spl=products["spl_id"].map(lambda v: str(v or "")),
    ).sort_values(
        ["product_ndc", "_finished", "_start", "_spl"], ascending=[True, False, False, True]
    )
    duplicate = ranked.duplicated("product_ndc", keep="first")
    listing_counts = ranked["product_ndc"].value_counts()
    issues.append(
        _issue(
            "duplicate_product_ndc",
            "Extra listings of a product_ndc that appears more than once "
            "(kept the finished, most recently started listing and its ingredients and routes; "
            "packages from all listings were merged)",
            "dropped",
            ranked[duplicate].drop_duplicates("product_ndc"),
            lambda r: f"{r.product_ndc} ({listing_counts[r.product_ndc]} listings)",
            count=int(duplicate.sum()),
        )
    )
    products = ranked[~duplicate].drop(columns=["_finished", "_start", "_spl"])
    products = products.sort_values("source_row").reset_index(drop=True)
    kept_rows = set(products["source_row"])
    kept_ndcs = set(products["product_ndc"])

    ingredients = ingredients[ingredients["source_row"].isin(kept_rows)]
    routes = routes[routes["source_row"].isin(kept_rows)]
    packages = packages[packages["product_ndc"].isin(kept_ndcs)]
    # Put the kept listing's packages first so its description wins on duplicates.
    packages = packages.assign(_kept=packages["source_row"].isin(kept_rows)).sort_values(
        ["_kept", "source_row"], ascending=[False, True]
    )

    # 4. Null generic name: allowed (brand name may still identify it), but reported.
    issues.append(
        _issue(
            "null_generic_name",
            "Product has no generic_name",
            "kept",
            products[products["generic_name"].isna()],
            lambda r: f"{r.product_ndc} (brand: {r.brand_name})",
        )
    )

    # 5. Missing package NDC.
    no_pkg_ndc = packages["package_ndc"].isna()
    issues.append(
        _issue(
            "missing_package_ndc",
            "Package has no package_ndc",
            "dropped",
            packages[no_pkg_ndc],
            lambda r: f"package of {r.product_ndc}",
        )
    )
    packages = packages[~no_pkg_ndc]

    # 6. Malformed package NDC: cannot identify a real package, so dropped.
    bad_pkg = ~packages["package_ndc"].map(is_valid_package_ndc)
    issues.append(
        _issue(
            "malformed_package_ndc",
            "package_ndc is not in 4-4-2, 5-3-2, or 5-4-1 digit format",
            "dropped",
            packages[bad_pkg],
            lambda r: f"'{r.package_ndc}' (product {r.product_ndc}: {r.description})",
        )
    )
    packages = packages[~bad_pkg]

    # 7. Duplicate package NDC: keep the first one.
    dup_pkg = packages.duplicated("package_ndc", keep="first")
    issues.append(
        _issue(
            "duplicate_package_ndc",
            "package_ndc appears more than once (kept the first)",
            "dropped",
            packages[dup_pkg],
            lambda r: str(r.package_ndc),
        )
    )
    packages = packages[~dup_pkg].drop(columns=["_kept"]).sort_values("package_ndc")
    packages = packages.reset_index(drop=True)

    # 8. Package NDC that does not start with its product NDC.
    mismatch = ~packages.apply(
        lambda r: package_belongs_to_product(r.package_ndc, r.product_ndc), axis=1
    ).astype(bool)
    issues.append(
        _issue(
            "package_product_mismatch",
            "package_ndc does not start with its product_ndc",
            "kept",
            packages[mismatch],
            lambda r: f"{r.package_ndc} under product {r.product_ndc}",
        )
    )

    # 9. Products with no packages: nothing to stock, but still useful for lookup.
    no_packages = ~products["product_ndc"].isin(set(packages["product_ndc"]))
    issues.append(
        _issue(
            "product_without_packages",
            "Product has no packages",
            "kept",
            products[no_packages],
            lambda r: f"{r.product_ndc} ({r.generic_name})",
        )
    )

    # 10. Ingredient without a name.
    no_name = ingredients["name"].isna()
    issues.append(
        _issue(
            "ingredient_without_name",
            "Active ingredient has no name",
            "dropped",
            ingredients[no_name],
            lambda r: f"ingredient of {r.product_ndc}",
        )
    )
    ingredients = ingredients[~no_name].reset_index(drop=True)

    # 11. Products with no active ingredients (common for bulk and allergenic items).
    no_ingredients = ~products["product_ndc"].isin(set(ingredients["product_ndc"]))
    issues.append(
        _issue(
            "product_without_ingredients",
            "Product lists no active ingredients",
            "kept",
            products[no_ingredients],
            lambda r: f"{r.product_ndc} ({r.generic_name}, {r.product_type})",
        )
    )

    # 12. Same route listed twice for one product.
    dup_route = routes.duplicated(["product_ndc", "route"], keep="first")
    issues.append(
        _issue(
            "duplicate_route",
            "Route listed twice for the same product",
            "dropped",
            routes[dup_route],
            lambda r: f"{r.product_ndc}: {r.route}",
        )
    )
    routes = routes[~dup_route].reset_index(drop=True)

    return ValidationResult(
        products=products,
        packages=packages,
        ingredients=ingredients,
        routes=routes,
        issues=issues,
        source_records=parsed.source_records,
        source_last_updated=parsed.source_last_updated,
    )
