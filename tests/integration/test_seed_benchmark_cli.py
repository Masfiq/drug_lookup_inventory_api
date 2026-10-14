from pathlib import Path

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Engine, func, select, text

from app import cli
from app.benchmark import run_benchmark
from app.config import Settings
from app.db.models import Base, InventoryLot, Package, Product, ReorderRule
from app.etl.pipeline import PipelineResult
from app.etl.seed_inventory import STOCKED_PRODUCT_TYPES, seed_inventory
from tests.conftest import FIXTURE

pytestmark = pytest.mark.integration


def current_lots(engine: Engine) -> list[tuple[str, str, int]]:
    # A short-lived connection: an open transaction here would block the next TRUNCATE.
    with engine.connect() as conn:
        rows = conn.execute(
            select(InventoryLot.package_ndc, InventoryLot.lot_number, InventoryLot.quantity)
        ).all()
    return sorted((str(a), str(b), int(c)) for a, b, c in rows)


def test_seed_inventory_is_synthetic_and_repeatable(loaded: PipelineResult, engine: Engine) -> None:
    first = seed_inventory(engine, packages=5, seed=1)
    lots_first = current_lots(engine)
    second = seed_inventory(engine, packages=5, seed=1)  # replaces, not appends

    assert first == second
    assert first.packages == first.reorder_rules == 5
    assert 5 <= first.lots <= 20
    assert lots_first == current_lots(engine)
    with engine.connect() as conn:
        types = conn.scalars(
            select(Product.product_type)
            .join(Package)
            .join(ReorderRule, ReorderRule.package_ndc == Package.package_ndc)
            .distinct()
        ).all()
    assert set(types) <= set(STOCKED_PRODUCT_TYPES)


def test_benchmark_runs_before_and_after(
    loaded: PipelineResult, engine: Engine, tmp_path: Path
) -> None:
    seed_inventory(engine, packages=10)
    path = run_benchmark(runs=1, engine=engine, reports_dir=tmp_path)
    report = path.read_text(encoding="utf-8")
    assert "| Query | Before (no index) | After (with index) | Speedup |" in report
    # On 17 rows PostgreSQL rightly prefers a sequential scan, so check the
    # indexes were recreated rather than expecting them in the plans.
    with engine.connect() as conn:
        indexes = set(conn.scalars(text("SELECT indexname FROM pg_indexes")))
        assert conn.scalar(select(func.count()).select_from(Product)) == 17
    assert {
        "ix_products_search_text_trgm",
        "ix_active_ingredients_name_prefix",
        "ix_inventory_lots_expiring",
    } <= indexes


def test_migrations_match_models(engine: Engine) -> None:
    """Fails if a model changes without a migration (expression indexes are skipped)."""
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == []


def test_cli_load_and_seed(
    empty_db: Engine,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import app.config
    import app.db.session

    monkeypatch.setattr(app.db.session, "get_engine", lambda: empty_db)
    monkeypatch.setattr(app.config, "get_settings", lambda: Settings(reports_dir=tmp_path))

    cli.main(["load", "--file", str(FIXTURE)])
    out = capsys.readouterr().out
    assert "Products  inserted 17" in out
    assert (tmp_path / "data_quality_report.md").exists()

    cli.main(["seed-inventory", "--packages", "3"])
    assert "across 3 packages" in capsys.readouterr().out

    with pytest.raises(SystemExit, match="not found"):
        cli.main(["load", "--file", str(tmp_path / "missing.json")])
