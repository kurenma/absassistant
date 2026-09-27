from decimal import Decimal


def calculate_average_daily_consumption(
    total_consumption: Decimal, days: int
) -> Decimal:

    if days <= 0:
        raise ValueError(f"days must be positive, got {days}")

    return total_consumption / days


def calculate_days_of_stock(
    current_stock: Decimal, average_daily_consumption: Decimal
) -> Decimal | None:

    if average_daily_consumption <= 0:
        return None

    if current_stock <= 0:
        return Decimal("0")

    return current_stock / average_daily_consumption
