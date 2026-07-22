"""Alembic environment.

URL БД берётся из окружения ``DATABASE_URL`` (через ``db.base.get_database_url``),
target_metadata — из ``db.base.Base`` (для автогенерации будущих ревизий).

Важно: URL передаём в ``create_engine`` напрямую, без ``config.set_main_option`` —
ConfigParser ломает пароли/`%` в connection string от DigitalOcean.
"""
from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

# Импорт слоя БД. prepend_sys_path=. в alembic.ini делает корень проекта видимым.
from db.base import Base, get_database_url
import db.models  # noqa: F401  — регистрирует все таблицы в Base.metadata

config = context.config

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
    connectable = create_engine(
        get_database_url(),
        poolclass=pool.NullPool,
        connect_args={"prepare_threshold": None},
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
