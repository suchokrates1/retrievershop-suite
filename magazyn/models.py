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
    case,
)
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy.ext.hybrid import hybrid_property

Base = declarative_base()


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    username = Column(String, unique=True, nullable=False)
    password = Column(String, nullable=False)


class Product(Base):
    __tablename__ = "products"
    id = Column(Integer, primary_key=True)
    # Keep old 'name' column for backward compatibility during migration
    _name = Column("name", String, nullable=True)
    # New structured fields
    category = Column(String, nullable=True)  # e.g. "Szelki", "Smycz", "Pas bezpieczeństwa"
    brand = Column(String, nullable=True, default="Truelove")  # e.g. "Truelove"
    series = Column(String, nullable=True)  # e.g. "Front Line Premium", "Active", "Blossom"
    color = Column(String)
    sizes = relationship(
        "ProductSize", back_populates="product", cascade="all, delete-orphan"
    )
    
    def __init__(self, **kwargs):
        """Initialize Product with support for legacy 'name' parameter."""
        # Handle legacy 'name' parameter for backward compatibility
        if 'name' in kwargs and 'category' not in kwargs:
            kwargs['_name'] = kwargs.pop('name')
        # Ensure _name is always populated (NOT NULL constraint in DB)
        if '_name' not in kwargs or kwargs.get('_name') is None:
            cat = kwargs.get('category', '')
            brand = kwargs.get('brand', '')
            series = kwargs.get('series', '')
            parts = [p for p in [cat, 'dla psa', brand, series] if p]
            if parts:
                kwargs['_name'] = ' '.join(parts)
            else:
                kwargs['_name'] = 'Produkt bez nazwy'
        super().__init__(**kwargs)
    
    @hybrid_property
    def name(self) -> str:
        """Return full product name for backward compatibility."""
        # If new fields are populated, build name from them
        if self.category:
            parts = [self.category, "dla psa"]
            if self.brand:
                parts.append(self.brand)
            if self.series:
                parts.append(self.series)
            return " ".join(parts)
        # Fallback to old name column
        return self._name or ""
    
    @name.inplace.setter
    def _name_setter(self, value: str):
        """Set name for backward compatibility (stores in _name column)."""
        self._name = value
    
    @name.inplace.expression
    @classmethod
    def _name_expression(cls):
        """SQL expression for name - builds full name from category/brand/series or uses _name."""
        from sqlalchemy import case, func
        # Build name from category + "dla psa" + brand + series when category exists
        # Otherwise fallback to _name
        return case(
            (cls.category.isnot(None) & (cls.category != ""),
             func.coalesce(cls.category, "") + " dla psa" +
             case((cls.brand.isnot(None) & (cls.brand != ""), " " + cls.brand), else_="") +
             case((cls.series.isnot(None) & (cls.series != ""), " " + cls.series), else_="")),
            else_=func.coalesce(cls._name, "")
        )
    
    @property
    def display_name(self) -> str:
        """Return display name (shorter version for UI)."""
        if self.series:
            return f"{self.series} {self.category or ''}"
        elif self.brand and self.category:
            return f"{self.brand} {self.category}"
        elif self.category:
            return self.category
        return self._name or ""
    
    @property
    def short_name(self) -> str:
        """Return very short name (series only or category)."""
        return self.series or self.category or self._name or ""


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


class ScanLog(Base):
    """Log of barcode/label scans for debugging and audit trail."""
    __tablename__ = "scan_logs"
    __table_args__ = (
        Index("idx_scan_logs_created_at", "created_at"),
        Index("idx_scan_logs_scan_type", "scan_type"),
    )
    id = Column(Integer, primary_key=True)
    scan_type = Column(String, nullable=False)  # 'product' or 'label'
    barcode = Column(String, nullable=False)
    success = Column(Boolean, nullable=False)
    result_data = Column(Text)  # JSON with result details
    error_message = Column(String)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    
    user = relationship("User")


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
    ean = Column(String, nullable=True)  # Cached EAN from Allegro API
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


class FixedCost(Base):
    """Koszty stale (np. ksiegowosc, skladki ZUS, serwisy).
    
    Koszty te sa odejmowane od miesiecznego zysku.
    Wartosc moze byc ujemna (np. dotacja, zwrot).
    """
    __tablename__ = "fixed_costs"
    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)  # Nazwa kosztu (np. "Ksiegowosc")
    amount = Column(Numeric(10, 2), nullable=False)  # Kwota w PLN (moze byc ujemna)
    description = Column(Text, nullable=True)  # Opcjonalny opis
    is_active = Column(Boolean, default=True, nullable=False)  # Czy koszt jest aktywny
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())
    
    def __repr__(self):
        return f"<FixedCost {self.name}: {self.amount} PLN>"


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


# =============================================================================
# Returns System - Obsluga zwrotow produktow
# =============================================================================

