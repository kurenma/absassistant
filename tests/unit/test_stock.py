from decimal import Decimal

from calculation.stock import calculate_batch_stock, calculate_stock
from product import MV_TYPES


def test_calculate_stock_returns_zero_for_empty_movements():
    assert calculate_stock([]) == Decimal("0")


def test_calculate_stock_applies_all_movement_types():
    operations = [
        (MV_TYPES.RECEIPT, Decimal("10")),
        (MV_TYPES.CONSUME, Decimal("2.5")),
        (MV_TYPES.WRITEOFF, Decimal("1")),
        (MV_TYPES.RETURN, Decimal("0.5")),
        (MV_TYPES.CORRECTION, Decimal("-2")),
    ]
    assert calculate_stock(operations) == Decimal("5")


def test_calculate_batch_stock_uses_allocated_quantity():
    operations = [
        (MV_TYPES.RECEIPT, Decimal("10"), Decimal("6")),
        (MV_TYPES.CONSUME, Decimal("4"), Decimal("1.5")),
    ]
    assert calculate_batch_stock(operations) == Decimal("4.5")


def test_calculate_batch_stock_applies_negative_correction():
    operations = [
        (MV_TYPES.RECEIPT, Decimal("10"), Decimal("10")),
        (MV_TYPES.CORRECTION, Decimal("-3"), Decimal("2")),
    ]
    assert calculate_batch_stock(operations) == Decimal("8")
