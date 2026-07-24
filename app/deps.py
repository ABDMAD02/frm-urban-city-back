"""FastAPI-зависимость: in-memory или PostgreSQL."""
from __future__ import annotations

from collections.abc import Generator
from typing import Annotated, Optional, Union

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app import config
from app.enums import Role
from app.storage.memory import MemoryStore
from db.base import SessionLocal, get_engine
from db.repository import DbStore
from db.seed import run_seed

Store = Union[MemoryStore, DbStore]

_memory = MemoryStore()
_bearer = HTTPBearer(auto_error=False)


def use_database() -> bool:
    return config.use_database()


def get_store(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> Generator[Store, None, None]:
    if not use_database():
        yield _memory
        return

    get_engine()
    session = SessionLocal()
    repo = DbStore(session, region_id="uralsk")
    # Tenant scope from JWT when present
    if creds is not None:
        try:
            from app import security

            uid = security.decode(creds.credentials, "access")
            user = repo.find_user_by_id(uid)
            if user is not None:
                if user.role == Role.platform_superadmin:
                    repo.set_region(None)
                elif user.regionId:
                    repo.set_region(user.regionId)
        except Exception:
            pass
    try:
        yield repo
        repo.commit()
        return
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
