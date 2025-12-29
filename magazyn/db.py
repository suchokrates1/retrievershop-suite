import datetime
from contextlib import contextmanager
import logging
from pathlib import Path
import importlib.util
import sqlite3
from datetime import timezone
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import create_engine, event
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


MIGRATIONS_DIR = Path(__file__).with_name("migrations")

SQLITE_CONNECT_ARGS = {"check_same_thread": False, "timeout": 5}
SQLITE_JOURNAL_MODE = "WAL"
SQLITE_BUSY_TIMEOUT_MS = 30000


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
    """Return a SQLite connection with standard settings applied."""

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


def configure_engine(db_path):
    """Create SQLAlchemy engine and session factory for ``db_path``."""
    global engine, SessionLocal
    engine = create_engine(
        f"sqlite:///{db_path}",
        future=True,
        connect_args=SQLITE_CONNECT_ARGS,
    )

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, _record):  # pragma: no cover - SQLAlchemy hook
        _configure_sqlite_connection(dbapi_connection)

    SessionLocal = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,  # keep returned objects usable after commit
    )


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
    This is useful for testing scenarios that require a completely
    clean database state without losing the ability of :func:`init_db`
    to preserve existing data."""
    Base.metadata.drop_all(engine)
    with sqlite_connect() as conn:
        conn.execute("DROP TABLE IF EXISTS alembic_version")
        conn.commit()
    Base.metadata.create_all(engine)


def create_default_user_if_needed(app):
    """Ensure the default admin account exists."""
    with app.app_context():
        with get_session() as session:
            try:
                user = session.query(User).filter_by(username="admin").first()
            except Exception:
                # If schema is missing (e.g., test DB reconfigured), rebuild and retry
                session.rollback()
                init_db()
                user = session.query(User).filter_by(username="admin").first()

            if not user:
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
