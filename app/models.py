"""Pydantic-схемы — зеркало доменных сущностей фронта + тела запросов/ответов API."""
from __future__ import annotations
from pydantic import BaseModel, Field, EmailStr
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
    districtId: str
    name: str


# ── Пользователи и собственники ───────────────────────────────────
class User(BaseModel):
    id: str
    name: str
    role: Role
    position: str
    microdistrictIds: list[str] | None = None
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
    districtId: str
    microdistrictId: str
    street: str
    ownerId: str
    status: ObjectStatus
    responsible: str
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
    ownerId: str | None = None


class ObjectPatch(BaseModel):
    name: str | None = None
    type: str | None = None
    category: str | None = None
    address: str | None = None
    ownerId: str | None = None
    responsible: str | None = None
    status: ObjectStatus | None = None


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
    districtId: str
    name: str


class ObjectTypeCreate(BaseModel):
    type: str
    category: str | None = None
