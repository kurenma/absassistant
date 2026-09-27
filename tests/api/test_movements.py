from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from api import movements as movement_api
from calculation.fefo import InsufficientStockError
from main import app
from product import MV_TYPES
from services.movements import (
    BatchNotFoundError,
    DocumentAlreadyExistsError,
    InsufficientBatchStockError,
    LocationNotFoundError,
    ProductNotFoundError,
)


def make_payload(**overrides) -> dict:
    payload = {
        "sku": "SKU-1",
        "location": "MAIN",
        "type": "receipt",
        "quantity": "5",
        "batch_number": "LOT-1",
        "document_number": "DOC-1",
        "occurred_at": "2026-09-01",
    }

    payload.update(overrides)
    return payload


def test_create_movement_returns_201(client, monkeypatch):
    fake_movement = SimpleNamespace(
        id=42,
        document_number="DOC-1",
        type=MV_TYPES.RECEIPT,
        quantity=Decimal("5"),
        occurred_at=date(2026, 9, 1),
    )

    mock_register = Mock(return_value=(fake_movement, Decimal("15")))
    monkeypatch.setattr(movement_api, "register_movement", mock_register)

    response = client.post("/api/movements", json=make_payload())

    assert response.status_code == 201

    body = response.json()
    assert body == {
        "id": 42,
        "document_number": "DOC-1",
        "type": "receipt",
        "quantity": "5",
        "occurred_at": "2026-09-01",
        "stock_after": "15",
    }

    mock_register.assert_called_once()
    call_kwargs = mock_register.call_args.kwargs
    assert call_kwargs["sku"] == "SKU-1"
    assert call_kwargs["location_code"] == "MAIN"
    assert call_kwargs["document_number"] == "DOC-1"
    assert call_kwargs["mv_type"] == MV_TYPES.RECEIPT
    assert call_kwargs["quantity"] == Decimal("5")
    assert call_kwargs["operation_date"] == date(2026, 9, 1)
    assert call_kwargs["batch_number"] == "LOT-1"
    assert "session" in call_kwargs


def test_invalid_payload_returns_422_without_calling_service(client, monkeypatch):
    mock_register = Mock()
    monkeypatch.setattr(movement_api, "register_movement", mock_register)

    response = client.post(
        "/api/movements",
        json=make_payload(quantity="0"),
    )

    assert response.status_code == 422
    assert "detail" in response.json()
    mock_register.assert_not_called()


@pytest.mark.parametrize(
    ("error", "expected_detail"),
    [
        (
            ProductNotFoundError("SKU-1"),
            {"code": "product_not_found", "sku": "SKU-1"},
        ),
        (
            LocationNotFoundError("MAIN"),
            {"code": "location_not_found", "location_code": "MAIN"},
        ),
        (
            BatchNotFoundError("LOT-1"),
            {"code": "batch_not_found", "batch_number": "LOT-1"},
        ),
    ],
)
def test_not_found_errors_return_404(
    client,
    monkeypatch,
    error,
    expected_detail,
):
    mock_register = Mock(side_effect=error)
    monkeypatch.setattr(movement_api, "register_movement", mock_register)

    response = client.post("/api/movements", json=make_payload())

    assert response.status_code == 404
    assert response.json() == {"detail": expected_detail}


def test_duplicate_document_returns_409(client, monkeypatch):
    mock_register = Mock(side_effect=DocumentAlreadyExistsError("DOC-1"))
    monkeypatch.setattr(movement_api, "register_movement", mock_register)

    response = client.post("/api/movements", json=make_payload())

    assert response.status_code == 409
    assert response.json() == {
        "detail": {
            "code": "document_already_exists",
            "document_number": "DOC-1",
        }
    }


def test_insufficient_stock_returns_422(client, monkeypatch):
    mock_register = Mock(
        side_effect=InsufficientStockError(
            requested_quantity=Decimal("8.5"),
            available_quantity=Decimal("7.5"),
        )
    )
    monkeypatch.setattr(movement_api, "register_movement", mock_register)

    response = client.post(
        "/api/movements",
        json=make_payload(
            type="consume",
            quantity="8.5",
            batch_number=None,
        ),
    )

    assert response.status_code == 422
    assert response.json() == {
        "detail": {
            "code": "insufficient_stock",
            "requested_quantity": "8.5",
            "available_quantity": "7.5",
        }
    }


