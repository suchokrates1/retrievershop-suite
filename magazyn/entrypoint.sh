#!/bin/sh
# Docker entrypoint script that runs migrations before starting the app

set -e

echo "Running database migrations..."
cd /app
alembic upgrade head

echo "Running custom migrations..."
python -c "
from magazyn.migrations.create_price_reports_tables import run_migration
run_migration()
"

echo "Starting Gunicorn..."
exec gunicorn magazyn.wsgi:app --bind 0.0.0.0:8000 --config magazyn/gunicorn.conf.py
