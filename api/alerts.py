from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from database import get_session
from schemas import AlertItem
from services.alerts import list_alerts

alerts_router = APIRouter(prefix="/alerts", tags=["alerts"])


@alerts_router.get("", response_model=list[AlertItem])
def get_alerts(
    location: str | None = Query(default=None, min_length=1, max_length=32),
    expiry_days: int = Query(default=30, ge=1, le=365),
    inactivity_days: int = Query(default=30, ge=1, le=365),
    session: Session = Depends(get_session),
):
    alerts = list_alerts(
        session=session,
        as_of=date.today(),
        location_code=location,
        expiry_warning_days=expiry_days,
        inactivity_days=inactivity_days,
    )
    return [
        AlertItem(
            type=alert.type,
            level=alert.level,
            sku=alert.sku,
            location=alert.location,
            message=alert.message,
            indicators=alert.indicators,
        )
        for alert in alerts
    ]
