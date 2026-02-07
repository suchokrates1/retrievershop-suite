"""
Dodaje kolumny competitor_is_super_seller i competitors_all_count 
do tabeli price_report_items.
"""

import sqlite3
import logging
import os

logger = logging.getLogger(__name__)


def get_db_path():
    return os.environ.get("DATABASE_PATH", "/app/data/database.db")


def upgrade(db_path=None):
    """Dodaje nowe kolumny do price_report_items."""
    if db_path is None:
        db_path = get_db_path()

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        # Sprawdz czy tabela istnieje
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='price_report_items'"
        )
        if not cursor.fetchone():
            logger.info("Tabela price_report_items nie istnieje - pomijam")
            return

        # Sprawdz istniejace kolumny
        cursor.execute("PRAGMA table_info(price_report_items)")
        existing_columns = {row[1] for row in cursor.fetchall()}

        if "competitor_is_super_seller" not in existing_columns:
            cursor.execute(
                "ALTER TABLE price_report_items ADD COLUMN competitor_is_super_seller BOOLEAN"
            )
            logger.info("Dodano kolumne competitor_is_super_seller")

        if "competitors_all_count" not in existing_columns:
            cursor.execute(
                "ALTER TABLE price_report_items ADD COLUMN competitors_all_count INTEGER"
            )
            logger.info("Dodano kolumne competitors_all_count")

        conn.commit()
        logger.info("Migracja add_competitor_details_to_report_items zakonczona")
    finally:
        cursor.close()
        conn.close()


if __name__ == "__main__":
    upgrade()
