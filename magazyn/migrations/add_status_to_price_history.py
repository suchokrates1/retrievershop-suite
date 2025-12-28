"""
Migration: Add 'status' column to allegro_price_history table
Date: 2025-12-28
Description: Adds status column to distinguish 'no_offers' vs 'cheapest' vs 'competitor_cheaper'
"""

import sqlite3
import sys
from pathlib import Path

def migrate(db_path):
    """Add status column to allegro_price_history."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        # Check if column already exists
        cursor.execute("PRAGMA table_info(allegro_price_history)")
        columns = [row[1] for row in cursor.fetchall()]
        
        if 'status' in columns:
            print("[OK] Column 'status' already exists")
            return
        
        # Add status column
        cursor.execute("""
            ALTER TABLE allegro_price_history 
            ADD COLUMN status TEXT DEFAULT 'unknown'
        """)
        
        # Update existing rows based on competitor_price/seller
        cursor.execute("""
            UPDATE allegro_price_history
            SET status = CASE
                WHEN competitor_seller IS NOT NULL AND competitor_price IS NOT NULL THEN 'competitor_cheaper'
                WHEN competitor_seller IS NULL AND competitor_price IS NULL THEN 'cheapest'
                ELSE 'unknown'
            END
            WHERE status = 'unknown'
        """)
        
        conn.commit()
        print("[OK] Added 'status' column to allegro_price_history")
        print(f"[OK] Updated {cursor.rowcount} existing rows")
        
    except Exception as e:
        conn.rollback()
        print(f"[ERROR] Migration failed: {e}")
        raise
    finally:
        conn.close()

if __name__ == "__main__":
    if len(sys.argv) > 1:
        db_path = sys.argv[1]
    else:
        # Default to workspace database
        db_path = Path(__file__).parent.parent.parent / "database.db"
    
    print(f"Running migration on: {db_path}")
    migrate(str(db_path))
