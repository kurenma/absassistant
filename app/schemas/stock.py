import datetime
from decimal import Decimal

from pydantic import BaseModel


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
