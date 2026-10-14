"""Settings, read from environment variables or a local .env file."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://drugs:drugs@localhost:5433/drugs"
    test_database_url: str = "postgresql+psycopg://drugs:drugs@localhost:5433/drugs_test"

    fda_ndc_url: str = "https://download.open.fda.gov/drug/ndc/drug-ndc-0001-of-0001.json.zip"
    raw_dir: Path = ROOT / "data" / "raw"
    reports_dir: Path = ROOT / "reports"

    search_cache_seconds: int = 300
    search_cache_size: int = 1000


@lru_cache
def get_settings() -> Settings:
    return Settings()
