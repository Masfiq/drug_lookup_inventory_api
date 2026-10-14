# Data quality report

Generated automatically by `python -m app.cli load`. Do not edit by hand.

- Generated: 2026-10-14 02:24 UTC
- Source: `drug-ndc-0001-of-0001.json`
- FDA data last updated: 2026-10-13
- Records in source file: 138,427

## Rows after cleaning

| Table | Rows |
| --- | ---: |
| products | 135,977 |
| packages | 256,975 |
| active_ingredients | 219,498 |
| product_routes | 121,231 |
| distinct routes | 72 |

## Checks

"dropped" means the rows were not loaded. "kept" means they were loaded and are only reported.

| Check | Count | Action | What it means |
| --- | ---: | --- | --- |
| `missing_product_ndc` | 0 | dropped | Product record has no product_ndc (the record and its packages, ingredients, and routes were not loaded) |
| `malformed_product_ndc` | 0 | kept | product_ndc is not in 4-4, 5-3, or 5-4 digit format |
| `duplicate_product_ndc` | 2,450 | dropped | Extra listings of a product_ndc that appears more than once (kept the finished, most recently started listing and its ingredients and routes; packages from all listings were merged) |
| `null_generic_name` | 3 | kept | Product has no generic_name |
| `missing_package_ndc` | 0 | dropped | Package has no package_ndc |
| `malformed_package_ndc` | 2 | dropped | package_ndc is not in 4-4-2, 5-3-2, or 5-4-1 digit format |
| `duplicate_package_ndc` | 4 | dropped | package_ndc appears more than once (kept the first) |
| `package_product_mismatch` | 0 | kept | package_ndc does not start with its product_ndc |
| `product_without_packages` | 364 | kept | Product has no packages |
| `ingredient_without_name` | 0 | dropped | Active ingredient has no name |
| `product_without_ingredients` | 2,516 | kept | Product lists no active ingredients |
| `duplicate_route` | 27 | dropped | Route listed twice for the same product |

Total issues found: 5,366. Rows dropped: 2,483.

## Examples

**`duplicate_product_ndc`** (2,450): 0002-0800 (2 listings); 0002-1436 (2 listings); 0002-2377 (2 listings); 0002-3115 (2 listings); 0009-0039 (2 listings)

**`null_generic_name`** (3): 50241-014 (brand: MG DermaClean); 50241-259 (brand: MG DermaSan); 77617-001 (brand: Healthy Hands Foaming Hand Sanitizer)

**`malformed_package_ndc`** (2): '02' (product 53209-2000: 50 mg in 1 BOX (02)); '47848-026-XX' (product 47848-026: 1 kg in 1 CARTON (47848-026-XX))

**`duplicate_package_ndc`** (4): 72603-474-25; 72043-2500-1; 72603-133-25; 72603-251-25

**`product_without_packages`** (364): 0065-0419 (Dextran, Hypromellose); 72526-104 (Risperidone); 73352-610 (Lidocaine Hydrochloride); 0574-0791 (methazolamide); 81583-105 (pegzilarginase-nbln)

**`product_without_ingredients`** (2,516): 71894-137 (onasemnogene abeparvovec-xioi, HUMAN PRESCRIPTION DRUG); 71894-154 (onasemnogene abeparvovec-xioi, HUMAN PRESCRIPTION DRUG); 71894-155 (onasemnogene abeparvovec-xioi, HUMAN PRESCRIPTION DRUG); 72288-002 (acetaminophen, dextromethorphan hydrobromide, guaifenesin, phenylephrine hydrochloride, doxylamine succinate, HUMAN OTC DRUG); 72288-711 (Acetaminophen, Dextromethorphan Hydrobromide, Doxylamine Succinate, Guaifenesin, Phenylephrine Hydrochloride, HUMAN OTC DRUG)

**`duplicate_route`** (27): 86211-114: INTRAVENOUS; 68466-2391: SUBLINGUAL; 16714-114: ORAL; 68466-0003: TOPICAL; 68466-1009: ORAL

## What changed in the database

| Table | Inserted | Updated | Unchanged |
| --- | ---: | ---: | ---: |
| products | 0 | 0 | 135,977 |
| packages | 0 | 0 | 256,975 |

- Products in the database but no longer in the FDA file (kept, not deleted): 0
- Load time: 18.7 s
