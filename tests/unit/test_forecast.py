from datetime import date
from decimal import Decimal

import pytest

from app.calculations.forecast import (
    ForecastInputs,
    calculate_estimated_cost,
    calculate_forecast,
    calculate_forecast_demand,
    calculate_recommended_order_date,
    calculate_recommended_purchase_quantity,
    calculate_reorder_point,
    calculate_safety_stock,
    calculate_stockout_date,
    resolve_horizon_days,
    round_purchase_quantity,
)


def test_calculate_forecast_demand():
    assert calculate_forecast_demand(Decimal("1.362"), 92) == Decimal("125.304")


def test_calculate_safety_stock_and_reorder_point():
    safety_stock = calculate_safety_stock(Decimal("1.5"), 10)
    reorder_point = calculate_reorder_point(Decimal("1.5"), 7, safety_stock)

    assert safety_stock == Decimal("15.0")
    assert reorder_point == Decimal("25.5")


@pytest.mark.parametrize(
    ("required", "package_size", "minimum", "expected"),
    [
        ("75.1", "5", "20", "80"),
        ("3", "5", "20", "20"),
        ("21", "5", "22", "25"),
        ("0", "5", "20", "0"),
        ("-1", "5", "20", "0"),
    ],
)
def test_round_purchase_quantity(required, package_size, minimum, expected):
    assert round_purchase_quantity(
        Decimal(required),
        Decimal(package_size),
        Decimal(minimum),
    ) == Decimal(expected)


def test_calculate_recommended_purchase_quantity_applies_stock_and_incoming():
    result = calculate_recommended_purchase_quantity(
        forecast_demand=Decimal("100"),
        safety_stock=Decimal("20"),
        current_stock=Decimal("30"),
        incoming_quantity=Decimal("15"),
        package_size=Decimal("10"),
        min_order_quantity=Decimal("20"),
    )

    assert result == Decimal("80")


@pytest.mark.parametrize(
    ("days", "months", "expected"),
    [
        (14, None, 14),
        (None, 3, 90),
    ],
)
def test_resolve_horizon_days(days, months, expected):
    assert resolve_horizon_days(days, months) == expected


@pytest.mark.parametrize(
    ("days", "months"),
    [
        (None, None),
        (14, 1),
        (0, None),
        (None, 0),
    ],
)
def test_resolve_horizon_days_rejects_invalid_choice(days, months):
    with pytest.raises(ValueError):
        resolve_horizon_days(days, months)


def test_calculate_estimated_cost_rounds_to_cents():
    assert calculate_estimated_cost(
        Decimal("75"),
        Decimal("1259.055"),
    ) == Decimal("94429.13")


def test_calculate_estimated_cost_is_unknown_without_price():
    assert calculate_estimated_cost(Decimal("75"), None) is None


def test_calculate_stockout_and_recommended_order_dates():
    as_of = date(2026, 9, 15)

    assert calculate_stockout_date(
        as_of,
        current_stock=Decimal("50"),
        incoming_quantity=Decimal("0"),
        average_daily_consumption=Decimal("5"),
    ) == date(2026, 9, 25)
    assert calculate_recommended_order_date(
        as_of,
        current_stock=Decimal("50"),
        incoming_quantity=Decimal("0"),
        average_daily_consumption=Decimal("5"),
        reorder_point=Decimal("15"),
    ) == date(2026, 9, 22)


def test_forecast_dates_are_unknown_without_consumption():
    as_of = date(2026, 9, 15)

    assert (
        calculate_stockout_date(
            as_of,
            Decimal("50"),
            Decimal("10"),
            Decimal("0"),
        )
        is None
    )
    assert (
        calculate_recommended_order_date(
            as_of,
            Decimal("50"),
            Decimal("10"),
            Decimal("0"),
            Decimal("0"),
        )
        is None
    )


def test_calculate_forecast_composes_all_metrics():
    metrics = calculate_forecast(
        ForecastInputs(
            as_of=date(2026, 10, 1),
            horizon_days=30,
            average_daily_consumption=Decimal("2"),
            current_stock=Decimal("20"),
            incoming_quantity=Decimal("10"),
            safety_stock_days=5,
            lead_time_days=7,
            package_size=Decimal("10"),
            min_order_quantity=Decimal("20"),
            unit_price=Decimal("12.50"),
        )
    )

    assert metrics.period_from == date(2026, 10, 1)
    assert metrics.period_to == date(2026, 10, 30)
    assert metrics.forecast_demand == Decimal("60")
    assert metrics.safety_stock == Decimal("10")
    assert metrics.reorder_point == Decimal("24")
    assert metrics.recommended_purchase_quantity == Decimal("40")
    assert metrics.estimated_cost == Decimal("500.00")
    assert metrics.recommended_order_date == date(2026, 10, 4)
    assert metrics.stockout_date == date(2026, 10, 16)


@pytest.mark.parametrize(
    ("function", "args"),
    [
        (calculate_forecast_demand, (Decimal("1"), 0)),
        (calculate_safety_stock, (Decimal("1"), -1)),
        (calculate_reorder_point, (Decimal("1"), -1, Decimal("0"))),
        (round_purchase_quantity, (Decimal("1"), Decimal("0"), Decimal("1"))),
    ],
)
def test_forecast_functions_reject_invalid_parameters(function, args):
    with pytest.raises(ValueError):
        function(*args)
