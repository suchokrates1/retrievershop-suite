import datetime
import os
from contextlib import contextmanager
import logging
from pathlib import Path
import importlib.util
import sqlite3
from datetime import timezone
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import create_engine, event, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker
from werkzeug.security import generate_password_hash

from .models import (
    Base,
    User,
    ProductSize,
    PurchaseBatch,
    Sale,
    Product,
    AllegroOffer,
)
from .config import settings
from .notifications import send_stock_alert

TWOPLACES = Decimal("0.01")

logger = logging.getLogger(__name__)


def to_decimal(value) -> Decimal:
    if isinstance(value, Decimal):
        return value.quantize(TWOPLACES, rounding=ROUND_HALF_UP)
    return Decimal(str(value)).quantize(TWOPLACES, rounding=ROUND_HALF_UP)

engine = None
SessionLocal = None
_is_postgres = False


MIGRATIONS_DIR = Path(__file__).with_name("migrations")

SQLITE_CONNECT_ARGS = {"check_same_thread": False, "timeout": 5}
# WAL mode - wymaga montowania katalogu (nie pojedynczego pliku) w Docker
SQLITE_JOURNAL_MODE = "WAL"
SQLITE_BUSY_TIMEOUT_MS = 30000


def is_postgres() -> bool:
    """Zwraca True jesli silnik to PostgreSQL."""
    return _is_postgres


def _configure_sqlite_connection(dbapi_connection):
    """Apply common SQLite PRAGMA settings to the given connection."""

    cursor = dbapi_connection.cursor()
    try:
        try:
            cursor.execute(f"PRAGMA journal_mode={SQLITE_JOURNAL_MODE}")
        except sqlite3.OperationalError as exc:
            logger.warning(
                "Unable to set SQLite journal_mode to %s; continuing without WAL mode: %s",
                SQLITE_JOURNAL_MODE,
                exc,
            )
        else:
            # ``journal_mode`` returns the active mode as a row, consume it to avoid
            # leaving the cursor in a pending state.
            try:
                cursor.fetchone()
            except sqlite3.Error:  # pragma: no cover - defensive
                pass

        try:
            cursor.execute(f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_MS}")
        except sqlite3.OperationalError as exc:
            logger.warning(
                "Unable to set SQLite busy_timeout; continuing with default timeout: %s",
                exc,
            )

        try:
            cursor.execute("PRAGMA foreign_keys=ON")
        except sqlite3.OperationalError as exc:
            logger.warning(
                "Unable to enable SQLite foreign_keys; continuing without enforcement: %s",
                exc,
            )
    finally:
        cursor.close()


def sqlite_connect(db_path=None, *, apply_pragmas=True, **kwargs):
    """Return a SQLite connection with standard settings applied.

    UWAGA: Uzywaj tylko do operacji specyficznych dla SQLite
    (np. skrypty migracji). Do zapytan runtime uzywaj ``db_connect()``.
    """

    if db_path is None:
        if engine is None:
            raise RuntimeError(
                "Database not configured. Call configure_engine() first."
            )
        db_path = engine.url.database

    params = {**SQLITE_CONNECT_ARGS, **kwargs}
    conn = sqlite3.connect(str(db_path), **params)
    if apply_pragmas:
        _configure_sqlite_connection(conn)
    return conn


@contextmanager
def db_connect():
    """Context manager dla raw SQL przez SQLAlchemy Connection.

    Dziala na obu backendach (SQLite i PostgreSQL).
    Uzywa ``text()`` do zapytan z ``:named`` parametrami.

    Przyklad::

        with db_connect() as conn:
            conn.execute(text("INSERT INTO t(k) VALUES (:v)"), {"v": 1})
    """
    if engine is None:
        raise RuntimeError("Database not configured. Call configure_engine() first.")
    with engine.connect() as conn:
        yield conn
        conn.commit()


def table_has_column(table_name: str, column_name: str) -> bool:
    """Sprawdza czy tabela ma kolumne. Dziala na SQLite i PostgreSQL."""
    with engine.connect() as conn:
        if _is_postgres:
            row = conn.execute(
                text(
                    "SELECT 1 FROM information_schema.columns "
                    "WHERE table_name = :tbl AND column_name = :col"
                ),
                {"tbl": table_name, "col": column_name},
            ).fetchone()
            return row is not None
        else:
            rows = conn.execute(
                text(f"PRAGMA table_info({table_name})")
            ).fetchall()
            return column_name in [r[1] for r in rows]


