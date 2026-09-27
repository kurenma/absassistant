from datetime import date, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.db.models import MovementType
from app.schemas.forecast import ForecastRequest
from app.schemas.movements import MovementCreate


def _today_minus(days: int = 1) -> date:
    return date.today() - timedelta(days=days)


def make_payload(**overrides) -> dict:

    payload = {
        "sku": "SKU-1",
        "location": "NN-1",
        "document_number": "DOC-1",
        "type": MovementType.RECEIPT,
        "quantity": Decimal("5"),
        "occurred_at": _today_minus(1),
        "batch_number": "LOT-1",
    }
    payload.update(overrides)
    return payload


def test_valid_receipt_is_created():

    movement = MovementCreate(**make_payload(type="receipt"))

    assert movement.type == MovementType.RECEIPT
    assert movement.batch_number == "LOT-1"
    assert movement.quantity == Decimal("5")


def test_valid_consume_without_batch_number():

    movement = MovementCreate(**make_payload(type="consume", batch_number=None))

    assert movement.type == MovementType.CONSUME


def test_negative_correction_is_allowed():

    movement = MovementCreate(**make_payload(type="correction", quantity=Decimal("-3")))

    assert movement.type == MovementType.CORRECTION
    assert movement.quantity == Decimal("-3")


@pytest.mark.parametrize(
    "mv_type",
    [
        MovementType.RECEIPT,
        MovementType.CONSUME,
        MovementType.WRITEOFF,
        MovementType.RETURN,
    ],
)
def test_non_correction_quantity_must_be_positive(mv_type):

    overrides = {"type": mv_type, "quantity": Decimal("-5")}

    with pytest.raises(ValidationError):
        MovementCreate(**make_payload(**overrides))


def test_correction_quantity_cannot_be_zero():

    with pytest.raises(ValidationError):
        MovementCreate(
            **make_payload(type=MovementType.CORRECTION, quantity=Decimal("0"))
        )


@pytest.mark.parametrize(
    "mv_type",
    [
        MovementType.RECEIPT,
        MovementType.CORRECTION,
        MovementType.WRITEOFF,
        MovementType.RETURN,
    ],
)
def test_batch_number_is_required_for_explicit_batch_operations(mv_type):

    with pytest.raises(ValidationError):
        MovementCreate(**make_payload(type=mv_type, batch_number=None))


def test_consume_cannot_have_batch_number():

    with pytest.raises(ValidationError):
        MovementCreate(**make_payload(type="consume"))


def test_occurred_at_cannot_be_in_future():

    with pytest.raises(ValidationError):
        MovementCreate(**make_payload(occurred_at=date.today() + timedelta(days=1)))


def test_string_fields_are_stripped():

    overrides = {"sku": " SKU-2 ", "location": " NN-2 ", "document_number": " DOC-2 "}

    movement = MovementCreate(**make_payload(**overrides))

    assert movement.sku == "SKU-2"
    assert movement.location == "NN-2"
    assert movement.document_number == "DOC-2"


def test_blank_required_string_is_rejected():

    with pytest.raises(ValidationError):
        MovementCreate(**make_payload(sku=""))


def test_quantity_rejects_excess_decimal_places():

    with pytest.raises(ValidationError):
        MovementCreate(**make_payload(quantity=Decimal("1.1234")))


@pytest.mark.parametrize(
    "payload",
    [
        {
            "sku": "SKU-1",
            "location": "MAIN",
            "horizon_days": 14,
            "safety_stock_days": 7,
        },
        {
            "sku": "SKU-1",
            "location": "MAIN",
            "horizon_months": 3,
            "safety_stock_days": 7,
        },
    ],
)
def test_forecast_request_accepts_one_horizon(payload):
    request = ForecastRequest(**payload)

    assert request.sku == "SKU-1"


@pytest.mark.parametrize(
    "overrides",
    [
        {},
        {"horizon_days": 14, "horizon_months": 1},
        {"horizon_days": 0},
        {"horizon_months": 0},
        {"horizon_days": 14, "safety_stock_days": -1},
    ],
)
def test_forecast_request_rejects_invalid_horizon(overrides):
    payload = {
        "sku": "SKU-1",
        "location": "MAIN",
        "safety_stock_days": 7,
        **overrides,
    }

    with pytest.raises(ValidationError):
        ForecastRequest(**payload)
