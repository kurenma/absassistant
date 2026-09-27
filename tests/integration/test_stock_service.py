from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from product import MV_TYPES, Batch, Location, Product
from services.movements import ProductNotFoundError, register_movement
from services.stock import get_stock_detail, list_stock

AS_OF = date(2026, 9, 15)


def create_product_and_location(
    session: Session,
    sku_prefix: str = "STOCK",
    location_prefix: str = "LOC",
) -> tuple[Product, Location]:
    suffix = uuid4().hex[:10]
    product = Product(
        sku=f"{sku_prefix}-{suffix}",
        name=f"Stock test product {suffix}",
        unit="kg",
    )
    location = Location(
        code=f"{location_prefix}-{suffix}",
        name=f"Stock test location {suffix}",
    )
    session.add_all([product, location])
    session.flush()
    return product, location


def create_batch(
    session: Session,
    product: Product,
    location: Location,
    batch_number: str,
    expires_at: date,
) -> Batch:
    batch = Batch(
        batch_number=batch_number,
        product_id=product.id,
        location_id=location.id,
        produced_at=date(2026, 1, 1),
        expires_at=expires_at,
        unit_price=Decimal("100.00"),
    )
    session.add(batch)
    session.flush()
    return batch


def add_movement(
    session: Session,
    product: Product,
    location: Location,
    mv_type: MV_TYPES,
    quantity: Decimal,
    operation_date: date,
    batch_number: str | None = None,
):
    return register_movement(
        session=session,
        sku=product.sku,
        location_code=location.code,
        document_number=f"STOCK-{uuid4().hex}",
        mv_type=mv_type,
        quantity=quantity,
        operation_date=operation_date,
        batch_number=batch_number,
    )[0]


@pytest.mark.integration
def test_list_stock_uses_exact_90_day_window_and_as_of_date(db_session):
    product, location = create_product_and_location(db_session)
    batch = create_batch(
        db_session,
        product,
        location,
        "LOT-METRICS",
        date(2026, 12, 31),
    )
    window_start = AS_OF - timedelta(days=89)

    add_movement(
        db_session,
        product,
        location,
        MV_TYPES.RECEIPT,
        Decimal("100"),
        date(2026, 6, 1),
        batch.batch_number,
    )
    add_movement(
        db_session,
        product,
        location,
        MV_TYPES.CONSUME,
        Decimal("7"),
        window_start - timedelta(days=1),
    )
    add_movement(
        db_session,
        product,
        location,
        MV_TYPES.CONSUME,
        Decimal("9"),
        window_start,
    )
    add_movement(
        db_session,
        product,
        location,
        MV_TYPES.CONSUME,
        Decimal("9"),
        AS_OF,
    )
    add_movement(
        db_session,
        product,
        location,
        MV_TYPES.WRITEOFF,
        Decimal("4"),
        AS_OF,
        batch.batch_number,
    )
    add_movement(
        db_session,
        product,
        location,
        MV_TYPES.CONSUME,
        Decimal("50"),
        AS_OF + timedelta(days=1),
    )

    summaries = list_stock(db_session, as_of=AS_OF)
    summary = next(item for item in summaries if item.sku == product.sku)

    assert summary.location == location.code
    assert summary.current_stock == Decimal("71.000")
    assert summary.avg_daily_consumption == Decimal("0.200")
    assert summary.days_of_stock == Decimal("355")
    assert summary.nearest_expiry == date(2026, 12, 31)


@pytest.mark.integration
def test_list_stock_chooses_nearest_nonexpired_batch_with_stock(db_session):
    product, location = create_product_and_location(db_session)
    expired = create_batch(
        db_session,
        product,
        location,
        "LOT-EXPIRED",
        date(2026, 9, 10),
    )
    empty = create_batch(
        db_session,
        product,
        location,
        "LOT-EMPTY",
        date(2026, 9, 16),
    )
    nearest = create_batch(
        db_session,
        product,
        location,
        "LOT-NEAREST",
        date(2026, 9, 20),
    )
    later = create_batch(
        db_session,
        product,
        location,
        "LOT-LATER",
        date(2026, 10, 1),
    )

    for batch, quantity in [
        (expired, Decimal("5")),
        (empty, Decimal("2")),
        (nearest, Decimal("3")),
        (later, Decimal("4")),
    ]:
        add_movement(
            db_session,
            product,
            location,
            MV_TYPES.RECEIPT,
            quantity,
            date(2026, 9, 1),
            batch.batch_number,
        )

    add_movement(
        db_session,
        product,
        location,
        MV_TYPES.WRITEOFF,
        Decimal("2"),
        date(2026, 9, 14),
        empty.batch_number,
    )

    summaries = list_stock(db_session, as_of=AS_OF)
    summary = next(item for item in summaries if item.sku == product.sku)

    assert summary.current_stock == Decimal("12.000")
    assert summary.avg_daily_consumption == Decimal("0")
    assert summary.days_of_stock is None
    assert summary.nearest_expiry == nearest.expires_at


