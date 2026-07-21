"""Слой БД Urban City (SQLAlchemy 2.0 ORM + Alembic).

Не связан с in-memory `app/store.py`: это параллельная реализация хранилища
на PostgreSQL. Переключение сервера на БД — см. `db/README.md`.
"""
from .base import Base, get_engine, SessionLocal, get_session, get_database_url

__all__ = ["Base", "get_engine", "SessionLocal", "get_session", "get_database_url"]
