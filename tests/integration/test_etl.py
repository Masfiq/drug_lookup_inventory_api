"""Loading into PostgreSQL: counts, idempotency, change detection, and the report."""

import json
import zipfile
from pathlib import Path

import pytest
from sqlalchemy import Engine, func, select, text, update
from sqlalchemy.exc import DataError
from sqlalchemy.orm import Session

from app.db.models import ActiveIngredient, EtlRun, Package, Product, ProductRoute, Route
from app.etl.download import JSON_NAME, download
from app.etl.pipeline import PipelineResult, run_pipeline
from tests.conftest import FIXTURE

pytestmark = pytest.mark.integration


def count(db: Session, model: type) -> int:
    return db.scalar(select(func.count()).select_from(model)) or 0


def test_load_writes_the_clean_tables(loaded: PipelineResult, db: Session) -> None:
    v = loaded.validation
    assert count(db, Product) == len(v.products) == 17
    assert count(db, Package) == len(v.packages) == 32
    assert count(db, ActiveIngredient) == len(v.ingredients)
    assert count(db, ProductRoute) == len(v.routes)
    assert loaded.stats.products.inserted == 17
    assert loaded.stats.packages.inserted == 32


def test_routes_are_stored_once_and_linked(loaded: PipelineResult, db: Session) -> None:
    names = db.scalars(select(Route.name)).all()
    assert len(names) == len(set(names))
    product = db.get(Product, "86211-114")
    assert product is not None
    assert [r.name for r in product.routes] == ["INTRAMUSCULAR", "INTRAVENOUS"]


def test_search_text_is_generated_by_the_database(loaded: PipelineResult, db: Session) -> None:
    product = db.get(Product, "58151-155")
    assert product is not None
    assert product.search_text == "lipitor atorvastatin calcium"


def test_loading_twice_changes_nothing(
    loaded: PipelineResult, engine: Engine, tmp_path: Path
) -> None:
    again = run_pipeline(engine, FIXTURE, tmp_path)
    assert (again.stats.products.inserted, again.stats.products.updated) == (0, 0)
    assert again.stats.products.unchanged == 17
    assert (again.stats.packages.inserted, again.stats.packages.updated) == (0, 0)
    with engine.connect() as conn:
        assert conn.scalar(select(func.count()).select_from(Product)) == 17
        assert conn.scalar(select(func.count()).select_from(ActiveIngredient)) == len(
            loaded.validation.ingredients
        )
        assert conn.scalar(select(func.count()).select_from(EtlRun)) == 2


def test_reload_detects_changed_and_missing_products(
    loaded: PipelineResult, engine: Engine, tmp_path: Path
) -> None:
    with engine.begin() as conn:
        conn.execute(
            update(Product).where(Product.product_ndc == "58151-155").values(labeler_name="Old")
        )
        conn.execute(
            text("INSERT INTO products (product_ndc, updated_at) VALUES ('0000-0000', now())")
        )

    again = run_pipeline(engine, FIXTURE, tmp_path)

    assert again.stats.products.updated == 1  # the labeler change was put back
    assert again.stats.products.unchanged == 16
    assert again.stats.products_not_in_source == 1  # kept, only reported
    report = again.report_path.read_text(encoding="utf-8")
    assert "| products | 0 | 1 | 16 |" in report


def test_report_is_written_with_counts(loaded: PipelineResult) -> None:
    text_ = loaded.report_path.read_text(encoding="utf-8")
    assert "| `duplicate_product_ndc` | 3 | dropped |" in text_
    assert "| `malformed_package_ndc` | 2 | dropped |" in text_
    assert "| products | 17 |" in text_


def test_failed_load_rolls_back_everything(empty_db: Engine, tmp_path: Path) -> None:
    """Routes load after products and packages. A route name too long for its
    column fails the load at that late step; the earlier inserts must be undone."""
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload["results"][0]["route"] = ["X" * 150]  # routes.name is VARCHAR(100)
    broken = tmp_path / "broken.json"
    broken.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(DataError):
        run_pipeline(empty_db, broken, tmp_path)

    with empty_db.connect() as conn:
        assert conn.scalar(select(func.count()).select_from(Product)) == 0  # nothing half-loaded
        assert conn.scalar(select(func.count()).select_from(Package)) == 0


def test_download_extracts_the_json(tmp_path: Path) -> None:
    source = tmp_path / "source.zip"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr(JSON_NAME, '{"results": []}')
    raw_dir = tmp_path / "raw"

    path = download(raw_dir=raw_dir, url=source.as_uri())

    assert path == raw_dir / JSON_NAME
    assert path.read_text() == '{"results": []}'
    assert not (raw_dir / "drug-ndc.json.zip").exists()
    assert download(raw_dir=raw_dir, url="http://unused.invalid") == path  # already there


def test_download_rejects_unexpected_zip(tmp_path: Path) -> None:
    source = tmp_path / "source.zip"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("something-else.json", "{}")
    with pytest.raises(RuntimeError, match="not found in zip"):
        download(raw_dir=tmp_path / "raw", url=source.as_uri())
