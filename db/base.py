"""Declarative Base, engine и фабрика сессий.

Строка подключения берётся из переменной окружения ``DATABASE_URL``.
Драйвер по умолчанию — psycopg (v3): ``postgresql+psycopg://...``.
"""
from __future__ import annotations

import logging
import os
from collections.abc import Iterator
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import NullPool, QueuePool

# Дефолт для локальной разработки; в проде задаётся через окружение.
DEFAULT_DATABASE_URL = "postgresql+psycopg://urban:urban@localhost:5432/urban_city"

logger = logging.getLogger(__name__)


def get_database_url() -> str:
    """URL БД из окружения с нормализацией схем DigitalOcean / Heroku / Railway.

    Без переписывания порта pooler — подходит для Alembic/миграций
    (Supabase Session mode на :5432).
    """
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


def _is_supabase_pooler(url: str) -> bool:
    try:
        host = (urlsplit(url).hostname or "").lower()
    except ValueError:
        return False
    return "pooler.supabase.com" in host or host.endswith(".supabase.com")


def _with_port(url: str, port: int) -> str:
    parts = urlsplit(url)
    host = parts.hostname or ""
    auth = ""
    if parts.username is not None:
        auth = parts.username
        if parts.password is not None:
            auth += f":{parts.password}"
        auth += "@"
    netloc = f"{auth}{host}:{port}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


def get_runtime_database_url() -> str:
    """URL для runtime API.

    Supabase Session pooler (:5432) ограничен ~15 клиентами и быстро
    падает под пачкой параллельных запросов фронта. По умолчанию
    переключаем runtime на Transaction pooler (:6543).

    DB_POOL_MODE:
      - auto (default): supabase pooler :5432 → :6543
      - transaction: force :6543 for supabase pooler
      - session: keep URL as-is (use small QueuePool)
    """
    url = get_database_url()
    mode = (os.getenv("DB_POOL_MODE") or "auto").strip().lower()
    if not _is_supabase_pooler(url):
        return url

    parts = urlsplit(url)
    port = parts.port
    if mode == "session":
        return url
    if mode in ("auto", "transaction") and (port is None or port == 5432):
        rewritten = _with_port(url, 6543)
        logger.warning(
            "Supabase session pooler (:5432) rewritten to transaction pooler (:6543) "
            "for runtime. Set DB_POOL_MODE=session to keep :5432."
        )
        return rewritten
    return url


def _pool_kwargs(url: str) -> dict:
    """Выбор пула под режим подключения."""
    mode = (os.getenv("DB_POOL_MODE") or "auto").strip().lower()
    parts = urlsplit(url)
    port = parts.port

    # Transaction mode (PgBouncer :6543): локальный пул не нужен.
    if port == 6543:
        return {"poolclass": NullPool}

    # Supabase Session mode: NullPool открывает клиента на каждый HTTP-запрос
    # и быстро упирается в EMAXCONNSESSION (pool_size≈15). Держим маленький
    # локальный пул без overflow.
    if _is_supabase_pooler(url) and mode == "session":
        pool_size = max(1, int(os.getenv("DB_POOL_SIZE", "3")))
        return {
            "poolclass": QueuePool,
            "pool_size": pool_size,
            "max_overflow": 0,
            "pool_timeout": int(os.getenv("DB_POOL_TIMEOUT", "30")),
            "pool_recycle": int(os.getenv("DB_POOL_RECYCLE", "280")),
        }

    # Прямой Postgres / прочие: как раньше — без локального пула.
    return {"poolclass": NullPool}


class Base(DeclarativeBase):
    """Общий Declarative Base для всех ORM-моделей слоя БД."""


_engine: Engine | None = None

SessionLocal = sessionmaker(autoflush=False, expire_on_commit=False, class_=Session)


def get_engine() -> Engine:
    """Singleton-engine. echo включается переменной SQL_ECHO=1 для отладки."""
    global _engine
    if _engine is None:
        url = get_runtime_database_url()
        # prepare_threshold=None — совместимость с PgBouncer/Supabase.
        _engine = create_engine(
            url,
            echo=os.getenv("SQL_ECHO", "") == "1",
            pool_pre_ping=True,
            future=True,
            connect_args={"prepare_threshold": None},
            **_pool_kwargs(url),
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
