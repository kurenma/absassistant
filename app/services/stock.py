import datetime
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.calculations.stock import calculate_batch_stock, calculate_stock
from app.calculations.stock_metrics import (
    calculate_average_daily_consumption,
    calculate_days_of_stock,
)
from app.db.models import (
    Batch,
    Location,
    Movement,
    MovementAllocation,
    MovementType,
    Product,
)
from app.services.movements import ProductNotFoundError


@dataclass
class StockSummary:
    sku: str
    name: str
    unit: str
    location: str
    current_stock: Decimal
    avg_daily_consumption: Decimal
    days_of_stock: Decimal | None
    nearest_expiry: datetime.date | None


@dataclass
class BatchStockDetail:
    batch_id: int
    batch_number: str
    quantity: Decimal
    produced_at: datetime.date
    expires_at: datetime.date
    unit_price: Decimal
    receipt_documents: list[str]


@dataclass
class LocationStockDetail:
    location: str
    current_stock: Decimal
    batches: list[BatchStockDetail]


@dataclass
class ProductStockDetail:
    sku: str
    name: str
    unit: str
    locations: list[LocationStockDetail]


CONSUMPTION_WINDOW_DAYS = 90


def list_stock(session: Session, as_of: datetime.date) -> list[StockSummary]:
    """Принимает сессию и дату актуальности остатка.

    Группирует движения по товарам и объектам, рассчитывает текущий остаток,
    средний расход за 90 дней, запас в днях и ближайший действующий срок
    годности. Возвращает отсортированный список сводных остатков.
    """
    window_start = as_of - datetime.timedelta(days=CONSUMPTION_WINDOW_DAYS - 1)

    movements_statement = (
        select(
            Product.id,
            Product.sku,
            Product.name,
            Product.unit,
            Location.id,
            Location.code,
            Movement.type,
            Movement.quantity,
            Movement.occurred_at,
        )
        .select_from(Movement)
        .join(Product, Product.id == Movement.product_id)
        .join(Location, Location.id == Movement.location_id)
        .where(Movement.occurred_at <= as_of)
    )

    movement_rows = session.execute(movements_statement).tuples().all()

    grouped: dict[tuple[int, int], dict] = defaultdict(
        lambda: {
            "sku": None,
            "name": None,
            "unit": None,
            "location": None,
            "stock_movements": [],
            "consumption_90d": Decimal("0"),
        }
    )

    for (
        product_id,
        sku,
        name,
        unit,
        location_id,
        location_code,
        mv_type,
        quantity,
        occurred_at,
    ) in movement_rows:
        key = (product_id, location_id)
        bucket = grouped[key]
        bucket["sku"] = sku
        bucket["name"] = name
        bucket["unit"] = unit
        bucket["location"] = location_code

        bucket["stock_movements"].append((mv_type, quantity))

        if mv_type == MovementType.CONSUME and window_start <= occurred_at <= as_of:
            bucket["consumption_90d"] += quantity

    allocations_statement = (
        select(
            MovementAllocation.batch_id,
            Batch.product_id,
            Batch.location_id,
            Batch.expires_at,
            Movement.type,
            Movement.quantity,
            MovementAllocation.quantity,
        )
        .select_from(MovementAllocation)
        .join(Batch, Batch.id == MovementAllocation.batch_id)
        .join(Movement, Movement.id == MovementAllocation.movement_id)
        .where(Movement.occurred_at <= as_of)
    )
    allocation_rows = session.execute(allocations_statement).tuples().all()

    batches: dict[int, dict] = defaultdict(
        lambda: {
            "product_id": None,
            "location_id": None,
            "expires_at": None,
            "allocations": [],
        }
    )

    for (
        batch_id,
        product_id,
        location_id,
        expires_at,
        mv_type,
        mv_quantity,
        allocated_quantity,
    ) in allocation_rows:
        b = batches[batch_id]
        b["product_id"] = product_id
        b["location_id"] = location_id
        b["expires_at"] = expires_at
        b["allocations"].append((mv_type, mv_quantity, allocated_quantity))

    nearest_expiry: dict[tuple[int, int], datetime.date] = {}

    for batch_id, b in batches.items():
        batch_stock = calculate_batch_stock(b["allocations"])
        if batch_stock <= 0:
            continue

        expires_at = b["expires_at"]
        if expires_at is None or expires_at < as_of:
            continue

        key = (b["product_id"], b["location_id"])
        current = nearest_expiry.get(key)
        if current is None or expires_at < current:
            nearest_expiry[key] = expires_at

    result: list[StockSummary] = []

    for (product_id, location_id), bucket in grouped.items():
        current_stock = calculate_stock(bucket["stock_movements"])

        avg_daily = calculate_average_daily_consumption(
            bucket["consumption_90d"],
            CONSUMPTION_WINDOW_DAYS,
        )

        days_left = calculate_days_of_stock(current_stock, avg_daily)

        result.append(
            StockSummary(
                sku=bucket["sku"],
                name=bucket["name"],
                unit=bucket["unit"],
                location=bucket["location"],
                current_stock=current_stock,
                avg_daily_consumption=avg_daily,
                days_of_stock=days_left,
                nearest_expiry=nearest_expiry.get((product_id, location_id)),
            )
        )

    result.sort(key=lambda s: (s.sku, s.location))
    return result


