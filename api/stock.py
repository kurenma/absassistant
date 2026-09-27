from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_session
from schemas import (
    StockBatchItem,
    StockDetailResponse,
    StockListItem,
    StockLocationDetail,
)
from services.movements import ProductNotFoundError
from services.stock import get_stock_detail, list_stock

stock_router = APIRouter(prefix="/stock", tags=["stock"])


@stock_router.get("", response_model=list[StockListItem])
def get_stock(session: Session = Depends(get_session)):

    summaries = list_stock(session=session, as_of=date.today())

    return [
        StockListItem(
            sku=s.sku,
            name=s.name,
            unit=s.unit,
            location=s.location,
            current_stock=s.current_stock,
            avg_daily_consumption=s.avg_daily_consumption,
            days_of_stock=s.days_of_stock,
            nearest_expiry=s.nearest_expiry,
        )
        for s in summaries
    ]


@stock_router.get(
    "/{sku}",
    response_model=StockDetailResponse,
    responses={404: {"description": "Product not found"}},
)
def get_stock_by_sku(sku: str, session: Session = Depends(get_session)):
    try:
        detail = get_stock_detail(
            session=session,
            sku=sku,
            as_of=date.today(),
        )
    except ProductNotFoundError as error:
        raise HTTPException(
            status_code=404,
            detail={"code": "product_not_found", "sku": error.sku},
        ) from error

    return StockDetailResponse(
        sku=detail.sku,
        name=detail.name,
        unit=detail.unit,
        locations=[
            StockLocationDetail(
                location=location.location,
                current_stock=location.current_stock,
                batches=[
                    StockBatchItem(
                        batch_number=batch.batch_number,
                        quantity=batch.quantity,
                        produced_at=batch.produced_at,
                        expires_at=batch.expires_at,
                        unit_price=batch.unit_price,
                        receipt_documents=batch.receipt_documents,
                    )
                    for batch in location.batches
                ],
            )
            for location in detail.locations
        ],
    )
