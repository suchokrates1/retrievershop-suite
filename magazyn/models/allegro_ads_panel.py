"""Snapshoty statystyk Allegro Ads Panel (Sales Center)."""

from sqlalchemy import Column, Date, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.orm import relationship

from .base import Base


class AllegroAdsSnapshot(Base):
    """Pojedynczy przebieg synchronizacji panelu Ads."""

    __tablename__ = "allegro_ads_snapshots"
    __table_args__ = (
        Index("idx_allegro_ads_snapshots_snapshot_date", "snapshot_date"),
        Index("idx_allegro_ads_snapshots_status", "status"),
    )

    id = Column(Integer, primary_key=True)
    snapshot_date = Column(Date, nullable=False)
    marketplace_id = Column(String, nullable=False, default="allegro-pl")
    scope_id_b64 = Column(String, nullable=False)
    period_start = Column(Date, nullable=False)
    period_end = Column(Date, nullable=False)
    status = Column(String, nullable=False, default="ok")
    error_message = Column(Text, nullable=True)
    synced_at = Column(DateTime, nullable=False, server_default=func.now())

    campaigns = relationship("AllegroAdsCampaignDaily", back_populates="snapshot", cascade="all, delete-orphan")
    chart_points = relationship("AllegroAdsChartDaily", back_populates="snapshot", cascade="all, delete-orphan")


class AllegroAdsCampaignDaily(Base):
    """Metryki kampanii z panelu Ads dla danego snapshotu."""

    __tablename__ = "allegro_ads_campaign_daily"
    __table_args__ = (
        UniqueConstraint("snapshot_id", "campaign_entity_id", name="uq_ads_campaign_snapshot_entity"),
        Index("idx_allegro_ads_campaign_daily_entity", "campaign_entity_id"),
    )

    id = Column(Integer, primary_key=True)
    snapshot_id = Column(Integer, ForeignKey("allegro_ads_snapshots.id", ondelete="CASCADE"), nullable=False)
    campaign_entity_id = Column(String, nullable=False)
    campaign_name = Column(String, nullable=False)
    clicks = Column(Integer, nullable=False, default=0)
    impressions = Column(Integer, nullable=False, default=0)
    ctr = Column(Numeric(8, 4), nullable=True)
    cpc = Column(Numeric(10, 2), nullable=True)
    cost = Column(Numeric(12, 2), nullable=False, default=0)
    roi = Column(Numeric(10, 2), nullable=True)
    interest = Column(Integer, nullable=False, default=0)
    sale_count = Column(Integer, nullable=False, default=0)
    sale_value = Column(Numeric(12, 2), nullable=False, default=0)

    snapshot = relationship("AllegroAdsSnapshot", back_populates="campaigns")
    sold_items = relationship("AllegroAdsSoldItem", back_populates="campaign", cascade="all, delete-orphan")


class AllegroAdsSoldItem(Base):
    """Pozycje z modala Sprzedane sztuki."""

    __tablename__ = "allegro_ads_sold_items"
    __table_args__ = (
        UniqueConstraint(
            "campaign_daily_id",
            "offer_id",
            name="uq_ads_sold_item_campaign_offer",
        ),
        Index("idx_allegro_ads_sold_items_offer_id", "offer_id"),
    )

    id = Column(Integer, primary_key=True)
    campaign_daily_id = Column(
        Integer,
        ForeignKey("allegro_ads_campaign_daily.id", ondelete="CASCADE"),
        nullable=False,
    )
    offer_id = Column(String, nullable=False)
    offer_name = Column(String, nullable=True)
    quantity = Column(Integer, nullable=False, default=0)
    sale_value = Column(Numeric(12, 2), nullable=False, default=0)

    campaign = relationship("AllegroAdsCampaignDaily", back_populates="sold_items")


class AllegroAdsChartDaily(Base):
    """Dzienne punkty wykresu (konto / zakres / kampania)."""

    __tablename__ = "allegro_ads_chart_daily"
    __table_args__ = (
        UniqueConstraint(
            "snapshot_id",
            "campaign_entity_id",
            "day",
            name="uq_ads_chart_snapshot_campaign_day",
        ),
        Index("idx_allegro_ads_chart_daily_day", "day"),
        Index("idx_allegro_ads_chart_daily_campaign", "campaign_entity_id"),
    )

    id = Column(Integer, primary_key=True)
    snapshot_id = Column(Integer, ForeignKey("allegro_ads_snapshots.id", ondelete="CASCADE"), nullable=False)
    campaign_entity_id = Column(String, nullable=False, default="")
    day = Column(Date, nullable=False)
    clicks = Column(Integer, nullable=False, default=0)
    impressions = Column(Integer, nullable=False, default=0)
    cost = Column(Numeric(12, 2), nullable=False, default=0)
    sale_count = Column(Integer, nullable=False, default=0)
    sale_value = Column(Numeric(12, 2), nullable=False, default=0)
    ctr = Column(Numeric(8, 4), nullable=True)
    cpc = Column(Numeric(10, 2), nullable=True)
    roi = Column(Numeric(10, 2), nullable=True)

    snapshot = relationship("AllegroAdsSnapshot", back_populates="chart_points")


__all__ = [
    "AllegroAdsCampaignDaily",
    "AllegroAdsChartDaily",
    "AllegroAdsSnapshot",
    "AllegroAdsSoldItem",
]
