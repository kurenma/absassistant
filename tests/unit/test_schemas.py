from datetime import date, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from product import MV_TYPES
from schemas import MovementCreate


def _today_minus(days: int = 1) -> date:
    return date.today() - timedelta(days=days)


def make_payload(**overrides) -> dict:

    payload = {
        "sku": "SKU-1",
        "location": "NN-1",
        "document_number": "DOC-1",
        "type": MV_TYPES.RECEIPT,
        "quantity": Decimal("5"),
        "occurred_at": _today_minus(1),
        "batch_number": "LOT-1",
    }
    payload.update(overrides)
    return payload


def test_valid_receipt_is_created():

    movement = MovementCreate(**make_payload(type="receipt"))

    assert movement.type == MV_TYPES.RECEIPT
    assert movement.batch_number == "LOT-1"
    assert movement.quantity == Decimal("5")


def test_valid_consume_without_batch_number():

    movement = MovementCreate(**make_payload(type="consume", batch_number=None))

    assert movement.type == MV_TYPES.CONSUME


def test_negative_correction_is_allowed():

    movement = MovementCreate(**make_payload(type="correction", quantity=Decimal("-3")))

    assert movement.type == MV_TYPES.CORRECTION
    assert movement.quantity == Decimal("-3")


@pytest.mark.parametrize(
    "mv_type",
    [MV_TYPES.RECEIPT, MV_TYPES.CONSUME, MV_TYPES.WRITEOFF, MV_TYPES.RETURN],
)
def test_non_correction_quantity_must_be_positive(mv_type):

    overrides = {"type": mv_type, "quantity": Decimal("-5")}

    with pytest.raises(ValidationError):
        MovementCreate(**make_payload(**overrides))


def test_correction_quantity_cannot_be_zero():

    with pytest.raises(ValidationError):
        MovementCreate(**make_payload(type=MV_TYPES.CORRECTION, quantity=Decimal("0")))


@pytest.mark.parametrize(
    "mv_type",
    [MV_TYPES.RECEIPT, MV_TYPES.CORRECTION, MV_TYPES.WRITEOFF, MV_TYPES.RETURN],
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
