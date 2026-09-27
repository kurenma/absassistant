import datetime
from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal


@dataclass(frozen=True)
class ForecastInputs:
    as_of: datetime.date
    horizon_days: int
    average_daily_consumption: Decimal
    current_stock: Decimal
    incoming_quantity: Decimal
    safety_stock_days: int
    lead_time_days: int
    package_size: Decimal
    min_order_quantity: Decimal
    unit_price: Decimal | None


@dataclass(frozen=True)
class ForecastMetrics:
    period_from: datetime.date
    period_to: datetime.date
    period_days: int
    average_daily_consumption: Decimal
    forecast_demand: Decimal
    current_stock: Decimal
    incoming_quantity: Decimal
    safety_stock: Decimal
    reorder_point: Decimal
    recommended_purchase_quantity: Decimal
    unit_price: Decimal | None
    estimated_cost: Decimal | None
    recommended_order_date: datetime.date | None
    stockout_date: datetime.date | None


def resolve_horizon_days(
    horizon_days: int | None,
    horizon_months: int | None,
) -> int:
    if (horizon_days is None) == (horizon_months is None):
        raise ValueError("Exactly one forecast horizon must be provided")
    if horizon_days is not None:
        if horizon_days <= 0:
            raise ValueError("horizon_days must be positive")
        return horizon_days
    if horizon_months is None or horizon_months <= 0:
        raise ValueError("horizon_months must be positive")
    return horizon_months * 30


def _require_nonnegative(name: str, value: Decimal | int) -> None:
    if value < 0:
        raise ValueError(f"{name} must be nonnegative, got {value}")


def calculate_forecast_demand(
    average_daily_consumption: Decimal,
    horizon_days: int,
) -> Decimal:
    _require_nonnegative("average_daily_consumption", average_daily_consumption)
    if horizon_days <= 0:
        raise ValueError(f"horizon_days must be positive, got {horizon_days}")
    return average_daily_consumption * horizon_days


def calculate_safety_stock(
    average_daily_consumption: Decimal,
    safety_stock_days: int,
) -> Decimal:
    _require_nonnegative("average_daily_consumption", average_daily_consumption)
    _require_nonnegative("safety_stock_days", safety_stock_days)
    return average_daily_consumption * safety_stock_days


def calculate_reorder_point(
    average_daily_consumption: Decimal,
    lead_time_days: int,
    safety_stock: Decimal,
) -> Decimal:
    _require_nonnegative("average_daily_consumption", average_daily_consumption)
    _require_nonnegative("lead_time_days", lead_time_days)
    _require_nonnegative("safety_stock", safety_stock)
    return average_daily_consumption * lead_time_days + safety_stock


def round_purchase_quantity(
    required_quantity: Decimal,
    package_size: Decimal,
    min_order_quantity: Decimal,
) -> Decimal:
    if package_size <= 0:
        raise ValueError(f"package_size must be positive, got {package_size}")
    if min_order_quantity <= 0:
        raise ValueError(
            f"min_order_quantity must be positive, got {min_order_quantity}"
        )
    if required_quantity <= 0:
        return Decimal("0")

    target = max(required_quantity, min_order_quantity)
    packages = (target / package_size).to_integral_value(rounding=ROUND_CEILING)
    return packages * package_size


def calculate_recommended_purchase_quantity(
    forecast_demand: Decimal,
    safety_stock: Decimal,
    current_stock: Decimal,
    incoming_quantity: Decimal,
    package_size: Decimal,
    min_order_quantity: Decimal,
) -> Decimal:
    for name, value in (
        ("forecast_demand", forecast_demand),
        ("safety_stock", safety_stock),
        ("current_stock", current_stock),
        ("incoming_quantity", incoming_quantity),
    ):
        _require_nonnegative(name, value)

    required_quantity = (
        forecast_demand + safety_stock - current_stock - incoming_quantity
    )
    return round_purchase_quantity(
        required_quantity,
        package_size,
        min_order_quantity,
    )


