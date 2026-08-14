"""Платформенный control-plane API (супер-админка)."""
from __future__ import annotations

from collections.abc import Generator
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app import security
from app.deps import use_database
from app.geo_import import GeoImportParseError, parse_geo_file
from app.models import (
    DistrictCreate,
    DistrictPatch,
    GeoConfigPatch,
    GeoImportRequest,
    GeoImportResponse,
    MicrodistrictCreate,
    MicrodistrictPatch,
    StreetCreate,
    StreetPatch,
)
from app.platform_models import (
    AdminUser,
    AuditEvent,
    GeoCatalogCityDetail,
    GeoCatalogCitySummary,
    ProvisionRegionRequest,
    ProvisionRegionResponse,
    Region,
    RegionAdminAccount,
    RegionStatusPatch,
    ReissueAdminRequest,
    ReissueAdminResponse,
)
from app.models import District, GeoConfig, Microdistrict, Street
from db.base import SessionLocal, get_engine
from db.platform_repository import PlatformStore
from app.storage import platform_memory

router = APIRouter(tags=["Платформа"])
_bearer = HTTPBearer(auto_error=False)


def _err(status: int, message: str, code: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"message": message, "code": code})


def get_platform_store() -> Generator[PlatformStore | platform_memory.MemoryPlatformStore, None, None]:
    if not use_database():
        yield platform_memory.STORE
        return
    get_engine()
    session = SessionLocal()
    store = PlatformStore(session)
    try:
        yield store
        store.commit()
    except Exception:
        store.rollback()
        raise
    finally:
        session.close()


PlatformStoreDep = Annotated[PlatformStore | platform_memory.MemoryPlatformStore, Depends(get_platform_store)]


