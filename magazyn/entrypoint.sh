#!/bin/sh
# Docker entrypoint script that runs migrations before starting the app

set -e

echo "Running database migrations..."
cd /app
alembic upgrade head

# Migracje legacy (SQLite-only) - pomijaj na PostgreSQL
if [ -z "$DATABASE_URL" ]; then
    echo "Running custom SQLite migrations..."
    python -c "
from magazyn.migrations.create_price_reports_tables import upgrade
from magazyn.migrations.create_excluded_sellers_table import upgrade as upgrade_excluded
from magazyn.migrations.add_competitor_details_to_report_items import upgrade as upgrade_competitor_details
from magazyn.db import engine, configure_engine
from magazyn.config import settings

# Skonfiguruj engine jesli jeszcze nie jest
if engine is None:
    configure_engine(settings.DB_PATH)
    from magazyn.db import engine

upgrade()
upgrade_excluded(engine)
upgrade_competitor_details()
"
else
    echo "PostgreSQL detected - skipping legacy SQLite migrations (schema managed by Alembic)"
fi

echo "Starting Gunicorn..."
exec gunicorn magazyn.wsgi:app --bind 0.0.0.0:8000 --config magazyn/gunicorn.conf.py
