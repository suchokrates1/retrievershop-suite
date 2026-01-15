"""Migracja tworzaca tabele returns i return_status_logs."""
from magazyn import DB_PATH
from magazyn.db import sqlite_connect


def migrate():
    with sqlite_connect(DB_PATH) as conn:
        cur = conn.cursor()
        
        # Sprawdz czy tabela returns juz istnieje
        cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='returns'"
        )
        if not cur.fetchone():
            cur.execute("""
                CREATE TABLE returns (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_id TEXT NOT NULL REFERENCES orders(order_id) ON DELETE CASCADE,
                    status TEXT NOT NULL DEFAULT 'pending',
                    customer_name TEXT,
                    items_json TEXT,
                    return_tracking_number TEXT,
                    return_carrier TEXT,
                    allegro_return_id TEXT,
                    messenger_notified INTEGER NOT NULL DEFAULT 0,
                    stock_restored INTEGER NOT NULL DEFAULT 0,
                    notes TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL
                )
            """)
            cur.execute("CREATE INDEX idx_returns_order_id ON returns(order_id)")
            cur.execute("CREATE INDEX idx_returns_status ON returns(status)")
            cur.execute("CREATE INDEX idx_returns_created_at ON returns(created_at)")
            conn.commit()
            print("Utworzono tabele returns z indeksami")
        else:
            print("Tabela returns juz istnieje")
        
        # Sprawdz czy tabela return_status_logs juz istnieje
        cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='return_status_logs'"
        )
        if not cur.fetchone():
            cur.execute("""
                CREATE TABLE return_status_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    return_id INTEGER NOT NULL REFERENCES returns(id) ON DELETE CASCADE,
                    status TEXT NOT NULL,
                    notes TEXT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL
                )
            """)
            cur.execute("CREATE INDEX idx_return_status_logs_return_id ON return_status_logs(return_id)")
            conn.commit()
            print("Utworzono tabele return_status_logs z indeksem")
        else:
            print("Tabela return_status_logs juz istnieje")


if __name__ == "__main__":
    migrate()
