import datetime
from collections.abc import Iterable
from decimal import Decimal


class InsufficientStockError(Exception):
    def __init__(
        self,
        requested_quantity: Decimal,
        available_quantity: Decimal,
    ) -> None:
        self.requested_quantity = requested_quantity
        self.available_quantity = available_quantity
        super().__init__(
            f"Requested {requested_quantity}, "
            f"but only {available_quantity} is available"
        )


def allocate_fefo(
    requested_quantity: Decimal,
    operation_date: datetime.date,
    batches: Iterable[tuple[int, datetime.date, Decimal]],
) -> list[tuple[int, Decimal]]:

    valid = [
        (batch_id, expires_at, current_stock)
        for batch_id, expires_at, current_stock in batches
        if expires_at >= operation_date and current_stock > 0
    ]

    available_quantity = sum(
        (stock for _, _, stock in valid),
        start=Decimal("0"),
    )

    if available_quantity < requested_quantity:
        raise InsufficientStockError(requested_quantity, available_quantity)

    valid.sort(key=lambda item: (item[1], item[0]))

    allocations: list[tuple[int, Decimal]] = []
    remaining = requested_quantity

    for batch_id, _, current_stock in valid:
        if remaining <= 0:
            break
        take = min(remaining, current_stock)
        allocations.append((batch_id, take))
        remaining -= take

    return allocations
