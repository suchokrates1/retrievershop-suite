import sqlite3
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


