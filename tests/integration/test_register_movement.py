from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from calculation.fefo import InsufficientStockError
from product import (
    MV_TYPES,
    Batch,
    Location,
    Movement,
    MovementAllocation,
    Product,
)
from services.movements import (
    DocumentAlreadyExistsError,
    InsufficientBatchStockError,
    get_batch_stock,
    get_current_stock,
    register_movement,
)

OPERATION_DATE = date(2026, 9, 1)


def create_inventory(
    session: Session,
    batch_specs: list[tuple[str, date]],
) -> tuple[Product, Location, dict[str, Batch]]:
    suffix = uuid4().hex[:12]
    product = Product(
        sku=f"TEST-SKU-{suffix}",
        name=f"Test product {suffix}",
        unit="kg",
    )
    location = Location(
        code=f"TEST-{suffix}",
        name=f"Test location {suffix}",
    )
    session.add_all([product, location])
    session.flush()

    batches = {
        batch_number: Batch(
            batch_number=batch_number,
            product_id=product.id,
            location_id=location.id,
            produced_at=date(2026, 8, 1),
            expires_at=expires_at,
            unit_price=Decimal("100.00"),
        )
        for batch_number, expires_at in batch_specs
    }
    session.add_all(batches.values())
    session.flush()

    return product, location, batches


def document_number(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex}"


def register_receipt(
    session: Session,
    product: Product,
    location: Location,
    batch_number: str,
    quantity: Decimal,
) -> tuple[Movement, Decimal]:
    return register_movement(
        session=session,
        sku=product.sku,
        location_code=location.code,
        document_number=document_number("RECEIPT"),
        mv_type=MV_TYPES.RECEIPT,
        quantity=quantity,
        operation_date=OPERATION_DATE,
        batch_number=batch_number,
    )


@pytest.mark.integration
def test_register_receipt_persists_movement_and_allocation(db_session):
    product, location, batches = create_inventory(
        db_session,
        [("LOT-1", date(2026, 10, 1))],
    )

    movement, new_stock = register_receipt(
        db_session,
        product,
        location,
        "LOT-1",
        Decimal("10"),
    )

    allocation = db_session.scalar(
        select(MovementAllocation).where(MovementAllocation.movement_id == movement.id)
    )

    assert movement.id is not None
    assert movement.product_id == product.id
    assert movement.location_id == location.id
    assert new_stock == Decimal("10.000")
    assert allocation is not None
    assert allocation.batch_id == batches["LOT-1"].id
    assert allocation.quantity == Decimal("10.000")


@pytest.mark.integration
def test_register_consume_allocates_by_fefo(db_session):
    product, location, batches = create_inventory(
        db_session,
        [
            ("LOT-A", date(2026, 9, 20)),
            ("LOT-B", date(2026, 9, 10)),
            ("LOT-C", date(2026, 9, 15)),
        ],
    )
    register_receipt(db_session, product, location, "LOT-A", Decimal("5"))
    register_receipt(db_session, product, location, "LOT-B", Decimal("2.5"))
    register_receipt(db_session, product, location, "LOT-C", Decimal("4"))

    movement, new_stock = register_movement(
        session=db_session,
        sku=product.sku,
        location_code=location.code,
        document_number=document_number("CONSUME"),
        mv_type=MV_TYPES.CONSUME,
        quantity=Decimal("4"),
        operation_date=OPERATION_DATE,
    )

    allocations = db_session.scalars(
        select(MovementAllocation).where(MovementAllocation.movement_id == movement.id)
    ).all()
    quantities_by_batch = {
        allocation.batch_id: allocation.quantity for allocation in allocations
    }

    assert quantities_by_batch == {
        batches["LOT-B"].id: Decimal("2.500"),
        batches["LOT-C"].id: Decimal("1.500"),
    }
    assert new_stock == Decimal("7.500")


