from decimal import Decimal

import pytest

from app.calculations.stock_metrics import (
    calculate_average_daily_consumption,
    calculate_days_of_stock,
)


def test_calculate_average_daily_consumption():
    result = calculate_average_daily_consumption(
        total_consumption=Decimal("122.58"),
        days=90,
    )

    assert result == Decimal("1.362")


@pytest.mark.parametrize("days", [0, -1])
def test_average_daily_consumption_requires_positive_period(days):
    with pytest.raises(ValueError, match="days must be positive"):
        calculate_average_daily_consumption(Decimal("10"), days)


def test_calculate_days_of_stock():
    result = calculate_days_of_stock(
        current_stock=Decimal("15"),
        average_daily_consumption=Decimal("2.5"),
    )

    assert result == Decimal("6")


@pytest.mark.parametrize("average", [Decimal("0"), Decimal("-1")])
def test_days_of_stock_is_unknown_without_positive_consumption(average):
    result = calculate_days_of_stock(
        current_stock=Decimal("15"),
        average_daily_consumption=average,
    )

    assert result is None


@pytest.mark.parametrize("stock", [Decimal("0"), Decimal("-1")])
def test_days_of_stock_is_zero_without_available_stock(stock):
    result = calculate_days_of_stock(
        current_stock=stock,
        average_daily_consumption=Decimal("2.5"),
    )

    assert result == Decimal("0")
