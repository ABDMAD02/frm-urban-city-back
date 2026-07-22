#!/bin/sh
set -e

PORT="${PORT:-8080}"
WORKERS="${WEB_CONCURRENCY:-2}"

if [ "${RUN_MIGRATIONS:-0}" = "1" ]; then
  if [ -n "${DATABASE_URL:-}" ]; then
    echo "Running alembic migrations..."
    alembic upgrade head
    echo "Seeding database (idempotent)..."
    python -c "from db.seed import run_seed_cli; run_seed_cli()"
  else
    echo "RUN_MIGRATIONS=1 but DATABASE_URL is empty — skipping migrations"
  fi
fi

exec gunicorn app.main:app \
  --worker-class uvicorn.workers.UvicornWorker \
  --bind "0.0.0.0:${PORT}" \
  --workers "${WORKERS}" \
  --timeout 120 \
  --graceful-timeout 30 \
  --keep-alive 5 \
  --access-logfile - \
  --error-logfile -
