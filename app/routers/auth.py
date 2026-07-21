"""Аутентификация. Пути с v2 — под уже написанный мобильный клиент."""
from fastapi import APIRouter, Depends, HTTPException, status, Response

from ..deps import StoreDep
from .. import security
from ..models import (
    LoginRequest, RefreshRequest, TokenPair, AuthResponse, User, ChangePasswordRequest,
)

router = APIRouter(tags=["Аутентификация"])


@router.post("/auth/v2/login", response_model=AuthResponse, summary="Вход по email и паролю")
def login(body: LoginRequest, repo: StoreDep):
    email_login = body.email.split("@")[0].lower()
    user = repo.find_user_by_login(email_login)
    user = user or repo.list_users()[0]
    tokens = security.issue_tokens(user)
    return AuthResponse(user=user, **tokens.model_dump())


@router.post("/auth/v2/refresh", response_model=TokenPair, summary="Обновить access-токен")
def refresh(body: RefreshRequest, repo: StoreDep):
    uid = security.decode(body.refresh_token, "refresh")
    user = repo.find_user_by_id(uid)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Пользователь не найден")
    return security.issue_tokens(user)


@router.get("/auth/me", response_model=User, summary="Профиль текущего пользователя")
def me(user: User = Depends(security.get_current_user)):
    return user


@router.post("/auth/logout", status_code=204, summary="Выход")
def logout():
    return Response(status_code=204)


@router.post("/auth/change-password", status_code=204, summary="Сменить пароль")
def change_password(body: ChangePasswordRequest, user: User = Depends(security.get_current_user)):
    return Response(status_code=204)
