"""Справочники (собственники, районы, микрорайоны, типы), фото, история, версии."""
from __future__ import annotations
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Query

from .. import config
from ..deps import StoreDep
from ..security import (
    accessible_object_ids,
    ensure_object_access,
    ensure_owner_business_access,
    get_current_user,
    require_region_admin,
)
from ..models import (
    Owner, CreateOwnerRequest, District, DistrictCreate, Microdistrict,
    MicrodistrictCreate, ObjectTypeCreate, Photo, HistoryEvent, ObjectVersion, User,
    ChecklistTemplateItem, ChecklistTemplateManageRequest, Street, StreetCreate, GeoConfig,
)
from ..enums import PhotoKind

router = APIRouter(tags=["Справочники"])


@router.get("/owners", response_model=list[Owner], summary="Собственники")
def list_owners(
    repo: StoreDep,
    user: User = Depends(get_current_user),
    ownerUserId: Optional[str] = Query(None, description="Фильтр по аккаунту-владельцу"),
):
    if user.role.value == "owner":
        if ownerUserId and ownerUserId != user.id:
            raise HTTPException(403, detail={"message": "Нет доступа к чужим бизнесам", "code": "forbidden"})
        return repo.list_owners(owner_user_id=user.id)
    if user.role.value != "region_admin":
        raise HTTPException(403, detail={"message": "Доступно только администратору района", "code": "forbidden"})
    return repo.list_owners(owner_user_id=ownerUserId)


@router.get("/owners/my", response_model=list[Owner], summary="Мои бизнесы владельца")
def list_my_owners(repo: StoreDep, user: User = Depends(get_current_user)):
    if user.role.value != "owner":
        raise HTTPException(403, detail={"message": "Только для владельца", "code": "forbidden"})
    return repo.list_owners(owner_user_id=user.id)


@router.post("/owners", response_model=Owner, status_code=201, summary="Создать собственника")
def create_owner(body: CreateOwnerRequest, repo: StoreDep, user: User = Depends(require_region_admin)):
    return repo.create_owner(body)


@router.patch("/owners/{wid}", response_model=Owner, summary="Правка собственника")
def update_owner(wid: str, body: CreateOwnerRequest, repo: StoreDep, user: User = Depends(require_region_admin)):
    owner = repo.update_owner(wid, body)
    if owner is None:
        raise HTTPException(404, "Собственник не найден")
    return owner


@router.get("/districts", response_model=list[District], summary="Районы")
def list_districts(repo: StoreDep, user: User = Depends(get_current_user)):
    return repo.list_districts()


@router.post("/districts/manage", response_model=District, status_code=201, summary="Создать район")
def create_district(body: DistrictCreate, repo: StoreDep, user: User = Depends(require_region_admin)):
    return repo.create_district(body)


@router.get("/microdistricts", response_model=list[Microdistrict], summary="Микрорайоны")
def list_microdistricts(repo: StoreDep, user: User = Depends(get_current_user)):
    return repo.list_microdistricts()


@router.post("/microdistricts/manage", response_model=Microdistrict, status_code=201, summary="Создать микрорайон")
def create_microdistrict(body: MicrodistrictCreate, repo: StoreDep, user: User = Depends(require_region_admin)):
    return repo.create_microdistrict(body)


@router.get("/object-types", response_model=list[str], summary="Типы объектов")
def list_object_types(repo: StoreDep, user: User = Depends(get_current_user)):
    return repo.list_object_types()


@router.post("/object-types/manage", response_model=list[str], status_code=201, summary="Добавить тип объекта")
def add_object_type(body: ObjectTypeCreate, repo: StoreDep, user: User = Depends(require_region_admin)):
    return repo.add_object_type(body.type)


@router.get("/photos", response_model=list[Photo], summary="Метаданные фото")
def list_photos(repo: StoreDep, user: User = Depends(get_current_user)):
    allowed = accessible_object_ids(repo, user)
    items = repo.list_photos()
    return [p for p in items if p.objectId in allowed]


@router.post("/photos", response_model=Photo, status_code=201, summary="Загрузить фото (файл)")
async def upload_photo(
    repo: StoreDep,
    file: UploadFile = File(...),
    kind: PhotoKind = Form(PhotoKind.general),
    caption: str = Form(""),
    objectId: Optional[str] = Form(None),
    user: User = Depends(get_current_user),
):
    from app.storage.object_store import R2NotConfiguredError, r2_configured, upload_bytes

    if objectId:
        ensure_object_access(repo, user, objectId)

    data = await file.read()
    if not data:
        raise HTTPException(400, detail={"message": "Пустой файл", "code": "empty_file"})

    if r2_configured():
        try:
            url = upload_bytes(
                data,
                filename=file.filename,
                content_type=file.content_type,
                object_id=objectId,
            )
        except ValueError as exc:
            raise HTTPException(400, detail={"message": str(exc), "code": "invalid_upload"}) from exc
        except R2NotConfiguredError as exc:
            raise HTTPException(503, detail={"message": str(exc), "code": "storage_unavailable"}) from exc
        except Exception as exc:
            raise HTTPException(
                502,
                detail={"message": f"R2 upload failed: {exc}", "code": "storage_upload_failed"},
            ) from exc
    elif config.ENV == "production":
        raise HTTPException(
            503,
            detail={"message": "R2 storage is not configured", "code": "storage_unavailable"},
        )
    else:
        # Local/dev fallback without R2 credentials.
        url = f"/media/{file.filename or 'photo.bin'}"

    photo = Photo(
        id="",
        objectId=objectId,
        kind=kind,
        caption=caption,
        url=url,
        date=config.today_str(),
        author=user.name,
    )
    return repo.add_photo_if_missing(photo, object_id=objectId)


@router.get("/history", response_model=list[HistoryEvent], summary="Лента событий")
def list_history(repo: StoreDep, user: User = Depends(get_current_user)):
    allowed = accessible_object_ids(repo, user)
    items = repo.list_history()
    return [h for h in items if h.objectId in allowed]


@router.get("/versions", response_model=list[ObjectVersion], summary="Версии карточек")
def list_versions(repo: StoreDep, user: User = Depends(get_current_user)):
    allowed = accessible_object_ids(repo, user)
    return [v for v in repo.list_versions() if v.objectId in allowed]


@router.get(
    "/checklist-template",
    response_model=list[ChecklistTemplateItem],
    summary="Шаблон чеклиста дизайн-кода (видимые пункты)",
)
def list_checklist_template(repo: StoreDep, user: User = Depends(get_current_user)):
    return repo.list_checklist_template(visible_only=True)


@router.post(
    "/checklist-template/manage",
    response_model=list[ChecklistTemplateItem],
    summary="Управление шаблоном чеклиста (upsert / hide / reorder)",
)
def manage_checklist_template(
    body: ChecklistTemplateManageRequest,
    repo: StoreDep,
    user: User = Depends(require_region_admin),
):
    return repo.manage_checklist_template(body.items)


@router.get("/streets", response_model=list[Street], summary="Улицы региона")
def list_streets(repo: StoreDep, user: User = Depends(get_current_user)):
    return repo.list_streets()


@router.post("/streets", response_model=Street, status_code=201, summary="Создать улицу")
def create_street(
    body: StreetCreate, repo: StoreDep, user: User = Depends(require_region_admin)
):
    return repo.create_street(body)


@router.get(
    "/cities/{city_id}/geo-config",
    response_model=GeoConfig,
    summary="Гео-конфиг города (схема адреса, флаги)",
)
def get_geo_config(city_id: str, repo: StoreDep, user: User = Depends(get_current_user)):
    return repo.get_geo_config(city_id)
