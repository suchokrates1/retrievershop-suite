from magazyn import DB_PATH
from magazyn.db import sqlite_connect


def migrate():
    with sqlite_connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='allegro_offers'"
        )
        if not cur.fetchone():
            print("allegro_offers table does not exist; skipping migration")
            return

        cur.execute("PRAGMA table_info(allegro_offers)")
        columns = cur.fetchall()
        product_column = next((col for col in columns if col[1] == "product_id"), None)
        if not product_column:
            print("product_id column not found on allegro_offers; skipping migration")
            return

        not_null = product_column[3]
        if not_null == 0:
            print("allegro_offers.product_id already allows NULL values")
            return

        cur.execute("ALTER TABLE allegro_offers RENAME TO allegro_offers_old")
        cur.execute(
            """
            CREATE TABLE allegro_offers (
                id INTEGER PRIMARY KEY,
                offer_id TEXT UNIQUE,
                title TEXT NOT NULL,
                price NUMERIC(10,2) NOT NULL,
                product_id INTEGER REFERENCES products(id),
                product_size_id INTEGER REFERENCES product_sizes(id),
                synced_at TEXT
            )
            """
        )
        cur.execute(
            """
            INSERT INTO allegro_offers (
                id, offer_id, title, price, product_id, product_size_id, synced_at
            )
            SELECT
                id, offer_id, title, price, product_id, product_size_id, synced_at
            FROM allegro_offers_old
            """
        )
        cur.execute("DROP TABLE allegro_offers_old")
        conn.commit()
        print("Updated allegro_offers.product_id to allow NULL values")


if __name__ == "__main__":
    migrate()
