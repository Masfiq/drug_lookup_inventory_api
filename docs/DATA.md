# The data

## Source

- **What:** the FDA National Drug Code (NDC) Directory, published through openFDA.
- **Download:** `https://download.open.fda.gov/drug/ndc/drug-ndc-0001-of-0001.json.zip`
  (28 MB zip, 245 MB of JSON). `python -m app.cli download` saves it to `data/raw/`, which is in
  `.gitignore`, so the raw file is never committed.
- **Docs:** https://open.fda.gov/apis/drug/ndc/
- **License:** public domain U.S. government data (see https://open.fda.gov/license/). openFDA's
  own disclaimer: do not rely on it for medical decisions.
- **Version used for the numbers in this repo:** `last_updated` 2026-10-13, 138,427 records.

## Fields we use

These field names were confirmed against the downloaded file before writing the parser
(every record has `product_ndc`, `labeler_name`, `packaging`, `dosage_form`,
`marketing_category`, and `product_type`; the others can be missing).

| FDA field | Present in | Goes to |
| --- | ---: | --- |
| `product_ndc` | 138,427 | `products.product_ndc` |
| `generic_name` | 138,424 | `products.generic_name` |
| `brand_name` | 116,688 | `products.brand_name` |
| `labeler_name` | 138,427 | `products.labeler_name` |
| `dosage_form` | 138,427 | `products.dosage_form` |
| `marketing_category` | 138,427 | `products.marketing_category` |
| `product_type` | 138,427 | `products.product_type` |
| `route` (list of strings) | 114,803 | `routes` + `product_routes` |
| `active_ingredients` (list of `{name, strength}`) | 135,894 | `active_ingredients` |
| `packaging` (list of `{package_ndc, description, ...}`) | 138,427 | `packages` |
| `finished`, `marketing_start_date`, `spl_id` | 138,427 | only used to pick between duplicate listings |

Fields such as `openfda`, `pharm_class`, `dea_schedule`, and `application_number` are not loaded
yet; see "What could come next" in the README.

## NDC formats

An NDC has three parts: labeler, product, package. FDA allows three 10 digit layouts:

| Layout | Product NDC | Package NDC (real example) |
| --- | --- | --- |
| 4-4-2 | `0002-0095` | `0002-0095-00` |
| 5-3-2 | `64980-443` | `64980-443-01` |
| 5-4-1 | `50090-7387` | `50090-7387-0` |

Rules are in `app/domain/ndc.py`.

## Quality checks

Each check counts rows, keeps up to 5 examples, and states its action. The latest counts are in
[`reports/data_quality_report.md`](../reports/data_quality_report.md).

| Code | Action | Rule | Count (2026-10-13 file) |
| --- | --- | --- | ---: |
| `missing_product_ndc` | dropped | No product NDC means no key. The record and its packages, ingredients, and routes are not loaded. | 0 |
| `malformed_product_ndc` | kept | Not 4-4, 5-3, or 5-4 digits. Still a unique key, so it is loaded and reported. | 0 |
| `duplicate_product_ndc` | dropped | Same product NDC in several listings. Keep the finished, most recently started one; merge packages from all. Counts the extra listings. | 2,450 |
| `null_generic_name` | kept | No generic name; the brand name still identifies it. | 3 |
| `missing_package_ndc` | dropped | A package with no NDC cannot be stocked. | 0 |
| `malformed_package_ndc` | dropped | Not 4-4-2, 5-3-2, or 5-4-1 digits. Real examples: `02`, `47848-026-XX`. | 2 |
| `duplicate_package_ndc` | dropped | Same package NDC twice; keep the first. | 4 |
| `package_product_mismatch` | kept | Package NDC does not start with its product NDC. | 0 |
| `product_without_packages` | kept | Nothing to stock, but still useful for lookup. | 364 |
| `ingredient_without_name` | dropped | An ingredient row with no name carries no information. | 0 |
| `product_without_ingredients` | kept | Common for bulk ingredients and some biologics. | 2,516 |
| `duplicate_route` | dropped | Same route listed twice for one product. | 27 |

Totals for that file: 5,366 issues, 2,483 rows dropped. Loaded: 135,977 products, 256,975
packages, 219,498 active ingredients, 121,231 product route links, 72 distinct routes.

## Synthetic inventory

Real pharmacy stock levels are private, so the stockroom is made up by
`app/etl/seed_inventory.py` (seeded random numbers plus Faker, so it is repeatable):

- 20,000 packages are sampled from products of type `HUMAN PRESCRIPTION DRUG` or
  `HUMAN OTC DRUG`.
- Each gets 1 to 4 lots with a Faker lot number like `FZ46096`, a quantity from 5 to 400, an
  expiration date between 45 days ago and 2 years ahead (so some lots are expired or expiring),
  and a received date in the past.
- Each gets a reorder threshold from 50 to 300.
- The default run created 50,163 lots across 20,000 packages.

Running it again replaces all inventory, including dispense records.

## Test fixture

`tests/fixtures/ndc_sample.json` holds 20 real records picked by `scripts/make_fixture.py`, each
for a reason (written next to it in the script), plus one injected record with no product NDC,
marked `injected_for_tests`. Regenerate it with `python scripts/make_fixture.py` after a download.
