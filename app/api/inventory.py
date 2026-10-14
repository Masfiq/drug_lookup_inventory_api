from __future__ import annotations

from dataclasses import asdict
from typing import Annotated, Any

from fastapi import APIRouter, Query, status

from app.api.deps import Limit, Offset, SessionDep
from app.schemas import (
    AllocationOut,
    DispenseIn,
    DispenseOut,
    ErrorResponse,
    ExpiringLotOut,
    ExpiringPage,
    LotIn,
    LotOut,
    StockLineOut,
    StockPage,
)
from app.services.inventory import InventoryService, StockLine

router = APIRouter(prefix="/inventory", tags=["inventory"])

ERRORS: dict[int | str, dict[str, Any]] = {
    404: {"model": ErrorResponse},
    409: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
}


def to_out(line: StockLine) -> StockLineOut:
    return StockLineOut(**asdict(line), below_threshold=line.below_threshold)


@router.get("", response_model=StockPage)
def stock(
    session: SessionDep,
    limit: Limit = 20,
    offset: Offset = 0,
    package_ndc: str | None = None,
) -> StockPage:
    """Current stock per package: the sum of its lots, split into usable and expired."""
    lines, total = InventoryService(session).stock(limit, offset, package_ndc)
    return StockPage(total=total, limit=limit, offset=offset, items=[to_out(x) for x in lines])


@router.post("/lots", response_model=LotOut, status_code=status.HTTP_201_CREATED, responses=ERRORS)
def receive_lot(body: LotIn, session: SessionDep) -> LotOut:
    """Receive a new lot of a package into stock."""
    lot = InventoryService(session).receive_lot(**body.model_dump())
    return LotOut.model_validate(lot)


@router.post("/dispense", response_model=DispenseOut, responses=ERRORS)
def dispense(body: DispenseIn, session: SessionDep) -> DispenseOut:
    """Dispense units using FEFO: the lots that expire first are used first.

    Runs in one transaction. Expired lots are never used. If there is not
    enough usable stock, nothing changes and the response is 409.
    """
    result = InventoryService(session).dispense(body.package_ndc, body.quantity, body.reference)
    return DispenseOut(
        package_ndc=result.package_ndc,
        quantity=result.quantity,
        allocations=[AllocationOut.model_validate(a) for a in result.allocations],
        remaining_usable=result.remaining_usable,
    )


@router.get("/expiring", response_model=ExpiringPage)
def expiring(
    session: SessionDep,
    days: Annotated[int, Query(ge=0, le=3650)] = 30,
    include_expired: bool = False,
    limit: Limit = 20,
    offset: Offset = 0,
) -> ExpiringPage:
    """Lots with stock that expire within ``days`` days, soonest first."""
    service = InventoryService(session)
    lots, total = service.expiring(days, limit, offset, include_expired)
    items = [
        ExpiringLotOut(
            **LotOut.model_validate(lot).model_dump(),
            days_until_expiry=(lot.expiration_date - service.today).days,
        )
        for lot in lots
    ]
    return ExpiringPage(days=days, total=total, limit=limit, offset=offset, items=items)


@router.get("/low-stock", response_model=StockPage)
def low_stock(session: SessionDep, limit: Limit = 20, offset: Offset = 0) -> StockPage:
    """Packages whose usable stock is below their reorder threshold, worst first."""
    lines, total = InventoryService(session).low_stock(limit, offset)
    return StockPage(total=total, limit=limit, offset=offset, items=[to_out(x) for x in lines])
