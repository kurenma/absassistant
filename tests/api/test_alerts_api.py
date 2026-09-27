from datetime import date
from decimal import Decimal
from unittest.mock import Mock

from api import alerts as alerts_api
from main import app
from services.alerts import AlertResult


def test_get_alerts_returns_serialized_indicators(client, monkeypatch):
    result = AlertResult(
        type="expiry",
        level="critical",
        sku="OIL-001",
        location="MS-01",
        message="Batch has expired.",
        indicators={
            "batch_number": "LOT-1",
            "quantity": Decimal("8.500"),
            "expires_at": date(2026, 9, 14),
            "days_until_expiry": -1,
            "optional": None,
        },
    )
    mock_list = Mock(return_value=[result])
    monkeypatch.setattr(alerts_api, "list_alerts", mock_list)
    monkeypatch.setattr(
        alerts_api, "date", Mock(today=Mock(return_value=date(2026, 9, 15)))
    )

    response = client.get(
        "/api/alerts",
        params={
            "location": "MS-01",
            "expiry_days": 15,
            "inactivity_days": 45,
        },
    )

    assert response.status_code == 200
    assert response.json() == [
        {
            "type": "expiry",
            "level": "critical",
            "sku": "OIL-001",
            "location": "MS-01",
            "message": "Batch has expired.",
            "indicators": {
                "batch_number": "LOT-1",
                "quantity": "8.500",
                "expires_at": "2026-09-14",
                "days_until_expiry": -1,
                "optional": None,
            },
        }
    ]
    call_kwargs = mock_list.call_args.kwargs
    assert call_kwargs["as_of"] == date(2026, 9, 15)
    assert call_kwargs["location_code"] == "MS-01"
    assert call_kwargs["expiry_warning_days"] == 15
    assert call_kwargs["inactivity_days"] == 45


def test_get_alerts_rejects_invalid_thresholds(client, monkeypatch):
    mock_list = Mock()
    monkeypatch.setattr(alerts_api, "list_alerts", mock_list)

    zero = client.get("/api/alerts", params={"expiry_days": 0})
    too_large = client.get("/api/alerts", params={"inactivity_days": 366})

    assert zero.status_code == 422
    assert too_large.status_code == 422
    mock_list.assert_not_called()


def test_openapi_documents_alerts_endpoint():
    operation = app.openapi()["paths"]["/api/alerts"]["get"]

    assert operation["tags"] == ["alerts"]
    assert {"200", "422"} <= set(operation["responses"])
