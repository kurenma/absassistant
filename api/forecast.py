from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_session
from schemas import (
    ForecastExplanation,
    ForecastPeriod,
    ForecastRequest,
    ForecastResponse,
    ForecastWarning,
)
from services.forecast import build_forecast
from services.movements import LocationNotFoundError, ProductNotFoundError

forecast_router = APIRouter(prefix="/forecast", tags=["forecast"])


@forecast_router.post(
    "",
    response_model=ForecastResponse,
    responses={404: {"description": "Product or location not found"}},
)
def create_forecast(
    body: ForecastRequest,
    session: Session = Depends(get_session),
):
    try:
        result = build_forecast(
            session=session,
            sku=body.sku,
            location_code=body.location,
            horizon_days=body.horizon_days,
            horizon_months=body.horizon_months,
            safety_stock_days=body.safety_stock_days,
            as_of=date.today(),
        )
    except ProductNotFoundError as error:
        raise HTTPException(
            status_code=404,
            detail={"code": "product_not_found", "sku": error.sku},
        ) from error
    except LocationNotFoundError as error:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "location_not_found",
                "location_code": error.code,
            },
        ) from error

    metrics = result.metrics
    return ForecastResponse(
        sku=result.sku,
        name=result.name,
        unit=result.unit,
        location=result.location,
        period=ForecastPeriod(
            from_=metrics.period_from,
            to=metrics.period_to,
            days=metrics.period_days,
        ),
        avg_daily_consumption=metrics.average_daily_consumption,
        forecast_demand=metrics.forecast_demand,
        current_stock=metrics.current_stock,
        incoming_qty=metrics.incoming_quantity,
        safety_stock=metrics.safety_stock,
        reorder_point=metrics.reorder_point,
        recommended_purchase_qty=metrics.recommended_purchase_quantity,
        unit_price=metrics.unit_price,
        estimated_cost=metrics.estimated_cost,
        recommended_order_date=metrics.recommended_order_date,
        stockout_date=metrics.stockout_date,
        explanation=ForecastExplanation(
            data_used=result.explanation.data_used,
            formulas=result.explanation.formulas,
            assumptions=result.explanation.assumptions,
            as_of=result.explanation.as_of,
        ),
        warnings=[
            ForecastWarning(level="warning", message=warning.message)
            for warning in result.warnings
        ],
    )
