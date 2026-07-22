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

# Дефолт для локальной разработки; в проде задаётся через окружение.
DEFAULT_DATABASE_URL = "postgresql+psycopg://urban:urban@localhost:5432/urban_city"


def get_database_url() -> str:
    """URL БД из окружения с нормализацией схем DigitalOcean / Heroku / Railway."""
    url = (os.getenv("DATABASE_URL") or "").strip()
    if not url:
        url = DEFAULT_DATABASE_URL
    # Нерезолвленный шаблон DO App Platform — частая ошибка в env.
    if url.startswith("${") or "://" not in url:
        raise RuntimeError(
            f"DATABASE_URL is invalid ({url!r}). "
            "In DigitalOcean: bind Managed Postgres to the app, then set "
            "DATABASE_URL from the database connection string "
            "(or ${db.DATABASE_URL} only if the DB component is linked)."
        )
    # DO / Heroku отдают postgres:// или postgresql:// без драйвера.
    if url.startswith("postgres://"):
        url = "postgresql+psycopg://" + url[len("postgres://") :]
    elif url.startswith("postgresql://") and not url.startswith("postgresql+"):
        url = "postgresql+psycopg://" + url[len("postgresql://") :]
    return url


class Base(DeclarativeBase):
    """Общий Declarative Base для всех ORM-моделей слоя БД."""


_engine: Engine | None = None

SessionLocal = sessionmaker(autoflush=False, expire_on_commit=False, class_=Session)


def get_engine() -> Engine:
    """Singleton-engine. echo включается переменной SQL_ECHO=1 для отладки."""
    global _engine
    if _engine is None:
        _engine = create_engine(
            get_database_url(),
            echo=os.getenv("SQL_ECHO", "") == "1",
            pool_pre_ping=True,
            future=True,
        )
        SessionLocal.configure(bind=_engine)
    return _engine


def get_session() -> Iterator[Session]:
    """FastAPI-зависимость: сессия на запрос с гарантированным закрытием."""
    get_engine()
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
