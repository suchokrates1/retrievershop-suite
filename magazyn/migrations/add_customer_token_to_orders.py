"""
Migration: Add customer_token column to orders table.
Date: 2026-03-24
Description: Dodaje kolumne customer_token do zamowien - unikalny token
pozwalajacy klientowi na dostep do strony zamowienia bez logowania.
Generowany przy tworzeniu zamowienia, uzywany w linkach emailowych.
"""

import secrets
import sqlite3


def migrate(db_path):
    """Add customer_token column to orders."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        cursor.execute("PRAGMA table_info(orders)")
        columns = [row[1] for row in cursor.fetchall()]

        if "customer_token" in columns:
            print("[OK] Kolumna 'customer_token' juz istnieje")
            return

        cursor.execute(
            "ALTER TABLE orders ADD COLUMN customer_token TEXT"
        )

        # Wygeneruj tokeny dla istniejacych zamowien
        cursor.execute("SELECT order_id FROM orders WHERE customer_token IS NULL")
        rows = cursor.fetchall()
        for (order_id,) in rows:
            token = secrets.token_urlsafe(32)
            cursor.execute(
                "UPDATE orders SET customer_token = ? WHERE order_id = ?",
                (token, order_id),
            )

        # Indeks na customer_token (uzyty do wyszukiwania)
        cursor.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_orders_customer_token "
            "ON orders(customer_token)"
        )

        conn.commit()
        print(
            f"[OK] Dodano kolumne 'customer_token' i wygenerowano "
            f"tokeny dla {len(rows)} zamowien"
        )
    except Exception as exc:
        conn.rollback()
        print(f"[BLAD] Migracja customer_token: {exc}")
        raise
    finally:
        conn.close()
