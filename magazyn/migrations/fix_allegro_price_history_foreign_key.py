"""Ensure allegro_price_history points to product_sizes."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

from magazyn import DB_PATH
from magazyn.db import sqlite_connect, _record_migration


CREATE_TABLE_SQL = """
CREATE TABLE allegro_price_history (
    id INTEGER PRIMARY KEY,
    offer_id TEXT,
    product_size_id INTEGER REFERENCES product_sizes(id) ON DELETE SET NULL,
    price NUMERIC(10,2) NOT NULL,
    recorded_at TEXT NOT NULL
)
"""

COLUMN_LIST = ("id", "offer_id", "product_size_id", "price", "recorded_at")

INDEX_STATEMENTS = (
    "CREATE INDEX IF NOT EXISTS idx_allegro_price_history_offer_id "
    "ON allegro_price_history(offer_id)",
    "CREATE INDEX IF NOT EXISTS idx_allegro_price_history_product_size "
    "ON allegro_price_history(product_size_id)",
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


def _table_exists(conn, table: str) -> bool:
    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    )
    try:
        return cur.fetchone() is not None
    finally:
        cur.close()


def _product_size_fk_target(conn) -> str | None:
    try:
        cur = conn.execute("PRAGMA foreign_key_list('allegro_price_history')")
    except sqlite3.OperationalError:
        return None
    try:
        for row in cur.fetchall():
            # row[3] -> column name, row[2] -> referenced table
            if row[3] == "product_size_id":
                return row[2]
    finally:
        cur.close()
    return None


def _rebuild_price_history(conn):
    with _foreign_keys_disabled(conn):
        cur = conn.cursor()
        try:
            conn.execute("BEGIN")
            cur.execute("ALTER TABLE allegro_price_history RENAME TO allegro_price_history_old")
            cur.execute(CREATE_TABLE_SQL)
            columns = ", ".join(COLUMN_LIST)
            cur.execute(
                f"INSERT INTO allegro_price_history ({columns}) "
                f"SELECT {columns} FROM allegro_price_history_old"
            )
            cur.execute("DROP TABLE allegro_price_history_old")
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()


def _ensure_indexes(conn):
    for statement in INDEX_STATEMENTS:
        conn.execute(statement)


def migrate():
    migration_name = Path(__file__).name
    with sqlite_connect(DB_PATH) as conn:
        table_exists = _table_exists(conn, "allegro_price_history")
        fk_target = _product_size_fk_target(conn) if table_exists else None

        needs_rebuild = False
        if not table_exists:
            needs_rebuild = True
        elif fk_target != "product_sizes":
            needs_rebuild = True

        if needs_rebuild:
            if table_exists:
                _rebuild_price_history(conn)
            else:
                conn.execute(CREATE_TABLE_SQL)
                conn.commit()

            _ensure_indexes(conn)
            conn.commit()

        conn.execute("DROP TABLE IF EXISTS product_sizes_old")
        conn.commit()

    _record_migration(migration_name)


if __name__ == "__main__":
    migrate()
