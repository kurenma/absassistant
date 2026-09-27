from collections.abc import Iterable
from decimal import Decimal

from app.db.models import MovementType


def calculate_stock(movements: Iterable[tuple[MovementType, Decimal]]) -> Decimal:

    stock = Decimal("0")

    for mv_type, quantity in movements:
        if mv_type in (
            MovementType.RECEIPT,
            MovementType.RETURN,
            MovementType.CORRECTION,
        ):
            stock += quantity
        elif mv_type in (MovementType.CONSUME, MovementType.WRITEOFF):
            stock -= quantity

    return stock


def calculate_batch_stock(
    allocations: Iterable[tuple[MovementType, Decimal, Decimal]],
) -> Decimal:

    normalized_movements: list[tuple[MovementType, Decimal]] = []

    for mv_type, mv_quantity, allocated_quantity in allocations:
        signed_quantity = allocated_quantity

        if mv_type == MovementType.CORRECTION and mv_quantity < 0:
            signed_quantity = -allocated_quantity

        normalized_movements.append((mv_type, signed_quantity))

    return calculate_stock(normalized_movements)
