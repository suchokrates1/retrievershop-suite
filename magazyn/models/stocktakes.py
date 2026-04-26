"""Modele remanentu."""

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import relationship

from .base import Base


class Stocktake(Base):
    """Sesja remanentu."""

    __tablename__ = "stocktakes"
    __table_args__ = (Index("idx_stocktakes_status", "status"),)

    id = Column(Integer, primary_key=True)
    started_at = Column(DateTime, nullable=False, server_default=func.now())
    finished_at = Column(DateTime, nullable=True)
    status = Column(String, nullable=False, default="in_progress")
    notes = Column(Text, nullable=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    user = relationship("User")
    items = relationship("StocktakeItem", back_populates="stocktake", cascade="all, delete-orphan")


class StocktakeItem(Base):
    """Pozycja remanentu."""

    __tablename__ = "stocktake_items"
    __table_args__ = (
        Index("idx_stocktake_items_stocktake_id", "stocktake_id"),
        Index("idx_stocktake_items_product_size_id", "stocktake_id", "product_size_id"),
    )

    id = Column(Integer, primary_key=True)
    stocktake_id = Column(
        Integer,
        ForeignKey("stocktakes.id", ondelete="CASCADE"),
        nullable=False,
    )
    product_size_id = Column(
        Integer,
        ForeignKey("product_sizes.id", ondelete="CASCADE"),
        nullable=False,
    )
    expected_qty = Column(Integer, nullable=False, default=0)
    scanned_qty = Column(Integer, nullable=False, default=0)
    scanned_at = Column(DateTime, nullable=True)

    stocktake = relationship("Stocktake", back_populates="items")
    product_size = relationship("ProductSize")


__all__ = ["Stocktake", "StocktakeItem"]
