from magazyn import DB_PATH
from magazyn import DB_PATH
from magazyn.db import sqlite_connect


def migrate():
    with sqlite_connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='allegro_price_history'"
        )
        if cur.fetchone():
            print("allegro_price_history table already exists")
            return

        cur.execute(
            """
            CREATE TABLE allegro_price_history (
                id INTEGER PRIMARY KEY,
                offer_id TEXT,
                product_size_id INTEGER REFERENCES product_sizes(id),
                price NUMERIC(10, 2) NOT NULL,
                recorded_at TEXT NOT NULL
            )
            """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_allegro_price_history_offer_id "
            "ON allegro_price_history(offer_id)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_allegro_price_history_product_size "
            "ON allegro_price_history(product_size_id)"
        )
        conn.commit()
        print("Created allegro_price_history table")


if __name__ == "__main__":
    migrate()
