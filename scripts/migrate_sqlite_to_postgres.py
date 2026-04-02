#!/usr/bin/env python3
"""Migracja danych z SQLite do PostgreSQL.

Uzycie:
    python scripts/migrate_sqlite_to_postgres.py [sciezka_sqlite] [database_url]

Domyslnie:
    sciezka_sqlite = /app/data/database.db (lub data/database.db lokalnie)
    database_url   = zmienna srodowiskowa DATABASE_URL

Skrypt:
1. Tworzy schemat w PostgreSQL na podstawie modeli SQLAlchemy
2. Kopiuje dane z kazdej tabeli SQLite -> PostgreSQL
3. Resetuje sekwencje (SERIAL) w PostgreSQL
4. Weryfikuje liczbe wierszy
"""

import os
import sys
import sqlite3
from pathlib import Path

# Dodaj katalog nadrzedny do sciezki importow
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine, text, inspect
from sqlalchemy.orm import sessionmaker

from magazyn.models import Base


# Tabele w kolejnosci uwzgledniajacej relacje (FK) - rodzice najpierw
TABLE_ORDER = [
    "users",
    "products",
    "product_sizes",
    "printed_orders",
    "label_queue",
    "scan_logs",
    "purchase_batches",
    "sales",
    "shipping_thresholds",
    "allegro_offers",
    "allegro_price_history",
    "app_settings",
    "fixed_costs",
    "allegro_replied_threads",
    "allegro_replied_discussions",
    "threads",
    "messages",
    "orders",
    "order_products",
    "order_status_logs",
    "returns",
    "return_status_logs",
    "price_reports",
    "price_report_items",
    "excluded_sellers",
    "stocktakes",
    "stocktake_items",
]

# Kolumny Boolean w SQLite (0/1) -> PostgreSQL (true/false)
BOOLEAN_COLUMNS = {
    "scan_logs": {"success"},
    "orders": {"confirmed", "payment_method_cod", "want_invoice"},
    "fixed_costs": {"is_active"},
    "threads": {"read"},
    "returns": {"messenger_notified", "stock_restored", "refund_processed"},
    "price_report_items": {"is_cheapest", "competitor_is_super_seller"},
}

BATCH_SIZE = 500


def get_sqlite_tables(sqlite_conn):
    """Pobierz liste tabel z SQLite."""
    cur = sqlite_conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    )
    return {row[0] for row in cur.fetchall()}


def get_sqlite_columns(sqlite_conn, table):
    """Pobierz nazwy kolumn dla tabeli SQLite."""
    cur = sqlite_conn.execute(f"PRAGMA table_info('{table}')")
    return [row[1] for row in cur.fetchall()]


def convert_row(table, columns, row):
    """Konwertuj wiersz SQLite na dane kompatybilne z PostgreSQL."""
    bool_cols = BOOLEAN_COLUMNS.get(table, set())
    result = {}
    created_at_val = None
    for col, val in zip(columns, row):
        if col in bool_cols and val is not None:
            val = bool(val)
        if col == "created_at" and val is not None:
            created_at_val = val
        result[col] = val

    # Fallback: jesli updated_at jest NULL a model wymaga NOT NULL
    if "updated_at" in result and result["updated_at"] is None:
        result["updated_at"] = created_at_val or "2026-01-01 00:00:00"

    return result


