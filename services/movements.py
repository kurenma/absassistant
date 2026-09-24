import datetime
from sqlalchemy import select
from sqlalchemy.orm import Session
from decimal import Decimal
from product import Product, Location, Movement, Batch, MovementAllocation
from calculation.stock import calculate_stock, calculate_batch_stock


class ProductNotFoundError(Exception):
    def __init__(self, sku: str) -> None:
        self.sku = sku
        super().__init__(f"Product with sku={sku!r} not found")

class LocationNotFoundError(Exception):

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(f"Location with code={code!r} not found")

class BatchNotFoundError(Exception):
    def __init__(self, batch_number: str) -> None:
        self.batch_number = batch_number
        super().__init__(
            f"Batch with batch_number={batch_number!r} not found"
        )

def resolve_product_and_location(
    session: Session,
    sku: str,
    location_code: str,
) -> tuple[Product, Location]:
    product = session.scalar(select(Product).where(Product.sku == sku))

    if product is None:
        raise ProductNotFoundError(sku)

    location = session.scalar(select(Location).where(Location.code == location_code))

    if location is None:
        raise LocationNotFoundError(location_code)

    return product, location

def get_current_stock(session: Session, product_id: int, location_id: int) -> Decimal:

    statement = (select(Movement.type, Movement.quantity).where(Movement.product_id == product_id, Movement.location_id == location_id,))
    movements = session.execute(statement).tuples().all()

    return calculate_stock(movements)

def resolve_batch(
    session: Session,
    product_id: int,
    location_id: int,
    batch_number: str,
) -> Batch:

    batch = session.scalar(select(Batch).where(Batch.product_id == product_id, Batch.location_id == location_id, Batch.batch_number == batch_number))

    if batch is None:
        raise BatchNotFoundError(batch_number)

    return batch

def get_batch_stock(session: Session, batch_id: int) -> Decimal:

    statement = (select(Movement.type, Movement.quantity, MovementAllocation.quantity).join(Movement, Movement.id == MovementAllocation.movement_id).where(MovementAllocation.batch_id == batch_id,))
    allocations = session.execute(statement).tuples().all()

    return calculate_batch_stock(allocations)

def get_batch_balances(
    session: Session,
    product_id: int,
    location_id: int
) -> list[tuple[int, datetime.date, Decimal]]:

    statement = (
        select(Batch)
        .where(
            Batch.product_id == product_id,
            Batch.location_id == location_id,
        )
        .order_by(
            Batch.expires_at.asc(),
            Batch.id.asc(),
        ) 
    )

    batches = session.scalars(statement).all()

    return [
        (batch.id, batch.expires_at, get_batch_stock(session, batch.id))
        for batch in batches
    ]