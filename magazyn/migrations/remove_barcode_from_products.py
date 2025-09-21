from magazyn import DB_PATH
from magazyn.db import sqlite_connect


def migrate():
    with sqlite_connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("PRAGMA table_info(products)")
        cols = [row[1] for row in cur.fetchall()]
        if "barcode" in cols:
            cur.execute(
                "CREATE TABLE products_new ("
                "id INTEGER PRIMARY KEY, name TEXT NOT NULL, color TEXT)"
            )
            cur.execute(
                "INSERT INTO products_new (id, name, color) "
                "SELECT id, name, color FROM products"
            )
            cur.execute("DROP TABLE products")
            cur.execute("ALTER TABLE products_new RENAME TO products")
            conn.commit()
            print("Removed barcode column from products")
        else:
            print("barcode column already removed")


if __name__ == "__main__":
    migrate()
