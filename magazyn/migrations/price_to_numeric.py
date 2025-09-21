from magazyn import DB_PATH
from magazyn.db import sqlite_connect


def _needs_numeric(cur, table, column):
    cur.execute(f"PRAGMA table_info({table})")
    cols = {row[1]: row[2].upper() for row in cur.fetchall()}
    col_type = cols.get(column, "")
    return "NUMERIC" not in col_type


def migrate():
    with sqlite_connect(DB_PATH) as conn:
        cur = conn.cursor()

        if _needs_numeric(cur, "purchase_batches", "price"):
            cur.execute("ALTER TABLE purchase_batches RENAME TO purchase_batches_old")
            cur.execute(
                """
                CREATE TABLE purchase_batches (
                    id INTEGER PRIMARY KEY,
                    product_id INTEGER NOT NULL REFERENCES products(id),
                    size TEXT NOT NULL,
                    quantity INTEGER NOT NULL,
                    price NUMERIC(10,2) NOT NULL,
                    purchase_date TEXT NOT NULL
                )
                """
            )
            cur.execute(
                """
                INSERT INTO purchase_batches (id, product_id, size, quantity, price, purchase_date)
                SELECT id, product_id, size, quantity, price, purchase_date
                FROM purchase_batches_old
                """
            )
            cur.execute("DROP TABLE purchase_batches_old")
            print("Converted purchase_batches.price to NUMERIC")
        else:
            print("purchase_batches.price already NUMERIC")

        cur.execute("PRAGMA table_info(sales)")
        cols = {row[1]: row[2].upper() for row in cur.fetchall()}
        if any(
            "NUMERIC" not in cols.get(col, "")
            for col in [
                "purchase_cost",
                "sale_price",
                "shipping_cost",
                "commission_fee",
            ]
        ):
            cur.execute("ALTER TABLE sales RENAME TO sales_old")
            cur.execute(
                """
                CREATE TABLE sales (
                    id INTEGER PRIMARY KEY,
                    product_id INTEGER NOT NULL REFERENCES products(id),
                    size TEXT NOT NULL,
                    quantity INTEGER NOT NULL,
                    sale_date TEXT NOT NULL,
                    purchase_cost NUMERIC(10,2) NOT NULL DEFAULT 0.0,
                    sale_price NUMERIC(10,2) NOT NULL DEFAULT 0.0,
                    shipping_cost NUMERIC(10,2) NOT NULL DEFAULT 0.0,
                    commission_fee NUMERIC(10,2) NOT NULL DEFAULT 0.0
                )
                """
            )
            cur.execute(
                """
                INSERT INTO sales (
                    id, product_id, size, quantity, sale_date,
                    purchase_cost, sale_price, shipping_cost, commission_fee
                )
                SELECT
                    id, product_id, size, quantity, sale_date,
                    purchase_cost, sale_price, shipping_cost, commission_fee
                FROM sales_old
                """
            )
            cur.execute("DROP TABLE sales_old")
            print("Converted sales price columns to NUMERIC")
        else:
            print("sales price columns already NUMERIC")

        if _needs_numeric(cur, "shipping_thresholds", "shipping_cost"):
            cur.execute(
                "ALTER TABLE shipping_thresholds RENAME TO shipping_thresholds_old"
            )
            cur.execute(
                """
                CREATE TABLE shipping_thresholds (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    min_order_value REAL NOT NULL,
                    shipping_cost NUMERIC(10,2) NOT NULL
                )
                """
            )
            cur.execute(
                """
                INSERT INTO shipping_thresholds (id, min_order_value, shipping_cost)
                SELECT id, min_order_value, shipping_cost
                FROM shipping_thresholds_old
                """
            )
            cur.execute("DROP TABLE shipping_thresholds_old")
            print("Converted shipping_thresholds.shipping_cost to NUMERIC")
        else:
            print("shipping_thresholds.shipping_cost already NUMERIC")

        if _needs_numeric(cur, "allegro_offers", "price"):
            cur.execute("ALTER TABLE allegro_offers RENAME TO allegro_offers_old")
            cur.execute(
                """
                CREATE TABLE allegro_offers (
                    id INTEGER PRIMARY KEY,
                    offer_id TEXT UNIQUE,
                    title TEXT NOT NULL,
                    price NUMERIC(10,2) NOT NULL,
                    product_id INTEGER NOT NULL REFERENCES products(id),
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
            print("Converted allegro_offers.price to NUMERIC")
        else:
            print("allegro_offers.price already NUMERIC")

        conn.commit()


if __name__ == "__main__":
    migrate()
