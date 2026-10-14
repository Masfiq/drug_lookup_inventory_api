# Project 2: Drug Lookup and Inventory API (openFDA data)

## Goal

Build an API that loads real public drug data from the FDA (the openFDA NDC Directory) into PostgreSQL and serves fast search, plus a pharmacy inventory layer with lot tracking, expiration alerts, and low stock reports.

This shows SQL skill, ETL on real healthcare data, data validation, query performance work, and clean API design. It can stand alone or later become the inventory module for Project 1 (Pharmacy Order Fulfillment Service), so keep the Drug and Inventory models compatible.

## How we work (read first)

- I am building this to learn and to explain it in interviews. **Explain the plan before each phase and the key design decisions after it.**
- Work in **small phases** and stop after each one so I can run, read, and commit.
- Readable code, type hints, no clever tricks.
- Never invent numbers. Row counts, query timings, and test counts in the README must come from real runs.
- Inventory data (lots, quantities) is **synthetic**. The drug reference data is real public FDA data. README must say this is a learning project, not for clinical use.
- In prose (README, docstrings), avoid em dashes and en dashes.

## Data source

- openFDA NDC Directory bulk download: `https://download.open.fda.gov/drug/ndc/drug-ndc-0001-of-0001.json.zip`
- API docs: https://open.fda.gov/apis/drug/ndc/
- Check the docs first and confirm the field names before writing the loader. Key fields include product_ndc, generic_name, brand_name, labeler_name, dosage_form, route, marketing_category, active_ingredients (list), packaging (list with package_ndc and description).
- Do not commit the raw data file to Git. Add it to `.gitignore` and provide a download script.

## Tech stack

- Python 3.11+, FastAPI, Pydantic
- PostgreSQL with SQLAlchemy 2.0 and Alembic
- Pandas for the ETL step (my existing strength)
- pytest, ruff, mypy
- Docker Compose for local PostgreSQL
- GitHub Actions CI

## Database design (normalized)

- **products**: product_ndc (PK), generic_name, brand_name, labeler_name, dosage_form, marketing_category
- **packages**: package_ndc (PK), product_ndc (FK), description
- **active_ingredients**: id, product_ndc (FK), name, strength
- **routes**: product_ndc (FK), route (many to many handled cleanly)
- **inventory_lots** (synthetic): id, package_ndc (FK), lot_number, quantity, expiration_date, received_at
- **reorder_rules** (synthetic): package_ndc, reorder_threshold

Explain why the schema is normalized this way and show an ER diagram (Mermaid) in the README.

## ETL pipeline

1. Download and unzip the JSON
2. Parse nested fields (ingredients, packaging, routes) into flat tables
3. **Validation checks**, reported in a generated `data_quality_report.md`: missing NDCs, duplicate keys, products with no packages, malformed NDC formats, null generic names. Count each issue; never silently drop rows without logging why.
4. Load into PostgreSQL in batches inside transactions; the loader must be **idempotent** (safe to run twice)
5. Seed synthetic inventory lots for a sample of packages

## API endpoints

- `GET /drugs/search?q=` search by brand or generic name, with **fuzzy matching** (PostgreSQL pg_trgm extension) and pagination
- `GET /drugs/{product_ndc}` product with ingredients, routes, and packages
- `GET /drugs/by-ingredient?name=` all products containing an ingredient
- `GET /inventory` current stock by package, summing lots
- `POST /inventory/lots` receive a new lot
- `POST /inventory/dispense` dispense quantity using **FEFO** (first expiring, first out) across lots, inside a transaction
- `GET /inventory/expiring?days=30` lots expiring soon
- `GET /inventory/low-stock` packages below reorder threshold
- `GET /health`

## Performance work (make this a visible section)

- Pick 3 real queries (name search, ingredient lookup, expiring lots)
- Run `EXPLAIN ANALYZE` before adding indexes, then add the right indexes (B-tree, GIN trigram), then measure again
- Put the real before and after timings in the README with a short explanation of why each index helps

## Build phases

1. **Scaffold**: structure, Docker Compose, FastAPI health endpoint, tooling. Show folder tree first.
2. **Download script and schema**: Alembic migration for all tables.
3. **ETL**: parser, validation report, idempotent loader. Tests on a small sample JSON fixture.
4. **Drug endpoints**: search, detail, by ingredient, with tests.
5. **Inventory layer**: synthetic seed, FEFO dispense logic as a pure function with unit tests, then endpoints.
6. **Performance**: EXPLAIN ANALYZE, indexes, real timings.
7. **CI** in GitHub Actions (tests run against the small fixture, not the full download).
8. **README**: overview, ER diagram, ETL flow diagram, data quality summary, performance table, how to run, example requests, design decisions, next steps.

## Stretch goals

- Simple search page (plain HTML or Streamlit) on top of the API
- Response caching for popular searches, with measured effect
- Weekly refresh job that reloads new FDA data and reports what changed

## Definition of done

- One command to start the database and API, one command to load data
- Tests pass in CI
- README shows real data quality counts and real query timings
- I can explain normalization, FEFO, transactions, and the indexes without notes
- At the end, give me 2 to 3 honest resume bullets using only real numbers from this project
