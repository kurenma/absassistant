from fastapi import FastAPI

from api.alerts import alerts_router
from api.forecast import forecast_router
from api.movements import movements_router
from api.stock import stock_router

app = FastAPI()
app.include_router(movements_router, prefix="/api")
app.include_router(stock_router, prefix="/api")
app.include_router(forecast_router, prefix="/api")
app.include_router(alerts_router, prefix="/api")


@app.get("/")
async def root():
    return {"message": "Hello, world!"}
