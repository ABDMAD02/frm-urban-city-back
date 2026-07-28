"""Объекты города: список (в скоупе роли), создание, правка карточки с FSM, поиск, геокодинг."""
from __future__ import annotations
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status

from .. import config
from ..deps import StoreDep
from ..security import get_current_user, require_region_admin
from ..fsm import can_transition
from ..models import (
    CityObject, CreateObjectRequest, UpdateObjectRequest, User,
    GeocodeResult, SearchResult,
)
from ..enums import Role, ObjectStatus

router = APIRouter(tags=["Объекты"])


def _scope(objects: list[CityObject], user: User) -> list[CityObject]:
    if user.role == Role.owner:
        ids = set(user.ownerObjectIds or [])
        return [o for o in objects if o.id in ids]
    if user.role == Role.urbanist and user.microdistrictIds:
        mds = set(user.microdistrictIds)
        return [o for o in objects if o.microdistrictId in mds]
    return objects


def _active(objects: list[CityObject]) -> list[CityObject]:
    return [o for o in objects if o.status != ObjectStatus.archived]


@router.get("/objects", response_model=list[CityObject], summary="Список объектов")
def list_objects(
    repo: StoreDep,
    user: User = Depends(get_current_user),
    status: Optional[ObjectStatus] = Query(None),
    type: Optional[str] = Query(None),
    microdistrictId: Optional[str] = Query(None),
    q: Optional[str] = Query(None),
):
    items = _active(_scope(repo.list_objects(), user))
    if status:
        items = [o for o in items if o.status == status]
    if type:
        items = [o for o in items if o.type == type]
    if microdistrictId:
        items = [o for o in items if o.microdistrictId == microdistrictId]
    if q:
        ql = q.lower()
        items = [o for o in items if ql in o.name.lower() or ql in o.address.lower()]
    return items


@router.post("/objects", response_model=CityObject, status_code=201, summary="Создать объект")
def create_object(body: CreateObjectRequest, repo: StoreDep, user: User = Depends(get_current_user)):
    return repo.create_object(body, user)


@router.get("/objects/{oid}", response_model=CityObject, summary="Один объект")
def get_object(oid: str, repo: StoreDep, user: User = Depends(get_current_user)):
    obj = repo.find_object(oid)
    if obj is None or obj.status == ObjectStatus.archived:
        raise HTTPException(404, "Объект не найден")
    return obj


@router.patch("/objects/{oid}", response_model=CityObject, summary="Правка карточки")
def update_object(oid: str, body: UpdateObjectRequest, repo: StoreDep, user: User = Depends(get_current_user)):
    obj = repo.find_object(oid)
    if obj is None or obj.status == ObjectStatus.archived:
        raise HTTPException(404, "Объект не найден")
    patch = body.patch
    if patch.status is not None and not can_transition(obj.status, patch.status):
        raise HTTPException(409, f"Недопустимый переход статуса: {obj.status.value} → {patch.status.value}")
    updated = repo.update_object(oid, patch, body.note, user.name)
    return updated


@router.delete(
    "/objects/{oid}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Удалить объект (только администратор района)",
)
def delete_object(
    oid: str,
    repo: StoreDep,
    user: User = Depends(require_region_admin),
):
    """Мягкое удаление: status → archived (физический DELETE в БД запрещён триггером)."""
    obj = repo.find_object(oid)
    if obj is None or obj.status == ObjectStatus.archived:
        raise HTTPException(404, detail={"message": "Объект не найден", "code": "not_found"})
    deleted = repo.delete_object(oid, user)
    if deleted is None:
        raise HTTPException(404, detail={"message": "Объект не найден", "code": "not_found"})
    return None


@router.get("/search", response_model=SearchResult, summary="Глобальный поиск")
def search(repo: StoreDep, q: str = Query(...), user: User = Depends(get_current_user)):
    ql = q.lower()
    found = [
        o
        for o in _active(_scope(repo.list_objects(), user))
        if ql in o.name.lower() or ql in o.address.lower() or ql in o.type.lower()
    ]
    return SearchResult(objects=found)


@router.get("/geocode/reverse", response_model=GeocodeResult, summary="Адрес по координатам")
def reverse_geocode(repo: StoreDep, lat: float = Query(...), lng: float = Query(...)):
    try:
        md = repo.first_microdistrict()
    except LookupError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    return GeocodeResult(address="—", street="—", districtId=md.districtId, microdistrictId=md.id)
