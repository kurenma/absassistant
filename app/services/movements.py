import datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.calculations.fefo import allocate_fefo
from app.calculations.stock import calculate_batch_stock, calculate_stock
from app.db.models import (
    Batch,
    Location,
    Movement,
    MovementAllocation,
    MovementType,
    Product,
)


class ProductNotFoundError(Exception):
    def __init__(self, sku: str) -> None:
        """Принимает SKU и создаёт ошибку отсутствующего товара; ничего не возвращает."""
        self.sku = sku
        super().__init__(f"Product with sku={sku!r} not found")


class LocationNotFoundError(Exception):
    def __init__(self, code: str) -> None:
        """Принимает код объекта и создаёт ошибку отсутствующей локации; ничего не возвращает."""
        self.code = code
        super().__init__(f"Location with code={code!r} not found")


class BatchNotFoundError(Exception):
    def __init__(self, batch_number: str) -> None:
        """Принимает номер партии и создаёт ошибку отсутствующей партии; ничего не возвращает."""
        self.batch_number = batch_number
        super().__init__(f"Batch with batch_number={batch_number!r} not found")


class DocumentAlreadyExistsError(Exception):
    def __init__(self, document_number: str) -> None:
        """Принимает номер документа и создаёт ошибку дублирования; ничего не возвращает."""
        self.document_number = document_number
        super().__init__(f"Document with number={document_number!r} already exists")


class InsufficientBatchStockError(Exception):
    def __init__(
        self,
        batch_id: int,
        available_quantity: Decimal,
        requested_quantity: Decimal,
    ) -> None:
        """Принимает партию и количества, формирует ошибку нехватки; ничего не возвращает."""
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
    """Принимает сессию, SKU и код объекта.

    Проверяет существование товара и объекта в БД. Возвращает найденные модели
    товара и объекта; при отсутствии одной из них выбрасывает предметную ошибку.
    """
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
) -> None:
    """Принимает сессию и номер документа.

    Проверяет уникальность номера среди движений. Ничего не возвращает; при
    найденном дубле выбрасывает ``DocumentAlreadyExistsError``.
    """
    document_id = session.scalar(
        select(Movement.id).where(Movement.document_number == document_number).limit(1)
    )

    if document_id is not None:
        raise DocumentAlreadyExistsError(document_number)


def ensure_batch_stock_available(
    session: Session,
    batch_id: int,
    requested_quantity: Decimal,
) -> Decimal:
    """Принимает сессию, идентификатор партии и запрошенное количество.

    Рассчитывает доступный остаток партии и проверяет достаточность. Возвращает
    доступное количество либо выбрасывает ``InsufficientBatchStockError``.
    """
    available_batch_stock = get_batch_stock(session, batch_id)

    if available_batch_stock < requested_quantity:
        raise InsufficientBatchStockError(
            batch_id,
            available_batch_stock,
            requested_quantity,
        )

    return available_batch_stock


def get_current_stock(session: Session, product_id: int, location_id: int) -> Decimal:
    """Принимает сессию, идентификаторы товара и объекта.

    Загружает движения выбранной позиции и рассчитывает их итоговый баланс.
    Возвращает текущий остаток в единицах товара.
    """
    statement = select(Movement.type, Movement.quantity).where(
        Movement.product_id == product_id,
        Movement.location_id == location_id,
    )
    movements = session.execute(statement).tuples().all()

    return calculate_stock(movements)


def resolve_batch(
    session: Session,
    product_id: int,
    location_id: int,
    batch_number: str,
) -> Batch:
    """Принимает сессию, товар, объект и номер партии.

    Ищет партию в точном контексте товара и объекта. Возвращает модель партии
    либо выбрасывает ``BatchNotFoundError``.
    """
    batch = session.scalar(
        select(Batch).where(
            Batch.product_id == product_id,
            Batch.location_id == location_id,
            Batch.batch_number == batch_number,
        )
    )

    if batch is None:
        raise BatchNotFoundError(batch_number)

    return batch


def get_batch_stock(session: Session, batch_id: int) -> Decimal:
    """Принимает сессию и идентификатор партии.

    Собирает все распределения движений по партии и рассчитывает её баланс.
    Возвращает фактический остаток партии.
    """
    statement = (
        select(
            Movement.type,
            Movement.quantity,
            MovementAllocation.quantity,
        )
        .join(Movement, Movement.id == MovementAllocation.movement_id)
        .where(MovementAllocation.batch_id == batch_id)
    )
    allocations = session.execute(statement).tuples().all()

    return calculate_batch_stock(allocations)


def get_batch_balances(
    session: Session,
    product_id: int,
    location_id: int,
) -> list[tuple[int, datetime.date, Decimal]]:
    """Принимает сессию, идентификаторы товара и объекта.

    Получает партии в порядке срока годности и рассчитывает остаток каждой.
    Возвращает список троек: идентификатор, срок годности и остаток партии.
    """
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
    requested_quantity: Decimal,
    operation_date: datetime.date,
) -> list[tuple[int, Decimal]]:
    """Принимает сессию, товар, объект, количество расхода и дату операции.

    Передаёт актуальные остатки партий в FEFO-алгоритм. Возвращает план
    распределения расхода в виде пар ``(batch_id, quantity)``.
    """
    batches = get_batch_balances(session, product_id, location_id)

    return allocate_fefo(requested_quantity, operation_date, batches)


