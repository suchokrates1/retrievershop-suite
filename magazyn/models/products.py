"""Modele produktow, stanow magazynowych i sprzedazy."""

from sqlalchemy import Column, Float, ForeignKey, Index, Integer, Numeric, String, Text, case, func
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import relationship

from .base import Base


class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True)
    _name = Column("name", String, nullable=True)
    category = Column(String, nullable=True)
    brand = Column(String, nullable=True, default="Truelove")
    series = Column(String, nullable=True)
    color = Column(String)
    sizes = relationship(
        "ProductSize",
        back_populates="product",
        cascade="all, delete-orphan",
    )

    def __init__(self, **kwargs):
        """Initialize Product with support for legacy 'name' parameter."""
        if "name" in kwargs and "category" not in kwargs:
            kwargs["_name"] = kwargs.pop("name")
        if "_name" not in kwargs or kwargs.get("_name") is None:
            category = kwargs.get("category", "")
            brand = kwargs.get("brand", "")
            series = kwargs.get("series", "")
            parts = [part for part in [category, "dla psa", brand, series] if part]
            kwargs["_name"] = " ".join(parts) if parts else "Produkt bez nazwy"
        super().__init__(**kwargs)

    @hybrid_property
    def name(self) -> str:
        """Return full product name for backward compatibility."""
        if self.category:
            parts = [self.category, "dla psa"]
            if self.brand:
                parts.append(self.brand)
            if self.series:
                parts.append(self.series)
            return " ".join(parts)
        return self._name or ""

    @name.inplace.setter
    def _name_setter(self, value: str):
        """Set name for backward compatibility."""
        self._name = value

    @name.inplace.expression
    @classmethod
    def _name_expression(cls):
        """SQL expression for name."""
        return case(
            (
                cls.category.isnot(None) & (cls.category != ""),
                func.coalesce(cls.category, "")
                + " dla psa"
                + case((cls.brand.isnot(None) & (cls.brand != ""), " " + cls.brand), else_="")
                + case((cls.series.isnot(None) & (cls.series != ""), " " + cls.series), else_=""),
            ),
            else_=func.coalesce(cls._name, ""),
        )

    @property
    def display_name(self) -> str:
        """Return display name for UI."""
        if self.series:
            return f"{self.series} {self.category or ''}"
        if self.brand and self.category:
            return f"{self.brand} {self.category}"
        if self.category:
            return self.category
        return self._name or ""

    @property
    def short_name(self) -> str:
        """Return very short name."""
        return self.series or self.category or self._name or ""


class ProductSize(Base):
    __tablename__ = "product_sizes"
    __table_args__ = (Index("idx_product_sizes_product_id_size", "product_id", "size"),)

    id = Column(Integer, primary_key=True)
    product_id = Column(
        Integer,
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
    )
    size = Column(String, nullable=False)
    quantity = Column(Integer, nullable=False, default=0)
    barcode = Column(String, unique=True)
    product = relationship("Product", back_populates="sizes")
    allegro_offers = relationship("AllegroOffer", back_populates="product_size")
    price_history = relationship(
        "AllegroPriceHistory",
        back_populates="product_size",
        cascade="all, delete-orphan",
    )


class PurchaseBatch(Base):
    """Batch produktow z jednej dostawy lub faktury."""

    __tablename__ = "purchase_batches"
    __table_args__ = (
        Index("idx_purchase_batches_product_size", "product_id", "size"),
        Index("idx_purchase_batches_barcode", "barcode"),
        Index("idx_purchase_batches_date", "purchase_date"),
    )

    id = Column(Integer, primary_key=True)
    product_id = Column(
        Integer,
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
    )
    size = Column(String, nullable=False)
    quantity = Column(Integer, nullable=False)
    remaining_quantity = Column(Integer, nullable=False, default=0)
    price = Column(Numeric(10, 2), nullable=False)
    purchase_date = Column(String, nullable=False)
    barcode = Column(String, nullable=True, index=True)
    invoice_number = Column(String, nullable=True)
    supplier = Column(String, nullable=True)
    notes = Column(Text, nullable=True)

    product = relationship("Product")


class Sale(Base):
    __tablename__ = "sales"
    __table_args__ = (Index("idx_sales_sale_date", "sale_date"),)

    id = Column(Integer, primary_key=True)
    product_id = Column(
        Integer,
        ForeignKey("products.id", ondelete="SET NULL"),
        nullable=True,
    )
    size = Column(String, nullable=False)
    quantity = Column(Integer, nullable=False)
    sale_date = Column(String, nullable=False)
    purchase_cost = Column(Numeric(10, 2), nullable=False, default=0.0)
    sale_price = Column(Numeric(10, 2), nullable=False, default=0.0)
    shipping_cost = Column(Numeric(10, 2), nullable=False, default=0.0)
    commission_fee = Column(Numeric(10, 2), nullable=False, default=0.0)


class ShippingThreshold(Base):
    __tablename__ = "shipping_thresholds"

    id = Column(Integer, primary_key=True)
    min_order_value = Column(Float, nullable=False)
    shipping_cost = Column(Numeric(10, 2), nullable=False)


__all__ = [
    "Product",
    "ProductSize",
    "PurchaseBatch",
    "Sale",
    "ShippingThreshold",
]
