"""Аутентификация. Пути с v2 — под мобильный клиент и супер-админку."""
from fastapi import APIRouter, Depends, HTTPException, status, Response

from ..deps import StoreDep
from .. import security
from ..enums import Role, AccountStatus
from ..models import (
    LoginRequest, RefreshRequest, TokenPair, AuthResponse, User, ChangePasswordRequest,
)
from ..platform_models import AdminUser
from ..passwords import verify_password, hash_password
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


def _unauthorized() -> None:
    raise HTTPException(
        status.HTTP_401_UNAUTHORIZED,
        detail={"message": "Неверный email или пароль", "code": "invalid_credentials"},
    )


@router.post("/auth/v2/login", response_model=AuthResponse, summary="Вход по email и паролю")
def login(body: LoginRequest, repo: StoreDep, platform: PlatformStoreDep):
    email = (body.email or "").strip()
    password = body.password or ""
    if not email or not password:
        _unauthorized()

    # 1) Platform superadmin
    admin, pwd_hash = platform.authenticate_lookup(email)
    if admin is not None:
        if not verify_password(password, pwd_hash):
            _unauthorized()
        tokens = security.issue_tokens(admin)
        return AuthResponse(user=_admin_as_user(admin), **tokens.model_dump())

    # 2) Regional / any app_user (including platform row via DbStore if present)
    user, pwd_hash = repo.authenticate_lookup(email)
    if user is None or not verify_password(password, pwd_hash):
        _unauthorized()
    if user.status == AccountStatus.blocked:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail={"message": "Аккаунт заблокирован", "code": "account_blocked"},
        )
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
def change_password(
    body: ChangePasswordRequest,
    repo: StoreDep,
    user: User = Depends(security.get_current_user),
):
    _, current_hash = repo.authenticate_lookup(user.login or user.email or user.id)
    if not verify_password(body.oldPassword, current_hash):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            detail={"message": "Неверный текущий пароль", "code": "invalid_credentials"},
        )
    if len(body.newPassword) < 8:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail={"message": "Пароль слишком короткий (мин. 8)", "code": "weak_password"},
        )
    ok = repo.set_password(user.id, body.newPassword)
    if not ok:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Пользователь не найден")
    return Response(status_code=204)