def migrate(sqlite_path, database_url):
    """Glowna funkcja migracji."""
    print(f"Zrodlo SQLite: {sqlite_path}")
    print(f"Cel PostgreSQL: {database_url.split('@')[1] if '@' in database_url else '***'}")
    print()

    # Polacz z SQLite
    sqlite_conn = sqlite3.connect(str(sqlite_path))
    sqlite_conn.row_factory = None
    sqlite_tables = get_sqlite_tables(sqlite_conn)

    # Polacz z PostgreSQL
    pg_engine = create_engine(database_url, future=True)
    PgSession = sessionmaker(bind=pg_engine)

    # 1. Utworz schemat
    print("=== TWORZENIE SCHEMATU ===")
    Base.metadata.create_all(pg_engine)
    print("Schemat utworzony pomyslnie.")
    print()

    # 2. Sprawdz ktore tabele istnieja w obu bazach
    pg_inspector = inspect(pg_engine)
    pg_tables = set(pg_inspector.get_table_names())

    tables_to_migrate = []
    for table in TABLE_ORDER:
        if table in sqlite_tables and table in pg_tables:
            tables_to_migrate.append(table)
        elif table in sqlite_tables:
            print(f"  UWAGA: {table} istnieje w SQLite ale nie w PostgreSQL - pomijam")
        elif table not in sqlite_tables:
            print(f"  INFO: {table} nie istnieje w SQLite - pomijam")

    # Dodaj tabele z SQLite ktore nie sa w TABLE_ORDER
    extra_tables = sqlite_tables - set(TABLE_ORDER) - {"alembic_version"}
    for table in sorted(extra_tables):
        if table in pg_tables:
            tables_to_migrate.append(table)
            print(f"  EXTRA: {table} - dodaje do migracji")

    print()

    # 3. Kopiuj dane (z wylaczonymi FK constraints)
    print("=== KOPIOWANIE DANYCH ===")
    stats = {}
    for table in tables_to_migrate:
        sqlite_cols = get_sqlite_columns(sqlite_conn, table)

        # Sprawdz kolumny w PostgreSQL
        pg_cols = {c["name"] for c in pg_inspector.get_columns(table)}
        # Uzyj tylko kolumn wspolnych
        common_cols = [c for c in sqlite_cols if c in pg_cols]
        if not common_cols:
            print(f"  {table}: brak wspolnych kolumn - pomijam")
            continue

        # Pobierz dane z SQLite
        cols_sql = ", ".join(f'"{c}"' for c in common_cols)
        cur = sqlite_conn.execute(f'SELECT {cols_sql} FROM "{table}"')
        rows = cur.fetchall()

        if not rows:
            print(f"  {table}: 0 wierszy - pomijam")
            stats[table] = 0
            continue

        # Wyczysc tabele docelowa i wstaw dane z wylaczonymi FK
        with pg_engine.connect() as conn:
            conn.execute(text(f'DELETE FROM "{table}"'))
            # Wylacz sprawdzanie FK na czas insertu
            conn.execute(text("SET session_replication_role = 'replica'"))

            inserted = 0
            for i in range(0, len(rows), BATCH_SIZE):
                batch = rows[i:i + BATCH_SIZE]
                params_list = []
                for row in batch:
                    params_list.append(convert_row(table, common_cols, row))

                placeholders = ", ".join(f":{c}" for c in common_cols)
                insert_sql = f'INSERT INTO "{table}" ({cols_sql}) VALUES ({placeholders})'
                conn.execute(text(insert_sql), params_list)
                inserted += len(batch)

            # Przywroc sprawdzanie FK
            conn.execute(text("SET session_replication_role = 'origin'"))
            conn.commit()

        print(f"  {table}: {inserted} wierszy")
        stats[table] = inserted

    print()

    # 4. Reset sekwencji
    print("=== RESET SEKWENCJI ===")
    with pg_engine.connect() as conn:
        for table in tables_to_migrate:
            # Sprawdz czy tabela ma kolumne id typu SERIAL
            columns = pg_inspector.get_columns(table)
            id_col = next((c for c in columns if c["name"] == "id"), None)
            if id_col and hasattr(id_col.get("default", ""), "__str__") and "nextval" in str(id_col.get("default", "")):
                result = conn.execute(text(f'SELECT MAX(id) FROM "{table}"'))
                max_id = result.scalar()
                if max_id is not None:
                    seq_name = f"{table}_id_seq"
                    conn.execute(text(f"SELECT setval('{seq_name}', {max_id})"))
                    print(f"  {table}_id_seq -> {max_id}")
        conn.commit()
    print()

    # 5. Weryfikacja
    print("=== WERYFIKACJA ===")
    ok = True
    for table, expected in stats.items():
        with pg_engine.connect() as conn:
            result = conn.execute(text(f'SELECT COUNT(*) FROM "{table}"'))
            actual = result.scalar()
        status = "OK" if actual == expected else "BLAD"
        if status == "BLAD":
            ok = False
        print(f"  {table}: SQLite={expected}, PG={actual} [{status}]")

    print()
    if ok:
        print("Migracja zakonczona pomyslnie!")
    else:
        print("UWAGA: Wystapily roznice w liczbie wierszy!")

    sqlite_conn.close()
    pg_engine.dispose()
    return ok


if __name__ == "__main__":
    sqlite_path = sys.argv[1] if len(sys.argv) > 1 else None
    database_url = sys.argv[2] if len(sys.argv) > 2 else os.environ.get("DATABASE_URL")

    if not sqlite_path:
        # Domyslne sciezki
        candidates = [
            Path("/app/data/database.db"),
            Path("data/database.db"),
        ]
        for p in candidates:
            if p.exists():
                sqlite_path = p
                break
        if not sqlite_path:
            print("Nie znaleziono bazy SQLite. Podaj sciezke jako argument.")
            sys.exit(1)

    if not database_url:
        print("Brak DATABASE_URL. Ustaw zmienna srodowiskowa lub podaj jako drugi argument.")
        sys.exit(1)

    success = migrate(sqlite_path, database_url)
    sys.exit(0 if success else 1)
