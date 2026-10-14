from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Query, Response

from app.api.deps import Limit, Offset, SessionDep
from app.cache import TTLCache
from app.config import get_settings
from app.schemas import (
    ErrorResponse,
    IngredientPage,
    ProductDetail,
    ProductSummary,
    ProductWithIngredients,
    SearchHit,
    SearchPage,
)
from app.services.drugs import DrugService, normalize_query

router = APIRouter(prefix="/drugs", tags=["drugs"])

_settings = get_settings()
search_cache: TTLCache[SearchPage] = TTLCache(
    _settings.search_cache_seconds, _settings.search_cache_size
)

NOT_FOUND: dict[int | str, dict[str, Any]] = {404: {"model": ErrorResponse}}


@router.get("/search", response_model=SearchPage)
def search(
    session: SessionDep,
    response: Response,
    q: Annotated[str, Query(min_length=2, max_length=100, description="Brand or generic name")],
    limit: Limit = 20,
    offset: Offset = 0,
) -> SearchPage:
    """Fuzzy search by brand or generic name. Tolerates small typos ("atorvastatn").

    Results are cached in memory for a few minutes; the ``X-Cache`` response
    header says HIT or MISS.
    """
    key = (normalize_query(q), limit, offset)
    cached = search_cache.get(key)
    if cached is not None:
        response.headers["X-Cache"] = "HIT"
        return cached

    rows, total = DrugService(session).search(q, limit, offset)
    page = SearchPage(
        query=key[0],
        total=total,
        limit=limit,
        offset=offset,
        items=[
            SearchHit(**ProductSummary.model_validate(product).model_dump(), score=score)
            for product, score in rows
        ],
    )
    search_cache.set(key, page)
    response.headers["X-Cache"] = "MISS"
    return page


@router.get("/by-ingredient", response_model=IngredientPage)
def by_ingredient(
    session: SessionDep,
    name: Annotated[str, Query(min_length=2, max_length=100, examples=["metformin"])],
    limit: Limit = 20,
    offset: Offset = 0,
) -> IngredientPage:
    """Products containing an active ingredient whose name starts with ``name``."""
    rows, total = DrugService(session).by_ingredient(name, limit, offset)
    return IngredientPage(
        ingredient=normalize_query(name),
        total=total,
        limit=limit,
        offset=offset,
        items=[ProductWithIngredients.model_validate(p) for p in rows],
    )


@router.get("/{product_ndc}", response_model=ProductDetail, responses=NOT_FOUND)
def get_drug(product_ndc: str, session: SessionDep) -> ProductDetail:
    """One product with its ingredients, routes, and packages."""
    return ProductDetail.model_validate(DrugService(session).get(product_ndc))
