"""Modele drukowania, kolejek etykiet i logow skanowania."""

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import relationship

from .base import Base


class PrintedOrder(Base):
    __tablename__ = "printed_orders"

    order_id = Column(String, primary_key=True)
    printed_at = Column(String)
    last_order_data = Column(Text)


class LabelQueue(Base):
    __tablename__ = "label_queue"

    id = Column(Integer, primary_key=True)
    order_id = Column(String)
    label_data = Column(Text)
    ext = Column(String)
    last_order_data = Column(Text)
    queued_at = Column(String)
    status = Column(String, default="queued")
    retry_count = Column(Integer, default=0)


class ScanLog(Base):
    """Log skanow kodow i etykiet."""

    __tablename__ = "scan_logs"
    __table_args__ = (
        Index("idx_scan_logs_created_at", "created_at"),
        Index("idx_scan_logs_scan_type", "scan_type"),
    )

    id = Column(Integer, primary_key=True)
    scan_type = Column(String, nullable=False)
    barcode = Column(String, nullable=False)
    success = Column(Boolean, nullable=False)
    result_data = Column(Text)
    error_message = Column(String)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    user = relationship("User")


__all__ = ["LabelQueue", "PrintedOrder", "ScanLog"]
