# API reference

Base URL when running locally: `http://127.0.0.1:8001`. Interactive docs with "Try it out"
buttons: `/docs`. Machine readable schema: `/openapi.json`.

All list endpoints are paginated with `limit` (1 to 100, default 20) and `offset` (default 0),
and return `total` so a client can show "results 21 to 40 of 515".

## Errors

Every error has the same shape:

```json
{"error": {"code": "not_found", "message": "No product with NDC 0000-0000",
           "details": {"product_ndc": "0000-0000"}}}
```

| Status | `code` | When |
| --- | --- | --- |
| 404 | `not_found` | Unknown product, package, or URL |
| 409 | `insufficient_stock` | Dispense asks for more than the usable (not expired) stock |
| 409 | `conflict` | Receiving a lot number that already exists for that package |
| 422 | `invalid_lot` | Receiving a lot that has already expired |
| 422 | `validation_error` | Bad input, for example `quantity: 0` or a search under 2 characters |
| 503 | `database_unavailable` | The database cannot be reached |

## Drugs

### `GET /drugs/search`

Fuzzy search by brand or generic name.

| Param | Required | Notes |
| --- | --- | --- |
| `q` | yes | 2 to 100 characters. Case and extra spaces are ignored. Typos are tolerated. |
| `limit`, `offset` | no | Pagination |

Response header `X-Cache` is `HIT` when the answer came from the 5 minute in-memory cache.

```bash
curl "http://127.0.0.1:8001/drugs/search?q=atorvastatn&limit=1"
```

```json
{"query": "atorvastatn", "total": 515, "limit": 1, "offset": 0,
 "items": [{"product_ndc": "0615-8006", "brand_name": "ATORVASTATIN CALCIUM",
            "generic_name": "ATORVASTATIN CALCIUM",
            "labeler_name": "NCS HealthCare of KY, LLC dba Vangard Labs",
            "dosage_form": "TABLET, FILM COATED", "product_type": "HUMAN PRESCRIPTION DRUG",
            "score": 0.833}]}
```

`score` (0 to 1) is the trigram word similarity; results are sorted by it, highest first.

### `GET /drugs/{product_ndc}`

One product with ingredients, routes, and packages. 404 if unknown.

```bash
curl "http://127.0.0.1:8001/drugs/58151-155"
```

```json
{"product_ndc": "58151-155", "brand_name": "Lipitor", "generic_name": "atorvastatin calcium",
 "labeler_name": "Viatris Specialty LLC", "dosage_form": "TABLET, FILM COATED",
 "product_type": "HUMAN PRESCRIPTION DRUG", "marketing_category": "NDA",
 "ingredients": [{"name": "ATORVASTATIN CALCIUM TRIHYDRATE", "strength": "10 mg/1"}],
 "routes": [{"name": "ORAL"}],
 "packages": [{"package_ndc": "58151-155-77", "description": "90 TABLET, FILM COATED in 1 BOTTLE (58151-155-77)"}]}
```

### `GET /drugs/by-ingredient`

Products that contain an active ingredient whose name **starts with** `name`
(case-insensitive). `%` and `_` are treated as normal characters.

```bash
curl "http://127.0.0.1:8001/drugs/by-ingredient?name=metformin&limit=2"
```

Each item is a product summary plus its `ingredients` list. On the full data set, "metformin"
returned 730 products.

## Inventory

### `GET /inventory`

Stock per package, summing all its lots. Only packages with at least one lot are listed.
Optional `package_ndc` filter.

```json
{"total": 20000, "limit": 1, "offset": 0,
 "items": [{"package_ndc": "0002-1200-48", "product_ndc": "0002-1200",
            "drug_name": "Amyvid (Florbetapir F 18)",
            "package_description": "1 VIAL, MULTI-DOSE in 1 CAN (0002-1200-48)  / 100 mL in 1 VIAL, MULTI-DOSE",
            "usable_quantity": 202, "expired_quantity": 0, "lot_count": 1,
            "next_expiration": "2027-06-25", "reorder_threshold": 87, "below_threshold": false}]}
```

- `usable_quantity`: units in lots that have not expired (what can be dispensed).
- `expired_quantity`: units in expired lots (must be removed, never dispensed).
- `next_expiration`: earliest expiry among usable lots.

### `POST /inventory/lots`

Receive a lot. Returns 201 with the new lot.

```json
{"package_ndc": "58151-155-77", "lot_number": "AB12345", "quantity": 100,
 "expiration_date": "2028-06-30", "received_at": null}
```

`lot_number` allows letters, digits, and dashes. Errors: 404 unknown package, 409 duplicate lot
for that package, 422 already expired or invalid input.

### `POST /inventory/dispense`

Take `quantity` units using FEFO, in one transaction.

```json
{"package_ndc": "58151-155-77", "quantity": 30, "reference": "RX-1001"}
```

```json
{"package_ndc": "0002-1436-00", "quantity": 100,
 "allocations": [{"lot_id": 33437, "lot_number": "FZ46096", "quantity": 100,
                  "expiration_date": "2027-07-27"}],
 "remaining_usable": 810}
```

`allocations` lists which lots were used, soonest expiring first. Each one is also saved in
`dispense_records` with the `reference`. If there is not enough usable stock the response is 409
and nothing changes.

### `GET /inventory/expiring`

Lots that still have stock and expire within `days` (0 to 3650, default 30), soonest first.
`include_expired=true` also lists lots that are already past their date
(`days_until_expiry` is negative for those).

```json
{"days": 30, "total": 2050, "limit": 20, "offset": 0,
 "items": [{"id": 437, "package_ndc": "71335-2575-3", "lot_number": "YY43426", "quantity": 11,
            "expiration_date": "2026-10-13", "received_at": "2026-05-06T09:00:00Z",
            "days_until_expiry": 0}]}
```

### `GET /inventory/low-stock`

Packages with a reorder rule whose **usable** stock is below the threshold, worst shortfall
first. Packages with a rule but no lots at all are included with 0.

## System

### `GET /health`

```json
{"status": "ok", "database": "ok", "products": 135977,
 "last_load": "2026-10-14T02:01:22.116654Z",
 "search_cache": {"entries": 0, "hits": 0, "misses": 0}}
```

`last_load` is when the most recent ETL run finished. Returns 503 if the database is unreachable.

### `GET /`

The search page.

The example responses above were captured from the running API on the full data set. The
inventory examples come from the synthetic stockroom, so your numbers will differ.
