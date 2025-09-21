from magazyn import DB_PATH
from magazyn.db import sqlite_connect


def migrate():
    with sqlite_connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='allegro_offers'"
        )
        if not cur.fetchone():
            cur.execute(
                "CREATE TABLE allegro_offers ("
                "id INTEGER PRIMARY KEY, "
                "offer_id TEXT UNIQUE, "
                "title TEXT NOT NULL, "
                "price REAL NOT NULL, "
                "product_id INTEGER NOT NULL REFERENCES products(id), "
                "product_size_id INTEGER REFERENCES product_sizes(id), "
                "synced_at TEXT)"
            )
            conn.commit()
            print("Created allegro_offers table")
        else:
            print("allegro_offers table already exists")


if __name__ == "__main__":
    migrate()
