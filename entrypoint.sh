#!/bin/bash
set -euo pipefail

echo "Starting Horilla HRMS Deployment..."

echo "Waiting for database to be ready..."
for i in $(seq 1 60); do
  if pg_isready -h "${DB_HOST}" -p "${DB_PORT}" -U "${DB_USER}" > /dev/null 2>&1; then
    echo "Database is ready!"
    break
  fi
  if [ "$i" -eq 60 ]; then
    echo "Database did not become ready in time."
    exit 1
  fi
  echo "Database is unavailable - sleeping ($i/60)"
  sleep 3
done

echo "Running database migrations..."
python3 manage.py migrate --noinput

echo "Collecting static files..."
python3 manage.py collectstatic --noinput

echo "Starting Gunicorn server..."
# Default workers=1 suits 2GB droplets; override with GUNICORN_WORKERS
exec gunicorn --bind 0.0.0.0:8000 \
  --workers "${GUNICORN_WORKERS:-1}" \
  --threads "${GUNICORN_THREADS:-2}" \
  --preload \
  --max-requests "${GUNICORN_MAX_REQUESTS:-1000}" \
  --max-requests-jitter "${GUNICORN_MAX_REQUESTS_JITTER:-50}" \
  --timeout "${GUNICORN_TIMEOUT:-120}" \
  horilla.wsgi:application