def get_stock_detail(
    session: Session,
    sku: str,
    as_of: datetime.date,
) -> ProductStockDetail:
    """Принимает сессию, SKU и дату актуальности.

    Находит товар, восстанавливает остатки его партий из распределений движений
    и группирует партии по объектам. Возвращает детализацию товара; для
    неизвестного SKU выбрасывает ``ProductNotFoundError``.
    """
    product = session.scalar(select(Product).where(Product.sku == sku))
    if product is None:
        raise ProductNotFoundError(sku)

    statement = (
        select(
            Batch.id,
            Batch.batch_number,
            Batch.produced_at,
            Batch.expires_at,
            Batch.unit_price,
            Location.id,
            Location.code,
            Movement.type,
            Movement.quantity,
            Movement.document_number,
            MovementAllocation.quantity,
        )
        .select_from(Batch)
        .join(Location, Location.id == Batch.location_id)
        .join(MovementAllocation, MovementAllocation.batch_id == Batch.id)
        .join(Movement, Movement.id == MovementAllocation.movement_id)
        .where(
            Batch.product_id == product.id,
            Movement.occurred_at <= as_of,
        )
        .order_by(
            Location.code.asc(),
            Batch.expires_at.asc(),
            Batch.id.asc(),
            Movement.occurred_at.asc(),
            Movement.id.asc(),
        )
    )
    rows = session.execute(statement).tuples().all()

    grouped_batches: dict[int, dict] = defaultdict(
        lambda: {
            "batch_number": None,
            "produced_at": None,
            "expires_at": None,
            "unit_price": None,
            "location_id": None,
            "location": None,
            "allocations": [],
            "receipt_documents": [],
        }
    )

    for (
        batch_id,
        batch_number,
        produced_at,
        expires_at,
        unit_price,
        location_id,
        location_code,
        mv_type,
        mv_quantity,
        document_number,
        allocated_quantity,
    ) in rows:
        batch = grouped_batches[batch_id]
        batch["batch_number"] = batch_number
        batch["produced_at"] = produced_at
        batch["expires_at"] = expires_at
        batch["unit_price"] = unit_price
        batch["location_id"] = location_id
        batch["location"] = location_code
        batch["allocations"].append((mv_type, mv_quantity, allocated_quantity))
        if (
            mv_type == MovementType.RECEIPT
            and document_number not in batch["receipt_documents"]
        ):
            batch["receipt_documents"].append(document_number)

    locations: dict[int, dict] = defaultdict(
        lambda: {
            "location": None,
            "current_stock": Decimal("0"),
            "batches": [],
        }
    )

    for batch_id, batch in grouped_batches.items():
        quantity = calculate_batch_stock(batch["allocations"])
        if quantity <= 0:
            continue

        batch_detail = BatchStockDetail(
            batch_id=batch_id,
            batch_number=batch["batch_number"],
            quantity=quantity,
            produced_at=batch["produced_at"],
            expires_at=batch["expires_at"],
            unit_price=batch["unit_price"],
            receipt_documents=batch["receipt_documents"],
        )
        location = locations[batch["location_id"]]
        location["location"] = batch["location"]
        location["current_stock"] += quantity
        location["batches"].append(batch_detail)

    location_details = [
        LocationStockDetail(
            location=location["location"],
            current_stock=location["current_stock"],
            batches=location["batches"],
        )
        for location in locations.values()
    ]
    location_details.sort(key=lambda item: item.location)

    return ProductStockDetail(
        sku=product.sku,
        name=product.name,
        unit=product.unit,
        locations=location_details,
    )
