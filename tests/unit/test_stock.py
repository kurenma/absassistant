from decimal import Decimal

from app.calculations.stock import calculate_batch_stock, calculate_stock
from app.db.models import MovementType


def test_calculate_stock_returns_zero_for_empty_movements():
    assert calculate_stock([]) == Decimal("0")


def test_calculate_stock_applies_all_movement_types():
    operations = [
        (MovementType.RECEIPT, Decimal("10")),
        (MovementType.CONSUME, Decimal("2.5")),
        (MovementType.WRITEOFF, Decimal("1")),
        (MovementType.RETURN, Decimal("0.5")),
        (MovementType.CORRECTION, Decimal("-2")),
    ]
    assert calculate_stock(operations) == Decimal("5")


def test_calculate_batch_stock_uses_allocated_quantity():
    operations = [
        (MovementType.RECEIPT, Decimal("10"), Decimal("6")),
        (MovementType.CONSUME, Decimal("4"), Decimal("1.5")),
    ]
    assert calculate_batch_stock(operations) == Decimal("4.5")


def test_calculate_batch_stock_applies_negative_correction():
    operations = [
        (MovementType.RECEIPT, Decimal("10"), Decimal("10")),
        (MovementType.CORRECTION, Decimal("-3"), Decimal("2")),
    ]
    assert calculate_batch_stock(operations) == Decimal("8")
