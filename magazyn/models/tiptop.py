"""Modele katalogu TipTop24 i mapowania do magazynu."""

from __future__ import annotations

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import relationship

from .base import Base


class TipTopProduct(Base):
    __tablename__ = "tiptop_products"

    id = Column(Integer, primary_key=True)
    tiptop_product_id = Column(Integer, nullable=False, unique=True)
    url = Column(String, nullable=False)
    name = Column(String, nullable=False)
    producer = Column(String, nullable=True)
    scraped_at = Column(DateTime, nullable=False, server_default=func.now())

    variants = relationship(
        "TipTopVariant",
        back_populates="product",
        cascade="all, delete-orphan",
        primaryjoin="TipTopProduct.tiptop_product_id==TipTopVariant.tiptop_product_id",
        foreign_keys="TipTopVariant.tiptop_product_id",
    )


class TipTopVariant(Base):
    __tablename__ = "tiptop_variants"
    __table_args__ = (
        UniqueConstraint(
            "tiptop_product_id",
            "size_label",
            "color_label",
            name="uq_tiptop_variants_product_size_color",
        ),
        Index("idx_tiptop_variants_product_id", "tiptop_product_id"),
    )

    id = Column(Integer, primary_key=True)
    tiptop_product_id = Column(
        Integer,
        ForeignKey("tiptop_products.tiptop_product_id", ondelete="CASCADE"),
        nullable=False,
    )
    # JSON map option_id -> value_id, e.g. {"8": 51, "9": 60}
    option_map = Column(Text, nullable=False, default="{}")
    size_label = Column(String, nullable=True)
    color_label = Column(String, nullable=True)
    variant_stock_id = Column(Integer, nullable=True)
    available = Column(Boolean, nullable=False, default=True)
    price = Column(Float, nullable=True)

    product = relationship(
        "TipTopProduct",
        back_populates="variants",
        primaryjoin="TipTopVariant.tiptop_product_id==TipTopProduct.tiptop_product_id",
        foreign_keys="[TipTopVariant.tiptop_product_id]",
    )
    links = relationship(
        "TipTopProductLink",
        back_populates="variant",
        cascade="all, delete-orphan",
    )


class TipTopProductLink(Base):
    __tablename__ = "tiptop_product_links"
    __table_args__ = (
        UniqueConstraint("product_size_id", name="uq_tiptop_links_product_size"),
        Index("idx_tiptop_links_variant_id", "tiptop_variant_id"),
    )

    id = Column(Integer, primary_key=True)
    product_size_id = Column(
        Integer,
        ForeignKey("product_sizes.id", ondelete="CASCADE"),
        nullable=False,
    )
    tiptop_variant_id = Column(
        Integer,
        ForeignKey("tiptop_variants.id", ondelete="CASCADE"),
        nullable=False,
    )
    match_confidence = Column(Float, nullable=True)
    match_type = Column(String(32), nullable=True)  # auto / manual
    created_at = Column(DateTime, nullable=False, server_default=func.now())

    variant = relationship("TipTopVariant", back_populates="links")
    product_size = relationship("ProductSize")


class TipTopReorderExclusion(Base):
    __tablename__ = "tiptop_reorder_exclusions"
    __table_args__ = (
        Index("idx_tiptop_excl_product_id", "product_id"),
        Index("idx_tiptop_excl_product_size_id", "product_size_id"),
    )

    id = Column(Integer, primary_key=True)
    product_id = Column(
        Integer,
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=True,
    )
    product_size_id = Column(
        Integer,
        ForeignKey("product_sizes.id", ondelete="CASCADE"),
        nullable=True,
    )
    reason = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())


__all__ = [
    "TipTopProduct",
    "TipTopVariant",
    "TipTopProductLink",
    "TipTopReorderExclusion",
]
