import datetime
from contextlib import contextmanager

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from werkzeug.security import generate_password_hash

from . import DB_PATH
from .models import Base, User, ProductSize, PurchaseBatch

engine = create_engine(f"sqlite:///{DB_PATH}", future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False)



@contextmanager
def get_session():
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
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
            .order_by(PurchaseBatch.price.asc(), PurchaseBatch.purchase_date.asc())
            .all()
        )

        remaining = to_consume
        for batch in batches:
            if remaining <= 0:
                break
            use = remaining if batch.quantity >= remaining else batch.quantity
            batch.quantity -= use
            remaining -= use
            if batch.quantity == 0:
                session.delete(batch)

        if to_consume > 0 and ps:
            ps.quantity -= to_consume - remaining
    return to_consume - remaining
