"""Объекты города: список (в скоупе роли), создание, правка карточки с FSM, поиск, геокодинг."""
from __future__ import annotations
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status

from ..deps import StoreDep
from ..security import accessible_object_ids, ensure_owner_business_access, ensure_object_access, get_current_user, require_region_admin
from ..fsm import can_transition
from ..models import (
    BulkDeleteObjectsRequest,
    BulkDeleteObjectsResult,
    CityObject,
    CreateObjectRequest,
    UpdateObjectRequest,
    User,
    GeocodeResult,
    SearchResult,
)
from ..enums import Role, ObjectStatus

router = APIRouter(tags=["Объекты"])


def _scope(repo: StoreDep, objects: list[CityObject], user: User) -> list[CityObject]:
    if user.role in (Role.owner, Role.urbanist):
        ids = accessible_object_ids(repo, user)
        return [o for o in objects if o.id in ids]
    return objects


def _active(objects: list[CityObject]) -> list[CityObject]:
    return [o for o in objects if o.status != ObjectStatus.archived]


def _soft_delete_object(repo: StoreDep, oid: str, user: User) -> bool:
    """Soft-delete one object. False if missing/already archived."""
    obj = repo.find_object(oid)
    if obj is None or obj.status == ObjectStatus.archived:
        return False
    return repo.delete_object(oid, user) is not None


@router.get("/objects", response_model=list[CityObject], summary="Список объектов")
def list_objects(
    repo: StoreDep,
    user: User = Depends(get_current_user),
    status: Optional[ObjectStatus] = Query(None),
    type: Optional[str] = Query(None),
    ownerId: Optional[str] = Query(None),
    microdistrictId: Optional[str] = Query(None),
    q: Optional[str] = Query(None),
):
    items = _active(_scope(repo, repo.list_objects(), user))
    if ownerId:
        ensure_owner_business_access(repo, user, ownerId)
        items = [o for o in items if o.ownerId == ownerId]
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


# Static path must be registered before /objects/{oid} so it is not captured as oid.
@router.post(
    "/objects/bulk-delete",
    response_model=BulkDeleteObjectsResult,
    summary="Массовое удаление объектов (только администратор района)",
)
def bulk_delete_objects(
    body: BulkDeleteObjectsRequest,
    repo: StoreDep,
    user: User = Depends(require_region_admin),
):
    """Идемпотентно: несуществующие / уже archived id пропускаются."""
    seen: set[str] = set()
    deleted = 0
    for oid in body.ids:
        if not oid or oid in seen:
            continue
        seen.add(oid)
        if _soft_delete_object(repo, oid, user):
            deleted += 1
    return BulkDeleteObjectsResult(deleted=deleted)


@router.get("/objects/{oid}", response_model=CityObject, summary="Один объект")
def get_object(oid: str, repo: StoreDep, user: User = Depends(get_current_user)):
    obj = repo.find_object(oid)
    if obj is None or obj.status == ObjectStatus.archived:
        raise HTTPException(404, detail={"message": "Объект не найден", "code": "not_found"})
    ensure_object_access(repo, user, obj.id)
    return obj


@router.patch("/objects/{oid}", response_model=CityObject, summary="Правка карточки")
def update_object(oid: str, body: UpdateObjectRequest, repo: StoreDep, user: User = Depends(get_current_user)):
    obj = repo.find_object(oid)
    if obj is None or obj.status == ObjectStatus.archived:
        raise HTTPException(404, detail={"message": "Объект не найден", "code": "not_found"})
    ensure_object_access(repo, user, obj.id)
    patch = body.patch
    if patch.status is not None and not can_transition(obj.status, patch.status):
        raise HTTPException(
            409,
            detail={
                "message": f"Недопустимый переход статуса: {obj.status.value} → {patch.status.value}",
                "code": "conflict",
            },
        )
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
    """Мягкое удаление: status → archived (как bulk-delete)."""
    if not _soft_delete_object(repo, oid, user):
        raise HTTPException(404, detail={"message": "Объект не найден", "code": "not_found"})
    return None


@router.get("/search", response_model=SearchResult, summary="Глобальный поиск")
def search(repo: StoreDep, q: str = Query(...), user: User = Depends(get_current_user)):
    ql = q.lower()
    found = [
        o
        for o in _active(_scope(repo, repo.list_objects(), user))
        if ql in o.name.lower() or ql in o.address.lower() or ql in o.type.lower()
    ]
    return SearchResult(objects=found)


@router.get("/geocode/reverse", response_model=GeocodeResult, summary="Адрес по координатам")
def reverse_geocode(
    repo: StoreDep,
    lat: float = Query(...),
    lng: float = Query(...),
    user: User = Depends(get_current_user),
):
    try:
        md = repo.first_microdistrict()
    except LookupError as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"message": str(exc), "code": "service_unavailable"},
        ) from exc
    return GeocodeResult(address="—", street="—", districtId=md.districtId, microdistrictId=md.id)
