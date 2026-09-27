import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ForecastRequest(BaseModel):
    sku: str = Field(min_length=1, max_length=64)
    location: str = Field(min_length=1, max_length=32)
    horizon_days: int | None = Field(default=None, gt=0)
    horizon_months: int | None = Field(default=None, gt=0)
    safety_stock_days: int = Field(ge=0)

    model_config = ConfigDict(str_strip_whitespace=True)

    @model_validator(mode="after")
    def validate_horizon(self):
        if (self.horizon_days is None) == (self.horizon_months is None):
            raise ValueError(
                "Exactly one of horizon_days or horizon_months must be provided"
            )
        return self


class ForecastPeriod(BaseModel):
    from_: datetime.date = Field(alias="from")
    to: datetime.date
    days: int

    model_config = ConfigDict(populate_by_name=True)


class ForecastExplanation(BaseModel):
    data_used: list[str]
    formulas: list[str]
    assumptions: list[str]
    as_of: datetime.date


class ForecastWarning(BaseModel):
    level: Literal["warning"]
    message: str


class ForecastResponse(BaseModel):
    sku: str
    name: str
    unit: str
    location: str
    period: ForecastPeriod
    avg_daily_consumption: Decimal
    forecast_demand: Decimal
    current_stock: Decimal
    incoming_qty: Decimal
    safety_stock: Decimal
    reorder_point: Decimal
    recommended_purchase_qty: Decimal
    unit_price: Decimal | None
    estimated_cost: Decimal | None
    recommended_order_date: datetime.date | None
    stockout_date: datetime.date | None
    explanation: ForecastExplanation
    warnings: list[ForecastWarning]
