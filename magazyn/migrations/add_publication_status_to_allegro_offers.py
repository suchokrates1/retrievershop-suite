"""
Migration: Add 'publication_status' column to allegro_offers table
Date: 2025-12-29
Description: Adds publication_status column to track ACTIVE/ENDED/INACTIVE offers
"""

import sqlite3
import sys
from pathlib import Path

def migrate(db_path):
    """Add publication_status column to allegro_offers."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        # Check if column already exists
        cursor.execute("PRAGMA table_info(allegro_offers)")
        columns = [row[1] for row in cursor.fetchall()]
        
        if 'publication_status' in columns:
            print("[OK] Column 'publication_status' already exists")
            return
        
        # Add publication_status column
        cursor.execute("""
            ALTER TABLE allegro_offers 
            ADD COLUMN publication_status TEXT DEFAULT 'ACTIVE'
        """)
        
        conn.commit()
        print("[SUCCESS] Added 'publication_status' column to allegro_offers")
        
        # Update existing offers to ACTIVE status
        cursor.execute("""
            UPDATE allegro_offers 
            SET publication_status = 'ACTIVE'
            WHERE publication_status IS NULL
        """)
        conn.commit()
        print(f"[SUCCESS] Updated {cursor.rowcount} existing offers to ACTIVE status")
        
    except Exception as e:
        conn.rollback()
        print(f"[ERROR] Migration failed: {e}")
        raise
    finally:
        conn.close()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python add_publication_status_to_allegro_offers.py <db_path>")
        sys.exit(1)
    
    db_path = sys.argv[1]
    if not Path(db_path).exists():
        print(f"[ERROR] Database not found: {db_path}")
        sys.exit(1)
    
    migrate(db_path)
