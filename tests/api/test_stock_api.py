from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock

from app.api.routes import stock as stock_api
from app.main import app
from app.services.movements import ProductNotFoundError


def test_get_stock_returns_calculated_summaries(client, monkeypatch):
    summaries = [
        SimpleNamespace(
            sku="OIL-001",
            name="Massage oil",
            unit="l",
            location="MS-01",
            current_stock=Decimal("50.39"),
            avg_daily_consumption=Decimal("1.362"),
            days_of_stock=Decimal("37"),
            nearest_expiry=date(2026, 10, 15),
        ),
        SimpleNamespace(
            sku="CREAM-001",
            name="Massage cream",
            unit="kg",
            location="MS-02",
            current_stock=Decimal("12"),
            avg_daily_consumption=Decimal("0"),
            days_of_stock=None,
            nearest_expiry=None,
        ),
    ]
    mock_list_stock = Mock(return_value=summaries)
    monkeypatch.setattr(stock_api, "list_stock", mock_list_stock)

    response = client.get("/api/stock")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 2
    assert body[0]["sku"] == "OIL-001"
    assert body[0]["location"] == "MS-01"
    assert Decimal(body[0]["current_stock"]) == Decimal("50.39")
    assert Decimal(body[0]["avg_daily_consumption"]) == Decimal("1.362")
    assert Decimal(body[0]["days_of_stock"]) == Decimal("37")
    assert body[0]["nearest_expiry"] == "2026-10-15"
    assert body[1]["days_of_stock"] is None
    assert body[1]["nearest_expiry"] is None

    mock_list_stock.assert_called_once()
    call_kwargs = mock_list_stock.call_args.kwargs
    assert call_kwargs["as_of"] == date.today()
    assert "session" in call_kwargs


def test_get_stock_returns_empty_list(client, monkeypatch):
    mock_list_stock = Mock(return_value=[])
    monkeypatch.setattr(stock_api, "list_stock", mock_list_stock)

    response = client.get("/api/stock")

    assert response.status_code == 200
    assert response.json() == []


def test_openapi_documents_stock_endpoint():
    operation = app.openapi()["paths"]["/api/stock"]["get"]

    assert operation["tags"] == ["stock"]
    assert "200" in operation["responses"]


def test_get_stock_detail_returns_locations_and_batches(client, monkeypatch):
    detail = SimpleNamespace(
        sku="OIL-001",
        name="Massage oil",
        unit="l",
        locations=[
            SimpleNamespace(
                location="MS-01",
                current_stock=Decimal("7.5"),
                batches=[
                    SimpleNamespace(
                        batch_number="LOT-1",
                        quantity=Decimal("7.5"),
                        produced_at=date(2026, 8, 1),
                        expires_at=date(2026, 10, 1),
                        unit_price=Decimal("1259.05"),
                        receipt_documents=["DOC-1", "DOC-2"],
                    )
                ],
            )
        ],
    )
    mock_detail = Mock(return_value=detail)
    monkeypatch.setattr(stock_api, "get_stock_detail", mock_detail)

    response = client.get("/api/stock/OIL-001")

    assert response.status_code == 200
    body = response.json()
    assert body["sku"] == "OIL-001"
    assert body["locations"][0]["location"] == "MS-01"
    assert Decimal(body["locations"][0]["current_stock"]) == Decimal("7.5")
    batch = body["locations"][0]["batches"][0]
    assert batch["batch_number"] == "LOT-1"
    assert Decimal(batch["quantity"]) == Decimal("7.5")
    assert Decimal(batch["unit_price"]) == Decimal("1259.05")
    assert batch["produced_at"] == "2026-08-01"
    assert batch["expires_at"] == "2026-10-01"
    assert batch["receipt_documents"] == ["DOC-1", "DOC-2"]

    call_kwargs = mock_detail.call_args.kwargs
    assert call_kwargs["sku"] == "OIL-001"
    assert call_kwargs["as_of"] == date.today()
    assert "session" in call_kwargs


def test_get_stock_detail_returns_404_for_unknown_product(client, monkeypatch):
    mock_detail = Mock(side_effect=ProductNotFoundError("UNKNOWN"))
    monkeypatch.setattr(stock_api, "get_stock_detail", mock_detail)

    response = client.get("/api/stock/UNKNOWN")

    assert response.status_code == 404
    assert response.json() == {
        "detail": {"code": "product_not_found", "sku": "UNKNOWN"}
    }


def test_openapi_documents_stock_detail_endpoint():
    operation = app.openapi()["paths"]["/api/stock/{sku}"]["get"]

    assert operation["tags"] == ["stock"]
    assert {"200", "404", "422"} <= set(operation["responses"])
