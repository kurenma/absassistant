import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel

AlertIndicatorValue = str | int | Decimal | datetime.date | None


class AlertItem(BaseModel):
    type: Literal["shortage_risk", "expiry", "no_movement"]
    level: Literal["warning", "critical"]
    sku: str
    location: str
    message: str
    indicators: dict[str, AlertIndicatorValue]
