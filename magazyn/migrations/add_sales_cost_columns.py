import sqlite3

from magazyn import DB_PATH


COLUMNS = {
    "purchase_cost": "NUMERIC(10,2) DEFAULT 0.0 NOT NULL",
    "sale_price": "NUMERIC(10,2) DEFAULT 0.0 NOT NULL",
    "shipping_cost": "NUMERIC(10,2) DEFAULT 0.0 NOT NULL",
    "commission_fee": "NUMERIC(10,2) DEFAULT 0.0 NOT NULL",
}


def migrate():
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("PRAGMA table_info(sales)")
        existing = {row[1] for row in cur.fetchall()}
        changed = False

        for column, definition in COLUMNS.items():
            if column not in existing:
                cur.execute(f"ALTER TABLE sales ADD COLUMN {column} {definition}")
                changed = True

        if changed:
            conn.commit()
            print("Added missing financial columns to sales")
        else:
            print("Sales table already contains financial columns")


if __name__ == "__main__":
    migrate()
