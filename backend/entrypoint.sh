#!/bin/sh
set -e

echo "Collecting static files..."
python manage.py collectstatic --noinput

echo "Running database migrations..."
python manage.py migrate --noinput

echo "Starting uvicorn..."
exec uvicorn config.asgi:application --host 0.0.0.0 --port 8000