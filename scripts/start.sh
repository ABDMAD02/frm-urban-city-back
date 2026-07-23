#!/bin/sh
set -e

PORT="${PORT:-8080}"
WORKERS="${WEB_CONCURRENCY:-2}"

ensure_schema() {
  python - <<'PY'
from sqlalchemy import inspect, text
from db.base import get_engine

engine = get_engine()
tables = set(inspect(engine).get_table_names())
need = {"owner", "city_object", "app_user", "district", "object_type"}
missing = sorted(need - tables)
print(f"Schema check: tables={len(tables)} missing={missing}")
if not missing:
    raise SystemExit(0)

print("Schema incomplete — resetting alembic revision and re-applying migrations")
with engine.begin() as conn:
    conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
raise SystemExit(2)
PY
}

if [ "${RUN_MIGRATIONS:-0}" = "1" ]; then
  if [ -n "${DATABASE_URL:-}" ]; then
    echo "Running alembic migrations..."
    # First attempt may no-op if alembic_version is stamped but tables were dropped.
    alembic upgrade head || echo "WARN: alembic upgrade head failed; checking schema..."
    if ! ensure_schema; then
      echo "Re-running alembic upgrade head after schema reset..."
      alembic upgrade head
      ensure_schema
    fi
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
