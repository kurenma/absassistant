import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from product import MV_TYPES


class MovementCreate(BaseModel):
    sku: str = Field(min_length=1, max_length=64)
    location: str = Field(min_length=1, max_length=32)
    type: MV_TYPES
    quantity: Decimal = Field(max_digits=14, decimal_places=3)
    batch_number: str | None = Field(default=None, min_length=1, max_length=64)
    document_number: str = Field(min_length=1, max_length=128)
    occurred_at: datetime.date

    model_config = ConfigDict(str_strip_whitespace=True)

    @model_validator(mode="after")
    def validate_quantity(self):

        if self.type == MV_TYPES.CORRECTION and self.quantity == 0:
            raise ValueError("The quantity for 'correction' must not be equal to zero.")
        elif self.type != MV_TYPES.CORRECTION and self.quantity <= 0:
            raise ValueError(
                "The quantity for this operation must be greater than zero."
            )

        return self

    @model_validator(mode="after")
    def validate_batch_number(self):

        types_requiring_batch = {
            MV_TYPES.RECEIPT,
            MV_TYPES.WRITEOFF,
            MV_TYPES.RETURN,
            MV_TYPES.CORRECTION,
        }

        if self.type in types_requiring_batch and self.batch_number is None:
            raise ValueError("The batch_number cannot be None")

        if self.type == MV_TYPES.CONSUME and self.batch_number is not None:
            raise ValueError("The batch_number for operation 'consume' must be None")

        return self

    @field_validator("occurred_at")
    @classmethod
    def occurred_at_not_in_future(cls, value: datetime.date):

        if value > datetime.date.today():
            raise ValueError("occurred_at cannot be in the future")

        return value


class MovementCreateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    document_number: str
    type: MV_TYPES
    quantity: Decimal
    occurred_at: datetime.date
    stock_after: Decimal


class MovementListItem(BaseModel):
    id: int
    sku: str
    location: str
    type: MV_TYPES
    quantity: Decimal
    document_number: str
    occurred_at: datetime.date
    created_at: datetime.datetime


class MovementListResponse(BaseModel):
    items: list[MovementListItem]
    total: int
    limit: int
    offset: int


class StockListItem(BaseModel):
    sku: str
    name: str
    unit: str
    location: str
    current_stock: Decimal
    avg_daily_consumption: Decimal
    days_of_stock: Decimal | None
    nearest_expiry: datetime.date | None


class StockBatchItem(BaseModel):
    batch_number: str
    quantity: Decimal
    produced_at: datetime.date
    expires_at: datetime.date
    unit_price: Decimal
    receipt_documents: list[str]


class StockLocationDetail(BaseModel):
    location: str
    current_stock: Decimal
    batches: list[StockBatchItem]


class StockDetailResponse(BaseModel):
    sku: str
    name: str
    unit: str
    locations: list[StockLocationDetail]


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
