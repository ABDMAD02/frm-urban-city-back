"""JWT и извлечение текущего пользователя.

Демо-упрощения (осознанно, как в прототипе):
- login принимает любой email/пароль и выдаёт токены под подходящего сид-пользователя;
- get_current_user НЕ обязателен: если токена нет (веб пока ходит по куке),
  подставляется демо-пользователь region_admin, чтобы чтения работали.
В проде: обязательная проверка токена, хэш паролей (bcrypt/argon2), реальный скоуп.
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from typing import Optional
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from . import config
from .deps import StoreDep
from .enums import Role
from .models import User, TokenPair
from .platform_models import AdminUser

_bearer = HTTPBearer(auto_error=False)


def _encode(sub: str, kind: str, ttl: timedelta) -> str:
    payload = {"sub": sub, "type": kind, "exp": datetime.now(timezone.utc) + ttl}
    return jwt.encode(payload, config.JWT_SECRET, algorithm=config.JWT_ALG)


def issue_tokens(user: User | AdminUser) -> TokenPair:
    access = _encode(user.id, "access", timedelta(minutes=config.ACCESS_TTL_MIN))
    refresh = _encode(user.id, "refresh", timedelta(days=config.REFRESH_TTL_DAYS))
    return TokenPair(access_token=access, refresh_token=refresh)


def decode(token: str, expected: str) -> str:
    try:
        payload = jwt.decode(token, config.JWT_SECRET, algorithms=[config.JWT_ALG])
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Недействительный токен")
    if payload.get("type") != expected:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Неверный тип токена")
    return payload["sub"]


def _demo_user(repo: StoreDep) -> User:
    admin = repo.find_region_admin()
    if admin is not None:
        return admin
    users = repo.list_users()
    if users:
        return users[0]
    raise HTTPException(
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "База не инициализирована: нет пользователей (запустите seed)",
    )


def get_current_user(
    repo: StoreDep,
    creds: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> User:
    if creds is None:
        return _demo_user(repo)
    uid = decode(creds.credentials, "access")
    user = repo.find_user_by_id(uid)
    if user is not None:
        return user
    return _demo_user(repo)


def require_platform_token(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> str:
    """Возвращает sub из access JWT; без токена — 401 (для /auth/v2/me)."""
    if creds is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            detail={"message": "Требуется авторизация", "code": "unauthorized"},
        )
    return decode(creds.credentials, "access")


def user_to_admin(user: User) -> AdminUser | None:
    if user.role != Role.platform_superadmin:
        return None
    return AdminUser(
        id=user.id,
        name=user.name,
        email=user.email or f"{user.login or user.id}@platform.local",
        role="platform_superadmin",
    )
