from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from calculation.fefo import InsufficientStockError
from database import get_session
from schemas import MovementCreate, MovementCreateResponse
from services.movements import (
    BatchNotFoundError,
    DocumentAlreadyExistsError,
    InsufficientBatchStockError,
    LocationNotFoundError,
    ProductNotFoundError,
    register_movement,
)

router = APIRouter(prefix="/movements", tags=["movements"])


@router.post(
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
