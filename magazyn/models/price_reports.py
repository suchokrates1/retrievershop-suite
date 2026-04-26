"""Modele raportow cenowych."""

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Index, Integer, Numeric, String, UniqueConstraint, func
from sqlalchemy.orm import relationship

from .base import Base


class PriceReport(Base):
    """Raport cenowy konkurencji."""

    __tablename__ = "price_reports"
    __table_args__ = (
        Index("idx_price_reports_created_at", "created_at"),
        Index("idx_price_reports_status", "status"),
    )

    id = Column(Integer, primary_key=True)
    status = Column(String, nullable=False, default="pending")
    items_total = Column(Integer, nullable=False, default=0)
    items_checked = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    completed_at = Column(DateTime, nullable=True)

    items = relationship("PriceReportItem", back_populates="report", cascade="all, delete-orphan")


class PriceReportItem(Base):
    """Pojedynczy wpis w raporcie cenowym."""

    __tablename__ = "price_report_items"
    __table_args__ = (
        UniqueConstraint("report_id", "offer_id", name="uq_price_report_items_report_offer"),
        Index("idx_price_report_items_report_id", "report_id"),
        Index("idx_price_report_items_offer_id", "offer_id"),
        Index("idx_price_report_items_is_cheapest", "is_cheapest"),
    )

    id = Column(Integer, primary_key=True)
    report_id = Column(Integer, ForeignKey("price_reports.id", ondelete="CASCADE"), nullable=False)
    offer_id = Column(String, nullable=False)
    product_name = Column(String, nullable=True)
    our_price = Column(Numeric(10, 2), nullable=True)
    competitor_price = Column(Numeric(10, 2), nullable=True)
    competitor_seller = Column(String, nullable=True)
    competitor_url = Column(String, nullable=True)
    is_cheapest = Column(Boolean, nullable=False, default=True)
    price_difference = Column(Float, nullable=True)
    our_position = Column(Integer, nullable=True)
    total_offers = Column(Integer, nullable=True)
    competitors_all_count = Column(Integer, nullable=True)
    competitor_is_super_seller = Column(Boolean, nullable=True)
    checked_at = Column(DateTime, nullable=False, server_default=func.now())
    error = Column(String, nullable=True)

    report = relationship("PriceReport", back_populates="items")


class ExcludedSeller(Base):
    """Sprzedawca wykluczony z analizy konkurencji."""

    __tablename__ = "excluded_sellers"

    id = Column(Integer, primary_key=True)
    seller_name = Column(String, unique=True, nullable=False)
    excluded_at = Column(DateTime, nullable=False, server_default=func.now())
    reason = Column(String, nullable=True)


__all__ = ["ExcludedSeller", "PriceReport", "PriceReportItem"]
