"""Объекты города: список (в скоупе роли), создание, правка карточки с FSM, поиск, геокодинг."""
from __future__ import annotations
from typing import Optional
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status

from ..deps import StoreDep
from ..security import accessible_object_ids, ensure_owner_business_access, ensure_object_access, get_current_user, require_operator, require_region_admin
from ..fsm import can_transition
from ..models import (
    BulkAssignObjectsRequest,
    BulkAssignObjectsResult,
    BulkDeleteObjectsRequest,
    BulkDeleteObjectsResult,
    CityObject,
    CoverageSummary,
    CoverageUrbanist,
    CreateObjectRequest,
    ObjectPatch,
    UpdateObjectRequest,
    User,
    GeocodeResult,
    SearchResult,
    ObjectImportResult,
)
from ..enums import Role, ObjectStatus

router = APIRouter(tags=["Объекты"])


def _validate_assignee(repo: StoreDep, actor: User, assigned_id: str | None) -> None:
    """Проверка назначаемого урбаниста (BR-5/6). assigned_id=None (снять override) — ок.

    Назначать вправе только region_admin; цель — урбанист того же региона.
    """
    if actor.role != Role.region_admin:
        raise HTTPException(
            403,
            detail={"message": "Назначать ответственного вправе только администратор района", "code": "forbidden"},
        )
    if assigned_id is None:
        return
    target = repo.find_user_by_id(assigned_id)
    if target is None:
        raise HTTPException(404, detail={"message": "Урбанист не найден", "code": "not_found"})
    if target.role != Role.urbanist:
        raise HTTPException(409, detail={"message": "Назначить можно только урбаниста", "code": "invalid_role"})
    if actor.regionId and target.regionId and target.regionId != actor.regionId:
        raise HTTPException(422, detail={"message": "Урбанист другого города", "code": "forbidden"})


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
def create_object(body: CreateObjectRequest, repo: StoreDep, user: User = Depends(require_operator)):
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


@router.post(
    "/objects/bulk-assign",
    response_model=BulkAssignObjectsResult,
    summary="Массово назначить ответственного (только администратор района)",
)
def bulk_assign_objects(
    body: BulkAssignObjectsRequest,
    repo: StoreDep,
    user: User = Depends(require_region_admin),
):
    """Идемпотентно: дубли/несуществующие/архивные id пропускаются."""
    _validate_assignee(repo, user, body.assignedUrbanistId)
    seen: set[str] = set()
    assigned = 0
    for oid in body.ids:
        if not oid or oid in seen:
            continue
        seen.add(oid)
        obj = repo.find_object(oid)
        if obj is None or obj.status == ObjectStatus.archived:
            continue
        patch = ObjectPatch(assignedUrbanistId=body.assignedUrbanistId)
        if repo.update_object(oid, patch, "Массовое назначение ответственного", user.name) is not None:
            assigned += 1
    return BulkAssignObjectsResult(assigned=assigned)


@router.get(
    "/objects/unassigned",
    response_model=list[CityObject],
    summary="Нераспределённые объекты (только администратор района)",
)
def list_unassigned_objects(repo: StoreDep, user: User = Depends(require_region_admin)):
    """BR-3: assignedUrbanistId IS NULL И мкр/улица вне всех зон урбанистов региона."""
    zone_md: set[str] = set()
    zone_st: set[str] = set()
    for u in repo.list_users():
        if u.role == Role.urbanist:
            zone_md.update(u.microdistrictIds or [])
            zone_st.update(u.streetIds or [])
    out = []
    for o in _active(repo.list_objects()):
        if o.assignedUrbanistId is not None:
            continue
        in_zone = (o.microdistrictId in zone_md) or (o.streetId in zone_st)
        if not in_zone:
            out.append(o)
    return out


@router.get(
    "/coverage/summary",
    response_model=CoverageSummary,
    summary="Покрытие: нагрузка урбанистов + нераспределённые (только администратор района)",
)
def coverage_summary(repo: StoreDep, user: User = Depends(require_region_admin)):
    """Проактивное удобство (§5.3): по каждому урбанисту — объекты в скоупе; отдельно unassigned."""
    urbanists = [u for u in repo.list_users() if u.role == Role.urbanist]
    zone_md: set[str] = set()
    zone_st: set[str] = set()
    for u in urbanists:
        zone_md.update(u.microdistrictIds or [])
        zone_st.update(u.streetIds or [])
    rows = [
        CoverageUrbanist(urbanistId=u.id, name=u.name, objects=len(accessible_object_ids(repo, u)))
        for u in urbanists
    ]
    unassigned = 0
    for o in _active(repo.list_objects()):
        if o.assignedUrbanistId is None and not (
            (o.microdistrictId in zone_md) or (o.streetId in zone_st)
        ):
            unassigned += 1
    return CoverageSummary(urbanists=rows, unassigned=unassigned)


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
    # Переопределение ответственного (override) вправе ставить только админ; цель — урбанист региона.
    if "assignedUrbanistId" in patch.model_fields_set:
        _validate_assignee(repo, user, patch.assignedUrbanistId)
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


@router.post("/objects/import-file", response_model=ObjectImportResult, summary="Массовый импорт объектов (CSV/GeoJSON)")
async def import_objects_file(
    repo: StoreDep,
    file: UploadFile = File(...),
    user: User = Depends(require_operator),
) -> ObjectImportResult:
    from ..services.object_import import parse_objects_file

    raw = (await file.read()).decode("utf-8", errors="replace")
    try:
        items = parse_objects_file(raw, file.filename or "")
    except ValueError as exc:
        raise HTTPException(422, detail={"message": str(exc), "code": "invalid_file"})
    return repo.import_objects(items, user)


@router.get("/geocode/reverse", response_model=GeocodeResult, summary="Адрес по координатам")
def reverse_geocode(
    repo: StoreDep,
    lat: float = Query(...),
    lng: float = Query(...),
    user: User = Depends(get_current_user),
):
    # Провайдер за флагом GEOCODER_PROVIDER (off|nominatim). Недоступен/выключен —
    # честный 503 (клиент глушит его в ручной режим), а НЕ фиктивный адрес.
    from ..services import geocoder

    try:
        data = geocoder.reverse(lat, lng)
    except geocoder.GeocoderUnavailable:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"message": "Обратный геокодер недоступен", "code": "geocoder_unavailable"},
        )
    # Имя улицы/мкр из геокодера → id справочника города (клиент проставит выпадашки).
    st_id, md_id, d_id = geocoder.match_ids(
        data.get("street"), data.get("microdistrict"),
        repo.list_streets(), repo.list_microdistricts(),
    )
    return GeocodeResult(
        address=data.get("address"),
        street=data.get("street"),
        house=data.get("house"),
        streetId=st_id,
        microdistrictId=md_id,
        districtId=d_id,
        confidence=data.get("confidence"),
    )
