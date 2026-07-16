#!/bin/bash

echo "🚀 Starting Horilla HRMS Deployment..."

echo "⏳ Waiting for database to be ready..."
for i in {1..60}; do
  if pg_isready -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" > /dev/null 2>&1; then
    echo "✅ Database is ready!"
    break
  fi
  echo "⏳ Database is unavailable - sleeping ($i/60)"
  sleep 3
done

# In production we only apply migrations (create them in dev and commit)
echo "📊 Running database migrations..."
python3 manage.py migrate --noinput || true

echo "📁 Collecting static files..."
python3 manage.py collectstatic --noinput || true

echo "🚀 Starting Gunicorn server..."
# Tuned for 4GB server: workers + threads, preload (load code once), max-requests (recycle workers).
exec gunicorn --bind 0.0.0.0:8000 \
  --workers "${GUNICORN_WORKERS:-2}" \
  --threads "${GUNICORN_THREADS:-2}" \
  --preload \
  --max-requests "${GUNICORN_MAX_REQUESTS:-1000}" \
  --max-requests-jitter "${GUNICORN_MAX_REQUESTS_JITTER:-50}" \
  --timeout "${GUNICORN_TIMEOUT:-120}" \
  horilla.wsgi:application