def _prepare_allocations(
    session: Session,
    product_id: int,
    location_id: int,
    mv_type: MovementType,
    quantity: Decimal,
    operation_date: datetime.date,
    batch_number: str | None = None,
) -> list[tuple[int, Decimal]]:
    """Принимает параметры движения и необязательный номер партии.

    Выбирает правило распределения для типа операции и проверяет остаток при
    уменьшении партии. Возвращает подготовленные распределения по партиям.
    """
    if mv_type == MovementType.CONSUME:
        return plan_consume_allocations(
            session,
            product_id,
            location_id,
            quantity,
            operation_date,
        )

    if batch_number is None:
        raise ValueError(f"batch_number is required for mv_type={mv_type!r}")

    batch = resolve_batch(session, product_id, location_id, batch_number)

    if mv_type == MovementType.WRITEOFF:
        ensure_batch_stock_available(session, batch.id, quantity)
        return [(batch.id, abs(quantity))]

    if mv_type in (MovementType.RECEIPT, MovementType.RETURN):
        return [(batch.id, abs(quantity))]

    if mv_type == MovementType.CORRECTION:
        if quantity < 0:
            ensure_batch_stock_available(session, batch.id, abs(quantity))
        return [(batch.id, abs(quantity))]

    raise ValueError(f"Unsupported movement type: {mv_type!r}")


def lock_batches_for_update(
    session: Session,
    product_id: int,
    location_id: int,
) -> None:
    """Принимает сессию, идентификаторы товара и объекта.

    Блокирует соответствующие партии до завершения транзакции, предотвращая
    конкурентное двойное списание. Ничего не возвращает.
    """
    statement = (
        select(Batch)
        .where(
            Batch.product_id == product_id,
            Batch.location_id == location_id,
        )
        .order_by(Batch.id.asc())
        .with_for_update()
    )

    session.scalars(statement).all()


def _is_document_number_conflict(error: IntegrityError) -> bool:
    """Принимает ошибку целостности БД.

    Проверяет имя нарушенного ограничения. Возвращает ``True``, если конфликт
    вызван повторным номером документа, иначе ``False``.
    """
    original_error = getattr(error, "orig", None)
    diagnostic = getattr(original_error, "diag", None)
    constraint_name = getattr(diagnostic, "constraint_name", None)
    return constraint_name == "movements_document_number_key"


def register_movement(
    session: Session,
    sku: str,
    location_code: str,
    document_number: str,
    mv_type: MovementType,
    quantity: Decimal,
    operation_date: datetime.date,
    batch_number: str | None = None,
) -> tuple[Movement, Decimal]:
    """Принимает сессию и полные данные нового движения.

    Проверяет справочники и документ, блокирует партии, создаёт движение и его
    распределения, затем фиксирует транзакцию. Возвращает созданное движение и
    новый общий остаток товара на объекте; при ошибке откатывает транзакцию.
    """
    try:
        product, location = resolve_product_and_location(session, sku, location_code)

        ensure_document_number_available(session, document_number)

        lock_batches_for_update(session, product.id, location.id)

        allocations = _prepare_allocations(
            session,
            product.id,
            location.id,
            mv_type,
            quantity,
            operation_date,
            batch_number,
        )

        movement = Movement(
            product_id=product.id,
            location_id=location.id,
            document_number=document_number,
            type=mv_type,
            quantity=quantity,
            occurred_at=operation_date,
        )

        total_allocated = sum(
            (allocated_quantity for _, allocated_quantity in allocations),
            start=Decimal("0"),
        )

        if total_allocated != abs(quantity):
            raise ValueError(
                f"Allocation sum {total_allocated} does not match "
                f"movement quantity {quantity}"
            )

        session.add(movement)
        session.flush()

        session.add_all(
            [
                MovementAllocation(
                    movement_id=movement.id,
                    batch_id=batch_id,
                    quantity=alloc_quantity,
                )
                for batch_id, alloc_quantity in allocations
            ]
        )
        session.flush()

        new_stock = get_current_stock(session, product.id, location.id)
        session.commit()

        return movement, new_stock

    except IntegrityError as error:
        session.rollback()
        if _is_document_number_conflict(error):
            raise DocumentAlreadyExistsError(document_number) from error
        raise
    except Exception:
        session.rollback()
        raise


def list_movements(
    session: Session,
    sku: str | None = None,
    location_code: str | None = None,
    mv_type: MovementType | None = None,
    date_from: datetime.date | None = None,
    date_to: datetime.date | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[tuple[Movement, str, str]], int]:
    """Принимает сессию, фильтры периода и движения, limit и offset.

    Формирует отфильтрованный запрос и отдельный подсчёт общего количества.
    Возвращает страницу движений вместе с SKU и кодом объекта, а также total.
    """
    conditions = []
    if sku is not None:
        conditions.append(Product.sku == sku)
    if location_code is not None:
        conditions.append(Location.code == location_code)
    if mv_type is not None:
        conditions.append(Movement.type == mv_type)
    if date_from is not None:
        conditions.append(Movement.occurred_at >= date_from)
    if date_to is not None:
        conditions.append(Movement.occurred_at <= date_to)

    count_statement = (
        select(func.count())
        .select_from(Movement)
        .join(Product, Product.id == Movement.product_id)
        .join(Location, Location.id == Movement.location_id)
        .where(*conditions)
    )
    total = session.scalar(count_statement) or 0

    rows_statement = (
        select(Movement, Product.sku, Location.code)
        .join(Product, Product.id == Movement.product_id)
        .join(Location, Location.id == Movement.location_id)
        .where(*conditions)
        .order_by(Movement.occurred_at.desc(), Movement.id.desc())
        .limit(limit)
        .offset(offset)
    )
    rows = list(session.execute(rows_statement).tuples().all())

    return rows, total
