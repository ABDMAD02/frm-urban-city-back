"""Declarative Base, engine и фабрика сессий.

Строка подключения берётся из переменной окружения ``DATABASE_URL``.
Драйвер по умолчанию — psycopg (v3): ``postgresql+psycopg://...``.
"""
from __future__ import annotations

import os
from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

# Дефолт для локальной разработки; в проде задаётся через окружение/Railway.
DEFAULT_DATABASE_URL = "postgresql+psycopg://urban:urban@localhost:5432/urban_city"


def get_database_url() -> str:
    """URL БД из окружения с нормализацией legacy-схемы ``postgres://``."""
    url = os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)
    # Railway/Heroku отдают postgres:// — SQLAlchemy 2.0 требует явный драйвер.
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+psycopg://", 1)
    return url


class Base(DeclarativeBase):
    """Общий Declarative Base для всех ORM-моделей слоя БД."""


# Engine создаётся лениво: импорт драйвера (psycopg) откладывается до первого
# обращения к БД — так модуль импортируется даже без установленного драйвера
# (нужно для offline-инструментов и валидации схемы).
_engine: Engine | None = None


def get_engine() -> Engine:
    """Singleton-engine. echo включается переменной SQL_ECHO=1 для отладки."""
    global _engine
    if _engine is None:
        _engine = create_engine(
            get_database_url(),
            echo=os.getenv("SQL_ECHO", "") == "1",
            pool_pre_ping=True,  # переустанавливать «протухшие» соединения
            future=True,
        )
    return _engine


SessionLocal = sessionmaker(autoflush=False, expire_on_commit=False, class_=Session)


def get_session() -> Iterator[Session]:
    """FastAPI-зависимость: сессия на запрос с гарантированным закрытием."""
    session = SessionLocal(bind=get_engine())
    try:
        yield session
    finally:
        session.close()