@pytest.mark.integration
def test_list_stock_sorts_by_sku_and_location(db_session):
    expected_pairs = []
    for sku_prefix, location_prefix in [
        ("ZZZ-STOCK", "AAA-LOC"),
        ("AAA-STOCK", "ZZZ-LOC"),
        ("AAA-STOCK", "AAA-LOC"),
    ]:
        product, location = create_product_and_location(
            db_session,
            sku_prefix,
            location_prefix,
        )
        batch = create_batch(
            db_session,
            product,
            location,
            f"LOT-{uuid4().hex[:8]}",
            date(2026, 12, 31),
        )
        add_movement(
            db_session,
            product,
            location,
            MV_TYPES.RECEIPT,
            Decimal("1"),
            date(2026, 9, 1),
            batch.batch_number,
        )
        expected_pairs.append((product.sku, location.code))

    summaries = list_stock(db_session, as_of=AS_OF)
    actual_pairs = [
        (summary.sku, summary.location)
        for summary in summaries
        if (summary.sku, summary.location) in expected_pairs
    ]

    assert actual_pairs == sorted(expected_pairs)


@pytest.mark.integration
def test_get_stock_detail_groups_positive_batches_and_receipt_documents(db_session):
    product, location = create_product_and_location(db_session)
    second_location = Location(
        code=f"SECOND-{uuid4().hex[:10]}",
        name="Second stock location",
    )
    db_session.add(second_location)
    db_session.flush()

    expired = create_batch(
        db_session,
        product,
        location,
        "DETAIL-EXPIRED",
        date(2026, 9, 10),
    )
    empty = create_batch(
        db_session,
        product,
        location,
        "DETAIL-EMPTY",
        date(2026, 9, 16),
    )
    active = create_batch(
        db_session,
        product,
        location,
        "DETAIL-ACTIVE",
        date(2026, 9, 20),
    )
    other_location_batch = create_batch(
        db_session,
        product,
        second_location,
        "DETAIL-SECOND-LOCATION",
        date(2026, 10, 1),
    )

    expired_receipt = add_movement(
        db_session,
        product,
        location,
        MV_TYPES.RECEIPT,
        Decimal("5"),
        date(2026, 9, 1),
        expired.batch_number,
    )
    add_movement(
        db_session,
        product,
        location,
        MV_TYPES.RECEIPT,
        Decimal("2"),
        date(2026, 9, 1),
        empty.batch_number,
    )
    add_movement(
        db_session,
        product,
        location,
        MV_TYPES.WRITEOFF,
        Decimal("2"),
        date(2026, 9, 14),
        empty.batch_number,
    )
    active_receipt_one = add_movement(
        db_session,
        product,
        location,
        MV_TYPES.RECEIPT,
        Decimal("3"),
        date(2026, 9, 2),
        active.batch_number,
    )
    active_receipt_two = add_movement(
        db_session,
        product,
        location,
        MV_TYPES.RECEIPT,
        Decimal("2"),
        date(2026, 9, 3),
        active.batch_number,
    )
    add_movement(
        db_session,
        product,
        location,
        MV_TYPES.WRITEOFF,
        Decimal("1"),
        date(2026, 9, 14),
        active.batch_number,
    )
    add_movement(
        db_session,
        product,
        location,
        MV_TYPES.RECEIPT,
        Decimal("10"),
        AS_OF + timedelta(days=1),
        active.batch_number,
    )
    second_location_receipt = add_movement(
        db_session,
        product,
        second_location,
        MV_TYPES.RECEIPT,
        Decimal("7"),
        date(2026, 9, 4),
        other_location_batch.batch_number,
    )

    detail = get_stock_detail(db_session, product.sku, as_of=AS_OF)

    assert detail.sku == product.sku
    assert detail.name == product.name
    assert detail.unit == product.unit
    assert [item.location for item in detail.locations] == sorted(
        [location.code, second_location.code]
    )

    locations = {item.location: item for item in detail.locations}
    first = locations[location.code]
    assert first.current_stock == Decimal("9.000")
    assert [batch.batch_number for batch in first.batches] == [
        expired.batch_number,
        active.batch_number,
    ]
    assert first.batches[0].quantity == Decimal("5.000")
    assert first.batches[0].receipt_documents == [expired_receipt.document_number]
    assert first.batches[1].quantity == Decimal("4.000")
    assert first.batches[1].receipt_documents == [
        active_receipt_one.document_number,
        active_receipt_two.document_number,
    ]
    assert empty.batch_number not in {batch.batch_number for batch in first.batches}

    second = locations[second_location.code]
    assert second.current_stock == Decimal("7.000")
    assert len(second.batches) == 1
    assert second.batches[0].receipt_documents == [
        second_location_receipt.document_number
    ]


@pytest.mark.integration
def test_get_stock_detail_raises_for_unknown_product(db_session):
    unknown_sku = f"UNKNOWN-{uuid4().hex}"

    with pytest.raises(ProductNotFoundError) as exc_info:
        get_stock_detail(db_session, unknown_sku, as_of=AS_OF)

    assert exc_info.value.sku == unknown_sku
