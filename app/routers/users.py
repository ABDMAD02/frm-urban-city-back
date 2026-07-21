"""Пользователи региона: список, создание (логин+временный пароль), блокировка/сброс пароля."""
from fastapi import APIRouter, Depends, HTTPException

from ..deps import StoreDep
from ..security import get_current_user
from ..models import (
    User, CreateUserRequest, CreateUserResponse,
    UpdateUserRequest, UpdateUserResponse,
)
from ..enums import Role

router = APIRouter(tags=["Пользователи"])


@router.get("/users", response_model=list[User], summary="Список пользователей")
def list_users(repo: StoreDep, user: User = Depends(get_current_user)):
    return repo.list_users()


@router.post("/users", response_model=CreateUserResponse, status_code=201, summary="Завести пользователя")
def create_user(body: CreateUserRequest, repo: StoreDep, actor: User = Depends(get_current_user)):
    if body.role == Role.region_admin:
        raise HTTPException(403, "region_admin не заводится через этот метод")
    new, creds = repo.create_user(body)
    return CreateUserResponse(user=new, credentials=creds)


@router.patch("/users/{uid}", response_model=UpdateUserResponse, summary="Правка пользователя")
def update_user(uid: str, body: UpdateUserRequest, repo: StoreDep, actor: User = Depends(get_current_user)):
    user, creds = repo.update_user(uid, body)
    if user is None:
        raise HTTPException(404, "Пользователь не найден")
    return UpdateUserResponse(user=user, credentials=creds)