def calculate_estimated_cost(
    recommended_purchase_quantity: Decimal,
    unit_price: Decimal | None,
) -> Decimal | None:
    _require_nonnegative(
        "recommended_purchase_quantity",
        recommended_purchase_quantity,
    )
    if unit_price is None:
        return None
    _require_nonnegative("unit_price", unit_price)
    return (recommended_purchase_quantity * unit_price).quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP,
    )


def calculate_stockout_date(
    as_of: datetime.date,
    current_stock: Decimal,
    incoming_quantity: Decimal,
    average_daily_consumption: Decimal,
) -> datetime.date | None:
    _require_nonnegative("current_stock", current_stock)
    _require_nonnegative("incoming_quantity", incoming_quantity)
    _require_nonnegative("average_daily_consumption", average_daily_consumption)
    if average_daily_consumption == 0:
        return None

    available_quantity = current_stock + incoming_quantity
    days_until_stockout = (
        available_quantity / average_daily_consumption
    ).to_integral_value(rounding=ROUND_CEILING)
    return as_of + datetime.timedelta(days=int(days_until_stockout))


def calculate_recommended_order_date(
    as_of: datetime.date,
    current_stock: Decimal,
    incoming_quantity: Decimal,
    average_daily_consumption: Decimal,
    reorder_point: Decimal,
) -> datetime.date | None:
    for name, value in (
        ("current_stock", current_stock),
        ("incoming_quantity", incoming_quantity),
        ("average_daily_consumption", average_daily_consumption),
        ("reorder_point", reorder_point),
    ):
        _require_nonnegative(name, value)
    if average_daily_consumption == 0:
        return None

    quantity_above_reorder_point = current_stock + incoming_quantity - reorder_point
    if quantity_above_reorder_point <= 0:
        return as_of

    days_until_reorder = (
        quantity_above_reorder_point / average_daily_consumption
    ).to_integral_value(rounding=ROUND_FLOOR)
    return as_of + datetime.timedelta(days=int(days_until_reorder))


def calculate_forecast(inputs: ForecastInputs) -> ForecastMetrics:
    forecast_demand = calculate_forecast_demand(
        inputs.average_daily_consumption,
        inputs.horizon_days,
    )
    safety_stock = calculate_safety_stock(
        inputs.average_daily_consumption,
        inputs.safety_stock_days,
    )
    reorder_point = calculate_reorder_point(
        inputs.average_daily_consumption,
        inputs.lead_time_days,
        safety_stock,
    )
    recommended_purchase_quantity = calculate_recommended_purchase_quantity(
        forecast_demand,
        safety_stock,
        inputs.current_stock,
        inputs.incoming_quantity,
        inputs.package_size,
        inputs.min_order_quantity,
    )

    return ForecastMetrics(
        period_from=inputs.as_of,
        period_to=inputs.as_of + datetime.timedelta(days=inputs.horizon_days - 1),
        period_days=inputs.horizon_days,
        average_daily_consumption=inputs.average_daily_consumption,
        forecast_demand=forecast_demand,
        current_stock=inputs.current_stock,
        incoming_quantity=inputs.incoming_quantity,
        safety_stock=safety_stock,
        reorder_point=reorder_point,
        recommended_purchase_quantity=recommended_purchase_quantity,
        unit_price=inputs.unit_price,
        estimated_cost=calculate_estimated_cost(
            recommended_purchase_quantity,
            inputs.unit_price,
        ),
        recommended_order_date=calculate_recommended_order_date(
            inputs.as_of,
            inputs.current_stock,
            inputs.incoming_quantity,
            inputs.average_daily_consumption,
            reorder_point,
        ),
        stockout_date=calculate_stockout_date(
            inputs.as_of,
            inputs.current_stock,
            inputs.incoming_quantity,
            inputs.average_daily_consumption,
        ),
    )