class Return(Base):
    """Model zwrotu produktu."""
    __tablename__ = "returns"
    __table_args__ = (
        Index("idx_returns_order_id", "order_id"),
        Index("idx_returns_status", "status"),
        Index("idx_returns_created_at", "created_at"),
    )
    
    id = Column(Integer, primary_key=True)
    order_id = Column(String, ForeignKey("orders.order_id", ondelete="CASCADE"), nullable=False)
    
    # Status zwrotu: pending, in_transit, delivered, completed, cancelled
    # pending - zgloszony, in_transit - paczka w drodze, delivered - paczka u nas, completed - stan przywrocony
    status = Column(String, nullable=False, default="pending")
    
    # Dane klienta (kopie na wypadek zmiany w zamowieniu)
    customer_name = Column(String, nullable=True)
    
    # Produkty do zwrotu (JSON: [{"ean": "xxx", "name": "yyy", "quantity": 1}])
    items_json = Column(Text, nullable=True)
    
    # Numer sledzenia paczki zwrotnej
    return_tracking_number = Column(String, nullable=True)
    return_carrier = Column(String, nullable=True)
    
    # Allegro Customer Return ID (jesli z Allegro)
    allegro_return_id = Column(String, nullable=True)
    
    # Flagi procesowania
    messenger_notified = Column(Boolean, default=False, nullable=False)
    stock_restored = Column(Boolean, default=False, nullable=False)
    
    # Notatki
    notes = Column(Text, nullable=True)
    
    # Timestamps
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())
    
    # Relationship
    order = relationship("Order")


class ReturnStatusLog(Base):
    """Historia zmian statusu zwrotu."""
    __tablename__ = "return_status_logs"
    __table_args__ = (
        Index("idx_return_status_logs_return_id", "return_id"),
    )
    
    id = Column(Integer, primary_key=True)
    return_id = Column(Integer, ForeignKey("returns.id", ondelete="CASCADE"), nullable=False)
    status = Column(String, nullable=False)
    notes = Column(Text, nullable=True)
    timestamp = Column(DateTime, nullable=False, server_default=func.now())
    
    # Relationship
    return_record = relationship("Return")


# =============================================================================
# Price Reports System - Raporty cenowe konkurencji
# =============================================================================

class PriceReport(Base):
    """Raport cenowy - glowna tabela."""
    __tablename__ = "price_reports"
    __table_args__ = (
        Index("idx_price_reports_created_at", "created_at"),
        Index("idx_price_reports_status", "status"),
    )
    
    id = Column(Integer, primary_key=True)
    
    # Status: pending, running, completed, failed
    status = Column(String, nullable=False, default="pending")
    
    # Postep
    items_total = Column(Integer, nullable=False, default=0)
    items_checked = Column(Integer, nullable=False, default=0)
    
    # Timestamps
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    completed_at = Column(DateTime, nullable=True)
    
    # Relationships
    items = relationship("PriceReportItem", back_populates="report", cascade="all, delete-orphan")


class PriceReportItem(Base):
    """Pojedynczy wpis w raporcie cenowym."""
    __tablename__ = "price_report_items"
    __table_args__ = (
        Index("idx_price_report_items_report_id", "report_id"),
        Index("idx_price_report_items_offer_id", "offer_id"),
        Index("idx_price_report_items_is_cheapest", "is_cheapest"),
    )
    
    id = Column(Integer, primary_key=True)
    report_id = Column(Integer, ForeignKey("price_reports.id", ondelete="CASCADE"), nullable=False)
    
    # Oferta
    offer_id = Column(String, nullable=False)
    product_name = Column(String, nullable=True)
    
    # Ceny
    our_price = Column(Numeric(10, 2), nullable=True)
    competitor_price = Column(Numeric(10, 2), nullable=True)
    competitor_seller = Column(String, nullable=True)
    competitor_url = Column(String, nullable=True)
    
    # Analiza
    is_cheapest = Column(Boolean, nullable=False, default=True)
    price_difference = Column(Float, nullable=True)  # our_price - competitor_price
    our_position = Column(Integer, nullable=True)
    total_offers = Column(Integer, nullable=True)  # oferty po filtrze (Smart + nie-wykluczeni)
    competitors_all_count = Column(Integer, nullable=True)  # wszystkie oferty przed filtrami
    competitor_is_super_seller = Column(Boolean, nullable=True)  # najtanszy konkurent to Super Sprzedawca?
    
    # Metadata
    checked_at = Column(DateTime, nullable=False, server_default=func.now())
    error = Column(String, nullable=True)
    
    # Relationship
    report = relationship("PriceReport", back_populates="items")


class ExcludedSeller(Base):
    """Wykluczony sprzedawca z analizy konkurencji."""
    __tablename__ = "excluded_sellers"
    
    id = Column(Integer, primary_key=True)
    seller_name = Column(String, unique=True, nullable=False)
    excluded_at = Column(DateTime, nullable=False, server_default=func.now())
    reason = Column(String, nullable=True)  # Opcjonalny powod wykluczenia


class Stocktake(Base):
    """Remanent - sesja inwentaryzacji."""
    __tablename__ = "stocktakes"
    __table_args__ = (
        Index("idx_stocktakes_status", "status"),
    )
    id = Column(Integer, primary_key=True)
    started_at = Column(DateTime, nullable=False, server_default=func.now())
    finished_at = Column(DateTime, nullable=True)
    status = Column(String, nullable=False, default="in_progress")  # in_progress, finished
    notes = Column(Text, nullable=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    user = relationship("User")
    items = relationship("StocktakeItem", back_populates="stocktake", cascade="all, delete-orphan")


class StocktakeItem(Base):
    """Pozycja remanentu - skan pojedynczego produktu."""
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
    scanned_at = Column(DateTime, nullable=True)  # Ostatni skan

    stocktake = relationship("Stocktake", back_populates="items")
    product_size = relationship("ProductSize")
