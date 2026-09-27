import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from calculation.fefo import InsufficientStockError
from database import get_session
from product import MV_TYPES
from schemas import (
    MovementCreate,
    MovementCreateResponse,
    MovementListItem,
    MovementListResponse,
)
from services.movements import (
    BatchNotFoundError,
    DocumentAlreadyExistsError,
    InsufficientBatchStockError,
    LocationNotFoundError,
    ProductNotFoundError,
    list_movements,
    register_movement,
)

movements_router = APIRouter(prefix="/movements", tags=["movements"])


@movements_router.get("", response_model=MovementListResponse)
def get_movements(
    sku: str | None = Query(default=None, min_length=1, max_length=64),
    location: str | None = Query(default=None, min_length=1, max_length=32),
    movement_type: MV_TYPES | None = Query(default=None, alias="type"),
    date_from: datetime.date | None = Query(default=None),
    date_to: datetime.date | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
):
    if date_from is not None and date_to is not None and date_from > date_to:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "invalid_date_range",
                "date_from": date_from.isoformat(),
                "date_to": date_to.isoformat(),
            },
        )

    rows, total = list_movements(
        session=session,
        sku=sku,
        location_code=location,
        mv_type=movement_type,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        offset=offset,
    )

    items = [
        MovementListItem(
            id=movement.id,
            sku=product_sku,
            location=location_code,
            type=movement.type,
            quantity=movement.quantity,
            document_number=movement.document_number,
            occurred_at=movement.occurred_at,
            created_at=movement.created_at,
        )
        for movement, product_sku, location_code in rows
    ]

    return MovementListResponse(items=items, total=total, limit=limit, offset=offset)


@movements_router.post(
    "",
    status_code=201,
    response_model=MovementCreateResponse,
    responses={
        404: {"description": "Product, location or batch not found"},
        409: {"description": "Document number already exists"},
        422: {"description": "Request validation error or insufficient stock"},
    },
)
def create_movement(body: MovementCreate, session: Session = Depends(get_session)):
    try:
        movement, new_stock = register_movement(
            session=session,
            sku=body.sku,
            location_code=body.location,
            document_number=body.document_number,
            mv_type=body.type,
            quantity=body.quantity,
            operation_date=body.occurred_at,
            batch_number=body.batch_number,
        )
    except ProductNotFoundError as e:
        raise HTTPException(
            status_code=404, detail={"code": "product_not_found", "sku": e.sku}
        ) from e
    except LocationNotFoundError as e:
        raise HTTPException(
            status_code=404,
            detail={"code": "location_not_found", "location_code": e.code},
        ) from e
    except BatchNotFoundError as e:
        raise HTTPException(
            status_code=404,
            detail={"code": "batch_not_found", "batch_number": e.batch_number},
        ) from e
    except DocumentAlreadyExistsError as e:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "document_already_exists",
                "document_number": e.document_number,
            },
        ) from e
    except InsufficientStockError as e:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "insufficient_stock",
                "requested_quantity": str(e.requested_quantity),
                "available_quantity": str(e.available_quantity),
            },
        ) from e
    except InsufficientBatchStockError as e:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "insufficient_batch_stock",
                "batch_id": e.batch_id,
                "requested_quantity": str(e.requested_quantity),
                "available_quantity": str(e.available_quantity),
            },
        ) from e

    return MovementCreateResponse(
        id=movement.id,
        document_number=movement.document_number,
        type=movement.type,
        quantity=movement.quantity,
        occurred_at=movement.occurred_at,
        stock_after=new_stock,
    )
