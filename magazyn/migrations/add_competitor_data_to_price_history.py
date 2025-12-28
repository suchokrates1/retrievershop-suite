"""Add competitor data columns to allegro_price_history table."""
from magazyn import DB_PATH
from magazyn.db import sqlite_connect


def migrate():
    with sqlite_connect(DB_PATH) as conn:
        cur = conn.cursor()
        
        # Check if columns already exist
        cur.execute("PRAGMA table_info(allegro_price_history)")
        columns = [row[1] for row in cur.fetchall()]
        
        if "competitor_price" in columns:
            print("Competitor data columns already exist in allegro_price_history")
            return
        
        # Add new columns for competitor data
        cur.execute(
            """
            ALTER TABLE allegro_price_history 
            ADD COLUMN competitor_price NUMERIC(10, 2)
            """
        )
        cur.execute(
            """
            ALTER TABLE allegro_price_history 
            ADD COLUMN competitor_seller TEXT
            """
        )
        cur.execute(
            """
            ALTER TABLE allegro_price_history 
            ADD COLUMN competitor_url TEXT
            """
        )
        cur.execute(
            """
            ALTER TABLE allegro_price_history 
            ADD COLUMN competitor_delivery_days INTEGER
            """
        )
        
        conn.commit()
        print("Added competitor data columns to allegro_price_history table")


if __name__ == "__main__":
    migrate()