@pytest.mark.integration
def test_insufficient_consume_rolls_back_without_changing_stock(db_session):
    product, location, _ = create_inventory(
        db_session,
        [
            ("LOT-B", date(2026, 9, 10)),
            ("LOT-C", date(2026, 9, 15)),
        ],
    )
    register_receipt(db_session, product, location, "LOT-B", Decimal("2.5"))
    register_receipt(db_session, product, location, "LOT-C", Decimal("5"))
    failed_document = document_number("CONSUME-FAILED")

    with pytest.raises(InsufficientStockError) as exc_info:
        register_movement(
            session=db_session,
            sku=product.sku,
            location_code=location.code,
            document_number=failed_document,
            mv_type=MV_TYPES.CONSUME,
            quantity=Decimal("8.5"),
            operation_date=OPERATION_DATE,
        )

    failed_movement = db_session.scalar(
        select(Movement).where(Movement.document_number == failed_document)
    )

    assert exc_info.value.requested_quantity == Decimal("8.5")
    assert exc_info.value.available_quantity == Decimal("7.500")
    assert failed_movement is None
    assert get_current_stock(db_session, product.id, location.id) == Decimal("7.500")


@pytest.mark.integration
def test_insufficient_writeoff_from_batch_rolls_back(db_session):
    product, location, batches = create_inventory(
        db_session,
        [
            ("LOT-SMALL", date(2026, 9, 10)),
            ("LOT-LARGE", date(2026, 9, 15)),
        ],
    )
    register_receipt(db_session, product, location, "LOT-SMALL", Decimal("1"))
    register_receipt(db_session, product, location, "LOT-LARGE", Decimal("10"))
    failed_document = document_number("WRITEOFF-FAILED")

    with pytest.raises(InsufficientBatchStockError) as exc_info:
        register_movement(
            session=db_session,
            sku=product.sku,
            location_code=location.code,
            document_number=failed_document,
            mv_type=MV_TYPES.WRITEOFF,
            quantity=Decimal("2"),
            operation_date=OPERATION_DATE,
            batch_number="LOT-SMALL",
        )

    assert exc_info.value.batch_id == batches["LOT-SMALL"].id
    assert exc_info.value.available_quantity == Decimal("1.000")
    assert get_batch_stock(db_session, batches["LOT-SMALL"].id) == Decimal("1.000")
    assert get_current_stock(db_session, product.id, location.id) == Decimal("11.000")
    assert (
        db_session.scalar(
            select(Movement).where(Movement.document_number == failed_document)
        )
        is None
    )


@pytest.mark.integration
def test_negative_correction_stores_positive_allocation(db_session):
    product, location, batches = create_inventory(
        db_session,
        [("LOT-1", date(2026, 10, 1))],
    )
    register_receipt(db_session, product, location, "LOT-1", Decimal("10"))

    movement, new_stock = register_movement(
        session=db_session,
        sku=product.sku,
        location_code=location.code,
        document_number=document_number("CORRECTION"),
        mv_type=MV_TYPES.CORRECTION,
        quantity=Decimal("-3"),
        operation_date=OPERATION_DATE,
        batch_number="LOT-1",
    )
    allocation = db_session.scalar(
        select(MovementAllocation).where(MovementAllocation.movement_id == movement.id)
    )

    assert movement.quantity == Decimal("-3.000")
    assert allocation is not None
    assert allocation.quantity == Decimal("3.000")
    assert new_stock == Decimal("7.000")
    assert get_batch_stock(db_session, batches["LOT-1"].id) == Decimal("7.000")


@pytest.mark.integration
def test_duplicate_document_rolls_back_second_movement(db_session):
    product, location, _ = create_inventory(
        db_session,
        [("LOT-1", date(2026, 10, 1))],
    )
    duplicate_document = document_number("DUPLICATE")
    register_movement(
        session=db_session,
        sku=product.sku,
        location_code=location.code,
        document_number=duplicate_document,
        mv_type=MV_TYPES.RECEIPT,
        quantity=Decimal("5"),
        operation_date=OPERATION_DATE,
        batch_number="LOT-1",
    )

    with pytest.raises(DocumentAlreadyExistsError):
        register_movement(
            session=db_session,
            sku=product.sku,
            location_code=location.code,
            document_number=duplicate_document,
            mv_type=MV_TYPES.RETURN,
            quantity=Decimal("2"),
            operation_date=OPERATION_DATE,
            batch_number="LOT-1",
        )

    movements = db_session.scalars(
        select(Movement).where(Movement.document_number == duplicate_document)
    ).all()

    assert len(movements) == 1
    assert movements[0].type == MV_TYPES.RECEIPT
    assert get_current_stock(db_session, product.id, location.id) == Decimal("5.000")
