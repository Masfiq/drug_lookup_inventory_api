"""Drug lookups: fuzzy name search, product detail, and ingredient search.

The query builders (``search_query``, ``ingredient_query``) are separate
functions so the benchmark can EXPLAIN ANALYZE exactly the SQL the API runs.
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import Select, exists, func, select
from sqlalchemy.orm import Session, selectinload

from app.db.models import ActiveIngredient, Product
from app.domain.errors import NotFoundError

# How similar a word must be to count as a match (0 to 1). 0.4 still matches a
# swapped-letter typo ("metfromin" scores 0.43 against "metformin"); measured on
# the full FDA data, it adds almost no unrelated results. Best matches sort first.
DEFAULT_SIMILARITY = 0.4


def normalize_query(q: str) -> str:
    return " ".join(q.lower().split())


def search_query(q: str) -> Select[Product, float]:
    """Products whose brand or generic name contains a word similar to ``q``.

    ``q <% search_text`` is pg_trgm's "word similarity" operator: it compares
    ``q`` against the best matching stretch of words in ``search_text``, so a
    query for "lipitor" matches "lipitor atorvastatin calcium". It can use the
    GIN trigram index, while computing similarity() row by row cannot.
    """
    score = func.word_similarity(q, Product.search_text).label("score")
    return (
        select(Product, score)
        .where(Product.search_text.bool_op("%>")(q))  # same as  q <% search_text
        .order_by(score.desc(), Product.brand_name.asc().nulls_last(), Product.product_ndc)
    )


def ingredient_query(name: str) -> Select[Product]:
    """Products that contain an active ingredient whose name starts with ``name``."""
    prefix = func.lower(ActiveIngredient.name).startswith(name.lower(), autoescape=True)
    has_ingredient = exists().where(ActiveIngredient.product_ndc == Product.product_ndc, prefix)
    return select(Product).where(has_ingredient).order_by(Product.generic_name, Product.product_ndc)


class DrugService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def set_similarity_threshold(self, threshold: float) -> None:
        """Applies to the current transaction only (``is_local`` = true)."""
        self.session.execute(
            select(func.set_config("pg_trgm.word_similarity_threshold", str(threshold), True))
        )

    def search(
        self, q: str, limit: int, offset: int, threshold: float = DEFAULT_SIMILARITY
    ) -> tuple[list[tuple[Product, float]], int]:
        q = normalize_query(q)
        self.set_similarity_threshold(threshold)
        stmt = search_query(q)
        total = self.session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        rows = self.session.execute(stmt.limit(limit).offset(offset)).all()
        return [(product, round(float(score), 3)) for product, score in rows], total

    def get(self, product_ndc: str) -> Product:
        stmt = (
            select(Product)
            .options(
                selectinload(Product.ingredients),
                selectinload(Product.routes),
                selectinload(Product.packages),
            )
            .where(Product.product_ndc == product_ndc)
        )
        product = self.session.scalars(stmt).one_or_none()
        if product is None:
            raise NotFoundError(f"No product with NDC {product_ndc}", product_ndc=product_ndc)
        return product

    def by_ingredient(self, name: str, limit: int, offset: int) -> tuple[Sequence[Product], int]:
        name = normalize_query(name)
        stmt = ingredient_query(name)
        total = self.session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        rows = self.session.scalars(
            stmt.options(selectinload(Product.ingredients)).limit(limit).offset(offset)
        ).all()
        return rows, total
