"""Пользователи региона: список, создание (логин+временный пароль), блокировка/сброс пароля."""
from fastapi import APIRouter, Depends, HTTPException, status

from ..deps import StoreDep
from ..security import require_region_admin
from ..models import (
    User, CreateUserRequest, CreateUserResponse,
    UpdateUserRequest, UpdateUserResponse,
)
from ..enums import Role

router = APIRouter(tags=["Пользователи"])


@router.get("/users", response_model=list[User], summary="Список пользователей")
def list_users(repo: StoreDep, user: User = Depends(require_region_admin)):
    return repo.list_users()


@router.post("/users", response_model=CreateUserResponse, status_code=201, summary="Завести пользователя")
def create_user(body: CreateUserRequest, repo: StoreDep, actor: User = Depends(require_region_admin)):
    if body.role == Role.region_admin:
        raise HTTPException(403, "region_admin не заводится через этот метод")
    if body.role == Role.platform_superadmin:
        raise HTTPException(403, "platform_superadmin не заводится через этот метод")
    new, creds = repo.create_user(body)
    return CreateUserResponse(user=new, credentials=creds)


@router.patch("/users/{uid}", response_model=UpdateUserResponse, summary="Правка пользователя")
def update_user(uid: str, body: UpdateUserRequest, repo: StoreDep, actor: User = Depends(require_region_admin)):
    user, creds = repo.update_user(uid, body)
    if user is None:
        raise HTTPException(404, "Пользователь не найден")
    return UpdateUserResponse(user=user, credentials=creds)


@router.delete(
    "/users/{uid}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Удалить пользователя (только администратор района)",
)
def delete_user(uid: str, repo: StoreDep, actor: User = Depends(require_region_admin)):
    target = repo.find_user_by_id(uid)
    if target is None:
        raise HTTPException(
            404,
            detail={"message": "Пользователь не найден", "code": "not_found"},
        )
    if target.id == actor.id:
        raise HTTPException(
            403,
            detail={"message": "Нельзя удалить собственный аккаунт", "code": "forbidden"},
        )
    if target.role in (Role.region_admin, Role.platform_superadmin):
        raise HTTPException(
            403,
            detail={
                "message": "Нельзя удалить администратора",
                "code": "forbidden",
            },
        )
    deleted = repo.delete_user(uid)
    if deleted is None:
        raise HTTPException(
            404,
            detail={"message": "Пользователь не найден", "code": "not_found"},
        )
    return None
