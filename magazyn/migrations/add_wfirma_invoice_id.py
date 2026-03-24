"""
Migration: Add wfirma_invoice_id, wfirma_invoice_number, emails_sent columns.
Date: 2026-03-25
Description: Dodaje kolumny do zamowien potrzebne do integracji
z wFirma (dane faktury) i sledzenia wyslanych emaili.
"""

import sqlite3


def migrate(db_path):
    """Add wfirma invoice and email tracking columns to orders."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        cursor.execute("PRAGMA table_info(orders)")
        columns = [row[1] for row in cursor.fetchall()]

        added = []

        if "wfirma_invoice_id" not in columns:
            cursor.execute(
                "ALTER TABLE orders ADD COLUMN wfirma_invoice_id INTEGER"
            )
            added.append("wfirma_invoice_id")

        if "wfirma_invoice_number" not in columns:
            cursor.execute(
                "ALTER TABLE orders ADD COLUMN wfirma_invoice_number TEXT"
            )
            added.append("wfirma_invoice_number")

        if "emails_sent" not in columns:
            cursor.execute(
                "ALTER TABLE orders ADD COLUMN emails_sent TEXT"
            )
            added.append("emails_sent")

        conn.commit()

        if added:
            print(f"[OK] Dodano kolumny: {', '.join(added)}")
        else:
            print("[OK] Wszystkie kolumny juz istnieja")
    except Exception as exc:
        conn.rollback()
        print(f"[BLAD] Migracja wfirma_invoice_id: {exc}")
        raise
    finally:
        conn.close()
