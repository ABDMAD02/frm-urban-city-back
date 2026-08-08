"""Pydantic-схемы — зеркало доменных сущностей фронта + тела запросов/ответов API."""
from __future__ import annotations
import re
from pydantic import BaseModel, Field, EmailStr, field_validator
from .enums import (
    Role, AccountStatus, ObjectStatus, InspectionResult, ReinspectionResult,
    PrescriptionStatus, LegalForm, ChecklistValue, PhotoKind, HistoryType,
)


# ── Справочники географии ─────────────────────────────────────────
class District(BaseModel):
    id: str
    name: str


class Microdistrict(BaseModel):
    id: str
    districtId: str | None = None
    name: str


# ── Пользователи и собственники ───────────────────────────────────
class User(BaseModel):
    id: str
    name: str
    role: Role
    position: str
    microdistrictIds: list[str] | None = None
    streetIds: list[str] | None = None        # зоны-улицы урбаниста
    ownerObjectIds: list[str] | None = None
    login: str | None = None
    status: AccountStatus | None = None
    createdAt: str | None = None
    regionId: str | None = None
    email: str | None = None


class Owner(BaseModel):
    id: str
    name: str
    legalForm: LegalForm
    bin: str | None = None
    phone: str
    email: str | None = None
    ownerUserId: str | None = None


# ── Фото / чек-лист / проверки / предписания ──────────────────────
class Photo(BaseModel):
    id: str
    objectId: str | None = None
    kind: PhotoKind
    caption: str
    color: str = ""          # плейсхолдер прототипа
    url: str | None = None   # реальный файл (прод)
    date: str
    author: str


class ChecklistItem(BaseModel):
    key: str
    label: str
    value: ChecklistValue
    comment: str | None = None


class Inspection(BaseModel):
    id: str
    objectId: str
    inspector: str
    inspectorId: str | None = None   # код сотрудника, проводившего проверку
    date: str
    result: InspectionResult
    checklist: list[ChecklistItem] = []
    comment: str | None = None
    photoIds: list[str] = []


class Prescription(BaseModel):
    id: str
    objectId: str
    inspectionId: str
    title: str
    description: str
    issuedAt: str
    deadline: str
    reinspectionDate: str
    status: PrescriptionStatus


class HistoryEvent(BaseModel):
    id: str
    objectId: str
    type: HistoryType
    actor: str
    date: str
    text: str


class ObjectVersion(BaseModel):
    id: str
    objectId: str
    date: str
    author: str
    label: str
    changes: list[str] = []


class CityObject(BaseModel):
    id: str
    name: str
    type: str
    category: str
    address: str
    lat: float
    lng: float
    districtId: str | None = None
    microdistrictId: str | None = None
    street: str | None = None
    streetId: str | None = None
    house: str | None = None
    apartment: str | None = None
    ownerId: str
    status: ObjectStatus
    responsible: str
    assignedUrbanistId: str | None = None      # явное переопределение ответственного (override)
    assignedUrbanistName: str | None = None    # денорм. имя для отображения (собирает сервер)
    createdAt: str
    updatedAt: str


# ── Аутентификация ────────────────────────────────────────────────
class LoginRequest(BaseModel):
    email: str
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "Bearer"


class AuthResponse(TokenPair):
    user: User


class ChangePasswordRequest(BaseModel):
    oldPassword: str
    newPassword: str


# ── Объекты ───────────────────────────────────────────────────────
class CreateObjectRequest(BaseModel):
    name: str
    type: str
    lat: float
    lng: float
    category: str | None = None
    address: str | None = None
    districtId: str | None = None
    microdistrictId: str | None = None
    street: str | None = None
    streetId: str | None = None
    house: str | None = None
    apartment: str | None = None
    ownerId: str | None = None


class BulkDeleteObjectsRequest(BaseModel):
    ids: list[str] = Field(default_factory=list)


class BulkDeleteObjectsResult(BaseModel):
    deleted: int


class BulkAssignObjectsRequest(BaseModel):
    ids: list[str] = Field(default_factory=list)
    assignedUrbanistId: str | None = None   # null = снять override со всех выбранных


class BulkAssignObjectsResult(BaseModel):
    assigned: int


class ObjectPatch(BaseModel):
    name: str | None = None
    type: str | None = None
    category: str | None = None
    address: str | None = None
    ownerId: str | None = None
    responsible: str | None = None
    status: ObjectStatus | None = None
    districtId: str | None = None
    microdistrictId: str | None = None
    street: str | None = None
    streetId: str | None = None
    house: str | None = None
    apartment: str | None = None
    assignedUrbanistId: str | None = None   # null = снять override (вернуть в зону)


class UpdateObjectRequest(BaseModel):
    patch: ObjectPatch
    note: str | None = None


