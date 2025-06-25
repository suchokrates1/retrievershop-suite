import sqlite3
import datetime
from contextlib import contextmanager
from werkzeug.security import generate_password_hash

from . import DB_PATH


@contextmanager
def get_db_connection():
    """Yield a database connection using a context manager."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        yield conn


def init_db():
    """Initialize the SQLite database and create required tables."""
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.executescript(
            """
            DROP TABLE IF EXISTS users;
            DROP TABLE IF EXISTS products;
            DROP TABLE IF EXISTS product_sizes;
            DROP TABLE IF EXISTS printed_orders;
            DROP TABLE IF EXISTS label_queue;
            DROP TABLE IF EXISTS settings;
            DROP TABLE IF EXISTS purchase_batches;
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL
            )
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                color TEXT,
                barcode TEXT UNIQUE
            )
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS product_sizes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER,
                size TEXT CHECK(size IN ('XS', 'S', 'M', 'L', 'XL', 'Uniwersalny')) NOT NULL,
                quantity INTEGER NOT NULL DEFAULT 0,
                barcode TEXT UNIQUE,
                FOREIGN KEY (product_id) REFERENCES products (id),
                UNIQUE(product_id, size)
            )
            """
        )

        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_product_id ON product_sizes (product_id);
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS printed_orders(
                order_id TEXT PRIMARY KEY,
                printed_at TEXT
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS label_queue(
                order_id TEXT,
                label_data TEXT,
                ext TEXT,
                last_order_data TEXT
            )
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS settings(
                key TEXT PRIMARY KEY,
                value TEXT
            )
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS purchase_batches(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER NOT NULL,
                size TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                price REAL NOT NULL,
                purchase_date TEXT NOT NULL,
                FOREIGN KEY (product_id) REFERENCES products(id)
            )
            """
        )

        conn.commit()


def register_default_user():
    """Ensure the default admin account exists."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM users WHERE username='admin'")
        if cursor.fetchone() is None:
            hashed_password = generate_password_hash(
                "admin123", method="pbkdf2:sha256", salt_length=16
            )
            cursor.execute(
                "INSERT INTO users (username, password) VALUES (?, ?)",
                ("admin", hashed_password),
            )
            conn.commit()


def record_purchase(product_id, size, quantity, price, purchase_date=None):
    """Insert a purchase batch and increase stock quantity."""
    purchase_date = purchase_date or datetime.datetime.now().isoformat()
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO purchase_batches (
                product_id, size, quantity, price, purchase_date
            ) VALUES (?, ?, ?, ?, ?)""",
            (product_id, size, quantity, price, purchase_date),
        )
        cur.execute(
            "UPDATE product_sizes SET quantity = quantity + ? "
            "WHERE product_id = ? AND size = ?",
            (quantity, product_id, size),
        )
        conn.commit()


def consume_stock(product_id, size, quantity):
    """Remove quantity from stock using cheapest purchase batches first."""
    with get_db_connection() as conn:
        cur = conn.cursor()
        row = cur.execute(
            "SELECT quantity FROM product_sizes WHERE product_id=? AND size=?",
            (product_id, size),
        ).fetchone()
        available = row["quantity"] if row else 0
        to_consume = min(available, quantity)

        batches = cur.execute(
            """
            SELECT id, quantity FROM purchase_batches
            WHERE product_id=? AND size=?
            ORDER BY price ASC, purchase_date ASC
            """,
            (product_id, size),
        ).fetchall()

        remaining = to_consume
        for batch in batches:
            if remaining <= 0:
                break
            use = remaining if batch["quantity"] >= remaining else batch["quantity"]
            new_q = batch["quantity"] - use
            if new_q == 0:
                cur.execute(
                    "DELETE FROM purchase_batches WHERE id=?",
                    (batch["id"],),
                )
            else:
                cur.execute(
                    "UPDATE purchase_batches SET quantity=? WHERE id=?",
                    (new_q, batch["id"]),
                )
            remaining -= use

        if to_consume > 0:
            cur.execute(
                "UPDATE product_sizes SET quantity = quantity - ? "
                "WHERE product_id=? AND size=?",
                (to_consume - remaining, product_id, size),
            )
        conn.commit()
    return to_consume - remaining


