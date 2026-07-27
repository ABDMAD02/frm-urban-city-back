"""Shared helpers for idempotent DDL in Alembic migrations."""


def create_enum_if_not_exists(name: str, values_sql: str) -> str:
    """PostgreSQL ENUM that survives re-run when the type already exists."""
    return f"""
    DO $$ BEGIN
        CREATE TYPE {name} AS ENUM ({values_sql});
    EXCEPTION
        WHEN duplicate_object THEN NULL;
    END $$;
    """
