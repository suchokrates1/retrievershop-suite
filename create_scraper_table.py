import sqlite3

conn = sqlite3.connect("/app/database.db")

conn.execute("""
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
""")

conn.execute("CREATE INDEX IF NOT EXISTS idx_scraper_tasks_status ON scraper_tasks(status)")
conn.execute("CREATE INDEX IF NOT EXISTS idx_scraper_tasks_ean ON scraper_tasks(ean)")

conn.commit()
print("✓ Tabela scraper_tasks utworzona")
