import datetime
from contextlib import contextmanager
import logging

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from werkzeug.security import generate_password_hash

from . import DB_PATH
from .models import Base, User, ProductSize, PurchaseBatch, Sale, Product
from .config import settings
from .notifications import send_stock_alert

engine = None
SessionLocal = None


def configure_engine(db_path):
    """Create SQLAlchemy engine and session factory for ``db_path``."""
    global engine, SessionLocal
    engine = create_engine(f"sqlite:///{db_path}", future=True)
    SessionLocal = sessionmaker(bind=engine, autoflush=False)


configure_engine(DB_PATH)
logger = logging.getLogger(__name__)


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
    """Drop all tables and recreate them.

    This is useful for testing scenarios that require a completely clean
    database state without losing the ability of :func:`init_db` to preserve
    existing data."""
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)


def ensure_schema():
    """Add missing columns to existing tables if necessary."""
    conn = engine.raw_connection()
    try:
        cur = conn.execute("PRAGMA table_info(product_sizes)")
        if "barcode" not in [row[1] for row in cur.fetchall()]:
            conn.execute("ALTER TABLE product_sizes ADD COLUMN barcode TEXT")
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_product_sizes_barcode "
                "ON product_sizes(barcode)"
            )
            conn.commit()

        cur = conn.execute("PRAGMA table_info(sales)")
        cols = [row[1] for row in cur.fetchall()]
        if "purchase_cost" not in cols:
            conn.execute(
                "ALTER TABLE sales ADD COLUMN purchase_cost "
                "REAL DEFAULT 0.0 NOT NULL"
            )
        if "sale_price" not in cols:
            conn.execute(
                "ALTER TABLE sales ADD COLUMN sale_price "
                "REAL DEFAULT 0.0 NOT NULL"
            )
        if "shipping_cost" not in cols:
            conn.execute(
                "ALTER TABLE sales ADD COLUMN shipping_cost "
                "REAL DEFAULT 0.0 NOT NULL"
            )
        if "commission_fee" not in cols:
            conn.execute(
                "ALTER TABLE sales ADD COLUMN commission_fee "
                "REAL DEFAULT 0.0 NOT NULL"
            )
        conn.commit()

        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
            " AND name='shipping_thresholds'"
        )
        if not cur.fetchone():
            conn.execute(
                "CREATE TABLE shipping_thresholds ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "min_order_value REAL NOT NULL, "
                "shipping_cost REAL NOT NULL)"
            )
            conn.commit()
    finally:
        conn.close()


def register_default_user():
    """Ensure the default admin account exists."""
    with get_session() as session:
        if not session.query(User).filter_by(username="admin").first():
            hashed_password = generate_password_hash(
                "admin123", method="pbkdf2:sha256", salt_length=16
            )
            session.add(User(username="admin", password=hashed_password))


def record_purchase(product_id, size, quantity, price, purchase_date=None):
    """Insert a purchase batch and increase stock quantity."""
    purchase_date = purchase_date or datetime.datetime.now().isoformat()
    with get_session() as session:
        session.add(
            PurchaseBatch(
                product_id=product_id,
                size=size,
                quantity=quantity,
                price=price,
                purchase_date=purchase_date,
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
    purchase_cost=0.0,
    sale_price=0.0,
    shipping_cost=0.0,
    commission_fee=0.0,
    sale_date=None,
):
    """Record a sale inside an existing session."""
    sale_date = sale_date or datetime.datetime.now().isoformat()
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


def consume_stock(product_id, size, quantity):
    """Remove quantity from stock using cheapest purchase batches first."""
    with get_session() as session:
        ps = (
            session.query(ProductSize)
            .filter_by(product_id=product_id, size=size)
            .first()
        )
        available = ps.quantity if ps else 0
        to_consume = min(available, quantity)

        batches = (
            session.query(PurchaseBatch)
            .filter_by(product_id=product_id, size=size)
            .order_by(
                PurchaseBatch.price.asc(), PurchaseBatch.purchase_date.asc()
            )
            .all()
        )

        remaining = to_consume
        purchase_cost = 0.0
        for batch in batches:
            if remaining <= 0:
                break
            use = (
                remaining if batch.quantity >= remaining else batch.quantity
            )
            batch.quantity -= use
            purchase_cost += use * batch.price
            remaining -= use
            if batch.quantity == 0:
                session.delete(batch)

        consumed = to_consume - remaining
        if ps:
            if consumed > 0:
                ps.quantity -= consumed
            record_sale(
                session,
                product_id,
                size,
                quantity,
                purchase_cost=purchase_cost,
            )
            if consumed > 0 and ps.quantity < settings.LOW_STOCK_THRESHOLD:
                try:
                    product = (
                        session.query(Product).filter_by(id=product_id).first()
                    )
                    name = product.name if product else str(product_id)
                    send_stock_alert(name, size, ps.quantity)
                except Exception as exc:
                    logger.error("Low stock alert failed: %s", exc)

    return consumed
