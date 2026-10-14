"""Command line entry point.

python -m app.cli run              migrate the database, then start the API
python -m app.cli load-all         download + load FDA data + seed inventory (one command)

python -m app.cli migrate          apply database migrations
python -m app.cli download         download the FDA NDC file into data/raw/
python -m app.cli load             parse, validate, and load it; writes the quality report
python -m app.cli seed-inventory   replace inventory with fresh synthetic lots
python -m app.cli benchmark        EXPLAIN ANALYZE the key queries without and with indexes
python -m app.cli serve            start the API only
"""

from __future__ import annotations

import argparse
from pathlib import Path

from alembic import command
from alembic.config import Config

ROOT = Path(__file__).resolve().parent.parent


def alembic_config(database_url: str | None = None) -> Config:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "alembic"))
    if database_url:
        config.set_main_option("sqlalchemy.url", database_url)
    return config


def migrate(database_url: str | None = None, revision: str = "head") -> None:
    from app.config import get_settings
    from app.db.session import check_database

    check_database(database_url or get_settings().database_url)  # fail fast, with a clear message
    command.upgrade(alembic_config(database_url), revision)


def cmd_download(args: argparse.Namespace) -> None:
    from app.etl.download import download

    download(force=args.force)


def cmd_load(args: argparse.Namespace) -> None:
    from app.config import get_settings
    from app.db.session import get_engine
    from app.etl.download import raw_json_path
    from app.etl.pipeline import run_pipeline

    path = Path(args.file) if args.file else raw_json_path()
    if not path.exists():
        raise SystemExit(f"{path} not found. Run: python -m app.cli download")
    print(f"Loading {path} ...")
    result = run_pipeline(get_engine(), path, get_settings().reports_dir)
    v, s = result.validation, result.stats
    print(f"Source records: {v.source_records:,}")
    print(
        f"Products  inserted {s.products.inserted:,}  updated {s.products.updated:,}  "
        f"unchanged {s.products.unchanged:,}"
    )
    print(
        f"Packages  inserted {s.packages.inserted:,}  updated {s.packages.updated:,}  "
        f"unchanged {s.packages.unchanged:,}"
    )
    print(f"Ingredients {s.ingredients:,}  product routes {s.product_routes:,}")
    print(f"Issues found {v.issues_found:,}  rows dropped {v.rows_dropped:,}")
    print(f"Report: {result.report_path}  ({result.seconds} s total)")


def cmd_seed(args: argparse.Namespace) -> None:
    from app.db.session import get_engine
    from app.etl.seed_inventory import seed_inventory

    stats = seed_inventory(get_engine(), packages=args.packages, seed=args.seed)
    print(
        f"Synthetic inventory: {stats.lots:,} lots across {stats.packages:,} packages, "
        f"{stats.reorder_rules:,} reorder rules"
    )


def cmd_load_all(args: argparse.Namespace) -> None:
    migrate()
    args.force = False
    cmd_download(args)
    args.file = None
    cmd_load(args)
    cmd_seed(args)


def cmd_benchmark(args: argparse.Namespace) -> None:
    from app.benchmark import run_benchmark

    run_benchmark(runs=args.runs)


def cmd_serve(args: argparse.Namespace) -> None:
    import uvicorn

    uvicorn.run("app.main:app", host=args.host, port=args.port)


def cmd_run(args: argparse.Namespace) -> None:
    migrate()
    print(f"API docs:    http://{args.host}:{args.port}/docs")
    print(f"Search page: http://{args.host}:{args.port}/")
    cmd_serve(args)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("migrate", help="apply database migrations").set_defaults(
        func=lambda _: migrate()
    )

    p = sub.add_parser("download", help="download the FDA NDC file")
    p.add_argument("--force", action="store_true", help="download again even if present")
    p.set_defaults(func=cmd_download)

    p = sub.add_parser("load", help="parse, validate, and load the FDA file")
    p.add_argument("--file", help="path to an FDA NDC JSON file (default: data/raw/)")
    p.set_defaults(func=cmd_load)

    for name, func, help_text in (
        ("seed-inventory", cmd_seed, "replace inventory with synthetic lots"),
        ("load-all", cmd_load_all, "download, load, and seed in one go"),
    ):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("--packages", type=int, default=20_000, help="packages to stock")
        p.add_argument("--seed", type=int, default=42)
        p.set_defaults(func=func)

    p = sub.add_parser("benchmark", help="time key queries without and with indexes")
    p.add_argument("--runs", type=int, default=7)
    p.set_defaults(func=cmd_benchmark)

    for name, func in (("serve", cmd_serve), ("run", cmd_run)):
        p = sub.add_parser(name, help="start the API" if name == "serve" else "migrate and serve")
        p.add_argument("--host", default="127.0.0.1")
        p.add_argument("--port", type=int, default=8001)
        p.set_defaults(func=func)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
