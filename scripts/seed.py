import datetime
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from database import SessionLocal
from product import (
    MV_TYPES,
    SUPPLY_STATUS,
    Batch,
    Location,
    Movement,
    Product,
    PurchaseOrder,
)
from services.movements import register_movement


@dataclass(frozen=True)
class MovementSeed:
    sku: str
    location: str
    document_number: str
    type: MV_TYPES
    quantity: Decimal
    occurred_at: datetime.date
    batch_number: str | None = None


def _get_or_create_location(session: Session, code: str, name: str) -> Location:
    location = session.scalar(select(Location).where(Location.code == code))
    if location is None:
        location = Location(code=code, name=name)
        session.add(location)
        session.flush()
    return location


def _get_or_create_product(
    session: Session,
    *,
    sku: str,
    name: str,
    unit: str,
    lead_time_days: int,
    package_size: Decimal,
    min_order_quantity: Decimal,
) -> Product:
    product = session.scalar(select(Product).where(Product.sku == sku))
    if product is None:
        product = Product(
            sku=sku,
            name=name,
            unit=unit,
            lead_time_days=lead_time_days,
            package_size=package_size,
            min_order_quantity=min_order_quantity,
        )
        session.add(product)
        session.flush()
    return product


def _get_or_create_batch(
    session: Session,
    *,
    product: Product,
    location: Location,
    batch_number: str,
    produced_at: datetime.date,
    expires_at: datetime.date,
    unit_price: Decimal,
) -> Batch:
    batch = session.scalar(
        select(Batch).where(
            Batch.product_id == product.id,
            Batch.location_id == location.id,
            Batch.batch_number == batch_number,
        )
    )
    if batch is None:
        batch = Batch(
            product_id=product.id,
            location_id=location.id,
            batch_number=batch_number,
            produced_at=produced_at,
            expires_at=expires_at,
            unit_price=unit_price,
        )
        session.add(batch)
        session.flush()
    return batch


def _register_movement_if_missing(session: Session, seed: MovementSeed) -> None:
    exists = session.scalar(
        select(Movement.id).where(Movement.document_number == seed.document_number)
    )
    if exists is not None:
        return

    register_movement(
        session=session,
        sku=seed.sku,
        location_code=seed.location,
        document_number=seed.document_number,
        mv_type=seed.type,
        quantity=seed.quantity,
        operation_date=seed.occurred_at,
        batch_number=seed.batch_number,
    )


def _create_purchase_order_if_missing(
    session: Session,
    *,
    product: Product,
    location: Location,
    expected_at: datetime.date,
) -> None:
    document_number = "SEED-PO-CREAM-001"
    exists = session.scalar(
        select(PurchaseOrder.id).where(PurchaseOrder.document_number == document_number)
    )
    if exists is not None:
        return

    session.add(
        PurchaseOrder(
            product_id=product.id,
            location_id=location.id,
            document_number=document_number,
            quantity=Decimal("24"),
            unit_price=Decimal("780.00"),
            expected_at=expected_at,
            status=SUPPLY_STATUS.IN_TRANSIT,
        )
    )
    session.commit()


def seed_database(session: Session, as_of: datetime.date | None = None) -> None:
    as_of = as_of or datetime.date.today()
    location = _get_or_create_location(session, "MS-01", "Mountain & Sea Spa")

    oil = _get_or_create_product(
        session,
        sku="OIL-001",
        name="Base massage oil",
        unit="l",
        lead_time_days=7,
        package_size=Decimal("5"),
        min_order_quantity=Decimal("10"),
    )
    cream = _get_or_create_product(
        session,
        sku="CREAM-001",
        name="Massage cream",
        unit="kg",
        lead_time_days=14,
        package_size=Decimal("6"),
        min_order_quantity=Decimal("12"),
    )
    towel = _get_or_create_product(
        session,
        sku="TOWEL-001",
        name="Disposable towel",
        unit="pcs",
        lead_time_days=5,
        package_size=Decimal("50"),
        min_order_quantity=Decimal("100"),
    )

    oil_batch = _get_or_create_batch(
        session,
        product=oil,
        location=location,
        batch_number="OIL-LOT-001",
        produced_at=as_of - datetime.timedelta(days=120),
        expires_at=as_of + datetime.timedelta(days=20),
        unit_price=Decimal("1259.05"),
    )
    cream_batch = _get_or_create_batch(
        session,
        product=cream,
        location=location,
        batch_number="CREAM-LOT-001",
        produced_at=as_of - datetime.timedelta(days=60),
        expires_at=as_of + datetime.timedelta(days=180),
        unit_price=Decimal("790.00"),
    )
    towel_batch = _get_or_create_batch(
        session,
        product=towel,
        location=location,
        batch_number="TOWEL-LOT-001",
        produced_at=as_of - datetime.timedelta(days=90),
        expires_at=as_of + datetime.timedelta(days=730),
        unit_price=Decimal("18.50"),
    )
    session.commit()

    movements = [
        MovementSeed(
            oil.sku,
            location.code,
            "SEED-OIL-RECEIPT-001",
            MV_TYPES.RECEIPT,
            Decimal("50"),
            as_of - datetime.timedelta(days=60),
            oil_batch.batch_number,
        ),
        MovementSeed(
            oil.sku,
            location.code,
            "SEED-OIL-CONSUME-001",
            MV_TYPES.CONSUME,
            Decimal("10"),
            as_of - datetime.timedelta(days=14),
        ),
        MovementSeed(
            oil.sku,
            location.code,
            "SEED-OIL-CONSUME-002",
            MV_TYPES.CONSUME,
            Decimal("20"),
            as_of - datetime.timedelta(days=1),
        ),
        MovementSeed(
            cream.sku,
            location.code,
            "SEED-CREAM-RECEIPT-001",
            MV_TYPES.RECEIPT,
            Decimal("12"),
            as_of - datetime.timedelta(days=40),
            cream_batch.batch_number,
        ),
        MovementSeed(
            cream.sku,
            location.code,
            "SEED-CREAM-CONSUME-001",
            MV_TYPES.CONSUME,
            Decimal("11"),
            as_of - datetime.timedelta(days=1),
        ),
        MovementSeed(
            towel.sku,
            location.code,
            "SEED-TOWEL-RECEIPT-001",
            MV_TYPES.RECEIPT,
            Decimal("100"),
            as_of - datetime.timedelta(days=45),
            towel_batch.batch_number,
        ),
    ]
    for movement in movements:
        _register_movement_if_missing(session, movement)

    _create_purchase_order_if_missing(
        session,
        product=cream,
        location=location,
        expected_at=as_of + datetime.timedelta(days=5),
    )


def main() -> None:
    with SessionLocal() as session:
        seed_database(session)
    print("Demo data is ready.")


if __name__ == "__main__":
    main()
