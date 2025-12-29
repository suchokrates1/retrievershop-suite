from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    ForeignKey,
    Text,
    Numeric,
    Index,
    DateTime,
    func,
    Boolean,
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    username = Column(String, unique=True, nullable=False)
    password = Column(String, nullable=False)


class Product(Base):
    __tablename__ = "products"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    color = Column(String)
    sizes = relationship(
        "ProductSize", back_populates="product", cascade="all, delete-orphan"
    )


class ProductSize(Base):
    __tablename__ = "product_sizes"
    __table_args__ = (
        Index("idx_product_sizes_product_id_size", "product_id", "size"),
    )
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
        "AllegroPriceHistory", back_populates="product_size", cascade="all, delete-orphan"
    )


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


class PurchaseBatch(Base):
    __tablename__ = "purchase_batches"
    id = Column(Integer, primary_key=True)
    product_id = Column(
        Integer,
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
    )
    size = Column(String, nullable=False)
    quantity = Column(Integer, nullable=False)
    price = Column(Numeric(10, 2), nullable=False)
    purchase_date = Column(String, nullable=False)


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


class AllegroOffer(Base):
    __tablename__ = "allegro_offers"
    id = Column(Integer, primary_key=True)
    offer_id = Column(String, unique=True)
    title = Column(String, nullable=False)
    price = Column(Numeric(10, 2), nullable=False)
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
        Index(
            "idx_allegro_price_history_offer_recorded_at",
            "offer_id",
            "recorded_at",
        ),
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
    
    # Competitor data
    competitor_price = Column(Numeric(10, 2), nullable=True)
    competitor_seller = Column(String, nullable=True)
    competitor_url = Column(String, nullable=True)
    competitor_delivery_days = Column(Integer, nullable=True)

    product_size = relationship("ProductSize", back_populates="price_history")


class AppSetting(Base):
    __tablename__ = "app_settings"
    key = Column(String, primary_key=True)
    value = Column(Text, nullable=True)
    updated_at = Column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )


class AllegroRepliedThread(Base):
    __tablename__ = "allegro_replied_threads"
    thread_id = Column(String, primary_key=True)
    replied_at = Column(DateTime, nullable=False, server_default=func.now())


class AllegroRepliedDiscussion(Base):
    __tablename__ = "allegro_replied_discussions"
    discussion_id = Column(String, primary_key=True)
    replied_at = Column(DateTime, nullable=False, server_default=func.now())


class Thread(Base):
    __tablename__ = "threads"
    id = Column(String, primary_key=True)
    title = Column(String, nullable=False)
    author = Column(String, nullable=False)
    last_message_at = Column(DateTime, nullable=False, server_default=func.now())
    type = Column(String, nullable=False)  # "wiadomość" or "dyskusja"
    read = Column(Boolean, default=False, nullable=False)
    messages = relationship("Message", back_populates="thread", cascade="all, delete-orphan")


class Message(Base):
    __tablename__ = "messages"
    id = Column(String, primary_key=True)
    thread_id = Column(String, ForeignKey("threads.id", ondelete="CASCADE"), nullable=False)
    author = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    thread = relationship("Thread", back_populates="messages")
