from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.db.models import MovementType
from app.services import movements as movement_service

OPERATION_DATE = date(2026, 9, 1)


def test_ensure_batch_stock_available_returns_current_stock(monkeypatch):
    session = Mock(name="session")
    mock_get_stock = Mock(return_value=Decimal("7.5"))
    monkeypatch.setattr(movement_service, "get_batch_stock", mock_get_stock)

    result = movement_service.ensure_batch_stock_available(
        session,
        42,
        Decimal("4"),
    )

    assert result == Decimal("7.5")
    mock_get_stock.assert_called_once_with(session, 42)


def test_ensure_batch_stock_available_raises_for_insufficient_stock(monkeypatch):
    session = Mock(name="session")
    mock_get_stock = Mock(return_value=Decimal("7.5"))
    monkeypatch.setattr(movement_service, "get_batch_stock", mock_get_stock)

    with pytest.raises(movement_service.InsufficientBatchStockError) as exc_info:
        movement_service.ensure_batch_stock_available(
            session,
            42,
            Decimal("8.5"),
        )

    assert exc_info.value.batch_id == 42
    assert exc_info.value.available_quantity == Decimal("7.5")
    assert exc_info.value.requested_quantity == Decimal("8.5")
    mock_get_stock.assert_called_once_with(session, 42)


def test_prepare_consume_allocations_uses_fefo_plan(monkeypatch):
    session = Mock(name="session")
    expected_allocations = [
        (2, Decimal("2.5")),
        (3, Decimal("1.5")),
    ]
    mock_plan = Mock(return_value=expected_allocations)
    monkeypatch.setattr(
        movement_service,
        "plan_consume_allocations",
        mock_plan,
    )

    result = movement_service._prepare_allocations(
        session,
        product_id=10,
        location_id=20,
        mv_type=MovementType.CONSUME,
        quantity=Decimal("4"),
        operation_date=OPERATION_DATE,
    )

    assert result == expected_allocations
    mock_plan.assert_called_once_with(
        session,
        10,
        20,
        Decimal("4"),
        OPERATION_DATE,
    )


def test_prepare_receipt_allocates_to_selected_batch(monkeypatch):
    session = Mock(name="session")
    batch = SimpleNamespace(id=42)
    mock_resolve_batch = Mock(return_value=batch)
    monkeypatch.setattr(
        movement_service,
        "resolve_batch",
        mock_resolve_batch,
    )

    result = movement_service._prepare_allocations(
        session,
        product_id=10,
        location_id=20,
        mv_type=MovementType.RECEIPT,
        quantity=Decimal("5"),
        operation_date=OPERATION_DATE,
        batch_number="LOT-1",
    )

    assert result == [(42, Decimal("5"))]
    mock_resolve_batch.assert_called_once_with(session, 10, 20, "LOT-1")


def test_prepare_writeoff_checks_selected_batch_stock(monkeypatch):
    session = Mock(name="session")
    batch = SimpleNamespace(id=42)
    mock_resolve_batch = Mock(return_value=batch)
    mock_ensure_stock = Mock()
    monkeypatch.setattr(
        movement_service,
        "resolve_batch",
        mock_resolve_batch,
    )
    monkeypatch.setattr(
        movement_service,
        "ensure_batch_stock_available",
        mock_ensure_stock,
    )

    result = movement_service._prepare_allocations(
        session,
        product_id=10,
        location_id=20,
        mv_type=MovementType.WRITEOFF,
        quantity=Decimal("3"),
        operation_date=OPERATION_DATE,
        batch_number="LOT-1",
    )

    assert result == [(42, Decimal("3"))]
    mock_ensure_stock.assert_called_once_with(session, 42, Decimal("3"))


def test_prepare_negative_correction_checks_absolute_quantity(monkeypatch):
    session = Mock(name="session")
    batch = SimpleNamespace(id=42)
    mock_resolve_batch = Mock(return_value=batch)
    mock_ensure_stock = Mock()
    monkeypatch.setattr(
        movement_service,
        "resolve_batch",
        mock_resolve_batch,
    )
    monkeypatch.setattr(
        movement_service,
        "ensure_batch_stock_available",
        mock_ensure_stock,
    )

    result = movement_service._prepare_allocations(
        session,
        product_id=10,
        location_id=20,
        mv_type=MovementType.CORRECTION,
        quantity=Decimal("-3"),
        operation_date=OPERATION_DATE,
        batch_number="LOT-1",
    )

    assert result == [(42, Decimal("3"))]
    mock_ensure_stock.assert_called_once_with(session, 42, Decimal("3"))


def test_prepare_positive_correction_does_not_check_stock(monkeypatch):
    session = Mock(name="session")
    batch = SimpleNamespace(id=42)
    mock_resolve_batch = Mock(return_value=batch)
    mock_ensure_stock = Mock()
    monkeypatch.setattr(
        movement_service,
        "resolve_batch",
        mock_resolve_batch,
    )
    monkeypatch.setattr(
        movement_service,
        "ensure_batch_stock_available",
        mock_ensure_stock,
    )

    result = movement_service._prepare_allocations(
        session,
        product_id=10,
        location_id=20,
        mv_type=MovementType.CORRECTION,
        quantity=Decimal("3"),
        operation_date=OPERATION_DATE,
        batch_number="LOT-1",
    )

    assert result == [(42, Decimal("3"))]
    mock_ensure_stock.assert_not_called()


def test_prepare_allocations_requires_batch_number():
    session = Mock(name="session")

    with pytest.raises(ValueError, match="batch_number is required"):
        movement_service._prepare_allocations(
            session,
            product_id=10,
            location_id=20,
            mv_type=MovementType.RECEIPT,
            quantity=Decimal("5"),
            operation_date=OPERATION_DATE,
            batch_number=None,
        )
