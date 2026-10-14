"""Write ``reports/data_quality_report.md`` from a validation result and load stats."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from app.etl.load import LoadStats
from app.etl.validate import ValidationResult


def render(result: ValidationResult, stats: LoadStats | None, source: str) -> str:
    lines = [
        "# Data quality report",
        "",
        "Generated automatically by `python -m app.cli load`. Do not edit by hand.",
        "",
        f"- Generated: {datetime.now(UTC):%Y-%m-%d %H:%M UTC}",
        f"- Source: `{source}`",
        f"- FDA data last updated: {result.source_last_updated or 'unknown'}",
        f"- Records in source file: {result.source_records:,}",
        "",
        "## Rows after cleaning",
        "",
        "| Table | Rows |",
        "| --- | ---: |",
        f"| products | {len(result.products):,} |",
        f"| packages | {len(result.packages):,} |",
        f"| active_ingredients | {len(result.ingredients):,} |",
        f"| product_routes | {len(result.routes):,} |",
        f"| distinct routes | {result.routes['route'].nunique():,} |",
        "",
        "## Checks",
        "",
        '"dropped" means the rows were not loaded. "kept" means they were loaded and are '
        "only reported.",
        "",
        "| Check | Count | Action | What it means |",
        "| --- | ---: | --- | --- |",
    ]
    for issue in result.issues:
        lines.append(f"| `{issue.code}` | {issue.count:,} | {issue.action} | {issue.description} |")
    lines += [
        "",
        f"Total issues found: {result.issues_found:,}. Rows dropped: {result.rows_dropped:,}.",
        "",
        "## Examples",
        "",
    ]
    for issue in result.issues:
        if issue.count:
            lines.append(f"**`{issue.code}`** ({issue.count:,}): " + "; ".join(issue.examples))
            lines.append("")

    if stats is not None:
        lines += [
            "## What changed in the database",
            "",
            "| Table | Inserted | Updated | Unchanged |",
            "| --- | ---: | ---: | ---: |",
            f"| products | {stats.products.inserted:,} | {stats.products.updated:,} | "
            f"{stats.products.unchanged:,} |",
            f"| packages | {stats.packages.inserted:,} | {stats.packages.updated:,} | "
            f"{stats.packages.unchanged:,} |",
            "",
            f"- Products in the database but no longer in the FDA file (kept, not deleted): "
            f"{stats.products_not_in_source:,}",
            f"- Load time: {stats.seconds} s",
            "",
        ]
    return "\n".join(lines)


def write_report(
    result: ValidationResult, stats: LoadStats | None, source: str, reports_dir: Path
) -> Path:
    reports_dir.mkdir(parents=True, exist_ok=True)
    path = reports_dir / "data_quality_report.md"
    path.write_text(render(result, stats, source), encoding="utf-8")
    return path
