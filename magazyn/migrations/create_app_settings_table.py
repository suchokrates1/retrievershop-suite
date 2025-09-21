from __future__ import annotations

from pathlib import Path

from magazyn import DB_PATH
from magazyn.db import sqlite_connect


SCHEMA = """
CREATE TABLE IF NOT EXISTS app_settings (
    key TEXT PRIMARY KEY,
    value TEXT,
    updated_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
)
"""


def migrate() -> None:
    db_path = Path(DB_PATH)
    with sqlite_connect(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='app_settings'"
        )
        if cursor.fetchone():
            print("app_settings table already exists")
            return

        cursor.execute(SCHEMA)
        conn.commit()
        print("Created app_settings table")


if __name__ == "__main__":
    migrate()

