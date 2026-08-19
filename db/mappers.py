"""ORM ↔ Pydantic (app/models.py). Публичный id — колонка ``code``."""
from __future__ import annotations

import logging
import uuid
from datetime import date, datetime

from app import config, models as dto
from app.domain_rules import effective_prescription_status
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

logger = logging.getLogger(__name__)


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


def user(row: orm.AppUser, *, microdistrict_ids: list[str] | None = None, street_ids: list[str] | None = None, owner_object_ids: list[str] | None = None) -> dto.User:
    return dto.User(
        id=_code(row),
        name=row.name,
        role=Role(row.role.value),
        position=row.position,
        microdistrictIds=microdistrict_ids,
        streetIds=street_ids,
        ownerObjectIds=owner_object_ids,
        login=row.login,
        status=AccountStatus(row.status.value),
        createdAt=_d(row.created_at),
        regionId=row.region_id,
        email=row.email,
        iin=row.iin,
        phone=row.phone,
        passwordChangeRequired=row.password_change_required,
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
    assigned = row.__dict__.get("assigned_urbanist")
    assigned_id = None
    assigned_name = None
    if assigned is not None:
        assigned_id = assigned.code or str(assigned.id)
        assigned_name = assigned.name
    elif getattr(row, "assigned_urbanist_id", None):
        assigned_id = str(row.assigned_urbanist_id)
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
        assignedUrbanistId=assigned_id,
        assignedUrbanistName=assigned_name,
        createdAt=_d(row.created_at),
        updatedAt=_d(row.updated_at),
    )




def _owner_public_id(row: orm.CityObject) -> str:
    """Публичный код владельца (w11) из загруженной связи; фолбэк — строка UUID."""
    if not row.owner_id:
        return "w4"
    owner = row.__dict__.get("owner")
    if owner is None:
        try:
            owner = row.owner
        except Exception as exc:
            logger.debug(
                "Lazy-load of Owner relation failed for owner_id=%s, falling back to UUID: %s: %s",
                row.owner_id,
                type(exc).__name__,
                exc,
            )
            owner = None
    if owner is not None:
        return owner.code or str(owner.id)
    return str(row.owner_id)


def _street_public_id(row: orm.CityObject) -> str | None:
    if not getattr(row, "street_id", None):
        return None
    street = row.__dict__.get("street_row")
    if street is None:
        try:
            street = row.street_row
        except Exception as exc:
            logger.debug(
                "Lazy-load of Street relation failed for street_id=%s, falling back to UUID: %s: %s",
                getattr(row, "street_id", None),
                type(exc).__name__,
                exc,
            )
            street = None
    if street is not None:
        return street.code or str(street.id)
    return str(row.street_id)


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


def checklist_item(row: orm.ChecklistItem) -> dto.ChecklistItem:
    return dto.ChecklistItem(
        key=row.key,
        label=row.label,
        value=ChecklistValue(row.value.value),
        comment=row.comment,
    )


def inspection(row: orm.Inspection, *, object_code: str, photo_ids: list[str]) -> dto.Inspection:
    inspector_user = row.__dict__.get("inspector_user")
    inspector_code = None
    if inspector_user is not None:
        inspector_code = inspector_user.code or str(inspector_user.id)
    elif row.inspector_id:
        inspector_code = str(row.inspector_id)
    return dto.Inspection(
        id=_code(row),
        objectId=object_code,
        inspector=row.inspector,
        inspectorId=inspector_code,
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
        status=effective_prescription_status(
            PrescriptionStatus(row.status.value), _d(row.deadline), config.today_str()
        ),
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
