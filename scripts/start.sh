#!/bin/sh
set -e

PORT="${PORT:-8080}"
WORKERS="${WEB_CONCURRENCY:-2}"

ensure_schema() {
  python - <<'PY'
from sqlalchemy import inspect, text
from db.base import get_engine

engine = get_engine()
insp = inspect(engine)
tables = set(insp.get_table_names())
need_tables = {"owner", "city_object", "app_user", "district", "object_type", "region", "subscription", "plan"}
missing_tables = sorted(need_tables - tables)

# Migration 0002: public API ids live in ``code`` on these tables.
need_code = ("owner", "app_user", "city_object")
missing_code = [
    t for t in need_code
    if t in tables and "code" not in {c["name"] for c in insp.get_columns(t)}
]
missing_region = [
    t for t in ("district", "city_object", "owner")
    if t in tables and "region_id" not in {c["name"] for c in insp.get_columns(t)}
]

print(
    f"Schema check: tables={len(tables)} "
    f"missing_tables={missing_tables} missing_code={missing_code} missing_region={missing_region}"
)
if not missing_tables and not missing_code and not missing_region:
    raise SystemExit(0)

print("Schema incomplete — resetting public schema and re-applying migrations")
with engine.begin() as conn:
    conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
    conn.execute(text("CREATE SCHEMA public"))
    conn.execute(text("GRANT ALL ON SCHEMA public TO public"))
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
