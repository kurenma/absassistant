from datetime import date
from decimal import Decimal
from unittest.mock import Mock

from app.api.routes import forecast as forecast_api
from app.calculations.forecast import ForecastMetrics
from app.main import app
from app.services.forecast import (
    ForecastExplanationData,
    ForecastResult,
    ForecastWarningData,
)
from app.services.movements import ProductNotFoundError


def make_forecast_result():
    return ForecastResult(
        sku="OIL-001",
        name="Massage oil",
        unit="l",
        location="MS-01",
        metrics=ForecastMetrics(
            period_from=date(2026, 10, 1),
            period_to=date(2026, 10, 30),
            period_days=30,
            average_daily_consumption=Decimal("1.5"),
            forecast_demand=Decimal("45"),
            current_stock=Decimal("10"),
            incoming_quantity=Decimal("5"),
            safety_stock=Decimal("7.5"),
            reorder_point=Decimal("18"),
            recommended_purchase_quantity=Decimal("40"),
            unit_price=Decimal("100.00"),
            estimated_cost=Decimal("4000.00"),
            recommended_order_date=date(2026, 10, 1),
            stockout_date=date(2026, 10, 11),
        ),
        explanation=ForecastExplanationData(
            data_used=["Movements"],
            formulas=["forecast = average * days"],
            assumptions=["One month is treated as 30 days."],
            as_of=date(2026, 9, 15),
        ),
        warnings=[
            ForecastWarningData(
                level="warning",
                message="Current stock is below the reorder point.",
            )
        ],
    )


def test_create_forecast_returns_calculation(client, monkeypatch):
    mock_build = Mock(return_value=make_forecast_result())
    monkeypatch.setattr(forecast_api, "build_forecast", mock_build)

    response = client.post(
        "/api/forecast",
        json={
            "sku": "OIL-001",
            "location": "MS-01",
            "horizon_months": 1,
            "safety_stock_days": 5,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["period"] == {
        "from": "2026-10-01",
        "to": "2026-10-30",
        "days": 30,
    }
    assert Decimal(body["recommended_purchase_qty"]) == Decimal("40")
    assert Decimal(body["estimated_cost"]) == Decimal("4000.00")
    assert body["warnings"][0]["level"] == "warning"
    assert body["explanation"]["as_of"] == "2026-09-15"

    call_kwargs = mock_build.call_args.kwargs
    assert call_kwargs["sku"] == "OIL-001"
    assert call_kwargs["location_code"] == "MS-01"
    assert call_kwargs["horizon_days"] is None
    assert call_kwargs["horizon_months"] == 1
    assert call_kwargs["safety_stock_days"] == 5
    assert "session" in call_kwargs


def test_create_forecast_rejects_missing_or_multiple_horizons(client, monkeypatch):
    mock_build = Mock()
    monkeypatch.setattr(forecast_api, "build_forecast", mock_build)

    base = {
        "sku": "OIL-001",
        "location": "MS-01",
        "safety_stock_days": 5,
    }
    missing = client.post("/api/forecast", json=base)
    multiple = client.post(
        "/api/forecast",
        json={**base, "horizon_days": 30, "horizon_months": 1},
    )

    assert missing.status_code == 422
    assert multiple.status_code == 422
    mock_build.assert_not_called()


def test_create_forecast_returns_404_for_unknown_product(client, monkeypatch):
    mock_build = Mock(side_effect=ProductNotFoundError("UNKNOWN"))
    monkeypatch.setattr(forecast_api, "build_forecast", mock_build)

    response = client.post(
        "/api/forecast",
        json={
            "sku": "UNKNOWN",
            "location": "MS-01",
            "horizon_days": 14,
            "safety_stock_days": 5,
        },
    )

    assert response.status_code == 404
    assert response.json() == {
        "detail": {"code": "product_not_found", "sku": "UNKNOWN"}
    }


def test_openapi_documents_forecast_endpoint():
    operation = app.openapi()["paths"]["/api/forecast"]["post"]

    assert operation["tags"] == ["forecast"]
    assert {"200", "404", "422"} <= set(operation["responses"])
