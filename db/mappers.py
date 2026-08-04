"""ORM ↔ Pydantic (app/models.py). Публичный id — колонка ``code``."""
from __future__ import annotations

import uuid
from datetime import date, datetime

from app import models as dto
from app.enums import (
    AccountStatus,
    ChecklistValue,
    HistoryType,
    InspectionResult,
    LegalForm,
    ObjectStatus,
    PhotoKind,
    PrescriptionStatus,
    Role,
)
from db import models as orm


def _d(v: date | datetime | str | None) -> str:
    if v is None:
        return ""
    if isinstance(v, str):
        return v[:10]
    if isinstance(v, datetime):
        return v.date().isoformat()
    return v.isoformat()


def _code(row) -> str:
    return row.code or str(row.id)


def district(row: orm.District) -> dto.District:
    return dto.District(id=row.id, name=row.name)


def microdistrict(row: orm.Microdistrict) -> dto.Microdistrict:
    return dto.Microdistrict(id=row.id, districtId=row.district_id, name=row.name)


def owner(row: orm.Owner, *, owner_user_id: str | None = None) -> dto.Owner:
    return dto.Owner(
        id=_code(row),
        name=row.name,
        legalForm=LegalForm(row.legal_form.value),
        bin=row.bin,
        phone=row.phone,
        email=row.email,
        ownerUserId=owner_user_id,
    )


def user(row: orm.AppUser, *, microdistrict_ids: list[str] | None = None, owner_object_ids: list[str] | None = None) -> dto.User:
    return dto.User(
        id=_code(row),
        name=row.name,
        role=Role(row.role.value),
        position=row.position,
        microdistrictIds=microdistrict_ids,
        ownerObjectIds=owner_object_ids,
        login=row.login,
        status=AccountStatus(row.status.value),
        createdAt=_d(row.created_at),
        regionId=row.region_id,
        email=row.email,
    )


def city_object(
    row: orm.CityObject,
    *,
    owner_id: str | None = None,
    street_id: str | None = None,
) -> dto.CityObject:
    """Map ORM → API. Public owner/street ids are short codes (w11), never raw UUIDs."""
    if owner_id is None:
        owner_id = _owner_public_id(row)
    if street_id is None and getattr(row, "street_id", None):
        street_id = _street_public_id(row)
    return dto.CityObject(
        id=_code(row),
        name=row.name,
        type=row.type,
        category=row.category or "—",
        address=row.address or "—",
        lat=row.lat,
        lng=row.lng,
        districtId=row.district_id,
        microdistrictId=row.microdistrict_id,
        street=row.street,
        streetId=street_id,
        house=getattr(row, "house", None),
        apartment=getattr(row, "apartment", None),
        ownerId=owner_id,
        status=ObjectStatus(row.status.value),
        responsible=row.responsible or "",
        createdAt=_d(row.created_at),
        updatedAt=_d(row.updated_at),
    )


# Заполняется репозиторием: owner uuid → code
_OWNER_UUID_TO_CODE: dict[uuid.UUID, str] = {}
_STREET_UUID_TO_CODE: dict[uuid.UUID, str] = {}


def set_owner_code_map(mapping: dict[uuid.UUID, str]) -> None:
    global _OWNER_UUID_TO_CODE
    _OWNER_UUID_TO_CODE = mapping


def set_street_code_map(mapping: dict[uuid.UUID, str]) -> None:
    global _STREET_UUID_TO_CODE
    _STREET_UUID_TO_CODE = mapping


def _street_code(uid: uuid.UUID | None) -> str | None:
    if uid is None:
        return None
    return _STREET_UUID_TO_CODE.get(uid) or str(uid)


def _owner_public_id(row: orm.CityObject) -> str:
    """Prefer Owner.code via relationship; fall back to module map / UUID string."""
    if not row.owner_id:
        return "w4"
    owner = row.__dict__.get("owner")
    if owner is None:
        try:
            owner = row.owner
        except Exception:
            owner = None
    if owner is not None:
        return owner.code or str(owner.id)
    return _owner_code(row.owner_id)


def _street_public_id(row: orm.CityObject) -> str | None:
    if not getattr(row, "street_id", None):
        return None
    street = row.__dict__.get("street_row")
    if street is None:
        try:
            street = row.street_row
        except Exception:
            street = None
    if street is not None:
        return street.code or str(street.id)
    return _street_code(row.street_id)


def checklist_template(row: orm.ChecklistTemplate) -> dto.ChecklistTemplateItem:
    return dto.ChecklistTemplateItem(
        id=str(row.id),
        key=row.key,
        titleRu=row.title_ru,
        titleKz=row.title_kz or "",
        category=row.category or "",
        sortOrder=row.sort_order,
        isVisible=row.is_visible,
    )


def street(row: orm.Street) -> dto.Street:
    return dto.Street(
        id=_code(row),
        name=row.name,
        districtId=row.district_id,
        microdistrictId=row.microdistrict_id,
    )


def _owner_code(uid: uuid.UUID | None) -> str:
    if uid is None:
        return "w4"
    return _OWNER_UUID_TO_CODE.get(uid, str(uid))


def checklist_item(row: orm.ChecklistItem) -> dto.ChecklistItem:
    return dto.ChecklistItem(
        key=row.key,
        label=row.label,
        value=ChecklistValue(row.value.value),
        comment=row.comment,
    )


def inspection(row: orm.Inspection, *, object_code: str, photo_ids: list[str]) -> dto.Inspection:
    return dto.Inspection(
        id=_code(row),
        objectId=object_code,
        inspector=row.inspector,
        date=_d(row.date),
        result=InspectionResult(row.result.value),
        checklist=[checklist_item(c) for c in row.checklist],
        comment=row.comment,
        photoIds=photo_ids,
    )


def prescription(row: orm.Prescription, *, object_code: str, inspection_code: str) -> dto.Prescription:
    return dto.Prescription(
        id=_code(row),
        objectId=object_code,
        inspectionId=inspection_code,
        title=row.title,
        description=row.description,
        issuedAt=_d(row.issued_at),
        deadline=_d(row.deadline),
        reinspectionDate=_d(row.reinspection_date),
        status=PrescriptionStatus(row.status.value),
    )


def photo(row: orm.Photo, *, object_code: str | None = None) -> dto.Photo:
    return dto.Photo(
        id=_code(row),
        objectId=object_code,
        kind=PhotoKind(row.kind.value),
        caption=row.caption or "",
        color=row.color or "",
        url=row.url,
        date=_d(row.date),
        author=row.author,
    )


def history_event(row: orm.HistoryEvent, *, object_code: str) -> dto.HistoryEvent:
    return dto.HistoryEvent(
        id=_code(row),
        objectId=object_code,
        type=HistoryType(row.type.value),
        actor=row.actor,
        date=_d(row.date),
        text=row.text,
    )


def object_version(row: orm.ObjectVersion, *, object_code: str) -> dto.ObjectVersion:
    return dto.ObjectVersion(
        id=_code(row),
        objectId=object_code,
        date=_d(row.date),
        author=row.author,
        label=row.label,
        changes=list(row.changes or []),
    )
