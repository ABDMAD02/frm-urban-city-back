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
    require_operator,
    require_region_admin,
)
from ..models import (
    Owner, CreateOwnerRequest, CreateOwnerResponse, District, DistrictCreate, Microdistrict,
    MicrodistrictCreate, ObjectTypeCreate, Photo, HistoryEvent, ObjectVersion, User,
    ChecklistTemplateItem, ChecklistTemplateManageRequest, Street, StreetCreate, StreetPatch,
    GeoConfig, GeoConfigPatch, CurrentCity, DesignCodeCatalogItem, ObjectTypeCatalogItem,
)
from ..enums import PhotoKind

router = APIRouter(tags=["Справочники"])


@router.get(
    "/design-code-catalog",
    response_model=list[DesignCodeCatalogItem],
    summary="Каталог пунктов дизайн-кода РК (глобальный)",
)
def list_design_code_catalog(user: User = Depends(get_current_user)):
    from app.store import DESIGN_CODE_CATALOG

    return [DesignCodeCatalogItem(**item) for item in DESIGN_CODE_CATALOG]


@router.get(
    "/object-type-catalog",
    response_model=list[ObjectTypeCatalogItem],
    summary="Каталог типовых типов объектов РК (глобальный)",
)
def list_object_type_catalog(user: User = Depends(get_current_user)):
    from app.store import OBJECT_TYPE_CATALOG

    return [ObjectTypeCatalogItem(**item) for item in OBJECT_TYPE_CATALOG]


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
    # Урбанист и админ района видят реестр бизнесов своего города (repo скоупит по региону).
    # Урбанисту это нужно для постановки объекта «в поле».
    if user.role.value not in ("region_admin", "urbanist"):
        raise HTTPException(403, detail={"message": "Доступно только сотруднику города", "code": "forbidden"})
    return repo.list_owners(owner_user_id=ownerUserId)


@router.get("/owners/my", response_model=list[Owner], summary="Мои бизнесы владельца")
def list_my_owners(repo: StoreDep, user: User = Depends(get_current_user)):
    if user.role.value != "owner":
        raise HTTPException(403, detail={"message": "Только для владельца", "code": "forbidden"})
    return repo.list_owners(owner_user_id=user.id)


@router.post("/owners", response_model=CreateOwnerResponse, status_code=201, summary="Создать собственника")
def create_owner(body: CreateOwnerRequest, repo: StoreDep, user: User = Depends(require_operator)):
    # Урбанист заводит бизнес «в поле» при постановке объекта; админ — в реестре.
    # Логин владельца обязателен и авто-создаётся (temp-пароль в credentials).
    owner, creds = repo.create_owner(body)
    return CreateOwnerResponse(owner=owner, credentials=creds)


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
def list_photos(
    repo: StoreDep,
    user: User = Depends(get_current_user),
    objectId: Optional[str] = Query(None),
    ids: Optional[str] = Query(None, description="Comma-separated photo ids"),
):
    from app.storage.object_store import resolve_readable_url

    allowed = accessible_object_ids(repo, user)
    items = repo.list_photos()
    id_filter = {x.strip() for x in (ids or "").split(",") if x.strip()} or None
    out: list[Photo] = []
    for p in items:
        # objectId may be missing on legacy rows — still return them for admin resolve
        if p.objectId is not None and p.objectId not in allowed:
            continue
        if objectId and p.objectId != objectId:
            continue
        if id_filter is not None and p.id not in id_filter:
            continue
        url = resolve_readable_url(p.url)
        out.append(p.model_copy(update={"url": url}) if url != p.url else p)
    return out


@router.get("/photos/{pid}", response_model=Photo, summary="Одно фото по id")
def get_photo(pid: str, repo: StoreDep, user: User = Depends(get_current_user)):
    from app.storage.object_store import resolve_readable_url

    photo = repo.find_photo(pid)
    if photo is None:
        raise HTTPException(404, detail={"message": "Фото не найдено", "code": "not_found"})
    allowed = accessible_object_ids(repo, user)
    if photo.objectId is not None and photo.objectId not in allowed:
        raise HTTPException(403, detail={"message": "Нет доступа к фото", "code": "forbidden"})
    url = resolve_readable_url(photo.url)
    return photo.model_copy(update={"url": url}) if url != photo.url else photo


