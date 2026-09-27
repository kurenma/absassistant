from fastapi import APIRouter

from app.api.routes.alerts import alerts_router
from app.api.routes.forecast import forecast_router
from app.api.routes.movements import movements_router
from app.api.routes.stock import stock_router

api_router = APIRouter(prefix="/api")
api_router.include_router(movements_router)
api_router.include_router(stock_router)
api_router.include_router(forecast_router)
api_router.include_router(alerts_router)
