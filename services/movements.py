import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from calculation.fefo import allocate_fefo
from calculation.stock import calculate_batch_stock, calculate_stock
from product import Batch, Location, Movement, MovementAllocation, Product, MV_TYPES


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

class DocumentAlreadyExistsError(Exception):
    def __init__(self, document_number: str) -> None:
        self.document_number = document_number
        super().__init__(
            f"Document with number={document_number!r} already exists"
        )


class InsufficientBatchStockError(Exception):
    def __int__(
            self,
            batch_id: int,
            available_quantity: Decimal,
            requested_quantity: Decimal
        ) -> None:
        self.batch_id = batch_id
        self.available_quantity = available_quantity
        self.requested_quantity = requested_quantity
        super().__init__(
            f"Batch {batch_id}: requested {requested_quantity}, "
            f"but only {available_quantity} is available"
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


def ensure_document_number_available(
        session: Session,
        document_number: str,
        location_code: str
) -> None:
    location = session.scalar(select(Location).where(Location.code == location_code))

    if location is None:
        raise LocationNotFoundError(location_code)

    document = session.scalar(select(Movement).where(Movement.location_id == location.id, Movement.document_number == document_number))

    if document is not None:
        raise DocumentAlreadyExistsError(document_number)

def ensure_batch_stock_available(
        session: Session,
        batch_id: int,
        requestes_quantity: Decimal
) -> Decimal:
    
    available_batch_stock = get_batch_stock(session, batch_id)

    if available_batch_stock < requestes_quantity:
        raise InsufficientBatchStockError(batch_id, available_batch_stock, requestes_quantity)

    return available_batch_stock


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


def plan_consume_allocations(
    session: Session,
    product_id: int,
    location_id: int,
    requestes_quantity: Decimal,
    operation_date: datetime.date
) -> list[tuple[int, Decimal]]:

    batches = get_batch_balances(session, product_id, location_id)

    return allocate_fefo(requestes_quantity, operation_date, batches)

def _prepare_allocations(
        session: Session,
        product_id: int,
        location_id: int,
        mv_type: MV_TYPES,
        quantity: Decimal,
        operation_date: datetime.date,
        batch_number: str | None = None
) -> list[tuple[int, Decimal]]:

    if mv_type == MV_TYPES.CONSUME:
        batches = get_batch_balances(session, product_id, location_id)
        return allocate_fefo(quantity, operation_date, batches)

    if batch_number is None:
        raise ValueError(f"batch_number is required for mv_type={mv_type!r}")

    batch = resolve_batch(session, product_id, location_id, batch_number)

    if mv_type == MV_TYPES.WRITEOFF:
        ensure_batch_stock_available(session, batch.id, quantity)
        return [(batch.id, abs(quantity))]

    if mv_type in (MV_TYPES.RECEIPT, MV_TYPES.RETURN):
        return [(batch.id, abs(quantity))]

    if mv_type == MV_TYPES.CORRECTION:
        if quantity < 0:
            ensure_batch_stock_available(session, batch.id, abs(quantity))
        return [(batch.id, quantity)]


def lock_batches_for_update(
        session: Session,
        product_id: int,
        location_id: int
) -> list[Batch]:

    statement = (
        select(Batch)
        .where(
            Batch.product_id == product_id,
            Batch.location_id == location_id,
        )
        .order_by(Batch.id.asc())
        .with_for_update()
    )

    batches = session.scalars(statement).all()

    return sorted(batches, key=lambda b: (b.expires_at, b.id))

def register_movement(
        session: Session,
        sku: str,
        product_id: int,
        location_code: str,
        document_number: str,
        mv_type: MV_TYPES,
        quantity: Decimal,
        operation_date: datetime.date,
        batch_number: str | None = None
) -> tuple[Movement, Decimal]:
    
    try:
        product, location = resolve_product_and_location(session, sku, location_code)

        ensure_document_number_available(session, document_number, location_code)

        lock_batches_for_update(session, product.id, location.id)

        allocations = _prepare_allocations(
            session,
            product_id,
            location.id,
            mv_type,
            quantity,
            operation_date,
            batch_number
        )

        movement = Movement(
            product_id=product.id,
            location_id=location.id,
            document_number=document_number,
            type=mv_type,
            quantity=quantity,
            occurred_at=operation_date
        )

        session.add(movement)
        session.flush()

        for batch_id, alloc_quantity in allocations:
            session.add(
                MovementAllocation(
                    movement_id=movement.id,
                    batch_id=batch_id,
                    quantity=alloc_quantity
                )
            )

        total_allocated = sum(
            (q for _, q in allocations),
            start=Decimal("0")
        )

        if total_allocated != quantity:
            raise ValueError(
                f"Allocation sum {total_allocated} does not match "
                f"movement quantity {quantity}"
            )

        session.commit()

        new_stock = get_current_stock(session, product.id, location.id)

        return movement, new_stock
    
    except Exception:
        session.rollback()
        raise