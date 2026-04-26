"""Modele zamowien i statusow."""

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, func
from sqlalchemy.orm import relationship

from .base import Base


class Order(Base):
    """Dane zamowienia."""

    __tablename__ = "orders"
    __table_args__ = (
        Index("idx_orders_date_add", "date_add"),
        Index("idx_orders_platform", "platform"),
    )

    order_id = Column(String, primary_key=True)
    external_order_id = Column(String, nullable=True)
    shop_order_id = Column(Integer, nullable=True)
    customer_name = Column(String, nullable=True)
    email = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    user_login = Column(String, nullable=True)
    platform = Column(String, nullable=True)
    order_source_id = Column(Integer, nullable=True)
    order_status_id = Column(Integer, nullable=True)
    confirmed = Column(Boolean, default=False)
    date_add = Column(Integer, nullable=True)
    date_confirmed = Column(Integer, nullable=True)
    date_in_status = Column(Integer, nullable=True)
    delivery_method = Column(String, nullable=True)
    delivery_method_id = Column(Integer, nullable=True)
    delivery_price = Column(Numeric(10, 2), nullable=True)
    delivery_fullname = Column(String, nullable=True)
    delivery_company = Column(String, nullable=True)
    delivery_address = Column(String, nullable=True)
    delivery_city = Column(String, nullable=True)
    delivery_postcode = Column(String, nullable=True)
    delivery_country = Column(String, nullable=True)
    delivery_country_code = Column(String(2), nullable=True)
    delivery_point_id = Column(String, nullable=True)
    delivery_point_name = Column(String, nullable=True)
    delivery_point_address = Column(String, nullable=True)
    delivery_point_postcode = Column(String, nullable=True)
    delivery_point_city = Column(String, nullable=True)
    invoice_fullname = Column(String, nullable=True)
    invoice_company = Column(String, nullable=True)
    invoice_nip = Column(String, nullable=True)
    invoice_address = Column(String, nullable=True)
    invoice_city = Column(String, nullable=True)
    invoice_postcode = Column(String, nullable=True)
    invoice_country = Column(String, nullable=True)
    want_invoice = Column(Boolean, default=False)
    currency = Column(String(3), default="PLN")
    payment_method = Column(String, nullable=True)
    payment_method_cod = Column(Boolean, default=False)
    payment_done = Column(Numeric(10, 2), nullable=True)
    user_comments = Column(Text, nullable=True)
    admin_comments = Column(Text, nullable=True)
    courier_code = Column(String, nullable=True)
    delivery_package_module = Column(String, nullable=True)
    delivery_package_nr = Column(String, nullable=True)
    products_json = Column(Text, nullable=True)
    customer_token = Column(String, nullable=True, unique=True, index=True)
    wfirma_invoice_id = Column(Integer, nullable=True)
    wfirma_invoice_number = Column(String, nullable=True)
    wfirma_correction_id = Column(Integer, nullable=True)
    wfirma_correction_number = Column(String, nullable=True)
    emails_sent = Column(Text, nullable=True)
    real_profit_sale_price = Column(Numeric(10, 2), nullable=True)
    real_profit_purchase_cost = Column(Numeric(10, 2), nullable=True)
    real_profit_packaging_cost = Column(Numeric(10, 2), nullable=True)
    real_profit_allegro_fees = Column(Numeric(10, 2), nullable=True)
    real_profit_amount = Column(Numeric(10, 2), nullable=True)
    real_profit_fee_source = Column(String(32), nullable=True)
    real_profit_shipping_estimated = Column(Boolean, nullable=True)
    real_profit_is_final = Column(Boolean, nullable=True)
    real_profit_error = Column(Text, nullable=True)
    real_profit_updated_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())

    products = relationship("OrderProduct", back_populates="order", cascade="all, delete-orphan")
    status_logs = relationship("OrderStatusLog", back_populates="order", cascade="all, delete-orphan")
    events = relationship("OrderEvent", back_populates="order", cascade="all, delete-orphan")


class OrderProduct(Base):
    """Produkt w zamowieniu."""

    __tablename__ = "order_products"
    __table_args__ = (
        Index("idx_order_products_ean", "ean"),
        Index("idx_order_products_order_id", "order_id"),
    )

    id = Column(Integer, primary_key=True)
    order_id = Column(String, ForeignKey("orders.order_id", ondelete="CASCADE"), nullable=False)
    order_product_id = Column(Integer, nullable=True)
    product_id = Column(String, nullable=True)
    variant_id = Column(String, nullable=True)
    sku = Column(String, nullable=True)
    ean = Column(String, nullable=True)
    name = Column(String, nullable=True)
    quantity = Column(Integer, default=1)
    price_brutto = Column(Numeric(10, 2), nullable=True)
    auction_id = Column(String, nullable=True)
    attributes = Column(Text, nullable=True)
    location = Column(String, nullable=True)
    product_size_id = Column(
        Integer,
        ForeignKey("product_sizes.id", ondelete="SET NULL"),
        nullable=True,
    )

    order = relationship("Order", back_populates="products")
    product_size = relationship("ProductSize")


class OrderStatusLog(Base):
    """Historia statusow zamowienia."""

    __tablename__ = "order_status_logs"
    __table_args__ = (
        Index("idx_order_status_logs_order_id", "order_id"),
        Index("idx_order_status_logs_timestamp", "timestamp"),
    )

    id = Column(Integer, primary_key=True)
    order_id = Column(String, ForeignKey("orders.order_id", ondelete="CASCADE"), nullable=False)
    status = Column(String, nullable=False)
    tracking_number = Column(String, nullable=True)
    courier_code = Column(String, nullable=True)
    timestamp = Column(DateTime, nullable=False, server_default=func.now())
    notes = Column(Text, nullable=True)

    order = relationship("Order", back_populates="status_logs")


class OrderEvent(Base):
    """Surowe zdarzenie z Allegro Order Events API."""

    __tablename__ = "order_events"
    __table_args__ = (
        Index("idx_order_events_order_id", "order_id"),
        Index("idx_order_events_allegro_event_id", "allegro_event_id"),
        Index("idx_order_events_occurred_at", "occurred_at"),
        Index("idx_order_events_event_type", "event_type"),
    )

    id = Column(Integer, primary_key=True)
    order_id = Column(String, ForeignKey("orders.order_id", ondelete="CASCADE"), nullable=False)
    allegro_event_id = Column(String(64), nullable=False, unique=True)
    event_type = Column(String(64), nullable=False)
    occurred_at = Column(DateTime, nullable=False)
    payload_json = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())

    order = relationship("Order", back_populates="events")


__all__ = ["Order", "OrderEvent", "OrderProduct", "OrderStatusLog"]
