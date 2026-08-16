"""JWT и извлечение текущего пользователя.

Все операционные ручки требуют валидный access JWT.
Без токена / битый токен / неизвестный user → 401.
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


def _unauthorized(message: str = "Требуется авторизация") -> None:
    raise HTTPException(
        status.HTTP_401_UNAUTHORIZED,
        detail={"message": message, "code": "unauthorized"},
    )


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
        _unauthorized("Недействительный токен")
    if payload.get("type") != expected:
        _unauthorized("Неверный тип токена")
    return payload["sub"]


def _authenticated_user(
    repo: StoreDep,
    creds: Optional[HTTPAuthorizationCredentials],
) -> User:
    """Загрузка пользователя по access JWT + проверка блокировки. БЕЗ гейта смены пароля."""
    if creds is None:
        _unauthorized()
    uid = decode(creds.credentials, "access")
    user = repo.find_user_by_id(uid)
    if user is None:
        _unauthorized("Недействительная сессия")
    if user.status is not None and user.status.value == "blocked":
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail={"message": "Аккаунт заблокирован", "code": "account_blocked"},
        )
    return user


def get_current_user_allow_password_change(
    repo: StoreDep,
    creds: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> User:
    """Как get_current_user, но БЕЗ force-change гейта.

    Только для /auth/change-password: пользователь с temp-паролём обязан иметь
    возможность его сменить, иначе — тупик (гейт блокирует смену, смена снимает гейт).
    """
    return _authenticated_user(repo, creds)


def get_current_user(
    repo: StoreDep,
    creds: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> User:
    """Обязательный access JWT. Без демо-подстановки.

    Пока `passwordChangeRequired` — доступ к операционным ручкам закрыт (403
    `password_change_required`): клиент обязан сначала сменить выданный temp-пароль.
    """
    user = _authenticated_user(repo, creds)
    if user.passwordChangeRequired:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail={
                "message": "Требуется смена временного пароля",
                "code": "password_change_required",
            },
        )
    return user


def require_platform_token(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> str:
    """Возвращает sub из access JWT; без токена — 401 (для /auth/v2/me)."""
    if creds is None:
        _unauthorized()
    return decode(creds.credentials, "access")


def require_region_admin(user: User = Depends(get_current_user)) -> User:
    """Только администратор района с валидным access JWT."""
    if user.role != Role.region_admin:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail={
                "message": "Действие доступно только администратору района",
                "code": "forbidden",
            },
        )
    return user


def require_operator(user: User = Depends(get_current_user)) -> User:
    """Контролирующая сторона: урбанист или админ района.

    Владелец (`owner`) — контролируемая сторона: он не создаёт объекты, не
    проводит проверки и не редактирует уведомления. Иначе нарушитель сам себе
    закрывает нарушение — контрольный процесс теряет смысл.
    """
    if user.role not in (Role.urbanist, Role.region_admin):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail={
                "message": "Действие доступно только сотруднику урбанистики или администратору",
                "code": "forbidden_role",
            },
        )
    return user


def owner_business_ids(repo: StoreDep, user: User) -> set[str]:
    """Все business Owner.id, привязанные к owner-аккаунту."""
    if user.role != Role.owner:
        return set()
    return {o.id for o in repo.list_owners(owner_user_id=user.id)}


def accessible_object_ids(repo: StoreDep, user: User) -> set[str]:
    """Object ids visible to current role.

    Правило скоупа урбаниста (ТЗ «Назначение на зоны», §3.1):
      1. O.assignedUrbanistId == U.id                       — явное переопределение (высший приоритет); ИЛИ
      2. O.assignedUrbanistId is None И (мкр O ∈ зоны-мкр U ИЛИ улица O ∈ зоны-улицы U).
    Следствия: чужой override скрывает объект из зоны; урбанист без зон и без явных
    объектов видит ПУСТОЙ скоуп (а не весь регион).
    """
    all_objects = repo.list_objects()
    if user.role == Role.owner:
        business_ids = owner_business_ids(repo, user)
        return {o.id for o in all_objects if o.ownerId in business_ids}
    if user.role == Role.urbanist:
        md = set(user.microdistrictIds or [])
        st = set(user.streetIds or [])
        result: set[str] = set()
        for o in all_objects:
            if o.assignedUrbanistId == user.id:
                result.add(o.id)
            elif o.assignedUrbanistId is None and (
                (o.microdistrictId is not None and o.microdistrictId in md)
                or (o.streetId is not None and o.streetId in st)
            ):
                result.add(o.id)
        return result
    return {o.id for o in all_objects}   # region_admin / platform_superadmin


def owner_object_ids(repo: StoreDep, user: User) -> set[str]:
    """Все object ids, доступные owner-аккаунту через его бизнесы."""
    if user.role != Role.owner:
        return set()
    return accessible_object_ids(repo, user)


def ensure_object_access(repo: StoreDep, user: User, object_id: str) -> None:
    """403 if current role tries to access object outside its server scope."""
    if user.role not in (Role.owner, Role.urbanist):
        return
    if object_id not in accessible_object_ids(repo, user):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail={"message": "Нет доступа к объекту", "code": "forbidden"},
        )


def ensure_owner_object_access(repo: StoreDep, user: User, object_id: str) -> None:
    """Backward-compatible wrapper for owner/field scopes."""
    ensure_object_access(repo, user, object_id)


def ensure_owner_business_access(repo: StoreDep, user: User, owner_id: str) -> None:
    """403 if owner tries to access чужой бизнес."""
    if user.role != Role.owner:
        return
    if owner_id not in owner_business_ids(repo, user):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail={"message": "Нет доступа к бизнесу", "code": "forbidden"},
        )


def user_to_admin(user: User) -> AdminUser | None:
    if user.role != Role.platform_superadmin:
        return None
    return AdminUser(
        id=user.id,
        name=user.name,
        email=user.email or f"{user.login or user.id}@platform.local",
        role="platform_superadmin",
    )
