import datetime
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from calculation.stock import calculate_batch_stock
from product import Batch, Location, Movement, MovementAllocation, Product
from services.stock import list_stock

AlertType = Literal["shortage_risk", "expiry", "no_movement"]
AlertLevel = Literal["warning", "critical"]
IndicatorValue = str | int | Decimal | datetime.date | None


@dataclass(frozen=True)
class AlertResult:
    type: AlertType
    level: AlertLevel
    sku: str
    location: str
    message: str
    indicators: dict[str, IndicatorValue]


def list_alerts(
    session: Session,
    as_of: datetime.date,
    location_code: str | None = None,
    expiry_warning_days: int = 30,
    inactivity_days: int = 30,
) -> list[AlertResult]:
    if expiry_warning_days <= 0:
        raise ValueError("expiry_warning_days must be positive")
    if inactivity_days <= 0:
        raise ValueError("inactivity_days must be positive")

    alerts: list[AlertResult] = []
    stock_summaries = list_stock(session, as_of)
    lead_times = dict(
        session.execute(select(Product.sku, Product.lead_time_days)).tuples().all()
    )

    for summary in stock_summaries:
        if location_code is not None and summary.location != location_code:
            continue
        lead_time_days = lead_times[summary.sku]
        if summary.days_of_stock is not None and summary.days_of_stock < lead_time_days:
            level: AlertLevel = "critical" if summary.current_stock <= 0 else "warning"
            alerts.append(
                AlertResult(
                    type="shortage_risk",
                    level=level,
                    sku=summary.sku,
                    location=summary.location,
                    message="Stock coverage is below supplier lead time.",
                    indicators={
                        "current_stock": summary.current_stock,
                        "avg_daily_consumption": summary.avg_daily_consumption,
                        "days_of_stock": summary.days_of_stock,
                        "lead_time_days": lead_time_days,
                    },
                )
            )

    expiry_limit = as_of + datetime.timedelta(days=expiry_warning_days)
    allocation_statement = (
        select(
            Batch.id,
            Batch.batch_number,
            Batch.expires_at,
            Product.sku,
            Location.code,
            Movement.type,
            Movement.quantity,
            MovementAllocation.quantity,
        )
        .select_from(Batch)
        .join(Product, Product.id == Batch.product_id)
        .join(Location, Location.id == Batch.location_id)
        .join(MovementAllocation, MovementAllocation.batch_id == Batch.id)
        .join(Movement, Movement.id == MovementAllocation.movement_id)
        .where(
            Movement.occurred_at <= as_of,
            Batch.expires_at <= expiry_limit,
        )
    )
    if location_code is not None:
        allocation_statement = allocation_statement.where(
            Location.code == location_code
        )

    batches: dict[int, dict] = defaultdict(
        lambda: {
            "batch_number": None,
            "expires_at": None,
            "sku": None,
            "location": None,
            "allocations": [],
        }
    )
    for (
        batch_id,
        batch_number,
        expires_at,
        sku,
        batch_location_code,
        movement_type,
        movement_quantity,
        allocated_quantity,
    ) in session.execute(allocation_statement).tuples().all():
        batch = batches[batch_id]
        batch["batch_number"] = batch_number
        batch["expires_at"] = expires_at
        batch["sku"] = sku
        batch["location"] = batch_location_code
        batch["allocations"].append(
            (movement_type, movement_quantity, allocated_quantity)
        )

    for batch in batches.values():
        quantity = calculate_batch_stock(batch["allocations"])
        if quantity <= 0:
            continue
        days_until_expiry = (batch["expires_at"] - as_of).days
        expired = days_until_expiry < 0
        alerts.append(
            AlertResult(
                type="expiry",
                level="critical" if expired else "warning",
                sku=batch["sku"],
                location=batch["location"],
                message=(
                    "Batch has expired."
                    if expired
                    else "Batch expires within the warning period."
                ),
                indicators={
                    "batch_number": batch["batch_number"],
                    "quantity": quantity,
                    "expires_at": batch["expires_at"],
                    "days_until_expiry": days_until_expiry,
                },
            )
        )

    inactivity_cutoff = as_of - datetime.timedelta(days=inactivity_days)
    last_movement_statement = (
        select(
            Product.sku,
            Location.code,
            func.max(Movement.occurred_at),
        )
        .select_from(Batch)
        .join(Product, Product.id == Batch.product_id)
        .join(Location, Location.id == Batch.location_id)
        .outerjoin(
            Movement,
            and_(
                Movement.product_id == Batch.product_id,
                Movement.location_id == Batch.location_id,
                Movement.occurred_at <= as_of,
            ),
        )
        .group_by(Product.sku, Location.code)
    )
    if location_code is not None:
        last_movement_statement = last_movement_statement.where(
            Location.code == location_code
        )

    for sku, item_location_code, last_movement_at in (
        session.execute(last_movement_statement).tuples().all()
    ):
        if last_movement_at is None or last_movement_at < inactivity_cutoff:
            alerts.append(
                AlertResult(
                    type="no_movement",
                    level="warning",
                    sku=sku,
                    location=item_location_code,
                    message="No inventory movement within the inactivity period.",
                    indicators={
                        "last_movement_at": last_movement_at,
                        "inactivity_days": inactivity_days,
                    },
                )
            )

    level_order = {"critical": 0, "warning": 1}
    alerts.sort(
        key=lambda alert: (
            level_order[alert.level],
            alert.sku,
            alert.location,
            alert.type,
            str(alert.indicators.get("batch_number", "")),
        )
    )
    return alerts
