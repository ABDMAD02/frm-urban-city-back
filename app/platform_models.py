"""Pydantic-схемы платформенного control-plane API (супер-админка)."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.enums import (
    AccountStatus,
    Locale,
    MapProvider,
    PlatformAuditAction,
    RegionStatus,
)
from app.models import (
    Credentials,
    District,
    DistrictCreate,
    DistrictPatch,
    GeoConfig,
    GeoConfigPatch,
    GeoImportRequest,
    GeoImportResponse,
    Microdistrict,
    MicrodistrictCreate,
    MicrodistrictPatch,
    Street,
    StreetCreate,
    StreetPatch,
)


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
    centerLat: float | None = None
    centerLng: float | None = None
    mapZoom: int | None = None


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


class GeoProvisionConfig(BaseModel):
    hasDistricts: bool = True
    hasMicrodistricts: bool = True
    hasStreets: bool = True
    addressSchema: str = "microdistrict,street,house"
    cityType: str | None = "city"
    oblast: str | None = None
    centerLat: float | None = None
    centerLng: float | None = None
    mapZoom: int | None = 12


class GeoProvision(BaseModel):
    source: Literal["catalog", "manual"] = "manual"
    cityCatalogId: str | None = None
    config: GeoProvisionConfig | None = None


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
    geo: GeoProvision | None = None


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


class GeoCatalogCitySummary(BaseModel):
    id: str
    name: str
    oblast: str | None = None
    districts: int = 0
    microdistricts: int = 0
    streets: int = 0


class GeoCatalogCityDetail(BaseModel):
    id: str
    name: str
    oblast: str | None = None
    config: GeoConfig
    districts: list[District] = Field(default_factory=list)
    microdistricts: list[Microdistrict] = Field(default_factory=list)
    streets: list[Street] = Field(default_factory=list)


class PlatformError(BaseModel):
    message: str
    code: str
