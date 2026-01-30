"""
Migracja: Utworzenie tabel dla raportow cenowych.

Tabele:
- price_reports: Glowna tabela raportow
- price_report_items: Pojedyncze wpisy z danymi cenowymi
"""

import logging
import os
import sqlite3

logger = logging.getLogger(__name__)


def get_db_path():
    """Zwraca sciezke do bazy danych."""
    return os.environ.get("DB_PATH", "/app/database.db")


def upgrade(db_path=None):
    """Tworzy tabele price_reports i price_report_items."""
    if db_path is None:
        db_path = get_db_path()
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        # Sprawdz czy tabele juz istnieja
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='price_reports'"
        )
        if cursor.fetchone():
            logger.info("Tabela price_reports juz istnieje - pomijam")
            return
        
        # Utworz tabele price_reports
        cursor.execute("""
            CREATE TABLE price_reports (
                id INTEGER PRIMARY KEY,
                status VARCHAR NOT NULL DEFAULT 'pending',
                items_total INTEGER NOT NULL DEFAULT 0,
                items_checked INTEGER NOT NULL DEFAULT 0,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                completed_at DATETIME
            )
        """)
        
        # Indeksy dla price_reports
        cursor.execute(
            "CREATE INDEX idx_price_reports_created_at ON price_reports(created_at)"
        )
        cursor.execute(
            "CREATE INDEX idx_price_reports_status ON price_reports(status)"
        )
        
        # Utworz tabele price_report_items
        cursor.execute("""
            CREATE TABLE price_report_items (
                id INTEGER PRIMARY KEY,
                report_id INTEGER NOT NULL,
                offer_id VARCHAR NOT NULL,
                product_name VARCHAR,
                our_price NUMERIC(10,2),
                competitor_price NUMERIC(10,2),
                competitor_seller VARCHAR,
                competitor_url VARCHAR,
                is_cheapest BOOLEAN NOT NULL DEFAULT 1,
                price_difference FLOAT,
                our_position INTEGER,
                total_offers INTEGER,
                checked_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                error VARCHAR,
                FOREIGN KEY (report_id) REFERENCES price_reports(id) ON DELETE CASCADE
            )
        """)
        
        # Indeksy dla price_report_items
        cursor.execute(
            "CREATE INDEX idx_price_report_items_report_id ON price_report_items(report_id)"
        )
        cursor.execute(
            "CREATE INDEX idx_price_report_items_offer_id ON price_report_items(offer_id)"
        )
        cursor.execute(
            "CREATE INDEX idx_price_report_items_is_cheapest ON price_report_items(is_cheapest)"
        )
        
        conn.commit()
        logger.info("Utworzono tabele price_reports i price_report_items")
        print("Utworzono tabele price_reports i price_report_items")
    finally:
        cursor.close()
        conn.close()


def downgrade(db_path=None):
    """Usuwa tabele price_reports i price_report_items."""
    if db_path is None:
        db_path = get_db_path()
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        cursor.execute("DROP TABLE IF EXISTS price_report_items")
        cursor.execute("DROP TABLE IF EXISTS price_reports")
        conn.commit()
        logger.info("Usunieto tabele price_reports i price_report_items")
    finally:
        cursor.close()
        conn.close()
