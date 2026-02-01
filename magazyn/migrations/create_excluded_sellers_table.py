"""
Migracja: Tworzenie tabeli excluded_sellers.

Tabela przechowuje liste sprzedawcow wykluczonych z analizy konkurencji.
"""

import logging
from datetime import datetime

logger = logging.getLogger(__name__)


def upgrade(engine):
    """Tworzy tabele excluded_sellers."""
    from sqlalchemy import text
    
    with engine.connect() as conn:
        # Sprawdz czy tabela istnieje
        result = conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='excluded_sellers'")
        )
        if result.fetchone():
            logger.info("Tabela excluded_sellers juz istnieje - pomijam")
            return
        
        # Utworz tabele
        conn.execute(text("""
            CREATE TABLE excluded_sellers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                seller_name TEXT NOT NULL UNIQUE,
                excluded_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                reason TEXT
            )
        """))
        
        # Indeks na nazwe sprzedawcy
        conn.execute(text(
            "CREATE INDEX idx_excluded_sellers_name ON excluded_sellers(seller_name)"
        ))
        
        conn.commit()
        logger.info("Utworzono tabele excluded_sellers")


def downgrade(engine):
    """Usuwa tabele excluded_sellers."""
    from sqlalchemy import text
    
    with engine.connect() as conn:
        conn.execute(text("DROP TABLE IF EXISTS excluded_sellers"))
        conn.commit()
        logger.info("Usunieto tabele excluded_sellers")


if __name__ == "__main__":
    from magazyn.db import engine
    upgrade(engine)
