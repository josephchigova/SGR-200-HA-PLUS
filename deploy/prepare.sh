#!/usr/bin/env bash
# Build the frontend, install backend packages, apply migrations, and collect static files.
# Copy backend/.env.production.example to backend/.env and set real values before the first run.
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-$ROOT/backend/.venv/bin/python}"

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "Python not found at $PYTHON_BIN. Create backend/.venv and install requirements first." >&2
  exit 1
fi

cd "$ROOT/frontend"
npm ci
VITE_BASE=/static/ npm run build

cd "$ROOT/backend"
"$PYTHON_BIN" -m pip install -r requirements.txt
"$PYTHON_BIN" manage.py check
"$PYTHON_BIN" manage.py migrate --noinput
"$PYTHON_BIN" manage.py collectstatic --noinput

echo "Ready. Start with: $PYTHON_BIN -m gunicorn config.wsgi:application --bind 127.0.0.1:8000 --workers 3 --timeout 60"
echo "Migrations do not insert reference data. On the Render shell run: python manage.py load_reference_data"
