"""Parser and data quality checks, run on a small slice of real FDA records."""

from pathlib import Path

import pytest

from app.etl.parse import parse_records, read_records
from app.etl.report import render
from app.etl.validate import ValidationResult, validate

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "ndc_sample.json"


@pytest.fixture(scope="module")
def result() -> ValidationResult:
    records, last_updated = read_records(FIXTURE)
    return validate(parse_records(records, last_updated))


def test_parse_flattens_nested_lists() -> None:
    records, _ = read_records(FIXTURE)
    parsed = parse_records(records)
    assert parsed.source_records == len(records) == 21
    assert len(parsed.products) == 21
    assert {"source_row", "product_ndc", "package_ndc", "description"} <= set(parsed.packages)
    assert {"source_row", "product_ndc", "name", "strength"} <= set(parsed.ingredients)
    assert set(parsed.routes.columns) == {"source_row", "product_ndc", "route"}


def test_parse_handles_missing_fields() -> None:
    parsed = parse_records([{"product_ndc": "0002-0095"}])
    assert len(parsed.products) == 1
    assert parsed.products.loc[0, "generic_name"] is None
    assert parsed.packages.empty and parsed.ingredients.empty and parsed.routes.empty


EXPECTED_COUNTS = {
    "missing_product_ndc": 1,  # the one injected test record
    "malformed_product_ndc": 0,
    "duplicate_product_ndc": 3,  # 0002-0800 listed twice, 47848-026 three times
    "null_generic_name": 1,  # 50241-014 MG DermaClean
    "missing_package_ndc": 0,
    "malformed_package_ndc": 2,  # '02' and '47848-026-XX'
    "duplicate_package_ndc": 1,  # 72603-474-25 listed twice
    "package_product_mismatch": 0,
    "product_without_packages": 2,  # 0065-0419, and 53209-2000 once '02' is dropped
    "ingredient_without_name": 0,
    "product_without_ingredients": 1,  # 71894-137 Zolgensma
    "duplicate_route": 1,  # 86211-114 lists INTRAVENOUS twice
}


def test_every_check_counts_the_real_problems(result: ValidationResult) -> None:
    assert {issue.code: issue.count for issue in result.issues} == EXPECTED_COUNTS


def test_dropped_rows_are_counted(result: ValidationResult) -> None:
    dropped = sum(
        c for code, c in EXPECTED_COUNTS.items() if result.issue(code).action == "dropped"
    )
    assert result.rows_dropped == dropped == 8
    assert result.issues_found == sum(EXPECTED_COUNTS.values())


def test_clean_tables_have_unique_keys(result: ValidationResult) -> None:
    assert result.products["product_ndc"].is_unique
    assert result.packages["package_ndc"].is_unique
    assert not result.routes.duplicated(["product_ndc", "route"]).any()
    assert result.products["product_ndc"].notna().all()
    assert len(result.products) == 17


def test_duplicate_listing_prefers_finished_and_merges_packages(result: ValidationResult) -> None:
    kept = result.products.set_index("product_ndc").loc["0002-0800"]
    assert kept["brand_name"] == "Sterile Diluent"  # the finished listing wins
    packages = set(
        result.packages.loc[result.packages["product_ndc"] == "0002-0800", "package_ndc"]
    )
    assert packages == {"0002-0800-00", "0002-0800-01"}  # packages from both listings
    pemetrexed = set(
        result.packages.loc[result.packages["product_ndc"] == "47848-026", "package_ndc"]
    )
    assert pemetrexed == {"47848-026-00", "47848-026-01"}  # the XX package was dropped


def test_examples_point_at_real_records(result: ValidationResult) -> None:
    assert result.issue("malformed_package_ndc").examples[0].startswith("'02'")
    assert "72603-474-25" in result.issue("duplicate_package_ndc").examples
    assert result.issue("missing_product_ndc").action == "dropped"
    assert result.issue("null_generic_name").action == "kept"


def test_report_lists_every_check(result: ValidationResult) -> None:
    text = render(result, None, "ndc_sample.json")
    for code in EXPECTED_COUNTS:
        assert f"`{code}`" in text
    assert "Records in source file: 21" in text
    assert "What changed" not in text  # no load stats given
