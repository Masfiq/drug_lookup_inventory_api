"""Domain errors. The API layer turns each one into an HTTP status code."""

from __future__ import annotations

from typing import Any


class DomainError(Exception):
    code: str = "domain_error"

    def __init__(self, message: str, **details: Any) -> None:
        super().__init__(message)
        self.message = message
        self.details = details


class NotFoundError(DomainError):
    code = "not_found"


class InsufficientStockError(DomainError):
    code = "insufficient_stock"


class ConflictError(DomainError):
    code = "conflict"


class InvalidLotError(DomainError):
    code = "invalid_lot"
