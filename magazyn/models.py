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
    """Represents a batch of products from a single purchase/delivery.
    
    Each batch tracks:
    - Original quantity purchased
    - Remaining quantity for FIFO consumption
    - Purchase price per unit
    - EAN code for matching
    - Invoice details for accounting
    """
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
    quantity = Column(Integer, nullable=False)  # Original quantity purchased
    remaining_quantity = Column(Integer, nullable=False, default=0)  # Remaining for FIFO
    price = Column(Numeric(10, 2), nullable=False)  # Unit purchase price
    purchase_date = Column(String, nullable=False)
    
    # EAN matching
    barcode = Column(String, nullable=True, index=True)  # EAN code from invoice
    
    # Invoice details
    invoice_number = Column(String, nullable=True)  # Invoice/receipt number
    supplier = Column(String, nullable=True)  # Supplier name
    notes = Column(Text, nullable=True)  # Additional notes
    
    # Relationship
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


# =============================================================================
# Orders System - Full BaseLinker order data with status tracking
# =============================================================================

class Order(Base):
    """Full order data from BaseLinker API."""
    __tablename__ = "orders"
    __table_args__ = (
        Index("idx_orders_date_add", "date_add"),
        Index("idx_orders_platform", "platform"),
    )
    
    # Primary key - BaseLinker order_id
    order_id = Column(String, primary_key=True)
    external_order_id = Column(String, nullable=True)  # e.g. Allegro order number
    shop_order_id = Column(Integer, nullable=True)
    
    # Customer info
    customer_name = Column(String, nullable=True)  # delivery_fullname
    email = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    user_login = Column(String, nullable=True)  # Allegro/eBay login
    
    # Order source and status
    platform = Column(String, nullable=True)  # allegro, ebay, shop
    order_source_id = Column(Integer, nullable=True)
    order_status_id = Column(Integer, nullable=True)
    confirmed = Column(Boolean, default=False)
    
    # Dates (stored as unix timestamps)
    date_add = Column(Integer, nullable=True)
    date_confirmed = Column(Integer, nullable=True)
    date_in_status = Column(Integer, nullable=True)
    
    # Delivery address
    delivery_method = Column(String, nullable=True)
    delivery_method_id = Column(Integer, nullable=True)
    delivery_price = Column(Numeric(10, 2), nullable=True)
    delivery_fullname = Column(String, nullable=True)
    delivery_company = Column(String, nullable=True)
    delivery_address = Column(String, nullable=True)
    delivery_city = Column(String, nullable=True)
    delivery_postcode = Column(String, nullable=True)
    delivery_country = Column(String, nullable=True)
    delivery_country_code = Column(String(2), nullable=True)
    
    # Pickup point (paczkomat)
    delivery_point_id = Column(String, nullable=True)
    delivery_point_name = Column(String, nullable=True)
    delivery_point_address = Column(String, nullable=True)
    delivery_point_postcode = Column(String, nullable=True)
    delivery_point_city = Column(String, nullable=True)
    
    # Invoice address
    invoice_fullname = Column(String, nullable=True)
    invoice_company = Column(String, nullable=True)
    invoice_nip = Column(String, nullable=True)
    invoice_address = Column(String, nullable=True)
    invoice_city = Column(String, nullable=True)
    invoice_postcode = Column(String, nullable=True)
    invoice_country = Column(String, nullable=True)
    want_invoice = Column(Boolean, default=False)
    
    # Payment
    currency = Column(String(3), default="PLN")
    payment_method = Column(String, nullable=True)
    payment_method_cod = Column(Boolean, default=False)  # Cash on delivery
    payment_done = Column(Numeric(10, 2), nullable=True)
    
    # Comments
    user_comments = Column(Text, nullable=True)
    admin_comments = Column(Text, nullable=True)
    
    # Courier/shipping
    courier_code = Column(String, nullable=True)
    delivery_package_module = Column(String, nullable=True)  # courier name
    delivery_package_nr = Column(String, nullable=True)  # tracking number
    
    # Raw products JSON (for reference, parsed into OrderProduct)
    products_json = Column(Text, nullable=True)
    
    # Timestamps
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())
    
    # Relationships
    products = relationship("OrderProduct", back_populates="order", cascade="all, delete-orphan")
    status_logs = relationship("OrderStatusLog", back_populates="order", cascade="all, delete-orphan")


class OrderProduct(Base):
    """Products in an order - links to ProductSize via EAN."""
    __tablename__ = "order_products"
    __table_args__ = (
        Index("idx_order_products_ean", "ean"),
        Index("idx_order_products_order_id", "order_id"),
    )
    
    id = Column(Integer, primary_key=True)
    order_id = Column(String, ForeignKey("orders.order_id", ondelete="CASCADE"), nullable=False)
    
    # BaseLinker product data
    order_product_id = Column(Integer, nullable=True)  # BaseLinker order item ID
    product_id = Column(String, nullable=True)  # BaseLinker/shop product ID
    variant_id = Column(String, nullable=True)
    sku = Column(String, nullable=True)
    ean = Column(String, nullable=True)  # Key for linking to ProductSize
    name = Column(String, nullable=True)
    quantity = Column(Integer, default=1)
    price_brutto = Column(Numeric(10, 2), nullable=True)
    
    # Additional fields
    auction_id = Column(String, nullable=True)  # Allegro listing ID
    attributes = Column(Text, nullable=True)  # Size, color etc as text
    location = Column(String, nullable=True)  # Warehouse location
    
    # Link to warehouse (via EAN)
    product_size_id = Column(
        Integer,
        ForeignKey("product_sizes.id", ondelete="SET NULL"),
        nullable=True,
    )
    
    # Relationships
    order = relationship("Order", back_populates="products")
    product_size = relationship("ProductSize")


class OrderStatusLog(Base):
    """Tracking order/label status changes."""
    __tablename__ = "order_status_logs"
    __table_args__ = (
        Index("idx_order_status_logs_order_id", "order_id"),
        Index("idx_order_status_logs_timestamp", "timestamp"),
    )
    
    id = Column(Integer, primary_key=True)
    order_id = Column(String, ForeignKey("orders.order_id", ondelete="CASCADE"), nullable=False)
    
    # Status: niewydrukowano, wydrukowano, przekazano_kurierowi, w_drodze, dostarczono
    status = Column(String, nullable=False)
    
    # Optional tracking info
    tracking_number = Column(String, nullable=True)
    courier_code = Column(String, nullable=True)
    
    # When this status was recorded
    timestamp = Column(DateTime, nullable=False, server_default=func.now())
    
    # Optional notes
    notes = Column(Text, nullable=True)
    
    # Relationship
    order = relationship("Order", back_populates="status_logs")

