import datetime
import enum
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True)
    sku: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    unit: Mapped[str] = mapped_column(String(8))
    lead_time_days: Mapped[int] = mapped_column(nullable=False)
    package_size: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    min_order_quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)

    batches: Mapped[list["Batch"]] = relationship(back_populates="product")
    purchase_orders: Mapped[list["PurchaseOrder"]] = relationship(
        back_populates="product"
    )

    __table_args__ = (
        CheckConstraint(
            "lead_time_days >= 0",
            name="ck_products_lead_time_days_nonnegative",
        ),
        CheckConstraint(
            "package_size > 0",
            name="ck_products_package_size_positive",
        ),
        CheckConstraint(
            "min_order_quantity > 0",
            name="ck_products_min_order_quantity_positive",
        ),
    )


class Location(Base):
    __tablename__ = "locations"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(64))

    batches: Mapped[list["Batch"]] = relationship(back_populates="location")
    purchase_orders: Mapped[list["PurchaseOrder"]] = relationship(
        back_populates="location"
    )


class Batch(Base):
    __tablename__ = "batches"

    id: Mapped[int] = mapped_column(primary_key=True)
    batch_number: Mapped[str] = mapped_column(String(64))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    location_id: Mapped[int] = mapped_column(ForeignKey("locations.id"))
    produced_at: Mapped[datetime.date] = mapped_column()
    expires_at: Mapped[datetime.date] = mapped_column()
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2))

    product: Mapped["Product"] = relationship(back_populates="batches")
    location: Mapped["Location"] = relationship(back_populates="batches")
    allocations: Mapped[list["MovementAllocation"]] = relationship(
        back_populates="batch"
    )

    __table_args__ = (
        CheckConstraint("unit_price >= 0", name="ck_batches_unit_price_nonnegative"),
        CheckConstraint(
            "produced_at <= expires_at", name="ck_batches_produced_expires_ratio"
        ),
        UniqueConstraint(
            "product_id",
            "location_id",
            "batch_number",
            name="uq_batches_product_location_number",
        ),
    )


class MovementType(enum.Enum):
    RECEIPT = "receipt"
    CONSUME = "consume"
    WRITEOFF = "writeoff"
    RETURN = "return"
    CORRECTION = "correction"


class SupplyStatus(enum.Enum):
    IN_TRANSIT = "in_transit"
    RECEIVED = "received"
    CANCELLED = "cancelled"


class Movement(Base):
    __tablename__ = "movements"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    location_id: Mapped[int] = mapped_column(ForeignKey("locations.id"))
    type: Mapped[MovementType] = mapped_column(Enum(MovementType, name="mv_types"))
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    document_number: Mapped[str] = mapped_column(String(128), unique=True)
    occurred_at: Mapped[datetime.date] = mapped_column()
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    allocations: Mapped[list["MovementAllocation"]] = relationship(
        back_populates="movement"
    )

    __table_args__ = (
        CheckConstraint(
            "quantity > 0 OR (type = 'CORRECTION' AND quantity < 0)",
            name="ck_movements_quantity_sign_by_type",
        ),
    )


class MovementAllocation(Base):
    __tablename__ = "movements_allocations"

    id: Mapped[int] = mapped_column(primary_key=True)
    movement_id: Mapped[int] = mapped_column(ForeignKey("movements.id"))
    batch_id: Mapped[int] = mapped_column(ForeignKey("batches.id"))
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3))

    movement: Mapped["Movement"] = relationship(back_populates="allocations")
    batch: Mapped["Batch"] = relationship(back_populates="allocations")

    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_movements_allocations_positiveonly"),
        UniqueConstraint(
            "batch_id", "movement_id", name="uq_movements_allocations_movement_batch"
        ),
    )


class PurchaseOrder(Base):
    __tablename__ = "purchase_orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    location_id: Mapped[int] = mapped_column(ForeignKey("locations.id"), nullable=False)
    document_number: Mapped[str] = mapped_column(String(128), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    expected_at: Mapped[datetime.date] = mapped_column(nullable=False)
    status: Mapped[SupplyStatus] = mapped_column(
        Enum(SupplyStatus, name="supply_status"), nullable=False
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    product: Mapped["Product"] = relationship(back_populates="purchase_orders")
    location: Mapped["Location"] = relationship(back_populates="purchase_orders")

    __table_args__ = (
        CheckConstraint(
            "quantity > 0",
            name="ck_purchase_orders_quantity_positive",
        ),
        CheckConstraint(
            "unit_price >= 0",
            name="ck_purchase_orders_unit_price_nonnegative",
        ),
        UniqueConstraint(
            "document_number",
            name="uq_purchase_orders_document_number",
        ),
        Index(
            "ix_purchase_orders_forecast_lookup",
            "product_id",
            "location_id",
            "status",
            "expected_at",
        ),
    )
