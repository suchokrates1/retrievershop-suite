#!/bin/sh
# Docker entrypoint script that runs migrations before starting the app

set -e

echo "Running database migrations..."
cd /app
alembic upgrade head

echo "Starting Gunicorn..."
exec gunicorn magazyn.wsgi:app --bind 0.0.0.0:8000 --config magazyn/gunicorn.conf.py
