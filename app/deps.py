"""FastAPI-зависимость: in-memory или PostgreSQL."""
from __future__ import annotations

import logging
from collections.abc import Generator
from typing import Annotated, Optional, Union

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import text

from app import config
from app.enums import Role
from app.storage.memory import MemoryStore
from db.base import SessionLocal, get_engine
from db.repository import DbStore

Store = Union[MemoryStore, DbStore]

logger = logging.getLogger(__name__)

_memory = MemoryStore()
_bearer = HTTPBearer(auto_error=False)


def use_database() -> bool:
    return config.use_database()


def get_store(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> Generator[Store, None, None]:
    if not use_database():
        # Tenant scope from JWT (same as DB path) so new cities see empty geo.
        if creds is not None:
            try:
                from app import security

                uid = security.decode(creds.credentials, "access")
                _memory.set_region(None)
                user = _memory.find_user_by_id(uid)
                if user is not None:
                    if user.role == Role.platform_superadmin:
                        _memory.set_region(None)
                    elif user.regionId:
                        _memory.set_region(user.regionId)
                    # no regionId and not superadmin → leave region=None (empty scope)
                else:
                    # Valid JWT but user not found → don't leak cross-tenant data.
                    # The route's get_current_user will raise 401 on find_user_by_id.
                    _memory.set_region(None)
            except Exception as exc:
                logger.warning(
                    "JWT resolve failed (memory store): %s: %s",
                    type(exc).__name__,
                    exc,
                )
                _memory.set_region(None)
        else:
            _memory.set_region("uralsk")
        yield _memory
        return

    get_engine()
    session = SessionLocal()
    repo = DbStore(session, region_id=None)
    # Tenant scope from JWT when present
    if creds is not None:
        try:
            from app import security

            uid = security.decode(creds.credentials, "access")
            # Lookup without region filter (multi-tenant login), then scope.
            repo.set_region(None)
            user = repo.find_user_by_id(uid)
            if user is not None:
                if user.role == Role.platform_superadmin:
                    repo.set_region(None)
                elif user.regionId:
                    repo.set_region(user.regionId)
                # no regionId and not superadmin → leave region=None (empty scope)
            # unknown user → region stays None; route raises 401 via find_user_by_id
        except Exception as exc:
            logger.warning(
                "JWT resolve failed (db store): %s: %s",
                type(exc).__name__,
                exc,
            )
            repo.set_region(None)
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
    """Проверка соединения с БД при старте воркера.

    Миграции / bootstrap / demo-seed делает только ``scripts/start.sh`` до gunicorn,
    иначе каждый worker повторно заливает демо-данные.
    """
    if not use_database():
        return
    get_engine()
    with SessionLocal() as session:
        session.execute(text("SELECT 1"))
        session.commit()
