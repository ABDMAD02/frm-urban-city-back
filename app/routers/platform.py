"""Платформенный control-plane API (супер-админка)."""
from __future__ import annotations

from collections.abc import Generator
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app import security
from app.deps import use_database
from app.platform_models import (
    AdminUser,
    AuditEvent,
    Plan,
    ProvisionRegionRequest,
    ProvisionRegionResponse,
    Region,
    RegionAdminAccount,
    RegionStatusPatch,
    ReissueAdminRequest,
    ReissueAdminResponse,
    Subscription,
    SubscriptionPatch,
)
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
        # JWT sub may be regional user id
        raise HTTPException(
            status_code=403,
            detail={"message": "Недостаточно прав", "code": "forbidden_role"},
        )
    return admin


# Override HTTPException detail shape for platform — use exception handler via helpers
def _raise(status: int, message: str, code: str) -> None:
    raise HTTPException(status_code=status, detail={"message": message, "code": code})


@router.get("/platform/regions", response_model=list[Region])
def list_regions(store: PlatformStoreDep, _: AdminUser = Depends(require_platform_superadmin)):
    return store.list_regions()


@router.get("/platform/subscriptions", response_model=list[Subscription])
def list_subscriptions(store: PlatformStoreDep, _: AdminUser = Depends(require_platform_superadmin)):
    return store.list_subscriptions()


@router.get("/platform/admin-users", response_model=list[AdminUser])
def list_admin_users(store: PlatformStoreDep, _: AdminUser = Depends(require_platform_superadmin)):
    return store.list_admin_users()


@router.get("/platform/region-admin-accounts", response_model=list[RegionAdminAccount])
def list_region_admins(store: PlatformStoreDep, _: AdminUser = Depends(require_platform_superadmin)):
    return store.list_region_admin_accounts()


@router.get("/platform/plans", response_model=list[Plan])
def list_plans(store: PlatformStoreDep, _: AdminUser = Depends(require_platform_superadmin)):
    return store.list_plans()


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
        region, sub, account, creds = store.provision_region(body, actor=actor.email or actor.name)
    except LookupError as exc:
        if str(exc) == "region_exists":
            _raise(409, "Регион уже существует", "region_exists")
        _raise(404, str(exc), str(exc))
    except ValueError as exc:
        _raise(400, str(exc), "invalid_request")
    return ProvisionRegionResponse(
        region=region, subscription=sub, adminAccount=account, credentials=creds
    )


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


@router.patch("/platform/regions/{regionId}/subscription", response_model=Subscription)
def patch_subscription(
    regionId: str,
    body: SubscriptionPatch,
    store: PlatformStoreDep,
    actor: AdminUser = Depends(require_platform_superadmin),
):
    try:
        return store.patch_subscription(regionId, body, actor=actor.email or actor.name)
    except LookupError as exc:
        code = str(exc)
        _raise(404, code, code)
    except ValueError:
        _raise(400, "Некорректная дата validUntil", "invalid_date")


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
