"""Run the ETL steps in order: read, parse, validate, load, report."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import Engine

from app.etl.load import LoadStats, load
from app.etl.parse import parse_records, read_records
from app.etl.report import write_report
from app.etl.validate import ValidationResult, validate


@dataclass
class PipelineResult:
    validation: ValidationResult
    stats: LoadStats
    report_path: Path
    seconds: float


def run_pipeline(engine: Engine, json_path: Path, reports_dir: Path) -> PipelineResult:
    started = time.perf_counter()
    records, last_updated = read_records(json_path)
    validation = validate(parse_records(records, last_updated))
    stats = load(engine, validation, source=json_path.name)
    report = write_report(validation, stats, json_path.name, reports_dir)
    return PipelineResult(validation, stats, report, round(time.perf_counter() - started, 1))