def configure_engine(db_path=None):
    """Create SQLAlchemy engine and session factory.

    Jesli zmienna DATABASE_URL jest ustawiona, laczy sie z PostgreSQL.
    W przeciwnym razie uzywa SQLite pod sciezka ``db_path``.
    """
    global engine, SessionLocal, _is_postgres

    database_url = os.environ.get("DATABASE_URL", "")

    if database_url.startswith("postgresql"):
        _is_postgres = True
        print(f"Configuring engine for PostgreSQL")
        engine = create_engine(
            database_url,
            future=True,
            pool_size=5,
            max_overflow=10,
            pool_pre_ping=True,
        )
    else:
        _is_postgres = False
        if db_path is None:
            raise ValueError("db_path is required when DATABASE_URL is not set")
        print(f"Configuring engine for {db_path}")
        engine = create_engine(
            f"sqlite:///{db_path}",
            future=True,
            connect_args=SQLITE_CONNECT_ARGS,
        )

        @event.listens_for(engine, "connect")
        def _set_sqlite_pragmas(dbapi_connection, _record):
            _configure_sqlite_connection(dbapi_connection)

    SessionLocal = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
    )
    print(f"SessionLocal set to: {SessionLocal}")


@contextmanager
def get_session():
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception as e:
        session.rollback()
        logger.exception("Database session error: %s", e)
        raise
    finally:
        session.close()


# Backward compatibility
get_db_connection = get_session


def init_db():
    """Initialize the SQLite database and create required tables."""
    Base.metadata.create_all(engine)

def reset_db():
    """Drop all tables and recreate them."""
    from sqlalchemy import text
    Base.metadata.drop_all(engine)
    if _is_postgres:
        with engine.connect() as conn:
            conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
            conn.commit()
    else:
        with sqlite_connect() as conn:
            conn.execute("DROP TABLE IF EXISTS alembic_version")
            conn.commit()
    Base.metadata.create_all(engine)


def create_default_user_if_needed(app):
    """Ensure the default admin account exists."""
    with app.app_context():
        with get_session() as session:
            try:
                user = session.query(User).filter_by(username="kontakt@retrievershop.pl").first()
            except Exception:
                # If schema is missing (e.g., test DB reconfigured), rebuild and retry
                session.rollback()
                init_db()
                user = session.query(User).filter_by(username="kontakt@retrievershop.pl").first()

            if not user:
                # Migracja ze starego loginu "admin" jesli istnieje
                old_user = session.query(User).filter_by(username="admin").first()
                if old_user:
                    old_user.username = "kontakt@retrievershop.pl"
                    old_user.password = generate_password_hash(
                        "Lucynka66@", method="pbkdf2:sha256", salt_length=16
                    )
                else:
                    hashed_password = generate_password_hash(
                        "Lucynka66@", method="pbkdf2:sha256", salt_length=16
                    )
                    session.add(User(username="kontakt@retrievershop.pl", password=hashed_password))


def record_purchase(
    product_id,
    size,
    quantity,
    price,
    purchase_date=None,
    barcode=None,
    invoice_number=None,
    supplier=None,
    notes=None,
):
    """Insert a purchase batch and increase stock quantity.
    
    Args:
        product_id: Product ID
        size: Product size
        quantity: Number of units purchased
        price: Purchase price per unit
        purchase_date: Date of purchase (defaults to now)
        barcode: EAN code from invoice
        invoice_number: Invoice/receipt number
        supplier: Supplier name
        notes: Additional notes
    """
    purchase_date = purchase_date or datetime.datetime.now().strftime('%Y-%m-%d')
    with get_session() as session:
        price = to_decimal(price)
        session.add(
            PurchaseBatch(
                product_id=product_id,
                size=size,
                quantity=quantity,
                remaining_quantity=quantity,  # FIFO: initially all available
                price=price,
                purchase_date=purchase_date,
                barcode=barcode,
                invoice_number=invoice_number,
                supplier=supplier,
                notes=notes,
            )
        )
        ps = (
            session.query(ProductSize)
            .filter_by(product_id=product_id, size=size)
            .first()
        )
        if ps:
            ps.quantity += quantity


def record_sale(
    session,
    product_id,
    size,
    quantity,
    purchase_cost=Decimal("0.00"),
    sale_price=Decimal("0.00"),
    shipping_cost=Decimal("0.00"),
    commission_fee=Decimal("0.00"),
    sale_date=None,
):
    """Record a sale inside an existing session."""
    sale_date = sale_date or datetime.datetime.now().isoformat()
    purchase_cost = to_decimal(purchase_cost)
    sale_price = to_decimal(sale_price)
    shipping_cost = to_decimal(shipping_cost)
    commission_fee = to_decimal(commission_fee)
    session.add(
        Sale(
            product_id=product_id,
            size=size,
            quantity=quantity,
            sale_date=sale_date,
            purchase_cost=purchase_cost,
            sale_price=sale_price,
            shipping_cost=shipping_cost,
            commission_fee=commission_fee,
        )
    )


