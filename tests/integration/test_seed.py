import datetime

import pytest
from sqlalchemy import func, select

from app.db.models import Batch, Movement, Product, PurchaseOrder
from scripts.seed import seed_database


@pytest.mark.integration
def test_seed_database_is_idempotent_and_creates_demo_dataset(db_session):
    as_of = datetime.date.today()

    seed_database(db_session, as_of)
    seed_database(db_session, as_of)

    product_count = db_session.scalar(
        select(func.count())
        .select_from(Product)
        .where(Product.sku.in_(["OIL-001", "CREAM-001", "TOWEL-001"]))
    )
    batch_count = db_session.scalar(
        select(func.count())
        .select_from(Batch)
        .where(
            Batch.batch_number.in_(["OIL-LOT-001", "CREAM-LOT-001", "TOWEL-LOT-001"])
        )
    )
    movement_count = db_session.scalar(
        select(func.count())
        .select_from(Movement)
        .where(Movement.document_number.like("SEED-%"))
    )
    order_count = db_session.scalar(
        select(func.count())
        .select_from(PurchaseOrder)
        .where(PurchaseOrder.document_number == "SEED-PO-CREAM-001")
    )

    assert product_count == 3
    assert batch_count == 3
    assert movement_count == 6
    assert order_count == 1
