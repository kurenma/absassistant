import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.db.models import MovementType


class MovementCreate(BaseModel):
    sku: str = Field(min_length=1, max_length=64)
    location: str = Field(min_length=1, max_length=32)
    type: MovementType
    quantity: Decimal = Field(max_digits=14, decimal_places=3)
    batch_number: str | None = Field(default=None, min_length=1, max_length=64)
    document_number: str = Field(min_length=1, max_length=128)
    occurred_at: datetime.date

    model_config = ConfigDict(str_strip_whitespace=True)

    @model_validator(mode="after")
    def validate_quantity(self):
        if self.type == MovementType.CORRECTION and self.quantity == 0:
            raise ValueError("The quantity for 'correction' must not be equal to zero.")
        if self.type != MovementType.CORRECTION and self.quantity <= 0:
            raise ValueError(
                "The quantity for this operation must be greater than zero."
            )
        return self

    @model_validator(mode="after")
    def validate_batch_number(self):
        types_requiring_batch = {
            MovementType.RECEIPT,
            MovementType.WRITEOFF,
            MovementType.RETURN,
            MovementType.CORRECTION,
        }

        if self.type in types_requiring_batch and self.batch_number is None:
            raise ValueError("The batch_number cannot be None")
        if self.type == MovementType.CONSUME and self.batch_number is not None:
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
    type: MovementType
    quantity: Decimal
    occurred_at: datetime.date
    stock_after: Decimal


class MovementListItem(BaseModel):
    id: int
    sku: str
    location: str
    type: MovementType
    quantity: Decimal
    document_number: str
    occurred_at: datetime.date
    created_at: datetime.datetime


class MovementListResponse(BaseModel):
    items: list[MovementListItem]
    total: int
    limit: int
    offset: int
