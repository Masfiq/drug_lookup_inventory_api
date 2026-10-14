"""Step 1 of the ETL: download and unzip the openFDA NDC Directory bulk file."""

from __future__ import annotations

import shutil
import urllib.request
import zipfile
from pathlib import Path

from app.config import get_settings

JSON_NAME = "drug-ndc-0001-of-0001.json"


def raw_json_path(raw_dir: Path | None = None) -> Path:
    return (raw_dir or get_settings().raw_dir) / JSON_NAME


def download(force: bool = False, raw_dir: Path | None = None, url: str | None = None) -> Path:
    """Download the zip (about 28 MB) and extract the JSON. Returns the JSON path.

    Skips the download when the JSON already exists, unless ``force`` is set.
    """
    settings = get_settings()
    raw_dir = raw_dir or settings.raw_dir
    url = url or settings.fda_ndc_url
    target = raw_json_path(raw_dir)
    if target.exists() and not force:
        print(f"Already downloaded: {target}")
        return target

    raw_dir.mkdir(parents=True, exist_ok=True)
    zip_path = raw_dir / "drug-ndc.json.zip"
    print(f"Downloading {url}")
    with urllib.request.urlopen(url, timeout=120) as response, zip_path.open("wb") as out:
        shutil.copyfileobj(response, out)
    print(f"Saved {zip_path.stat().st_size / 1_000_000:.1f} MB, unzipping")

    with zipfile.ZipFile(zip_path) as archive:
        if JSON_NAME not in archive.namelist():
            raise RuntimeError(f"{JSON_NAME} not found in zip, got {archive.namelist()}")
        archive.extract(JSON_NAME, raw_dir)  # extract only the file we expect, by name
    zip_path.unlink()
    print(f"Extracted {target} ({target.stat().st_size / 1_000_000:.1f} MB)")
    return target
