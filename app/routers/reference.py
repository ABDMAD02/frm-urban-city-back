"""Справочники (собственники, районы, микрорайоны, типы), фото, история, версии."""
from __future__ import annotations
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form

from .. import config
from ..deps import StoreDep
from ..security import get_current_user
from ..models import (
    Owner, CreateOwnerRequest, District, DistrictCreate, Microdistrict,
    MicrodistrictCreate, ObjectTypeCreate, Photo, HistoryEvent, ObjectVersion, User,
)
from ..enums import PhotoKind

router = APIRouter(tags=["Справочники"])


@router.get("/owners", response_model=list[Owner], summary="Собственники")
def list_owners(repo: StoreDep, user: User = Depends(get_current_user)):
    return repo.list_owners()


@router.post("/owners", response_model=Owner, status_code=201, summary="Создать собственника")
def create_owner(body: CreateOwnerRequest, repo: StoreDep, user: User = Depends(get_current_user)):
    return repo.create_owner(body)


@router.patch("/owners/{wid}", response_model=Owner, summary="Правка собственника")
def update_owner(wid: str, body: CreateOwnerRequest, repo: StoreDep, user: User = Depends(get_current_user)):
    owner = repo.update_owner(wid, body)
    if owner is None:
        raise HTTPException(404, "Собственник не найден")
    return owner


@router.get("/districts", response_model=list[District], summary="Районы")
def list_districts(repo: StoreDep, user: User = Depends(get_current_user)):
    return repo.list_districts()


@router.post("/districts/manage", response_model=District, status_code=201, summary="Создать район")
def create_district(body: DistrictCreate, repo: StoreDep, user: User = Depends(get_current_user)):
    return repo.create_district(body)


@router.get("/microdistricts", response_model=list[Microdistrict], summary="Микрорайоны")
def list_microdistricts(repo: StoreDep, user: User = Depends(get_current_user)):
    return repo.list_microdistricts()


@router.post("/microdistricts/manage", response_model=Microdistrict, status_code=201, summary="Создать микрорайон")
def create_microdistrict(body: MicrodistrictCreate, repo: StoreDep, user: User = Depends(get_current_user)):
    return repo.create_microdistrict(body)


@router.get("/object-types", response_model=list[str], summary="Типы объектов")
def list_object_types(repo: StoreDep, user: User = Depends(get_current_user)):
    return repo.list_object_types()


@router.post("/object-types/manage", response_model=list[str], status_code=201, summary="Добавить тип объекта")
def add_object_type(body: ObjectTypeCreate, repo: StoreDep, user: User = Depends(get_current_user)):
    return repo.add_object_type(body.type)


@router.get("/photos", response_model=list[Photo], summary="Метаданные фото")
def list_photos(repo: StoreDep, user: User = Depends(get_current_user)):
    return repo.list_photos()


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
        kind=kind,
        caption=caption,
        url=url,
        date=config.DEMO_TODAY,
        author=user.name,
    )
    return repo.add_photo_if_missing(photo, object_id=objectId)


@router.get("/history", response_model=list[HistoryEvent], summary="Лента событий")
def list_history(repo: StoreDep, user: User = Depends(get_current_user)):
    return repo.list_history()


@router.get("/versions", response_model=list[ObjectVersion], summary="Версии карточек")
def list_versions(repo: StoreDep, user: User = Depends(get_current_user)):
    return repo.list_versions()