@router.post("/photos", response_model=Photo, status_code=201, summary="Загрузить фото (файл)")
async def upload_photo(
    repo: StoreDep,
    file: UploadFile = File(...),
    kind: PhotoKind = Form(PhotoKind.general),
    caption: str = Form(""),
    objectId: str = Form(..., description="Код объекта (o1, …)"),
    id: Optional[str] = Form(
        None,
        description="Клиентский id (например ph-…). Если не передан — сервер выдаст pN",
    ),
    user: User = Depends(get_current_user),
):
    from app.storage.object_store import (
        R2NotConfiguredError,
        r2_configured,
        resolve_readable_url,
        upload_bytes,
    )

    if not objectId:
        raise HTTPException(400, detail={"message": "objectId обязателен", "code": "bad_request"})
    ensure_object_access(repo, user, objectId)
    if repo.find_object(objectId) is None:
        raise HTTPException(404, detail={"message": "Объект не найден", "code": "not_found"})

    data = await file.read()
    if not data:
        raise HTTPException(400, detail={"message": "Пустой файл", "code": "empty_file"})

    from app.storage.image_normalize import normalize_image_for_web

    try:
        data, upload_name, upload_ctype = normalize_image_for_web(
            data,
            filename=file.filename,
            content_type=file.content_type,
        )
    except ValueError as exc:
        raise HTTPException(400, detail={"message": str(exc), "code": "invalid_upload"}) from exc

    if r2_configured():
        try:
            url = upload_bytes(
                data,
                filename=upload_name,
                content_type=upload_ctype,
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
        url = f"/media/{upload_name or 'photo.bin'}"

    client_id = (id or "").strip()
    photo = Photo(
        id=client_id,
        objectId=objectId,
        kind=kind,
        caption=caption,
        url=url,
        date=config.today_str(),
        author=user.name,
    )
    saved = repo.add_photo_if_missing(photo, object_id=objectId)
    readable = resolve_readable_url(saved.url)
    return saved.model_copy(update={"url": readable}) if readable != saved.url else saved


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


@router.patch("/streets/{sid}", response_model=Street, summary="Изменить улицу")
def update_street(
    sid: str, body: StreetPatch, repo: StoreDep, user: User = Depends(require_region_admin)
):
    street = repo.update_street(sid, body)
    if street is None:
        raise HTTPException(404, detail={"message": "Улица не найдена", "code": "not_found"})
    return street


@router.delete(
    "/streets/{sid}",
    status_code=204,
    summary="Удалить улицу",
)
def delete_street(sid: str, repo: StoreDep, user: User = Depends(require_region_admin)):
    if not repo.delete_street(sid):
        raise HTTPException(404, detail={"message": "Улица не найдена", "code": "not_found"})
    return None


@router.get(
    "/cities/current",
    response_model=CurrentCity,
    summary="Текущий город пользователя (из JWT regionId)",
)
def get_current_city(repo: StoreDep, user: User = Depends(get_current_user)):
    return repo.get_current_city()


@router.get(
    "/cities/{city_id}/geo-config",
    response_model=GeoConfig,
    summary="Гео-конфиг города (схема адреса, флаги)",
)
def get_geo_config(city_id: str, repo: StoreDep, user: User = Depends(get_current_user)):
    return repo.get_geo_config(city_id)


@router.patch(
    "/cities/{city_id}/geo-config",
    response_model=GeoConfig,
    summary="Обновить гео-конфиг города",
)
def patch_geo_config(
    city_id: str,
    body: GeoConfigPatch,
    repo: StoreDep,
    user: User = Depends(require_region_admin),
):
    return repo.update_geo_config(city_id, body)
