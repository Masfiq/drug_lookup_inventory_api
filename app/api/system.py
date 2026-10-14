from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import func, select

from app.api.deps import SessionDep
from app.api.drugs import search_cache
from app.api.errors import error_response
from app.db.models import EtlRun, Product
from app.schemas import ErrorResponse, HealthOut

router = APIRouter(tags=["system"])


@router.get("/health", response_model=HealthOut, responses={503: {"model": ErrorResponse}})
def health(session: SessionDep) -> HealthOut | JSONResponse:
    """Is the API up, can it reach the database, and how much data is loaded?"""
    try:
        products = session.scalar(select(func.count()).select_from(Product)) or 0
        last_load = session.scalar(select(func.max(EtlRun.finished_at)))
    except Exception:
        return error_response(503, "database_unavailable", "Database is not reachable")
    return HealthOut(
        status="ok",
        database="ok",
        products=products,
        last_load=last_load,
        search_cache={
            "entries": len(search_cache),
            "hits": search_cache.hits,
            "misses": search_cache.misses,
        },
    )
