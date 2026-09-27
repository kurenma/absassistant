from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest

from app.db.models import Batch, Location, MovementType, Product
from app.services.alerts import list_alerts
from app.services.movements import register_movement

AS_OF = date(2026, 9, 15)


def create_inventory(
    db_session,
    *,
    sku_prefix: str,
    location_code: str,
    lead_time_days: int = 7,
    batch_number: str = "LOT-1",
    expires_at: date = date(2026, 12, 31),
):
    suffix = uuid4().hex[:10]
    product = Product(
        sku=f"{sku_prefix}-{suffix}",
        name=f"Alert product {suffix}",
        unit="kg",
        lead_time_days=lead_time_days,
        package_size=Decimal("1"),
        min_order_quantity=Decimal("1"),
    )
    location = Location(
        code=f"{location_code}-{suffix}",
        name=f"Alert location {suffix}",
    )
    db_session.add_all([product, location])
    db_session.flush()

    batch = Batch(
        batch_number=batch_number,
        product_id=product.id,
        location_id=location.id,
        produced_at=date(2026, 1, 1),
        expires_at=expires_at,
        unit_price=Decimal("10.00"),
    )
    db_session.add(batch)
    db_session.flush()
    return product, location, batch


def add_movement(
    db_session,
    product,
    location,
    *,
    mv_type: MovementType,
    quantity: str,
    occurred_at: date,
    batch_number: str | None = None,
):
    return register_movement(
        session=db_session,
        sku=product.sku,
        location_code=location.code,
        document_number=f"ALERT-{uuid4().hex}",
        mv_type=mv_type,
        quantity=Decimal(quantity),
        operation_date=occurred_at,
        batch_number=batch_number,
    )


@pytest.mark.integration
def test_list_alerts_detects_shortage_expiry_and_inactivity(db_session):
    shortage_product, shortage_location, shortage_batch = create_inventory(
        db_session,
        sku_prefix="SHORTAGE",
        location_code="SHORT",
        lead_time_days=14,
    )
    add_movement(
        db_session,
        shortage_product,
        shortage_location,
        mv_type=MovementType.RECEIPT,
        quantity="10",
        occurred_at=date(2026, 6, 1),
        batch_number=shortage_batch.batch_number,
    )
    add_movement(
        db_session,
        shortage_product,
        shortage_location,
        mv_type=MovementType.CONSUME,
        quantity="9",
        occurred_at=AS_OF,
    )

    critical_product, critical_location, critical_batch = create_inventory(
        db_session,
        sku_prefix="CRITICAL",
        location_code="CRIT",
        lead_time_days=14,
    )
    add_movement(
        db_session,
        critical_product,
        critical_location,
        mv_type=MovementType.RECEIPT,
        quantity="5",
        occurred_at=date(2026, 6, 1),
        batch_number=critical_batch.batch_number,
    )
    add_movement(
        db_session,
        critical_product,
        critical_location,
        mv_type=MovementType.CONSUME,
        quantity="5",
        occurred_at=AS_OF,
    )

    expiry_product, expiry_location, expiry_batch = create_inventory(
        db_session,
        sku_prefix="EXPIRY",
        location_code="EXP",
        expires_at=date(2026, 9, 14),
    )
    add_movement(
        db_session,
        expiry_product,
        expiry_location,
        mv_type=MovementType.RECEIPT,
        quantity="5",
        occurred_at=AS_OF,
        batch_number=expiry_batch.batch_number,
    )

    inactive_product, inactive_location, inactive_batch = create_inventory(
        db_session,
        sku_prefix="INACTIVE",
        location_code="IDLE",
    )
    add_movement(
        db_session,
        inactive_product,
        inactive_location,
        mv_type=MovementType.RECEIPT,
        quantity="3",
        occurred_at=date(2026, 8, 15),
        batch_number=inactive_batch.batch_number,
    )

    alerts = list_alerts(db_session, AS_OF)

    shortage = next(
        alert
        for alert in alerts
        if alert.type == "shortage_risk" and alert.sku == shortage_product.sku
    )
    assert shortage.level == "warning"
    assert shortage.indicators == {
        "current_stock": Decimal("1.000"),
        "avg_daily_consumption": Decimal("0.100"),
        "days_of_stock": Decimal("10"),
        "lead_time_days": 14,
    }

    critical_shortage = next(
        alert
        for alert in alerts
        if alert.type == "shortage_risk" and alert.sku == critical_product.sku
    )
    assert critical_shortage.level == "critical"
    assert critical_shortage.indicators["current_stock"] == Decimal("0.000")

    expiry = next(
        alert
        for alert in alerts
        if alert.type == "expiry" and alert.sku == expiry_product.sku
    )
    assert expiry.level == "critical"
    assert expiry.indicators["quantity"] == Decimal("5.000")
    assert expiry.indicators["days_until_expiry"] == -1

    inactivity = next(
        alert
        for alert in alerts
        if alert.type == "no_movement" and alert.sku == inactive_product.sku
    )
    assert inactivity.level == "warning"
    assert inactivity.indicators["last_movement_at"] == date(2026, 8, 15)


@pytest.mark.integration
def test_list_alerts_respects_location_and_thresholds(db_session):
    product, location, batch = create_inventory(
        db_session,
        sku_prefix="FILTERED",
        location_code="FILTER",
        expires_at=date(2026, 9, 25),
    )
    add_movement(
        db_session,
        product,
        location,
        mv_type=MovementType.RECEIPT,
        quantity="2",
        occurred_at=date(2026, 8, 25),
        batch_number=batch.batch_number,
    )

    excluded = list_alerts(
        db_session,
        AS_OF,
        location_code=location.code,
        expiry_warning_days=5,
        inactivity_days=30,
    )
    included = list_alerts(
        db_session,
        AS_OF,
        location_code=location.code,
        expiry_warning_days=10,
        inactivity_days=20,
    )
    unknown_location = list_alerts(
        db_session,
        AS_OF,
        location_code="UNKNOWN",
    )

    assert excluded == []
    assert {alert.type for alert in included} == {"expiry", "no_movement"}
    assert all(alert.location == location.code for alert in included)
    expiry = next(alert for alert in included if alert.type == "expiry")
    assert expiry.level == "warning"
    assert expiry.indicators["days_until_expiry"] == 10
    assert unknown_location == []


@pytest.mark.integration
def test_list_alerts_ignores_expiring_batch_without_stock(db_session):
    product, location, batch = create_inventory(
        db_session,
        sku_prefix="EMPTY",
        location_code="EMPTY",
        expires_at=date(2026, 9, 20),
    )
    add_movement(
        db_session,
        product,
        location,
        mv_type=MovementType.RECEIPT,
        quantity="2",
        occurred_at=AS_OF,
        batch_number=batch.batch_number,
    )
    add_movement(
        db_session,
        product,
        location,
        mv_type=MovementType.WRITEOFF,
        quantity="2",
        occurred_at=AS_OF,
        batch_number=batch.batch_number,
    )

    alerts = list_alerts(db_session, AS_OF, location_code=location.code)

    assert all(alert.type != "expiry" for alert in alerts)
