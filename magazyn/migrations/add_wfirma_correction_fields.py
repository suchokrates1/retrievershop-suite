"""
Migration: Add wfirma_correction_id, wfirma_correction_number columns.
Date: 2026-03-25
Description: Dodaje kolumny do zamowien na dane korekty faktury wFirma.
"""

import sqlite3


def migrate(db_path):
    """Add wfirma correction columns to orders."""
    conn = sqlite3.connect(db_path, timeout=30)
    cursor = conn.cursor()

    try:
        cursor.execute("PRAGMA table_info(orders)")
        columns = [row[1] for row in cursor.fetchall()]

        added = []

        if "wfirma_correction_id" not in columns:
            cursor.execute(
                "ALTER TABLE orders ADD COLUMN wfirma_correction_id INTEGER"
            )
            added.append("wfirma_correction_id")

        if "wfirma_correction_number" not in columns:
            cursor.execute(
                "ALTER TABLE orders ADD COLUMN wfirma_correction_number TEXT"
            )
            added.append("wfirma_correction_number")

        conn.commit()

        if added:
            print(f"Dodano kolumny: {', '.join(added)}")
        else:
            print("Kolumny juz istnieja - pomijam.")

    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()
