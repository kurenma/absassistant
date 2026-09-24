from product import MV_TYPES
from decimal import Decimal
from collections.abc import Iterable


def calculate_stock(movements: Iterable[tuple[MV_TYPES, Decimal]]) -> Decimal:

    stock = Decimal("0")

    for mv_type, quantity in movements:
        if mv_type in (MV_TYPES.RECEIPT, MV_TYPES.RETURN, MV_TYPES.CORRECTION):
            stock += quantity
        elif mv_type in (MV_TYPES.CONSUME, MV_TYPES.WRITEOFF):
            stock -= quantity

    return stock

def calculate_batch_stock(allocations: Iterable[tuple[MV_TYPES, Decimal, Decimal]]) -> Decimal:

    normalized_movements: list[tuple[MV_TYPES, Decimal]] = []

    for mv_type, mv_quantity, allocated_quantity in allocations:

        signed_quantity = allocated_quantity

        if mv_type == MV_TYPES.CORRECTION and mv_quantity < 0:
            signed_quantity = -allocated_quantity

        normalized_movements.append((mv_type, signed_quantity))

    return calculate_stock(normalized_movements)