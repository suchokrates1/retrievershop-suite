import sqlite3
from magazyn import DB_PATH


def migrate():
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("PRAGMA table_info(product_sizes)")
        cols = [row[1] for row in cur.fetchall()]
        if "barcode" not in cols:
            cur.execute("ALTER TABLE product_sizes ADD COLUMN barcode TEXT")
            conn.commit()
            print("Added barcode column to product_sizes")
        else:
            print("barcode column already exists")


if __name__ == "__main__":
    migrate()