def test_insufficient_batch_stock_returns_422(client, monkeypatch):
    mock_register = Mock(
        side_effect=InsufficientBatchStockError(
            batch_id=42,
            available_quantity=Decimal("1"),
            requested_quantity=Decimal("2"),
        )
    )
    monkeypatch.setattr(movement_api, "register_movement", mock_register)

    response = client.post(
        "/api/movements",
        json=make_payload(type="writeoff", quantity="2"),
    )

    assert response.status_code == 422
    assert response.json() == {
        "detail": {
            "code": "insufficient_batch_stock",
            "batch_id": 42,
            "requested_quantity": "2",
            "available_quantity": "1",
        }
    }


def test_openapi_documents_movement_responses():
    operation = app.openapi()["paths"]["/api/movements"]["post"]

    assert {"201", "404", "409", "422"} <= set(operation["responses"])


def test_get_movements_returns_filtered_items(client, monkeypatch):
    fake_movement = SimpleNamespace(
        id=42,
        document_number="DOC-1",
        type=MV_TYPES.CONSUME,
        quantity=Decimal("2.5"),
        occurred_at=date(2026, 9, 10),
        created_at=datetime(2026, 9, 10, 12, 30, tzinfo=timezone.utc),
    )
    mock_list = Mock(return_value=([(fake_movement, "SKU-1", "MAIN")], 17))
    monkeypatch.setattr(movement_api, "list_movements", mock_list)

    response = client.get(
        "/api/movements",
        params={
            "sku": "SKU-1",
            "location": "MAIN",
            "type": "consume",
            "date_from": "2026-09-01",
            "date_to": "2026-09-30",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 17
    assert body["limit"] == 50
    assert body["offset"] == 0
    assert len(body["items"]) == 1
    item = body["items"][0]
    assert item["id"] == 42
    assert item["sku"] == "SKU-1"
    assert item["location"] == "MAIN"
    assert item["type"] == "consume"
    assert Decimal(item["quantity"]) == Decimal("2.5")
    assert item["document_number"] == "DOC-1"
    assert item["occurred_at"] == "2026-09-10"
    assert datetime.fromisoformat(
        item["created_at"].replace("Z", "+00:00")
    ) == datetime(2026, 9, 10, 12, 30, tzinfo=timezone.utc)

    call_kwargs = mock_list.call_args.kwargs
    assert call_kwargs["sku"] == "SKU-1"
    assert call_kwargs["location_code"] == "MAIN"
    assert call_kwargs["mv_type"] == MV_TYPES.CONSUME
    assert call_kwargs["date_from"] == date(2026, 9, 1)
    assert call_kwargs["date_to"] == date(2026, 9, 30)
    assert call_kwargs["limit"] == 50
    assert call_kwargs["offset"] == 0
    assert "session" in call_kwargs


def test_get_movements_returns_empty_list(client, monkeypatch):
    mock_list = Mock(return_value=([], 0))
    monkeypatch.setattr(movement_api, "list_movements", mock_list)

    response = client.get("/api/movements", params={"sku": "UNKNOWN"})

    assert response.status_code == 200
    assert response.json() == {
        "items": [],
        "total": 0,
        "limit": 50,
        "offset": 0,
    }
    mock_list.assert_called_once()


def test_get_movements_rejects_reversed_date_range(client, monkeypatch):
    mock_list = Mock()
    monkeypatch.setattr(movement_api, "list_movements", mock_list)

    response = client.get(
        "/api/movements",
        params={
            "date_from": "2026-09-30",
            "date_to": "2026-09-01",
        },
    )

    assert response.status_code == 422
    assert response.json() == {
        "detail": {
            "code": "invalid_date_range",
            "date_from": "2026-09-30",
            "date_to": "2026-09-01",
        }
    }
    mock_list.assert_not_called()


def test_get_movements_rejects_unknown_movement_type(client, monkeypatch):
    mock_list = Mock()
    monkeypatch.setattr(movement_api, "list_movements", mock_list)

    response = client.get("/api/movements", params={"type": "transfer"})

    assert response.status_code == 422
    mock_list.assert_not_called()


@pytest.mark.parametrize(
    "params",
    [
        {"limit": 0},
        {"limit": 101},
        {"offset": -1},
    ],
)
def test_get_movements_rejects_invalid_pagination(client, monkeypatch, params):
    mock_list = Mock()
    monkeypatch.setattr(movement_api, "list_movements", mock_list)

    response = client.get("/api/movements", params=params)

    assert response.status_code == 422
    mock_list.assert_not_called()


def test_openapi_documents_get_movement_filters():
    operation = app.openapi()["paths"]["/api/movements"]["get"]
    parameter_names = {parameter["name"] for parameter in operation["parameters"]}

    assert {
        "sku",
        "location",
        "type",
        "date_from",
        "date_to",
        "limit",
        "offset",
    } <= parameter_names
