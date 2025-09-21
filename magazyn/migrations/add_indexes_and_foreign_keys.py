"""Add supporting indexes and explicit ON DELETE actions."""

from __future__ import annotations

from contextlib import contextmanager

from magazyn import DB_PATH
from magazyn.db import sqlite_connect


INDEX_STATEMENTS: tuple[tuple[str, str], ...] = (
    (
        "idx_product_sizes_product_id_size",
        "CREATE INDEX IF NOT EXISTS idx_product_sizes_product_id_size "
        "ON product_sizes(product_id, size)",
    ),
    (
        "idx_sales_sale_date",
        "CREATE INDEX IF NOT EXISTS idx_sales_sale_date ON sales(sale_date)",
    ),
    (
        "idx_allegro_price_history_recorded_at",
        "CREATE INDEX IF NOT EXISTS idx_allegro_price_history_recorded_at "
        "ON allegro_price_history(recorded_at)",
    ),
    (
        "idx_allegro_price_history_offer_recorded_at",
        "CREATE INDEX IF NOT EXISTS idx_allegro_price_history_offer_recorded_at "
        "ON allegro_price_history(offer_id, recorded_at)",
    ),
    (
        "idx_allegro_price_history_product_size",
        "CREATE INDEX IF NOT EXISTS idx_allegro_price_history_product_size "
        "ON allegro_price_history(product_size_id)",
    ),
)


@contextmanager
def _foreign_keys_disabled(conn):
    cur = conn.cursor()
    try:
        cur.execute("PRAGMA foreign_keys=OFF")
        yield
    finally:
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()


def _foreign_key_actions(conn, table: str) -> dict[str, str]:
    cur = conn.cursor()
    try:
        cur.execute(f"PRAGMA foreign_key_list({table})")
        result: dict[str, str] = {}
        for row in cur.fetchall():
            # row[3] -> column name, row[6] -> on_delete
            result[row[3]] = (row[6] or "").upper()
        return result
    finally:
        cur.close()


def _column_allows_null(conn, table: str, column: str) -> bool:
    cur = conn.cursor()
    try:
        cur.execute(f"PRAGMA table_info({table})")
        for cid, name, _type, notnull, *_ in cur.fetchall():
            if name == column:
                return not notnull
        raise ValueError(f"Column {column} not found in table {table}")
    finally:
        cur.close()


def _rebuild_table(conn, table: str, create_sql: str, columns: tuple[str, ...]):
    with _foreign_keys_disabled(conn):
        cur = conn.cursor()
        try:
            conn.execute("BEGIN")
            cur.execute(f"ALTER TABLE {table} RENAME TO {table}_old")
            cur.execute(create_sql)
            column_list = ", ".join(columns)
            cur.execute(
                f"INSERT INTO {table} ({column_list}) SELECT {column_list} FROM {table}_old"
            )
            cur.execute(f"DROP TABLE {table}_old")
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()


def _ensure_product_sizes(conn):
    actions = _foreign_key_actions(conn, "product_sizes")
    if actions.get("product_id") == "CASCADE":
        return

    _rebuild_table(
        conn,
        "product_sizes",
        """
        CREATE TABLE product_sizes (
            id INTEGER PRIMARY KEY,
            product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
            size TEXT NOT NULL,
            quantity INTEGER NOT NULL DEFAULT 0,
            barcode TEXT UNIQUE
        )
        """,
        ("id", "product_id", "size", "quantity", "barcode"),
    )


def _ensure_purchase_batches(conn):
    actions = _foreign_key_actions(conn, "purchase_batches")
    if actions.get("product_id") == "CASCADE":
        return

    _rebuild_table(
        conn,
        "purchase_batches",
        """
        CREATE TABLE purchase_batches (
            id INTEGER PRIMARY KEY,
            product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
            size TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            price NUMERIC(10,2) NOT NULL,
            purchase_date TEXT NOT NULL
        )
        """,
        ("id", "product_id", "size", "quantity", "price", "purchase_date"),
    )


def _ensure_sales(conn):
    actions = _foreign_key_actions(conn, "sales")
    allows_null = _column_allows_null(conn, "sales", "product_id")
    if actions.get("product_id") == "SET NULL" and allows_null:
        return

    _rebuild_table(
        conn,
        "sales",
        """
        CREATE TABLE sales (
            id INTEGER PRIMARY KEY,
            product_id INTEGER REFERENCES products(id) ON DELETE SET NULL,
            size TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            sale_date TEXT NOT NULL,
            purchase_cost NUMERIC(10,2) NOT NULL DEFAULT 0.0,
            sale_price NUMERIC(10,2) NOT NULL DEFAULT 0.0,
            shipping_cost NUMERIC(10,2) NOT NULL DEFAULT 0.0,
            commission_fee NUMERIC(10,2) NOT NULL DEFAULT 0.0
        )
        """,
        (
            "id",
            "product_id",
            "size",
            "quantity",
            "sale_date",
            "purchase_cost",
            "sale_price",
            "shipping_cost",
            "commission_fee",
        ),
    )


def _ensure_allegro_offers(conn):
    actions = _foreign_key_actions(conn, "allegro_offers")
    allows_null = _column_allows_null(conn, "allegro_offers", "product_id")
    if (
        actions.get("product_id") == "SET NULL"
        and actions.get("product_size_id") == "SET NULL"
        and allows_null
    ):
        return

    _rebuild_table(
        conn,
        "allegro_offers",
        """
        CREATE TABLE allegro_offers (
            id INTEGER PRIMARY KEY,
            offer_id TEXT UNIQUE,
            title TEXT NOT NULL,
            price NUMERIC(10,2) NOT NULL,
            product_id INTEGER REFERENCES products(id) ON DELETE SET NULL,
            product_size_id INTEGER REFERENCES product_sizes(id) ON DELETE SET NULL,
            synced_at TEXT
        )
        """,
        (
            "id",
            "offer_id",
            "title",
            "price",
            "product_id",
            "product_size_id",
            "synced_at",
        ),
    )


def _ensure_price_history(conn):
    actions = _foreign_key_actions(conn, "allegro_price_history")
    if actions.get("product_size_id") == "SET NULL":
        return

    _rebuild_table(
        conn,
        "allegro_price_history",
        """
        CREATE TABLE allegro_price_history (
            id INTEGER PRIMARY KEY,
            offer_id TEXT,
            product_size_id INTEGER REFERENCES product_sizes(id) ON DELETE SET NULL,
            price NUMERIC(10,2) NOT NULL,
            recorded_at TEXT NOT NULL
        )
        """,
        ("id", "offer_id", "product_size_id", "price", "recorded_at"),
    )


def _ensure_indexes(conn):
    cur = conn.cursor()
    try:
        for name, statement in INDEX_STATEMENTS:
            cur.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name=?",
                (name,),
            )
            if cur.fetchone():
                continue
            cur.execute(statement)
    finally:
        cur.close()


def migrate():
    with sqlite_connect(DB_PATH) as conn:
        _ensure_product_sizes(conn)
        _ensure_purchase_batches(conn)
        _ensure_sales(conn)
        _ensure_allegro_offers(conn)
        _ensure_price_history(conn)
        _ensure_indexes(conn)
        conn.commit()


if __name__ == "__main__":
    migrate()