def consume_stock(
    product_id,
    size,
    quantity,
    sale_price=Decimal("0.00"),
    shipping_cost=Decimal("0.00"),
    commission_fee=Decimal("0.00"),
):
    """Remove quantity from stock using FIFO (oldest purchase batches first).
    
    Uses remaining_quantity field to track how much is left from each batch.
    Records sale with actual purchase cost for profit calculation.
    """
    with get_session() as session:
        sale_price = to_decimal(sale_price)
        shipping_cost = to_decimal(shipping_cost)
        commission_fee = to_decimal(commission_fee)
        ps = (
            session.query(ProductSize)
            .filter_by(product_id=product_id, size=size)
            .first()
        )
        if not ps:
            logger.warning(
                "Missing stock entry for product_id=%s size=%s",
                product_id,
                size,
            )
        available = ps.quantity if ps else 0
        to_consume = min(available, quantity)

        # FIFO: Get batches ordered by purchase date (oldest first)
        # Use remaining_quantity if available, otherwise fall back to quantity
        batches = (
            session.query(PurchaseBatch)
            .filter(
                PurchaseBatch.product_id == product_id,
                PurchaseBatch.size == size,
            )
            .order_by(
                PurchaseBatch.purchase_date.asc(),
                PurchaseBatch.id.asc(),  # Secondary sort for same date
            )
            .all()
        )

        # Fallback: jesli nie znaleziono partii po size, szukaj po barcode
        # (obsluguje przypadek gdy purchase_batch ma size="" a product_size "Uniwersalny")
        if not any(b.remaining_quantity and b.remaining_quantity > 0 for b in batches):
            if ps and ps.barcode:
                fallback_batches = (
                    session.query(PurchaseBatch)
                    .filter(
                        PurchaseBatch.product_id == product_id,
                        PurchaseBatch.barcode == ps.barcode,
                        PurchaseBatch.size != size,
                    )
                    .order_by(
                        PurchaseBatch.purchase_date.asc(),
                        PurchaseBatch.id.asc(),
                    )
                    .all()
                )
                if fallback_batches:
                    logger.info(
                        "FIFO fallback: dopasowanie po barcode %s dla product_id=%s size=%s",
                        ps.barcode, product_id, size,
                    )
                    batches = fallback_batches

        remaining = to_consume
        purchase_cost = Decimal("0.00")
        for batch in batches:
            if remaining <= 0:
                break
            
            # Use remaining_quantity if set, otherwise use quantity (for old records)
            batch_available = batch.remaining_quantity if batch.remaining_quantity is not None else batch.quantity
            
            if batch_available <= 0:
                continue
                
            use = min(remaining, batch_available)
            
            # Update remaining_quantity for FIFO
            if batch.remaining_quantity is not None:
                batch.remaining_quantity -= use
            else:
                batch.remaining_quantity = batch.quantity - use
            
            # Also update quantity for backward compatibility
            batch.quantity = max(0, batch.quantity - use)
            
            purchase_cost += use * batch.price
            remaining -= use
            
            # Don't delete batch - keep for history, remaining_quantity=0 marks it as depleted

        consumed = to_consume - remaining
        if consumed == 0 and to_consume > 0 and ps and not batches:
            # Adjust quantity even when no purchase batches exist
            ps.quantity -= to_consume
            consumed = to_consume
        elif consumed > 0 and ps:
            ps.quantity -= consumed
            if ps.quantity < settings.LOW_STOCK_THRESHOLD:
                try:
                    product = (
                        session.query(Product)
                        .filter_by(id=product_id)
                        .first()
                    )
                    name = product.name if product else str(product_id)
                    send_stock_alert(name, size, ps.quantity)
                except Exception as exc:
                    logger.error("Low stock alert failed: %s", exc)

        if consumed < quantity:
            logger.warning(
                "Insufficient stock for product_id=%s size=%s:"
                " requested=%s consumed=%s",
                product_id,
                size,
                quantity,
                consumed,
            )

        record_sale(
            session,
            product_id,
            size,
            quantity,
            purchase_cost=purchase_cost.quantize(TWOPLACES, rounding=ROUND_HALF_UP),
            sale_price=sale_price,
            shipping_cost=shipping_cost,
            commission_fee=commission_fee,
        )

        if consumed > 0:
            product = (
                session.query(Product).filter_by(id=product_id).first()
            )
            name = product.name if product else str(product_id)
            logger.info(
                "Pobrano z magazynu: %s %s x%s",
                name,
                size,
                consumed,
            )

    return consumed
