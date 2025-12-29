#!/bin/sh
# Docker entrypoint script that runs migrations before starting the app

set -e

echo "Running database migrations..."
cd /app
alembic upgrade head

echo "Starting Flask development server..."
exec python -m flask --app magazyn.wsgi run --host 0.0.0.0 --port 8000
