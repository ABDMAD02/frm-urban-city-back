"""FastAPI-зависимость: in-memory или PostgreSQL."""
from __future__ import annotations

from collections.abc import Generator
from typing import Annotated, Union

from fastapi import Depends

from app import config
from app.storage.memory import MemoryStore
from db.base import SessionLocal, get_engine
from db.repository import DbStore
from db.seed import run_seed

Store = Union[MemoryStore, DbStore]

_memory = MemoryStore()


def use_database() -> bool:
    return config.use_database()


def get_store() -> Generator[Store, None, None]:
    if not use_database():
        yield _memory
        return

    get_engine()
    session = SessionLocal()
    repo = DbStore(session)
    try:
        yield repo
        repo.commit()
    except Exception:
        repo.rollback()
        raise
    finally:
        session.close()


StoreDep = Annotated[Store, Depends(get_store)]


def init_database() -> None:
    """Seed при старте. Миграции уже делает scripts/start.sh (один раз до gunicorn)."""
    if not use_database():
        return
    get_engine()
    with SessionLocal() as session:
        run_seed(session)
        session.commit()
