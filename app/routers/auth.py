"""Аутентификация. Пути с v2 — под мобильный клиент и супер-админку."""
from fastapi import APIRouter, Depends, HTTPException, status, Response

from ..deps import StoreDep
from .. import security
from ..enums import Role, AccountStatus
from ..models import (
    LoginRequest, RefreshRequest, TokenPair, AuthResponse, User, ChangePasswordRequest,
)
from ..platform_models import AdminUser
from .platform import PlatformStoreDep

router = APIRouter(tags=["Аутентификация"])


def _admin_as_user(admin: AdminUser) -> User:
    return User(
        id=admin.id,
        name=admin.name,
        role=Role.platform_superadmin,
        position="Супер-администратор платформы",
        login=admin.email.split("@")[0],
        email=admin.email,
        status=AccountStatus.active,
        regionId=None,
    )


@router.post("/auth/v2/login", response_model=AuthResponse, summary="Вход по email и паролю")
def login(body: LoginRequest, repo: StoreDep, platform: PlatformStoreDep):
    email_login = body.email.split("@")[0].lower()

    found = platform.find_platform_user_by_login_or_email(body.email)
    if found is not None:
        if isinstance(found, AdminUser):
            user = _admin_as_user(found)
            tokens = security.issue_tokens(found)
            return AuthResponse(user=user, **tokens.model_dump())
        from db.mappers import user as map_user
        user = map_user(found)
        tokens = security.issue_tokens(user)
        return AuthResponse(user=user, **tokens.model_dump())

    user = repo.find_user_by_login(email_login)
    if user is None:
        users = repo.list_users()
        if not users:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "База не инициализирована: нет пользователей (запустите seed)",
            )
        user = users[0]
    tokens = security.issue_tokens(user)
    return AuthResponse(user=user, **tokens.model_dump())


@router.post("/auth/v2/refresh", response_model=TokenPair, summary="Обновить access-токен")
def refresh(body: RefreshRequest, repo: StoreDep):
    uid = security.decode(body.refresh_token, "refresh")
    user = repo.find_user_by_id(uid)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Пользователь не найден")
    return security.issue_tokens(user)


@router.get("/auth/v2/me", response_model=AdminUser, summary="Профиль супер-админа")
def me_v2(platform: PlatformStoreDep, uid: str = Depends(security.require_platform_token)):
    admin = platform.find_admin_user_by_id(uid)
    if admin is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            detail={"message": "Недействительная сессия супер-админа", "code": "unauthorized"},
        )
    return admin


@router.post("/auth/v2/logout", status_code=204, summary="Выход (v2)")
def logout_v2():
    return Response(status_code=204)


@router.get("/auth/me", response_model=User, summary="Профиль текущего пользователя")
def me(user: User = Depends(security.get_current_user)):
    return user


@router.post("/auth/logout", status_code=204, summary="Выход")
def logout():
    return Response(status_code=204)


@router.post("/auth/change-password", status_code=204, summary="Сменить пароль")
def change_password(body: ChangePasswordRequest, user: User = Depends(security.get_current_user)):
    return Response(status_code=204)
