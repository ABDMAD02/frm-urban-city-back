"""Alembic environment.

URL БД берётся из окружения ``DATABASE_URL`` (через ``db.base.get_database_url``),
target_metadata — из ``db.base.Base`` (для автогенерации будущих ревизий).
"""
from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# Импорт слоя БД. prepend_sys_path=. в alembic.ini делает корень проекта видимым.
from db.base import Base, get_database_url
import db.models  # noqa: F401  — регистрирует все таблицы в Base.metadata

config = context.config
# Подставляем реальный URL из окружения (в alembic.ini его нет).
config.set_main_option("sqlalchemy.url", get_database_url())

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Генерация SQL без подключения к БД (alembic upgrade --sql)."""
    context.configure(
        url=get_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Применение миграций через живое подключение."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