# ── Проверки ──────────────────────────────────────────────────────
class CreateInspectionRequest(BaseModel):
    inspection: Inspection
    status: ObjectStatus
    note: str | None = None
    photos: list[Photo] = Field(default_factory=list)


class InspectionResultView(BaseModel):
    object: CityObject
    inspection: Inspection
    prescription: Prescription | None = None


class ReinspectionRequest(BaseModel):
    result: ReinspectionResult


# ── Пользователи / собственники — тела ────────────────────────────
class CreateUserRequest(BaseModel):
    name: str
    role: Role  # ожидается urbanist|owner
    position: str
    microdistrictIds: list[str] | None = None
    streetIds: list[str] | None = None
    # Для role=owner: id карточки собственника. Если не передан — создаётся автоматически.
    ownerId: str | None = None


class Credentials(BaseModel):
    login: str
    tempPassword: str


class CreateUserResponse(BaseModel):
    user: User
    credentials: Credentials


class UpdateUserRequest(BaseModel):
    status: AccountStatus | None = None
    resetPassword: bool | None = None
    microdistrictIds: list[str] | None = None
    streetIds: list[str] | None = None


class UpdateUserResponse(BaseModel):
    user: User
    credentials: Credentials | None = None


class CreateOwnerRequest(BaseModel):
    name: str
    legalForm: LegalForm
    phone: str
    bin: str | None = None
    email: str | None = None
    ownerUserId: str | None = None

    @field_validator("bin", mode="before")
    @classmethod
    def normalize_bin(cls, value: object) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            return None
        if not re.fullmatch(r"[0-9]{12}", text):
            raise ValueError("БИН/ИИН должен состоять из 12 цифр")
        return text

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, value: object) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            return None
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", text, flags=re.IGNORECASE):
            raise ValueError("Некорректный email")
        return text


# ── Предписания — действия ────────────────────────────────────────
class PrescriptionPatch(BaseModel):
    status: PrescriptionStatus | None = None
    deadline: str | None = None
    reinspectionDate: str | None = None


class SendPrescriptionRequest(BaseModel):
    email: str | None = None
    message: str | None = None


class SendResult(BaseModel):
    sent: bool
    sentAt: str
    to: str | None = None


# ── Аналитика ─────────────────────────────────────────────────────
class TrendPoint(BaseModel):
    month: str
    value: int


class KpiSummary(BaseModel):
    total: int
    inspections: int
    violations: int
    compliant: int
    overdue: int
    fixed: int
    inspectedPct: float
    compliantPct: float


class DistrictStat(BaseModel):
    districtId: str
    name: str
    total: int
    violations: int
    compliant: int


# ── Прочее ────────────────────────────────────────────────────────
class Notification(BaseModel):
    id: str
    type: str
    text: str
    objectId: str | None = None
    date: str
    read: bool = False


class GeocodeResult(BaseModel):
    address: str
    street: str
    districtId: str
    microdistrictId: str


class SearchResult(BaseModel):
    objects: list[CityObject] = []


class DistrictCreate(BaseModel):
    name: str


class MicrodistrictCreate(BaseModel):
    districtId: str | None = None
    name: str


class ObjectTypeCreate(BaseModel):
    type: str
    category: str | None = None


class ChecklistTemplateItem(BaseModel):
    id: str
    key: str
    titleRu: str
    titleKz: str = ""
    category: str = ""
    sortOrder: int = 0
    isVisible: bool = True


class ChecklistTemplateManageItem(BaseModel):
    id: str | None = None
    key: str
    titleRu: str
    titleKz: str = ""
    category: str = ""
    sortOrder: int = 0
    isVisible: bool = True


class ChecklistTemplateManageRequest(BaseModel):
    items: list[ChecklistTemplateManageItem] = Field(default_factory=list)


class Street(BaseModel):
    id: str
    name: str
    districtId: str | None = None
    microdistrictId: str | None = None


class StreetCreate(BaseModel):
    name: str
    districtId: str | None = None
    microdistrictId: str | None = None


class StreetPatch(BaseModel):
    name: str | None = None
    districtId: str | None = None
    microdistrictId: str | None = None


class GeoConfig(BaseModel):
    hasDistricts: bool
    hasMicrodistricts: bool
    hasStreets: bool
    addressSchema: str
    cityType: str | None = None
    oblast: str | None = None


class GeoConfigPatch(BaseModel):
    hasDistricts: bool | None = None
    hasMicrodistricts: bool | None = None
    hasStreets: bool | None = None
    addressSchema: str | None = None
    cityType: str | None = None
    oblast: str | None = None


class CurrentCity(BaseModel):
    """Город текущего пользователя (из JWT regionId) + geo-конфиг."""

    id: str
    name: str
    code: str
    hasDistricts: bool
    hasMicrodistricts: bool
    hasStreets: bool
    addressSchema: str
    cityType: str | None = None
    oblast: str | None = None
