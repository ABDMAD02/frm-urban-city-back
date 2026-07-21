"""Загрузка сид-данных из app/store.py в PostgreSQL (идемпотентно)."""
from __future__ import annotations

from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import store as seed
from db.enums import (
    AccountStatus,
    HistoryType,
    InspectionResult,
    LegalForm,
    ObjectStatus,
    PhotoKind,
    PrescriptionStatus,
    Role,
)
from db.codes import uuid_for_code
from db import models as m


def _parse_date(s: str) -> date:
    y, mo, d = s.split("-")
    return date(int(y), int(mo), int(d))


def is_seeded(session: Session) -> bool:
    return session.scalar(select(func.count()).select_from(m.CityObject)) > 0


def run_seed(session: Session) -> None:
    if is_seeded(session):
        return

    for d in seed.DISTRICTS:
        session.add(m.District(id=d.id, name=d.name))

    for md in seed.MICRODISTRICTS:
        session.add(m.Microdistrict(id=md.id, district_id=md.districtId, name=md.name))

    for t_name, t_cat in seed.TYPES:
        session.add(m.ObjectType(name=t_name, category=t_cat))

    owner_uuid: dict[str, m.Owner] = {}
    for o in seed.OWNERS:
        row = m.Owner(
            id=uuid_for_code(o.id),
            code=o.id,
            name=o.name,
            legal_form=LegalForm(o.legalForm.value),
            bin=o.bin,
            phone=o.phone,
            email=o.email,
        )
        session.add(row)
        owner_uuid[o.id] = row

    user_uuid: dict[str, m.AppUser] = {}
    for u in seed.USERS:
        owner_id = None
        if u.role.value == "owner" and u.ownerObjectIds:
            # u2 → w2 (ИП Сапаров)
            owner_id = owner_uuid["w2"].id
        row = m.AppUser(
            id=uuid_for_code(u.id),
            code=u.id,
            name=u.name,
            role=Role(u.role.value),
            position=u.position,
            login=u.login,
            status=AccountStatus(u.status.value) if u.status else AccountStatus.active,
            owner_id=owner_id,
            created_at=_parse_date(u.createdAt or "2026-05-01"),
        )
        session.add(row)
        user_uuid[u.id] = row
        if u.microdistrictIds:
            for md_id in u.microdistrictIds:
                session.add(m.UserMicrodistrict(user_id=row.id, microdistrict_id=md_id))

    object_uuid: dict[str, m.CityObject] = {}
    for o in seed.OBJECTS:
        row = m.CityObject(
            id=uuid_for_code(o.id),
            code=o.id,
            name=o.name,
            type=o.type,
            category=o.category,
            address=o.address,
            lat=o.lat,
            lng=o.lng,
            district_id=o.districtId,
            microdistrict_id=o.microdistrictId,
            street=o.street,
            owner_id=owner_uuid[o.ownerId].id,
            status=ObjectStatus(o.status.value),
            responsible=o.responsible,
            created_at=_parse_date(o.createdAt),
            updated_at=_parse_date(o.updatedAt),
        )
        session.add(row)
        object_uuid[o.id] = row

    photo_uuid: dict[str, m.Photo] = {}
    photo_objects = {"p1": "o5", "p2": "o5", "p3": "o12", "p4": "o1", "p5": "o12", "p6": "o12"}
    for p in seed.PHOTOS:
        oid = photo_objects.get(p.id, "o1")
        row = m.Photo(
            id=uuid_for_code(p.id),
            code=p.id,
            object_id=object_uuid[oid].id,
            kind=p.kind,
            caption=p.caption,
            color=p.color or None,
            url=p.url,
            date=_parse_date(p.date),
            author=p.author,
        )
        session.add(row)
        photo_uuid[p.id] = row

    inspection_uuid: dict[str, m.Inspection] = {}
    for insp in seed.INSPECTIONS:
        row = m.Inspection(
            id=uuid_for_code(insp.id),
            code=insp.id,
            object_id=object_uuid[insp.objectId].id,
            inspector=insp.inspector,
            date=_parse_date(insp.date),
            result=insp.result,
            comment=insp.comment,
        )
        session.add(row)
        inspection_uuid[insp.id] = row
        for item in insp.checklist:
            session.add(
                m.ChecklistItem(
                    inspection_id=row.id,
                    key=item.key,
                    label=item.label,
                    value=item.value,
                    comment=item.comment,
                )
            )
        for pid in insp.photoIds:
            if pid in photo_uuid:
                photo_uuid[pid].inspection_id = row.id

    for pr in seed.PRESCRIPTIONS:
        session.add(
            m.Prescription(
                id=uuid_for_code(pr.id),
                code=pr.id,
                object_id=object_uuid[pr.objectId].id,
                inspection_id=inspection_uuid[pr.inspectionId].id,
                title=pr.title,
                description=pr.description,
                issued_at=_parse_date(pr.issuedAt),
                deadline=_parse_date(pr.deadline),
                reinspection_date=_parse_date(pr.reinspectionDate),
                status=pr.status,
            )
        )

    for h in seed.HISTORY:
        session.add(
            m.HistoryEvent(
                id=uuid_for_code(h.id),
                code=h.id,
                object_id=object_uuid[h.objectId].id,
                type=h.type,
                actor=h.actor,
                date=_parse_date(h.date),
                text=h.text,
            )
        )

    for v in seed.VERSIONS:
        session.add(
            m.ObjectVersion(
                id=uuid_for_code(v.id),
                code=v.id,
                object_id=object_uuid[v.objectId].id,
                date=_parse_date(v.date),
                author=v.author,
                label=v.label,
                changes=v.changes,
            )
        )

    session.flush()


def run_seed_cli() -> None:
    from db.base import SessionLocal

    with SessionLocal() as session:
        run_seed(session)
        session.commit()
        print("Seed completed.")


if __name__ == "__main__":
    run_seed_cli()
