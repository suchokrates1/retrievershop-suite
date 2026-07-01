# Legacy SQLite migrations

Ten katalog zawiera **historyczne skrypty migracji SQLite** z okresu przed Alembic.

## Produkcja (PostgreSQL)

Na produkcji schemat jest zarządzany wyłącznie przez **Alembic** (`/migrations/` w root repozytorium).
Entrypoint (`magazyn/entrypoint.sh`) pomija te skrypty, gdy ustawione jest `DATABASE_URL`.

## Lokalny dev (SQLite)

Przy starcie bez `DATABASE_URL` entrypoint uruchamia wybrane skrypty:

- `create_price_reports_tables`
- `create_excluded_sellers_table`
- `add_competitor_details_to_report_items`

Pozostałe pliki w tym katalogu to archiwum jednorazowych migracji — nie uruchamiaj ich ręcznie na Postgresie.

## Testy

Testy jednostkowe używają izolowanego pliku SQLite w `tmp_path` (patrz `magazyn/tests/conftest.py`).
Nigdy nie uruchamiaj `pytest` wewnątrz kontenera produkcyjnego z ustawionym `DATABASE_URL`.
