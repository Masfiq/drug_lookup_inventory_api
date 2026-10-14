"""Build tests/fixtures/ndc_sample.json: a small, real slice of the FDA file.

The tests and CI use this instead of the 245 MB download. The records are
picked on purpose so that every data quality check has at least one real
example to catch. One extra record with no product_ndc is added by hand
(marked "injected_for_tests"), because the real file has none.

Usage (after `python -m app.cli download`):
    python scripts/make_fixture.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "data" / "raw" / "drug-ndc-0001-of-0001.json"
TARGET = ROOT / "tests" / "fixtures" / "ndc_sample.json"

KEEP_FIELDS = [
    "product_ndc", "generic_name", "brand_name", "labeler_name", "dosage_form", "route",
    "marketing_category", "product_type", "finished", "marketing_start_date", "spl_id",
    "active_ingredients", "packaging",
]  # fmt: skip

# Each product NDC is here for a reason.
PICKS = {
    "58151-155": "Lipitor 10 mg (brand name search)",
    "0002-0800": "listed twice in the FDA file (duplicate_product_ndc)",
    "53209-2000": "has package NDC '02' (malformed_package_ndc)",
    "47848-026": "has package NDC '47848-026-XX' (malformed_package_ndc)",
    "0065-0419": "has no packages (product_without_packages)",
    "50241-014": "has no generic name (null_generic_name)",
    "71894-137": "has no active ingredients (product_without_ingredients)",
    "86211-114": "lists a route twice (duplicate_route)",
}
EXTRA_GENERICS = [
    "metformin hydrochloride",
    "ibuprofen",
    "insulin glargine",
    "atorvastatin calcium",
]
DUPLICATE_PACKAGE = "72603-474-25"  # appears under two records (duplicate_package_ndc)


def slim(record: dict[str, object]) -> dict[str, object]:
    return {key: record[key] for key in KEEP_FIELDS if key in record}


def main() -> None:
    if not SOURCE.exists():
        sys.exit(f"{SOURCE} not found. Run: python -m app.cli download")
    with SOURCE.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    results = payload["results"]

    chosen: list[dict[str, object]] = []
    for record in results:
        ndc = record.get("product_ndc")
        packages = [p.get("package_ndc") for p in record.get("packaging", [])]
        if ndc in PICKS or DUPLICATE_PACKAGE in packages:
            chosen.append(slim(record))
    for generic in EXTRA_GENERICS:
        matches = [
            r for r in results
            if str(r.get("generic_name", "")).lower() == generic and r.get("packaging")
            and r.get("finished")
        ]  # fmt: skip
        chosen += [slim(r) for r in matches[:2]]

    chosen.append(
        {
            "injected_for_tests": "no product_ndc (missing_product_ndc); the real file has none",
            "generic_name": "Test Record",
            "labeler_name": "Test",
            "packaging": [{"package_ndc": "99999-999-99", "description": "1 in 1 BOX"}],
        }
    )
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    meta = {"source": "openFDA NDC Directory", "last_updated": payload["meta"]["last_updated"]}
    TARGET.write_text(json.dumps({"meta": meta, "results": chosen}, indent=1), encoding="utf-8")
    print(f"Wrote {len(chosen)} records to {TARGET}")


if __name__ == "__main__":
    main()
