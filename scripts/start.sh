#!/bin/sh
set -e

PORT="${PORT:-8080}"
WORKERS="${WEB_CONCURRENCY:-2}"

reset_public_schema() {
  if [ "${ENV:-development}" = "production" ] && [ "${ALLOW_DB_RESET:-0}" != "1" ]; then
    echo "FATAL: RESET_DB=1 in production without ALLOW_DB_RESET=1 — refusing to drop data."
    exit 1
  fi
  echo "RESET_DB=1 — dropping public schema for a clean database..."
  python - <<'PY'
from sqlalchemy import text
from db.base import get_engine

engine = get_engine()
with engine.begin() as conn:
    conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
    conn.execute(text("CREATE SCHEMA public"))
    conn.execute(text("GRANT ALL ON SCHEMA public TO public"))
print("Public schema recreated")
PY
}

ensure_schema() {
  python - <<'PY'
import os

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text

from db.base import get_engine

_IS_PROD = os.getenv("ENV", "development") == "production"
_ALLOW_RESET = os.getenv("ALLOW_DB_RESET", "0").lower() in ("1", "true", "yes")

# Container cwd is /app; alembic.ini is at repo root.
HEAD_REVISION = ScriptDirectory.from_config(Config("alembic.ini")).get_current_head()

engine = get_engine()
insp = inspect(engine)
tables = set(insp.get_table_names())
# subscription/plan removed in 0008; user_street added in 0007.
need_tables = {
    "owner", "city_object", "app_user", "district", "object_type", "region",
    "street", "user_street",
}
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

alembic_version = None
if "alembic_version" in tables:
    with engine.connect() as conn:
        alembic_version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()

print(
    f"Schema check: tables={len(tables)} "
    f"missing_tables={missing_tables} missing_code={missing_code} "
    f"missing_region={missing_region} alembic_version={alembic_version!r} "
    f"head={HEAD_REVISION!r}"
)

if missing_tables or missing_code or missing_region:
    if _IS_PROD and not _ALLOW_RESET:
        # В production не роняем данные молча. Разбор — вручную/в CI; при
        # осознанном пересоздании выставить ALLOW_DB_RESET=1.
        print(
            "FATAL: schema incomplete in production — refusing to DROP SCHEMA. "
            "Fix manually or set ALLOW_DB_RESET=1 to override."
        )
        raise SystemExit(4)
    print("Schema incomplete — resetting public schema and re-applying migrations")
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
        conn.execute(text("GRANT ALL ON SCHEMA public TO public"))
    raise SystemExit(2)

if alembic_version != HEAD_REVISION:
    # Never stamp forward: that skips DDL (e.g. user_street from 0007).
    print(
        f"Alembic version {alembic_version!r} != head {HEAD_REVISION!r} — need upgrade"
    )
    raise SystemExit(5)

raise SystemExit(0)
PY
}

if [ "${RUN_MIGRATIONS:-0}" = "1" ]; then
  if [ -n "${DATABASE_URL:-}" ]; then
    if [ "${RESET_DB:-0}" = "1" ]; then
      reset_public_schema
    fi

    echo "Running alembic migrations..."
    alembic upgrade head || echo "WARN: alembic upgrade head failed; checking schema..."
    set +e
    ensure_schema
    schema_status=$?
    set -e
    case $schema_status in
      0) ;;
      2)
        echo "Re-running alembic upgrade head after schema reset..."
        alembic upgrade head
        ensure_schema
        ;;
      5)
        echo "Re-running alembic upgrade head (behind head)..."
        alembic upgrade head
        ensure_schema
        ;;
      4)
        echo "Refusing to auto-reset schema in production. Aborting start."
        exit 1
        ;;
      *)
        echo "Schema check failed with unexpected code $schema_status"
        exit 1
        ;;
    esac

    # Minimal platform account only (no demo city data). Default: on.
    if [ "${BOOTSTRAP_PLATFORM:-1}" = "1" ]; then
      echo "Bootstrapping platform superadmin (no demo seed)..."
      python -c "from db.seed import run_platform_bootstrap_cli; run_platform_bootstrap_cli()"
    else
      echo "BOOTSTRAP_PLATFORM=0 — skipping platform bootstrap"
    fi

    # Full demo dataset (districts/objects/users). Default: off.
    if [ "${SEED_DEMO:-0}" = "1" ]; then
      echo "SEED_DEMO=1 — seeding demo dataset..."
      if ! python -c "from db.seed import run_seed_cli; run_seed_cli()"; then
        echo "WARN: demo seed failed; continuing startup (schema is ready)"
      fi
    else
      echo "SEED_DEMO=0 — leaving tenant tables empty"
    fi
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
