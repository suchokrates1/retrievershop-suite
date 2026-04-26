"""Modele zwrotow."""

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import relationship

from .base import Base


class Return(Base):
    """Zwrot produktu dla zamowienia."""

    __tablename__ = "returns"
    __table_args__ = (
        Index("idx_returns_order_id", "order_id"),
        Index("idx_returns_status", "status"),
        Index("idx_returns_created_at", "created_at"),
    )

    id = Column(Integer, primary_key=True)
    order_id = Column(String, ForeignKey("orders.order_id", ondelete="CASCADE"), nullable=False)
    status = Column(String, nullable=False, default="pending")
    customer_name = Column(String, nullable=True)
    items_json = Column(Text, nullable=True)
    return_tracking_number = Column(String, nullable=True)
    return_carrier = Column(String, nullable=True)
    allegro_return_id = Column(String, nullable=True)
    messenger_notified = Column(Boolean, default=False, nullable=False)
    stock_restored = Column(Boolean, default=False, nullable=False)
    refund_processed = Column(Boolean, default=False, nullable=False)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())

    order = relationship("Order")


class ReturnStatusLog(Base):
    """Historia zmian statusu zwrotu."""

    __tablename__ = "return_status_logs"
    __table_args__ = (Index("idx_return_status_logs_return_id", "return_id"),)

    id = Column(Integer, primary_key=True)
    return_id = Column(Integer, ForeignKey("returns.id", ondelete="CASCADE"), nullable=False)
    status = Column(String, nullable=False)
    notes = Column(Text, nullable=True)
    timestamp = Column(DateTime, nullable=False, server_default=func.now())

    return_record = relationship("Return")


__all__ = ["Return", "ReturnStatusLog"]
