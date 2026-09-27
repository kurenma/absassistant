from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest

from app.db.models import (
    Batch,
    Location,
    MovementType,
    Product,
    PurchaseOrder,
    SupplyStatus,
)
from app.services.forecast import build_forecast
from app.services.movements import register_movement

AS_OF = date(2026, 9, 15)


def create_forecast_inventory(db_session):
    suffix = uuid4().hex[:10]
    product = Product(
        sku=f"FORECAST-{suffix}",
        name=f"Forecast product {suffix}",
        unit="kg",
        lead_time_days=7,
        package_size=Decimal("10"),
        min_order_quantity=Decimal("20"),
    )
    location = Location(
        code=f"FC-{suffix}",
        name=f"Forecast location {suffix}",
    )
    db_session.add_all([product, location])
    db_session.flush()
    batch = Batch(
        batch_number=f"LOT-{suffix}",
        product_id=product.id,
        location_id=location.id,
        produced_at=date(2026, 1, 1),
        expires_at=date(2026, 12, 31),
        unit_price=Decimal("12.34"),
    )
    db_session.add(batch)
    db_session.flush()
    return product, location, batch


def add_order(
    db_session,
    product,
    location,
    quantity,
    expected_at,
    status,
):
    order = PurchaseOrder(
        product_id=product.id,
        location_id=location.id,
        document_number=f"PO-{uuid4().hex}",
        quantity=Decimal(quantity),
        unit_price=Decimal("11.00"),
        expected_at=expected_at,
        status=status,
    )
    db_session.add(order)
    db_session.flush()
    return order


@pytest.mark.integration
def test_build_forecast_uses_stock_orders_price_and_supplier_terms(db_session):
    product, location, batch = create_forecast_inventory(db_session)
    register_movement(
        session=db_session,
        sku=product.sku,
        location_code=location.code,
        document_number=f"RECEIPT-{uuid4().hex}",
        mv_type=MovementType.RECEIPT,
        quantity=Decimal("10"),
        operation_date=date(2026, 6, 1),
        batch_number=batch.batch_number,
    )
    register_movement(
        session=db_session,
        sku=product.sku,
        location_code=location.code,
        document_number=f"CONSUME-{uuid4().hex}",
        mv_type=MovementType.CONSUME,
        quantity=Decimal("9"),
        operation_date=AS_OF,
    )

    add_order(
        db_session,
        product,
        location,
        "1",
        date(2026, 9, 1),
        SupplyStatus.IN_TRANSIT,
    )
    add_order(
        db_session,
        product,
        location,
        "1",
        date(2026, 10, 1),
        SupplyStatus.IN_TRANSIT,
    )
    add_order(
        db_session,
        product,
        location,
        "10",
        date(2026, 10, 20),
        SupplyStatus.IN_TRANSIT,
    )
    add_order(
        db_session,
        product,
        location,
        "20",
        date(2026, 10, 1),
        SupplyStatus.CANCELLED,
    )
    add_order(
        db_session,
        product,
        location,
        "20",
        date(2026, 10, 1),
        SupplyStatus.RECEIVED,
    )

    result = build_forecast(
        session=db_session,
        sku=product.sku,
        location_code=location.code,
        horizon_days=30,
        horizon_months=None,
        safety_stock_days=5,
        as_of=AS_OF,
    )

    metrics = result.metrics
    assert metrics.period_from == AS_OF
    assert metrics.period_to == date(2026, 10, 14)
    assert metrics.average_daily_consumption == Decimal("0.100")
    assert metrics.current_stock == Decimal("1.000")
    assert metrics.incoming_quantity == Decimal("2.000")
    assert metrics.forecast_demand == Decimal("3.000")
    assert metrics.safety_stock == Decimal("0.500")
    assert metrics.reorder_point == Decimal("1.200")
    assert metrics.recommended_purchase_quantity == Decimal("20.000")
    assert metrics.unit_price == Decimal("12.34")
    assert metrics.estimated_cost == Decimal("246.80")
    assert metrics.recommended_order_date == date(2026, 10, 3)
    assert metrics.stockout_date == date(2026, 10, 15)
    assert [warning.message for warning in result.warnings] == [
        "Current stock is below the reorder point."
    ]


@pytest.mark.integration
def test_build_forecast_documents_month_assumption(db_session):
    product, location, batch = create_forecast_inventory(db_session)
    register_movement(
        session=db_session,
        sku=product.sku,
        location_code=location.code,
        document_number=f"RECEIPT-{uuid4().hex}",
        mv_type=MovementType.RECEIPT,
        quantity=Decimal("1"),
        operation_date=AS_OF,
        batch_number=batch.batch_number,
    )

    result = build_forecast(
        session=db_session,
        sku=product.sku,
        location_code=location.code,
        horizon_days=None,
        horizon_months=2,
        safety_stock_days=0,
        as_of=AS_OF,
    )

    assert result.metrics.period_days == 60
    assert "One month is treated as 30 days." in result.explanation.assumptions
