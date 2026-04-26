"""Modele przesylek i bledow etykiet."""

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import relationship

from .base import Base


class ShipmentError(Base):
    """Blad tworzenia przesylki lub etykiety."""

    __tablename__ = "shipment_errors"
    __table_args__ = (
        Index("idx_shipment_errors_order_id", "order_id"),
        Index("idx_shipment_errors_error_type", "error_type"),
        Index("idx_shipment_errors_delivery_method", "delivery_method"),
        Index("idx_shipment_errors_created_at", "created_at"),
    )

    id = Column(Integer, primary_key=True)
    order_id = Column(String, ForeignKey("orders.order_id", ondelete="CASCADE"), nullable=False)
    error_type = Column(String(64), nullable=False)
    error_code = Column(String(32), nullable=True)
    error_message = Column(Text, nullable=True)
    delivery_method = Column(String(255), nullable=True)
    raw_response = Column(Text, nullable=True)
    resolved = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())

    order = relationship("Order")


__all__ = ["ShipmentError"]
