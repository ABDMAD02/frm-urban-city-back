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


def city_object(row: orm.CityObject) -> dto.CityObject:
    return dto.CityObject(
        id=_code(row),
        name=row.name,
        type=row.type,
        category=row.category or "—",
        address=row.address or "—",
        lat=row.lat,
        lng=row.lng,
        districtId=row.district_id or "d1",
        microdistrictId=row.microdistrict_id or "m1",
        street=row.street or "—",
        ownerId=_owner_code(row.owner_id) if row.owner_id else "w4",
        status=ObjectStatus(row.status.value),
        responsible=row.responsible or "",
        createdAt=_d(row.created_at),
        updatedAt=_d(row.updated_at),
    )


# Заполняется репозиторием: owner uuid → code
_OWNER_UUID_TO_CODE: dict[uuid.UUID, str] = {}


def set_owner_code_map(mapping: dict[uuid.UUID, str]) -> None:
    global _OWNER_UUID_TO_CODE
    _OWNER_UUID_TO_CODE = mapping


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


def photo(row: orm.Photo) -> dto.Photo:
    return dto.Photo(
        id=_code(row),
        objectId=_code(row.object) if getattr(row, "object", None) is not None else None,
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
