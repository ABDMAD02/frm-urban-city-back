"""Pydantic-схемы платформенного control-plane API (супер-админка)."""
from __future__ import annotations

from pydantic import BaseModel, Field

from app.enums import (
    AccountStatus,
    Locale,
    MapProvider,
    PlatformAuditAction,
    RegionStatus,
)
from app.models import Credentials


class Region(BaseModel):
    id: str
    code: str
    name: str
    status: RegionStatus
    timezone: str
    locale: Locale
    mapProvider: MapProvider
    createdAt: str
    cityType: str | None = None
    oblast: str | None = None
    hasDistricts: bool = True
    hasMicrodistricts: bool = True
    hasStreets: bool = True
    addressSchema: str = "microdistrict,street,house"


class AdminUser(BaseModel):
    id: str
    name: str
    email: str
    role: str = "platform_superadmin"


class RegionAdminAccount(BaseModel):
    id: str
    regionId: str
    name: str
    login: str
    role: str = "region_admin"
    status: AccountStatus
    createdAt: str


class AuditEvent(BaseModel):
    id: str
    regionId: str
    actor: str
    action: PlatformAuditAction
    detail: str
    at: str


class ProvisionRegionRequest(BaseModel):
    code: str = Field(min_length=2, max_length=32)
    name: str = Field(min_length=1)
    timezone: str = "Asia/Oral"
    locale: Locale = Locale.ru
    mapProvider: MapProvider = MapProvider.twogis
    adminName: str = Field(min_length=1)
    cityType: str | None = "city"
    oblast: str | None = None
    hasDistricts: bool = True
    hasMicrodistricts: bool = True
    hasStreets: bool = True
    addressSchema: str = "microdistrict,street,house"


class RegionStatusPatch(BaseModel):
    status: RegionStatus


class ReissueAdminRequest(BaseModel):
    name: str = Field(min_length=1)


class ProvisionRegionResponse(BaseModel):
    region: Region
    adminAccount: RegionAdminAccount
    credentials: Credentials


class ReissueAdminResponse(BaseModel):
    account: RegionAdminAccount
    credentials: Credentials


class PlatformError(BaseModel):
    message: str
    code: str
