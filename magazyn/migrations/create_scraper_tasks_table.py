"""
Migration: Create scraper_tasks table

Stores scraping tasks for external workers.
"""

def up(db):
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS scraper_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ean TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            price NUMERIC(10, 2),
            url TEXT,
            error TEXT,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            processing_started_at TIMESTAMP,
            completed_at TIMESTAMP
        )
        """
    )
    
    db.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_scraper_tasks_status
        ON scraper_tasks(status)
        """
    )
    
    db.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_scraper_tasks_ean
        ON scraper_tasks(ean)
        """
    )


def down(db):
    db.execute("DROP TABLE IF EXISTS scraper_tasks")
