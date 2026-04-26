"""Modele integracji Allegro."""

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, func
from sqlalchemy.orm import relationship

from .base import Base


class AllegroOffer(Base):
    __tablename__ = "allegro_offers"

    id = Column(Integer, primary_key=True)
    offer_id = Column(String, unique=True)
    title = Column(String, nullable=False)
    price = Column(Numeric(10, 2), nullable=False)
    ean = Column(String, nullable=True)
    product_id = Column(
        Integer,
        ForeignKey("products.id", ondelete="SET NULL"),
        nullable=True,
    )
    product_size_id = Column(
        Integer,
        ForeignKey("product_sizes.id", ondelete="SET NULL"),
        nullable=True,
    )
    synced_at = Column(String)
    publication_status = Column(String, default="ACTIVE")

    product = relationship("Product")
    product_size = relationship("ProductSize", back_populates="allegro_offers")


class AllegroPriceHistory(Base):
    __tablename__ = "allegro_price_history"
    __table_args__ = (
        Index("idx_allegro_price_history_recorded_at", "recorded_at"),
        Index("idx_allegro_price_history_offer_recorded_at", "offer_id", "recorded_at"),
        Index("idx_allegro_price_history_product_size", "product_size_id"),
    )

    id = Column(Integer, primary_key=True)
    offer_id = Column(String, index=True)
    product_size_id = Column(
        Integer,
        ForeignKey("product_sizes.id", ondelete="SET NULL"),
        nullable=True,
    )
    price = Column(Numeric(10, 2), nullable=False)
    recorded_at = Column(String, nullable=False)
    competitor_price = Column(Numeric(10, 2), nullable=True)
    competitor_seller = Column(String, nullable=True)
    competitor_url = Column(String, nullable=True)
    competitor_delivery_days = Column(Integer, nullable=True)

    product_size = relationship("ProductSize", back_populates="price_history")


class AllegroBillingType(Base):
    """Slownik typow billingowych Allegro z wersjonowaniem mapowania."""

    __tablename__ = "allegro_billing_types"

    type_id = Column(String(32), primary_key=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    mapping_category = Column(String(64), nullable=True)
    mapping_version = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())
    last_seen_at = Column(DateTime, nullable=False, server_default=func.now())


class AllegroRepliedThread(Base):
    __tablename__ = "allegro_replied_threads"

    thread_id = Column(String, primary_key=True)
    replied_at = Column(DateTime, nullable=False, server_default=func.now())


class AllegroRepliedDiscussion(Base):
    __tablename__ = "allegro_replied_discussions"

    discussion_id = Column(String, primary_key=True)
    replied_at = Column(DateTime, nullable=False, server_default=func.now())


__all__ = [
    "AllegroBillingType",
    "AllegroOffer",
    "AllegroPriceHistory",
    "AllegroRepliedDiscussion",
    "AllegroRepliedThread",
]
