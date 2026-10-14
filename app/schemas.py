"""Pydantic request and response schemas (the public API contract)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    error: ErrorBody


class Page(BaseModel):
    total: int
    limit: int
    offset: int


# ----- drugs ----------------------------------------------------------------


class IngredientOut(ORMModel):
    name: str
    strength: str | None


class RouteOut(ORMModel):
    name: str


class PackageOut(ORMModel):
    package_ndc: str
    description: str | None


class ProductSummary(ORMModel):
    product_ndc: str
    brand_name: str | None
    generic_name: str | None
    labeler_name: str | None
    dosage_form: str | None
    product_type: str | None


class SearchHit(ProductSummary):
    score: float = Field(description="Word similarity between the query and the name, 0 to 1")


class SearchPage(Page):
    query: str
    items: list[SearchHit]


class ProductWithIngredients(ProductSummary):
    ingredients: list[IngredientOut]


class IngredientPage(Page):
    ingredient: str
    items: list[ProductWithIngredients]


class ProductDetail(ProductSummary):
    marketing_category: str | None
    ingredients: list[IngredientOut]
    routes: list[RouteOut]
    packages: list[PackageOut]


# ----- inventory ------------------------------------------------------------


class StockLineOut(ORMModel):
    package_ndc: str
    product_ndc: str
    drug_name: str
    package_description: str | None
    usable_quantity: int = Field(description="Units in lots that have not expired")
    expired_quantity: int = Field(description="Units in expired lots (must not be dispensed)")
    lot_count: int
    next_expiration: date | None
    reorder_threshold: int | None
    below_threshold: bool


class StockPage(Page):
    items: list[StockLineOut]


class LotIn(BaseModel):
    package_ndc: str = Field(min_length=1, max_length=20, examples=["0071-0155-23"])
    lot_number: str = Field(
        min_length=1, max_length=40, pattern=r"^[A-Za-z0-9\-]+$", examples=["AB12345"]
    )
    quantity: int = Field(gt=0, le=1_000_000, examples=[500])
    expiration_date: date = Field(examples=["2027-06-30"])
    received_at: datetime | None = None


class LotOut(ORMModel):
    id: int
    package_ndc: str
    lot_number: str
    quantity: int
    expiration_date: date
    received_at: datetime


class ExpiringLotOut(LotOut):
    days_until_expiry: int


class ExpiringPage(Page):
    days: int
    items: list[ExpiringLotOut]


class DispenseIn(BaseModel):
    package_ndc: str = Field(min_length=1, max_length=20)
    quantity: int = Field(gt=0, le=100_000, examples=[30])
    reference: str | None = Field(
        default=None, max_length=100, description="Optional order or prescription reference"
    )


class AllocationOut(ORMModel):
    lot_id: int
    lot_number: str
    quantity: int
    expiration_date: date


class DispenseOut(BaseModel):
    package_ndc: str
    quantity: int
    allocations: list[AllocationOut]
    remaining_usable: int


class HealthOut(BaseModel):
    status: str
    database: str
    products: int
    last_load: datetime | None
    search_cache: dict[str, int]
