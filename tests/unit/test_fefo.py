from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import pytest

from app.calculations.fefo import InsufficientStockError, allocate_fefo


@dataclass(frozen=True)
class BatchState:
    batch_id: int
    expires_at: date
    current_stock: Decimal

    def as_tuple(self) -> tuple[int, date, Decimal]:
        return (self.batch_id, self.expires_at, self.current_stock)


OP_DATE = date(2026, 9, 1)


def test_allocate_fefo_uses_batches_with_earliest_expiration_first():

    batches = [
        BatchState(1, date(2026, 9, 20), Decimal("5")),
        BatchState(2, date(2026, 9, 10), Decimal("2.5")),
        BatchState(3, date(2026, 9, 15), Decimal("4")),
    ]

    assert allocate_fefo(Decimal("4"), OP_DATE, (b.as_tuple() for b in batches)) == [
        (2, Decimal("2.5")),
        (3, Decimal("1.5")),
    ]


def test_allocate_fefo_ignores_expired_batches():

    batches = [
        BatchState(1, date(2025, 12, 31), Decimal("100")),
        BatchState(2, date(2026, 10, 10), Decimal("4")),
    ]

    assert allocate_fefo(Decimal("4"), OP_DATE, (b.as_tuple() for b in batches)) == [
        (2, Decimal("4")),
    ]


def test_allocate_fefo_accepts_batch_expiring_on_operation_date():

    batches = [
        BatchState(1, date(2026, 9, 1), Decimal("4")),
        BatchState(2, date(2026, 9, 1), Decimal("2")),
    ]

    assert allocate_fefo(Decimal("5.5"), OP_DATE, (b.as_tuple() for b in batches)) == [
        (1, Decimal("4")),
        (2, Decimal("1.5")),
    ]


def test_allocate_fefo_ignores_batches_with_zero_stock():

    batches = [
        BatchState(1, date(2026, 10, 1), Decimal("0")),
        BatchState(2, date(2026, 11, 1), Decimal("3.5")),
        BatchState(3, date(2026, 12, 1), Decimal("1.5")),
    ]

    assert allocate_fefo(Decimal("5"), OP_DATE, (b.as_tuple() for b in batches)) == [
        (2, Decimal("3.5")),
        (3, Decimal("1.5")),
    ]


def test_allocate_fefo_uses_batch_id_for_equal_expiration_dates():

    batches = [
        BatchState(2, date(2026, 9, 1), Decimal("4")),
        BatchState(1, date(2026, 9, 1), Decimal("2")),
    ]

    assert allocate_fefo(Decimal("5"), OP_DATE, (b.as_tuple() for b in batches)) == [
        (1, Decimal("2")),
        (2, Decimal("3")),
    ]


def test_allocate_fefo_raises_error_when_stock_is_insufficient():

    batches = [
        BatchState(2, date(2026, 12, 1), Decimal("5")),
        BatchState(1, date(2026, 9, 10), Decimal("2.5")),
    ]

    with pytest.raises(InsufficientStockError) as exc_info:
        allocate_fefo(Decimal("8.5"), OP_DATE, (b.as_tuple() for b in batches))

    assert exc_info.value.requested_quantity == Decimal("8.5")
    assert exc_info.value.available_quantity == Decimal("7.5")
