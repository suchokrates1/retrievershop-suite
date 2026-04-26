"""
Migration: Add 'refund_processed' column to returns table
Date: 2026-03-25
Description: Separate flag for money refund vs stock restore.
  Previously status='completed' meant both stock restored AND money refunded,
  which was incorrect (stock restore != money refund).
  Now refund_processed tracks actual money refund independently.
  Also fixes returns that got completed via stock restore without actual refund.
"""

import sqlite3
import sys


def migrate(db_path):
    """Add refund_processed column and fix incorrectly completed returns."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        cursor.execute("PRAGMA table_info(returns)")
        columns = [row[1] for row in cursor.fetchall()]

        if "refund_processed" in columns:
            print("[OK] Column 'refund_processed' already exists")
        else:
            cursor.execute("""
                ALTER TABLE returns
                ADD COLUMN refund_processed BOOLEAN NOT NULL DEFAULT 0
            """)
            print("[OK] Added column 'refund_processed' to returns")

        # Napraw zwroty ktore dostaly status completed tylko przez stock restore
        # (nie przez faktyczny zwrot pieniedzy). Przywroc je do delivered.
        cursor.execute("""
            UPDATE returns
            SET status = 'delivered'
            WHERE status = 'completed'
              AND stock_restored = 1
              AND refund_processed = 0
        """)
        fixed = cursor.rowcount
        if fixed:
            print(f"[OK] Fixed {fixed} returns: completed -> delivered (stock restored but no refund)")

        conn.commit()
        print("[OK] Migration completed")

    except Exception as e:
        conn.rollback()
        print(f"[ERROR] Migration failed: {e}")
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    db_path = sys.argv[1] if len(sys.argv) > 1 else "/app/data/database.db"
    migrate(db_path)
