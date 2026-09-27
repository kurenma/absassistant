import datetime
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.calculations.forecast import (
    ForecastInputs,
    ForecastMetrics,
    calculate_forecast,
    resolve_horizon_days,
)
from app.calculations.stock import calculate_stock
from app.calculations.stock_metrics import calculate_average_daily_consumption
from app.db.models import (
    Batch,
    Movement,
    MovementAllocation,
    MovementType,
    PurchaseOrder,
    SupplyStatus,
)
from app.services.movements import resolve_product_and_location


@dataclass(frozen=True)
class ForecastExplanationData:
    data_used: list[str]
    formulas: list[str]
    assumptions: list[str]
    as_of: datetime.date


@dataclass(frozen=True)
class ForecastWarningData:
    level: str
    message: str


@dataclass(frozen=True)
class ForecastResult:
    sku: str
    name: str
    unit: str
    location: str
    metrics: ForecastMetrics
    explanation: ForecastExplanationData
    warnings: list[ForecastWarningData]


def build_forecast(
    session: Session,
    sku: str,
    location_code: str,
    horizon_days: int | None,
    horizon_months: int | None,
    safety_stock_days: int,
    as_of: datetime.date,
) -> ForecastResult:
    """Принимает сессию, товар, объект, горизонт, страховой запас и дату расчёта.

    Загружает движения, поставки в пути, условия поставщика и последнюю цену,
    после чего вызывает детерминированный расчётный модуль. Возвращает прогноз
    закупки с объяснением исходных данных, формул, допущений и предупреждений.
    """
    product, location = resolve_product_and_location(session, sku, location_code)
    resolved_horizon_days = resolve_horizon_days(horizon_days, horizon_months)
    period_to = as_of + datetime.timedelta(days=resolved_horizon_days - 1)
    consumption_window_start = as_of - datetime.timedelta(days=89)

    movement_rows = (
        session.execute(
            select(Movement.type, Movement.quantity, Movement.occurred_at).where(
                Movement.product_id == product.id,
                Movement.location_id == location.id,
                Movement.occurred_at <= as_of,
            )
        )
        .tuples()
        .all()
    )
    current_stock = calculate_stock(
        (mv_type, quantity) for mv_type, quantity, _ in movement_rows
    )
    consumed_quantity = sum(
        (
            quantity
            for mv_type, quantity, occurred_at in movement_rows
            if mv_type == MovementType.CONSUME
            and consumption_window_start <= occurred_at <= as_of
        ),
        start=Decimal("0"),
    )
    average_daily_consumption = calculate_average_daily_consumption(
        consumed_quantity,
        90,
    )

    incoming_quantity = session.scalar(
        select(func.coalesce(func.sum(PurchaseOrder.quantity), 0)).where(
            PurchaseOrder.product_id == product.id,
            PurchaseOrder.location_id == location.id,
            PurchaseOrder.status == SupplyStatus.IN_TRANSIT,
            PurchaseOrder.expected_at <= period_to,
        )
    )
    incoming_quantity = Decimal(incoming_quantity or 0)

    unit_price = session.scalar(
        select(Batch.unit_price)
        .select_from(Movement)
        .join(
            MovementAllocation,
            MovementAllocation.movement_id == Movement.id,
        )
        .join(Batch, Batch.id == MovementAllocation.batch_id)
        .where(
            Movement.product_id == product.id,
            Movement.location_id == location.id,
            Movement.type == MovementType.RECEIPT,
            Movement.occurred_at <= as_of,
        )
        .order_by(Movement.occurred_at.desc(), Movement.id.desc())
        .limit(1)
    )

    metrics = calculate_forecast(
        ForecastInputs(
            as_of=as_of,
            horizon_days=resolved_horizon_days,
            average_daily_consumption=average_daily_consumption,
            current_stock=current_stock,
            incoming_quantity=incoming_quantity,
            safety_stock_days=safety_stock_days,
            lead_time_days=product.lead_time_days,
            package_size=product.package_size,
            min_order_quantity=product.min_order_quantity,
            unit_price=unit_price,
        )
    )

    assumptions = [
        "Incoming quantity includes in-transit orders expected by period end.",
        "Unit price is taken from the latest receipt.",
    ]
    if horizon_months is not None:
        assumptions.append("One month is treated as 30 days.")

    warnings: list[ForecastWarningData] = []
    if metrics.current_stock < metrics.reorder_point:
        warnings.append(
            ForecastWarningData(
                level="warning",
                message="Current stock is below the reorder point.",
            )
        )
    if metrics.unit_price is None:
        warnings.append(
            ForecastWarningData(
                level="warning",
                message="Purchase price is unavailable.",
            )
        )

    return ForecastResult(
        sku=product.sku,
        name=product.name,
        unit=product.unit,
        location=location.code,
        metrics=metrics,
        explanation=ForecastExplanationData(
            data_used=[
                "Consumption movements for the previous 90 days.",
                f"Stock calculated from movements as of {as_of.isoformat()}.",
                "Open in-transit purchase orders due by period end.",
            ],
            formulas=[
                "average daily consumption = consumption for 90 days / 90",
                "forecast demand = average daily consumption * period days",
                "safety stock = average daily consumption * safety stock days",
                "reorder point = lead-time demand + safety stock",
                "purchase = forecast + safety stock - stock - incoming",
            ],
            assumptions=assumptions,
            as_of=as_of,
        ),
        warnings=warnings,
    )
