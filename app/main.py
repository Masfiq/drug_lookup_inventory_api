"""FastAPI application factory."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse

from app.api import drugs, inventory, system
from app.api.errors import register_error_handlers

SEARCH_PAGE = Path(__file__).resolve().parent / "static" / "index.html"

DESCRIPTION = """
Search real FDA drug data and manage a (synthetic) pharmacy inventory.

**Learning project. Not for clinical use.** Drug reference data comes from the
public openFDA NDC Directory. All inventory data (lots, quantities, dates) is
made up.
"""


def create_app() -> FastAPI:
    app = FastAPI(title="Drug Lookup and Inventory API", version="0.1.0", description=DESCRIPTION)
    register_error_handlers(app)
    for module in (drugs, inventory, system):
        app.include_router(module.router)

    @app.get("/", include_in_schema=False)
    def search_page() -> FileResponse:
        return FileResponse(SEARCH_PAGE)

    return app


app = create_app()
