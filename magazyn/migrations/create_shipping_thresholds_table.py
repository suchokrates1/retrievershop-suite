from magazyn import DB_PATH
from magazyn.db import sqlite_connect


def migrate():
    with sqlite_connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='shipping_thresholds'"
        )
        if cur.fetchone():
            print("shipping_thresholds table already exists")
            return

        cur.execute(
            """
            CREATE TABLE shipping_thresholds (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                min_order_value REAL NOT NULL,
                shipping_cost NUMERIC(10,2) NOT NULL
            )
            """
        )
        conn.commit()
        print("Created shipping_thresholds table")


if __name__ == "__main__":
    migrate()
