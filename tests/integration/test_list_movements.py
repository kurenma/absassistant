from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from product import MV_TYPES, Batch, Location, Product
from services.movements import list_movements, register_movement


def create_inventory(session: Session) -> tuple[Product, Location, Batch]:
    suffix = uuid4().hex[:12]
    product = Product(
        sku=f"LIST-SKU-{suffix}",
        name=f"List test product {suffix}",
        unit="kg",
        lead_time_days=7,
        package_size=Decimal("1"),
        min_order_quantity=Decimal("1"),
    )
    location = Location(
        code=f"LIST-{suffix}",
        name=f"List test location {suffix}",
    )
    session.add_all([product, location])
    session.flush()

    batch = Batch(
        batch_number=f"LOT-{suffix}",
        product_id=product.id,
        location_id=location.id,
        produced_at=date(2026, 8, 1),
        expires_at=date(2026, 12, 31),
        unit_price=Decimal("100.00"),
    )
    session.add(batch)
    session.flush()

    return product, location, batch


def add_movement(
    session: Session,
    product: Product,
    location: Location,
    batch: Batch,
    document_prefix: str,
    mv_type: MV_TYPES,
    quantity: Decimal,
    operation_date: date,
):
    batch_number = None if mv_type == MV_TYPES.CONSUME else batch.batch_number
    return register_movement(
        session=session,
        sku=product.sku,
        location_code=location.code,
        document_number=f"{document_prefix}-{uuid4().hex}",
        mv_type=mv_type,
        quantity=quantity,
        operation_date=operation_date,
        batch_number=batch_number,
    )[0]


@pytest.mark.integration
def test_list_movements_orders_by_date_and_id_descending(db_session):
    product, location, batch = create_inventory(db_session)
    first = add_movement(
        db_session,
        product,
        location,
        batch,
        "FIRST",
        MV_TYPES.RECEIPT,
        Decimal("2"),
        date(2026, 9, 1),
    )
    second = add_movement(
        db_session,
        product,
        location,
        batch,
        "SECOND",
        MV_TYPES.RETURN,
        Decimal("1"),
        date(2026, 9, 1),
    )
    third = add_movement(
        db_session,
        product,
        location,
        batch,
        "THIRD",
        MV_TYPES.RECEIPT,
        Decimal("3"),
        date(2026, 9, 2),
    )

    rows, total = list_movements(
        db_session,
        sku=product.sku,
        location_code=location.code,
    )

    assert total == 3
    assert [movement.id for movement, _, _ in rows] == [
        third.id,
        second.id,
        first.id,
    ]
    assert all(sku == product.sku for _, sku, _ in rows)
    assert all(code == location.code for _, _, code in rows)


@pytest.mark.integration
def test_list_movements_combines_all_filters(db_session):
    product, location, batch = create_inventory(db_session)
    other_product, other_location, other_batch = create_inventory(db_session)
    add_movement(
        db_session,
        product,
        location,
        batch,
        "OUTSIDE-DATE",
        MV_TYPES.RETURN,
        Decimal("1"),
        date(2026, 9, 1),
    )
    expected = add_movement(
        db_session,
        product,
        location,
        batch,
        "EXPECTED",
        MV_TYPES.RETURN,
        Decimal("2"),
        date(2026, 9, 10),
    )
    add_movement(
        db_session,
        product,
        location,
        batch,
        "WRONG-TYPE",
        MV_TYPES.RECEIPT,
        Decimal("3"),
        date(2026, 9, 10),
    )
    add_movement(
        db_session,
        other_product,
        other_location,
        other_batch,
        "WRONG-INVENTORY",
        MV_TYPES.RETURN,
        Decimal("4"),
        date(2026, 9, 10),
    )

    rows, total = list_movements(
        db_session,
        sku=product.sku,
        location_code=location.code,
        mv_type=MV_TYPES.RETURN,
        date_from=date(2026, 9, 5),
        date_to=date(2026, 9, 15),
    )

    assert total == 1
    assert len(rows) == 1
    movement, sku, location_code = rows[0]
    assert movement.id == expected.id
    assert sku == product.sku
    assert location_code == location.code


@pytest.mark.integration
def test_list_movements_paginates_without_changing_total(db_session):
    product, location, batch = create_inventory(db_session)
    movements = [
        add_movement(
            db_session,
            product,
            location,
            batch,
            f"PAGE-{index}",
            MV_TYPES.RECEIPT,
            Decimal("1"),
            date(2026, 9, index),
        )
        for index in range(1, 4)
    ]

    rows, total = list_movements(
        db_session,
        sku=product.sku,
        location_code=location.code,
        limit=1,
        offset=1,
    )

    assert total == 3
    assert len(rows) == 1
    assert rows[0][0].id == movements[1].id


@pytest.mark.integration
def test_list_movements_returns_empty_list_for_unknown_sku(db_session):
    rows, total = list_movements(db_session, sku=f"UNKNOWN-{uuid4().hex}")

    assert rows == []
    assert total == 0