def require_platform_superadmin(
    store: PlatformStoreDep,
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> AdminUser:
    if creds is None:
        raise HTTPException(status_code=401, detail={"message": "Требуется авторизация", "code": "unauthorized"})
    uid = security.decode(creds.credentials, "access")
    admin = store.find_admin_user_by_id(uid)
    if admin is None:
        raise HTTPException(
            status_code=403,
            detail={"message": "Недостаточно прав", "code": "forbidden_role"},
        )
    return admin


def _raise(status: int, message: str, code: str) -> None:
    raise HTTPException(status_code=status, detail={"message": message, "code": code})


def _lookup(exc: LookupError) -> None:
    key = str(exc)
    if key == "region_exists":
        _raise(409, "Регион уже существует", "region_exists")
    if key == "region_not_found":
        _raise(404, "Регион не найден", "region_not_found")
    if key == "catalog_not_found":
        _raise(404, "Город не найден в каталоге", "catalog_not_found")
    if key == "not_found":
        _raise(404, "Запись не найдена", "not_found")
    _raise(404, key, key)


def _value(exc: ValueError) -> None:
    key = str(exc)
    if key == "geo_incomplete":
        _raise(422, "География региона не заполнена", "geo_incomplete")
    if key == "in_use":
        _raise(409, "Нельзя удалить: есть зависимые записи", "in_use")
    if key == "invalid_status_transition":
        _raise(409, "Недопустимый переход статуса", "invalid_status_transition")
    if key == "not_provisioning":
        _raise(409, "Активация доступна только для региона в статусе provisioning", "not_provisioning")
    _raise(400, key, "invalid_request")


@router.get("/platform/regions", response_model=list[Region])
def list_regions(store: PlatformStoreDep, _: AdminUser = Depends(require_platform_superadmin)):
    return store.list_regions()


@router.get("/platform/regions/{regionId}", response_model=Region)
def get_region(regionId: str, store: PlatformStoreDep, _: AdminUser = Depends(require_platform_superadmin)):
    region = store.find_region(regionId)
    if region is None:
        _raise(404, "Регион не найден", "region_not_found")
    return region


@router.get("/platform/admin-users", response_model=list[AdminUser])
def list_admin_users(store: PlatformStoreDep, _: AdminUser = Depends(require_platform_superadmin)):
    return store.list_admin_users()


@router.get("/platform/region-admin-accounts", response_model=list[RegionAdminAccount])
def list_region_admins(store: PlatformStoreDep, _: AdminUser = Depends(require_platform_superadmin)):
    return store.list_region_admin_accounts()


@router.get("/platform/audit", response_model=list[AuditEvent])
def list_audit(
    store: PlatformStoreDep,
    _: AdminUser = Depends(require_platform_superadmin),
    regionId: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    cursor: str | None = Query(None),
):
    return store.list_audit(region_id=regionId, limit=limit, cursor=cursor)


@router.post("/platform/regions", response_model=ProvisionRegionResponse, status_code=201)
def provision_region(
    body: ProvisionRegionRequest,
    store: PlatformStoreDep,
    actor: AdminUser = Depends(require_platform_superadmin),
):
    try:
        region, account, creds = store.provision_region(body, actor=actor.email or actor.name)
    except LookupError as exc:
        _lookup(exc)
    except ValueError as exc:
        _value(exc)
    return ProvisionRegionResponse(region=region, adminAccount=account, credentials=creds)


@router.patch("/platform/regions/{regionId}/status", response_model=Region)
def patch_region_status(
    regionId: str,
    body: RegionStatusPatch,
    store: PlatformStoreDep,
    actor: AdminUser = Depends(require_platform_superadmin),
):
    try:
        return store.patch_region_status(regionId, body.status, actor=actor.email or actor.name)
    except LookupError:
        _raise(404, "Регион не найден", "region_not_found")
    except ValueError:
        _raise(409, "Недопустимый переход статуса", "invalid_status_transition")


@router.post("/platform/regions/{regionId}/activate", response_model=Region)
def activate_region(
    regionId: str,
    store: PlatformStoreDep,
    actor: AdminUser = Depends(require_platform_superadmin),
):
    try:
        return store.activate_region(regionId, actor=actor.email or actor.name)
    except LookupError:
        _raise(404, "Регион не найден", "region_not_found")
    except ValueError as exc:
        _value(exc)


@router.post("/platform/regions/{regionId}/admin-account", response_model=ReissueAdminResponse, status_code=201)
def reissue_admin(
    regionId: str,
    body: ReissueAdminRequest,
    store: PlatformStoreDep,
    actor: AdminUser = Depends(require_platform_superadmin),
):
    try:
        account, creds = store.reissue_admin(regionId, body, actor=actor.email or actor.name)
    except LookupError:
        _raise(404, "Регион не найден", "region_not_found")
    return ReissueAdminResponse(account=account, credentials=creds)


# ── Geo-config ────────────────────────────────────────────────────

@router.get("/platform/regions/{regionId}/geo-config", response_model=GeoConfig)
def get_geo_config(
    regionId: str, store: PlatformStoreDep, _: AdminUser = Depends(require_platform_superadmin)
):
    try:
        return store.get_region_geo_config(regionId)
    except LookupError:
        _raise(404, "Регион не найден", "region_not_found")


@router.patch("/platform/regions/{regionId}/geo-config", response_model=GeoConfig)
def patch_geo_config(
    regionId: str,
    body: GeoConfigPatch,
    store: PlatformStoreDep,
    _: AdminUser = Depends(require_platform_superadmin),
):
    try:
        return store.patch_region_geo_config(regionId, body)
    except LookupError:
        _raise(404, "Регион не найден", "region_not_found")


# ── Districts ───────────────────────────────────────────────────

@router.get("/platform/regions/{regionId}/districts", response_model=list[District])
def list_districts(
    regionId: str, store: PlatformStoreDep, _: AdminUser = Depends(require_platform_superadmin)
):
    try:
        return store.list_region_districts(regionId)
    except LookupError:
        _raise(404, "Регион не найден", "region_not_found")


@router.post("/platform/regions/{regionId}/districts", response_model=District, status_code=201)
def create_district(
    regionId: str,
    body: DistrictCreate,
    store: PlatformStoreDep,
    _: AdminUser = Depends(require_platform_superadmin),
):
    try:
        return store.create_region_district(regionId, body)
    except LookupError:
        _raise(404, "Регион не найден", "region_not_found")


@router.patch("/platform/regions/{regionId}/districts/{did}", response_model=District)
def update_district(
    regionId: str,
    did: str,
    body: DistrictPatch,
    store: PlatformStoreDep,
    _: AdminUser = Depends(require_platform_superadmin),
):
    try:
        return store.update_region_district(regionId, did, body)
    except LookupError as exc:
        _lookup(exc)


@router.delete("/platform/regions/{regionId}/districts/{did}", status_code=204)
def delete_district(
    regionId: str, did: str, store: PlatformStoreDep, _: AdminUser = Depends(require_platform_superadmin)
):
    try:
        store.delete_region_district(regionId, did)
    except LookupError as exc:
        _lookup(exc)
    except ValueError as exc:
        _value(exc)
    return None


# ── Microdistricts ──────────────────────────────────────────────

@router.get("/platform/regions/{regionId}/microdistricts", response_model=list[Microdistrict])
def list_microdistricts(
    regionId: str, store: PlatformStoreDep, _: AdminUser = Depends(require_platform_superadmin)
):
    try:
        return store.list_region_microdistricts(regionId)
    except LookupError:
        _raise(404, "Регион не найден", "region_not_found")


@router.post("/platform/regions/{regionId}/microdistricts", response_model=Microdistrict, status_code=201)
def create_microdistrict(
    regionId: str,
    body: MicrodistrictCreate,
    store: PlatformStoreDep,
    _: AdminUser = Depends(require_platform_superadmin),
):
    try:
        return store.create_region_microdistrict(regionId, body)
    except LookupError:
        _raise(404, "Регион не найден", "region_not_found")


@router.patch("/platform/regions/{regionId}/microdistricts/{mid}", response_model=Microdistrict)
def update_microdistrict(
    regionId: str,
    mid: str,
    body: MicrodistrictPatch,
    store: PlatformStoreDep,
    _: AdminUser = Depends(require_platform_superadmin),
):
    try:
        return store.update_region_microdistrict(regionId, mid, body)
    except LookupError as exc:
        _lookup(exc)


@router.delete("/platform/regions/{regionId}/microdistricts/{mid}", status_code=204)
def delete_microdistrict(
    regionId: str, mid: str, store: PlatformStoreDep, _: AdminUser = Depends(require_platform_superadmin)
):
    try:
        store.delete_region_microdistrict(regionId, mid)
    except LookupError as exc:
        _lookup(exc)
    except ValueError as exc:
        _value(exc)
    return None


# ── Streets ─────────────────────────────────────────────────────

@router.get("/platform/regions/{regionId}/streets", response_model=list[Street])
def list_streets(
    regionId: str, store: PlatformStoreDep, _: AdminUser = Depends(require_platform_superadmin)
):
    try:
        return store.list_region_streets(regionId)
    except LookupError:
        _raise(404, "Регион не найден", "region_not_found")


@router.post("/platform/regions/{regionId}/streets", response_model=Street, status_code=201)
def create_street(
    regionId: str,
    body: StreetCreate,
    store: PlatformStoreDep,
    _: AdminUser = Depends(require_platform_superadmin),
):
    try:
        return store.create_region_street(regionId, body)
    except LookupError:
        _raise(404, "Регион не найден", "region_not_found")


@router.patch("/platform/regions/{regionId}/streets/{sid}", response_model=Street)
def update_street(
    regionId: str,
    sid: str,
    body: StreetPatch,
    store: PlatformStoreDep,
    _: AdminUser = Depends(require_platform_superadmin),
):
    try:
        return store.update_region_street(regionId, sid, body)
    except LookupError as exc:
        _lookup(exc)


@router.delete("/platform/regions/{regionId}/streets/{sid}", status_code=204)
def delete_street(
    regionId: str, sid: str, store: PlatformStoreDep, _: AdminUser = Depends(require_platform_superadmin)
):
    try:
        store.delete_region_street(regionId, sid)
    except LookupError as exc:
        _lookup(exc)
    except ValueError as exc:
        _value(exc)
    return None


# ── Import + catalog ──────────────────────────────────────────────

@router.post("/platform/regions/{regionId}/geo/import", response_model=GeoImportResponse)
def import_geo(
    regionId: str,
    body: GeoImportRequest,
    store: PlatformStoreDep,
    _: AdminUser = Depends(require_platform_superadmin),
):
    try:
        return store.import_region_geo(regionId, body)
    except LookupError:
        _raise(404, "Регион не найден", "region_not_found")


# Импорт географии файлом — JSON (плоский/иерархический), CSV или TSV.
# Формат детектится по расширению/содержимому; можно переопределить полем format.
MAX_GEO_FILE_BYTES = 5 * 1024 * 1024


@router.post("/platform/regions/{regionId}/geo/import-file", response_model=GeoImportResponse)
async def import_geo_file(
    regionId: str,
    store: PlatformStoreDep,
    file: UploadFile = File(...),
    format: str | None = Form(default=None),
    _: AdminUser = Depends(require_platform_superadmin),
):
    content = await file.read()
    if not content:
        _raise(422, "Пустой файл", "empty_file")
    if len(content) > MAX_GEO_FILE_BYTES:
        _raise(413, "Файл слишком большой (макс. 5 МБ)", "file_too_large")
    try:
        body = parse_geo_file(file.filename or "", content, format)
    except GeoImportParseError as exc:
        _raise(422, str(exc), "geo_import_parse_error")
    try:
        return store.import_region_geo(regionId, body)
    except LookupError:
        _raise(404, "Регион не найден", "region_not_found")


@router.get("/platform/geo-catalog/cities", response_model=list[GeoCatalogCitySummary])
def list_geo_catalog_cities(
    store: PlatformStoreDep, _: AdminUser = Depends(require_platform_superadmin)
):
    return store.list_geo_catalog_cities()


@router.get("/platform/geo-catalog/cities/{cid}", response_model=GeoCatalogCityDetail)
def get_geo_catalog_city(
    cid: str, store: PlatformStoreDep, _: AdminUser = Depends(require_platform_superadmin)
):
    try:
        return store.get_geo_catalog_city(cid)
    except LookupError:
        _raise(404, "Город не найден в каталоге", "catalog_not_found")
