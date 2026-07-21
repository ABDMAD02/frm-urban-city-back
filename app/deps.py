"""FastAPI-зависимость: in-memory или PostgreSQL."""
from __future__ import annotations

from collections.abc import Generator
from typing import Annotated, Union

from fastapi import Depends

from app import config
from app.storage.memory import MemoryStore
from db.base import SessionLocal
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
    """Миграции + seed при старте (вызывается из lifespan)."""
    if not use_database():
        return
    from alembic import command
    from alembic.config import Config
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    alembic_cfg = Config(str(root / "alembic.ini"))
    command.upgrade(alembic_cfg, "head")
    with SessionLocal() as session:
        run_seed(session)
        session.commit()
