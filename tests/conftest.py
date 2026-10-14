"""Shared fixtures.

Integration tests use a real PostgreSQL test database (TEST_DATABASE_URL,
default ``drugs_test`` on localhost:5433). The schema is built by running the
real Alembic migrations, and the small real-data fixture is loaded through
the real ETL pipeline. Every test starts from that same state.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.api.drugs import search_cache
from app.cli import migrate
from app.config import get_settings
from app.db.session import get_session, make_engine
from app.etl.pipeline import PipelineResult, run_pipeline
from app.main import app

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", get_settings().test_database_url)
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "ndc_sample.json"
TABLES = (
    "dispense_records, inventory_lots, reorder_rules, product_routes, routes, "
    "active_ingredients, packages, products, etl_runs"
)


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    eng = make_engine(TEST_DATABASE_URL)
    try:
        with eng.begin() as conn:
            conn.execute(text("DROP SCHEMA public CASCADE"))
            conn.execute(text("CREATE SCHEMA public"))
    except OperationalError as exc:  # pragma: no cover - depends on the environment
        pytest.fail(
            f"Cannot reach the test database at {TEST_DATABASE_URL}. "
            f"Start it with `docker compose up -d db`. ({exc.orig})"
        )
    migrate(TEST_DATABASE_URL)
    yield eng
    eng.dispose()


@pytest.fixture
def empty_db(engine: Engine) -> Engine:
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {TABLES} RESTART IDENTITY CASCADE"))
    search_cache.clear()
    return engine


@pytest.fixture
def loaded(empty_db: Engine, tmp_path: Path) -> PipelineResult:
    """The real-data fixture, loaded through the full ETL pipeline."""
    return run_pipeline(empty_db, FIXTURE, tmp_path)


@pytest.fixture
def session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)


@pytest.fixture
def db(session_factory: sessionmaker[Session]) -> Iterator[Session]:
    with session_factory() as session:
        yield session


@pytest.fixture
def client(session_factory: sessionmaker[Session], loaded: PipelineResult) -> Iterator[TestClient]:
    def override() -> Iterator[Session]:
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = override
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
