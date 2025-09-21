import datetime
from contextlib import contextmanager
import logging
from pathlib import Path
import importlib.util
import sqlite3
from datetime import timezone
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from werkzeug.security import generate_password_hash

from . import DB_PATH
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


def to_decimal(value) -> Decimal:
    if isinstance(value, Decimal):
        return value.quantize(TWOPLACES, rounding=ROUND_HALF_UP)
    return Decimal(str(value)).quantize(TWOPLACES, rounding=ROUND_HALF_UP)

engine = None
SessionLocal = None


MIGRATIONS_DIR = Path(__file__).with_name("migrations")


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


def _ensure_schema_migrations_table(conn):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            filename TEXT PRIMARY KEY,
            applied_at TEXT NOT NULL
        )
        """
    )


def _get_applied_migrations():
    with sqlite3.connect(DB_PATH) as conn:
        _ensure_schema_migrations_table(conn)
        cur = conn.execute("SELECT filename FROM schema_migrations")
        return {row[0] for row in cur.fetchall()}


def _record_migration(filename):
    with sqlite3.connect(DB_PATH) as conn:
        _ensure_schema_migrations_table(conn)
        conn.execute(
            "INSERT INTO schema_migrations (filename, applied_at) VALUES (?, ?)",
            (filename, datetime.datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()


def apply_migrations():
    """Execute migration scripts that have not been run yet."""

    applied = _get_applied_migrations()
    for path in sorted(MIGRATIONS_DIR.glob("*.py")):
        if path.name in applied:
            continue
        spec = importlib.util.spec_from_file_location(path.stem, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        migrate = getattr(module, "migrate", None)
        if callable(migrate):
            migrate()
            _record_migration(path.name)


def init_db():
    """Initialize the SQLite database and create required tables."""
    Base.metadata.create_all(engine)
    apply_migrations()


def reset_db():
    """Drop all tables and recreate them.

    This is useful for testing scenarios that require a completely
    clean database state without losing the ability of :func:`init_db`
    to preserve existing data."""
    Base.metadata.drop_all(engine)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("DROP TABLE IF EXISTS schema_migrations")
        conn.commit()
    Base.metadata.create_all(engine)
    apply_migrations()


def register_default_user():
    """Ensure the default admin account exists."""
    with get_session() as session:
        if not session.query(User).filter_by(username="admin").first():
            hashed_password = generate_password_hash(
                "admin123", method="pbkdf2:sha256", salt_length=16
            )
            session.add(User(username="admin", password=hashed_password))


def record_purchase(
    product_id,
    size,
    quantity,
    price,
    purchase_date=None,
):
    """Insert a purchase batch and increase stock quantity."""
    purchase_date = purchase_date or datetime.datetime.now().isoformat()
    with get_session() as session:
        price = to_decimal(price)
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
    """Remove quantity from stock using cheapest purchase batches first."""
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

        batches = (
            session.query(PurchaseBatch)
            .filter_by(product_id=product_id, size=size)
            .order_by(
                PurchaseBatch.price.asc(),
                PurchaseBatch.purchase_date.asc(),
            )
            .all()
        )

        remaining = to_consume
        purchase_cost = Decimal("0.00")
        for batch in batches:
            if remaining <= 0:
                break
            use = remaining if batch.quantity >= remaining else batch.quantity
            batch.quantity -= use
            purchase_cost += use * batch.price
            remaining -= use
            if batch.quantity == 0:
                session.delete(batch)

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
